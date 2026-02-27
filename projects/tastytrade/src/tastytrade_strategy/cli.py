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
from .risk import RiskRules, check_trade, portfolio_from_positions
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
# Journal agent commands (JSON output for Claude Task subagents)
# ---------------------------------------------------------------------------

@app.command()
def journal_log(
    credit: float = typer.Option(..., "--credit", "-c", help="Credit received (positive) or debit paid"),
    rationale: str = typer.Option("", "--rationale", "-r", help="Trade rationale"),
    profit_target: float | None = typer.Option(None, "--profit-target", help="Profit target price"),
    stop_loss: float | None = typer.Option(None, "--stop-loss", help="Stop loss price"),
    strategy_file: Path | None = typer.Option(None, "--strategy", "-s", help="build-strategy JSON (default: stdin)"),
):
    """Log a new trade from build-strategy output. Outputs JSON with trade ID.

    Reads strategy JSON from --strategy file or stdin.
    Designed for agent use — outputs machine-readable JSON.

    Usage (pipe from build-strategy):
        uv run tt-strategy build-strategy iron_condor ... | \\
          uv run tt-strategy journal-log --credit 1.85 --rationale "High IV, neutral"

    Usage (file):
        uv run tt-strategy journal-log --strategy strategy.json --credit 1.85
    """
    if strategy_file:
        if not strategy_file.exists():
            typer.echo(json.dumps({"error": f"Strategy file not found: {strategy_file}"}))
            raise typer.Exit(1)
        strategy_text = strategy_file.read_text()
    else:
        strategy_text = sys.stdin.read()

    try:
        s = json.loads(strategy_text)
    except json.JSONDecodeError as e:
        typer.echo(json.dumps({"error": f"Invalid strategy JSON: {e}"}))
        raise typer.Exit(1)

    # Map strategy_type string to StrategyType enum
    from .models import StrategyType as ST
    strategy_type_map = {v.value: v for v in ST}
    raw_type = s.get("strategy_type", "")
    strategy_type = strategy_type_map.get(raw_type)
    if strategy_type is None:
        typer.echo(json.dumps({"error": f"Unknown strategy_type '{raw_type}'. Valid: {list(strategy_type_map)}"}))
        raise typer.Exit(1)

    legs = [
        OrderLeg(
            symbol=leg.get("symbol", s.get("underlying", "")),
            action=leg.get("action", "Sell to Open"),
            quantity=int(leg.get("quantity", 1)),
            option_type=leg.get("option_type"),
            strike_price=leg.get("strike_price"),
            expiration_date=leg.get("expiration_date", s.get("expiration_date")),
        )
        for leg in s.get("legs", [])
    ]

    from .journal import Journal, JournalEntry
    entry = JournalEntry(
        underlying=s.get("underlying", ""),
        strategy_type=strategy_type,
        legs=legs,
        entry_price=Decimal(str(credit)),
        rationale=rationale,
        profit_target=Decimal(str(profit_target)) if profit_target is not None else None,
        stop_loss=Decimal(str(stop_loss)) if stop_loss is not None else None,
    )

    journal = Journal()
    logged = journal.log_trade(entry)

    typer.echo(json.dumps({
        "logged": True,
        "trade_id": logged.id,
        "underlying": logged.underlying,
        "strategy_type": logged.strategy_type.value,
        "entry_price": float(logged.entry_price),
        "rationale": logged.rationale,
        "timestamp": logged.timestamp,
        "legs": len(logged.legs),
    }))


