"""COMEX warehouse stock data — CME public reports.

Fetches daily warehouse stock levels from CME's public XLS files.
Tracks registered/eligible inventory for metals commodities.
"""

import hashlib
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .models import ComexAnalysis, ComexWarehouse

# CME public report URLs for COMEX warehouse stocks
CME_STOCK_URLS: dict[str, str] = {
    "gold": "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls",
    "silver": "https://www.cmegroup.com/delivery_reports/Silver_Stocks.xls",
    "copper": "https://www.cmegroup.com/delivery_reports/Copper_Stocks.xls",
    "platinum": "https://www.cmegroup.com/delivery_reports/Platinum_Stocks.xls",
    "palladium": "https://www.cmegroup.com/delivery_reports/Palladium_Stocks.xls",
}

VALID_METALS = frozenset(CME_STOCK_URLS.keys())

# Units by metal
METAL_UNITS: dict[str, str] = {
    "gold": "troy_oz",
    "silver": "troy_oz",
    "copper": "lbs",
    "platinum": "troy_oz",
    "palladium": "troy_oz",
}

# Cache
CACHE_DIR = Path.home() / ".market-agent" / "cache"
CACHE_TTL_HOURS = 12


def _cache_key(metal: str) -> str:
    key = f"comex|{metal}|{datetime.utcnow().strftime('%Y-%m-%d')}"
    return hashlib.md5(key.encode()).hexdigest()


def _load_cache(key: str) -> Optional[dict]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (datetime.utcnow().timestamp() - path.stat().st_mtime) / 3600
    if age_hours > CACHE_TTL_HOURS:
        path.unlink()
        return None
    with open(path) as f:
        return json.load(f)


def _save_cache(key: str, data: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    with open(path, "w") as f:
        json.dump(data, f)


def _validate_metal(metal: str) -> str:
    """Validate and normalize metal name."""
    normalized = metal.lower().strip()
    if normalized not in VALID_METALS:
        raise ValueError(
            f"Unknown metal: {metal!r}. Valid: {sorted(VALID_METALS)}"
        )
    return normalized


def _parse_comex_xls(content: bytes, metal: str) -> Optional[ComexWarehouse]:
    """Parse CME warehouse stock XLS file.

    CME XLS format: rows with label in column 0, "TOTAL TODAY" in column 7.
    Grand totals appear as "Total Registered", "Total Eligible" near bottom.
    """
    try:
        df = pd.read_excel(BytesIO(content), engine="xlrd")
    except Exception:
        try:
            df = pd.read_excel(BytesIO(content), engine="openpyxl")
        except Exception:
            return None

    if df.empty:
        return None

    registered = 0.0
    eligible = 0.0

    # Look for grand total summary rows (e.g. "Total Registered", "Total Eligible")
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip().lower() if pd.notna(row.iloc[0]) else ""
        # TOTAL TODAY is in column index 7
        total_today = row.iloc[7] if len(row) > 7 else None

        if not _is_numeric(total_today):
            continue

        val = float(total_today)
        if label.startswith("total registered"):
            registered = val
        elif label.startswith("total eligible"):
            eligible = val

    total = registered + eligible
    if total <= 0:
        return None

    return ComexWarehouse(
        metal=metal,
        date=datetime.utcnow(),
        registered=registered,
        eligible=eligible,
        total=total,
        unit=METAL_UNITS.get(metal, "troy_oz"),
    )


def _is_numeric(val) -> bool:
    """Check if a value is numeric (not NaN)."""
    if pd.isna(val):
        return False
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def fetch_comex_stocks(metal: str) -> Optional[ComexWarehouse]:
    """Fetch current COMEX warehouse stock levels for a metal.

    Args:
        metal: Metal name (gold, silver, copper, platinum, palladium)

    Returns:
        ComexWarehouse with current stock levels, or None on failure.
    """
    metal = _validate_metal(metal)

    cache_key = _cache_key(metal)
    cached = _load_cache(cache_key)
    if cached is not None:
        return ComexWarehouse(**cached)

    url = CME_STOCK_URLS[metal]

    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (market-agent)",
        })
        resp.raise_for_status()
    except Exception:
        return None

    result = _parse_comex_xls(resp.content, metal)
    if result:
        _save_cache(cache_key, result.model_dump(mode="json"))

    return result


def analyze_comex(
    current: ComexWarehouse,
    history: Optional[list[ComexWarehouse]] = None,
) -> ComexAnalysis:
    """Analyze COMEX warehouse stock trends.

    Args:
        current: Current warehouse stock levels
        history: Optional list of historical snapshots for trend analysis

    Returns:
        ComexAnalysis with trend direction and change metrics.
    """
    registered_pct = (
        (current.registered / current.total * 100) if current.total > 0 else 0.0
    )

    # Determine trend from history
    trend = "stable"
    change_30d_pct = 0.0

    if history and len(history) >= 2:
        # Sort by date, oldest first
        sorted_hist = sorted(history, key=lambda h: h.date)
        oldest = sorted_hist[0]
        if oldest.total > 0:
            change_30d_pct = (current.total - oldest.total) / oldest.total * 100

        if change_30d_pct < -3.0:
            trend = "drawing"
        elif change_30d_pct > 3.0:
            trend = "building"

    return ComexAnalysis(
        metal=current.metal,
        date=current.date,
        registered_pct=round(registered_pct, 2),
        trend=trend,
        change_30d_pct=round(change_30d_pct, 2),
    )


def fetch_all_metals_comex() -> dict[str, Optional[ComexWarehouse]]:
    """Fetch COMEX warehouse stocks for all 5 metals.

    Returns:
        Dict mapping metal name to ComexWarehouse (or None on failure).
    """
    results = {}
    for metal in CME_STOCK_URLS:
        results[metal] = fetch_comex_stocks(metal)
    return results
