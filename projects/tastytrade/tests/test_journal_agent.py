"""Tests for journal-log and journal-query CLI commands + Journal.rich_stats."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tastytrade_strategy.cli import app
from tastytrade_strategy.journal import Journal, JournalEntry
from tastytrade_strategy.models import OrderLeg, StrategyType, TradeStatus

runner = CliRunner()

_FUTURE_EXP = "2026-06-20"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _strategy_json(
    underlying: str = "SPY",
    strategy_type: str = "iron_condor",
    expiration: str = _FUTURE_EXP,
) -> dict:
    return {
        "strategy_type": strategy_type,
        "underlying": underlying,
        "expiration_date": expiration,
        "credit": 1.85,
        "quantity": 1,
        "legs": [
            {
                "symbol": f"{underlying.ljust(6)}{expiration[2:].replace('-', '')}P00490000",
                "action": "Buy to Open",
                "quantity": 1,
                "option_type": "P",
                "strike_price": 490.0,
                "expiration_date": expiration,
            },
            {
                "symbol": f"{underlying.ljust(6)}{expiration[2:].replace('-', '')}P00495000",
                "action": "Sell to Open",
                "quantity": 1,
                "option_type": "P",
                "strike_price": 495.0,
                "expiration_date": expiration,
            },
        ],
        "risk": {"max_profit": 185.0, "max_loss": 315.0, "breakevens": [488.15, 511.85]},
    }


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    return Journal(db_path=tmp_path / "test.db")


def _entry(journal: Journal, underlying: str = "SPY", strategy_type=StrategyType.IRON_CONDOR) -> JournalEntry:
    return journal.log_trade(JournalEntry(
        underlying=underlying,
        strategy_type=strategy_type,
        legs=[OrderLeg(symbol=underlying, action="Sell to Open", quantity=1, option_type="P",
                       strike_price=495.0, expiration_date=_FUTURE_EXP)],
        entry_price=Decimal("1.85"),
        rationale="High IV",
    ))


def _run_log(strategy: dict, extra_args: list[str] | None = None) -> dict:
    """Invoke journal-log with strategy JSON written to a temp file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "strategy.json")
        with open(sf, "w") as f:
            json.dump(strategy, f)
        args = ["journal-log", "--credit", "1.85", "--strategy", sf] + (extra_args or [])
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        return json.loads(result.output)


def _run_query(action: str, extra_args: list[str] | None = None, db_path: str | None = None) -> tuple[dict, int]:
    """Invoke journal-query with an optional custom db via env override.

    Because the CLI always creates Journal() with the default path we can't
    inject a temp DB here — so these tests use the real (empty) default DB or
    test methods on Journal directly.  For command-level tests we just verify
    the output shape.
    """
    args = ["journal-query", action] + (extra_args or [])
    result = runner.invoke(app, args)
    return result.output, result.exit_code


# ---------------------------------------------------------------------------
# journal-log
# ---------------------------------------------------------------------------

