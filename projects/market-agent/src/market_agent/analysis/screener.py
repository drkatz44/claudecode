"""Market screener — find trading opportunities across asset classes."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pandas as pd

from ..data.fetcher import get_bars, get_fundamentals, get_multiple_bars
from .technical import atr, bars_to_df, bollinger_bands, rsi, sma, trend_summary, volume_sma_ratio


@dataclass
class ScreenResult:
    """Single screener result with scoring."""
    symbol: str
    score: float
    trend: str
    rsi_14: float
    atr_pct: float  # ATR as % of price
    volume_ratio: float  # current vol / avg vol
    bb_pct_b: float
    close: float
    sma_20: float
    sma_50: float
    sector: Optional[str] = None
    market_cap: Optional[int] = None
    details: dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


# --- Preset Watchlists ---

SP500_TOP = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "UNH", "XOM", "V", "MA", "PG", "COST", "JNJ", "HD", "ABBV",
    "MRK", "WMT", "NFLX", "AMD", "CRM", "ORCL", "CVX", "BAC", "KO", "PEP",
]

CRYPTO_MAJORS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "AVAX-USD",
    "DOT-USD", "LINK-USD", "POL-USD", "XRP-USD", "ATOM-USD",
]

SECTOR_ETFS = [
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLB", "XLU", "XLRE", "XLC",
]

HIGH_IV_NAMES = [
    "TSLA", "NVDA", "AMD", "MARA", "RIOT", "COIN", "PLTR", "SOFI",
    "MSTR", "GME", "AMC", "HOOD", "RBLX", "SNAP", "XYZ", "SHOP",
]


def screen_momentum(
    symbols: list[str],
    min_rsi: float = 50,
    max_rsi: float = 70,
    min_volume_ratio: float = 1.0,
    lookback: str = "6mo",
) -> list[ScreenResult]:
    """Screen for momentum: uptrend + rising volume + not overbought."""
    all_bars = get_multiple_bars(symbols, period=lookback)
    results = []

    for sym, bars in all_bars.items():
        if len(bars) < 50:
            continue

        summary = trend_summary(bars)
        if summary.get("error"):
            continue

        vol_ratio = volume_sma_ratio(bars).iloc[-1]
        atr_val = float(summary["atr_14"])
        close = float(summary["close"])
        atr_pct = (atr_val / close * 100) if close > 0 else 0

        rsi_val = summary["rsi_14"]

        # Score: favor strong uptrend + not overbought + above-average volume
        score = 0.0
        if summary["trend"] == "bullish":
            score += 40
        elif summary["trend"] == "neutral":
            score += 20

        # RSI in sweet spot (not overbought, not oversold)
        if min_rsi <= rsi_val <= max_rsi:
            score += 25
        elif rsi_val < min_rsi:
            score += 10  # could be starting move

        # Volume confirmation
        if vol_ratio > 1.5:
            score += 20
        elif vol_ratio > 1.0:
            score += 10

        # MACD positive
        if summary["macd_histogram"] > 0:
            score += 15

        if rsi_val < min_rsi or rsi_val > max_rsi:
            continue
        if vol_ratio < min_volume_ratio:
            continue

        results.append(ScreenResult(
            symbol=sym,
            score=round(score, 1),
            trend=summary["trend"],
            rsi_14=rsi_val,
            atr_pct=round(atr_pct, 2),
            volume_ratio=round(float(vol_ratio), 2),
            bb_pct_b=float(summary["bb_pct_b"]),
            close=close,
            sma_20=float(summary["sma_20"]),
            sma_50=float(summary["sma_50"]),
            details=summary,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def screen_mean_reversion(
    symbols: list[str],
    max_rsi: float = 30,
    max_bb_pct_b: float = 0.1,
    lookback: str = "6mo",
) -> list[ScreenResult]:
    """Screen for mean reversion: oversold + near lower Bollinger Band."""
    all_bars = get_multiple_bars(symbols, period=lookback)
    results = []

    for sym, bars in all_bars.items():
        if len(bars) < 50:
            continue

        summary = trend_summary(bars)
        if summary.get("error"):
            continue

        rsi_val = summary["rsi_14"]
        bb_pct = float(summary["bb_pct_b"])
        vol_ratio = volume_sma_ratio(bars).iloc[-1]
        close = float(summary["close"])
        atr_val = float(summary["atr_14"])
        atr_pct = (atr_val / close * 100) if close > 0 else 0

        if rsi_val > max_rsi and bb_pct > max_bb_pct_b:
            continue

        # Score: favor deeply oversold + high volume (capitulation)
        score = 0.0
        if rsi_val < 20:
            score += 40
        elif rsi_val < 30:
            score += 25

        if bb_pct < 0:
            score += 30  # below lower band
        elif bb_pct < 0.1:
            score += 20

        if vol_ratio > 2.0:
            score += 20  # high volume = potential capitulation
        elif vol_ratio > 1.5:
            score += 10

        # Penalize if still in strong downtrend (catching falling knife)
        if summary["trend"] == "bearish":
            score -= 15

        results.append(ScreenResult(
            symbol=sym,
            score=round(score, 1),
            trend=summary["trend"],
            rsi_14=rsi_val,
            atr_pct=round(atr_pct, 2),
            volume_ratio=round(float(vol_ratio), 2),
            bb_pct_b=bb_pct,
            close=close,
            sma_20=float(summary["sma_20"]),
            sma_50=float(summary["sma_50"]),
            details=summary,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def screen_volatility(
    symbols: list[str],
    min_atr_pct: float = 2.0,
    lookback: str = "6mo",
) -> list[ScreenResult]:
    """Screen for high-volatility names good for options premium selling."""
    all_bars = get_multiple_bars(symbols, period=lookback)
    results = []

    for sym, bars in all_bars.items():
        if len(bars) < 50:
            continue

        summary = trend_summary(bars)
        if summary.get("error"):
            continue

        close = float(summary["close"])
        atr_val = float(summary["atr_14"])
        atr_pct = (atr_val / close * 100) if close > 0 else 0
        vol_ratio = volume_sma_ratio(bars).iloc[-1]

        if atr_pct < min_atr_pct:
            continue

        # Score: favor high volatility + liquid + not in free-fall
        score = 0.0
        score += min(atr_pct * 10, 40)  # cap at 40 for volatility
        if vol_ratio > 1.0:
            score += 20
        if summary["trend"] != "bearish":
            score += 20  # selling premium is safer in uptrend/neutral
        if summary["rsi_14"] > 30:
            score += 10  # not deeply oversold

        results.append(ScreenResult(
            symbol=sym,
            score=round(score, 1),
            trend=summary["trend"],
            rsi_14=summary["rsi_14"],
            atr_pct=round(atr_pct, 2),
            volume_ratio=round(float(vol_ratio), 2),
            bb_pct_b=float(summary["bb_pct_b"]),
            close=close,
            sma_20=float(summary["sma_20"]),
            sma_50=float(summary["sma_50"]),
            details=summary,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results
