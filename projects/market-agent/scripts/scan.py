#!/usr/bin/env python3
"""Quick market scan — run from project root with: uv run python scripts/scan.py"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from market_agent import validate_symbol
from market_agent.analysis.screener import (
    CRYPTO_MAJORS,
    HIGH_IV_NAMES,
    SECTOR_ETFS,
    SP500_TOP,
    screen_mean_reversion,
    screen_momentum,
    screen_volatility,
)
from market_agent.analysis.technical import trend_summary
from market_agent.data.fetcher import get_bars

console = Console()


def print_results(title: str, results: list, limit: int = 10):
    table = Table(title=title, show_lines=False)
    table.add_column("Symbol", style="bold cyan", width=10)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Trend", width=8)
    table.add_column("RSI", justify="right", width=6)
    table.add_column("ATR%", justify="right", width=7)
    table.add_column("Vol Ratio", justify="right", width=9)
    table.add_column("BB%B", justify="right", width=7)
    table.add_column("Close", justify="right", width=10)
    table.add_column("SMA20", justify="right", width=10)
    table.add_column("SMA50", justify="right", width=10)

    for r in results[:limit]:
        trend_style = "green" if r.trend == "bullish" else "red" if r.trend == "bearish" else "yellow"
        table.add_row(
            r.symbol,
            f"{r.score:.0f}",
            f"[{trend_style}]{r.trend}[/]",
            f"{r.rsi_14:.0f}",
            f"{r.atr_pct:.1f}%",
            f"{r.volume_ratio:.1f}x",
            f"{r.bb_pct_b:.2f}",
            f"{r.close:.2f}",
            f"{r.sma_20:.2f}",
            f"{r.sma_50:.2f}",
        )

    console.print(table)
    console.print()


def main():
    scan_type = sys.argv[1] if len(sys.argv) > 1 else "all"

    if scan_type in ("momentum", "all"):
        console.print("[bold]Scanning top equities for momentum...[/]")
        results = screen_momentum(SP500_TOP)
        print_results("Momentum — S&P 500 Top 30", results)

    if scan_type in ("mean_reversion", "all"):
        console.print("[bold]Scanning for mean reversion setups...[/]")
        results = screen_mean_reversion(SP500_TOP, max_rsi=35)
        print_results("Mean Reversion — Oversold", results)

    if scan_type in ("volatility", "all"):
        console.print("[bold]Scanning high-IV names for options premium...[/]")
        results = screen_volatility(HIGH_IV_NAMES)
        print_results("Volatility — Options Premium", results)

    if scan_type in ("crypto", "all"):
        console.print("[bold]Scanning crypto majors...[/]")
        results = screen_momentum(CRYPTO_MAJORS, min_rsi=40, max_rsi=75)
        print_results("Crypto Momentum", results)

    if scan_type in ("sectors", "all"):
        console.print("[bold]Scanning sector ETFs...[/]")
        results = screen_momentum(SECTOR_ETFS, min_rsi=40, max_rsi=75)
        print_results("Sector Rotation", results)

    if scan_type == "symbol" and len(sys.argv) > 2:
        sym = validate_symbol(sys.argv[2])
        console.print(f"[bold]Technical summary for {sym}[/]")
        bars = get_bars(sym, period="6mo")
        if bars:
            summary = trend_summary(bars)
            for k, v in summary.items():
                console.print(f"  {k:20s}: {v}")
        else:
            console.print(f"  No data for {sym}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        console.print("Usage: python scripts/scan.py [momentum|mean_reversion|volatility|crypto|sectors|all|symbol TICKER]")
        sys.exit(0)
    main()
