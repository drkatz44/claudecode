"""Strategy utilities.

Helpers for delta-based strike selection from option chains.
Strategy models (ShortPut, VerticalSpread, etc.) are constructed directly.
"""

from __future__ import annotations

from decimal import Decimal

from .models import OptionContract, OptionType


def find_strike_by_delta(
    chain: list[OptionContract],
    target_delta: Decimal,
    option_type: OptionType,
) -> OptionContract | None:
    """Find the contract in a chain closest to the target delta.

    Args:
        chain: List of OptionContract with greeks populated.
        target_delta: Target delta value (e.g., Decimal("-0.30") for a short put).
        option_type: Filter chain to this option type.

    Returns:
        The contract with delta closest to target, or None if chain is empty
        or no contracts have greeks.
    """
    candidates = [
        c for c in chain
        if c.option_type == option_type and c.greeks is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c.greeks.delta - target_delta))  # type: ignore[union-attr]