@app.command()
def journal_query(
    action: str = typer.Argument(..., help="Action: open | stats | history | close"),
    trade_id: int | None = typer.Option(None, "--id", help="Trade ID (for close)"),
    exit_price: float | None = typer.Option(None, "--exit-price", help="Exit price (for close)"),
    pnl: float | None = typer.Option(None, "--pnl", help="Realized P&L (for close)"),
    underlying: str | None = typer.Option(None, "--underlying", "-u", help="Filter by underlying (history)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Result limit (history)"),
):
    """Query the trade journal. Outputs JSON.

    Actions:
      open     — list all open trades
      stats    — full analytics (win rate, P&L, by-strategy, by-underlying)
      history  — recent closed trades (--underlying to filter, --limit N)
      close    — close a trade (--id, --exit-price, --pnl required)

    Usage:
        uv run tt-strategy journal-query open
        uv run tt-strategy journal-query stats
        uv run tt-strategy journal-query history --underlying SPY --limit 10
        uv run tt-strategy journal-query close --id 42 --exit-price 0.65 --pnl 120
    """
    from .journal import Journal
    journal = Journal()

    if action == "open":
        trades = journal.get_open_trades()
        typer.echo(json.dumps({
            "count": len(trades),
            "trades": [
                {
                    "id": t.id,
                    "underlying": t.underlying,
                    "strategy_type": t.strategy_type.value,
                    "entry_price": float(t.entry_price),
                    "profit_target": float(t.profit_target) if t.profit_target else None,
                    "stop_loss": float(t.stop_loss) if t.stop_loss else None,
                    "rationale": t.rationale,
                    "timestamp": t.timestamp,
                    "legs": len(t.legs),
                    "expiration_date": t.legs[0].expiration_date if t.legs else None,
                }
                for t in trades
            ],
        }, indent=2))

    elif action == "stats":
        stats = journal.rich_stats()
        typer.echo(json.dumps(stats, indent=2))

    elif action == "history":
        trades = journal.get_history(underlying=underlying, limit=limit)
        typer.echo(json.dumps({
            "count": len(trades),
            "trades": [
                {
                    "id": t.id,
                    "underlying": t.underlying,
                    "strategy_type": t.strategy_type.value,
                    "entry_price": float(t.entry_price),
                    "exit_price": float(t.exit_price) if t.exit_price else None,
                    "pnl": float(t.pnl) if t.pnl else None,
                    "status": t.status.value,
                    "timestamp": t.timestamp,
                }
                for t in trades
            ],
        }, indent=2))

    elif action == "close":
        if trade_id is None or exit_price is None:
            typer.echo(json.dumps({"error": "close requires --id and --exit-price"}))
            raise typer.Exit(1)
        closed = journal.close_trade(
            trade_id,
            exit_price=Decimal(str(exit_price)),
            pnl=Decimal(str(pnl)) if pnl is not None else None,
        )
        if closed is None:
            typer.echo(json.dumps({"error": f"Trade {trade_id} not found or already closed"}))
            raise typer.Exit(1)
        typer.echo(json.dumps({
            "closed": True,
            "trade_id": closed.id,
            "underlying": closed.underlying,
            "strategy_type": closed.strategy_type.value,
            "entry_price": float(closed.entry_price),
            "exit_price": float(closed.exit_price) if closed.exit_price else None,
            "pnl": float(closed.pnl) if closed.pnl else None,
            "status": closed.status.value,
        }))

    else:
        typer.echo(json.dumps({"error": f"Unknown action '{action}'. Use: open | stats | history | close"}))
        raise typer.Exit(1)


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
# Risk agent command (JSON output for Claude Task subagents)
# ---------------------------------------------------------------------------

