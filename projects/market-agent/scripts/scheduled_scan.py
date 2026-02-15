#!/usr/bin/env python3
"""Scheduled market scan — runs pipeline, diffs with previous, generates report.

Usage:
    uv run python scripts/scheduled_scan.py              # run scan + report
    uv run python scripts/scheduled_scan.py --install     # install launchd job
    uv run python scripts/scheduled_scan.py --uninstall   # remove launchd job
"""

import html
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console

from market_agent import validate_symbol
from market_agent.analysis.charts import chart_technical
from market_agent.analysis.screener import (
    HIGH_IV_NAMES,
    SP500_TOP,
    filter_correlated,
    screen_momentum,
    screen_volatility,
)
from market_agent.data.config import load_config
from market_agent.data.fetcher import get_bars
from market_agent.signals.generator import signal_from_momentum, signal_from_volatility
from market_agent.signals.recommender import (
    Recommendation,
    recommend_from_momentum,
    recommend_from_signal,
    recommend_from_volatility,
)

console = Console()

DATA_DIR = Path.home() / ".market-agent"
LAST_SCAN_PATH = DATA_DIR / "last_scan.json"
REPORTS_DIR = DATA_DIR / "reports"
PLIST_NAME = "com.market-agent.daily-scan"
PLIST_SRC = Path(__file__).parent.parent / "launchd" / f"{PLIST_NAME}.plist"
PLIST_DST = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_NAME}.plist"


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", name)


