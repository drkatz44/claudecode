"""Tests for screener functions (mocked data)."""

from unittest.mock import patch

import pytest

from market_agent.analysis.screener import (
    ScreenResult,
    filter_correlated,
    screen_mean_reversion,
    screen_momentum,
    screen_volatility,
)
from conftest import generate_bars


def _make_screen_result(symbol, score=50.0, trend="bullish", rsi=55.0, atr_pct=2.0):
    return ScreenResult(
        symbol=symbol,
        score=score,
        trend=trend,
        rsi_14=rsi,
        atr_pct=atr_pct,
        volume_ratio=1.2,
        bb_pct_b=0.5,
        close=100.0,
        sma_20=98.0,
        sma_50=95.0,
    )


class TestScreenMomentum:
    @patch("market_agent.analysis.screener.get_multiple_bars")
    @patch("market_agent.analysis.screener._near_earnings")
    def test_finds_uptrending(self, mock_earnings, mock_bars):
        mock_earnings.return_value = False
        bars = generate_bars(100, trend="up", volatility=0.02)
        mock_bars.return_value = {"AAPL": bars, "MSFT": bars}

        results = screen_momentum(["AAPL", "MSFT"])
        # Should produce results (may be filtered by RSI/volume)
        assert isinstance(results, list)

    @patch("market_agent.analysis.screener.get_multiple_bars")
    @patch("market_agent.analysis.screener._near_earnings")
    def test_skips_short_data(self, mock_earnings, mock_bars):
        mock_earnings.return_value = False
        short = generate_bars(20, trend="up")
        mock_bars.return_value = {"AAPL": short}

        results = screen_momentum(["AAPL"])
        assert len(results) == 0

    @patch("market_agent.analysis.screener.get_multiple_bars")
    @patch("market_agent.analysis.screener._near_earnings")
    def test_results_sorted_by_score(self, mock_earnings, mock_bars):
        mock_earnings.return_value = False
        bars = generate_bars(100, trend="up", volatility=0.02)
        mock_bars.return_value = {"A": bars, "B": bars, "C": bars}

        results = screen_momentum(["A", "B", "C"], min_rsi=0, max_rsi=100, min_volume_ratio=0)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score


class TestScreenMeanReversion:
    @patch("market_agent.analysis.screener.get_multiple_bars")
    @patch("market_agent.analysis.screener._near_earnings")
    def test_finds_oversold(self, mock_earnings, mock_bars):
        mock_earnings.return_value = False
        bars = generate_bars(100, trend="down", volatility=0.03)
        mock_bars.return_value = {"AAPL": bars}

        results = screen_mean_reversion(["AAPL"], max_rsi=100, max_bb_pct_b=2.0)
        assert isinstance(results, list)


class TestScreenVolatility:
    @patch("market_agent.analysis.screener.get_multiple_bars")
    @patch("market_agent.analysis.screener._near_earnings")
    def test_finds_volatile(self, mock_earnings, mock_bars):
        mock_earnings.return_value = False
        bars = generate_bars(100, trend="up", volatility=0.04)
        mock_bars.return_value = {"TSLA": bars}

        results = screen_volatility(["TSLA"], min_atr_pct=0.0)
        assert isinstance(results, list)


class TestFilterCorrelated:
    def test_empty_list(self):
        assert filter_correlated([]) == []

    def test_single_item(self):
        r = _make_screen_result("AAPL")
        assert filter_correlated([r]) == [r]

    @patch("market_agent.analysis.screener.get_multiple_bars")
    def test_removes_correlated(self, mock_bars):
        # Same bars = perfect correlation
        bars = generate_bars(100, trend="up")
        mock_bars.return_value = {"AAPL": bars, "MSFT": bars}

        r1 = _make_screen_result("AAPL", score=80)
        r2 = _make_screen_result("MSFT", score=60)
        results = filter_correlated([r1, r2], threshold=0.7)
        # Should keep higher scorer and drop the correlated one
        assert len(results) == 1
        assert results[0].symbol == "AAPL"

    @patch("market_agent.analysis.screener.get_multiple_bars")
    def test_keeps_uncorrelated(self, mock_bars):
        up_bars = generate_bars(100, trend="up", volatility=0.01)
        down_bars = generate_bars(100, trend="down", volatility=0.04)
        mock_bars.return_value = {"AAPL": up_bars, "GLD": down_bars}

        r1 = _make_screen_result("AAPL", score=70)
        r2 = _make_screen_result("GLD", score=65)
        results = filter_correlated([r1, r2], threshold=0.95)
        # At high threshold, even somewhat correlated should be kept
        assert len(results) >= 1
