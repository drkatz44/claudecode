"""Tests for the risk-agent CLI command and enriched portfolio_from_positions."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from tastytrade_strategy.cli import app
from tastytrade_strategy.risk import PortfolioSnapshot, portfolio_from_positions

runner = CliRunner()

_FUTURE_EXP = (date.today() + timedelta(days=45)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# portfolio_from_positions enhancements
# ---------------------------------------------------------------------------

class TestPortfolioFromPositions:
    def test_unwraps_api_envelope(self):
        balances = {"data": {"net-liquidating-value": "100000", "derivative-buying-power": "50000"}}
        portfolio = portfolio_from_positions([], balances)
        assert portfolio.net_liquidating_value == Decimal("100000")
        assert portfolio.buying_power == Decimal("50000")

    def test_bp_fallback_hierarchy(self):
        """Falls back to equity-buying-power when derivative is absent."""
        balances = {"net-liquidating-value": "100000", "equity-buying-power": "40000"}
        portfolio = portfolio_from_positions([], balances)
        assert portfolio.buying_power == Decimal("40000")

    def test_quantity_direction_short(self):
        """Short positions get negative quantity."""
        positions = [
            {"underlying-symbol": "SPY", "quantity": "5", "quantity-direction": "Short", "mark": "10.0"},
        ]
        portfolio = portfolio_from_positions(positions, {"net-liquidating-value": "0", "derivative-buying-power": "0"})
        assert portfolio.positions[0].quantity == -5

    def test_quantity_direction_long(self):
        positions = [
            {"underlying-symbol": "AAPL", "quantity": "3", "quantity-direction": "Long", "mark": "150.0"},
        ]
        portfolio = portfolio_from_positions(positions, {"net-liquidating-value": "0", "derivative-buying-power": "0"})
        assert portfolio.positions[0].quantity == 3

    def test_mark_price_fallback(self):
        """Falls back to mark-price then close-price."""
        positions = [{"underlying-symbol": "X", "quantity": "1", "mark-price": "25.0"}]
        portfolio = portfolio_from_positions(positions, {"net-liquidating-value": "0"})
        assert portfolio.positions[0].mark == Decimal("25.0")

    def test_missing_fields_default_to_zero(self):
        portfolio = portfolio_from_positions([{"symbol": "X"}], {})
        assert portfolio.net_liquidating_value == Decimal("0")
        assert portfolio.buying_power == Decimal("0")


# ---------------------------------------------------------------------------
# risk-agent CLI command
# ---------------------------------------------------------------------------

def _occ(underlying: str, expiration: str, side: str, strike: int) -> str:
    """Build a proper OCC symbol: root(6 padded) + yymmdd + P/C + strike*1000(8 digits)."""
    root = underlying.ljust(6)
    ymd = expiration[2:].replace("-", "")  # YYYY-MM-DD → YYMMDD
    return f"{root}{ymd}{side}{strike * 1000:08d}"


def _strategy_json(
    underlying: str = "SPY",
    strategy_type: str = "iron_condor",
    max_profit: float = 185.0,
    max_loss: float = 315.0,
    expiration: str | None = None,
) -> dict:
    if expiration is None:
        expiration = _FUTURE_EXP
    return {
        "strategy_type": strategy_type,
        "underlying": underlying,
        "expiration_date": expiration,
        "credit": 1.85,
        "quantity": 1,
        "legs": [
            {"symbol": _occ(underlying, expiration, "P", 490), "action": "Buy to Open",  "quantity": 1, "option_type": "P", "strike_price": 490.0, "expiration_date": expiration},
            {"symbol": _occ(underlying, expiration, "P", 495), "action": "Sell to Open", "quantity": 1, "option_type": "P", "strike_price": 495.0, "expiration_date": expiration},
            {"symbol": _occ(underlying, expiration, "C", 505), "action": "Sell to Open", "quantity": 1, "option_type": "C", "strike_price": 505.0, "expiration_date": expiration},
            {"symbol": _occ(underlying, expiration, "C", 510), "action": "Buy to Open",  "quantity": 1, "option_type": "C", "strike_price": 510.0, "expiration_date": expiration},
        ],
        "risk": {"max_profit": max_profit, "max_loss": max_loss, "breakevens": [488.15, 511.85], "risk_reward_ratio": 1.7},
    }


def _portfolio_json(nlv: float = 100000.0, bp: float = 50000.0, positions: list | None = None) -> dict:
    return {
        "positions": positions or [],
        "balances": {"net-liquidating-value": str(nlv), "derivative-buying-power": str(bp)},
    }


class TestRiskAgentCommand:
    def _run(self, portfolio: dict, strategy: dict, extra_args: list[str] | None = None, tmp_path=None) -> dict:
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            pf = os.path.join(tmpdir, "portfolio.json")
            sf = os.path.join(tmpdir, "strategy.json")
            with open(pf, "w") as f:
                json.dump(portfolio, f)
            with open(sf, "w") as f:
                json.dump(strategy, f)
            args = [pf, "--strategy", sf] + (extra_args or [])
            result = runner.invoke(app, ["risk-agent"] + args)
            assert result.exit_code == 0, result.output
            return json.loads(result.output)

    def test_approved_within_limits(self):
        out = self._run(
            _portfolio_json(nlv=100000, bp=50000),
            _strategy_json(max_loss=3000),
        )
        assert out["approved"] is True
        assert out["violations"] == []
        assert "APPROVED" in out["summary"]

    def test_position_size_violation(self):
        out = self._run(
            _portfolio_json(nlv=100000, bp=50000),
            _strategy_json(max_loss=10000),
        )
        assert out["approved"] is False
        assert any("Position risk" in v for v in out["violations"])

    def test_bp_violation(self):
        out = self._run(
            _portfolio_json(nlv=200000, bp=50000),
            _strategy_json(max_loss=30000),
        )
        assert out["approved"] is False
        assert any("BP usage" in v for v in out["violations"])

    def test_dte_violation(self):
        out = self._run(
            _portfolio_json(),
            _strategy_json(expiration="2020-01-01"),
        )
        assert out["approved"] is False
        assert any("DTE" in v for v in out["violations"])

    def test_checks_dict_populated(self):
        out = self._run(
            _portfolio_json(nlv=100000, bp=50000),
            _strategy_json(max_loss=3000),
        )
        checks = out["checks"]
        assert checks["position_size_pct"] == pytest.approx(0.03, rel=0.01)
        assert checks["position_size_limit"] == 0.05
        assert checks["dte"] is not None
        assert checks["dte"] > 0
        assert checks["correlated_positions"] == 0

    def test_custom_rules(self):
        out = self._run(
            _portfolio_json(nlv=100000, bp=50000),
            _strategy_json(max_loss=8000),
            extra_args=["--max-position-pct", "0.10", "--max-bp-pct", "0.80"],
        )
        assert out["approved"] is True

    def test_correlated_positions_counted(self):
        portfolio = _portfolio_json(
            nlv=100000, bp=50000,
            positions=[
                {"underlying-symbol": "SPY", "quantity": "1", "quantity-direction": "Short", "mark": "3.0"},
                {"underlying-symbol": "SPY", "quantity": "1", "quantity-direction": "Short", "mark": "3.0"},
                {"underlying-symbol": "SPY", "quantity": "1", "quantity-direction": "Short", "mark": "3.0"},
            ]
        )
        out = self._run(portfolio, _strategy_json(underlying="SPY", max_loss=3000))
        assert out["checks"]["correlated_positions"] == 3
        assert out["approved"] is False

    def test_strategy_and_portfolio_in_output(self):
        out = self._run(
            _portfolio_json(nlv=100000, bp=50000),
            _strategy_json(max_loss=3000, max_profit=185),
        )
        assert out["strategy"]["underlying"] == "SPY"
        assert out["strategy"]["max_loss"] == 3000.0
        assert out["portfolio"]["nlv"] == 100000.0
        assert out["portfolio"]["buying_power"] == 50000.0
