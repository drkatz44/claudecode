#!/usr/bin/env python3
"""Generate backtest reports on real data.

Usage:
    uv run python scripts/report.py AAPL              # single symbol report
    uv run python scripts/report.py AAPL,NVDA,SPY     # multi-symbol
    uv run python scripts/report.py AAPL --walk-forward  # include walk-forward
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console

from market_agent import validate_symbol
from market_agent.analysis.charts import chart_equity_curve
from market_agent.backtest.engine import backtest, walk_forward
from market_agent.backtest.reporter import generate_report, generate_multi_report, save_report
from market_agent.backtest.strategies import (
    breakout_volume,
    macd_momentum,
    mean_reversion_bb,
    momentum_crossover,
)
from market_agent.data.fetcher import get_bars

console = Console()

STRATEGIES = {
    "momentum_crossover": momentum_crossover,
    "mean_reversion_bb": mean_reversion_bb,
    "macd_momentum": macd_momentum,
    "breakout_volume": breakout_volume,
}


def run_report(symbol: str, do_walk_forward: bool = False):
    """Run all strategies on a symbol and generate a report."""
    console.print(f"[bold]Generating report for {symbol}...[/]")

    period = "5y" if do_walk_forward else "2y"
    bars = get_bars(symbol, period=period)
    if len(bars) < 50:
        console.print(f"  [red]Not enough data for {symbol} ({len(bars)} bars)[/]")
        return None, None

    spy_bars = get_bars("SPY", period=period)

    results = {}
    chart_paths = {}
    wf_results = {}

    for name, func in STRATEGIES.items():
        console.print(f"  Running {name}...")
        try:
            result = backtest(
                bars=bars,
                signal_func=func,
                initial_capital=10000.0,
                position_size_pct=10.0,
                slippage_bps=5.0,
                benchmark_bars=spy_bars,
            )
            results[name] = result

            # Generate equity curve chart
            chart_path = chart_equity_curve(
                result.equity_curve, symbol, strategy_name=name,
                benchmark_return_pct=result.benchmark_return_pct,
            )
            if chart_path:
                chart_paths[name] = chart_path

            # Walk-forward
            if do_walk_forward and len(bars) >= 400:
                try:
                    wf = walk_forward(
                        bars=bars,
                        signal_func=func,
                        train_bars=252,
                        test_bars=63,
                        initial_capital=10000.0,
                        slippage_bps=5.0,
                    )
                    wf_results[name] = wf
                except ValueError:
                    pass

        except (ValueError, ZeroDivisionError) as e:
            console.print(f"  [red]Error with {name}: {e}[/]")

    if not results:
        return None, None

    # Generate report
    report_md = generate_report(
        symbol, results,
        walk_forward=wf_results if wf_results else None,
        chart_paths=chart_paths if chart_paths else None,
    )
    report_path = save_report(report_md, symbol)

    # Print summary
    console.print(f"\n  [green]Report saved: {report_path}[/]")
    for name, result in results.items():
        ret_style = "green" if result.total_return_pct > 0 else "red"
        console.print(
            f"    {name}: [{ret_style}]{result.total_return_pct:+.1f}%[/] "
            f"(Sharpe {result.sharpe_ratio:.2f}, DD {result.max_drawdown_pct:.1f}%)"
        )

    return results, report_path


def main():
    if len(sys.argv) < 2:
        console.print("Usage: python scripts/report.py SYMBOL[,SYMBOL2,...] [--walk-forward]")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    do_walk_forward = "--walk-forward" in flags

    symbols = [validate_symbol(s) for s in args[0].split(",")]

    all_results = {}
    for symbol in symbols:
        results, _ = run_report(symbol, do_walk_forward)
        if results:
            all_results[symbol] = results
        console.print()

    # Multi-symbol aggregate
    if len(all_results) > 1:
        multi_md = generate_multi_report(all_results)
        multi_path = save_report(multi_md, "summary")
        console.print(f"[green]Multi-symbol summary: {multi_path}[/]")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        console.print(__doc__)
        sys.exit(0)
    main()
