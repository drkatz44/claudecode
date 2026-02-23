#!/usr/bin/env python3
"""Agent-based trading pipeline — regime-aware options/futures scanning.

Usage:
    uv run python scripts/agent_pipeline.py                  # full daily scan
    uv run python scripts/agent_pipeline.py --symbol ES      # single symbol
    uv run python scripts/agent_pipeline.py --symbols SPY,QQQ,GLD  # multiple symbols
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

from market_agent import validate_symbol
from market_agent.agents.orchestrator import Orchestrator
from market_agent.agents.state import PortfolioState

console = Console()


def build_state(args: argparse.Namespace) -> PortfolioState:
    """Build initial PortfolioState from CLI args."""
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
    """Display regime info."""
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
    """Display trade proposals in a Rich table."""
    if not state.proposals:
        console.print("[dim]No trade proposals generated[/dim]")
        return

    table = Table(title=f"Trade Proposals ({len(state.proposals)})")
    table.add_column("Symbol", style="cyan")
    table.add_column("Strategy", style="green")
    table.add_column("Credit", justify="right")
    table.add_column("Max Loss", justify="right")
    table.add_column("Size %", justify="right")
    table.add_column("Legs", style="dim")
    table.add_column("Rationale")

    for p in state.proposals:
        credit = f"${p.credit:.2f}" if p.credit else "-"
        max_loss = f"${p.max_loss:.2f}" if p.max_loss else "undef"
        legs_str = " / ".join(
            f"{l.get('side','?')[0].upper()} {l.get('strike','?')} {l.get('type','?')[0].upper()}"
            for l in p.legs[:4]
        )
        rationale = p.rationale[0] if p.rationale else ""

        table.add_row(
            p.symbol,
            p.strategy_type,
            credit,
            max_loss,
            f"{p.position_size_pct:.1f}%",
            legs_str,
            rationale,
        )

    console.print(table)


def display_alerts(state: PortfolioState) -> None:
    """Display any alerts."""
    for alert in state.alerts:
        if alert.startswith("WARN"):
            console.print(f"[yellow]{alert}[/yellow]")
        else:
            console.print(f"[dim]{alert}[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Agent-based trading pipeline")
    parser.add_argument("--symbol", type=str, help="Single symbol to scan")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--net-liq", type=float, default=75000, help="Net liquidation value")
    parser.add_argument("--buying-power", type=float, default=75000, help="Buying power")
    parser.add_argument("--max-proposals", type=int, default=10, help="Max proposals to show")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print("[bold]Agent Pipeline[/bold]", style="blue")
    console.print()

    state = build_state(args)
    orchestrator = Orchestrator(max_proposals=args.max_proposals)
    state = orchestrator.run(state)

    display_regime(state)
    console.print()
    display_proposals(state)
    console.print()
    display_alerts(state)


if __name__ == "__main__":
    main()
