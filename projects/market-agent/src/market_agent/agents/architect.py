"""Trade Architect agent.

Constructs concrete trade proposals based on current regime,
scanning the futures + ETF universe for opportunities.
"""

import logging
from decimal import Decimal

from .. import validate_symbol
from ..analysis.options import iv_rank, options_summary, resolve_strategy
from ..analysis.vol_regime import compute_ivx
from ..data.fetcher import get_bars
from ..data.futures import ETF_UNIVERSE, FUTURES_UNIVERSE, is_futures
from .state import PortfolioState, TradeProposal, VolRegime

logger = logging.getLogger(__name__)

# Regime → strategy mapping with BP limits and position sizing
REGIME_PLAYBOOK: dict[VolRegime, dict] = {
    VolRegime.LOW: {
        "strategies": ["calendar", "diagonal", "vertical_spread", "bwb"],
        "bp_limit_pct": 40.0,
        "position_size_pct": 1.5,
        "min_ivr": 15,
        "delta_target": 0.20,
        "dte_range": (30, 60),
        "profit_target_pct": 50.0,
        "rationale_prefix": "Low vol regime — favor time spreads and defined risk",
    },
    VolRegime.NORMAL: {
        "strategies": ["strangle", "iron_condor", "vertical_spread", "jade_lizard"],
        "bp_limit_pct": 50.0,
        "position_size_pct": 2.0,
        "min_ivr": 25,
        "delta_target": 0.16,
        "dte_range": (30, 45),
        "profit_target_pct": 50.0,
        "rationale_prefix": "Normal vol regime — standard premium selling",
    },
    VolRegime.HIGH: {
        "strategies": ["strangle", "jade_lizard", "back_ratio", "bwb"],
        "bp_limit_pct": 50.0,
        "position_size_pct": 2.5,
        "min_ivr": 25,
        "delta_target": 0.20,  # Wider strikes in high vol
        "dte_range": (30, 60),
        "profit_target_pct": 50.0,
        "rationale_prefix": "High vol regime — wide strikes, convexity plays",
    },
}


class TradeArchitect:
    """Constructs trade proposals for the current regime.

    Reads: state.regime, state.scan_symbols
    Writes: state.proposals
    """

    def __init__(self, max_proposals: int = 10):
        self.max_proposals = max_proposals

    def run(self, state: PortfolioState) -> PortfolioState:
        """Scan universe and build trade proposals."""
        if not state.regime:
            logger.warning("No regime state — run RegimeDetector first")
            return state

        regime = state.regime.regime
        playbook = REGIME_PLAYBOOK[regime]
        symbols = state.scan_symbols or self._default_universe()

        proposals: list[TradeProposal] = []

        for symbol in symbols:
            try:
                symbol = validate_symbol(symbol)
            except ValueError:
                logger.warning("Invalid symbol skipped: %s", symbol)
                continue

            try:
                proposal = self._evaluate_symbol(symbol, regime, playbook)
                if proposal:
                    proposals.append(proposal)
            except (ValueError, KeyError, TypeError):
                logger.exception("Error evaluating %s", symbol)

        # Sort by IVR (highest first) and cap
        proposals.sort(key=lambda p: p.risk_score, reverse=False)
        state.proposals = proposals[:self.max_proposals]

        logger.info(
            "Architect: %d proposals from %d symbols scanned (regime=%s)",
            len(state.proposals), len(symbols), regime.value,
        )

        return state

    def _evaluate_symbol(
        self, symbol: str, regime: VolRegime, playbook: dict,
    ) -> TradeProposal | None:
        """Evaluate a single symbol for trade opportunity."""
        bars = get_bars(symbol, period="1y", interval="1d")
        if not bars or len(bars) < 50:
            return None

        # Get current IV info
        summary = options_summary(symbol)
        if not summary:
            return None

        ivr = summary["iv_rank"]
        if ivr < playbook["min_ivr"]:
            return None  # IV too low for premium selling

        underlying_price = Decimal(str(summary["underlying_price"]))
        ivx = compute_ivx(bars)

        # Try strategies in playbook order until one resolves
        for strategy_type in playbook["strategies"]:
            resolved = resolve_strategy(
                symbol=symbol,
                strategy_type=strategy_type,
                underlying_price=underlying_price,
                delta_target=playbook["delta_target"],
                dte_range=playbook["dte_range"],
            )
            if not resolved:
                continue

            rationale = [
                playbook["rationale_prefix"],
                f"IVR: {ivr:.0f} (min {playbook['min_ivr']})",
                f"IVx: {ivx:.1f}%",
                f"VIX: {regime.value}",
            ]

            skew = summary.get("skew", {})
            if skew.get("skew_direction") == "put_skew":
                rationale.append(f"Put skew: {skew.get('magnitude', 0):.1f}pts")

            return TradeProposal(
                symbol=symbol,
                strategy_type=strategy_type,
                legs=resolved.get("legs", []),
                regime=regime,
                position_size_pct=playbook["position_size_pct"],
                profit_target_pct=playbook["profit_target_pct"],
                max_dte=playbook["dte_range"][1],
                rationale=rationale,
                credit=resolved.get("credit"),
                max_loss=resolved.get("max_loss"),
                breakevens=resolved.get("breakevens", []),
            )

        return None

    def _default_universe(self) -> list[str]:
        """Return the default scanning universe (ETFs only — futures need special handling)."""
        return ETF_UNIVERSE
