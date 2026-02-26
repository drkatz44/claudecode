"""Tests for Phase 3 Orchestrator: circuit breakers and sector BP caps."""

from decimal import Decimal

import pytest

from market_agent.agents.orchestrator import (
    MAX_PORTFOLIO_DELTA_PCT,
    MAX_SECTOR_BP_PCT,
    VIX_CIRCUIT_BREAKER,
    Orchestrator,
)
from market_agent.agents.state import (
    PortfolioState,
    RegimeState,
    TradeProposal,
    VolRegime,
)
from market_agent.analysis.sectors import MAX_SECTOR_BP_PCT as SECTOR_CAP


def _make_regime(vix: float = 18.0, regime: VolRegime = VolRegime.NORMAL) -> RegimeState:
    return RegimeState(
        vix_level=vix, vix_5d_change=0.0,
        regime=regime, ivr=50.0, ivx=5.0,
    )


def _make_proposal(
    symbol: str = "SPY",
    size_pct: float = 2.0,
    is_madman: bool = False,
) -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        strategy_type="strangle",
        legs=[],
        regime=VolRegime.NORMAL,
        position_size_pct=size_pct,
        is_madman=is_madman,
    )


def _make_state(
    proposals: list | None = None,
    regime: RegimeState | None = None,
    net_liq: float = 100000,
    portfolio_delta: float = 0.0,
    open_positions: list | None = None,
) -> PortfolioState:
    state = PortfolioState(
        net_liq=Decimal(str(net_liq)),
        buying_power=Decimal(str(net_liq)),
        regime=regime or _make_regime(),
        proposals=proposals or [],
        open_positions=open_positions or [],
    )
    state.portfolio_delta = portfolio_delta
    return state


# ---------------------------------------------------------------------------
# VIX circuit breaker
# ---------------------------------------------------------------------------

class TestVixCircuitBreaker:
    def test_vix_above_threshold_halves_sizes(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal(size_pct=2.0), _make_proposal("QQQ", size_pct=3.0)],
            regime=_make_regime(vix=VIX_CIRCUIT_BREAKER + 1),
        )
        state = orch._apply_circuit_breakers(state)
        assert state.proposals[0].position_size_pct == pytest.approx(1.0)
        assert state.proposals[1].position_size_pct == pytest.approx(1.5)

    def test_vix_above_threshold_adds_alert(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal()],
            regime=_make_regime(vix=45.0),
        )
        state = orch._apply_circuit_breakers(state)
        assert any("VIX" in a and "circuit breaker" in a for a in state.alerts)

    def test_vix_below_threshold_unchanged(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal(size_pct=2.0)],
            regime=_make_regime(vix=VIX_CIRCUIT_BREAKER - 1),
        )
        state = orch._apply_circuit_breakers(state)
        assert state.proposals[0].position_size_pct == pytest.approx(2.0)
        assert not any("VIX" in a and "circuit breaker" in a for a in state.alerts)

    def test_vix_at_exact_threshold_no_trigger(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal(size_pct=2.0)],
            regime=_make_regime(vix=VIX_CIRCUIT_BREAKER),
        )
        state = orch._apply_circuit_breakers(state)
        assert state.proposals[0].position_size_pct == pytest.approx(2.0)

    def test_empty_proposals_no_crash(self):
        orch = Orchestrator()
        state = _make_state(proposals=[], regime=_make_regime(vix=50.0))
        state = orch._apply_circuit_breakers(state)
        assert state.proposals == []


# ---------------------------------------------------------------------------
# Portfolio delta circuit breaker
# ---------------------------------------------------------------------------

