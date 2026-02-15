"""Report generation for backtest results.

Produces markdown reports with strategy comparisons, trade summaries,
and chart references.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .engine import BacktestResult

REPORTS_DIR = Path.home() / ".market-agent" / "reports"


def _safe_name(name: str) -> str:
    """Sanitize string for use in filenames."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "", name)


def generate_report(
    symbol: str,
    results: dict[str, BacktestResult],
    walk_forward: Optional[dict[str, dict]] = None,
    chart_paths: Optional[dict[str, Path]] = None,
) -> str:
    """Generate a markdown report comparing strategy backtests.

    Args:
        symbol: Ticker symbol
        results: Dict mapping strategy_name -> BacktestResult
        walk_forward: Optional dict mapping strategy_name -> walk-forward results
        chart_paths: Optional dict mapping strategy_name -> chart file path

    Returns:
        Markdown string.
    """
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# Backtest Report: {symbol}")
    lines.append(f"")
    lines.append(f"Generated: {now}")
    lines.append(f"")

    if not results:
        lines.append("No backtest results available.")
        return "\n".join(lines)

    # Strategy comparison table
    lines.append("## Strategy Comparison")
    lines.append("")
    lines.append("| Strategy | Return | Win Rate | Trades | PF | Sharpe | Sortino | Max DD | Alpha |")
    lines.append("|----------|--------|----------|--------|----|--------|---------|--------|-------|")

    best_strat = None
    best_return = float("-inf")

    for name, result in results.items():
        ret = result.total_return_pct
        alpha_str = f"{result.alpha:+.1f}%" if result.alpha is not None else "-"

        lines.append(
            f"| {name} | {ret:+.1f}% | {result.win_rate:.1f}% | "
            f"{result.total_trades} | {result.profit_factor:.2f} | "
            f"{result.sharpe_ratio:.2f} | {result.sortino_ratio:.2f} | "
            f"{result.max_drawdown_pct:.1f}% | {alpha_str} |"
        )

        if ret > best_return:
            best_return = ret
            best_strat = name

    lines.append("")

    # Best/worst highlights
    if best_strat and len(results) > 1:
        worst_strat = min(results, key=lambda k: results[k].total_return_pct)
        lines.append(f"**Best strategy:** {best_strat} ({best_return:+.1f}%)")
        worst_ret = results[worst_strat].total_return_pct
        lines.append(f"**Worst strategy:** {worst_strat} ({worst_ret:+.1f}%)")
        lines.append("")

    # Walk-forward summary
    if walk_forward:
        lines.append("## Walk-Forward Analysis")
        lines.append("")
        lines.append("| Strategy | Windows | Avg Return | Avg Sharpe | Best | Worst | Consistency |")
        lines.append("|----------|---------|------------|------------|------|-------|-------------|")

        for name, wf in walk_forward.items():
            if not wf or not wf.get("windows"):
                continue
            lines.append(
                f"| {name} | {wf['total_windows']} | {wf['avg_return']:+.1f}% | "
                f"{wf['avg_sharpe']:.2f} | {wf['best_return']:+.1f}% | "
                f"{wf['worst_return']:+.1f}% | {wf['consistency']:.0f}% |"
            )
        lines.append("")

    # Chart references
    if chart_paths:
        lines.append("## Charts")
        lines.append("")
        for name, path in chart_paths.items():
            lines.append(f"- **{name}**: `{path}`")
        lines.append("")

    # Last 10 trades for best strategy
    if best_strat and results[best_strat].trades:
        trades = results[best_strat].trades[-10:]
        lines.append(f"## Recent Trades ({best_strat})")
        lines.append("")
        lines.append("| Entry | Exit | Dir | Entry$ | Exit$ | P&L% | Bars | Reason |")
        lines.append("|-------|------|-----|--------|-------|------|------|--------|")

        for t in trades:
            pnl_fmt = f"{t.pnl_pct:+.2f}%"
            lines.append(
                f"| {t.entry_time.strftime('%Y-%m-%d')} | {t.exit_time.strftime('%Y-%m-%d')} | "
                f"{t.direction.value} | {t.entry_price:.2f} | {t.exit_price:.2f} | "
                f"{pnl_fmt} | {t.bars_held} | {t.exit_reason} |"
            )
        lines.append("")

    return "\n".join(lines)


def generate_multi_report(
    all_results: dict[str, dict[str, BacktestResult]],
) -> str:
    """Generate aggregate report ranking strategies across multiple symbols.

    Args:
        all_results: Dict mapping symbol -> {strategy_name -> BacktestResult}

    Returns:
        Markdown string.
    """
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append("# Multi-Symbol Backtest Summary")
    lines.append(f"")
    lines.append(f"Generated: {now}")
    lines.append(f"Symbols: {', '.join(all_results.keys())}")
    lines.append("")

    # Aggregate by strategy
    strategy_stats: dict[str, list[float]] = {}
    for symbol, results in all_results.items():
        for strat_name, result in results.items():
            if strat_name not in strategy_stats:
                strategy_stats[strat_name] = []
            strategy_stats[strat_name].append(result.total_return_pct)

    lines.append("## Strategy Rankings (Avg Return)")
    lines.append("")
    lines.append("| Strategy | Avg Return | # Symbols | Best | Worst |")
    lines.append("|----------|------------|-----------|------|-------|")

    ranked = sorted(strategy_stats.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True)
    for name, returns in ranked:
        avg = sum(returns) / len(returns)
        lines.append(
            f"| {name} | {avg:+.1f}% | {len(returns)} | "
            f"{max(returns):+.1f}% | {min(returns):+.1f}% |"
        )
    lines.append("")

    # Per-symbol best strategy
    lines.append("## Best Strategy Per Symbol")
    lines.append("")
    lines.append("| Symbol | Best Strategy | Return |")
    lines.append("|--------|---------------|--------|")

    for symbol, results in all_results.items():
        if results:
            best = max(results.items(), key=lambda x: x[1].total_return_pct)
            lines.append(f"| {symbol} | {best[0]} | {best[1].total_return_pct:+.1f}% |")
    lines.append("")

    return "\n".join(lines)


def save_report(content: str, symbol: str) -> Path:
    """Save report markdown to file.

    Args:
        content: Markdown report string
        symbol: Symbol name (used in filename)

    Returns:
        Path to saved file.
    """
    safe_sym = _safe_name(symbol)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_sym}_{datetime.now().strftime('%Y%m%d')}.md"
    path = REPORTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return path
