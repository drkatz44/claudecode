"""Typer CLI for tastytrade-strategy.

Supplementary to the Claude + MCP interface. Provides direct access to
journal management, screening, and risk checking.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .chain_builder import ChainBuilderError, build_iron_condor, build_short_put, build_strangle, build_vertical_spread
from .chain_parser import parse_greeks_response, parse_nested_chain
from .journal import Journal
from .mcp_parser import parse_market_metrics_response
from .models import Direction, MarketMetrics, OptionType, OrderLeg, RiskProfile
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
# Screen agent command (JSON output for Claude Task subagents)
# ---------------------------------------------------------------------------

@app.command()
def screen_agent(
    iv_rank_min: float = typer.Option(0.30, "--iv-min", help="Min IV rank (0-1)"),
    iv_rank_max: float = typer.Option(1.0, "--iv-max", help="Max IV rank (0-1)"),
    liquidity_min: float | None = typer.Option(None, "--liq-min", help="Min liquidity rating"),
    earnings_days: int = typer.Option(7, "--earnings-days", help="Exclude symbols with earnings within N days"),
    beta_max: float | None = typer.Option(None, "--beta-max", help="Max absolute beta"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results to return"),
    input_file: Path | None = typer.Option(None, "--input", "-i", help="JSON file (default: stdin)"),
):
    """Screen symbols from raw tastytrade market-metrics JSON. Outputs compact JSON.

    Reads raw MCP/API response from stdin or --input file. Designed for use
    as a Claude Task subagent — outputs machine-readable JSON, not a table.

    Usage (pipe MCP response):
        echo '<mcp_response>' | uv run tt-strategy screen-agent --iv-min 0.40

    Usage (file):
        uv run tt-strategy screen-agent --input metrics.json --limit 5
    """
    if input_file:
        if not input_file.exists():
            typer.echo(json.dumps({"error": f"File not found: {input_file}"}))
            raise typer.Exit(1)
        raw_text = input_file.read_text()
    else:
        raw_text = sys.stdin.read()

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        typer.echo(json.dumps({"error": f"Invalid JSON: {e}"}))
        raise typer.Exit(1)

    metrics_list = parse_market_metrics_response(raw)

    if not metrics_list:
        typer.echo(json.dumps({"error": "No market metrics found in input"}))
        raise typer.Exit(1)

    criteria = ScreenCriteria(
        iv_rank_min=Decimal(str(iv_rank_min)),
        iv_rank_max=Decimal(str(iv_rank_max)),
        liquidity_min=Decimal(str(liquidity_min)) if liquidity_min is not None else None,
        earnings_exclusion_days=earnings_days,
        beta_max=Decimal(str(beta_max)) if beta_max is not None else None,
    )

    results = screen(metrics_list, criteria)[:limit]

    output = {
        "count": len(results),
        "criteria": {
            "iv_rank_min": str(criteria.iv_rank_min),
            "iv_rank_max": str(criteria.iv_rank_max),
            "liquidity_min": str(criteria.liquidity_min) if criteria.liquidity_min else None,
            "earnings_exclusion_days": criteria.earnings_exclusion_days,
            "beta_max": str(criteria.beta_max) if criteria.beta_max else None,
        },
        "results": [
            {
                "symbol": r.symbol,
                "score": float(r.score),
                "iv_rank": float(r.metrics.iv_rank),
                "iv": float(r.metrics.implied_volatility) if r.metrics.implied_volatility else None,
                "hv": float(r.metrics.historical_volatility) if r.metrics.historical_volatility else None,
                "liquidity": float(r.metrics.liquidity_rating) if r.metrics.liquidity_rating else None,
                "beta": float(r.metrics.beta) if r.metrics.beta else None,
                "earnings_date": r.metrics.earnings_date,
                "reasons": r.reasons,
            }
            for r in results
        ],
    }

    typer.echo(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Build strategy command (JSON output for Claude Task subagents)
# ---------------------------------------------------------------------------

_STRATEGIES = ["short_put", "vertical_spread", "iron_condor", "strangle"]

@app.command()
def build_strategy(
    strategy: str = typer.Argument(..., help=f"Strategy type: {', '.join(_STRATEGIES)}"),
    dte: int = typer.Option(45, "--dte", help="Target days to expiration"),
    put_delta: float = typer.Option(0.30, "--put-delta", help="Short put delta (absolute)"),
    call_delta: float = typer.Option(0.30, "--call-delta", help="Short call delta (absolute)"),
    long_put_delta: float = typer.Option(0.16, "--long-put-delta", help="Long put wing delta"),
    long_call_delta: float = typer.Option(0.16, "--long-call-delta", help="Long call wing delta"),
    quantity: int = typer.Option(1, "--quantity", "-q", help="Number of contracts"),
    chain_file: Path | None = typer.Option(None, "--chain", "-c", help="Nested option chain JSON (default: stdin)"),
    greeks_file: Path | None = typer.Option(None, "--greeks", "-g", help="Greeks JSON file (optional)"),
):
    """Build a strategy from an option chain. Outputs order-ready JSON.

    Reads nested option chain JSON from --chain file or stdin.
    Optionally enriches strikes with greeks from --greeks file.
    Designed for agent use — outputs machine-readable JSON.

    Usage (pipe chain from MCP):
        echo '<chain_response>' | uv run tt-strategy build-strategy iron_condor --dte 45

    Usage (files):
        uv run tt-strategy build-strategy short_put \\
          --chain chain.json --greeks greeks.json --dte 45 --put-delta 0.30
    """
    if strategy not in _STRATEGIES:
        typer.echo(json.dumps({"error": f"Unknown strategy '{strategy}'. Choose: {_STRATEGIES}"}))
        raise typer.Exit(1)

    # Load chain
    if chain_file:
        if not chain_file.exists():
            typer.echo(json.dumps({"error": f"Chain file not found: {chain_file}"}))
            raise typer.Exit(1)
        chain_text = chain_file.read_text()
    else:
        chain_text = sys.stdin.read()

    try:
        chain_raw = json.loads(chain_text)
    except json.JSONDecodeError as e:
        typer.echo(json.dumps({"error": f"Invalid chain JSON: {e}"}))
        raise typer.Exit(1)

    # Load greeks (optional)
    greeks_map = {}
    if greeks_file:
        if not greeks_file.exists():
            typer.echo(json.dumps({"error": f"Greeks file not found: {greeks_file}"}))
            raise typer.Exit(1)
        try:
            greeks_raw = json.loads(greeks_file.read_text())
            greeks_map = parse_greeks_response(greeks_raw)
        except json.JSONDecodeError as e:
            typer.echo(json.dumps({"error": f"Invalid greeks JSON: {e}"}))
            raise typer.Exit(1)

    # Parse chain
    contracts, expiration_date = parse_nested_chain(chain_raw, target_dte=dte, greeks_map=greeks_map)

    if not contracts:
        typer.echo(json.dumps({"error": "No contracts found in chain for the given DTE"}))
        raise typer.Exit(1)

    # Infer underlying from first contract
    underlying = contracts[0].underlying if contracts else ""

    try:
        if strategy == "short_put":
            result = build_short_put(
                contracts, underlying, expiration_date or "",
                target_delta=Decimal(str(put_delta)),
                quantity=quantity,
            )
        elif strategy == "vertical_spread":
            result = build_vertical_spread(
                contracts, underlying, expiration_date or "",
                option_type=OptionType.PUT,
                direction=Direction.BULLISH,
                short_delta=Decimal(str(put_delta)),
                long_delta=Decimal(str(long_put_delta)),
                quantity=quantity,
            )
        elif strategy == "iron_condor":
            result = build_iron_condor(
                contracts, underlying, expiration_date or "",
                put_short_delta=Decimal(str(put_delta)),
                put_long_delta=Decimal(str(long_put_delta)),
                call_short_delta=Decimal(str(call_delta)),
                call_long_delta=Decimal(str(long_call_delta)),
                quantity=quantity,
            )
        elif strategy == "strangle":
            result = build_strangle(
                contracts, underlying, expiration_date or "",
                put_delta=Decimal(str(put_delta)),
                call_delta=Decimal(str(call_delta)),
                quantity=quantity,
            )

        result["expiration_date_selected"] = expiration_date
        result["dte_target"] = dte
        result["greeks_available"] = bool(greeks_map)

        typer.echo(json.dumps(result, indent=2))

    except ChainBuilderError as e:
        typer.echo(json.dumps({"error": str(e)}))
        raise typer.Exit(1)


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
