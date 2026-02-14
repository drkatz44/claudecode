"""Signal generation — converts analysis into actionable trading signals."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..analysis.screener import ScreenResult
from ..analysis.technical import atr, bars_to_df, bollinger_bands, pivot_points
from ..data.fetcher import get_bars
from ..data.models import AssetClass, Bar, Signal, SignalDirection, TimeFrame


def _classify_asset(symbol: str) -> AssetClass:
    if symbol.endswith("-USD"):
        return AssetClass.CRYPTO
    if symbol.startswith("XL") or symbol in ("SPY", "QQQ", "IWM", "DIA", "GLD", "TLT"):
        return AssetClass.ETF
    return AssetClass.EQUITY


def signal_from_momentum(result: ScreenResult, bars: list[Bar]) -> Optional[Signal]:
    """Generate a long signal from a momentum screen result.

    Entry: current close
    Stop: below SMA-20 or 2x ATR, whichever is tighter
    Target: 2:1 reward/risk from entry
    """
    if result.trend != "bullish" or result.score < 50:
        return None

    close = Decimal(str(result.close))
    sma20 = Decimal(str(result.sma_20))
    atr_val = Decimal(str(round(result.atr_pct / 100 * result.close, 4)))

    # Stop loss: tighter of SMA-20 or 2x ATR below
    stop_sma = sma20 - atr_val * Decimal("0.5")
    stop_atr = close - atr_val * 2
    stop = max(stop_sma, stop_atr)  # tighter stop

    risk = close - stop
    if risk <= 0:
        return None

    target = close + risk * 2  # 2:1 R/R

    return Signal(
        symbol=result.symbol,
        asset_class=_classify_asset(result.symbol),
        direction=SignalDirection.LONG,
        strength=min(result.score / 100, 1.0),
        strategy="momentum",
        entry_price=close,
        stop_loss=round(stop, 2),
        take_profit=round(target, 2),
        timeframe=TimeFrame.D1,
        metadata={
            "rsi": result.rsi_14,
            "volume_ratio": result.volume_ratio,
            "trend_score": result.details.get("trend_score", 0),
            "macd_histogram": result.details.get("macd_histogram", 0),
        },
    )


def signal_from_mean_reversion(result: ScreenResult, bars: list[Bar]) -> Optional[Signal]:
    """Generate a long signal from a mean reversion screen result.

    Entry: current close (oversold bounce)
    Stop: below recent low or lower Bollinger Band
    Target: SMA-20 (mean reversion target)
    """
    if result.score < 30:
        return None

    close = Decimal(str(result.close))
    sma20 = Decimal(str(result.sma_20))
    atr_val = Decimal(str(round(result.atr_pct / 100 * result.close, 4)))

    # Stop: 1.5x ATR below current price
    stop = close - atr_val * Decimal("1.5")
    # Target: SMA-20 (the "mean" we're reverting to)
    target = sma20

    if target <= close:
        # Already above SMA-20, use SMA-50 or 2x ATR
        target = close + atr_val * 2

    risk = close - stop
    if risk <= 0:
        return None

    return Signal(
        symbol=result.symbol,
        asset_class=_classify_asset(result.symbol),
        direction=SignalDirection.LONG,
        strength=min(result.score / 100, 1.0),
        strategy="mean_reversion",
        entry_price=close,
        stop_loss=round(stop, 2),
        take_profit=round(target, 2),
        timeframe=TimeFrame.D1,
        metadata={
            "rsi": result.rsi_14,
            "bb_pct_b": result.bb_pct_b,
            "volume_ratio": result.volume_ratio,
        },
    )


def signal_from_volatility(result: ScreenResult) -> Optional[Signal]:
    """Generate an options premium signal from a volatility screen result.

    This produces a NEUTRAL signal — it's for selling premium (strangles,
    iron condors) not directional trades. The tastytrade project handles
    the actual options strategy construction.
    """
    if result.score < 40:
        return None

    close = Decimal(str(result.close))

    return Signal(
        symbol=result.symbol,
        asset_class=_classify_asset(result.symbol),
        direction=SignalDirection.NEUTRAL,
        strength=min(result.score / 100, 1.0),
        strategy="volatility_premium",
        entry_price=close,
        timeframe=TimeFrame.D1,
        metadata={
            "atr_pct": result.atr_pct,
            "rsi": result.rsi_14,
            "trend": result.trend,
            "volume_ratio": result.volume_ratio,
            "suggested_strategy": _suggest_options_strategy(result),
        },
    )


def _suggest_options_strategy(result: ScreenResult) -> str:
    """Suggest an options strategy based on market conditions."""
    if result.trend == "bullish":
        if result.rsi_14 > 60:
            return "short_put"  # bullish + strong = sell puts
        return "short_put"
    elif result.trend == "bearish":
        if result.rsi_14 < 35:
            return "short_put"  # oversold bounce potential
        return "iron_condor"  # bearish + volatile = defined risk
    else:
        if result.atr_pct > 5:
            return "iron_condor"  # very volatile neutral = defined risk
        return "strangle"  # moderate vol neutral = sell both sides


def generate_signals(
    momentum_results: list[ScreenResult],
    reversion_results: list[ScreenResult],
    volatility_results: list[ScreenResult],
    max_signals: int = 10,
) -> list[Signal]:
    """Generate signals from all screener results, ranked by strength."""
    signals = []

    for r in momentum_results[:5]:
        bars = get_bars(r.symbol, period="6mo")
        sig = signal_from_momentum(r, bars)
        if sig:
            signals.append(sig)

    for r in reversion_results[:5]:
        bars = get_bars(r.symbol, period="6mo")
        sig = signal_from_mean_reversion(r, bars)
        if sig:
            signals.append(sig)

    for r in volatility_results[:5]:
        sig = signal_from_volatility(r)
        if sig:
            signals.append(sig)

    # Sort by strength descending
    signals.sort(key=lambda s: s.strength, reverse=True)
    return signals[:max_signals]