def _load_previous() -> dict[str, dict]:
    """Load previous scan results."""
    if not LAST_SCAN_PATH.exists():
        return {}
    try:
        data = json.loads(LAST_SCAN_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _save_current(recs: list[Recommendation]):
    """Save current scan results for next diff."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    for rec in recs:
        data[rec.symbol] = {
            "action": rec.action,
            "direction": rec.direction,
            "confidence": rec.confidence,
            "strategy": rec.strategy_name,
            "timestamp": datetime.now().isoformat(),
        }
    LAST_SCAN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _find_new(current: list[Recommendation], previous: dict[str, dict]) -> list[Recommendation]:
    """Find new or changed recommendations."""
    new = []
    for rec in current:
        prev = previous.get(rec.symbol)
        if prev is None:
            new.append(rec)
        elif prev.get("action") != rec.action or prev.get("direction") != rec.direction:
            new.append(rec)
    return new


def _generate_report(recs: list[Recommendation], new_recs: list[Recommendation]) -> str:
    """Generate scan report markdown."""
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# Scheduled Scan Report")
    lines.append(f"")
    lines.append(f"Generated: {now}")
    lines.append(f"Total recommendations: {len(recs)}")
    lines.append(f"New/changed signals: {len(new_recs)}")
    lines.append("")

    if new_recs:
        lines.append("## New Signals")
        lines.append("")
        lines.append("| Symbol | Action | Direction | Confidence | Strategy |")
        lines.append("|--------|--------|-----------|------------|----------|")
        for rec in new_recs:
            lines.append(
                f"| {rec.symbol} | {rec.action} | {rec.direction} | "
                f"{rec.confidence:.0%} | {rec.strategy_name} |"
            )
        lines.append("")

    lines.append("## All Recommendations")
    lines.append("")
    lines.append("| Symbol | Action | Direction | Confidence | Strategy | Options |")
    lines.append("|--------|--------|-----------|------------|----------|---------|")
    for rec in sorted(recs, key=lambda r: r.confidence, reverse=True):
        opts = rec.options_strategy.strategy_type if rec.options_strategy else "-"
        lines.append(
            f"| {rec.symbol} | {rec.action} | {rec.direction} | "
            f"{rec.confidence:.0%} | {rec.strategy_name} | {opts} |"
        )
    lines.append("")
    return "\n".join(lines)


def run_scan():
    """Execute scheduled scan workflow."""
    config = load_config()
    console.print(f"[bold]Scheduled scan starting at {datetime.now().strftime('%H:%M')}[/]")

    # Determine symbols
    if config.scan.symbols:
        momentum_symbols = config.scan.symbols
        vol_symbols = config.scan.symbols
    else:
        momentum_symbols = SP500_TOP
        vol_symbols = HIGH_IV_NAMES

    all_recs: list[Recommendation] = []

    # Run configured strategies
    strategies = config.scan.strategies

    if "momentum" in strategies or "all" in strategies:
        console.print("  [dim]Running momentum scan...[/]")
        results = screen_momentum(momentum_symbols)
        results = filter_correlated(results)
        for r in results[:8]:
            bars = get_bars(r.symbol, period="6mo")
            sig = signal_from_momentum(r, bars)
            if sig and sig.strength >= config.scan.min_confidence:
                all_recs.append(recommend_from_momentum(r, sig))

    if "volatility" in strategies or "all" in strategies:
        console.print("  [dim]Running volatility scan...[/]")
        results = screen_volatility(vol_symbols)
        results = filter_correlated(results)
        for r in results[:8]:
            sig = signal_from_volatility(r)
            if sig and sig.strength >= config.scan.min_confidence:
                all_recs.append(recommend_from_volatility(r, sig))

    # Load previous and find changes
    previous = _load_previous()
    new_recs = _find_new(all_recs, previous)

    # Save current
    _save_current(all_recs)

    # Generate charts for top picks
    chart_paths = []
    for rec in sorted(all_recs, key=lambda r: r.confidence, reverse=True)[:3]:
        bars = get_bars(rec.symbol, period="6mo")
        if bars and len(bars) >= 20:
            path = chart_technical(bars, rec.symbol)
            if path:
                chart_paths.append(path)

    # Generate and save report
    report_md = _generate_report(all_recs, new_recs)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_name = f"scan_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    report_path = REPORTS_DIR / report_name
    report_path.write_text(report_md, encoding="utf-8")

    # Print summary
    console.print(f"\n[bold green]Scan complete[/]")
    console.print(f"  Recommendations: {len(all_recs)}")
    console.print(f"  New/changed: {len(new_recs)}")
    console.print(f"  Report: {report_path}")
    if chart_paths:
        console.print(f"  Charts: {len(chart_paths)} generated")

    for rec in new_recs:
        console.print(f"  [yellow]NEW:[/] {rec.symbol} — {rec.action} ({rec.confidence:.0%})")


def install_launchd():
    """Install launchd job for daily scanning."""
    if not PLIST_SRC.exists():
        console.print(f"[red]Plist template not found: {PLIST_SRC}[/]")
        sys.exit(1)

    # Read and customize template
    uv_path = shutil.which("uv")
    if not uv_path:
        console.print("[red]uv not found in PATH[/]")
        sys.exit(1)

    project_path = Path(__file__).parent.parent.resolve()
    log_path = DATA_DIR / "logs"
    log_path.mkdir(parents=True, exist_ok=True)

    # Validate paths exist
    if not project_path.exists():
        console.print(f"[red]Project path not found: {project_path}[/]")
        sys.exit(1)

    template = PLIST_SRC.read_text(encoding="utf-8")
    # Escape values for XML safety before inserting into plist
    plist = template.replace("{{UV_PATH}}", html.escape(uv_path))
    plist = plist.replace("{{PROJECT_PATH}}", html.escape(str(project_path)))
    plist = plist.replace("{{LOG_PATH}}", html.escape(str(log_path)))

    PLIST_DST.parent.mkdir(parents=True, exist_ok=True)
    PLIST_DST.write_text(plist, encoding="utf-8")

    subprocess.run(["launchctl", "load", str(PLIST_DST)], check=True)
    console.print(f"[green]Installed: {PLIST_DST}[/]")
    console.print(f"[dim]Schedule: weekdays 8:30 AM[/]")


def uninstall_launchd():
    """Remove launchd job."""
    if PLIST_DST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_DST)], check=False)
        PLIST_DST.unlink()
        console.print(f"[green]Removed: {PLIST_DST}[/]")
    else:
        console.print("[dim]No launchd job found[/]")


if __name__ == "__main__":
    if "--install" in sys.argv:
        install_launchd()
    elif "--uninstall" in sys.argv:
        uninstall_launchd()
    elif "--help" in sys.argv:
        console.print(__doc__)
    else:
        run_scan()
