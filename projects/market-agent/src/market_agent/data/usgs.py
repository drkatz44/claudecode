"""USGS commodity data — annual production/consumption statistics.

Stub module for future integration with USGS Mineral Commodity Summaries.
Data source: https://data.usgs.gov (public, no auth required).

Currently not implemented — reserved for supply-side context
(mine production, global consumption, reserves data).
"""

from typing import Optional

# USGS commodity identifiers
USGS_COMMODITIES: dict[str, str] = {
    "GOLD": "gold",
    "SILVER": "silver",
    "COPPER": "copper",
    "PLATINUM": "platinum-group-metals",
    "PALLADIUM": "platinum-group-metals",
}

VALID_COMMODITIES = frozenset(USGS_COMMODITIES.keys())


def fetch_usgs_production(commodity: str) -> Optional[dict]:
    """Fetch annual production data from USGS.

    Args:
        commodity: Metal name (GOLD, SILVER, COPPER, PLATINUM, PALLADIUM)

    Returns:
        None — not yet implemented.
    """
    normalized = commodity.upper().strip()
    if normalized not in VALID_COMMODITIES:
        raise ValueError(
            f"Unknown commodity: {commodity!r}. Valid: {sorted(VALID_COMMODITIES)}"
        )
    # Stub: return None until USGS integration is built
    return None


def fetch_usgs_reserves(commodity: str) -> Optional[dict]:
    """Fetch global reserve estimates from USGS.

    Args:
        commodity: Metal name

    Returns:
        None — not yet implemented.
    """
    normalized = commodity.upper().strip()
    if normalized not in VALID_COMMODITIES:
        raise ValueError(
            f"Unknown commodity: {commodity!r}. Valid: {sorted(VALID_COMMODITIES)}"
        )
    return None
