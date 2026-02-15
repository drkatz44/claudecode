#!/usr/bin/env python3
"""Full analysis pipeline — scan → signal → recommend.

Usage:
    uv run python scripts/pipeline.py                    # full daily scan
    uv run python scripts/pipeline.py momentum           # momentum only
    uv run python scripts/pipeline.py volatility          # premium selling only
    uv run python scripts/pipeline.py symbol AAPL         # single symbol deep dive
    uv run python scripts/pipeline.py watchlist my_list   # scan a saved watchlist
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from market_agent import validate_symbol
from market_agent.analysis.screener import (
    CRYPTO_MAJORS,
    HIGH_IV_NAMES,
    SECTOR_ETFS,
    SP500_TOP,
    filter_correlated,
    screen_mean_reversion,
    screen_momentum,
    screen_volatility,
)
from market_agent.analysis.charts import chart_technical
from market_agent.analysis.technical import trend_summary
from market_agent.data.fetcher import get_bars
from market_agent.data.watchlist import get_or_create, list_watchlists, load_watchlist, save_watchlist
from market_agent.signals.generator import (
    signal_from_mean_reversion,
    signal_from_momentum,
    signal_from_volatility,
)
from market_agent.signals.recommender import (
    Recommendation,
    recommend_from_momentum,
    recommend_from_reversion,
    recommend_from_signal,
    recommend_from_volatility,
)

console = Console()


def print_recommendations(title: str, recs: list[Recommendation]):
    """Print recommendations in a formatted table."""
    if not recs:
        console.print(f"  [dim]No recommendations for {title}[/]")
        return

    table = Table(title=title, show_lines=True, title_style="bold white")
    table.add_column("Symbol", style="bold cyan", width=8)
    table.add_column("Action", width=14)
    table.add_column("Conf", justify="right", width=5)
    table.add_column("Entry", justify="right", width=10)
    table.add_column("Stop", justify="right", width=10)
    table.add_column("Target", justify="right", width=10)
    table.add_column("R/R", justify="right", width=5)
    table.add_column("Size", justify="right", width=5)
    table.add_column("Options", width=14)
    table.add_column("Rationale", width=30)

    for rec in recs:
        action_style = {
            "buy_equity": "green",
            "sell_premium": "yellow",
            "sell_equity": "red",
            "watch": "dim",
        }.get(rec.action, "white")

        options_str = ""
        if rec.options_strategy:
            os = rec.options_strategy
            options_str = f"{os.strategy_type}"
            if os.delta_target:
                options_str += f" d{os.delta_target}"

        table.add_row(
            rec.symbol,
            f"[{action_style}]{rec.action}[/]",
            f"{rec.confidence:.0%}",
            f"{rec.entry_price:.2f}" if rec.entry_price else "-",
            f"{rec.stop_loss:.2f}" if rec.stop_loss else "-",
            f"{rec.take_profit:.2f}" if rec.take_profit else "-",
            f"{rec.risk_reward:.1f}" if rec.risk_reward else "-",
            f"{rec.position_size_pct:.0f}%",
            options_str or "-",
            "; ".join(rec.rationale[:2]),
        )

    console.print(table)
    console.print()


def run_momentum_pipeline(symbols: list[str]) -> list[Recommendation]:
    """Scan → signal → recommend for momentum."""
    results = screen_momentum(symbols)
    results = filter_correlated(results)
    recs = []
    for r in results[:8]:
        bars = get_bars(r.symbol, period="6mo")
        signal = signal_from_momentum(r, bars)
        if signal:
            rec = recommend_from_momentum(r, signal)
            recs.append(rec)
    return recs


def run_reversion_pipeline(symbols: list[str]) -> list[Recommendation]:
    """Scan → signal → recommend for mean reversion."""
    results = screen_mean_reversion(symbols, max_rsi=35)
    results = filter_correlated(results)
    recs = []
    for r in results[:8]:
        bars = get_bars(r.symbol, period="6mo")
        signal = signal_from_mean_reversion(r, bars)
        if signal:
            rec = recommend_from_reversion(r, signal)
            recs.append(rec)
    return recs


def run_volatility_pipeline(symbols: list[str]) -> list[Recommendation]:
    """Scan → signal → recommend for volatility/premium selling."""
    results = screen_volatility(symbols)
    results = filter_correlated(results)
    recs = []
    for r in results[:8]:
        signal = signal_from_volatility(r)
        if signal:
            rec = recommend_from_volatility(r, signal)
            recs.append(rec)
    return recs


def deep_dive(symbol: str):
    """Single-symbol deep analysis."""
    console.print(Panel(f"[bold]Deep Dive: {symbol}[/]", style="cyan"))

    bars = get_bars(symbol, period="1y")
    if not bars or len(bars) < 50:
        console.print(f"  [red]Insufficient data for {symbol}[/]")
        return

    # Technical summary
    summary = trend_summary(bars)
    trend_style = "green" if summary["trend"] == "bullish" else "red" if summary["trend"] == "bearish" else "yellow"

    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="bold", width=18)
    info_table.add_column("Value", width=15)
    info_table.add_column("Key", style="bold", width=18)
    info_table.add_column("Value", width=15)

    info_table.add_row(
        "Close", f"${summary['close']:.2f}",
        "Trend", f"[{trend_style}]{summary['trend']}[/]",
    )
    info_table.add_row(
        "SMA-20", f"${summary['sma_20']}",
        "SMA-50", f"${summary['sma_50']}",
    )
    info_table.add_row(
        "RSI-14", f"{summary['rsi_14']}",
        "MACD Hist", f"{summary['macd_histogram']}",
    )
    info_table.add_row(
        "BB %B", f"{summary['bb_pct_b']}",
        "ATR-14", f"${summary['atr_14']}",
    )
    info_table.add_row(
        "Trend Score", f"{summary['trend_score']}",
        "Signals", f"{summary['bullish_signals']}B / {summary['bearish_signals']}S",
    )
    console.print(info_table)
    console.print()

    # Generate all possible signals
    from market_agent.analysis.screener import ScreenResult
    close = float(summary["close"])
    atr_pct = float(summary["atr_14"]) / close * 100 if close > 0 else 0
    from market_agent.analysis.technical import volume_sma_ratio
    vol_ratio = float(volume_sma_ratio(bars).iloc[-1])

    screen_result = ScreenResult(
        symbol=symbol,
        score=50.0,
        trend=summary["trend"],
        rsi_14=summary["rsi_14"],
        atr_pct=round(atr_pct, 2),
        volume_ratio=round(vol_ratio, 2),
        bb_pct_b=float(summary["bb_pct_b"]),
        close=close,
        sma_20=float(summary["sma_20"]),
        sma_50=float(summary["sma_50"]),
        details=summary,
    )

    recs = []

    # Try momentum signal
    sig = signal_from_momentum(screen_result, bars)
    if sig:
        recs.append(recommend_from_momentum(screen_result, sig))

    # Try mean reversion signal
    sig = signal_from_mean_reversion(screen_result, bars)
    if sig:
        recs.append(recommend_from_reversion(screen_result, sig))

    # Try volatility signal
    sig = signal_from_volatility(screen_result)
    if sig:
        recs.append(recommend_from_volatility(screen_result, sig))

    if recs:
        print_recommendations(f"Recommendations for {symbol}", recs)
    else:
        console.print(f"  [dim]No actionable signals for {symbol} right now[/]")

    # Generate technical chart
    chart_path = chart_technical(bars, symbol)
    if chart_path:
        console.print(f"  [dim]Chart saved: {chart_path}[/]")

    # Add to watchlist
    wl = get_or_create("recent_scans", "Symbols recently analyzed")
    wl.add(symbol, notes=f"Deep dive {datetime.now().strftime('%Y-%m-%d')}")
    save_watchlist(wl)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    console.print(Panel(
        f"[bold]Market Analysis Pipeline[/]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/]",
        style="blue",
    ))

    all_recs = []

    if mode == "symbol" and len(sys.argv) > 2:
        deep_dive(validate_symbol(sys.argv[2]))
        return

    if mode == "watchlist" and len(sys.argv) > 2:
        wl_name = sys.argv[2]
        wl = load_watchlist(wl_name)
        if not wl:
            console.print(f"[red]Watchlist '{wl_name}' not found[/]")
            available = list_watchlists()
            if available:
                console.print(f"Available: {', '.join(available)}")
            return
        console.print(f"[bold]Scanning watchlist: {wl_name} ({len(wl.symbols)} symbols)[/]")
        recs = run_momentum_pipeline(wl.symbols)
        recs.extend(run_volatility_pipeline(wl.symbols))
        print_recommendations(f"Watchlist: {wl_name}", recs)
        return

    if mode in ("momentum", "all"):
        console.print("[bold]Momentum scan...[/]")
        recs = run_momentum_pipeline(SP500_TOP)
        print_recommendations("Momentum — Equities", recs)
        all_recs.extend(recs)

    if mode in ("reversion", "mean_reversion", "all"):
        console.print("[bold]Mean reversion scan...[/]")
        recs = run_reversion_pipeline(SP500_TOP)
        print_recommendations("Mean Reversion — Oversold Bounces", recs)
        all_recs.extend(recs)

    if mode in ("volatility", "premium", "all"):
        console.print("[bold]Volatility / premium selling scan...[/]")
        recs = run_volatility_pipeline(HIGH_IV_NAMES)
        print_recommendations("Premium Selling — Options", recs)
        all_recs.extend(recs)

    if mode in ("sectors", "all"):
        console.print("[bold]Sector rotation scan...[/]")
        recs = run_momentum_pipeline(SECTOR_ETFS)
        print_recommendations("Sector Rotation — ETFs", recs)
        all_recs.extend(recs)

    if mode in ("crypto", "all"):
        console.print("[bold]Crypto scan...[/]")
        from market_agent.analysis.screener import screen_momentum as sm
        results = sm(CRYPTO_MAJORS, min_rsi=40, max_rsi=75)
        recs = []
        for r in results[:5]:
            bars = get_bars(r.symbol, period="6mo")
            sig = signal_from_momentum(r, bars)
            if sig:
                recs.append(recommend_from_signal(sig))
        print_recommendations("Crypto Momentum", recs)
        all_recs.extend(recs)

    # Summary
    if all_recs:
        console.print(Panel(
            f"[bold]Summary: {len(all_recs)} recommendations[/]\n"
            f"  Buy equity: {sum(1 for r in all_recs if r.action == 'buy_equity')}\n"
            f"  Sell premium: {sum(1 for r in all_recs if r.action == 'sell_premium')}\n"
            f"  High confidence (>70%): {sum(1 for r in all_recs if r.confidence > 0.7)}",
            style="green",
        ))

        # Save top picks to watchlist
        wl = get_or_create("pipeline_picks", "Auto-generated from pipeline runs")
        for rec in all_recs:
            if rec.confidence >= 0.5:
                wl.add(rec.symbol, notes=f"{rec.action} via {rec.strategy_name}", tags=[rec.action])
        save_watchlist(wl)
        console.print(f"[dim]Top picks saved to watchlist 'pipeline_picks'[/]")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        console.print(__doc__)
        sys.exit(0)
    main()