@app.command()
def risk_agent(
    portfolio_file: Path = typer.Argument(..., help="JSON file with MCP positions+balances response"),
    strategy_file: Path | None = typer.Option(None, "--strategy", "-s", help="build-strategy JSON (default: stdin)"),
    max_position_pct: float = typer.Option(0.05, "--max-position-pct", help="Max loss as fraction of NLV"),
    max_bp_pct: float = typer.Option(0.50, "--max-bp-pct", help="Max buying power usage fraction"),
    min_dte: int = typer.Option(7, "--min-dte", help="Minimum days to expiration"),
    max_correlated: int = typer.Option(3, "--max-correlated", help="Max positions per underlying"),
):
    """Run risk checks on a proposed strategy. Outputs compact JSON.

    Reads portfolio (positions + balances) from --portfolio file.
    Reads strategy from --strategy file or stdin (build-strategy output).
    Designed for agent use — outputs machine-readable JSON.

    Usage:
        uv run tt-strategy build-strategy iron_condor ... | \\
          uv run tt-strategy risk-agent portfolio.json

    Usage (files):
        uv run tt-strategy risk-agent portfolio.json --strategy strategy.json
    """
    # Load portfolio
    if not portfolio_file.exists():
        typer.echo(json.dumps({"error": f"Portfolio file not found: {portfolio_file}"}))
        raise typer.Exit(1)

    try:
        portfolio_raw = json.loads(portfolio_file.read_text())
    except json.JSONDecodeError as e:
        typer.echo(json.dumps({"error": f"Invalid portfolio JSON: {e}"}))
        raise typer.Exit(1)

    # Unwrap API envelope: {"data": {"items": [...]}} or {"data": {...}}
    positions_raw: list[dict] = []
    balances_raw: dict = {}

    if "positions" in portfolio_raw and "balances" in portfolio_raw:
        # Simple combined format: {"positions": [...], "balances": {...}}
        positions_raw = portfolio_raw["positions"]
        balances_raw = portfolio_raw["balances"]
    elif "data" in portfolio_raw:
        data = portfolio_raw["data"]
        if isinstance(data, list):
            positions_raw = data
        elif isinstance(data, dict) and "items" in data:
            positions_raw = data["items"]
        else:
            balances_raw = data
    else:
        positions_raw = portfolio_raw if isinstance(portfolio_raw, list) else []

    # Load strategy
    if strategy_file:
        if not strategy_file.exists():
            typer.echo(json.dumps({"error": f"Strategy file not found: {strategy_file}"}))
            raise typer.Exit(1)
        strategy_text = strategy_file.read_text()
    else:
        strategy_text = sys.stdin.read()

    try:
        strategy_raw = json.loads(strategy_text)
    except json.JSONDecodeError as e:
        typer.echo(json.dumps({"error": f"Invalid strategy JSON: {e}"}))
        raise typer.Exit(1)

    # Build portfolio snapshot
    portfolio = portfolio_from_positions(positions_raw, balances_raw)

    # Extract risk profile and legs from build-strategy output
    risk_data = strategy_raw.get("risk", {})
    legs_data = strategy_raw.get("legs", [])
    underlying = strategy_raw.get("underlying", "")
    strategy_type = strategy_raw.get("strategy_type", "unknown")
    expiration_date = strategy_raw.get("expiration_date", "")

    risk_profile = RiskProfile(
        max_profit=Decimal(str(risk_data.get("max_profit", 0))),
        max_loss=Decimal(str(risk_data.get("max_loss", 0))),
        breakevens=[Decimal(str(b)) for b in risk_data.get("breakevens", [])],
    )

    legs = [
        OrderLeg(
            symbol=leg.get("symbol", underlying),
            action=leg.get("action", "Sell to Open"),
            quantity=int(leg.get("quantity", 1)),
            option_type=leg.get("option_type"),
            strike_price=leg.get("strike_price"),
            expiration_date=leg.get("expiration_date", expiration_date),
        )
        for leg in legs_data
    ]

    rules = RiskRules(
        max_position_pct=Decimal(str(max_position_pct)),
        max_bp_usage_pct=Decimal(str(max_bp_pct)),
        min_dte=min_dte,
        max_correlated_positions=max_correlated,
    )

    result = check_trade(risk_profile, legs, portfolio, rules)

    # Build detail checks dict
    position_pct = (
        float(risk_profile.max_loss / portfolio.net_liquidating_value)
        if portfolio.net_liquidating_value > 0 else None
    )
    bp_usage = (
        float(1 - (portfolio.buying_power - risk_profile.max_loss) / portfolio.buying_power)
        if portfolio.buying_power > 0 else None
    )
    correlated = sum(1 for p in portfolio.positions if p.underlying == underlying)

    # DTE from first option leg
    dte_value: int | None = None
    from datetime import date as _date, datetime as _datetime
    for leg in legs:
        if leg.expiration_date:
            try:
                exp = _datetime.strptime(leg.expiration_date, "%Y-%m-%d").date()
                dte_value = (exp - _date.today()).days
                break
            except ValueError:
                pass

    output = {
        "approved": result.approved,
        "violations": result.violations,
        "warnings": result.warnings,
        "summary": (
            f"{'APPROVED' if result.approved else 'REJECTED'} — "
            f"{underlying} {strategy_type.replace('_', ' ').title()}"
            + (f" {expiration_date}" if expiration_date else "")
        ),
        "strategy": {
            "type": strategy_type,
            "underlying": underlying,
            "expiration_date": expiration_date,
            "max_profit": float(risk_profile.max_profit),
            "max_loss": float(risk_profile.max_loss),
            "risk_reward_ratio": float(risk_profile.risk_reward_ratio) if risk_profile.risk_reward_ratio else None,
        },
        "portfolio": {
            "nlv": float(portfolio.net_liquidating_value),
            "buying_power": float(portfolio.buying_power),
            "open_positions": len(portfolio.positions),
        },
        "checks": {
            "position_size_pct": round(position_pct, 4) if position_pct is not None else None,
            "position_size_limit": max_position_pct,
            "bp_usage_after": round(bp_usage, 4) if bp_usage is not None else None,
            "bp_usage_limit": max_bp_pct,
            "dte": dte_value,
            "dte_min": min_dte,
            "correlated_positions": correlated,
            "correlated_limit": max_correlated,
        },
    }

    typer.echo(json.dumps(output, indent=2))


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


