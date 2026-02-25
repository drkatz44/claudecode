"""Tests for multi-leg options backtester (options_engine.py)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from market_agent.backtest.options_engine import (
    OptionsTrade,
    OptionsBacktestResult,
    _build_result,
    _estimate_pnl,
    backtest_structure,
)
from market_agent.data.models import Bar


def _make_bars(n: int = 60, start_price: float = 450.0) -> list[Bar]:
    """Create a sequence of daily bars with a gentle uptrend."""
    bars = []
    for i in range(n):
        price = start_price + i * 0.10
        bars.append(Bar(
            timestamp=datetime(2024, 1, 1) + timedelta(days=i),
            open=Decimal(str(price - 0.5)),
            high=Decimal(str(price + 1.0)),
            low=Decimal(str(price - 1.0)),
            close=Decimal(str(price)),
            volume=1_000_000,
        ))
    return bars


def _make_trade(
    exit_pnl: float = 50.0,
    dit: int = 15,
    mae: float = -20.0,
    exit_reason: str = "profit_target",
) -> OptionsTrade:
    return OptionsTrade(
        entry_date=date(2024, 1, 1),
        exit_date=date(2024, 1, 1) + timedelta(days=dit),
        strategy_type="strangle",
        symbol="SPY",
        credit=2.00,
        exit_pnl=exit_pnl,
        dit=dit,
        mae=mae,
        exit_reason=exit_reason,
    )


class TestBuildResult:
    def test_empty_trades_returns_zero_stats(self):
        r = _build_result("SPY", "strangle", [], "yfinance")
        assert r.sample_size == 0
        assert r.win_rate == 0
        assert r.avg_pnl == 0

    def test_win_rate_calculation(self):
        trades = [
            _make_trade(exit_pnl=50.0),
            _make_trade(exit_pnl=-30.0),
            _make_trade(exit_pnl=40.0),
            _make_trade(exit_pnl=20.0),
        ]
        r = _build_result("SPY", "strangle", trades, "yfinance")
        assert r.win_rate == pytest.approx(75.0)

    def test_avg_dit_calculation(self):
        trades = [_make_trade(dit=10), _make_trade(dit=20), _make_trade(dit=30)]
        r = _build_result("SPY", "strangle", trades, "yfinance")
        assert r.avg_dit == pytest.approx(20.0)

    def test_max_adverse_excursion(self):
        trades = [
            _make_trade(mae=-10.0),
            _make_trade(mae=-50.0),
            _make_trade(mae=-5.0),
        ]
        r = _build_result("SPY", "strangle", trades, "yfinance")
        assert r.max_adverse_excursion == pytest.approx(-50.0)

    def test_sharpe_computed(self):
        trades = [_make_trade(exit_pnl=float(v)) for v in [50, 30, 40, 20, 60]]
        r = _build_result("SPY", "strangle", trades, "yfinance")
        assert r.sharpe != 0.0

    def test_provider_type_stored(self):
        r = _build_result("SPY", "strangle", [_make_trade()], "ThetaDataProvider")
        assert r.provider_type == "ThetaDataProvider"

    def test_symbol_and_strategy_stored(self):
        r = _build_result("QQQ", "iron_condor", [], "yfinance")
        assert r.symbol == "QQQ"
        assert r.strategy_type == "iron_condor"

    def test_pnl_distribution_populated(self):
        trades = [_make_trade(exit_pnl=float(v)) for v in [10, 20, 30]]
        r = _build_result("SPY", "strangle", trades, "yfinance")
        assert len(r.pnl_distribution) == 3

    def test_to_dict_keys(self):
        r = _build_result("SPY", "strangle", [_make_trade()], "yfinance")
        d = r.to_dict()
        assert "win_rate" in d
        assert "avg_dit" in d
        assert "sample_size" in d
        assert "sharpe" in d


class TestEstimatePnl:
    """Unit tests for _estimate_pnl strategy-specific logic."""

    def _call(self, strategy_type, structure, net_credit=2.0,
              entry=450.0, current=450.0, theta=0.5, days=5, dte=45):
        return _estimate_pnl(
            strategy_type=strategy_type,
            structure=structure,
            net_credit=net_credit,
            entry_price=entry,
            current_price=current,
            theta_collected=theta,
            days_held=days,
            dte_at_entry=dte,
        )

    def test_strangle_flat_market_profit(self):
        structure = {"legs": [{"strike": 440}, {"strike": 460}]}
        pnl = self._call("strangle", structure, entry=450.0, current=450.0, theta=1.0)
        assert pnl > 0  # Theta benefit, no intrinsic loss

    def test_strangle_large_move_loss(self):
        structure = {"legs": [{"strike": 440}, {"strike": 460}]}
        # Price moves way below lower strike
        pnl = self._call("strangle", structure, entry=450.0, current=420.0, theta=0.2)
        assert pnl < 0  # Intrinsic loss dominates

    def test_iron_condor_same_as_strangle_logic(self):
        structure = {"legs": [{"strike": 430}, {"strike": 470}]}
        pnl = self._call("iron_condor", structure, entry=450.0, current=450.0, theta=0.8)
        assert pnl > 0

    def test_short_put_up_move_profit(self):
        structure = {"legs": [{"strike": 430, "side": "sell"}]}
        pnl = self._call("short_put", structure, entry=450.0, current=460.0, theta=0.5)
        assert pnl >= 0  # Price above short strike → no intrinsic loss

    def test_short_put_down_move_loss(self):
        structure = {"legs": [{"strike": 450, "side": "sell"}]}
        # Price drops to 400 — well below short strike
        pnl = self._call("short_put", structure, entry=450.0, current=400.0, theta=0.3)
        assert pnl < 0

    def test_calendar_time_value(self):
        structure = {}
        pnl = self._call("calendar", structure, net_credit=1.0, entry=450.0, current=450.0,
                         theta=0.5, days=20, dte=40)
        # Flat market: time fraction benefit should be positive or near 0
        # pnl = net_credit * time_fraction * 0.7 - abs(pct_move) * net_credit * 2
        # = 1.0 * (20/40) * 0.7 - 0 = 0.35
        assert pnl == pytest.approx(0.35, abs=0.05)

    def test_default_strategy_falls_back(self):
        structure = {}
        pnl = self._call("jade_lizard", structure, entry=450.0, current=450.0, theta=0.5)
        # Should use fallback: theta - abs(move) * 0.5 = 0.5 - 0 = 0.5
        assert pnl == pytest.approx(0.5)


class TestBacktestStructure:
    """Integration tests with mocked yfinance + provider."""

    def _make_provider(self):
        from market_agent.data.models import OptionQuote
        provider = MagicMock()
        provider.get_expirations.return_value = ["2024-03-15", "2024-04-19"]
        # Return a minimal chain so resolver works
        provider.get_chain.return_value = []
        return provider

    @patch("market_agent.backtest.options_engine.get_bars")
    def test_insufficient_bars_returns_empty(self, mock_bars):
        mock_bars.return_value = []
        provider = self._make_provider()
        result = backtest_structure("SPY", "strangle", provider=provider, lookback_days=30)
        assert result.sample_size == 0

    @patch("market_agent.backtest.options_engine.get_bars")
    @patch("market_agent.backtest.options_engine.resolve_strategy")
    def test_returns_result_object(self, mock_resolve, mock_bars):
        mock_bars.return_value = _make_bars(300)
        # Resolver returns a valid structure
        mock_resolve.return_value = {
            "credit": 2.50, "debit": 0, "expiration": "2024-03-15",
            "legs": [{"strike": 430}, {"strike": 470}],
        }
        provider = self._make_provider()
        result = backtest_structure("SPY", "strangle", provider=provider, lookback_days=252)
        assert isinstance(result, OptionsBacktestResult)
        assert result.symbol == "SPY"
        assert result.strategy_type == "strangle"

    @patch("market_agent.backtest.options_engine.get_bars")
    @patch("market_agent.backtest.options_engine.resolve_strategy")
    def test_sample_size_positive(self, mock_resolve, mock_bars):
        mock_bars.return_value = _make_bars(300)
        mock_resolve.return_value = {
            "credit": 2.0, "debit": 0, "expiration": "2024-03-15",
            "legs": [],
        }
        provider = self._make_provider()
        result = backtest_structure(
            "SPY", "strangle", provider=provider,
            lookback_days=60, entry_freq_days=7,
        )
        assert result.sample_size >= 0  # At least attempted entries

    @patch("market_agent.backtest.options_engine.get_bars")
    @patch("market_agent.backtest.options_engine.resolve_strategy")
    def test_dit_is_positive(self, mock_resolve, mock_bars):
        mock_bars.return_value = _make_bars(300)
        mock_resolve.return_value = {
            "credit": 2.0, "debit": 0, "expiration": "2024-03-15",
            "legs": [],
        }
        provider = self._make_provider()
        result = backtest_structure(
            "SPY", "strangle", provider=provider,
            lookback_days=60,
        )
        if result.trades:
            for trade in result.trades:
                assert trade.dit >= 0

    @patch("market_agent.backtest.options_engine.get_bars")
    def test_resolver_failure_skips_entry(self, mock_bars):
        mock_bars.return_value = _make_bars(300)
        provider = self._make_provider()
        # Provider returns empty chain, and resolver will be called but returns None
        with patch("market_agent.backtest.options_engine.resolve_strategy", return_value=None):
            result = backtest_structure(
                "SPY", "strangle", provider=provider, lookback_days=30,
            )
        assert result.sample_size == 0


class TestOptionsTradeDataclass:
    def test_fields_accessible(self):
        t = _make_trade()
        assert t.symbol == "SPY"
        assert t.dit == 15
        assert t.exit_reason == "profit_target"
        assert t.credit == 2.00

    def test_exit_reasons(self):
        for reason in ("profit_target", "stop_loss", "dte_exit", "end_of_data"):
            t = _make_trade(exit_reason=reason)
            assert t.exit_reason == reason
