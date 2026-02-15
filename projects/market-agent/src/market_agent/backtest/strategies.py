"""Pre-built signal functions for backtesting.

Each function takes bars[:i] and returns an Optional[Signal],
following the no-look-ahead convention.
"""

from decimal import Decimal
from typing import Optional

from ..analysis.technical import atr, bollinger_bands, ema, macd, rsi, sma, volume_sma_ratio
from ..data.models import Bar, Signal, SignalDirection, TimeFrame


def momentum_crossover(bars: list[Bar]) -> Optional[Signal]:
    """EMA 12/26 crossover with RSI confirmation.

    Long when EMA-12 crosses above EMA-26 AND RSI > 50.
    Exit via stop/target.
    """
    if len(bars) < 30:
        return None

    ema_12 = ema(bars, 12)
    ema_26 = ema(bars, 26)
    rsi_val = rsi(bars, 14)
    atr_val = atr(bars, 14)

    curr_12 = ema_12.iloc[-1]
    prev_12 = ema_12.iloc[-2]
    curr_26 = ema_26.iloc[-1]
    prev_26 = ema_26.iloc[-2]
    curr_rsi = rsi_val.iloc[-1]
    curr_atr = atr_val.iloc[-1]

    close = Decimal(str(round(float(bars[-1].close), 4)))
    atr_d = Decimal(str(round(curr_atr, 4)))

    # Bullish crossover: was below, now above
    if prev_12 <= prev_26 and curr_12 > curr_26 and curr_rsi > 50:
        stop = close - atr_d * 2
        target = close + atr_d * 3

        return Signal(
            symbol=bars[-1].timestamp.strftime("%Y%m%d"),  # placeholder
            asset_class="equity",
            direction=SignalDirection.LONG,
            strength=min(curr_rsi / 100, 1.0),
            strategy="momentum_crossover",
            entry_price=close,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={"rsi": round(curr_rsi, 1), "atr": round(curr_atr, 4)},
        )

    # Bearish crossover: was above, now below
    if prev_12 >= prev_26 and curr_12 < curr_26 and curr_rsi < 50:
        stop = close + atr_d * 2
        target = close - atr_d * 3

        return Signal(
            symbol=bars[-1].timestamp.strftime("%Y%m%d"),
            asset_class="equity",
            direction=SignalDirection.SHORT,
            strength=max(1.0 - curr_rsi / 100, 0.3),
            strategy="momentum_crossover",
            entry_price=close,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={"rsi": round(curr_rsi, 1), "atr": round(curr_atr, 4)},
        )
    return None


def mean_reversion_bb(bars: list[Bar]) -> Optional[Signal]:
    """Bollinger Band mean reversion.

    Long when price closes below lower band AND RSI < 30.
    Target: middle band (SMA-20). Stop: 1.5x ATR below entry.
    """
    if len(bars) < 25:
        return None

    bb = bollinger_bands(bars)
    rsi_val = rsi(bars, 14)
    atr_val = atr(bars, 14)

    close = float(bars[-1].close)
    lower = bb["lower"].iloc[-1]
    middle = bb["middle"].iloc[-1]
    curr_rsi = rsi_val.iloc[-1]
    curr_atr = atr_val.iloc[-1]

    upper = bb["upper"].iloc[-1]
    close_d = Decimal(str(round(close, 4)))
    atr_d = Decimal(str(round(curr_atr, 4)))

    # Long: below lower band + oversold
    if close < lower and curr_rsi < 30:
        stop = close_d - atr_d * Decimal("1.5")
        target = Decimal(str(round(middle, 4)))

        return Signal(
            symbol="",
            asset_class="equity",
            direction=SignalDirection.LONG,
            strength=max(0.3, 1.0 - curr_rsi / 100),
            strategy="mean_reversion_bb",
            entry_price=close_d,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={"rsi": round(curr_rsi, 1), "bb_lower": round(lower, 2)},
        )

    # Short: above upper band + overbought
    if close > upper and curr_rsi > 70:
        stop = close_d + atr_d * Decimal("1.5")
        target = Decimal(str(round(middle, 4)))

        return Signal(
            symbol="",
            asset_class="equity",
            direction=SignalDirection.SHORT,
            strength=max(0.3, curr_rsi / 100),
            strategy="mean_reversion_bb",
            entry_price=close_d,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={"rsi": round(curr_rsi, 1), "bb_upper": round(upper, 2)},
        )
    return None


