"""High-level strategy construction from parsed option chains.

Takes a parsed chain (list of OptionContract with optional greeks) and
user-specified parameters, and produces ready-to-submit strategy models.

All functions return a dict with:
  - "strategy": the strategy model (e.g. IronCondor)
  - "legs": list[dict] ready for MCP place_order(legs=[...])
  - "risk": dict with max_profit, max_loss, breakevens, risk_reward_ratio
  - "summary": human-readable description

Design principle: no MCP calls here. This is pure data transformation.
The caller (agent or CLI) is responsible for fetching chain + greeks data.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import (
    IronCondor,
    OptionContract,
    OptionType,
    ShortPut,
    Strangle,
    VerticalSpread,
    Direction,
)
from .strategies import find_strike_by_delta


class ChainBuilderError(Exception):
    """Raised when a strategy cannot be constructed from the given chain."""


def _require(contract: OptionContract | None, description: str) -> OptionContract:
    if contract is None:
        raise ChainBuilderError(f"Could not find strike for: {description}")
    return contract


def _legs_dict(strategy: Any) -> list[dict]:
    """Convert strategy order legs to dicts for MCP place_order."""
    return [leg.model_dump(exclude_none=True) for leg in strategy.to_order_legs()]


def _risk_dict(strategy: Any) -> dict:
    rp = strategy.risk_profile()
    return {
        "max_profit": float(rp.max_profit),
        "max_loss": float(rp.max_loss),
        "breakevens": [float(b) for b in rp.breakevens],
        "risk_reward_ratio": float(rp.risk_reward_ratio) if rp.risk_reward_ratio else None,
    }


# ---------------------------------------------------------------------------
# Short Put
# ---------------------------------------------------------------------------

def build_short_put(
    chain: list[OptionContract],
    underlying: str,
    expiration_date: str,
    target_delta: Decimal = Decimal("0.30"),
    quantity: int = 1,
) -> dict:
    """Construct a short put at the strike closest to target_delta.

    Args:
        chain: OptionContract list for the target expiration, greeks populated.
        underlying: Underlying symbol.
        expiration_date: Target expiration (YYYY-MM-DD).
        target_delta: Absolute delta target (e.g., 0.30 for a 30-delta put).
            Internally negated for put selection.
        quantity: Number of contracts.

    Returns:
        Dict with strategy, legs, risk, summary.
    """
    put = _require(
        find_strike_by_delta(chain, -abs(target_delta), OptionType.PUT),
        f"short put near {target_delta} delta",
    )
    credit = put.greeks.price if put.greeks else None
    strategy = ShortPut(
        underlying=underlying,
        expiration_date=expiration_date,
        strike=put.strike_price,
        quantity=quantity,
        credit=credit,
    )
    delta_str = f"{put.greeks.delta:.2f}" if put.greeks else "unknown"
    return {
        "strategy_type": "short_put",
        "underlying": underlying,
        "expiration_date": expiration_date,
        "strike": float(put.strike_price),
        "delta": delta_str,
        "credit": float(credit) if credit else None,
        "quantity": quantity,
        "legs": _legs_dict(strategy),
        "risk": _risk_dict(strategy),
        "summary": (
            f"Short Put: {underlying} {expiration_date} "
            f"{put.strike_price}P x{quantity} @ {credit or 'mkt'}"
        ),
    }


# ---------------------------------------------------------------------------
# Vertical Spread
# ---------------------------------------------------------------------------

def build_vertical_spread(
    chain: list[OptionContract],
    underlying: str,
    expiration_date: str,
    option_type: OptionType,
    direction: Direction,
    short_delta: Decimal = Decimal("0.30"),
    long_delta: Decimal = Decimal("0.16"),
    quantity: int = 1,
) -> dict:
    """Construct a vertical spread (bull put or bear call).

    Args:
        chain: OptionContract list for the target expiration, greeks populated.
        underlying: Underlying symbol.
        expiration_date: Target expiration (YYYY-MM-DD).
        option_type: PUT (bull put spread) or CALL (bear call spread).
        direction: BULLISH or BEARISH.
        short_delta: Delta of the short strike (closer to ATM).
        long_delta: Delta of the long strike (further OTM, wing).
        quantity: Number of spreads.

    Returns:
        Dict with strategy, legs, risk, summary.
    """
    neg = option_type == OptionType.PUT

    short = _require(
        find_strike_by_delta(
            chain,
            -abs(short_delta) if neg else abs(short_delta),
            option_type,
        ),
        f"short {option_type.value} near {short_delta} delta",
    )
    long = _require(
        find_strike_by_delta(
            chain,
            -abs(long_delta) if neg else abs(long_delta),
            option_type,
        ),
        f"long {option_type.value} near {long_delta} delta",
    )

    if short.strike_price == long.strike_price:
        raise ChainBuilderError(
            f"Short and long strikes are the same ({short.strike_price}). "
            "Widen delta targets."
        )

    # Credit = short premium - long premium
    credit: Decimal | None = None
    if short.greeks and long.greeks:
        credit = short.greeks.price - long.greeks.price

    strategy = VerticalSpread(
        underlying=underlying,
        expiration_date=expiration_date,
        short_strike=short.strike_price,
        long_strike=long.strike_price,
        option_type=option_type,
        direction=direction,
        quantity=quantity,
        credit=credit,
    )
    width = abs(short.strike_price - long.strike_price)
    return {
        "strategy_type": "vertical_spread",
        "underlying": underlying,
        "expiration_date": expiration_date,
        "option_type": option_type.value,
        "direction": direction.value,
        "short_strike": float(short.strike_price),
        "long_strike": float(long.strike_price),
        "width": float(width),
        "credit": float(credit) if credit else None,
        "quantity": quantity,
        "legs": _legs_dict(strategy),
        "risk": _risk_dict(strategy),
        "summary": (
            f"{'Bull Put' if neg else 'Bear Call'} Spread: {underlying} "
            f"{expiration_date} {short.strike_price}/{long.strike_price} "
            f"x{quantity} @ {credit or 'mkt'}"
        ),
    }


# ---------------------------------------------------------------------------
# Iron Condor
# ---------------------------------------------------------------------------

def build_iron_condor(
    chain: list[OptionContract],
    underlying: str,
    expiration_date: str,
    put_short_delta: Decimal = Decimal("0.16"),
    put_long_delta: Decimal = Decimal("0.08"),
    call_short_delta: Decimal = Decimal("0.16"),
    call_long_delta: Decimal = Decimal("0.08"),
    quantity: int = 1,
) -> dict:
    """Construct an iron condor (bull put spread + bear call spread).

    Args:
        chain: OptionContract list for the target expiration, greeks populated.
        underlying: Underlying symbol.
        expiration_date: Target expiration (YYYY-MM-DD).
        put_short_delta: Delta of the short put (e.g., 0.16).
        put_long_delta: Delta of the long put wing (e.g., 0.08).
        call_short_delta: Delta of the short call (e.g., 0.16).
        call_long_delta: Delta of the long call wing (e.g., 0.08).
        quantity: Number of condors.

    Returns:
        Dict with strategy, legs, risk, summary.
    """
    put_short = _require(
        find_strike_by_delta(chain, -abs(put_short_delta), OptionType.PUT),
        f"short put near {put_short_delta} delta",
    )
    put_long = _require(
        find_strike_by_delta(chain, -abs(put_long_delta), OptionType.PUT),
        f"long put near {put_long_delta} delta",
    )
    call_short = _require(
        find_strike_by_delta(chain, abs(call_short_delta), OptionType.CALL),
        f"short call near {call_short_delta} delta",
    )
    call_long = _require(
        find_strike_by_delta(chain, abs(call_long_delta), OptionType.CALL),
        f"long call near {call_long_delta} delta",
    )

    credit: Decimal | None = None
    if all(c.greeks for c in [put_short, put_long, call_short, call_long]):
        credit = (
            put_short.greeks.price - put_long.greeks.price  # type: ignore[union-attr]
            + call_short.greeks.price - call_long.greeks.price  # type: ignore[union-attr]
        )

    strategy = IronCondor(
        underlying=underlying,
        expiration_date=expiration_date,
        put_long_strike=put_long.strike_price,
        put_short_strike=put_short.strike_price,
        call_short_strike=call_short.strike_price,
        call_long_strike=call_long.strike_price,
        quantity=quantity,
        credit=credit,
    )
    put_width = put_short.strike_price - put_long.strike_price
    call_width = call_long.strike_price - call_short.strike_price
    return {
        "strategy_type": "iron_condor",
        "underlying": underlying,
        "expiration_date": expiration_date,
        "put_strikes": {
            "short": float(put_short.strike_price),
            "long": float(put_long.strike_price),
            "width": float(put_width),
        },
        "call_strikes": {
            "short": float(call_short.strike_price),
            "long": float(call_long.strike_price),
            "width": float(call_width),
        },
        "credit": float(credit) if credit else None,
        "quantity": quantity,
        "legs": _legs_dict(strategy),
        "risk": _risk_dict(strategy),
        "summary": (
            f"Iron Condor: {underlying} {expiration_date} "
            f"{put_long.strike_price}/{put_short.strike_price}/"
            f"{call_short.strike_price}/{call_long.strike_price} "
            f"x{quantity} @ {credit or 'mkt'}"
        ),
    }


# ---------------------------------------------------------------------------
# Strangle
# ---------------------------------------------------------------------------

def build_strangle(
    chain: list[OptionContract],
    underlying: str,
    expiration_date: str,
    put_delta: Decimal = Decimal("0.25"),
    call_delta: Decimal = Decimal("0.25"),
    quantity: int = 1,
) -> dict:
    """Construct a short strangle (short OTM put + short OTM call).

    Args:
        chain: OptionContract list for the target expiration, greeks populated.
        underlying: Underlying symbol.
        expiration_date: Target expiration (YYYY-MM-DD).
        put_delta: Absolute delta for the short put (e.g., 0.25).
        call_delta: Absolute delta for the short call (e.g., 0.25).
        quantity: Number of strangles.

    Returns:
        Dict with strategy, legs, risk, summary.
    """
    put = _require(
        find_strike_by_delta(chain, -abs(put_delta), OptionType.PUT),
        f"short put near {put_delta} delta",
    )
    call = _require(
        find_strike_by_delta(chain, abs(call_delta), OptionType.CALL),
        f"short call near {call_delta} delta",
    )

    credit: Decimal | None = None
    if put.greeks and call.greeks:
        credit = put.greeks.price + call.greeks.price

    strategy = Strangle(
        underlying=underlying,
        expiration_date=expiration_date,
        put_strike=put.strike_price,
        call_strike=call.strike_price,
        quantity=quantity,
        credit=credit,
    )
    return {
        "strategy_type": "strangle",
        "underlying": underlying,
        "expiration_date": expiration_date,
        "put_strike": float(put.strike_price),
        "call_strike": float(call.strike_price),
        "credit": float(credit) if credit else None,
        "quantity": quantity,
        "legs": _legs_dict(strategy),
        "risk": _risk_dict(strategy),
        "summary": (
            f"Strangle: {underlying} {expiration_date} "
            f"{put.strike_price}P/{call.strike_price}C "
            f"x{quantity} @ {credit or 'mkt'}"
        ),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

BUILDERS = {
    "short_put": build_short_put,
    "vertical_spread": build_vertical_spread,
    "iron_condor": build_iron_condor,
    "strangle": build_strangle,
}
