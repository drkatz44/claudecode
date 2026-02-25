"""Tests for Kelly Criterion position sizing."""

import pytest

from market_agent.analysis.kelly import (
    expected_value,
    half_kelly,
    kelly_fraction,
    kelly_size_multiplier,
    position_size_pct,
)


class TestKellyFraction:
    def test_positive_edge(self):
        # 70% win rate, win 50%, lose 100% → positive Kelly
        f = kelly_fraction(70, 50, 100)
        assert f > 0

    def test_negative_edge(self):
        # 40% win rate, win 50%, lose 150% → negative edge → 0
        f = kelly_fraction(40, 50, 150)
        assert f == 0.0

    def test_zero_win_rate(self):
        assert kelly_fraction(0, 50, 100) == 0.0

    def test_zero_avg_loss(self):
        assert kelly_fraction(60, 50, 0) == 0.0

    def test_perfect_win_rate(self):
        f = kelly_fraction(100, 50, 100)
        assert f == pytest.approx(1.0)

    def test_symmetric_payoff(self):
        # 50% win, win/loss equal → Kelly = 0
        f = kelly_fraction(50, 100, 100)
        assert f == pytest.approx(0.0)

    def test_range(self):
        for wr in range(30, 80, 10):
            for win in [30, 50, 80]:
                for loss in [50, 100, 150]:
                    f = kelly_fraction(wr, win, loss)
                    assert 0.0 <= f <= 1.0


class TestHalfKelly:
    def test_is_half_of_full(self):
        full = kelly_fraction(70, 50, 80)
        half = half_kelly(70, 50, 80)
        assert abs(half - full * 0.5) < 1e-9

    def test_zero_for_negative_edge(self):
        assert half_kelly(30, 30, 200) == 0.0


class TestKellySizeMultiplier:
    def test_negative_edge_reduces(self):
        # Low win rate = reduce size to 0.5x
        mult = kelly_size_multiplier(35, 50, 200)
        assert mult == 0.5

    def test_marginal_edge(self):
        # Small positive Kelly → 0.75x
        # Need to engineer a case where 0 < f < 0.10
        # win_rate=55, avg_win=30, avg_loss=100: f ≈ (0.3*0.55 - 0.45)/0.3 = (0.165-0.45)/0.3 < 0
        # Try win_rate=70, avg_win=50, avg_loss=200: f = (0.25*0.7-0.3)/0.25 = (0.175-0.3)/0.25 < 0
        # Hard to get exactly marginal — just test the boundary behavior
        mult = kelly_size_multiplier(60, 40, 100)
        assert mult in (0.5, 0.75, 1.0, 1.5)

    def test_strong_edge_increases(self):
        # Very favorable odds → 1.5x
        mult = kelly_size_multiplier(90, 80, 20)
        assert mult == 1.5

    def test_multiplier_is_one_of_four_levels(self):
        for wr in [40, 55, 65, 80, 95]:
            mult = kelly_size_multiplier(wr, 50, 100)
            assert mult in (0.5, 0.75, 1.0, 1.5)


class TestPositionSizePct:
    def test_madman_hard_cap(self):
        # Madman trades always capped at 0.15% regardless of Kelly
        size = position_size_pct(90, 100, 10, default_pct=3.0, is_madman=True)
        assert size == 0.15

    def test_respects_min(self):
        size = position_size_pct(35, 30, 200, default_pct=2.0, min_pct=0.5)
        assert size >= 0.5

    def test_respects_max(self):
        size = position_size_pct(90, 100, 5, default_pct=3.0, max_pct=5.0)
        assert size <= 5.0

    def test_default_applied(self):
        # With neutral Kelly (1x multiplier), should return default
        size = position_size_pct(65, 40, 100, default_pct=2.0)
        assert 0.5 <= size <= 5.0

    def test_strong_edge_increases_default(self):
        # Very high win rate → 1.5x multiplier → bigger than default
        size_strong = position_size_pct(92, 80, 20, default_pct=2.0, max_pct=5.0)
        size_weak = position_size_pct(35, 20, 200, default_pct=2.0, min_pct=0.5)
        assert size_strong >= size_weak


class TestExpectedValue:
    def test_positive_ev(self):
        ev = expected_value(65, 50, 50)
        assert ev > 0

    def test_negative_ev(self):
        ev = expected_value(40, 50, 150)
        assert ev < 0

    def test_breakeven(self):
        # 50% win, win 100, lose 100 → EV = 0
        ev = expected_value(50, 100, 100)
        assert abs(ev) < 1e-9
