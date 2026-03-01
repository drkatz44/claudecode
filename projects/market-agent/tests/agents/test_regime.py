"""Tests for Regime Detector agent."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from market_agent.agents.regime import RegimeDetector
from market_agent.agents.state import PortfolioState, VolRegime
from market_agent.data.models import Bar


def _make_vix_bars(vix_level: float, count: int = 120) -> list[Bar]:
    """Create simulated VIX bars around a level."""
    import random
    random.seed(42)
    bars = []
    for i in range(count):
        # Small random walk around the level
        noise = random.gauss(0, 0.5)
        close = max(9.0, vix_level + noise)
        bars.append(Bar(
            timestamp=datetime(2024, 1, 1 + i % 28, 16, 0),
            open=Decimal(str(round(close - 0.2, 2))),
            high=Decimal(str(round(close + 0.5, 2))),
            low=Decimal(str(round(close - 0.5, 2))),
            close=Decimal(str(round(close, 2))),
            volume=0,
        ))
    return bars


class TestRegimeDetector:
    @patch("market_agent.agents.regime.get_bars")
    def test_low_vix_regime(self, mock_get_bars):
        mock_get_bars.return_value = _make_vix_bars(12.0)
        state = PortfolioState()
        detector = RegimeDetector()
        state = detector.run(state)

        assert state.regime is not None
        assert state.regime.regime == VolRegime.LOW
        assert state.regime.vix_level < 15

    @patch("market_agent.agents.regime.get_bars")
    def test_normal_vix_regime(self, mock_get_bars):
        mock_get_bars.return_value = _make_vix_bars(18.0)
        state = PortfolioState()
        detector = RegimeDetector()
        state = detector.run(state)

        assert state.regime is not None
        assert state.regime.regime == VolRegime.NORMAL

    @patch("market_agent.agents.regime.get_bars")
    def test_high_vix_regime(self, mock_get_bars):
        mock_get_bars.return_value = _make_vix_bars(30.0)
        state = PortfolioState()
        detector = RegimeDetector()
        state = detector.run(state)

        assert state.regime is not None
        assert state.regime.regime == VolRegime.HIGH
        assert state.regime.vix_level > 25

    @patch("market_agent.agents.regime.get_bars")
    def test_insufficient_data(self, mock_get_bars):
        mock_get_bars.return_value = _make_vix_bars(18.0, count=5)
        state = PortfolioState()
        detector = RegimeDetector()
        state = detector.run(state)

        assert state.regime is None

    @patch("market_agent.agents.regime.get_bars")
    def test_no_data(self, mock_get_bars):
        mock_get_bars.return_value = None
        state = PortfolioState()
        detector = RegimeDetector()
        state = detector.run(state)

        assert state.regime is None

    @patch("market_agent.agents.regime.get_bars")
    def test_regime_fields_populated(self, mock_get_bars):
        mock_get_bars.return_value = _make_vix_bars(20.0, count=260)
        state = PortfolioState()
        detector = RegimeDetector()
        state = detector.run(state)

        assert state.regime is not None
        assert state.regime.ivx > 0
        assert 0 <= state.regime.ivr <= 100
        assert state.regime.vix_term_structure in ("contango", "backwardation", "flat")
        assert isinstance(state.regime.vix_5d_change, float)
        assert state.regime.vvix_level >= 0  # 0.0 when unavailable, positive when fetched
