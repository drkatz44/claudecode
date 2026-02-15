"""Chart generation — technical, equity curve, and options chain visualizations.

Uses matplotlib with Agg backend (headless-safe, no X11 required).
Charts saved as PNG to ~/.market-agent/charts/.
"""

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from ..analysis.technical import bars_to_df, sma, bollinger_bands
from ..data.models import Bar, OptionQuote

CHART_DIR = Path.home() / ".market-agent" / "charts"


def _safe_name(name: str) -> str:
    """Sanitize string for use in filenames."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "", name)


def _ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def chart_technical(
    bars: list[Bar],
    symbol: str,
    signals: Optional[list[dict]] = None,
    save_path: Optional[Path] = None,
) -> Optional[Path]:
    """Generate a technical analysis chart with price + volume.

    Args:
        bars: OHLCV bars
        symbol: Ticker symbol (used in title and filename)
        signals: Optional list of signal dicts with keys:
            - timestamp: datetime
            - direction: "long" or "short"
        save_path: Override save location (default: CHART_DIR)

    Returns:
        Path to saved PNG, or None if insufficient data.
    """
    if len(bars) < 20:
        return None

    safe_sym = _safe_name(symbol)
    df = bars_to_df(bars)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    dates = df.index

    # Indicators
    sma_20 = sma(bars, 20)
    sma_50 = sma(bars, 50) if len(bars) >= 50 else None
    bb = bollinger_bands(bars, period=20)

    fig, (ax_price, ax_vol) = plt.subplots(
        2, 1, figsize=(14, 8), height_ratios=[3, 1],
        sharex=True, gridspec_kw={"hspace": 0.05},
    )

    # Price panel
    ax_price.plot(dates, close, color="#2196F3", linewidth=1.5, label="Close")
    ax_price.plot(dates, sma_20.values, color="#FF9800", linewidth=1, alpha=0.8, label="SMA-20")
    if sma_50 is not None:
        ax_price.plot(dates, sma_50.values, color="#9C27B0", linewidth=1, alpha=0.8, label="SMA-50")

    # Bollinger Bands shading
    ax_price.fill_between(
        dates, bb["upper"].astype(float).values, bb["lower"].astype(float).values,
        alpha=0.1, color="#2196F3", label="BB(20,2)",
    )

    # Signal markers
    if signals:
        for sig in signals:
            ts = sig.get("timestamp")
            direction = sig.get("direction", "")
            if ts is None:
                continue
            # Find closest bar
            idx = df.index.searchsorted(ts)
            if idx >= len(df):
                idx = len(df) - 1
            price_at = close.iloc[idx]
            if direction == "long":
                ax_price.annotate(
                    "\u25b2", (dates[idx], price_at),
                    fontsize=14, color="green", ha="center", va="bottom",
                )
            elif direction == "short":
                ax_price.annotate(
                    "\u25bc", (dates[idx], price_at),
                    fontsize=14, color="red", ha="center", va="top",
                )

    date_range = f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}"
    ax_price.set_title(f"{symbol} — {date_range}", fontsize=14, fontweight="bold")
    ax_price.legend(loc="upper left", fontsize=9)
    ax_price.grid(True, alpha=0.3)
    ax_price.set_ylabel("Price ($)")

    # Volume panel
    colors = ["#4CAF50" if close.iloc[i] >= close.iloc[max(0, i - 1)] else "#F44336"
              for i in range(len(close))]
    ax_vol.bar(dates, volume, color=colors, alpha=0.6, width=0.8)
    ax_vol.set_ylabel("Volume")
    ax_vol.grid(True, alpha=0.3)
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax_vol.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    fig.autofmt_xdate(rotation=30)

    # Save
    if save_path is None:
        _ensure_dir(CHART_DIR)
        save_path = CHART_DIR / f"{safe_sym}_technical_{datetime.now().strftime('%Y%m%d')}.png"

    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return save_path


def chart_equity_curve(
    equity_curve: list[tuple[datetime, float]],
    symbol: str,
    strategy_name: str = "",
    initial_capital: float = 10000.0,
    benchmark_return_pct: Optional[float] = None,
    save_path: Optional[Path] = None,
) -> Optional[Path]:
    """Generate equity curve + drawdown chart from backtest results.

    Args:
        equity_curve: List of (datetime, equity_value) tuples
        symbol: Ticker symbol
        strategy_name: Strategy name for title
        initial_capital: Starting capital
        benchmark_return_pct: Optional benchmark return % for comparison line
        save_path: Override save location

    Returns:
        Path to saved PNG, or None if insufficient data.
    """
    if len(equity_curve) < 2:
        return None

    safe_sym = _safe_name(symbol)
    safe_strat = _safe_name(strategy_name)

    dates = [e[0] for e in equity_curve]
    equity = np.array([e[1] for e in equity_curve])

    # Drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak * 100

    total_return = (equity[-1] - initial_capital) / initial_capital * 100
    max_dd = drawdown.max()

    fig, (ax_eq, ax_dd) = plt.subplots(
        2, 1, figsize=(14, 8), height_ratios=[3, 1],
        sharex=True, gridspec_kw={"hspace": 0.05},
    )

    # Equity curve
    ax_eq.plot(dates, equity, color="#2196F3", linewidth=1.5, label=f"{strategy_name or 'Strategy'}")
    ax_eq.axhline(y=initial_capital, color="gray", linestyle="--", alpha=0.5, label="Initial Capital")

    # Benchmark line
    if benchmark_return_pct is not None:
        bench_vals = np.linspace(initial_capital, initial_capital * (1 + benchmark_return_pct / 100), len(dates))
        ax_eq.plot(dates, bench_vals, color="#FF9800", linewidth=1, linestyle="--",
                   alpha=0.7, label=f"Benchmark ({benchmark_return_pct:+.1f}%)")

    ax_eq.annotate(
        f"Return: {total_return:+.1f}%\nMax DD: {max_dd:.1f}%",
        xy=(0.02, 0.95), xycoords="axes fraction",
        fontsize=10, va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
    )

    title = f"{symbol} — Equity Curve"
    if strategy_name:
        title += f" ({strategy_name})"
    ax_eq.set_title(title, fontsize=14, fontweight="bold")
    ax_eq.legend(loc="upper left", fontsize=9)
    ax_eq.grid(True, alpha=0.3)
    ax_eq.set_ylabel("Equity ($)")

    # Drawdown panel
    ax_dd.fill_between(dates, 0, -drawdown, color="#F44336", alpha=0.4)
    ax_dd.plot(dates, -drawdown, color="#F44336", linewidth=0.8)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.grid(True, alpha=0.3)
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax_dd.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    fig.autofmt_xdate(rotation=30)

    # Save
    if save_path is None:
        _ensure_dir(CHART_DIR)
        save_path = CHART_DIR / f"{safe_sym}_{safe_strat}_equity_{datetime.now().strftime('%Y%m%d')}.png"

    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return save_path


def chart_options_chain(
    chain: list[OptionQuote],
    underlying_price: float,
    symbol: str,
    save_path: Optional[Path] = None,
) -> Optional[Path]:
    """Generate options chain visualization — IV smile + OI distribution.

    Args:
        chain: List of OptionQuote objects
        underlying_price: Current underlying price
        symbol: Ticker symbol
        save_path: Override save location

    Returns:
        Path to saved PNG, or None if insufficient data.
    """
    if len(chain) < 4:
        return None

    safe_sym = _safe_name(symbol)

    calls = [q for q in chain if q.option_type == "call"]
    puts = [q for q in chain if q.option_type == "put"]

    fig, (ax_iv, ax_oi) = plt.subplots(
        2, 1, figsize=(14, 8), height_ratios=[1, 1],
        gridspec_kw={"hspace": 0.3},
    )

    # IV Smile panel
    if calls:
        call_strikes = [float(q.strike) for q in calls if q.iv]
        call_ivs = [float(q.iv) * 100 for q in calls if q.iv]
        if call_strikes:
            ax_iv.plot(call_strikes, call_ivs, "o-", color="#4CAF50", markersize=4,
                       linewidth=1, label="Calls IV", alpha=0.8)

    if puts:
        put_strikes = [float(q.strike) for q in puts if q.iv]
        put_ivs = [float(q.iv) * 100 for q in puts if q.iv]
        if put_strikes:
            ax_iv.plot(put_strikes, put_ivs, "o-", color="#F44336", markersize=4,
                       linewidth=1, label="Puts IV", alpha=0.8)

    ax_iv.axvline(x=underlying_price, color="gray", linestyle="--", alpha=0.7, label=f"Spot ${underlying_price:.2f}")
    ax_iv.set_title(f"{symbol} — IV Smile", fontsize=14, fontweight="bold")
    ax_iv.set_ylabel("Implied Volatility (%)")
    ax_iv.set_xlabel("Strike")
    ax_iv.legend(loc="upper right", fontsize=9)
    ax_iv.grid(True, alpha=0.3)

    # OI Distribution panel
    call_oi_strikes = [float(q.strike) for q in calls if q.open_interest > 0]
    call_oi_vals = [q.open_interest for q in calls if q.open_interest > 0]
    put_oi_strikes = [float(q.strike) for q in puts if q.open_interest > 0]
    put_oi_vals = [q.open_interest for q in puts if q.open_interest > 0]

    bar_width = 0.4
    if call_oi_strikes:
        # Offset for side-by-side bars
        call_pos = [s - bar_width / 2 for s in call_oi_strikes]
        ax_oi.bar(call_pos, call_oi_vals, width=bar_width, color="#4CAF50",
                  alpha=0.7, label="Call OI")
    if put_oi_strikes:
        put_pos = [s + bar_width / 2 for s in put_oi_strikes]
        ax_oi.bar(put_pos, put_oi_vals, width=bar_width, color="#F44336",
                  alpha=0.7, label="Put OI")

    ax_oi.axvline(x=underlying_price, color="gray", linestyle="--", alpha=0.7)
    ax_oi.set_title("Open Interest Distribution", fontsize=12)
    ax_oi.set_ylabel("Open Interest")
    ax_oi.set_xlabel("Strike")
    ax_oi.legend(loc="upper right", fontsize=9)
    ax_oi.grid(True, alpha=0.3)

    # Save
    if save_path is None:
        _ensure_dir(CHART_DIR)
        save_path = CHART_DIR / f"{safe_sym}_options_{datetime.now().strftime('%Y%m%d')}.png"

    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return save_path
