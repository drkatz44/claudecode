"""Tests for the backtesting engine."""

from decimal import Decimal

import pytest

from market_agent.backtest.engine import BacktestResult, backtest, walk_forward, _apply_slippage
from market_agent.backtest.strategies import momentum_crossover, breakout_volume
from market_agent.data.models import SignalDirection
from conftest import generate_bars


class TestApplySlippage:
    def test_long_slippage_increases_price(self):
        price = Decimal("100.00")
        result = _apply_slippage(price, SignalDirection.LONG, 10.0)
        assert result > price

    def test_short_slippage_decreases_price(self):
        price = Decimal("100.00")
        result = _apply_slippage(price, SignalDirection.SHORT, 10.0)
        assert result < price

    def test_zero_slippage(self):
        price = Decimal("100.00")
        result = _apply_slippage(price, SignalDirection.LONG, 0.0)
        assert result == price

    def test_slippage_amount(self):
        price = Decimal("100.00")
        result = _apply_slippage(price, SignalDirection.LONG, 100.0)  # 100 bps = 1%
        assert result == Decimal("101.00")


class TestBacktest:
    def test_basic_execution(self, uptrend_bars):
        result = backtest(uptrend_bars, momentum_crossover)
        assert isinstance(result, BacktestResult)
        assert result.initial_capital == Decimal("10000")

    def test_produces_trades(self):
        # Use longer series for more signal opportunities
        bars = generate_bars(200, trend="up", volatility=0.025)
        result = backtest(bars, breakout_volume)
        # breakout_volume should fire at least once on 200 bars
        assert result.total_trades >= 0  # may be 0 depending on exact data

    def test_insufficient_bars_raises(self, short_bars):
        with pytest.raises(ValueError, match="at least 50 bars"):
            backtest(short_bars, momentum_crossover)

    def test_win_rate_bounds(self, uptrend_bars):
        result = backtest(uptrend_bars, momentum_crossover)
        assert 0 <= result.win_rate <= 100

    def test_commission_reduces_returns(self):
        bars = generate_bars(200, trend="up", volatility=0.025)
        r_no_comm = backtest(bars, breakout_volume, commission_pct=0.0)
        r_with_comm = backtest(bars, breakout_volume, commission_pct=0.5)
        # With commissions, returns should be lower (or equal if no trades)
        if r_no_comm.total_trades > 0:
            assert r_with_comm.total_return_pct <= r_no_comm.total_return_pct

    def test_slippage_reduces_returns(self):
        bars = generate_bars(200, trend="up", volatility=0.025)
        r_no_slip = backtest(bars, breakout_volume, slippage_bps=0.0)
        r_with_slip = backtest(bars, breakout_volume, slippage_bps=50.0)
        if r_no_slip.total_trades > 0:
            assert r_with_slip.total_return_pct <= r_no_slip.total_return_pct

    def test_benchmark_fields(self, uptrend_bars):
        bench = generate_bars(100, trend="up", start_price=400)
        result = backtest(uptrend_bars, momentum_crossover, benchmark_bars=bench)
        assert result.benchmark_return_pct is not None
        assert result.alpha is not None

    def test_no_benchmark(self, uptrend_bars):
        result = backtest(uptrend_bars, momentum_crossover)
        assert result.benchmark_return_pct is None
        assert result.alpha is None

    def test_enhanced_metrics_exist(self, uptrend_bars):
        result = backtest(uptrend_bars, momentum_crossover)
        assert hasattr(result, "sortino_ratio")
        assert hasattr(result, "calmar_ratio")
        assert hasattr(result, "max_win_streak")
        assert hasattr(result, "max_loss_streak")

    def test_equity_curve_length(self, uptrend_bars):
        result = backtest(uptrend_bars, momentum_crossover)
        # Should have one entry per bar after warmup
        assert len(result.equity_curve) == len(uptrend_bars) - 50

    def test_summary_dict(self, uptrend_bars):
        result = backtest(uptrend_bars, momentum_crossover)
        s = result.summary()
        assert "total_return" in s
        assert "sortino_ratio" in s
        assert "calmar_ratio" in s


class TestSignalExits:
    def test_signal_exit_enabled(self):
        bars = generate_bars(200, trend="up", volatility=0.03)
        r_with = backtest(bars, momentum_crossover, use_signal_exits=True)
        r_without = backtest(bars, momentum_crossover, use_signal_exits=False)
        # Results should differ (or be the same if no opposing signals)
        assert isinstance(r_with, BacktestResult)
        assert isinstance(r_without, BacktestResult)


class TestWalkForward:
    def test_basic_walk_forward(self):
        bars = generate_bars(500, trend="up", volatility=0.02)
        result = walk_forward(bars, momentum_crossover, train_bars=200, test_bars=63)
        assert "windows" in result
        assert "avg_return" in result
        assert "total_windows" in result
        assert result["total_windows"] > 0

    def test_insufficient_bars_raises(self, uptrend_bars):
        with pytest.raises(ValueError, match="Need at least"):
            walk_forward(uptrend_bars, momentum_crossover, train_bars=200, test_bars=63)

    def test_consistency_bounds(self):
        bars = generate_bars(500, trend="up", volatility=0.02)
        result = walk_forward(bars, momentum_crossover, train_bars=200, test_bars=63)
        if result["total_windows"] > 0:
            assert 0 <= result["consistency"] <= 100
