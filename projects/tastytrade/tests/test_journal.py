"""Tests for the trade journal module."""

from decimal import Decimal
from pathlib import Path

import pytest

from tastytrade_strategy.journal import Journal, JournalEntry
from tastytrade_strategy.models import OrderLeg, StrategyType, TradeStatus


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    """Create a journal with a temporary database."""
    return Journal(db_path=tmp_path / "test_journal.db")


def _entry(**kwargs) -> JournalEntry:
    defaults = {
        "underlying": "SPY",
        "strategy_type": StrategyType.SHORT_PUT,
        "legs": [
            OrderLeg(
                symbol="SPY",
                action="Sell to Open",
                quantity=1,
                option_type="P",
                strike_price=450.0,
                expiration_date="2025-03-21",
            )
        ],
        "entry_price": Decimal("2.50"),
        "rationale": "High IV rank, support at 440",
    }
    defaults.update(kwargs)
    return JournalEntry(**defaults)


class TestLogTrade:
    def test_creates_entry_with_id(self, journal: Journal):
        entry = journal.log_trade(_entry())
        assert entry.id is not None
        assert entry.id > 0

    def test_preserves_fields(self, journal: Journal):
        entry = journal.log_trade(_entry(rationale="test rationale"))
        trades = journal.get_open_trades()
        assert len(trades) == 1
        assert trades[0].rationale == "test rationale"
        assert trades[0].underlying == "SPY"
        assert trades[0].strategy_type == StrategyType.SHORT_PUT

    def test_preserves_legs(self, journal: Journal):
        journal.log_trade(_entry())
        trades = journal.get_open_trades()
        assert len(trades[0].legs) == 1
        leg = trades[0].legs[0]
        assert leg.symbol == "SPY"
        assert leg.action == "Sell to Open"
        assert leg.strike_price == 450.0


class TestCloseTrade:
    def test_closes_trade(self, journal: Journal):
        entry = journal.log_trade(_entry())
        closed = journal.close_trade(entry.id, exit_price=Decimal("1.00"), pnl=Decimal("150"))
        assert closed is not None
        assert closed.status == TradeStatus.CLOSED
        assert closed.exit_price == Decimal("1.00")
        assert closed.pnl == Decimal("150")

    def test_only_closes_open_trades(self, journal: Journal):
        entry = journal.log_trade(_entry())
        journal.close_trade(entry.id, exit_price=Decimal("1.00"), pnl=Decimal("150"))
        # Try to close again — should not change anything
        result = journal.close_trade(entry.id, exit_price=Decimal("0.50"), pnl=Decimal("200"))
        assert result is not None
        assert result.pnl == Decimal("150")  # original close values preserved


class TestGetOpenTrades:
    def test_returns_only_open(self, journal: Journal):
        e1 = journal.log_trade(_entry(underlying="AAPL"))
        journal.log_trade(_entry(underlying="SPY"))
        journal.close_trade(e1.id, exit_price=Decimal("1"), pnl=Decimal("100"))
        open_trades = journal.get_open_trades()
        assert len(open_trades) == 1
        assert open_trades[0].underlying == "SPY"


class TestGetHistory:
    def test_returns_all(self, journal: Journal):
        journal.log_trade(_entry(underlying="AAPL"))
        journal.log_trade(_entry(underlying="SPY"))
        history = journal.get_history()
        assert len(history) == 2

    def test_filter_by_underlying(self, journal: Journal):
        journal.log_trade(_entry(underlying="AAPL"))
        journal.log_trade(_entry(underlying="SPY"))
        history = journal.get_history(underlying="AAPL")
        assert len(history) == 1
        assert history[0].underlying == "AAPL"

    def test_limit(self, journal: Journal):
        for i in range(10):
            journal.log_trade(_entry(underlying=f"SYM{i}"))
        history = journal.get_history(limit=3)
        assert len(history) == 3


class TestSummaryStats:
    def test_empty_journal(self, journal: Journal):
        stats = journal.summary_stats()
        assert stats["total_trades"] == 0
        assert stats["total_pnl"] == Decimal("0")

    def test_with_closed_trades(self, journal: Journal):
        e1 = journal.log_trade(_entry(underlying="AAPL"))
        e2 = journal.log_trade(_entry(underlying="SPY"))
        e3 = journal.log_trade(_entry(underlying="GOOG"))
        journal.close_trade(e1.id, exit_price=Decimal("1"), pnl=Decimal("150"))
        journal.close_trade(e2.id, exit_price=Decimal("3"), pnl=Decimal("-50"))
        journal.close_trade(e3.id, exit_price=Decimal("0.5"), pnl=Decimal("200"))

        stats = journal.summary_stats()
        assert stats["total_trades"] == 3
        assert stats["total_pnl"] == Decimal("300")
        assert stats["winners"] == 2
        assert stats["losers"] == 1

    def test_win_rate(self, journal: Journal):
        e1 = journal.log_trade(_entry())
        e2 = journal.log_trade(_entry())
        journal.close_trade(e1.id, exit_price=Decimal("1"), pnl=Decimal("100"))
        journal.close_trade(e2.id, exit_price=Decimal("1"), pnl=Decimal("-50"))
        stats = journal.summary_stats()
        assert stats["win_rate"] == Decimal("0.5")
