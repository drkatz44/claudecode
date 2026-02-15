"""Market screener — find trading opportunities across asset classes."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

import pandas as pd

from ..data.fetcher import get_bars, get_fundamentals, get_multiple_bars
from .technical import atr, bars_to_df, bollinger_bands, relative_strength, rsi, sma, trend_summary, volume_sma_ratio


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
    rs_spy: Optional[float] = None  # relative strength vs SPY
    details: dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


def _near_earnings(symbol: str, days_buffer: int = 7) -> bool:
    """Return True if symbol has earnings within days_buffer days."""
    try:
        fund = get_fundamentals(symbol)
        if not fund or not fund.next_earnings:
            return False
        days_until = (fund.next_earnings - datetime.now()).days
        return -days_buffer <= days_until <= days_buffer
    except Exception:
        return False


def filter_correlated(
    results: list[ScreenResult],
    threshold: float = 0.7,
    lookback: str = "3mo",
) -> list[ScreenResult]:
    """Remove highly correlated symbols, keeping highest-scoring per cluster."""
    if len(results) <= 1:
        return results

    symbols = [r.symbol for r in results]
    all_bars = get_multiple_bars(symbols, period=lookback)

    # Build returns matrix
    returns_dict = {}
    for sym, bars in all_bars.items():
        if len(bars) < 20:
            continue
        df = bars_to_df(bars)
        returns_dict[sym] = df["close"].pct_change().dropna()

    if len(returns_dict) < 2:
        return results

    returns_df = pd.DataFrame(returns_dict)
    corr_matrix = returns_df.corr()

    # Greedy: keep top scorers, skip correlated
    filtered = []
    skip = set()

    for r in results:
        if r.symbol not in corr_matrix.index or r.symbol in skip:
            continue
        filtered.append(r)
        for other in corr_matrix.index:
            if other != r.symbol and other not in skip:
                if corr_matrix.loc[r.symbol, other] > threshold:
                    skip.add(other)

    return filtered


# --- Preset Watchlists ---

SP500_TOP = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "UNH", "XOM", "V", "MA", "PG", "COST", "JNJ", "HD", "ABBV",
    "MRK", "WMT", "NFLX", "AMD", "CRM", "ORCL", "CVX", "BAC", "KO", "PEP",
]

CRYPTO_MAJORS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "AVAX-USD",
    "DOT-USD", "LINK-USD", "DOGE-USD", "XRP-USD", "ATOM-USD",
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
    skip_earnings: bool = True,
    min_rs: Optional[float] = None,
) -> list[ScreenResult]:
    """Screen for momentum: uptrend + rising volume + not overbought."""
    all_bars = get_multiple_bars(symbols, period=lookback)
    spy_bars = get_bars("SPY", period=lookback) if min_rs is not None else None
    results = []

    for sym, bars in all_bars.items():
        if len(bars) < 50:
            continue
        if skip_earnings and _near_earnings(sym):
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

        # Relative strength filter
        rs_val = None
        if spy_bars and min_rs is not None:
            rs = relative_strength(bars, spy_bars, period=63)
            rs_val = round(float(rs.iloc[-1]), 2) if not pd.isna(rs.iloc[-1]) else None
            if rs_val is not None and rs_val < min_rs:
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
            rs_spy=rs_val,
            details=summary,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def screen_mean_reversion(
    symbols: list[str],
    max_rsi: float = 30,
    max_bb_pct_b: float = 0.1,
    lookback: str = "6mo",
    skip_earnings: bool = True,
) -> list[ScreenResult]:
    """Screen for mean reversion: oversold + near lower Bollinger Band."""
    all_bars = get_multiple_bars(symbols, period=lookback)
    results = []

    for sym, bars in all_bars.items():
        if len(bars) < 50:
            continue
        if skip_earnings and _near_earnings(sym):
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
    skip_earnings: bool = True,
) -> list[ScreenResult]:
    """Screen for high-volatility names good for options premium selling."""
    all_bars = get_multiple_bars(symbols, period=lookback)
    results = []

    for sym, bars in all_bars.items():
        if len(bars) < 50:
            continue
        if skip_earnings and _near_earnings(sym):
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
