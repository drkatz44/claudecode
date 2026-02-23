"""Tests for vol regime classification and term structure analysis."""

from datetime import datetime
from decimal import Decimal

from market_agent.agents.state import VolRegime
from market_agent.analysis.vol_regime import (
    classify_regime,
    compute_ivx,
    vix_change,
    vix_term_structure,
)
from market_agent.data.models import Bar


def _make_bars(closes: list[float]) -> list[Bar]:
    """Helper to create bars from a list of close prices."""
    from datetime import timedelta
    base = datetime(2024, 1, 1)
    return [
        Bar(
            timestamp=base + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(c * 1.01)),
            low=Decimal(str(c * 0.99)),
            close=Decimal(str(c)),
            volume=1000000,
        )
        for i, c in enumerate(closes)
    ]


class TestClassifyRegime:
    def test_low_vix(self):
        assert classify_regime(12.0) == VolRegime.LOW
        assert classify_regime(14.9) == VolRegime.LOW

    def test_normal_vix(self):
        assert classify_regime(15.0) == VolRegime.NORMAL
        assert classify_regime(20.0) == VolRegime.NORMAL
        assert classify_regime(25.0) == VolRegime.NORMAL

    def test_high_vix(self):
        assert classify_regime(25.1) == VolRegime.HIGH
        assert classify_regime(30.0) == VolRegime.HIGH
        assert classify_regime(80.0) == VolRegime.HIGH

    def test_boundary_low(self):
        assert classify_regime(14.99) == VolRegime.LOW

    def test_boundary_high(self):
        assert classify_regime(25.01) == VolRegime.HIGH


class TestVixTermStructure:
    def test_contango(self):
        # VX1 > VIX spot = normal/contango
        assert vix_term_structure(18.0, 20.0) == "contango"

    def test_backwardation(self):
        # VX1 < VIX spot = elevated fear
        assert vix_term_structure(30.0, 25.0) == "backwardation"

    def test_flat(self):
        # Within threshold
        assert vix_term_structure(20.0, 20.2) == "flat"
        assert vix_term_structure(20.0, 19.8) == "flat"

    def test_zero_inputs(self):
        assert vix_term_structure(0, 20) == "flat"
        assert vix_term_structure(20, 0) == "flat"

    def test_custom_threshold(self):
        # 5% threshold
        assert vix_term_structure(20.0, 20.5, threshold=0.05) == "flat"
        assert vix_term_structure(20.0, 22.0, threshold=0.05) == "contango"


class TestComputeIvx:
    def test_basic_computation(self):
        # 35 bars of steadily increasing prices
        closes = [100 + i * 0.5 for i in range(35)]
        bars = _make_bars(closes)
        ivx = compute_ivx(bars, period=30)
        assert ivx > 0
        assert isinstance(ivx, float)

    def test_insufficient_data(self):
        bars = _make_bars([100, 101, 102])
        assert compute_ivx(bars, period=30) == 0.0

    def test_flat_market(self):
        bars = _make_bars([100.0] * 35)
        ivx = compute_ivx(bars, period=30)
        assert ivx == 0.0  # No movement = zero expected move

    def test_volatile_market(self):
        # Alternating up/down = high vol
        closes = [100 + (5 if i % 2 == 0 else -5) for i in range(35)]
        bars = _make_bars(closes)
        ivx_volatile = compute_ivx(bars, period=30)

        # Steady market
        closes_steady = [100 + i * 0.1 for i in range(35)]
        bars_steady = _make_bars(closes_steady)
        ivx_steady = compute_ivx(bars_steady, period=30)

        assert ivx_volatile > ivx_steady


class TestVixChange:
    def test_positive_change(self):
        bars = _make_bars([15, 16, 17, 18, 19, 20, 21])
        change = vix_change(bars, lookback=5)
        assert change > 0

    def test_negative_change(self):
        bars = _make_bars([25, 24, 23, 22, 21, 20, 19])
        change = vix_change(bars, lookback=5)
        assert change < 0

    def test_no_change(self):
        bars = _make_bars([20, 20, 20, 20, 20, 20, 20])
        assert vix_change(bars, lookback=5) == 0.0

    def test_insufficient_data(self):
        bars = _make_bars([20, 21])
        assert vix_change(bars, lookback=5) == 0.0
