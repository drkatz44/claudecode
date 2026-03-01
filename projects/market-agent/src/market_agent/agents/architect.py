"""Trade Architect agent.

Constructs concrete trade proposals based on current regime,
scanning the futures + ETF universe for opportunities.
"""

import logging
from decimal import Decimal

from .. import validate_symbol
from ..analysis.kelly import atr_position_size_pct
from ..analysis.options import iv_rank, options_summary, resolve_strategy
from ..analysis.technical import atr as compute_atr, historical_volatility as compute_hv
from ..analysis.vol_regime import compute_ivx
from ..data.fetcher import get_bars
from ..data.futures import ETF_UNIVERSE, FUTURES_UNIVERSE, is_futures
from .state import PortfolioState, RegimeState, TradeProposal, VolRegime

logger = logging.getLogger(__name__)

# IV/RV spread: minimum premium of implied over 20-day realized vol (pct points)
# Replaces IVR > 50 hard gate — measures actual variance risk premium, not relative rank
IV_RV_MIN_SPREAD = 3.0

# VVIX: when vol-of-vol is this elevated the timing of any VIX move is too uncertain
VVIX_SUPPRESS_THRESHOLD = 125.0

# High-conviction flag: VIX must still be elevated enough to have premium worth selling
HIGH_CONVICTION_MIN_VIX = 18.0


# Regime → strategy mapping with BP limits and position sizing
REGIME_PLAYBOOK: dict[VolRegime, dict] = {
    VolRegime.LOW: {
        "strategies": ["calendar", "diagonal", "vertical_spread", "bwb"],
        "bp_limit_pct": 40.0,
        "position_size_pct": 1.5,
        "delta_target": 0.20,
        "dte_range": (30, 60),
        "profit_target_pct": 50.0,
        "rationale_prefix": "Low vol regime — favor time spreads and defined risk",
    },
    VolRegime.NORMAL: {
        "strategies": ["strangle", "iron_condor", "vertical_spread", "jade_lizard"],
        "bp_limit_pct": 50.0,
        "position_size_pct": 2.0,
        "delta_target": 0.16,
        "dte_range": (38, 52),  # TastyTrade empirical data: 45 DTE midpoint is optimal
        "profit_target_pct": 50.0,
        "rationale_prefix": "Normal vol regime — standard premium selling",
    },
    VolRegime.HIGH: {
        "strategies": ["strangle", "jade_lizard", "back_ratio", "bwb"],
        "bp_limit_pct": 50.0,
        "position_size_pct": 2.5,
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

        # --- Entry suppression gates ---
        # Backwardation + rising VIX = selling into accelerating fear — worst possible entry
        if (state.regime.vix_term_structure == "backwardation"
                and state.regime.vix_5d_change > 0):
            state.alerts.append(
                f"WARN: Backwardation + rising VIX ({state.regime.vix_5d_change:+.1f}% 5d) "
                "— suppressing proposals (worst entry conditions)"
            )
            logger.warning(
                "Proposal suppression: backwardation + rising VIX (%.1f%%)",
                state.regime.vix_5d_change,
            )
            return state

        # VVIX meta-filter: when vol-of-vol is extreme, even the direction of VIX is uncertain
        if state.regime.vvix_level > VVIX_SUPPRESS_THRESHOLD:
            state.alerts.append(
                f"WARN: VVIX {state.regime.vvix_level:.0f} > {VVIX_SUPPRESS_THRESHOLD:.0f} "
                "— vol-of-vol too elevated, suppressing proposals"
            )
            logger.warning("Proposal suppression: VVIX %.0f", state.regime.vvix_level)
            return state

        # High-conviction flag: vol regime transitioning favourably
        high_conviction = self._is_high_conviction(state.regime)

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
                    proposal.high_conviction = high_conviction
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

        # IV/RV spread: actual variance risk premium — measures the edge, not relative history
        current_iv = summary.get("current_iv", 0.0) or 0.0
        if current_iv <= 0:
            return None
        hv_series = compute_hv(bars, period=20)
        hv_valid = hv_series.dropna()
        realized_vol_pct = float(hv_valid.iloc[-1]) * 100 if not hv_valid.empty else 0.0
        iv_rv_spread = current_iv - realized_vol_pct
        if iv_rv_spread < IV_RV_MIN_SPREAD:
            return None  # No meaningful variance risk premium — edge is not there

        underlying_price = Decimal(str(summary["underlying_price"]))
        ivx = compute_ivx(bars)

        # ATR-normalized position sizing — equal expected daily dollar risk per position
        atr_series = compute_atr(bars, period=20)
        atr_valid = atr_series.dropna()
        if not atr_valid.empty and float(underlying_price) > 0:
            atr_pct = float(atr_valid.iloc[-1]) / float(underlying_price) * 100
            sized_pct = atr_position_size_pct(
                atr_pct=atr_pct,
                regime_default_pct=playbook["position_size_pct"],
            )
        else:
            sized_pct = playbook["position_size_pct"]

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
                f"IVR: {ivr:.0f} | IV/RV spread: {iv_rv_spread:.1f}pts",
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
                position_size_pct=sized_pct,
                profit_target_pct=playbook["profit_target_pct"],
                max_dte=playbook["dte_range"][1],
                rationale=rationale,
                credit=resolved.get("credit"),
                max_loss=resolved.get("max_loss"),
                breakevens=resolved.get("breakevens", []),
            )

        return None

    def _is_high_conviction(self, regime: RegimeState) -> bool:
        """Return True when vol regime is transitioning favorably for short-vol entry.

        High conviction = contango/flat term structure + VIX falling + enough premium.
        This is the backwardation→contango recovery signal: fear is subsiding but IV
        is still elevated enough to sell.
        """
        return (
            regime.vix_term_structure in ("contango", "flat")
            and regime.vix_5d_change < 0
            and regime.vix_level >= HIGH_CONVICTION_MIN_VIX
        )

    def _default_universe(self) -> list[str]:
        """Return the default scanning universe (ETFs only — futures need special handling)."""
        return ETF_UNIVERSE
