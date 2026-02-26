"""Orchestrator — sequences agents and enforces portfolio constraints.

Full pipeline (Phase 2):
  RegimeDetector → TradeArchitect → TradeEvaluator → RiskMonitor → MadmanScout → Constraints

The orchestrator enforces cross-cutting constraints:
- Max buying power usage
- Max concurrent positions
- Sector/correlation limits
- Risk score ceiling
"""

import logging
from decimal import Decimal

from ..analysis.sectors import MAX_SECTOR_BP_PCT, get_sector, portfolio_sector_bp, sector_headroom
from .architect import TradeArchitect
from .evaluator import TradeEvaluator
from .madman import MadmanScout
from .regime import RegimeDetector
from .risk_monitor import RiskMonitor
from .state import PortfolioState, TradeProposal

logger = logging.getLogger(__name__)

# Portfolio-level constraints
MAX_BP_USAGE_PCT = 50.0       # Never exceed 50% BP
MAX_POSITIONS = 15            # Max concurrent open positions
MAX_SECTOR_ALLOCATION = 3     # Max proposals per symbol
MAX_SINGLE_POSITION_PCT = 5.0 # No single position > 5% of net liq
MAX_RISK_SCORE = 0.80         # Reject proposals with risk_score above this

# Circuit breakers — hard limits that override all agent outputs
VIX_CIRCUIT_BREAKER = 40.0     # Halve all position sizes when VIX spikes here
MAX_PORTFOLIO_DELTA_PCT = 25.0  # Block new proposals when portfolio is this directional