# ---------------------------------------------------------------------------
# Pipeline command — chains screen → build → risk-check → journal
# ---------------------------------------------------------------------------

def _load_portfolio_from_file(portfolio_file: Path) -> tuple[list[dict], dict]:
    """Load and parse a portfolio JSON file into (positions, balances)."""
    portfolio_raw = json.loads(portfolio_file.read_text())
    positions_raw: list[dict] = []
    balances_raw: dict = {}

    if "positions" in portfolio_raw and "balances" in portfolio_raw:
        positions_raw = portfolio_raw["positions"]
        balances_raw = portfolio_raw["balances"]
    elif "data" in portfolio_raw:
        data = portfolio_raw["data"]
        if isinstance(data, list):
            positions_raw = data
        elif isinstance(data, dict) and "items" in data:
            positions_raw = data["items"]
        else:
            balances_raw = data
    else:
        positions_raw = portfolio_raw if isinstance(portfolio_raw, list) else []

    return positions_raw, balances_raw


def _journal_from_strategy(strategy_dict: dict, credit: float, rationale: str) -> "JournalEntry | None":
    """Build a JournalEntry from a build-strategy dict, or return None on failure."""
    from .models import StrategyType as ST
    from .journal import JournalEntry

    strategy_type_map = {v.value: v for v in ST}
    raw_type = strategy_dict.get("strategy_type", "")
    strategy_type = strategy_type_map.get(raw_type)
    if strategy_type is None:
        return None

    underlying = strategy_dict.get("underlying", "")
    expiration_date = strategy_dict.get("expiration_date", "")
    legs = [
        OrderLeg(
            symbol=leg.get("symbol", underlying),
            action=leg.get("action", "Sell to Open"),
            quantity=int(leg.get("quantity", 1)),
            option_type=leg.get("option_type"),
            strike_price=leg.get("strike_price"),
            expiration_date=leg.get("expiration_date", expiration_date),
        )
        for leg in strategy_dict.get("legs", [])
    ]

    return JournalEntry(
        underlying=underlying,
        strategy_type=strategy_type,
        legs=legs,
        entry_price=Decimal(str(credit)),
        rationale=rationale,
    )


