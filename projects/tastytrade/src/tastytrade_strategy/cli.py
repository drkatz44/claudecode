"""Typer CLI for tastytrade-strategy.

Supplementary to the Claude + MCP interface. Provides direct access to
journal management, screening, and risk checking.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .journal import Journal
from .models import MarketMetrics, OrderLeg, RiskProfile
from .risk import check_trade, portfolio_from_positions
from .screener import ScreenCriteria, screen

app = typer.Typer(name="tt-strategy", help="Tastytrade options strategy tools")
console = Console()


# ---------------------------------------------------------------------------
# Journal commands
# ---------------------------------------------------------------------------

@app.command()
def journal_list():
    """List open trades in the journal."""
    journal = Journal()
    trades = journal.get_open_trades()
    if not trades:
        console.print("[dim]No open trades.[/dim]")
        return

    table = Table(title="Open Trades")
    table.add_column("ID", style="cyan")
    table.add_column("Date", style="dim")
    table.add_column("Symbol", style="bold")
    table.add_column("Strategy")
    table.add_column("Entry", justify="right")
    table.add_column("Rationale")

    for t in trades:
        table.add_row(
            str(t.id),
            t.timestamp[:10],
            t.underlying,
            t.strategy_type.value,
            str(t.entry_price),
            t.rationale[:40] if t.rationale else "",
        )
    console.print(table)


@app.command()
def journal_stats():
    """Show summary statistics for closed trades."""
    journal = Journal()
    stats = journal.summary_stats()

    if stats["total_trades"] == 0:
        console.print("[dim]No closed trades yet.[/dim]")
        return

    table = Table(title="Trade Statistics")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Total Trades", str(stats["total_trades"]))
    table.add_row("Total P&L", f"${stats['total_pnl']}")
    table.add_row("Winners", str(stats["winners"]))
    table.add_row("Losers", str(stats["losers"]))
    table.add_row("Win Rate", f"{stats['win_rate']:.1%}")
    table.add_row("Avg P&L", f"${stats['avg_pnl']:.2f}")
    console.print(table)


@app.command()
def journal_close(
    trade_id: int = typer.Argument(..., help="Trade ID to close"),
    exit_price: float = typer.Option(..., "--exit", "-e", help="Exit price"),
    pnl: float = typer.Option(..., "--pnl", "-p", help="Realized P&L"),
):
    """Close an open trade by ID."""
    journal = Journal()
    result = journal.close_trade(
        trade_id,
        exit_price=Decimal(str(exit_price)),
        pnl=Decimal(str(pnl)),
    )
    if result and result.status.value == "closed":
        console.print(f"[green]Trade #{trade_id} closed. P&L: ${pnl}[/green]")
    else:
        console.print(f"[red]Trade #{trade_id} not found or already closed.[/red]")


# ---------------------------------------------------------------------------
# Screen command
# ---------------------------------------------------------------------------

@app.command()
def screen_cmd(
    metrics_file: Path = typer.Argument(..., help="JSON file with market metrics"),
    iv_rank_min: float = typer.Option(0.30, "--iv-min", help="Min IV rank (0-1)"),
    iv_rank_max: float = typer.Option(1.0, "--iv-max", help="Max IV rank (0-1)"),
    liquidity_min: float | None = typer.Option(None, "--liq-min", help="Min liquidity rating"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
):
    """Screen symbols from pre-fetched metrics JSON."""
    if not metrics_file.exists():
        console.print(f"[red]File not found: {metrics_file}[/red]")
        raise typer.Exit(1)

    raw = json.loads(metrics_file.read_text())
    if not isinstance(raw, list):
        raw = [raw]

    metrics_list = [MarketMetrics(**m) for m in raw]
    criteria = ScreenCriteria(
        iv_rank_min=Decimal(str(iv_rank_min)),
        iv_rank_max=Decimal(str(iv_rank_max)),
        liquidity_min=Decimal(str(liquidity_min)) if liquidity_min is not None else None,
    )
    results = screen(metrics_list, criteria)[:limit]

    if not results:
        console.print("[dim]No symbols matched criteria.[/dim]")
        return

    table = Table(title="Screen Results")
    table.add_column("Symbol", style="bold")
    table.add_column("IV Rank", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Reasons")

    for r in results:
        table.add_row(
            r.symbol,
            f"{r.metrics.iv_rank}",
            f"{r.score:.1f}",
            "; ".join(r.reasons) if r.reasons else "",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Risk check command
# ---------------------------------------------------------------------------

@app.command()
def risk_check(
    portfolio_file: Path = typer.Argument(..., help="JSON with positions + balances"),
    max_loss: float = typer.Option(..., "--max-loss", help="Strategy max loss"),
    max_profit: float = typer.Option(..., "--max-profit", help="Strategy max profit"),
    symbol: str = typer.Option("SPY", "--symbol", "-s", help="Underlying symbol"),
    expiration: str = typer.Option("2025-12-31", "--exp", help="Expiration date"),
):
    """Check a proposed trade against portfolio risk rules."""
    if not portfolio_file.exists():
        console.print(f"[red]File not found: {portfolio_file}[/red]")
        raise typer.Exit(1)

    raw = json.loads(portfolio_file.read_text())
    positions_data = raw.get("positions", [])
    balances_data = raw.get("balances", {})

    portfolio = portfolio_from_positions(positions_data, balances_data)
    risk_profile = RiskProfile(
        max_profit=Decimal(str(max_profit)),
        max_loss=Decimal(str(max_loss)),
    )
    legs = [
        OrderLeg(
            symbol=symbol,
            action="Sell to Open",
            quantity=1,
            option_type="P",
            strike_price=float(max_loss / 100 + max_profit / 100),
            expiration_date=expiration,
        )
    ]

    result = check_trade(risk_profile, legs, portfolio)

    if result.approved:
        console.print("[green]APPROVED[/green]")
    else:
        console.print("[red]REJECTED[/red]")

    if result.violations:
        console.print("\n[red]Violations:[/red]")
        for v in result.violations:
            console.print(f"  - {v}")

    if result.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            console.print(f"  - {w}")


if __name__ == "__main__":
    app()
