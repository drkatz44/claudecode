"""Orchestrator — sequences agents and enforces portfolio constraints.

Pipeline: RegimeDetector → TradeArchitect → (future: Evaluator → RiskMonitor → MadmanScout)

The orchestrator enforces cross-cutting constraints:
- Max buying power usage
- Max concurrent positions
- Sector/correlation limits
"""

import logging
from decimal import Decimal

from .architect import TradeArchitect
from .regime import RegimeDetector
from .state import PortfolioState, TradeProposal

logger = logging.getLogger(__name__)

# Portfolio-level constraints
MAX_BP_USAGE_PCT = 50.0       # Never exceed 50% BP
MAX_POSITIONS = 15            # Max concurrent open positions
MAX_SECTOR_ALLOCATION = 3     # Max proposals per sector/underlying
MAX_SINGLE_POSITION_PCT = 5.0 # No single position > 5% of net liq


class Orchestrator:
    """Sequences sub-agents and enforces portfolio constraints.

    Usage:
        state = PortfolioState(net_liq=75000, buying_power=60000, ...)
        orchestrator = Orchestrator()
        state = orchestrator.run(state)
        # state.proposals now contains filtered, risk-checked proposals
    """

    def __init__(
        self,
        max_proposals: int = 10,
        max_bp_pct: float = MAX_BP_USAGE_PCT,
        max_positions: int = MAX_POSITIONS,
    ):
        self.regime_detector = RegimeDetector()
        self.trade_architect = TradeArchitect(max_proposals=max_proposals)
        self.max_bp_pct = max_bp_pct
        self.max_positions = max_positions

    def run(self, state: PortfolioState) -> PortfolioState:
        """Run the full agent pipeline."""
        logger.info("Starting agent pipeline...")

        # Step 1: Detect regime
        state = self.regime_detector.run(state)
        if not state.regime:
            state.alerts.append("WARN: Could not detect regime — aborting pipeline")
            return state

        # Step 2: Generate proposals
        state = self.trade_architect.run(state)

        # Step 3: Apply portfolio constraints
        state = self._apply_constraints(state)

        logger.info(
            "Pipeline complete: %d proposals, %d alerts",
            len(state.proposals), len(state.alerts),
        )

        return state

    def _apply_constraints(self, state: PortfolioState) -> PortfolioState:
        """Filter proposals by portfolio-level constraints."""
        current_positions = len(state.open_positions)
        available_slots = max(0, self.max_positions - current_positions)

        if available_slots == 0:
            state.alerts.append("WARN: Max positions reached — no new trades")
            state.proposals = []
            return state

        # Check BP headroom
        bp_available = float(state.buying_power)
        net_liq = float(state.net_liq)
        if net_liq <= 0:
            state.proposals = []
            return state

        current_bp_usage = state.bp_usage_pct
        bp_headroom = self.max_bp_pct - current_bp_usage

        if bp_headroom <= 0:
            state.alerts.append(
                f"WARN: BP usage at {current_bp_usage:.1f}% — max {self.max_bp_pct}%"
            )
            state.proposals = []
            return state

        # Filter: no single position > MAX_SINGLE_POSITION_PCT
        filtered: list[TradeProposal] = []
        symbol_count: dict[str, int] = {}

        for proposal in state.proposals:
            # Position size check
            if proposal.position_size_pct > MAX_SINGLE_POSITION_PCT:
                continue

            # Sector/symbol concentration
            sym = proposal.symbol
            if symbol_count.get(sym, 0) >= MAX_SECTOR_ALLOCATION:
                continue
            symbol_count[sym] = symbol_count.get(sym, 0) + 1

            # Check if adding this would exceed BP limit
            position_bp = net_liq * proposal.position_size_pct / 100
            if current_bp_usage + (position_bp / bp_available * 100 if bp_available > 0 else 100) > self.max_bp_pct:
                state.alerts.append(
                    f"INFO: Skipping {sym} {proposal.strategy_type} — would exceed BP limit"
                )
                continue

            filtered.append(proposal)

            if len(filtered) >= available_slots:
                break

        state.proposals = filtered
        return state
