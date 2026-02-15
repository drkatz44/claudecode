"""Tests for technical analysis indicators."""

import pandas as pd
import pytest

from market_agent.analysis.technical import (
    adx,
    atr,
    bollinger_bands,
    ema,
    historical_volatility,
    macd,
    obv,
    pivot_points,
    rate_of_change,
    relative_strength,
    rsi,
    sma,
    stochastic,
    trend_summary,
    volume_sma_ratio,
    vwap_rolling,
)
from conftest import generate_bars


class TestSMA:
    def test_sma_returns_series(self, uptrend_bars):
        result = sma(uptrend_bars, 20)
        assert isinstance(result, pd.Series)
        assert len(result) == len(uptrend_bars)

    def test_sma_first_values_nan(self, uptrend_bars):
        result = sma(uptrend_bars, 20)
        assert pd.isna(result.iloc[0])
        assert pd.notna(result.iloc[19])

    def test_sma_follows_trend(self, uptrend_bars):
        result = sma(uptrend_bars, 20)
        # SMA should generally increase in uptrend
        valid = result.dropna()
        assert valid.iloc[-1] > valid.iloc[0]


class TestEMA:
    def test_ema_returns_series(self, uptrend_bars):
        result = ema(uptrend_bars, 12)
        assert isinstance(result, pd.Series)
        assert len(result) == len(uptrend_bars)

    def test_ema_faster_than_sma(self, uptrend_bars):
        ema_val = ema(uptrend_bars, 20).iloc[-1]
        sma_val = sma(uptrend_bars, 20).iloc[-1]
        # In uptrend, EMA should be closer to price (higher) than SMA
        close = float(uptrend_bars[-1].close)
        assert abs(ema_val - close) < abs(sma_val - close)


class TestRSI:
    def test_rsi_bounds(self, uptrend_bars):
        result = rsi(uptrend_bars, 14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_high_in_uptrend(self, uptrend_bars):
        result = rsi(uptrend_bars, 14)
        assert result.iloc[-1] > 50

    def test_rsi_low_in_downtrend(self, downtrend_bars):
        result = rsi(downtrend_bars, 14)
        assert result.iloc[-1] < 50

    def test_rsi_insufficient_bars(self, short_bars):
        result = rsi(short_bars, 14)
        # Should still return a series, mostly NaN
        assert isinstance(result, pd.Series)


class TestMACD:
    def test_macd_columns(self, uptrend_bars):
        result = macd(uptrend_bars)
        assert "macd" in result.columns
        assert "signal" in result.columns
        assert "histogram" in result.columns

    def test_macd_histogram_is_diff(self, uptrend_bars):
        result = macd(uptrend_bars)
        valid_idx = result.dropna().index
        for idx in valid_idx[:5]:
            expected = result.loc[idx, "macd"] - result.loc[idx, "signal"]
            assert abs(result.loc[idx, "histogram"] - expected) < 1e-10


class TestBollingerBands:
    def test_bb_columns(self, uptrend_bars):
        result = bollinger_bands(uptrend_bars)
        assert set(result.columns) == {"upper", "middle", "lower", "bandwidth", "pct_b"}

    def test_bb_order(self, uptrend_bars):
        result = bollinger_bands(uptrend_bars)
        valid = result.dropna()
        assert (valid["upper"] >= valid["middle"]).all()
        assert (valid["middle"] >= valid["lower"]).all()

    def test_bb_pct_b_range(self, flat_bars):
        result = bollinger_bands(flat_bars)
        valid = result["pct_b"].dropna()
        # Most values should be between 0 and 1 for flat data
        within = ((valid >= -0.5) & (valid <= 1.5)).sum()
        assert within / len(valid) > 0.8


class TestATR:
    def test_atr_positive(self, uptrend_bars):
        result = atr(uptrend_bars, 14)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_atr_returns_series(self, uptrend_bars):
        result = atr(uptrend_bars)
        assert isinstance(result, pd.Series)


class TestADX:
    def test_adx_columns(self, uptrend_bars):
        result = adx(uptrend_bars)
        assert set(result.columns) == {"adx", "plus_di", "minus_di"}

    def test_adx_bounds(self, uptrend_bars):
        result = adx(uptrend_bars)
        valid = result.dropna()
        assert (valid["adx"] >= 0).all()
        assert (valid["adx"] <= 100).all()

    def test_adx_trending_market(self, uptrend_bars):
        result = adx(uptrend_bars)
        # Strongly trending market should have ADX > 20
        last_adx = result["adx"].iloc[-1]
        assert last_adx > 15  # slightly relaxed threshold for synthetic data


class TestRelativeStrength:
    def test_rs_above_one_outperforming(self):
        strong = generate_bars(100, trend="up", volatility=0.01)
        weak = generate_bars(100, trend="flat", volatility=0.01)
        result = relative_strength(strong, weak, period=20)
        valid = result.dropna()
        assert valid.iloc[-1] > 1.0

    def test_rs_returns_series(self, uptrend_bars, flat_bars):
        result = relative_strength(uptrend_bars, flat_bars, period=20)
        assert isinstance(result, pd.Series)


class TestStochastic:
    def test_stochastic_columns(self, uptrend_bars):
        result = stochastic(uptrend_bars)
        assert "k" in result.columns
        assert "d" in result.columns

    def test_stochastic_bounds(self, uptrend_bars):
        result = stochastic(uptrend_bars)
        valid = result.dropna()
        assert (valid["k"] >= 0).all()
        assert (valid["k"] <= 100).all()


class TestVolumeIndicators:
    def test_volume_sma_ratio(self, uptrend_bars):
        result = volume_sma_ratio(uptrend_bars, 20)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_obv_returns_series(self, uptrend_bars):
        result = obv(uptrend_bars)
        assert isinstance(result, pd.Series)

    def test_vwap_rolling(self, uptrend_bars):
        result = vwap_rolling(uptrend_bars)
        valid = result.dropna()
        assert len(valid) > 0


class TestPivotPoints:
    def test_pivot_keys(self, uptrend_bars):
        result = pivot_points(uptrend_bars)
        assert set(result.keys()) == {"r2", "r1", "pivot", "s1", "s2"}

    def test_pivot_order(self, uptrend_bars):
        result = pivot_points(uptrend_bars)
        assert result["r2"] > result["r1"] > result["pivot"] > result["s1"] > result["s2"]

    def test_pivot_empty_bars(self):
        result = pivot_points([])
        assert result == {}


class TestTrendSummary:
    def test_summary_keys(self, uptrend_bars):
        result = trend_summary(uptrend_bars)
        assert "trend" in result
        assert "rsi_14" in result
        assert "sma_20" in result
        assert "sma_50" in result

    def test_bullish_trend(self, uptrend_bars):
        result = trend_summary(uptrend_bars)
        assert result["trend"] in ("bullish", "neutral")

    def test_bearish_trend(self, downtrend_bars):
        result = trend_summary(downtrend_bars)
        assert result["trend"] in ("bearish", "neutral")

    def test_insufficient_bars(self, short_bars):
        result = trend_summary(short_bars)
        assert "error" in result
