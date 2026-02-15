#!/usr/bin/env python3
"""Run backtests on historical data.

Usage:
    uv run python scripts/backtest.py AAPL                    # all strategies on AAPL
    uv run python scripts/backtest.py AAPL momentum_crossover  # specific strategy
    uv run python scripts/backtest.py SPY,QQQ,AAPL            # multiple symbols
    uv run python scripts/backtest.py AAPL --walk-forward      # walk-forward analysis
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from market_agent import validate_symbol
from market_agent.backtest.engine import backtest, walk_forward
from market_agent.backtest.strategies import breakout_volume, macd_momentum, mean_reversion_bb, momentum_crossover
from market_agent.data.fetcher import get_bars

console = Console()

STRATEGIES = {
    "momentum_crossover": momentum_crossover,
    "mean_reversion_bb": mean_reversion_bb,
    "macd_momentum": macd_momentum,
    "breakout_volume": breakout_volume,
}


def run_backtest(symbol: str, strategy_name: str, strategy_func, period: str = "2y",
                 benchmark_bars=None):
    bars = get_bars(symbol, period=period)
    if len(bars) < 50:
        console.print(f"  [red]Not enough data for {symbol}[/]")
        return None

    result = backtest(
        bars=bars,
        signal_func=strategy_func,
        initial_capital=10000.0,
        position_size_pct=10.0,
        slippage_bps=5.0,
        benchmark_bars=benchmark_bars,
    )
    return result


def run_walk_forward(symbol: str, strategy_name: str, strategy_func, period: str = "5y"):
    bars = get_bars(symbol, period=period)
    if len(bars) < 400:
        console.print(f"  [red]Not enough data for walk-forward on {symbol} ({len(bars)} bars)[/]")
        return None

    return walk_forward(
        bars=bars,
        signal_func=strategy_func,
        train_bars=252,
        test_bars=63,
        initial_capital=10000.0,
        position_size_pct=10.0,
        slippage_bps=5.0,
    )


def main():
    if len(sys.argv) < 2:
        console.print("Usage: python scripts/backtest.py SYMBOL[,SYMBOL2,...] [strategy] [--walk-forward]")
        console.print(f"Strategies: {', '.join(STRATEGIES.keys())}")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    do_walk_forward = "--walk-forward" in flags

    symbols = [validate_symbol(s) for s in args[0].split(",")]
    strategy_filter = args[1] if len(args) > 1 else None

    strategies = STRATEGIES
    if strategy_filter and strategy_filter in STRATEGIES:
        strategies = {strategy_filter: STRATEGIES[strategy_filter]}

    # Fetch SPY for benchmark
    spy_bars = get_bars("SPY", period="5y" if do_walk_forward else "2y")

    if do_walk_forward:
        # Walk-forward mode
        wf_table = Table(title="Walk-Forward Analysis (5yr, 252/63)", show_lines=True)
        wf_table.add_column("Symbol", style="bold cyan", width=8)
        wf_table.add_column("Strategy", width=20)
        wf_table.add_column("Windows", justify="right", width=8)
        wf_table.add_column("Avg Ret", justify="right", width=9)
        wf_table.add_column("Avg Sharpe", justify="right", width=10)
        wf_table.add_column("Best", justify="right", width=9)
        wf_table.add_column("Worst", justify="right", width=9)
        wf_table.add_column("Win%", justify="right", width=7)

        for symbol in symbols:
            console.print(f"[bold]Walk-forward: {symbol}...[/]")
            for name, func in strategies.items():
                wf = run_walk_forward(symbol, name, func)
                if not wf or not wf["windows"]:
                    continue

                ret_style = "green" if wf["avg_return"] > 0 else "red"
                wf_table.add_row(
                    symbol,
                    name,
                    str(wf["total_windows"]),
                    f"[{ret_style}]{wf['avg_return']:.1f}%[/]",
                    f"{wf['avg_sharpe']:.2f}",
                    f"{wf['best_return']:.1f}%",
                    f"{wf['worst_return']:.1f}%",
                    f"{wf['consistency']:.0f}%",
                )

                # Show per-window detail
                for w in wf["windows"]:
                    wr = "green" if w["return_pct"] > 0 else "red"
                    console.print(
                        f"  Window {w['window']}: {w['test_start']} → {w['test_end']}  "
                        f"[{wr}]{w['return_pct']:+.1f}%[/]  "
                        f"Sharpe {w['sharpe']:.2f}  "
                        f"Trades {w['trades']}  "
                        f"WR {w['win_rate']:.0f}%"
                    )
                console.print()

        console.print(wf_table)
        return

    # Standard backtest mode
    result = None
    table = Table(title="Backtest Results (2yr daily, 5bps slippage)", show_lines=True)
    table.add_column("Symbol", style="bold cyan", width=8)
    table.add_column("Strategy", width=20)
    table.add_column("Return", justify="right", width=9)
    table.add_column("Bench", justify="right", width=9)
    table.add_column("Alpha", justify="right", width=8)
    table.add_column("Win Rate", justify="right", width=9)
    table.add_column("Trades", justify="right", width=7)
    table.add_column("PF", justify="right", width=6)
    table.add_column("Max DD", justify="right", width=8)
    table.add_column("Sharpe", justify="right", width=7)
    table.add_column("Sortino", justify="right", width=8)

    for symbol in symbols:
        console.print(f"[bold]Backtesting {symbol}...[/]")
        for name, func in strategies.items():
            result = run_backtest(symbol, name, func, benchmark_bars=spy_bars)
            if not result:
                continue

            s = result.summary()
            ret_style = "green" if result.total_return_pct > 0 else "red"
            alpha_style = "green" if result.alpha and result.alpha > 0 else "red"

            table.add_row(
                symbol,
                name,
                f"[{ret_style}]{s['total_return']}[/]",
                s.get("benchmark_return", "-"),
                f"[{alpha_style}]{s.get('alpha', '-')}[/]" if "alpha" in s else "-",
                s["win_rate"],
                str(s["total_trades"]),
                s["profit_factor"],
                s["max_drawdown"],
                s["sharpe_ratio"],
                s["sortino_ratio"],
            )

    console.print()
    console.print(table)

    # Print recent trades for the last symbol/strategy combo
    if result and result.trades:
        console.print(f"\n[bold]Last 5 trades ({symbols[-1]}):[/]")
        trade_table = Table(show_lines=False)
        trade_table.add_column("Entry", width=12)
        trade_table.add_column("Exit", width=12)
        trade_table.add_column("Dir", width=6)
        trade_table.add_column("Entry$", justify="right", width=10)
        trade_table.add_column("Exit$", justify="right", width=10)
        trade_table.add_column("P&L%", justify="right", width=8)
        trade_table.add_column("Bars", justify="right", width=5)
        trade_table.add_column("Reason", width=12)

        for t in result.trades[-5:]:
            pnl_style = "green" if t.pnl > 0 else "red"
            trade_table.add_row(
                t.entry_time.strftime("%Y-%m-%d"),
                t.exit_time.strftime("%Y-%m-%d"),
                t.direction.value,
                f"{t.entry_price:.2f}",
                f"{t.exit_price:.2f}",
                f"[{pnl_style}]{t.pnl_pct:.2f}%[/]",
                str(t.bars_held),
                t.exit_reason,
            )
        console.print(trade_table)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        console.print(__doc__)
        sys.exit(0)
    main()
