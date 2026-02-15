"""Technical analysis indicators computed from OHLCV bars.

All functions take a list of Bar objects and return pandas Series
or DataFrames for easy composition.
"""

from decimal import Decimal

import pandas as pd

from ..data.models import Bar


def bars_to_df(bars: list[Bar]) -> pd.DataFrame:
    """Convert Bar list to pandas DataFrame with float columns."""
    records = [{
        "timestamp": b.timestamp,
        "open": float(b.open),
        "high": float(b.high),
        "low": float(b.low),
        "close": float(b.close),
        "volume": b.volume,
    } for b in bars]
    df = pd.DataFrame(records)
    if not df.empty:
        df.set_index("timestamp", inplace=True)
    return df


# --- Trend Indicators ---

def sma(bars: list[Bar], period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    df = bars_to_df(bars)
    return df["close"].rolling(window=period).mean()


def ema(bars: list[Bar], period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    df = bars_to_df(bars)
    return df["close"].ewm(span=period, adjust=False).mean()


def macd(bars: list[Bar], fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD (Moving Average Convergence Divergence).

    Returns DataFrame with columns: macd, signal, histogram
    """
    df = bars_to_df(bars)
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }, index=df.index)


# --- Momentum Indicators ---

def rsi(bars: list[Bar], period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100)."""
    df = bars_to_df(bars)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def stochastic(bars: list[Bar], k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator (%K, %D)."""
    df = bars_to_df(bars)
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    denom = (high_max - low_min).replace(0, 1e-10)
    k = 100 * (df["close"] - low_min) / denom
    d = k.rolling(window=d_period).mean()
    return pd.DataFrame({"k": k, "d": d}, index=df.index)


def rate_of_change(bars: list[Bar], period: int = 10) -> pd.Series:
    """Rate of Change (percentage)."""
    df = bars_to_df(bars)
    return df["close"].pct_change(periods=period) * 100


# --- Volatility Indicators ---

def bollinger_bands(bars: list[Bar], period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands.

    Returns DataFrame with columns: upper, middle, lower, bandwidth, pct_b
    """
    df = bars_to_df(bars)
    middle = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    band_width_raw = upper - lower
    bandwidth = band_width_raw / middle.replace(0, 1e-10)
    pct_b = (df["close"] - lower) / band_width_raw.replace(0, 1e-10)
    return pd.DataFrame({
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
        "pct_b": pct_b,
    }, index=df.index)


def atr(bars: list[Bar], period: int = 14) -> pd.Series:
    """Average True Range."""
    df = bars_to_df(bars)
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def historical_volatility(bars: list[Bar], period: int = 20) -> pd.Series:
    """Annualized historical volatility (close-to-close)."""
    import numpy as np
    df = bars_to_df(bars)
    log_returns = np.log(df["close"] / df["close"].shift(1))
    return log_returns.rolling(window=period).std() * (252 ** 0.5)


# --- Volume Indicators ---

def vwap_rolling(bars: list[Bar], period: int = 20) -> pd.Series:
    """Rolling VWAP approximation."""
    df = bars_to_df(bars)
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]
    return tp_vol.rolling(window=period).sum() / df["volume"].rolling(window=period).sum()


def obv(bars: list[Bar]) -> pd.Series:
    """On-Balance Volume."""
    df = bars_to_df(bars)
    direction = df["close"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * df["volume"]).cumsum()


def volume_sma_ratio(bars: list[Bar], period: int = 20) -> pd.Series:
    """Current volume as ratio of SMA volume. >1 = above average."""
    df = bars_to_df(bars)
    avg_vol = df["volume"].rolling(window=period).mean().replace(0, 1e-10)
    return df["volume"] / avg_vol


# --- Trend Strength ---

def adx(bars: list[Bar], period: int = 14) -> pd.DataFrame:
    """Average Directional Index — measures trend strength (0-100).

    ADX > 25 = trending market, < 20 = ranging/choppy.
    +DI > -DI = bullish pressure, -DI > +DI = bearish pressure.

    Returns DataFrame with columns: adx, plus_di, minus_di
    """
    df = bars_to_df(bars)
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder smoothing (same as ATR)
    atr_smooth = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di_smooth = plus_dm.ewm(alpha=1 / period, min_periods=period).mean()
    minus_di_smooth = minus_dm.ewm(alpha=1 / period, min_periods=period).mean()

    atr_safe = atr_smooth.replace(0, 1e-10)
    plus_di = 100 * plus_di_smooth / atr_safe
    minus_di = 100 * minus_di_smooth / atr_safe

    # ADX = smoothed DX
    di_sum = (plus_di + minus_di).replace(0, 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx_line = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return pd.DataFrame({
        "adx": adx_line,
        "plus_di": plus_di,
        "minus_di": minus_di,
    }, index=df.index)


def relative_strength(bars: list[Bar], benchmark_bars: list[Bar], period: int = 63) -> pd.Series:
    """Relative strength vs a benchmark (e.g., SPY).

    RS > 1.0 = outperforming benchmark over the period.
    RS < 1.0 = underperforming benchmark.

    Args:
        bars: Symbol's OHLCV bars
        benchmark_bars: Benchmark's OHLCV bars (e.g., SPY)
        period: Lookback for rate-of-change comparison (63 ~= 3 months)
    """
    import numpy as np

    sym_df = bars_to_df(bars)
    bench_df = bars_to_df(benchmark_bars)

    merged = pd.merge(
        sym_df[["close"]].rename(columns={"close": "sym"}),
        bench_df[["close"]].rename(columns={"close": "bench"}),
        left_index=True, right_index=True, how="inner",
    )

    sym_roc = merged["sym"].pct_change(periods=period)
    bench_roc = merged["bench"].pct_change(periods=period)

    rs = (1 + sym_roc) / (1 + bench_roc).replace(0, 1e-10)
    return rs.replace([np.inf, -np.inf], np.nan)


# --- Support/Resistance ---

def pivot_points(bars: list[Bar]) -> dict[str, Decimal]:
    """Classic pivot points from the most recent bar."""
    if not bars:
        return {}
    last = bars[-1]
    h, l, c = float(last.high), float(last.low), float(last.close)
    pivot = (h + l + c) / 3
    return {
        "r2": Decimal(str(round(pivot + (h - l), 4))),
        "r1": Decimal(str(round(2 * pivot - l, 4))),
        "pivot": Decimal(str(round(pivot, 4))),
        "s1": Decimal(str(round(2 * pivot - h, 4))),
        "s2": Decimal(str(round(pivot - (h - l), 4))),
    }


# --- Composite Analysis ---

def trend_summary(bars: list[Bar]) -> dict:
    """Quick trend assessment from multiple indicators."""
    if len(bars) < 50:
        return {"error": "Need at least 50 bars"}

    df = bars_to_df(bars)
    close = df["close"].iloc[-1]
    sma_20 = sma(bars, 20).iloc[-1]
    sma_50 = sma(bars, 50).iloc[-1]
    ema_12 = ema(bars, 12).iloc[-1]
    rsi_val = rsi(bars, 14).iloc[-1]
    macd_data = macd(bars)
    bb = bollinger_bands(bars)
    atr_val = atr(bars).iloc[-1]

    # Trend direction
    bullish_signals = 0
    bearish_signals = 0

    if close > sma_20:
        bullish_signals += 1
    else:
        bearish_signals += 1

    if close > sma_50:
        bullish_signals += 1
    else:
        bearish_signals += 1

    if sma_20 > sma_50:
        bullish_signals += 1
    else:
        bearish_signals += 1

    if macd_data["histogram"].iloc[-1] > 0:
        bullish_signals += 1
    else:
        bearish_signals += 1

    if rsi_val > 50:
        bullish_signals += 1
    else:
        bearish_signals += 1

    total = bullish_signals + bearish_signals
    trend_score = (bullish_signals - bearish_signals) / total  # -1 to +1

    return {
        "close": close,
        "sma_20": round(sma_20, 2),
        "sma_50": round(sma_50, 2),
        "ema_12": round(ema_12, 2),
        "rsi_14": round(rsi_val, 1),
        "macd_histogram": round(macd_data["histogram"].iloc[-1], 4),
        "bb_pct_b": round(bb["pct_b"].iloc[-1], 3),
        "atr_14": round(atr_val, 4),
        "trend_score": round(trend_score, 2),
        "trend": "bullish" if trend_score > 0.2 else "bearish" if trend_score < -0.2 else "neutral",
        "bullish_signals": bullish_signals,
        "bearish_signals": bearish_signals,
    }
