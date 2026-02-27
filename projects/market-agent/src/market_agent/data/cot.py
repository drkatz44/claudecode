"""CFTC Commitments of Traders data — disaggregated futures.

Fetches weekly COT reports from CFTC Socrata API (free, no auth required).
Provides managed money positioning analysis for metals commodities.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .models import CotAnalysis, CotReport

# --- CFTC commodity codes (disaggregated futures) ---
CFTC_CODES: dict[str, str] = {
    "GOLD": "088691",
    "SILVER": "084691",
    "COPPER": "085692",
    "PLATINUM": "076651",
    "PALLADIUM": "075651",
}

VALID_COMMODITIES = frozenset(CFTC_CODES.keys())

SOCRATA_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"

# Cache
CACHE_DIR = Path.home() / ".market-agent" / "cache"
CACHE_TTL_HOURS = 24


def _cache_key(commodity: str, weeks: int) -> str:
    key = f"cot|{commodity}|{weeks}|{datetime.utcnow().strftime('%Y-%m-%d')}"
    return hashlib.md5(key.encode()).hexdigest()


def _load_cache(key: str) -> Optional[list[dict]]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (datetime.utcnow().timestamp() - path.stat().st_mtime) / 3600
    if age_hours > CACHE_TTL_HOURS:
        path.unlink()
        return None
    with open(path) as f:
        return json.load(f)


def _save_cache(key: str, data: list[dict]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    with open(path, "w") as f:
        json.dump(data, f)


def _validate_commodity(commodity: str) -> str:
    """Validate and normalize commodity name."""
    normalized = commodity.upper().strip()
    if normalized not in VALID_COMMODITIES:
        raise ValueError(
            f"Unknown commodity: {commodity!r}. Valid: {sorted(VALID_COMMODITIES)}"
        )
    return normalized


def fetch_cot(commodity: str, weeks: int = 52) -> list[CotReport]:
    """Fetch COT disaggregated futures data from CFTC Socrata API.

    Args:
        commodity: Metal name (GOLD, SILVER, COPPER, PLATINUM, PALLADIUM)
        weeks: Number of weeks of history to fetch (default 52)

    Returns:
        List of CotReport sorted by date descending (newest first).
    """
    commodity = _validate_commodity(commodity)
    code = CFTC_CODES[commodity]

    cache_key = _cache_key(commodity, weeks)
    cached = _load_cache(cache_key)
    if cached is not None:
        return [CotReport(**r) for r in cached]

    params = {
        "cftc_contract_market_code": code,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(weeks),
    }

    try:
        resp = requests.get(SOCRATA_URL, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return []

    if not isinstance(rows, list):
        return []

    reports = []
    for row in rows:
        try:
            report = CotReport(
                commodity=commodity,
                report_date=datetime.fromisoformat(
                    row["report_date_as_yyyy_mm_dd"][:10]
                ),
                managed_money_long=int(row.get("m_money_positions_long_all", 0)),
                managed_money_short=int(row.get("m_money_positions_short_all", 0)),
                managed_money_spreading=int(
                    row.get("m_money_positions_spread_all", 0)
                ),
                commercial_long=int(row.get("prod_merc_positions_long_all", 0)),
                commercial_short=int(row.get("prod_merc_positions_short_all", 0)),
                non_reportable_long=int(row.get("nonrept_positions_long_all", 0)),
                non_reportable_short=int(row.get("nonrept_positions_short_all", 0)),
                open_interest=int(row.get("open_interest_all", 0)),
            )
            reports.append(report)
        except (KeyError, ValueError, TypeError):
            continue

    if reports:
        _save_cache(cache_key, [r.model_dump(mode="json") for r in reports])

    return reports


def analyze_cot(reports: list[CotReport]) -> Optional[CotAnalysis]:
    """Analyze COT positioning data.

    Computes managed money net positioning, z-score vs 1-year history,
    and classifies positioning extremes (>1.5 sigma).

    Args:
        reports: List of CotReport sorted by date descending.

    Returns:
        CotAnalysis for the most recent report, or None if insufficient data.
    """
    if not reports:
        return None

    latest = reports[0]

    mm_net = latest.managed_money_long - latest.managed_money_short
    mm_net_pct = (mm_net / latest.open_interest * 100) if latest.open_interest > 0 else 0.0

    # Z-score vs available history
    nets = [r.managed_money_long - r.managed_money_short for r in reports]
    mean_net = sum(nets) / len(nets)

    if len(nets) > 1:
        variance = sum((n - mean_net) ** 2 for n in nets) / (len(nets) - 1)
        std_net = variance ** 0.5
    else:
        std_net = 0.0

    z_score = (mm_net - mean_net) / std_net if std_net > 0 else 0.0

    # Classify positioning
    if z_score > 1.5:
        positioning_signal = "extreme_long"
    elif z_score < -1.5:
        positioning_signal = "extreme_short"
    else:
        positioning_signal = "neutral"

    # Weekly change
    if len(reports) >= 2:
        prev_net = reports[1].managed_money_long - reports[1].managed_money_short
        weekly_change = mm_net - prev_net
    else:
        weekly_change = 0

    return CotAnalysis(
        commodity=latest.commodity,
        report_date=latest.report_date,
        mm_net=mm_net,
        mm_net_pct=round(mm_net_pct, 2),
        z_score=round(z_score, 2),
        positioning_signal=positioning_signal,
        weekly_change=weekly_change,
    )


def fetch_all_metals_cot(weeks: int = 52) -> dict[str, Optional[CotAnalysis]]:
    """Fetch and analyze COT data for all 5 metals.

    Returns:
        Dict mapping commodity name to CotAnalysis (or None on failure).
    """
    results = {}
    for commodity in CFTC_CODES:
        reports = fetch_cot(commodity, weeks)
        results[commodity] = analyze_cot(reports)
    return results
