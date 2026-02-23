"""Tests for Trade Architect agent."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from market_agent.agents.architect import REGIME_PLAYBOOK, TradeArchitect
from market_agent.agents.state import PortfolioState, RegimeState, VolRegime


def _make_regime(regime: VolRegime, vix: float = 18.0) -> RegimeState:
    return RegimeState(
        vix_level=vix, vix_5d_change=0.0,
        regime=regime, ivr=50.0, ivx=5.0,
    )


def _make_options_summary(symbol: str, ivr: float = 50.0) -> dict:
    return {
        "symbol": symbol,
        "underlying_price": 450.0,
        "iv_rank": ivr,
        "iv_percentile": ivr,
        "current_iv": 25.0,
        "put_call_oi_ratio": 1.1,
        "skew": {"skew_direction": "put_skew", "magnitude": 3.0},
        "expirations_count": 12,
        "chain_size": 200,
    }


def _make_resolved_strategy(strategy_type: str) -> dict:
    return {
        "expiration": "2024-03-15",
        "dte": 30,
        "legs": [
            {"strike": 440.0, "type": "put", "side": "sell", "bid": 3.50, "ask": 3.80},
            {"strike": 470.0, "type": "call", "side": "sell", "bid": 2.80, "ask": 3.10},
        ],
        "credit": 6.30,
        "max_loss": 500.0,
        "breakevens": [433.70, 476.30],
    }


class TestRegimePlaybook:
    def test_all_regimes_have_playbook(self):
        for regime in VolRegime:
            assert regime in REGIME_PLAYBOOK

    def test_low_vol_strategies(self):
        playbook = REGIME_PLAYBOOK[VolRegime.LOW]
        assert "calendar" in playbook["strategies"]
        assert "diagonal" in playbook["strategies"]
        assert playbook["bp_limit_pct"] <= 40

    def test_normal_vol_strategies(self):
        playbook = REGIME_PLAYBOOK[VolRegime.NORMAL]
        assert "strangle" in playbook["strategies"]
        assert "iron_condor" in playbook["strategies"]

    def test_high_vol_strategies(self):
        playbook = REGIME_PLAYBOOK[VolRegime.HIGH]
        assert "jade_lizard" in playbook["strategies"]
        assert "back_ratio" in playbook["strategies"]
        assert playbook["delta_target"] >= 0.20  # Wide strikes

    def test_all_have_required_keys(self):
        required = {"strategies", "bp_limit_pct", "position_size_pct", "min_ivr",
                     "delta_target", "dte_range", "profit_target_pct", "rationale_prefix"}
        for regime, playbook in REGIME_PLAYBOOK.items():
            assert required.issubset(playbook.keys()), f"Missing keys in {regime}"


class TestTradeArchitect:
    @patch("market_agent.agents.architect.resolve_strategy")
    @patch("market_agent.agents.architect.options_summary")
    @patch("market_agent.agents.architect.compute_ivx", return_value=5.0)
    @patch("market_agent.agents.architect.get_bars")
    def test_generates_proposals(self, mock_bars, mock_ivx, mock_summary, mock_resolve):
        from market_agent.data.models import Bar
        from datetime import datetime, timedelta

        mock_bars.return_value = [
            Bar(timestamp=datetime(2024, 1, 1) + timedelta(days=i), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000)
            for i in range(60)
        ]
        mock_summary.return_value = _make_options_summary("SPY", ivr=45)
        mock_resolve.return_value = _make_resolved_strategy("strangle")

        state = PortfolioState(scan_symbols=["SPY"])
        state.regime = _make_regime(VolRegime.NORMAL)

        architect = TradeArchitect(max_proposals=5)
        state = architect.run(state)

        assert len(state.proposals) > 0
        assert state.proposals[0].symbol == "SPY"
        assert state.proposals[0].regime == VolRegime.NORMAL

    @patch("market_agent.agents.architect.options_summary")
    @patch("market_agent.agents.architect.get_bars")
    def test_filters_low_ivr(self, mock_bars, mock_summary):
        from market_agent.data.models import Bar
        from datetime import datetime, timedelta

        mock_bars.return_value = [
            Bar(timestamp=datetime(2024, 1, 1) + timedelta(days=i), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000)
            for i in range(60)
        ]
        # IVR of 10 is below min_ivr=25 for NORMAL regime
        mock_summary.return_value = _make_options_summary("SPY", ivr=10)

        state = PortfolioState(scan_symbols=["SPY"])
        state.regime = _make_regime(VolRegime.NORMAL)

        architect = TradeArchitect()
        state = architect.run(state)

        assert len(state.proposals) == 0

    def test_no_regime_aborts(self):
        state = PortfolioState()
        architect = TradeArchitect()
        state = architect.run(state)

        assert len(state.proposals) == 0

    @patch("market_agent.agents.architect.resolve_strategy")
    @patch("market_agent.agents.architect.options_summary")
    @patch("market_agent.agents.architect.compute_ivx", return_value=8.0)
    @patch("market_agent.agents.architect.get_bars")
    def test_proposal_has_rationale(self, mock_bars, mock_ivx, mock_summary, mock_resolve):
        from market_agent.data.models import Bar
        from datetime import datetime, timedelta

        mock_bars.return_value = [
            Bar(timestamp=datetime(2024, 1, 1) + timedelta(days=i), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000)
            for i in range(60)
        ]
        mock_summary.return_value = _make_options_summary("SPY", ivr=50)
        mock_resolve.return_value = _make_resolved_strategy("strangle")

        state = PortfolioState(scan_symbols=["SPY"])
        state.regime = _make_regime(VolRegime.HIGH, vix=30)

        architect = TradeArchitect()
        state = architect.run(state)

        assert len(state.proposals) > 0
        rationale = state.proposals[0].rationale
        assert any("IVR" in r for r in rationale)
        assert any("IVx" in r for r in rationale)
