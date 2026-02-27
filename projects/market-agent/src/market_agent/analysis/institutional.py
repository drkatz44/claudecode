"""Institutional flow analysis — COT positioning + COMEX warehouse data.

Aggregates CFTC managed money positioning and COMEX warehouse stock signals
into a combined institutional bias for metals commodities.
"""

from typing import Optional

from ..data.comex import analyze_comex, fetch_all_metals_comex
from ..data.cot import fetch_all_metals_cot
from ..data.models import ComexAnalysis, CotAnalysis

# Ticker → commodity mapping for metals-related equities/ETFs
METALS_TICKER_MAP: dict[str, str] = {
    # Gold
    "GLD": "GOLD", "IAU": "GOLD", "GDX": "GOLD", "GDXJ": "GOLD",
    "NEM": "GOLD", "GOLD": "GOLD", "AEM": "GOLD", "KGC": "GOLD",
    "AU": "GOLD", "FNV": "GOLD", "WPM": "GOLD", "RGLD": "GOLD",
    # Silver
    "SLV": "GOLD", "SIVR": "GOLD", "SIL": "GOLD",
    "AG": "SILVER", "PAAS": "SILVER", "HL": "SILVER",
    # Copper
    "CPER": "COPPER", "COPX": "COPPER",
    "FCX": "COPPER", "SCCO": "COPPER", "TECK": "COPPER",
    # Platinum/Palladium
    "PPLT": "PLATINUM", "PALL": "PALLADIUM",
}


def is_metals_ticker(symbol: str) -> bool:
    """Check if a ticker is metals-related."""
    return symbol.upper() in METALS_TICKER_MAP


def ticker_to_commodity(symbol: str) -> Optional[str]:
    """Map a ticker symbol to its metals commodity."""
    return METALS_TICKER_MAP.get(symbol.upper())


def get_metals_context(weeks: int = 52) -> dict:
    """Fetch COT + COMEX data for all metals.

    Returns:
        Dict with 'cot' and 'comex' sub-dicts keyed by commodity/metal.
    """
    cot_data = fetch_all_metals_cot(weeks=weeks)
    comex_raw = fetch_all_metals_comex()

    # Analyze COMEX data
    comex_data: dict[str, Optional[ComexAnalysis]] = {}
    for metal, warehouse in comex_raw.items():
        if warehouse:
            comex_data[metal] = analyze_comex(warehouse)
        else:
            comex_data[metal] = None

    return {"cot": cot_data, "comex": comex_data}


def institutional_bias(
    commodity: str,
    cot: Optional[CotAnalysis],
    comex: Optional[ComexAnalysis],
) -> dict:
    """Combine COT positioning and COMEX warehouse signals into a bias.

    Signal combinations:
    - extreme_long + drawing = "bullish_crowded" (0.85 confidence adj)
    - extreme_short + drawing = "bullish_capitulation" (1.2 confidence adj)
    - neutral + building = "neutral_abundant" (0.9 confidence adj)
    - extreme_long + building = "bearish_excess" (0.8 confidence adj)
    - extreme_short + building = "neutral_rebuilding" (0.95 confidence adj)

    Returns:
        Dict with 'bias', 'confidence_adj', and 'rationale' keys.
    """
    positioning = cot.positioning_signal if cot else "unknown"
    trend = comex.trend if comex else "unknown"

    # Default
    bias = "neutral"
    confidence_adj = 1.0
    rationale_parts = []

    if cot:
        rationale_parts.append(
            f"MM net {cot.mm_net:+,} ({cot.mm_net_pct:+.1f}% OI), "
            f"z={cot.z_score:+.2f} → {positioning}"
        )

    if comex:
        rationale_parts.append(
            f"COMEX {comex.trend} ({comex.change_30d_pct:+.1f}% 30d), "
            f"registered {comex.registered_pct:.0f}%"
        )

    # Combined signal logic
    if positioning == "extreme_long" and trend == "drawing":
        bias = "bullish_crowded"
        confidence_adj = 0.85
        rationale_parts.append("Crowded long but physical drawdown supports price")
    elif positioning == "extreme_short" and trend == "drawing":
        bias = "bullish_capitulation"
        confidence_adj = 1.2
        rationale_parts.append("Short capitulation + physical squeeze potential")
    elif positioning == "neutral" and trend == "building":
        bias = "neutral_abundant"
        confidence_adj = 0.9
        rationale_parts.append("Neutral positioning, ample physical supply")
    elif positioning == "extreme_long" and trend == "building":
        bias = "bearish_excess"
        confidence_adj = 0.8
        rationale_parts.append("Crowded long with rising supply — risk of unwind")
    elif positioning == "extreme_short" and trend == "building":
        bias = "neutral_rebuilding"
        confidence_adj = 0.95
        rationale_parts.append("Shorts rebuilding as supply increases")
    elif positioning == "extreme_long":
        bias = "bullish_crowded"
        confidence_adj = 0.85
        rationale_parts.append("Crowded long — risk of pullback")
    elif positioning == "extreme_short":
        bias = "bullish_capitulation"
        confidence_adj = 1.1
        rationale_parts.append("Extreme short positioning — contrarian bullish")
    elif trend == "drawing":
        bias = "bullish_physical"
        confidence_adj = 1.05
        rationale_parts.append("Physical inventory drawdown")
    elif trend == "building":
        bias = "neutral_abundant"
        confidence_adj = 0.9
        rationale_parts.append("Physical supply building")

    return {
        "bias": bias,
        "confidence_adj": confidence_adj,
        "rationale": "; ".join(rationale_parts),
    }