def macd_momentum(bars: list[Bar]) -> Optional[Signal]:
    """MACD histogram momentum.

    Long when MACD histogram turns positive (crosses zero) AND
    MACD line is above signal line AND price is above SMA-50.
    """
    if len(bars) < 55:
        return None

    macd_data = macd(bars)
    sma_50 = sma(bars, 50)
    atr_val = atr(bars, 14)

    hist_curr = macd_data["histogram"].iloc[-1]
    hist_prev = macd_data["histogram"].iloc[-2]
    macd_line = macd_data["macd"].iloc[-1]
    signal_line = macd_data["signal"].iloc[-1]
    curr_sma50 = sma_50.iloc[-1]
    close = float(bars[-1].close)
    curr_atr = atr_val.iloc[-1]

    close_d = Decimal(str(round(close, 4)))
    atr_d = Decimal(str(round(curr_atr, 4)))

    # Long: histogram crosses zero from below + above SMA-50
    if hist_prev <= 0 and hist_curr > 0 and macd_line > signal_line and close > curr_sma50:
        stop = close_d - atr_d * Decimal("2.5")
        target = close_d + atr_d * Decimal("4")

        return Signal(
            symbol="",
            asset_class="equity",
            direction=SignalDirection.LONG,
            strength=0.7,
            strategy="macd_momentum",
            entry_price=close_d,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={
                "macd": round(macd_line, 4),
                "signal": round(signal_line, 4),
                "histogram": round(hist_curr, 4),
            },
        )

    # Short: histogram crosses zero from above + below SMA-50
    if hist_prev >= 0 and hist_curr < 0 and macd_line < signal_line and close < curr_sma50:
        stop = close_d + atr_d * Decimal("2.5")
        target = close_d - atr_d * Decimal("4")

        return Signal(
            symbol="",
            asset_class="equity",
            direction=SignalDirection.SHORT,
            strength=0.7,
            strategy="macd_momentum",
            entry_price=close_d,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={
                "macd": round(macd_line, 4),
                "signal": round(signal_line, 4),
                "histogram": round(hist_curr, 4),
            },
        )
    return None


def breakout_volume(bars: list[Bar], lookback: int = 20, volume_mult: float = 1.5) -> Optional[Signal]:
    """Breakout strategy with volume confirmation.

    Long when price makes new high over lookback period + above-average volume.
    Short when price makes new low over lookback period + above-average volume.
    Stop: 1 ATR beyond breakout level. Target: 2x ATR.
    """
    if len(bars) < max(lookback + 5, 30):
        return None

    atr_val = atr(bars, 14)
    vol_ratio = volume_sma_ratio(bars, lookback)

    curr_atr = atr_val.iloc[-1]
    curr_vol_ratio = vol_ratio.iloc[-1]
    close = float(bars[-1].close)
    high = float(bars[-1].high)
    low = float(bars[-1].low)

    if curr_vol_ratio < volume_mult:
        return None

    # Lookback highs/lows (excluding current bar)
    lookback_highs = [float(b.high) for b in bars[-(lookback + 1):-1]]
    lookback_lows = [float(b.low) for b in bars[-(lookback + 1):-1]]
    prev_high = max(lookback_highs)
    prev_low = min(lookback_lows)

    close_d = Decimal(str(round(close, 4)))
    atr_d = Decimal(str(round(curr_atr, 4)))

    # Breakout long: new high
    if high > prev_high:
        stop = close_d - atr_d
        target = close_d + atr_d * 2

        return Signal(
            symbol="",
            asset_class="equity",
            direction=SignalDirection.LONG,
            strength=min(curr_vol_ratio / 3, 1.0),
            strategy="breakout_volume",
            entry_price=close_d,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={
                "vol_ratio": round(curr_vol_ratio, 2),
                "prev_high": round(prev_high, 2),
                "atr": round(curr_atr, 4),
            },
        )

    # Breakdown short: new low
    if low < prev_low:
        stop = close_d + atr_d
        target = close_d - atr_d * 2

        return Signal(
            symbol="",
            asset_class="equity",
            direction=SignalDirection.SHORT,
            strength=min(curr_vol_ratio / 3, 1.0),
            strategy="breakout_volume",
            entry_price=close_d,
            stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            timeframe=TimeFrame.D1,
            metadata={
                "vol_ratio": round(curr_vol_ratio, 2),
                "prev_low": round(prev_low, 2),
                "atr": round(curr_atr, 4),
            },
        )
    return None
