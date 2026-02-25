#!/usr/bin/env python3
"""Agent-based trading pipeline — regime-aware options/futures scanning.

Usage:
    uv run python scripts/agent_pipeline.py                        # full daily scan
    uv run python scripts/agent_pipeline.py --symbol SPY           # single symbol
    uv run python scripts/agent_pipeline.py --symbols SPY,QQQ,GLD  # multiple symbols
    uv run python scripts/agent_pipeline.py --eval                  # with historical evaluation
    uv run python scripts/agent_pipeline.py --org-chart             # show system architecture
"""

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich import box

from market_agent import validate_symbol
from market_agent.agents.orchestrator import Orchestrator
from market_agent.agents.state import PortfolioState

console = Console()


# ---------------------------------------------------------------------------
# Org Chart
# ---------------------------------------------------------------------------

def print_org_chart() -> None:
    """Print system architecture as a Rich tree."""
    root = Tree("[bold blue]market-agent[/bold blue]  Agent System")

    # Data layer
    data = root.add("[bold cyan]Data Layer[/bold cyan]")
    data.add("fetcher.py     yfinance bars, quotes, option chains")
    data.add("models.py      Bar, OptionQuote, Signal (Pydantic)")
    data.add("theta.py       Historical options provider (yfinance | Theta Data)")
    data.add("futures.py     14 futures contract specs")
    data.add("config.py      ~/.market-agent/config.yaml")

    # Analysis layer
    analysis = root.add("[bold cyan]Analysis Layer[/bold cyan]")
    analysis.add("black_scholes.py   BS price, delta, gamma, theta, vega, IV solver")
    analysis.add("vol_regime.py      VIX classification, term structure, IVx")
    analysis.add("options.py         IV rank, skew, strike selection (BS delta)")
    analysis.add("kelly.py           Kelly Criterion → position size multiplier")
    analysis.add("technical.py       15 indicators (SMA, RSI, MACD, BB, ATR…)")
    analysis.add("screener.py        Momentum, reversion, volatility screens")

    # Backtest data sources
    bt_data = root.add("[bold cyan]Backtest Data Sources[/bold cyan]  (priority order)")
    bt_data.add("[bold]1.[/bold] tastytrade API  [dim]data/tasty_backtest.py[/dim]  real fills — needs tastytrade_token in config")
    bt_data.add("[bold]2.[/bold] Theta Data      [dim]data/theta.py[/dim]           historical chains — needs theta_data_key in config")
    bt_data.add("[bold]3.[/bold] YFinance        [dim]data/theta.py[/dim]           proxy: theta decay + price move (default)")

    # Agent pipeline
    pipeline = root.add("[bold green]Agent Pipeline[/bold green]  (state: PortfolioState)")

    r1 = pipeline.add("[bold]1. RegimeDetector[/bold]   [dim]agents/regime.py[/dim]")
    r1.add("Reads: VIX bars (yfinance)")
    r1.add("Writes: state.regime  {vix_level, regime, ivr, ivx, term_structure}")

    r2 = pipeline.add("[bold]2. TradeArchitect[/bold]   [dim]agents/architect.py[/dim]")
    r2.add("Reads: state.regime, state.scan_symbols")
    r2.add("Logic: regime → playbook (LOW=calendars, NORMAL=strangles, HIGH=jade lizards)")
    r2.add("Writes: state.proposals  {symbol, strategy, legs, position_size_pct}")

    r3 = pipeline.add("[bold]3. TradeEvaluator[/bold]   [dim]agents/evaluator.py[/dim]  [yellow](--eval)[/yellow]")
    r3.add("Reads: state.proposals")
    r3.add("Runs: backtest_structure() over 252-day lookback")
    r3.add("Applies: Kelly Criterion to position_size_pct")
    r3.add("Writes: proposal.eval_stats  {win_rate, avg_dit, sample_size, sharpe}")

    r4 = pipeline.add("[bold]4. RiskMonitor[/bold]      [dim]agents/risk_monitor.py[/dim]")
    r4.add("Entry: risk_score = f(BP_impact, correlation, regime_fit, IVR)")
    r4.add("In-trade: ROLL at 21 DTE | CLOSE at 2× credit | ADJUST delta breach")
    r4.add("Writes: proposal.risk_score, state.alerts")

    r5 = pipeline.add("[bold]5. MadmanScout[/bold]      [dim]agents/madman.py[/dim]")
    r5.add("Earnings calendars: 5-15d pre-earnings → 0.15% allocation")
    r5.add("VIX call spreads: low VIX + FOMC within 14d → 0.15% allocation")
    r5.add("Back ratios: high vol net-credit setups → 0.15% allocation")
    r5.add("0DTE gamma: Monday/Wednesday/Friday flag (informational)")
    r5.add("Writes: state.proposals (appends madman=True proposals)")

    r6 = pipeline.add("[bold]6. Orchestrator[/bold]     [dim]agents/orchestrator.py[/dim]")
    r6.add("Constraints: BP ≤ 50%, max 15 positions, max 3 per symbol")
    r6.add("Filters: risk_score > 0.80 rejected, size > 5% rejected")
    r6.add("Output: state.proposals (final, filtered)")

    # Backtest layer
    bt = root.add("[bold cyan]Backtest Layer[/bold cyan]")
    bt.add("options_engine.py   Multi-leg options backtester (DIT, MAE, P&L)")
    bt.add("engine.py           Equity long/short walk-forward backtester")
    bt.add("strategies.py       4 strategy implementations")

    # Execution
    exec_node = root.add("[bold red]Execution (tastytrade)[/bold red]  [dim]requires human approval[/dim]")
    exec_node.add("recommender.py → to_order_legs() → tasty-agent MCP")
    exec_node.add("dry_run=True default — all orders require explicit confirmation")

    console.print(root)
    console.print()
    console.print(
        "[dim]Position sizing: regime defaults × Kelly multiplier (0.5×–1.5×) | "
        "Madman hard cap: 0.10–0.20%[/dim]"
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def build_state(args: argparse.Namespace) -> PortfolioState:
    state = PortfolioState(
        net_liq=Decimal(str(args.net_liq)),
        buying_power=Decimal(str(args.buying_power)),
    )
    if args.symbol:
        state.scan_symbols = [validate_symbol(args.symbol)]
    elif args.symbols:
        state.scan_symbols = [validate_symbol(s.strip()) for s in args.symbols.split(",")]
    return state


def display_regime(state: PortfolioState) -> None:
    if not state.regime:
        console.print("[red]No regime detected[/red]")
        return

    r = state.regime
    color = {"low": "green", "normal": "yellow", "high": "red"}[r.regime.value]
    console.print(Panel(
        f"[bold {color}]{r.regime.value.upper()}[/bold {color}]  "
        f"VIX: {r.vix_level:.1f}  "
        f"5d chg: {r.vix_5d_change:+.1f}%  "
        f"IVR: {r.ivr:.0f}  "
        f"IVx: {r.ivx:.1f}%  "
        f"Term: {r.vix_term_structure}",
        title="Regime",
    ))


def display_proposals(state: PortfolioState) -> None:
    regular = [p for p in state.proposals if not p.is_madman]
    madman = [p for p in state.proposals if p.is_madman]

    if regular:
        _display_proposal_table(regular, title="Trade Proposals", style="cyan")

    if madman:
        console.print()
        _display_proposal_table(madman, title="[bold yellow]Madman Scout[/bold yellow] (asymmetric)", style="yellow")

    if not regular and not madman:
        console.print("[dim]No trade proposals generated[/dim]")


def _display_proposal_table(proposals, title: str, style: str) -> None:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("Symbol", style=style)
    table.add_column("Strategy", style="green")
    table.add_column("Credit", justify="right")
    table.add_column("Risk", justify="right")
    table.add_column("Size %", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("AvgDIT", justify="right")
    table.add_column("n", justify="right")
    table.add_column("Rationale")

    for p in proposals:
        credit = f"${p.credit:.2f}" if p.credit else "-"
        risk_color = "red" if p.risk_score > 0.6 else ("yellow" if p.risk_score > 0.3 else "green")
        risk_str = f"[{risk_color}]{p.risk_score:.2f}[/{risk_color}]"

        if p.eval_stats:
            win_rate = p.eval_stats.get("win_rate")
            avg_dit = p.eval_stats.get("avg_dit")
            sample = p.eval_stats.get("sample_size", "-")
            win_str = f"{win_rate:.0f}%" if win_rate is not None else "-"
            dit_str = f"{avg_dit:.0f}d" if avg_dit is not None else "-"
        else:
            win_str = dit_str = "-"
            sample = "-"

        rationale = p.rationale[0] if p.rationale else ""
        table.add_row(
            p.symbol, p.strategy_type, credit, risk_str,
            f"{p.position_size_pct:.2f}%", win_str, dit_str, str(sample),
            rationale,
        )

    console.print(table)


def display_alerts(state: PortfolioState) -> None:
    if not state.alerts:
        return
    console.print()
    for alert in state.alerts:
        if alert.startswith("ROLL") or alert.startswith("CLOSE") or alert.startswith("ADJUST"):
            console.print(f"[bold red]{alert}[/bold red]")
        elif alert.startswith("WARN"):
            console.print(f"[yellow]{alert}[/yellow]")
        else:
            console.print(f"[dim]{alert}[/dim]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agent-based trading pipeline")
    parser.add_argument("--symbol", type=str, help="Single symbol to scan")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--net-liq", type=float, default=75000, help="Net liquidation value")
    parser.add_argument("--buying-power", type=float, default=75000, help="Buying power")
    parser.add_argument("--max-proposals", type=int, default=10, help="Max proposals to show")
    parser.add_argument("--eval", action="store_true", help="Enable historical evaluation (slow)")
    parser.add_argument("--no-madman", action="store_true", help="Disable Madman Scout")
    parser.add_argument("--org-chart", action="store_true", help="Print system org chart and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.org_chart:
        print_org_chart()
        return

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print("[bold]Agent Pipeline[/bold]", style="blue")
    console.print()

    state = build_state(args)
    orchestrator = Orchestrator(
        max_proposals=args.max_proposals,
        enable_eval=args.eval,
        enable_madman=not args.no_madman,
    )
    state = orchestrator.run(state)

    display_regime(state)
    console.print()
    display_proposals(state)
    display_alerts(state)


if __name__ == "__main__":
    main()