def format_institutional_summary(context: dict) -> str:
    """Format institutional data as a markdown summary.

    Args:
        context: Dict from get_metals_context() with 'cot' and 'comex' keys.

    Returns:
        Markdown-formatted string.
    """
    lines = ["## Institutional Flow Summary", ""]

    # COT table
    cot_data = context.get("cot", {})
    if any(v is not None for v in cot_data.values()):
        lines.append("### COT Managed Money Positioning")
        lines.append("")
        lines.append(
            "| Commodity | MM Net | % OI | Z-Score | Signal | Wk Chg |"
        )
        lines.append(
            "|-----------|--------|------|---------|--------|--------|"
        )
        for commodity, analysis in sorted(cot_data.items()):
            if analysis:
                lines.append(
                    f"| {commodity} | {analysis.mm_net:+,} | "
                    f"{analysis.mm_net_pct:+.1f}% | {analysis.z_score:+.2f} | "
                    f"{analysis.positioning_signal} | {analysis.weekly_change:+,} |"
                )
            else:
                lines.append(f"| {commodity} | - | - | - | N/A | - |")
        lines.append("")

    # COMEX table
    comex_data = context.get("comex", {})
    if any(v is not None for v in comex_data.values()):
        lines.append("### COMEX Warehouse Stocks")
        lines.append("")
        lines.append(
            "| Metal | Registered % | Trend | 30d Chg |"
        )
        lines.append(
            "|-------|-------------|-------|---------|"
        )
        for metal, analysis in sorted(comex_data.items()):
            if analysis:
                lines.append(
                    f"| {metal.title()} | {analysis.registered_pct:.0f}% | "
                    f"{analysis.trend} | {analysis.change_30d_pct:+.1f}% |"
                )
            else:
                lines.append(f"| {metal.title()} | - | N/A | - |")
        lines.append("")

    # Combined bias
    lines.append("### Combined Bias")
    lines.append("")
    lines.append("| Commodity | Bias | Conf Adj | Rationale |")
    lines.append("|-----------|------|----------|-----------|")

    for commodity in sorted(set(
        [k.upper() for k in cot_data.keys()] +
        [k.upper() for k in comex_data.keys()]
    )):
        cot = cot_data.get(commodity) or cot_data.get(commodity.lower())
        comex = comex_data.get(commodity.lower()) or comex_data.get(commodity)
        result = institutional_bias(commodity, cot, comex)
        lines.append(
            f"| {commodity} | {result['bias']} | "
            f"{result['confidence_adj']:.2f} | {result['rationale'][:60]} |"
        )
    lines.append("")

    return "\n".join(lines)