@app.command()
def pipeline(
    metrics_file: Path = typer.Option(..., "--metrics", help="JSON from MCP get_market_metrics"),
    portfolio_file: Path = typer.Option(..., "--portfolio", help="JSON from MCP get_positions + get_balances"),
    chains_dir: Path | None = typer.Option(None, "--chains-dir", help="Dir containing {SYMBOL}.json chain files"),
    greeks_dir: Path | None = typer.Option(None, "--greeks-dir", help="Dir containing {SYMBOL}_greeks.json files"),
    strategy: str = typer.Option("iron_condor", "--strategy", help="Strategy type: short_put | vertical_spread | iron_condor | strangle"),
    dte: int = typer.Option(45, "--dte", help="Target days to expiration"),
    put_delta: float = typer.Option(0.30, "--put-delta", help="Short put delta (absolute)"),
    call_delta: float = typer.Option(0.30, "--call-delta", help="Short call delta (absolute)"),
    long_put_delta: float = typer.Option(0.16, "--long-put-delta", help="Long put wing delta"),
    long_call_delta: float = typer.Option(0.16, "--long-call-delta", help="Long call wing delta"),
    iv_min: float = typer.Option(0.30, "--iv-min", help="Min IV rank for screening (0-1)"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max symbols to build strategies for"),
    auto_journal: bool = typer.Option(False, "--auto-journal", help="Log all approved trades to journal"),
    rationale: str = typer.Option("", "--rationale", help="Rationale string stored in journal entries"),
    max_position_pct: float = typer.Option(0.05, "--max-position-pct", help="Max loss as fraction of NLV"),
    max_bp_pct: float = typer.Option(0.50, "--max-bp-pct", help="Max buying power usage fraction"),
    min_dte_risk: int = typer.Option(7, "--min-dte", help="Minimum days to expiration for risk check"),
):
    """Run full pipeline: screen → build → risk-check → (journal). Outputs JSON.

    Chains the four agents programmatically from pre-fetched data files.
    Each symbol in the metrics file is screened, then a strategy is built
    from its chain file (if present), risk-checked against the portfolio,
    and optionally journaled if approved.

    Usage:
        uv run tt-strategy pipeline \\
          --metrics metrics.json --portfolio portfolio.json \\
          --chains-dir /tmp/chains/ --strategy iron_condor --auto-journal
    """
    # --- Validate inputs ---
    if not metrics_file.exists():
        typer.echo(json.dumps({"error": f"Metrics file not found: {metrics_file}"}))
        raise typer.Exit(1)
    if not portfolio_file.exists():
        typer.echo(json.dumps({"error": f"Portfolio file not found: {portfolio_file}"}))
        raise typer.Exit(1)
    if strategy not in _STRATEGIES:
        typer.echo(json.dumps({"error": f"Unknown strategy '{strategy}'. Choose: {_STRATEGIES}"}))
        raise typer.Exit(1)

    # --- Load metrics + screen ---
    try:
        metrics_raw = json.loads(metrics_file.read_text())
    except json.JSONDecodeError as e:
        typer.echo(json.dumps({"error": f"Invalid metrics JSON: {e}"}))
        raise typer.Exit(1)

    metrics_list = parse_market_metrics_response(metrics_raw)
    criteria = ScreenCriteria(iv_rank_min=Decimal(str(iv_min)))
    screened = screen(metrics_list, criteria)[:limit]

    # --- Load portfolio ---
    try:
        positions_raw, balances_raw = _load_portfolio_from_file(portfolio_file)
    except (json.JSONDecodeError, Exception) as e:
        typer.echo(json.dumps({"error": f"Invalid portfolio JSON: {e}"}))
        raise typer.Exit(1)

    portfolio = portfolio_from_positions(positions_raw, balances_raw)
    rules = RiskRules(
        max_position_pct=Decimal(str(max_position_pct)),
        max_bp_usage_pct=Decimal(str(max_bp_pct)),
        min_dte=min_dte_risk,
    )

    # --- Process each screened symbol ---
    results = []
    skipped = []
    rejected = []
    journal = Journal() if auto_journal else None

    for screen_result in screened:
        sym = screen_result.symbol

        # Locate chain file
        chain_file: Path | None = None
        if chains_dir is not None:
            candidate = chains_dir / f"{sym}.json"
            if candidate.exists():
                chain_file = candidate

        if chain_file is None:
            reason = "no chain file" if chains_dir is not None else "no chains-dir provided"
            skipped.append({"symbol": sym, "reason": reason})
            continue

        # Load optional greeks
        greeks_map = {}
        if greeks_dir is not None:
            greeks_candidate = greeks_dir / f"{sym}_greeks.json"
            if greeks_candidate.exists():
                try:
                    greeks_raw = json.loads(greeks_candidate.read_text())
                    greeks_map = parse_greeks_response(greeks_raw)
                except (json.JSONDecodeError, Exception):
                    pass  # greeks are optional; skip silently

        # Parse chain
        try:
            chain_raw = json.loads(chain_file.read_text())
        except json.JSONDecodeError as e:
            skipped.append({"symbol": sym, "reason": f"invalid chain JSON: {e}"})
            continue

        contracts, expiration_date = parse_nested_chain(chain_raw, target_dte=dte, greeks_map=greeks_map)
        if not contracts:
            skipped.append({"symbol": sym, "reason": "no contracts found for target DTE"})
            continue

        # Build strategy
        try:
            if strategy == "short_put":
                strategy_dict = build_short_put(
                    contracts, sym, expiration_date or "",
                    target_delta=Decimal(str(put_delta)),
                )
            elif strategy == "vertical_spread":
                strategy_dict = build_vertical_spread(
                    contracts, sym, expiration_date or "",
                    option_type=OptionType.PUT,
                    direction=Direction.BULLISH,
                    short_delta=Decimal(str(put_delta)),
                    long_delta=Decimal(str(long_put_delta)),
                )
            elif strategy == "iron_condor":
                strategy_dict = build_iron_condor(
                    contracts, sym, expiration_date or "",
                    put_short_delta=Decimal(str(put_delta)),
                    put_long_delta=Decimal(str(long_put_delta)),
                    call_short_delta=Decimal(str(call_delta)),
                    call_long_delta=Decimal(str(long_call_delta)),
                )
            elif strategy == "strangle":
                strategy_dict = build_strangle(
                    contracts, sym, expiration_date or "",
                    put_delta=Decimal(str(put_delta)),
                    call_delta=Decimal(str(call_delta)),
                )
        except ChainBuilderError as e:
            skipped.append({"symbol": sym, "reason": f"build failed: {e}"})
            continue

        # Risk check
        risk_data = strategy_dict.get("risk", {})
        legs_data = strategy_dict.get("legs", [])
        expiration_date_str = strategy_dict.get("expiration_date", "")

        risk_profile = RiskProfile(
            max_profit=Decimal(str(risk_data.get("max_profit", 0))),
            max_loss=Decimal(str(risk_data.get("max_loss", 0))),
            breakevens=[Decimal(str(b)) for b in risk_data.get("breakevens", [])],
        )
        legs = [
            OrderLeg(
                symbol=leg.get("symbol", sym),
                action=leg.get("action", "Sell to Open"),
                quantity=int(leg.get("quantity", 1)),
                option_type=leg.get("option_type"),
                strike_price=leg.get("strike_price"),
                expiration_date=leg.get("expiration_date", expiration_date_str),
            )
            for leg in legs_data
        ]
        risk_result = check_trade(risk_profile, legs, portfolio, rules)

        # Journal if approved and --auto-journal
        journal_id: int | None = None
        if risk_result.approved and auto_journal and journal is not None:
            credit_val = strategy_dict.get("credit") or 0.0
            entry = _journal_from_strategy(strategy_dict, float(credit_val), rationale)
            if entry is not None:
                logged = journal.log_trade(entry)
                journal_id = logged.id

        screen_entry = {
            "score": float(screen_result.score),
            "iv_rank": float(screen_result.metrics.iv_rank),
            "reasons": screen_result.reasons,
        }
        risk_entry = {
            "approved": risk_result.approved,
            "violations": risk_result.violations,
            "warnings": risk_result.warnings,
        }

        record = {
            "symbol": sym,
            "screen": screen_entry,
            "strategy": strategy_dict,
            "risk": risk_entry,
            "journal_id": journal_id,
        }

        if risk_result.approved:
            results.append(record)
        else:
            rejected.append({"symbol": sym, "risk": risk_entry})

    output = {
        "screened": len(screened),
        "built": len(results) + len(rejected),
        "approved": len(results),
        "results": results,
        "skipped": skipped,
        "rejected": rejected,
    }
    typer.echo(json.dumps(output, indent=2))


if __name__ == "__main__":
    app()
