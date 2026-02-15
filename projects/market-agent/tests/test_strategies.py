"""Tests for backtest strategy signal functions."""

import pytest

from market_agent.backtest.strategies import (
    breakout_volume,
    macd_momentum,
    mean_reversion_bb,
    momentum_crossover,
)
from market_agent.data.models import SignalDirection
from conftest import generate_bars


class TestMomentumCrossover:
    def test_returns_none_insufficient_bars(self, short_bars):
        result = momentum_crossover(short_bars)
        assert result is None

    def test_signal_has_required_fields(self, uptrend_bars):
        # Run over many bars — may or may not fire
        for i in range(30, len(uptrend_bars)):
            sig = momentum_crossover(uptrend_bars[:i])
            if sig is not None:
                assert sig.strategy == "momentum_crossover"
                assert sig.entry_price is not None
                assert sig.stop_loss is not None
                assert sig.take_profit is not None
                assert sig.direction in (SignalDirection.LONG, SignalDirection.SHORT)
                break

    def test_long_signal_stops_below_entry(self, uptrend_bars):
        for i in range(30, len(uptrend_bars)):
            sig = momentum_crossover(uptrend_bars[:i])
            if sig and sig.direction == SignalDirection.LONG:
                assert sig.stop_loss < sig.entry_price
                assert sig.take_profit > sig.entry_price
                break

    def test_short_signal_stops_above_entry(self, downtrend_bars):
        for i in range(30, len(downtrend_bars)):
            sig = momentum_crossover(downtrend_bars[:i])
            if sig and sig.direction == SignalDirection.SHORT:
                assert sig.stop_loss > sig.entry_price
                assert sig.take_profit < sig.entry_price
                break


class TestMeanReversionBB:
    def test_returns_none_insufficient_bars(self, short_bars):
        result = mean_reversion_bb(short_bars)
        assert result is None

    def test_strategy_name(self, uptrend_bars):
        for i in range(25, len(uptrend_bars)):
            sig = mean_reversion_bb(uptrend_bars[:i])
            if sig is not None:
                assert sig.strategy == "mean_reversion_bb"
                break


class TestMACDMomentum:
    def test_returns_none_insufficient_bars(self):
        bars = generate_bars(40, trend="up")
        result = macd_momentum(bars)
        assert result is None

    def test_signal_has_macd_metadata(self, uptrend_bars):
        for i in range(55, len(uptrend_bars)):
            sig = macd_momentum(uptrend_bars[:i])
            if sig is not None:
                assert "macd" in sig.metadata
                assert "signal" in sig.metadata
                assert "histogram" in sig.metadata
                break


class TestBreakoutVolume:
    def test_returns_none_insufficient_bars(self, short_bars):
        result = breakout_volume(short_bars)
        assert result is None

    def test_signal_has_vol_ratio_metadata(self, uptrend_bars):
        for i in range(30, len(uptrend_bars)):
            sig = breakout_volume(uptrend_bars[:i])
            if sig is not None:
                assert sig.strategy == "breakout_volume"
                assert "vol_ratio" in sig.metadata
                assert "atr" in sig.metadata
                break

    def test_long_breakout_stops_below(self, uptrend_bars):
        for i in range(30, len(uptrend_bars)):
            sig = breakout_volume(uptrend_bars[:i])
            if sig and sig.direction == SignalDirection.LONG:
                assert sig.stop_loss < sig.entry_price
                assert sig.take_profit > sig.entry_price
                break

    def test_short_breakdown_stops_above(self, downtrend_bars):
        for i in range(30, len(downtrend_bars)):
            sig = breakout_volume(downtrend_bars[:i])
            if sig and sig.direction == SignalDirection.SHORT:
                assert sig.stop_loss > sig.entry_price
                assert sig.take_profit < sig.entry_price
                break
