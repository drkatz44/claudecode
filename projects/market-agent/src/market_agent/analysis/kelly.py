"""Kelly Criterion position sizing for options premium selling.

Kelly f* = (bp - q) / b
  where b = avg_win / avg_loss, p = win probability, q = 1 - p

Direct Kelly application to options is impractical because the risk/reward
per trade is often unfavorable in isolation (win small, lose bigger), even
when strategies are profitable in aggregate through high win rates and
active management. This module uses Kelly as a *relative ranking tool*:

1. Compute Kelly fraction from historical eval_stats (win_rate, avg_win, avg_loss)
2. Map to a size multiplier (0.5x to 1.5x of the regime's default allocation)
3. Absolute position size is always capped between min_pct and max_pct

This is consistent with a half-Kelly / fractional Kelly approach where
the maximum bet is bounded by portfolio risk rules.
"""


def kelly_fraction(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> float:
    """Full Kelly fraction (f*).

    Args:
        win_rate: Win percentage (0-100, e.g., 65 for 65%)
        avg_win_pct: Average winning trade as % of premium collected (e.g., 50)
        avg_loss_pct: Average losing trade as % of premium collected (e.g., 150)

    Returns:
        Kelly fraction in [0, 1]. Returns 0 if edge is negative.
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0 or win_rate <= 0:
        return 0.0

    p = win_rate / 100.0
    q = 1.0 - p
    b = avg_win_pct / avg_loss_pct  # Payoff ratio

    f = (b * p - q) / b
    return max(0.0, min(f, 1.0))


def half_kelly(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> float:
    """Half-Kelly fraction — standard risk management practice.

    Reduces volatility of outcomes while capturing ~75% of EV vs full Kelly.
    """
    return kelly_fraction(win_rate, avg_win_pct, avg_loss_pct) * 0.5


def kelly_size_multiplier(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> float:
    """Map Kelly edge to a position-size multiplier for the regime default.

    Maps Kelly fraction to a multiplier in [0.5, 1.5]:
        - f* <= 0         → 0.5x (negative or zero edge — reduce size)
        - 0 < f* < 0.10  → 0.75x (marginal edge)
        - 0.10 ≤ f* < 0.30 → 1.0x (normal edge — use default)
        - f* ≥ 0.30       → 1.5x (strong edge — size up slightly)

    This keeps position sizes within safe portfolio bounds regardless of the
    raw Kelly fraction's magnitude.
    """
    f = kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)

    if f <= 0:
        return 0.5
    elif f < 0.10:
        return 0.75
    elif f < 0.30:
        return 1.0
    else:
        return 1.5


def position_size_pct(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    default_pct: float,
    min_pct: float = 0.5,
    max_pct: float = 5.0,
    is_madman: bool = False,
) -> float:
    """Compute final position size as % of portfolio using Kelly-scaled default.

    Args:
        win_rate: Historical win rate 0-100
        avg_win_pct: Avg win as % of premium (e.g., 50 for 50% profit target)
        avg_loss_pct: Avg loss as % of premium (e.g., 150 for 1.5x stop)
        default_pct: Regime-based default allocation %
        min_pct: Floor position size % (default 0.5%)
        max_pct: Ceiling position size % (default 5.0%)
        is_madman: If True, hard-cap at 0.2% (asymmetric / speculative trades)

    Returns:
        Position size as % of portfolio.
    """
    if is_madman:
        return min(0.15, max_pct)  # Madman trades: 0.10-0.20% hard cap

    multiplier = kelly_size_multiplier(win_rate, avg_win_pct, avg_loss_pct)
    size = default_pct * multiplier
    return max(min_pct, min(size, max_pct))


def expected_value(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> float:
    """Expected value per trade as % of premium collected.

    Positive = edge exists, negative = avoid this setup.
    """
    p = win_rate / 100.0
    return p * avg_win_pct - (1 - p) * avg_loss_pct
