"""Simple backtesting engine for signal strategies.

Walks through historical bars, applies signals at each bar, tracks P&L.
No look-ahead bias: signals are generated from data up to (not including)
the current bar, and fills happen at the next bar's open.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional

import pandas as pd

from ..analysis.technical import bars_to_df
from ..data.models import Bar, Signal, SignalDirection


@dataclass
class Trade:
    """Completed trade record."""
    symbol: str
    direction: SignalDirection
    strategy: str
    entry_time: datetime
    entry_price: Decimal
    exit_time: datetime
    exit_price: Decimal
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    pnl: Decimal
    pnl_pct: float
    bars_held: int
    exit_reason: str  # "stop_loss", "take_profit", "signal_exit", "end_of_data"


@dataclass
class Position:
    """Open position being tracked."""
    symbol: str
    direction: SignalDirection
    strategy: str
    entry_time: datetime
    entry_price: Decimal
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    entry_bar_idx: int


@dataclass
class BacktestResult:
    """Backtest output summary."""
    trades: list[Trade]
    initial_capital: Decimal
    final_capital: Decimal
    total_return_pct: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    avg_bars_held: float
    equity_curve: list[tuple[datetime, float]]

    def summary(self) -> dict:
        return {
            "total_return": f"{self.total_return_pct:.1f}%",
            "win_rate": f"{self.win_rate:.1f}%",
            "total_trades": self.total_trades,
            "avg_win": f"{self.avg_win:.2f}%",
            "avg_loss": f"{self.avg_loss:.2f}%",
            "profit_factor": f"{self.profit_factor:.2f}",
            "max_drawdown": f"{self.max_drawdown_pct:.1f}%",
            "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
            "avg_bars_held": f"{self.avg_bars_held:.1f}",
        }


# Type for signal generator function: takes bars up to current point, returns Optional[Signal]
SignalFunc = Callable[[list[Bar]], Optional[Signal]]


def backtest(
    bars: list[Bar],
    signal_func: SignalFunc,
    initial_capital: float = 10000.0,
    position_size_pct: float = 10.0,
    max_positions: int = 1,
    commission_pct: float = 0.0,
) -> BacktestResult:
    """Run a backtest on historical bars.

    Args:
        bars: Historical OHLCV bars
        signal_func: Function that takes bars[:i] and returns an optional Signal
        initial_capital: Starting capital
        position_size_pct: % of capital per position
        max_positions: Max concurrent positions
        commission_pct: Round-trip commission as % of trade value
    """
    if len(bars) < 50:
        raise ValueError("Need at least 50 bars for backtesting")

    capital = Decimal(str(initial_capital))
    positions: list[Position] = []
    trades: list[Trade] = []
    equity_curve = []
    peak_equity = capital

    for i in range(50, len(bars)):
        current_bar = bars[i]
        prev_bars = bars[:i]

        # Track equity
        unrealized = Decimal(0)
        for pos in positions:
            if pos.direction == SignalDirection.LONG:
                unrealized += current_bar.close - pos.entry_price
            elif pos.direction == SignalDirection.SHORT:
                unrealized += pos.entry_price - current_bar.close

        current_equity = capital + unrealized
        equity_curve.append((current_bar.timestamp, float(current_equity)))
        peak_equity = max(peak_equity, current_equity)

        # Check stops and targets on open positions
        closed = []
        for j, pos in enumerate(positions):
            exit_price = None
            exit_reason = None

            if pos.direction == SignalDirection.LONG:
                if pos.stop_loss and current_bar.low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "stop_loss"
                elif pos.take_profit and current_bar.high >= pos.take_profit:
                    exit_price = pos.take_profit
                    exit_reason = "take_profit"
            elif pos.direction == SignalDirection.SHORT:
                if pos.stop_loss and current_bar.high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "stop_loss"
                elif pos.take_profit and current_bar.low <= pos.take_profit:
                    exit_price = pos.take_profit
                    exit_reason = "take_profit"

            if exit_price:
                pnl = _calc_pnl(pos, exit_price, commission_pct)
                capital += pnl
                trades.append(Trade(
                    symbol=pos.symbol,
                    direction=pos.direction,
                    strategy=pos.strategy,
                    entry_time=pos.entry_time,
                    entry_price=pos.entry_price,
                    exit_time=current_bar.timestamp,
                    exit_price=exit_price,
                    stop_loss=pos.stop_loss,
                    take_profit=pos.take_profit,
                    pnl=pnl,
                    pnl_pct=float(pnl / pos.entry_price * 100),
                    bars_held=i - pos.entry_bar_idx,
                    exit_reason=exit_reason,
                ))
                closed.append(j)

        for j in sorted(closed, reverse=True):
            positions.pop(j)

        # Generate new signal
        if len(positions) < max_positions:
            signal = signal_func(prev_bars)
            if signal and signal.direction != SignalDirection.NEUTRAL:
                pos_size = capital * Decimal(str(position_size_pct / 100))
                # Enter at next bar open (current bar, since signal from prev_bars)
                entry_price = current_bar.open

                positions.append(Position(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    strategy=signal.strategy,
                    entry_time=current_bar.timestamp,
                    entry_price=entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    entry_bar_idx=i,
                ))

    # Close remaining positions at last bar
    for pos in positions:
        last_bar = bars[-1]
        pnl = _calc_pnl(pos, last_bar.close, commission_pct)
        capital += pnl
        trades.append(Trade(
            symbol=pos.symbol,
            direction=pos.direction,
            strategy=pos.strategy,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=last_bar.timestamp,
            exit_price=last_bar.close,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            pnl=pnl,
            pnl_pct=float(pnl / pos.entry_price * 100),
            bars_held=len(bars) - 1 - pos.entry_bar_idx,
            exit_reason="end_of_data",
        ))

    return _build_result(trades, Decimal(str(initial_capital)), capital, equity_curve)


def _calc_pnl(pos: Position, exit_price: Decimal, commission_pct: float) -> Decimal:
    if pos.direction == SignalDirection.LONG:
        gross = exit_price - pos.entry_price
    else:
        gross = pos.entry_price - exit_price
    commission = pos.entry_price * Decimal(str(commission_pct / 100))
    return gross - commission


def _build_result(
    trades: list[Trade],
    initial_capital: Decimal,
    final_capital: Decimal,
    equity_curve: list[tuple[datetime, float]],
) -> BacktestResult:
    total_return = float((final_capital - initial_capital) / initial_capital * 100)

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]

    win_rate = len(winners) / len(trades) * 100 if trades else 0
    avg_win = sum(t.pnl_pct for t in winners) / len(winners) if winners else 0
    avg_loss = sum(t.pnl_pct for t in losers) / len(losers) if losers else 0

    gross_wins = sum(float(t.pnl) for t in winners)
    gross_losses = abs(sum(float(t.pnl) for t in losers))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    # Max drawdown
    peak = 0.0
    max_dd = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Sharpe (daily returns)
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1][1]
            curr = equity_curve[i][1]
            if prev > 0:
                returns.append((curr - prev) / prev)
        if returns:
            import numpy as np
            arr = np.array(returns)
            sharpe = (arr.mean() / arr.std() * (252 ** 0.5)) if arr.std() > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    avg_held = sum(t.bars_held for t in trades) / len(trades) if trades else 0

    return BacktestResult(
        trades=trades,
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_return_pct=total_return,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        sharpe_ratio=float(sharpe),
        total_trades=len(trades),
        avg_bars_held=avg_held,
        equity_curve=equity_curve,
    )
