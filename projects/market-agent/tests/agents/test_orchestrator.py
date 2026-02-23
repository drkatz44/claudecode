"""Tests for Orchestrator — full pipeline with mocked data."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from market_agent.agents.orchestrator import Orchestrator
from market_agent.agents.state import (
    PortfolioState,
    RegimeState,
    TradeProposal,
    VolRegime,
)


def _make_proposal(symbol: str, size_pct: float = 2.0) -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        strategy_type="strangle",
        legs=[{"strike": 440, "type": "put", "side": "sell"}],
        regime=VolRegime.NORMAL,
        position_size_pct=size_pct,
        credit=5.0,
        max_loss=500.0,
    )


class TestOrchestratorConstraints:
    def test_max_positions_cap(self):
        """Should block new proposals when at max positions."""
        orch = Orchestrator(max_positions=5)

        state = PortfolioState(
            open_positions=[{"symbol": f"SYM{i}"} for i in range(5)]
        )
        state.regime = RegimeState(
            vix_level=18, vix_5d_change=0,
            regime=VolRegime.NORMAL, ivr=50, ivx=5,
        )
        state.proposals = [_make_proposal("SPY")]

        state = orch._apply_constraints(state)

        assert len(state.proposals) == 0
        assert any("Max positions" in a for a in state.alerts)

    def test_bp_limit_cap(self):
        """Should block proposals when BP usage exceeds limit."""
        orch = Orchestrator(max_bp_pct=50.0)

        state = PortfolioState(bp_usage_pct=55.0)
        state.regime = RegimeState(
            vix_level=18, vix_5d_change=0,
            regime=VolRegime.NORMAL, ivr=50, ivx=5,
        )
        state.proposals = [_make_proposal("SPY")]

        state = orch._apply_constraints(state)

        assert len(state.proposals) == 0
        assert any("BP usage" in a for a in state.alerts)

    def test_position_size_limit(self):
        """Should reject proposals with size > 5%."""
        orch = Orchestrator()

        state = PortfolioState()
        state.proposals = [_make_proposal("SPY", size_pct=6.0)]

        state = orch._apply_constraints(state)
        assert len(state.proposals) == 0

    def test_symbol_concentration(self):
        """Should limit proposals per symbol."""
        orch = Orchestrator()

        state = PortfolioState()
        state.proposals = [_make_proposal("SPY") for _ in range(5)]

        state = orch._apply_constraints(state)
        assert len(state.proposals) <= 3  # MAX_SECTOR_ALLOCATION

    def test_available_slots(self):
        """Should respect available position slots."""
        orch = Orchestrator(max_positions=3)

        state = PortfolioState(
            open_positions=[{"symbol": "AAPL"}],  # 1 open
        )
        state.proposals = [
            _make_proposal("SPY"),
            _make_proposal("QQQ"),
            _make_proposal("GLD"),
            _make_proposal("IWM"),
        ]

        state = orch._apply_constraints(state)
        assert len(state.proposals) <= 2  # 3 max - 1 open = 2 slots


class TestOrchestratorPipeline:
    @patch.object(Orchestrator, "_apply_constraints", side_effect=lambda s: s)
    @patch("market_agent.agents.architect.resolve_strategy")
    @patch("market_agent.agents.architect.options_summary")
    @patch("market_agent.agents.architect.compute_ivx", return_value=5.0)
    @patch("market_agent.agents.architect.get_bars")
    @patch("market_agent.agents.regime.get_bars")
    def test_full_pipeline(self, mock_vix_bars, mock_bars, mock_ivx, mock_summary, mock_resolve, mock_constraints):
        from datetime import datetime, timedelta

        from market_agent.data.models import Bar

        # VIX bars
        mock_vix_bars.return_value = [
            Bar(timestamp=datetime(2024, 1, 1) + timedelta(days=i), open=Decimal("18"),
                high=Decimal("19"), low=Decimal("17"), close=Decimal("18"), volume=0)
            for i in range(120)
        ]

        # Symbol bars
        mock_bars.return_value = [
            Bar(timestamp=datetime(2024, 1, 1) + timedelta(days=i), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000)
            for i in range(60)
        ]

        mock_summary.return_value = {
            "symbol": "SPY", "underlying_price": 450.0,
            "iv_rank": 50.0, "iv_percentile": 50.0, "current_iv": 25.0,
            "put_call_oi_ratio": 1.0, "skew": {"skew_direction": "neutral", "magnitude": 0},
            "expirations_count": 12, "chain_size": 200,
        }
        mock_resolve.return_value = {
            "expiration": "2024-03-15", "dte": 30,
            "legs": [{"strike": 440, "type": "put", "side": "sell"}],
            "credit": 3.50, "max_loss": 500, "breakevens": [436.50],
        }

        state = PortfolioState(scan_symbols=["SPY"])
        orch = Orchestrator(max_proposals=5)
        state = orch.run(state)

        # Should have regime + proposals
        assert state.regime is not None
        assert state.regime.regime == VolRegime.NORMAL
        assert len(state.proposals) > 0

    @patch("market_agent.agents.regime.get_bars")
    def test_pipeline_no_vix_data(self, mock_bars):
        mock_bars.return_value = None

        state = PortfolioState()
        orch = Orchestrator()
        state = orch.run(state)

        assert state.regime is None
        assert any("regime" in a.lower() for a in state.alerts)
