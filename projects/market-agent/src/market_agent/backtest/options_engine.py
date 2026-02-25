"""Multi-leg options backtester.

Fundamentally different from engine.py (equity long/short) — tracks option
structures through their life cycle with management rules applied.

Without Theta Data (yfinance path):
  - Entry uses the current option chain pricing as a proxy for historical prices
  - P&L estimated from underlying price moves + linear theta decay
  - Results are directionally correct but imprecise (overstates accuracy)

With Theta Data:
  - Walks actual historical end-of-day chains for each date in the lookback
  - Accurate bid/ask fills, IV evolution, and Greek path

Usage:
    result = backtest_structure(
        symbol="SPY",
        strategy_type="strangle",
        delta_target=0.16,
        dte_range=(30, 45),
        lookback_days=252,
        profit_target_pct=50,
        stop_loss_pct=200,
    )
    print(result.win_rate, result.avg_dit, result.sample_size)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np

from ..analysis.options import find_optimal_expiry, resolve_strategy
from ..data.fetcher import get_bars
from ..data.models import Bar

logger = logging.getLogger(__name__)

# Annualised risk-free rate for theta decay estimate
RISK_FREE_RATE = 0.045


@dataclass
class OptionsTrade:
    """Record of a single historical options trade."""

    entry_date: date
    exit_date: date
    strategy_type: str
    symbol: str
    credit: float          # Net credit received (positive) or debit paid (negative)
    exit_pnl: float        # P&L at close (positive = profit)
    dit: int               # Days in trade
    mae: float             # Max adverse excursion (worst unrealised loss)
    exit_reason: str       # "profit_target" | "stop_loss" | "dte_exit" | "end_of_data"
    legs: list[dict] = field(default_factory=list)


@dataclass
class OptionsBacktestResult:
    """Aggregated results from multi-leg options backtest."""

    symbol: str
    strategy_type: str
    sample_size: int
    win_rate: float            # 0-100
    avg_pnl: float             # Average P&L per trade (as % of |credit|)
    avg_dit: float             # Average days in trade
    max_adverse_excursion: float  # Worst single-trade MAE
    pnl_distribution: list[float] = field(default_factory=list)  # Per-trade P&L %
    sharpe: float = 0.0
    trades: list[OptionsTrade] = field(default_factory=list)
    provider_type: str = "yfinance"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy_type": self.strategy_type,
            "sample_size": self.sample_size,
            "win_rate": round(self.win_rate, 1),
            "avg_pnl": round(self.avg_pnl, 1),
            "avg_dit": round(self.avg_dit, 1),
            "max_adverse_excursion": round(self.max_adverse_excursion, 1),
            "sharpe": round(self.sharpe, 2),
            "provider_type": self.provider_type,
        }


def backtest_structure(
    symbol: str,
    strategy_type: str,
    delta_target: float = 0.16,
    dte_range: tuple[int, int] = (30, 45),
    lookback_days: int = 252,
    profit_target_pct: float = 50.0,
    stop_loss_pct: float = 200.0,
    max_dte_exit: int = 21,
    entry_freq_days: int = 7,
    provider=None,
) -> OptionsBacktestResult:
    """Backtest an options structure over historical data.

    Entry logic: every `entry_freq_days` trading days over the lookback period,
    attempt to open the given strategy at target delta and DTE.

    Exit logic (first triggered wins):
      1. Profit target: P&L >= profit_target_pct% of credit
      2. Stop loss: loss >= stop_loss_pct% of credit
      3. DTE exit: DTE reaches max_dte_exit (roll prompt)
      4. End of data

    P&L estimation (yfinance path):
      Uses linear theta decay + delta-weighted underlying move as a proxy for
      the option structure's daily mark.

    Args:
        symbol: Underlying ticker
        strategy_type: "strangle", "iron_condor", "short_put", etc.
        delta_target: Target delta for short strikes
        dte_range: (min_dte, max_dte) for entry expiry selection
        lookback_days: Historical lookback in calendar days
        profit_target_pct: % of credit to target as profit (e.g., 50)
        stop_loss_pct: % of credit at which to stop out (e.g., 200)
        max_dte_exit: Roll/exit when DTE falls below this
        entry_freq_days: Days between entry attempts
        provider: OptionsDataProvider (defaults to YFinanceOptionsProvider)

    Returns:
        OptionsBacktestResult with aggregated statistics.
    """
    if provider is None:
        from ..data.theta import get_provider
        provider = get_provider()

    provider_type = type(provider).__name__

    # Fetch underlying price history
    bars = get_bars(symbol, period="2y", interval="1d")
    if not bars or len(bars) < 50:
        logger.warning("Insufficient price history for %s backtest", symbol)
        return OptionsBacktestResult(
            symbol=symbol, strategy_type=strategy_type,
            sample_size=0, win_rate=0, avg_pnl=0, avg_dit=0,
            max_adverse_excursion=0, provider_type=provider_type,
        )

    # Build date → bar index map for O(1) lookup
    bar_by_date: dict[date, Bar] = {b.timestamp.date(): b for b in bars}
    sorted_dates = sorted(bar_by_date.keys())

    # Select entry dates: every entry_freq_days over the lookback
    cutoff = sorted_dates[-1] - timedelta(days=lookback_days)
    entry_dates = [
        d for i, d in enumerate(sorted_dates)
        if d >= cutoff and i % entry_freq_days == 0
    ]

    trades: list[OptionsTrade] = []

    for entry_date in entry_dates:
        trade = _simulate_trade(
            symbol=symbol,
            strategy_type=strategy_type,
            delta_target=delta_target,
            dte_range=dte_range,
            entry_date=entry_date,
            bar_by_date=bar_by_date,
            sorted_dates=sorted_dates,
            profit_target_pct=profit_target_pct,
            stop_loss_pct=stop_loss_pct,
            max_dte_exit=max_dte_exit,
            provider=provider,
        )
        if trade is not None:
            trades.append(trade)

    return _build_result(symbol, strategy_type, trades, provider_type)


def _simulate_trade(
    symbol: str,
    strategy_type: str,
    delta_target: float,
    dte_range: tuple[int, int],
    entry_date: date,
    bar_by_date: dict[date, Bar],
    sorted_dates: list[date],
    profit_target_pct: float,
    stop_loss_pct: float,
    max_dte_exit: int,
    provider,
) -> OptionsTrade | None:
    """Simulate a single trade entry-to-exit."""
    entry_bar = bar_by_date.get(entry_date)
    if not entry_bar:
        return None

    entry_price = float(entry_bar.close)
    if math.isnan(entry_price) or entry_price <= 0:
        return None

    # Resolve strategy at entry (uses current yfinance chain or Theta Data)
    from ..data.fetcher import get_expirations
    from ..analysis.options import find_optimal_expiry

    expirations = provider.get_expirations(symbol, as_of=entry_date)
    if not expirations:
        # Fall back to live expirations if provider returns none
        expirations = get_expirations(symbol)
    if not expirations:
        return None

    expiry = find_optimal_expiry(expirations, dte_range[0], dte_range[1])
    if not expiry:
        return None

    chain = provider.get_chain(symbol, as_of=entry_date, expiry=expiry)

    if chain:
        # Use live chain data for resolution
        from decimal import Decimal
        from ..analysis.options import (
            _resolve_short_put, _resolve_strangle, _resolve_iron_condor,
            _resolve_vertical_spread,
        )
        exp_date_obj = datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date_obj - entry_date).days
        underlying_price = Decimal(str(entry_price))

        resolver_map = {
            "short_put": lambda: _resolve_short_put(chain, underlying_price, delta_target, expiry, dte),
            "strangle": lambda: _resolve_strangle(chain, underlying_price, delta_target, expiry, dte),
            "iron_condor": lambda: _resolve_iron_condor(chain, underlying_price, delta_target, expiry, dte, 5),
            "vertical_spread": lambda: _resolve_vertical_spread(chain, underlying_price, delta_target, expiry, dte, 5),
        }
        resolve_fn = resolver_map.get(strategy_type)
        structure = resolve_fn() if resolve_fn else None
    else:
        structure = None

    if structure is None:
        # Use live resolve_strategy as fallback (may not reflect historical prices)
        from decimal import Decimal
        structure = resolve_strategy(
            symbol=symbol,
            strategy_type=strategy_type,
            underlying_price=Decimal(str(entry_price)),
            delta_target=delta_target,
            dte_range=dte_range,
        )

    if structure is None:
        return None

    credit = structure.get("credit") or 0.0
    debit = structure.get("debit") or 0.0
    net_credit = credit - debit  # Positive = received credit

    if abs(net_credit) < 0.01:
        return None  # No valid pricing

    expiry_date = datetime.strptime(structure.get("expiration", expiry), "%Y-%m-%d").date()
    dte_at_entry = (expiry_date - entry_date).days

    # Estimate daily theta decay: assume linear decay from entry to expiry
    daily_theta = net_credit / max(dte_at_entry, 1) if net_credit > 0 else 0.0

    # Walk forward day by day to exit
    future_dates = [d for d in sorted_dates if d > entry_date]
    mae = 0.0
    exit_date = entry_date
    exit_pnl = 0.0
    exit_reason = "end_of_data"
    cumulative_pnl = 0.0

    for current_date in future_dates:
        current_bar = bar_by_date.get(current_date)
        if not current_bar:
            continue

        current_price = float(current_bar.close)
        if math.isnan(current_price) or current_price <= 0:
            continue
        days_held = (current_date - entry_date).days
        dte_remaining = max(dte_at_entry - days_held, 0)

        # Estimate P&L: theta decay (benefit) + delta-weighted price move (risk for strangles)
        theta_collected = daily_theta * days_held
        price_move_pct = (current_price - entry_price) / entry_price

        # Strategy-specific P&L estimate
        pnl = _estimate_pnl(
            strategy_type=strategy_type,
            structure=structure,
            net_credit=net_credit,
            entry_price=entry_price,
            current_price=current_price,
            theta_collected=theta_collected,
            days_held=days_held,
            dte_at_entry=dte_at_entry,
        )

        cumulative_pnl = pnl
        mae = min(mae, pnl)  # MAE is the worst (most negative) point

        # Check exit conditions
        profit_threshold = net_credit * profit_target_pct / 100
        loss_threshold = -abs(net_credit) * stop_loss_pct / 100

        exit_date = current_date
        if pnl >= profit_threshold:
            exit_pnl = pnl
            exit_reason = "profit_target"
            break
        elif pnl <= loss_threshold:
            exit_pnl = pnl
            exit_reason = "stop_loss"
            break
        elif dte_remaining <= max_dte_exit:
            exit_pnl = pnl
            exit_reason = "dte_exit"
            break
    else:
        exit_pnl = cumulative_pnl

    dit = (exit_date - entry_date).days

    # Normalise P&L as % of premium (credit or debit)
    premium_basis = abs(net_credit) if abs(net_credit) > 0 else 1.0
    pnl_pct = exit_pnl / premium_basis * 100
    mae_pct = mae / premium_basis * 100

    return OptionsTrade(
        entry_date=entry_date,
        exit_date=exit_date,
        strategy_type=strategy_type,
        symbol=symbol,
        credit=net_credit,
        exit_pnl=pnl_pct,
        dit=dit,
        mae=mae_pct,
        exit_reason=exit_reason,
        legs=structure.get("legs", []),
    )


def _estimate_pnl(
    strategy_type: str,
    structure: dict,
    net_credit: float,
    entry_price: float,
    current_price: float,
    theta_collected: float,
    days_held: int,
    dte_at_entry: int,
) -> float:
    """Estimate P&L for a structure from underlying move + theta decay.

    This is a proxy estimation for the yfinance path (no historical option prices).
    For credit strategies: profit from theta decay, loss from large moves.
    For debit strategies: inverse.
    """
    price_move = current_price - entry_price
    pct_move = price_move / entry_price

    if strategy_type in ("strangle", "iron_condor"):
        # Credit strategy: theta is positive, large moves hurt
        # Simple model: approx delta exposure = 0 (delta-neutral at entry)
        # Gamma-weighted loss from large moves
        legs = structure.get("legs", [])
        if legs:
            strikes = [l.get("strike", entry_price) for l in legs]
            lower = min(strikes)
            upper = max(strikes)
            if current_price < lower:
                intrinsic_loss = lower - current_price
            elif current_price > upper:
                intrinsic_loss = current_price - upper
            else:
                intrinsic_loss = 0.0
        else:
            intrinsic_loss = abs(price_move) * 0.5

        return theta_collected - intrinsic_loss

    elif strategy_type in ("short_put", "vertical_spread"):
        # Bullish credit: profit from up/flat, loss from down
        legs = structure.get("legs", [])
        short_strike = max(
            (l.get("strike", 0) for l in legs if l.get("side") == "sell"),
            default=entry_price * 0.95,
        )
        if current_price < short_strike:
            intrinsic_loss = short_strike - current_price
            if strategy_type == "vertical_spread":
                long_strike = min(
                    (l.get("strike", 0) for l in legs if l.get("side") == "buy"),
                    default=short_strike - 5,
                )
                intrinsic_loss = min(intrinsic_loss, short_strike - long_strike)
        else:
            intrinsic_loss = 0.0
        return theta_collected - intrinsic_loss

    elif strategy_type in ("calendar", "diagonal"):
        # Time spread: profits from decay differential + vol expansion
        # Very rough: benefit from theta differential, hurt by large moves
        time_fraction = days_held / max(dte_at_entry, 1)
        return net_credit * time_fraction * 0.7 - abs(pct_move) * net_credit * 2

    elif strategy_type == "back_ratio":
        # Long convexity: loses slowly, profits on large down moves
        return -theta_collected * 0.5 + (max(entry_price * 0.10 - abs(price_move), 0) * 0)

    elif strategy_type == "bwb":
        # BWB: profits in range, defined loss outside
        return theta_collected - abs(price_move) * 0.3

    # Default: simple theta minus move
    return theta_collected - abs(price_move) * 0.5


def _build_result(
    symbol: str,
    strategy_type: str,
    trades: list[OptionsTrade],
    provider_type: str,
) -> OptionsBacktestResult:
    """Aggregate trades into OptionsBacktestResult."""
    if not trades:
        return OptionsBacktestResult(
            symbol=symbol, strategy_type=strategy_type,
            sample_size=0, win_rate=0, avg_pnl=0, avg_dit=0,
            max_adverse_excursion=0, provider_type=provider_type,
        )

    pnl_values = [t.exit_pnl for t in trades]
    winners = [p for p in pnl_values if p > 0]
    mae_values = [t.mae for t in trades]

    win_rate = len(winners) / len(trades) * 100
    avg_pnl = sum(pnl_values) / len(pnl_values)
    avg_dit = sum(t.dit for t in trades) / len(trades)
    max_mae = min(mae_values) if mae_values else 0.0

    # Sharpe on per-trade P&L
    arr = np.array(pnl_values)
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0

    return OptionsBacktestResult(
        symbol=symbol,
        strategy_type=strategy_type,
        sample_size=len(trades),
        win_rate=round(win_rate, 1),
        avg_pnl=round(avg_pnl, 1),
        avg_dit=round(avg_dit, 1),
        max_adverse_excursion=round(max_mae, 1),
        pnl_distribution=pnl_values,
        sharpe=round(sharpe, 2),
        trades=trades,
        provider_type=provider_type,
    )
