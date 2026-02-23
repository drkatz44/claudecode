"""Regime Detector agent.

Fetches VIX data, classifies the current volatility regime,
and writes RegimeState to PortfolioState.
"""

import logging

from ..analysis.options import iv_rank
from ..analysis.vol_regime import classify_regime, compute_ivx, vix_change, vix_term_structure
from ..data.fetcher import get_bars
from .state import PortfolioState, RegimeState

logger = logging.getLogger(__name__)

# VIX futures front-month proxy (VX1) — yfinance ticker
VIX_TICKER = "^VIX"
VIX_FUTURES_PROXY = "^VIX"  # yfinance doesn't have VX futures; use VIX as proxy


class RegimeDetector:
    """Detects the current volatility regime from VIX and IV metrics.

    Reads: nothing (fetches its own data)
    Writes: state.regime
    """

    def run(self, state: PortfolioState) -> PortfolioState:
        """Fetch VIX, compute regime, and update state."""
        bars = get_bars(VIX_TICKER, period="6mo", interval="1d")
        if not bars or len(bars) < 30:
            logger.warning("Insufficient VIX data for regime detection")
            return state

        vix_level = float(bars[-1].close)
        regime = classify_regime(vix_level)
        vix_5d = vix_change(bars, lookback=5)
        ivx = compute_ivx(bars, period=30)

        # IV rank of VIX itself (how elevated is vol relative to its own history)
        current_iv_proxy = float(bars[-1].close) / 100  # VIX as decimal
        ivr = iv_rank(bars, current_iv_proxy, period=252)

        # Previous IVR for 5d change
        if len(bars) > 5:
            prev_bars = bars[:-5]
            prev_iv_proxy = float(prev_bars[-1].close) / 100
            prev_ivr = iv_rank(prev_bars, prev_iv_proxy, period=252)
            ivr_5d_change = ivr - prev_ivr
        else:
            ivr_5d_change = 0.0

        # Term structure: compare current VIX to 3-month VIX (VIX3M proxy)
        # yfinance doesn't have VIX futures, use VIX vs its 20-day SMA as proxy
        vix_sma20 = sum(float(b.close) for b in bars[-20:]) / 20
        term = vix_term_structure(vix_level, vix_sma20)

        state.regime = RegimeState(
            vix_level=vix_level,
            vix_5d_change=vix_5d,
            regime=regime,
            ivr=ivr,
            ivx=ivx,
            ivr_5d_change=ivr_5d_change,
            vix_term_structure=term,
        )

        logger.info(
            "Regime: %s | VIX: %.1f | IVR: %.1f | IVx: %.1f%% | Term: %s",
            regime.value, vix_level, ivr, ivx, term,
        )

        return state