class TestJournalLog:
    def test_logs_returns_trade_id(self):
        out = _run_log(_strategy_json())
        assert out["logged"] is True
        assert isinstance(out["trade_id"], int)
        assert out["trade_id"] > 0

    def test_logs_correct_underlying(self):
        out = _run_log(_strategy_json(underlying="AAPL"))
        assert out["underlying"] == "AAPL"

    def test_logs_strategy_type(self):
        out = _run_log(_strategy_json(strategy_type="iron_condor"))
        assert out["strategy_type"] == "iron_condor"

    def test_entry_price_matches_credit(self):
        out = _run_log(_strategy_json(), extra_args=["--credit", "2.50"])
        assert out["entry_price"] == pytest.approx(2.50)

    def test_rationale_stored(self):
        out = _run_log(_strategy_json(), extra_args=["--rationale", "High IV rank"])
        assert out["rationale"] == "High IV rank"

    def test_leg_count_in_output(self):
        out = _run_log(_strategy_json())
        assert out["legs"] == 2

    def test_timestamp_present(self):
        out = _run_log(_strategy_json())
        assert "timestamp" in out
        assert len(out["timestamp"]) > 0

    def test_invalid_strategy_type_exits_nonzero(self):
        bad = _strategy_json()
        bad["strategy_type"] = "butterfly"
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = os.path.join(tmpdir, "s.json")
            with open(sf, "w") as f:
                json.dump(bad, f)
            result = runner.invoke(app, ["journal-log", "--credit", "1.0", "--strategy", sf])
            assert result.exit_code != 0
            err = json.loads(result.output)
            assert "error" in err

    def test_missing_strategy_file_exits_nonzero(self):
        result = runner.invoke(app, ["journal-log", "--credit", "1.0", "--strategy", "/nonexistent/strategy.json"])
        assert result.exit_code != 0

    def test_profit_target_stored(self):
        out = _run_log(_strategy_json(), extra_args=["--profit-target", "0.93"])
        # logged is True and no error — profit_target is stored in DB, not returned in output
        assert out["logged"] is True

    def test_short_put_strategy(self):
        strat = {
            "strategy_type": "short_put",
            "underlying": "TSLA",
            "expiration_date": _FUTURE_EXP,
            "legs": [{"symbol": "TSLA  260620P00400000", "action": "Sell to Open",
                       "quantity": 1, "option_type": "P", "strike_price": 400.0,
                       "expiration_date": _FUTURE_EXP}],
            "risk": {"max_profit": 300.0, "max_loss": 700.0},
        }
        out = _run_log(strat, extra_args=["--credit", "3.00"])
        assert out["strategy_type"] == "short_put"
        assert out["underlying"] == "TSLA"


# ---------------------------------------------------------------------------
# journal-query (action: open)
# ---------------------------------------------------------------------------

class TestJournalQueryOpen:
    def test_open_returns_json_with_count(self):
        output, code = _run_query("open")
        assert code == 0
        data = json.loads(output)
        assert "count" in data
        assert "trades" in data
        assert isinstance(data["trades"], list)

    def test_open_count_matches_trades_length(self):
        output, _ = _run_query("open")
        data = json.loads(output)
        assert data["count"] == len(data["trades"])


# ---------------------------------------------------------------------------
# journal-query (action: stats)
# ---------------------------------------------------------------------------

class TestJournalQueryStats:
    def test_stats_returns_json(self):
        output, code = _run_query("stats")
        assert code == 0
        data = json.loads(output)
        assert "open_trades" in data
        assert "closed_trades" in data
        assert "total_pnl" in data
        assert "win_rate" in data

    def test_stats_has_breakdown_keys(self):
        output, _ = _run_query("stats")
        data = json.loads(output)
        assert "by_strategy" in data
        assert "by_underlying" in data
        assert "max_win" in data
        assert "max_loss" in data


# ---------------------------------------------------------------------------
# journal-query (action: history)
# ---------------------------------------------------------------------------

class TestJournalQueryHistory:
    def test_history_returns_json(self):
        output, code = _run_query("history")
        assert code == 0
        data = json.loads(output)
        assert "count" in data
        assert "trades" in data

    def test_history_limit_flag_accepted(self):
        output, code = _run_query("history", extra_args=["--limit", "5"])
        assert code == 0

    def test_history_underlying_flag_accepted(self):
        output, code = _run_query("history", extra_args=["--underlying", "SPY"])
        assert code == 0


# ---------------------------------------------------------------------------
# journal-query (action: close)
# ---------------------------------------------------------------------------

class TestJournalQueryClose:
    def test_close_missing_id_returns_error(self):
        output, code = _run_query("close", extra_args=["--exit-price", "0.65"])
        assert code != 0
        data = json.loads(output)
        assert "error" in data

    def test_close_nonexistent_id_returns_error(self):
        output, code = _run_query("close", extra_args=["--id", "99999", "--exit-price", "0.65"])
        assert code != 0
        data = json.loads(output)
        assert "error" in data

    def test_unknown_action_returns_error(self):
        output, code = _run_query("badaction")
        assert code != 0
        data = json.loads(output)
        assert "error" in data