class Orchestrator:
    """Sequences sub-agents and enforces portfolio constraints.

    Usage:
        state = PortfolioState(net_liq=75000, buying_power=60000, ...)
        orchestrator = Orchestrator()
        state = orchestrator.run(state)
        # state.proposals now contains filtered, risk-checked proposals

    With evaluation (slow — backtests each proposal):
        orchestrator = Orchestrator(enable_eval=True)
        state = orchestrator.run(state)
    """

    def __init__(
        self,
        max_proposals: int = 10,
        max_bp_pct: float = MAX_BP_USAGE_PCT,
        max_positions: int = MAX_POSITIONS,
        enable_eval: bool = False,
        enable_madman: bool = True,
    ):
        self.regime_detector = RegimeDetector()
        self.trade_architect = TradeArchitect(max_proposals=max_proposals)
        self.trade_evaluator = TradeEvaluator() if enable_eval else None
        self.risk_monitor = RiskMonitor()
        self.madman_scout = MadmanScout() if enable_madman else None
        self.max_bp_pct = max_bp_pct
        self.max_positions = max_positions

    def run(self, state: PortfolioState) -> PortfolioState:
        """Run the full agent pipeline."""
        logger.info("Starting agent pipeline (eval=%s, madman=%s)...",
                    self.trade_evaluator is not None, self.madman_scout is not None)

        # Step 1: Detect regime
        state = self.regime_detector.run(state)
        if not state.regime:
            state.alerts.append("WARN: Could not detect regime — aborting pipeline")
            return state

        # Step 2: Generate proposals
        state = self.trade_architect.run(state)

        # Step 3: Historical evaluation + Kelly sizing (optional — slow)
        if self.trade_evaluator is not None:
            state = self.trade_evaluator.run(state)

        # Step 4: Risk scoring + in-trade alerts
        state = self.risk_monitor.run(state)

        # Step 5: Madman / asymmetric opportunities
        if self.madman_scout is not None:
            state = self.madman_scout.run(state)

        # Step 6: Circuit breakers — hard limits that cannot be overridden
        state = self._apply_circuit_breakers(state)

        # Step 7: Apply portfolio constraints
        state = self._apply_constraints(state)

        logger.info(
            "Pipeline complete: %d proposals, %d alerts",
            len(state.proposals), len(state.alerts),
        )

        return state

    def _apply_circuit_breakers(self, state: PortfolioState) -> PortfolioState:
        """Hard risk limits that cannot be overridden by any agent output.

        These exist because even a high-confidence model can be wrong during
        tail events — circuit breakers ensure the account survives to trade
        another day regardless of model confidence (LTCM lesson).
        """
        if not state.proposals:
            return state

        # 1. VIX spike — volatility regime uncertainty, halve all sizes
        if state.regime and state.regime.vix_level > VIX_CIRCUIT_BREAKER:
            for p in state.proposals:
                p.position_size_pct = round(p.position_size_pct * 0.5, 3)
            state.alerts.append(
                f"WARN: VIX {state.regime.vix_level:.0f} > {VIX_CIRCUIT_BREAKER:.0f} "
                "circuit breaker — all position sizes halved"
            )
            logger.warning(
                "VIX circuit breaker triggered at %.1f — position sizes halved",
                state.regime.vix_level,
            )

        # 2. Portfolio delta overload — block new directional exposure
        net_liq = float(state.net_liq)
        if net_liq > 0:
            delta_pct = abs(state.portfolio_delta) * 100 / net_liq
            if delta_pct > MAX_PORTFOLIO_DELTA_PCT:
                # Madman proposals are often protective (VIX calls, back ratios) — keep them
                rejected = [p for p in state.proposals if not p.is_madman]
                state.proposals = [p for p in state.proposals if p.is_madman]
                if rejected:
                    state.alerts.append(
                        f"WARN: Portfolio delta {delta_pct:.1f}% > {MAX_PORTFOLIO_DELTA_PCT}% "
                        f"circuit breaker — {len(rejected)} proposal(s) blocked"
                    )
                    logger.warning(
                        "Delta circuit breaker triggered: %.1f%% — blocked %d proposals",
                        delta_pct, len(rejected),
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

        # Check BP headroom — use Decimal throughout for financial precision
        bp_available = state.buying_power
        net_liq = state.net_liq
        if net_liq <= 0:
            state.proposals = []
            return state

        current_bp_usage = Decimal(str(state.bp_usage_pct))
        max_bp = Decimal(str(self.max_bp_pct))
        bp_headroom = max_bp - current_bp_usage

        if bp_headroom <= 0:
            state.alerts.append(
                f"WARN: BP usage at {state.bp_usage_pct:.1f}% — max {self.max_bp_pct}%"
            )
            state.proposals = []
            return state

        # Filter: enforce size, concentration, risk score, sector cap, and BP limits
        filtered: list[TradeProposal] = []
        symbol_count: dict[str, int] = {}
        proposal_sector_bp: dict[str, float] = {}  # accumulates across this filter pass
        existing_sector_bp = portfolio_sector_bp(state.open_positions, float(net_liq))
        cumulative_bp_pct = current_bp_usage

        for proposal in state.proposals:
            sym = proposal.symbol

            # Risk score ceiling (madman proposals bypass this — they're intentionally risky)
            if not proposal.is_madman and proposal.risk_score > MAX_RISK_SCORE:
                state.alerts.append(
                    f"INFO: {sym} {proposal.strategy_type} "
                    f"risk_score={proposal.risk_score:.2f} > {MAX_RISK_SCORE} — skipped"
                )
                continue

            # Position size check
            if proposal.position_size_pct > MAX_SINGLE_POSITION_PCT:
                continue

            # Symbol concentration
            if symbol_count.get(sym, 0) >= MAX_SECTOR_ALLOCATION:
                continue
            symbol_count[sym] = symbol_count.get(sym, 0) + 1

            # Sector BP cap — correlated positions magnify losses (LTCM lesson)
            sector = get_sector(sym)
            sector_used = (existing_sector_bp.get(sector, 0.0)
                           + proposal_sector_bp.get(sector, 0.0))
            if sector_used + proposal.position_size_pct > MAX_SECTOR_BP_PCT:
                state.alerts.append(
                    f"INFO: Skipping {sym} {proposal.strategy_type} — "
                    f"sector '{sector}' at {sector_used:.1f}% (cap {MAX_SECTOR_BP_PCT}%)"
                )
                continue
            proposal_sector_bp[sector] = proposal_sector_bp.get(sector, 0.0) + proposal.position_size_pct

            # Check if adding this would exceed total BP limit
            position_bp = net_liq * Decimal(str(proposal.position_size_pct)) / Decimal("100")
            position_bp_pct = (position_bp / bp_available * Decimal("100")) if bp_available > 0 else Decimal("100")
            if cumulative_bp_pct + position_bp_pct > max_bp:
                state.alerts.append(
                    f"INFO: Skipping {sym} {proposal.strategy_type} — would exceed BP limit"
                )
                continue
            cumulative_bp_pct += position_bp_pct

            filtered.append(proposal)

            if len(filtered) >= available_slots:
                break

        state.proposals = filtered
        return state
