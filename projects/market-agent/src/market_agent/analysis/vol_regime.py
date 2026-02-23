"""VIX regime classification and volatility term structure analysis."""

import numpy as np

from ..agents.state import VolRegime
from ..data.models import Bar


def classify_regime(vix_level: float) -> VolRegime:
    """Classify market regime based on VIX level.

    Thresholds:
        < 15  → LOW  (complacency, sell calendars/diagonals)
        15-25 → NORMAL (bread-and-butter premium selling)
        > 25  → HIGH (wide strikes, jade lizards, back ratios)
    """
    if vix_level < 15:
        return VolRegime.LOW
    elif vix_level <= 25:
        return VolRegime.NORMAL
    else:
        return VolRegime.HIGH


def vix_term_structure(vix_spot: float, vx1_price: float, threshold: float = 0.02) -> str:
    """Determine VIX term structure from spot vs front-month futures.

    Args:
        vix_spot: Current VIX spot level.
        vx1_price: VX1 (front-month VIX futures) price.
        threshold: Minimum spread ratio to classify (default 2%).

    Returns:
        "contango" if VX1 > VIX spot (normal, mean-reverting fear)
        "backwardation" if VX1 < VIX spot (elevated fear, hedging demand)
        "flat" if within threshold
    """
    if vx1_price <= 0 or vix_spot <= 0:
        return "flat"

    spread_ratio = (vx1_price - vix_spot) / vix_spot

    if spread_ratio > threshold:
        return "contango"
    elif spread_ratio < -threshold:
        return "backwardation"
    return "flat"


def compute_ivx(bars: list[Bar], period: int = 30) -> float:
    """Compute 30-day expected move (IVx proxy) from price bars.

    Uses realized volatility annualized, then converts to expected move
    for the given period. This approximates the IVx metric.

    Args:
        bars: Historical price bars (need at least period+1).
        period: Lookback period in trading days.

    Returns:
        Expected percentage move over `period` days (e.g., 5.2 means 5.2%).
    """
    if len(bars) < period + 1:
        return 0.0

    closes = [float(b.close) for b in bars[-(period + 1):]]
    log_returns = np.diff(np.log(closes))

    if len(log_returns) == 0:
        return 0.0

    daily_vol = float(np.std(log_returns))
    annualized_vol = daily_vol * np.sqrt(252)

    # Expected move for the period: annual_vol * sqrt(period/252)
    expected_move_pct = annualized_vol * np.sqrt(period / 252) * 100
    return round(expected_move_pct, 2)


def vix_change(bars: list[Bar], lookback: int = 5) -> float:
    """Calculate VIX percentage change over lookback period.

    Args:
        bars: VIX price bars.
        lookback: Number of bars to look back.

    Returns:
        Percentage change (e.g., 15.3 means VIX rose 15.3%).
    """
    if len(bars) < lookback + 1:
        return 0.0

    current = float(bars[-1].close)
    previous = float(bars[-(lookback + 1)].close)

    if previous <= 0:
        return 0.0

    return round((current - previous) / previous * 100, 2)