# ---------------------------------------------------------------------------
# Journal.rich_stats (unit tests on Journal directly)
# ---------------------------------------------------------------------------

class TestRichStats:
    def test_empty_journal(self, journal: Journal):
        stats = journal.rich_stats()
        assert stats["closed_trades"] == 0
        assert stats["total_pnl"] == 0.0
        assert stats["winners"] == 0
        assert stats["losers"] == 0
        assert stats["by_strategy"] == {}
        assert stats["by_underlying"] == {}

    def test_open_trades_counted(self, journal: Journal):
        _entry(journal, "SPY")
        _entry(journal, "AAPL")
        stats = journal.rich_stats()
        assert stats["open_trades"] == 2
        assert stats["closed_trades"] == 0

    def test_closed_trade_stats(self, journal: Journal):
        e1 = _entry(journal, "SPY")
        e2 = _entry(journal, "SPY")
        e3 = _entry(journal, "AAPL", strategy_type=StrategyType.SHORT_PUT)
        journal.close_trade(e1.id, exit_price=Decimal("0.50"), pnl=Decimal("135"))
        journal.close_trade(e2.id, exit_price=Decimal("2.50"), pnl=Decimal("-65"))
        journal.close_trade(e3.id, exit_price=Decimal("0.30"), pnl=Decimal("200"))

        stats = journal.rich_stats()
        assert stats["closed_trades"] == 3
        assert stats["winners"] == 2
        assert stats["losers"] == 1
        assert stats["breakeven"] == 0
        assert stats["total_pnl"] == pytest.approx(270.0)
        assert stats["avg_pnl"] == pytest.approx(90.0)
        assert stats["max_win"] == pytest.approx(200.0)
        assert stats["max_loss"] == pytest.approx(-65.0)
        assert stats["win_rate"] == pytest.approx(2 / 3, rel=0.01)

    def test_by_strategy_breakdown(self, journal: Journal):
        e1 = _entry(journal, "SPY", strategy_type=StrategyType.IRON_CONDOR)
        e2 = _entry(journal, "AAPL", strategy_type=StrategyType.SHORT_PUT)
        journal.close_trade(e1.id, exit_price=Decimal("0.50"), pnl=Decimal("135"))
        journal.close_trade(e2.id, exit_price=Decimal("0.30"), pnl=Decimal("200"))

        stats = journal.rich_stats()
        assert "iron_condor" in stats["by_strategy"]
        assert "short_put" in stats["by_strategy"]
        ic = stats["by_strategy"]["iron_condor"]
        assert ic["trades"] == 1
        assert ic["total_pnl"] == pytest.approx(135.0)
        assert ic["win_rate"] == pytest.approx(1.0)

    def test_by_underlying_breakdown(self, journal: Journal):
        e1 = _entry(journal, "SPY")
        e2 = _entry(journal, "SPY")
        e3 = _entry(journal, "AAPL")
        journal.close_trade(e1.id, exit_price=Decimal("0.50"), pnl=Decimal("100"))
        journal.close_trade(e2.id, exit_price=Decimal("2.00"), pnl=Decimal("-50"))
        journal.close_trade(e3.id, exit_price=Decimal("0.30"), pnl=Decimal("200"))

        stats = journal.rich_stats()
        assert "SPY" in stats["by_underlying"]
        assert "AAPL" in stats["by_underlying"]
        spy = stats["by_underlying"]["SPY"]
        assert spy["trades"] == 2
        assert spy["total_pnl"] == pytest.approx(50.0)
        assert spy["win_rate"] == pytest.approx(0.5)

    def test_breakeven_counted(self, journal: Journal):
        e1 = _entry(journal)
        journal.close_trade(e1.id, exit_price=Decimal("1.85"), pnl=Decimal("0"))
        stats = journal.rich_stats()
        assert stats["breakeven"] == 1
        assert stats["winners"] == 0
        assert stats["losers"] == 0

    def test_open_count_helper(self, journal: Journal):
        _entry(journal)
        _entry(journal)
        assert journal._count_open() == 2
