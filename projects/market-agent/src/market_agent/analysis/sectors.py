"""Sector classification and portfolio concentration management.

Maps instrument symbols to sector buckets and provides helpers for checking
sector-level buying-power concentration — a key circuit breaker preventing
LTCM-style correlated blowups where positions that appear uncorrelated all
move against you simultaneously because they share the same underlying risk.
"""

# Symbol → sector bucket
SECTOR_MAP: dict[str, str] = {
    # Broad market
    "SPY": "broad", "IWM": "broad", "VTI": "broad", "DIA": "broad",
    "/ES": "broad", "/YM": "broad", "/RTY": "broad",

    # Tech
    "QQQ": "tech", "XLK": "tech",
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "AMD": "tech",
    "GOOG": "tech", "GOOGL": "tech", "META": "tech",
    "/NQ": "tech",

    # Financial
    "XLF": "financial", "JPM": "financial", "GS": "financial", "BAC": "financial",

    # Energy
    "XLE": "energy", "USO": "energy",
    "/CL": "energy", "/NG": "energy", "/HO": "energy", "/RB": "energy",

    # Metals / Materials
    "GLD": "metals", "SLV": "metals", "GDX": "metals", "GDXJ": "metals",
    "/GC": "metals", "/SI": "metals", "/HG": "metals", "/PA": "metals", "/PL": "metals",
    "XLB": "materials",

    # Rates / Fixed Income
    "TLT": "rates", "IEF": "rates", "SHY": "rates",
    "/ZN": "rates", "/ZB": "rates", "/ZT": "rates",

    # Consumer
    "XLY": "consumer", "XLP": "consumer",
    "AMZN": "consumer", "TSLA": "consumer",

    # Agriculture / Softs
    "/ZC": "ag", "/ZW": "ag", "/ZS": "ag", "/ZL": "ag", "/ZM": "ag",
    "/KC": "ag", "/CT": "ag", "/SB": "ag",

    # Volatility
    "VXX": "volatility", "UVXY": "volatility", "SVXY": "volatility",
}

# Max buying-power % allocated to any single sector (open positions + new proposals)
MAX_SECTOR_BP_PCT = 30.0


def get_sector(symbol: str) -> str:
    """Return sector bucket for a symbol. Returns 'other' if unmapped."""
    return SECTOR_MAP.get(symbol.upper(), "other")


def portfolio_sector_bp(
    open_positions: list[dict],
    net_liq: float,
) -> dict[str, float]:
    """Return BP% already allocated to each sector from open positions.

    Reads 'position_size_pct' or 'bp_pct' from each position dict.
    Falls back to 0 if neither field is present.
    """
    exposure: dict[str, float] = {}
    for pos in open_positions:
        sym = pos.get("symbol", "").upper()
        sector = get_sector(sym)
        pct = float(pos.get("position_size_pct", pos.get("bp_pct", 0)) or 0)
        exposure[sector] = exposure.get(sector, 0.0) + pct
    return exposure


def sector_headroom(
    sector: str,
    open_positions: list[dict],
    net_liq: float,
    max_sector_pct: float = MAX_SECTOR_BP_PCT,
) -> float:
    """Return remaining BP% capacity for a sector. Negative means over-limit."""
    used = portfolio_sector_bp(open_positions, net_liq)
    return max_sector_pct - used.get(sector, 0.0)
