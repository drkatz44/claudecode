"""Parse raw tastytrade option chain and greeks responses into internal models.

The tastytrade API returns nested option chains in a structure grouped by
expiration, then by strike. Greeks are fetched separately. This module
handles both formats and assembles OptionContract objects with greeks attached.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import OptionContract, OptionGreeks, OptionType


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _get(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


# ---------------------------------------------------------------------------
# Expiration selection
# ---------------------------------------------------------------------------

def find_expiration_by_dte(
    expirations: list[dict],
    target_dte: int,
) -> dict | None:
    """Return the expiration dict closest to target_dte.

    Args:
        expirations: List of expiration dicts from the nested chain response.
            Each must have a ``days-to-expiration`` or ``dte`` field.
        target_dte: Desired days to expiration (e.g., 45).

    Returns:
        The expiration dict closest to target_dte, or None if list is empty.
    """
    if not expirations:
        return None

    def dte(exp: dict) -> int:
        raw = _get(exp, "days-to-expiration", "daysToExpiration", "dte")
        try:
            return int(raw) if raw is not None else 0
        except (ValueError, TypeError):
            return 0

    return min(expirations, key=lambda e: abs(dte(e) - target_dte))


# ---------------------------------------------------------------------------
# Greeks parsing
# ---------------------------------------------------------------------------

def _parse_greeks(raw: dict) -> OptionGreeks | None:
    """Parse a single greeks dict (from MCP get_greeks or DXLink Greeks event)."""
    price = _dec(_get(raw, "price", "mark", "mid", "theo"))
    iv = _dec(_get(raw, "implied-volatility", "volatility", "implied_volatility", "iv"))
    delta = _dec(_get(raw, "delta"))
    gamma = _dec(_get(raw, "gamma"))
    theta = _dec(_get(raw, "theta"))
    rho = _dec(_get(raw, "rho"))
    vega = _dec(_get(raw, "vega"))

    # All fields required for OptionGreeks
    if any(v is None for v in [price, iv, delta, gamma, theta, rho, vega]):
        return None

    return OptionGreeks(
        price=price,  # type: ignore[arg-type]
        implied_volatility=iv,  # type: ignore[arg-type]
        delta=delta,  # type: ignore[arg-type]
        gamma=gamma,  # type: ignore[arg-type]
        theta=theta,  # type: ignore[arg-type]
        rho=rho,  # type: ignore[arg-type]
        vega=vega,  # type: ignore[arg-type]
    )


def parse_greeks_response(response: dict | list) -> dict[str, OptionGreeks]:
    """Parse a greeks response into a symbol → OptionGreeks mapping.

    Accepts:
    - Tastytrade API envelope: ``{"data": {"items": [...]}}``
    - Plain list: ``[{"symbol": "...", "delta": ...}, ...]``
    - MCP tasty-agent format: ``[{"symbol": ..., "delta": ...}]``

    Args:
        response: Raw greeks JSON.

    Returns:
        Dict mapping OCC symbol → OptionGreeks.
    """
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        data = response.get("data", response)
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]
    else:
        return {}

    result: dict[str, OptionGreeks] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = _get(item, "symbol", "streamer-symbol", "eventSymbol")
        greeks = _parse_greeks(item)
        if symbol and greeks:
            result[str(symbol)] = greeks

    return result


# ---------------------------------------------------------------------------
# Option chain parsing
# ---------------------------------------------------------------------------

def parse_chain_strikes(
    underlying: str,
    expiration_date: str,
    strikes: list[dict],
    greeks_map: dict[str, OptionGreeks] | None = None,
) -> list[OptionContract]:
    """Parse a list of strike dicts into OptionContract objects.

    Args:
        underlying: Underlying symbol (e.g., ``"AAPL"``).
        expiration_date: ISO date string (``"YYYY-MM-DD"``).
        strikes: List of strike dicts from the nested chain response.
            Each has ``strike-price``, ``call`` (OCC symbol), ``put`` (OCC symbol).
        greeks_map: Optional mapping of OCC symbol → OptionGreeks.

    Returns:
        List of OptionContract, one per side (call + put) per strike.
    """
    if greeks_map is None:
        greeks_map = {}

    contracts: list[OptionContract] = []
    for s in strikes:
        strike_raw = _get(s, "strike-price", "strikePrice", "strike")
        strike = _dec(strike_raw)
        if strike is None:
            continue

        call_symbol = _get(s, "call", "call-symbol")
        put_symbol = _get(s, "put", "put-symbol")

        if call_symbol:
            contracts.append(OptionContract(
                underlying=underlying,
                option_type=OptionType.CALL,
                strike_price=strike,
                expiration_date=expiration_date,
                greeks=greeks_map.get(str(call_symbol)),
            ))

        if put_symbol:
            contracts.append(OptionContract(
                underlying=underlying,
                option_type=OptionType.PUT,
                strike_price=strike,
                expiration_date=expiration_date,
                greeks=greeks_map.get(str(put_symbol)),
            ))

    return contracts


def parse_nested_chain(
    response: dict | list,
    target_dte: int | None = None,
    greeks_map: dict[str, OptionGreeks] | None = None,
) -> tuple[list[OptionContract], str | None]:
    """Parse a full nested option chain response.

    Handles the tastytrade ``GET /option-chains/{symbol}/nested`` response.
    Optionally selects the expiration closest to target_dte.

    Args:
        response: Raw JSON from the nested option chain endpoint or API envelope.
        target_dte: If provided, select the expiration closest to this DTE.
            If None, uses the first expiration.
        greeks_map: Optional mapping of OCC symbol → OptionGreeks to attach.

    Returns:
        Tuple of (contracts, expiration_date). expiration_date is None if
        no expirations found.
    """
    # Unwrap API envelope
    if isinstance(response, dict):
        data = response.get("data", response)
        if isinstance(data, dict) and "items" in data:
            chains = data["items"]
        elif isinstance(data, list):
            chains = data
        else:
            chains = [data]
    elif isinstance(response, list):
        chains = response
    else:
        return [], None

    # Get the first chain (most symbols have one root)
    chain = chains[0] if chains else {}

    underlying = _get(chain, "underlying-symbol", "symbol") or ""
    expirations = chain.get("expirations", [])

    if not expirations:
        return [], None

    if target_dte is not None:
        expiration = find_expiration_by_dte(expirations, target_dte)
    else:
        expiration = expirations[0]

    if expiration is None:
        return [], None

    expiration_date = str(_get(expiration, "expiration-date", "expirationDate", "date") or "")
    strikes = expiration.get("strikes", [])

    contracts = parse_chain_strikes(underlying, expiration_date, strikes, greeks_map)
    return contracts, expiration_date
