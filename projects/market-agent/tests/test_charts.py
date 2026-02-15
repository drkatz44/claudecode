"""Tests for chart generation module."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from market_agent.analysis.charts import (
    chart_technical,
    chart_equity_curve,
    chart_options_chain,
    _safe_name,
)
from market_agent.data.models import Bar, OptionQuote
from conftest import generate_bars


class TestSafeName:
    def test_normal_name(self):
        assert _safe_name("AAPL") == "AAPL"

    def test_strips_special(self):
        assert _safe_name("BTC-USD") == "BTC-USD"

    def test_strips_path_traversal(self):
        assert _safe_name("../../../etc/passwd") == "etcpasswd"

    def test_strips_spaces(self):
        assert _safe_name("my file name") == "myfilename"


class TestChartTechnical:
    def test_creates_png(self, tmp_path):
        bars = generate_bars(100, trend="up")
        path = chart_technical(bars, "AAPL", save_path=tmp_path / "test.png")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
        assert path.stat().st_size > 0

    def test_insufficient_bars(self, tmp_path):
        bars = generate_bars(10, trend="up")
        path = chart_technical(bars, "TEST", save_path=tmp_path / "test.png")
        assert path is None

    def test_with_signals(self, tmp_path):
        bars = generate_bars(100, trend="up")
        signals = [
            {"timestamp": bars[30].timestamp, "direction": "long"},
            {"timestamp": bars[70].timestamp, "direction": "short"},
        ]
        path = chart_technical(bars, "AAPL", signals=signals, save_path=tmp_path / "test.png")
        assert path is not None
        assert path.exists()

    def test_short_bars_no_sma50(self, tmp_path):
        bars = generate_bars(30, trend="up")
        path = chart_technical(bars, "TEST", save_path=tmp_path / "test.png")
        assert path is not None
        assert path.exists()


class TestChartEquityCurve:
    def _make_curve(self, n=100, initial=10000.0, trend=0.001):
        base = datetime(2024, 1, 2)
        curve = []
        val = initial
        for i in range(n):
            val *= (1 + trend + 0.005 * (1 if i % 3 == 0 else -0.5))
            curve.append((base + timedelta(days=i), val))
        return curve

    def test_creates_png(self, tmp_path):
        curve = self._make_curve()
        path = chart_equity_curve(curve, "SPY", strategy_name="momentum",
                                  save_path=tmp_path / "eq.png")
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 0

    def test_with_benchmark(self, tmp_path):
        curve = self._make_curve()
        path = chart_equity_curve(curve, "SPY", strategy_name="momentum",
                                  benchmark_return_pct=15.0,
                                  save_path=tmp_path / "eq.png")
        assert path is not None
        assert path.exists()

    def test_insufficient_data(self, tmp_path):
        curve = [(datetime(2024, 1, 1), 10000.0)]
        path = chart_equity_curve(curve, "SPY", save_path=tmp_path / "eq.png")
        assert path is None

    def test_negative_returns(self, tmp_path):
        curve = self._make_curve(trend=-0.003)
        path = chart_equity_curve(curve, "SPY", strategy_name="bad_strat",
                                  save_path=tmp_path / "eq.png")
        assert path is not None
        assert path.exists()


class TestChartOptionsChain:
    def _make_chain(self, underlying=100.0, n_strikes=10):
        chain = []
        for i in range(-n_strikes // 2, n_strikes // 2 + 1):
            strike = underlying + i * 5
            if strike <= 0:
                continue
            for opt_type in ("call", "put"):
                iv = 0.25 + abs(i) * 0.02
                chain.append(OptionQuote(
                    symbol=f"TEST{opt_type[0].upper()}{int(strike)}",
                    underlying="TEST",
                    strike=Decimal(str(strike)),
                    expiration=datetime(2025, 3, 21),
                    option_type=opt_type,
                    bid=Decimal("1.50"),
                    ask=Decimal("1.60"),
                    last=Decimal("1.55"),
                    volume=100,
                    open_interest=500 + i * 50,
                    iv=Decimal(str(round(iv, 4))),
                ))
        return chain

    def test_creates_png(self, tmp_path):
        chain = self._make_chain()
        path = chart_options_chain(chain, 100.0, "AAPL",
                                   save_path=tmp_path / "opts.png")
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 0

    def test_insufficient_chain(self, tmp_path):
        chain = self._make_chain(n_strikes=1)
        # Very small chain
        path = chart_options_chain(chain[:2], 100.0, "TEST",
                                   save_path=tmp_path / "opts.png")
        assert path is None

    def test_no_iv_options(self, tmp_path):
        chain = []
        for i in range(6):
            chain.append(OptionQuote(
                symbol=f"TESTC{90 + i * 5}",
                underlying="TEST",
                strike=Decimal(str(90 + i * 5)),
                expiration=datetime(2025, 3, 21),
                option_type="call",
                bid=Decimal("1.50"),
                ask=Decimal("1.60"),
                last=Decimal("1.55"),
                volume=100,
                open_interest=500,
                iv=None,  # No IV data
            ))
        path = chart_options_chain(chain, 100.0, "TEST",
                                   save_path=tmp_path / "opts.png")
        # Should still create chart (OI data available even without IV)
        assert path is not None