class TestDeltaCircuitBreaker:
    def _high_delta_state(self, net_liq=100000):
        # delta_pct = 30000 / 100000 * 100 = 30% > MAX_PORTFOLIO_DELTA_PCT
        return _make_state(
            proposals=[_make_proposal()],
            net_liq=net_liq,
            portfolio_delta=30000.0,
        )

    def test_high_delta_blocks_normal_proposals(self):
        orch = Orchestrator()
        state = self._high_delta_state()
        state = orch._apply_circuit_breakers(state)
        assert len(state.proposals) == 0

    def test_high_delta_adds_alert(self):
        orch = Orchestrator()
        state = self._high_delta_state()
        state = orch._apply_circuit_breakers(state)
        assert any("delta" in a.lower() and "circuit breaker" in a for a in state.alerts)

    def test_high_delta_allows_madman_proposals(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[
                _make_proposal(is_madman=False),
                _make_proposal("VXX", is_madman=True),  # protective — kept
            ],
            portfolio_delta=30000.0,
        )
        state = orch._apply_circuit_breakers(state)
        assert len(state.proposals) == 1
        assert state.proposals[0].is_madman

    def test_normal_delta_allows_all_proposals(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal(), _make_proposal("QQQ")],
            portfolio_delta=5000.0,  # 5% — well below 25% threshold
        )
        state = orch._apply_circuit_breakers(state)
        assert len(state.proposals) == 2

    def test_negative_delta_also_triggers(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal()],
            portfolio_delta=-30000.0,  # same magnitude, opposite direction
        )
        state = orch._apply_circuit_breakers(state)
        assert len(state.proposals) == 0


# ---------------------------------------------------------------------------
# Sector BP cap in _apply_constraints
# ---------------------------------------------------------------------------

class TestSectorBpCap:
    def test_sector_cap_blocks_over_limit_proposal(self):
        orch = Orchestrator()
        # Already have 28% in "broad" sector (SPY + IWM)
        state = _make_state(
            proposals=[_make_proposal("SPY", size_pct=5.0)],  # would push broad to 33%
            open_positions=[
                {"symbol": "SPY", "position_size_pct": 15.0},
                {"symbol": "IWM", "position_size_pct": 13.0},
            ],
        )
        state.regime = _make_regime()
        state = orch._apply_constraints(state)
        assert len(state.proposals) == 0
        assert any("sector" in a.lower() for a in state.alerts)

    def test_sector_cap_allows_different_sector(self):
        orch = Orchestrator()
        # Broad is at cap, but metals has room
        state = _make_state(
            proposals=[_make_proposal("GLD", size_pct=2.0)],  # metals — unconstrained
            open_positions=[
                {"symbol": "SPY", "position_size_pct": 30.0},  # broad at cap
            ],
        )
        state.regime = _make_regime()
        state = orch._apply_constraints(state)
        assert len(state.proposals) == 1
        assert state.proposals[0].symbol == "GLD"

    def test_sector_cap_accumulates_across_proposals(self):
        orch = Orchestrator()
        # Existing 16% broad, plus three 5% proposals:
        # proposal 1: 16+5=21 ≤ 30 → ok
        # proposal 2: 21+5=26 ≤ 30 → ok
        # proposal 3: 26+5=31 > 30 → blocked
        state = _make_state(
            proposals=[
                _make_proposal("SPY", size_pct=5.0),
                _make_proposal("IWM", size_pct=5.0),
                _make_proposal("DIA", size_pct=5.0),  # would hit 31% → blocked
            ],
            open_positions=[{"symbol": "VTI", "position_size_pct": 16.0}],
        )
        state.regime = _make_regime()
        state = orch._apply_constraints(state)
        symbols = [p.symbol for p in state.proposals]
        assert "DIA" not in symbols
        assert len(state.proposals) == 2

    def test_existing_positions_count_toward_sector(self):
        orch = Orchestrator()
        state = _make_state(
            proposals=[_make_proposal("QQQ", size_pct=2.0)],
            open_positions=[
                {"symbol": "XLK", "position_size_pct": 29.0},  # tech at 29%
            ],
        )
        state.regime = _make_regime()
        state = orch._apply_constraints(state)
        # 29 + 2 = 31 > 30 → blocked
        assert len(state.proposals) == 0
