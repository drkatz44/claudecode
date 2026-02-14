#!/usr/bin/env python3
"""Run backtests on historical data.

Usage:
    uv run python scripts/backtest.py AAPL                    # all strategies on AAPL
    uv run python scripts/backtest.py AAPL momentum_crossover  # specific strategy
    uv run python scripts/backtest.py SPY,QQQ,AAPL            # multiple symbols
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.table import Table

from market_agent.backtest.engine import backtest
from market_agent.backtest.strategies import macd_momentum, mean_reversion_bb, momentum_crossover
from market_agent.data.fetcher import get_bars

console = Console()

STRATEGIES = {
    "momentum_crossover": momentum_crossover,
    "mean_reversion_bb": mean_reversion_bb,
    "macd_momentum": macd_momentum,
}


def run_backtest(symbol: str, strategy_name: str, strategy_func, period: str = "2y"):
    bars = get_bars(symbol, period=period)
    if len(bars) < 50:
        console.print(f"  [red]Not enough data for {symbol}[/]")
        return None

    result = backtest(
        bars=bars,
        signal_func=strategy_func,
        initial_capital=10000.0,
        position_size_pct=10.0,
    )
    return result


def main():
    if len(sys.argv) < 2:
        console.print("Usage: python scripts/backtest.py SYMBOL[,SYMBOL2,...] [strategy]")
        console.print(f"Strategies: {', '.join(STRATEGIES.keys())}")
        sys.exit(1)

    symbols = sys.argv[1].upper().split(",")
    strategy_filter = sys.argv[2] if len(sys.argv) > 2 else None

    strategies = STRATEGIES
    if strategy_filter and strategy_filter in STRATEGIES:
        strategies = {strategy_filter: STRATEGIES[strategy_filter]}

    # Results table
    table = Table(title="Backtest Results (2yr daily)", show_lines=True)
    table.add_column("Symbol", style="bold cyan", width=8)
    table.add_column("Strategy", width=20)
    table.add_column("Return", justify="right", width=9)
    table.add_column("Win Rate", justify="right", width=9)
    table.add_column("Trades", justify="right", width=7)
    table.add_column("Avg Win", justify="right", width=9)
    table.add_column("Avg Loss", justify="right", width=9)
    table.add_column("PF", justify="right", width=6)
    table.add_column("Max DD", justify="right", width=8)
    table.add_column("Sharpe", justify="right", width=7)
    table.add_column("Avg Hold", justify="right", width=8)

    for symbol in symbols:
        console.print(f"[bold]Backtesting {symbol}...[/]")
        for name, func in strategies.items():
            result = run_backtest(symbol, name, func)
            if not result:
                continue

            s = result.summary()
            ret_style = "green" if result.total_return_pct > 0 else "red"

            table.add_row(
                symbol,
                name,
                f"[{ret_style}]{s['total_return']}[/]",
                s["win_rate"],
                str(s["total_trades"]),
                s["avg_win"],
                s["avg_loss"],
                s["profit_factor"],
                s["max_drawdown"],
                s["sharpe_ratio"],
                s["avg_bars_held"],
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
    main()
