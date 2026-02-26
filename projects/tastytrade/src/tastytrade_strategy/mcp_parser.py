"""Parse raw tastytrade API responses into internal models.

Handles the dasherized key format returned by the tastytrade REST API
and the tasty-agent MCP server. Designed to be lenient — unknown or
missing fields are silently ignored so the screener still works with
partial data.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import MarketMetrics


def _dec(value: Any) -> Decimal | None:
    """Safely convert a value to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _get(data: dict, *keys: str) -> Any:
    """Return the first matching key value from a dict, trying each key in order."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def parse_market_metrics(raw: dict) -> MarketMetrics:
    """Parse a single market-metrics item from the tastytrade API.

    Accepts both dasherized API format (e.g. ``implied-volatility-index-rank``)
    and snake_case/normalized formats so results can come from either the raw
    REST API or the tasty-agent MCP server.

    Args:
        raw: A single item dict from ``GET /market-metrics`` response.

    Returns:
        MarketMetrics with all available fields populated.
    """
    symbol = _get(raw, "symbol") or ""

    # IV rank — tastytrade returns as 0-100; normalize to 0-1
    # Field name confirmed from /open-api-spec/market-metrics/: "implied-volatility-rank"
    iv_rank_raw = _get(
        raw,
        "implied-volatility-rank",
        "implied-volatility-index-rank",
        "iv-rank",
        "iv_rank",
        "ivRank",
    )
    iv_rank_dec = _dec(iv_rank_raw)
    if iv_rank_dec is not None and iv_rank_dec > 1:
        iv_rank_dec = iv_rank_dec / 100

    # IV percentile — same normalization
    iv_pct_raw = _get(
        raw,
        "implied-volatility-percentile",
        "iv-percentile",
        "iv_percentile",
        "ivPercentile",
    )
    iv_pct_dec = _dec(iv_pct_raw)
    if iv_pct_dec is not None and iv_pct_dec > 1:
        iv_pct_dec = iv_pct_dec / 100

    # Current IV
    iv_raw = _get(
        raw,
        "implied-volatility-index",
        "implied-volatility",
        "implied_volatility",
        "impliedVolatility",
        "iv",
    )

    # Historical volatility — prefer 30-day, fall back to others
    hv_raw = _get(
        raw,
        "historical-volatility-30-day",
        "historical-volatility-60-day",
        "historical-volatility-90-day",
        "historical-volatility-99-day",
        "historical-volatility",
        "historical_volatility",
        "historicalVolatility",
        "hv",
    )

    liquidity_raw = _get(
        raw,
        "liquidity-rating",
        "liquidity_rating",
        "liquidityRating",
        "liquidity",
    )

    beta_raw = _get(raw, "beta", "beta-value", "beta_value", "betaValue")

    market_cap_raw = _get(
        raw,
        "market-cap",
        "market_cap",
        "marketCap",
    )

    earnings_raw = _get(
        raw,
        "earnings-next-date-estimate",
        "earnings-date",
        "earnings_date",
        "earningsDate",
        "next-earnings-date",
    )
    # Normalize earnings date to YYYY-MM-DD if it has a time component
    earnings_date: str | None = None
    if earnings_raw:
        earnings_date = str(earnings_raw)[:10]

    borrow_raw = _get(
        raw,
        "borrow-rate",
        "borrow_rate",
        "borrowRate",
    )

    return MarketMetrics(
        symbol=symbol,
        iv_rank=iv_rank_dec if iv_rank_dec is not None else Decimal("0"),
        iv_percentile=iv_pct_dec,
        implied_volatility=_dec(iv_raw),
        historical_volatility=_dec(hv_raw),
        liquidity_rating=_dec(liquidity_raw),
        beta=_dec(beta_raw),
        market_cap=_dec(market_cap_raw),
        earnings_date=earnings_date,
        borrow_rate=_dec(borrow_raw),
    )


def parse_market_metrics_response(response: dict | list) -> list[MarketMetrics]:
    """Parse a full tastytrade API response into a list of MarketMetrics.

    Handles three input shapes:
    - Raw API envelope: ``{"data": {"items": [...]}}``
    - Array of items: ``[{...}, {...}]``
    - Single item: ``{...}``

    Args:
        response: Raw JSON from ``GET /market-metrics`` or tasty-agent MCP.

    Returns:
        List of MarketMetrics, one per symbol.
    """
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        # Try to unwrap the standard tastytrade response envelope
        data = response.get("data", response)
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]
    else:
        return []

    return [parse_market_metrics(item) for item in items if item]
