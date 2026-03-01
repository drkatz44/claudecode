"""Market data fetcher — yfinance backend (no API key needed).

Provides unified data access that can be swapped to MCP backends
(Polygon, Alpha Vantage) when API keys are available.
"""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from .models import Bar, Fundamentals, OptionQuote, Quote

# --- File-based cache ---

CACHE_DIR = Path.home() / ".market-agent" / "cache"


def _cache_key(symbol: str, period: str, interval: str, start: Optional[str], end: Optional[str]) -> str:
    key = f"{symbol}|{period}|{interval}|{start}|{end}|{datetime.utcnow().strftime('%Y-%m-%d')}"
    return hashlib.md5(key.encode()).hexdigest()


def _load_cache(key: str, ttl_hours: int) -> Optional[list[Bar]]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (datetime.utcnow().timestamp() - path.stat().st_mtime) / 3600
    if age_hours > ttl_hours:
        path.unlink()
        return None
    with open(path) as f:
        data = json.load(f)
    return [
        Bar(
            timestamp=datetime.fromisoformat(b["t"]),
            open=Decimal(b["o"]),
            high=Decimal(b["h"]),
            low=Decimal(b["l"]),
            close=Decimal(b["c"]),
            volume=b["v"],
        )
        for b in data
    ]


def _save_cache(key: str, bars: list[Bar]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    data = [
        {"t": b.timestamp.isoformat(), "o": str(b.open), "h": str(b.high),
         "l": str(b.low), "c": str(b.close), "v": b.volume}
        for b in bars
    ]
    with open(path, "w") as f:
        json.dump(data, f)


def get_bars(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
    start: Optional[str] = None,
    end: Optional[str] = None,
    use_cache: bool = True,
    cache_ttl_hours: int = 4,
) -> list[Bar]:
    """Fetch OHLCV bars for a symbol with file-based caching.

    Args:
        symbol: Ticker symbol (e.g., "AAPL", "BTC-USD", "SPY")
        period: yfinance period string ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max")
        interval: Bar interval ("1m", "5m", "15m", "1h", "1d", "1wk")
        start: Start date string (overrides period if set)
        end: End date string
        use_cache: Use file-based cache (default True)
        cache_ttl_hours: Cache TTL in hours (default 4)
    """
    # Check cache first
    if use_cache:
        key = _cache_key(symbol, period, interval, start, end)
        cached = _load_cache(key, cache_ttl_hours)
        if cached is not None:
            return cached

    ticker = yf.Ticker(symbol)
    kwargs = {"interval": interval}
    if start:
        kwargs["start"] = start
        if end:
            kwargs["end"] = end
    else:
        kwargs["period"] = period

    df = ticker.history(**kwargs)
    if df.empty:
        return []

    bars = []
    for ts, row in df.iterrows():
        if pd.notna(row["Close"]) and pd.notna(row["Volume"]):
            bars.append(Bar(
                timestamp=ts.to_pydatetime(),
                open=Decimal(str(round(row["Open"], 4))),
                high=Decimal(str(round(row["High"], 4))),
                low=Decimal(str(round(row["Low"], 4))),
                close=Decimal(str(round(row["Close"], 4))),
                volume=int(row["Volume"]),
            ))

    # Save to cache
    if use_cache and bars:
        _save_cache(key, bars)

    return bars


def get_quote(symbol: str) -> Optional[Quote]:
    """Fetch current quote for a symbol."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    if not info or "bid" not in info:
        # Fallback to last bar
        df = ticker.history(period="1d", interval="1m")
        if df.empty:
            return None
        last_row = df.iloc[-1]
        return Quote(
            symbol=symbol,
            bid=Decimal(str(round(last_row["Close"], 4))),
            ask=Decimal(str(round(last_row["Close"], 4))),
            last=Decimal(str(round(last_row["Close"], 4))),
            volume=int(last_row["Volume"]),
            timestamp=df.index[-1].to_pydatetime(),
        )

    return Quote(
        symbol=symbol,
        bid=Decimal(str(info.get("bid", 0))),
        ask=Decimal(str(info.get("ask", 0))),
        last=Decimal(str(info.get("regularMarketPrice", info.get("previousClose", 0)))),
        volume=int(info.get("regularMarketVolume", info.get("volume", 0))),
        timestamp=datetime.utcnow(),
    )


def get_fundamentals(symbol: str) -> Optional[Fundamentals]:
    """Fetch company fundamentals. Returns None for ETFs and crypto."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    if not info or "symbol" not in info:
        return None
    if info.get("quoteType") in ("ETF", "CRYPTOCURRENCY"):
        return None

    cal = ticker.calendar
    next_earnings = None
    if isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.columns and len(cal) > 0:
        next_earnings = cal["Earnings Date"].iloc[0]
    elif isinstance(cal, dict) and "Earnings Date" in cal:
        dates = cal["Earnings Date"]
        if dates:
            next_earnings = dates[0] if isinstance(dates, list) else dates

    return Fundamentals(
        symbol=symbol,
        market_cap=info.get("marketCap"),
        pe_ratio=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        peg_ratio=info.get("pegRatio"),
        price_to_book=info.get("priceToBook"),
        dividend_yield=info.get("dividendYield"),
        eps=info.get("trailingEps"),
        revenue=info.get("totalRevenue"),
        profit_margin=info.get("profitMargins"),
        debt_to_equity=info.get("debtToEquity"),
        current_ratio=info.get("currentRatio"),
        beta=info.get("beta"),
        fifty_two_week_high=Decimal(str(info["fiftyTwoWeekHigh"])) if info.get("fiftyTwoWeekHigh") else None,
        fifty_two_week_low=Decimal(str(info["fiftyTwoWeekLow"])) if info.get("fiftyTwoWeekLow") else None,
        avg_volume=info.get("averageVolume"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        next_earnings=next_earnings,
    )


def get_multiple_bars(
    symbols: list[str],
    period: str = "6mo",
    interval: str = "1d",
) -> dict[str, list[Bar]]:
    """Fetch bars for multiple symbols efficiently."""
    df = yf.download(symbols, period=period, interval=interval, group_by="ticker", progress=False)
    result = {}

    if len(symbols) == 1:
        # yf.download doesn't group by ticker for single symbol
        sym = symbols[0]
        result[sym] = []
        for ts, row in df.iterrows():
            if pd.notna(row["Close"]):
                result[sym].append(Bar(
                    timestamp=ts.to_pydatetime(),
                    open=Decimal(str(round(row["Open"], 4))),
                    high=Decimal(str(round(row["High"], 4))),
                    low=Decimal(str(round(row["Low"], 4))),
                    close=Decimal(str(round(row["Close"], 4))),
                    volume=int(row["Volume"]),
                ))
    else:
        for sym in symbols:
            if sym not in df.columns.get_level_values(0):
                continue
            sym_df = df[sym]
            result[sym] = []
            for ts, row in sym_df.iterrows():
                if pd.notna(row["Close"]):
                    result[sym].append(Bar(
                        timestamp=ts.to_pydatetime(),
                        open=Decimal(str(round(row["Open"], 4))),
                        high=Decimal(str(round(row["High"], 4))),
                        low=Decimal(str(round(row["Low"], 4))),
                        close=Decimal(str(round(row["Close"], 4))),
                        volume=int(row["Volume"]),
                    ))

    return result


def get_expirations(symbol: str) -> list[str]:
    """Return list of available option expiration dates for a symbol."""
    try:
        ticker = yf.Ticker(symbol)
        return list(ticker.options)
    except Exception:
        return []


def get_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    use_cache: bool = True,
    cache_ttl_hours: float = 0.25,  # 15 minutes
) -> list[OptionQuote]:
    """Fetch option chain for a symbol at a given expiration.

    Args:
        symbol: Ticker symbol
        expiry: Expiration date string (YYYY-MM-DD). If None, uses nearest expiration.
        use_cache: Use file-based cache (default True)
        cache_ttl_hours: Cache TTL in hours (default 0.25 = 15 min)

    Returns:
        List of OptionQuote objects for both calls and puts.
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            return []

        target_expiry = expiry if expiry and expiry in expirations else expirations[0]
        chain = ticker.option_chain(target_expiry)
    except Exception:
        return []

    quotes = []
    expiry_dt = datetime.strptime(target_expiry, "%Y-%m-%d")

    for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
        for _, row in df.iterrows():
            strike = row.get("strike")
            if strike is None or pd.isna(strike) or strike <= 0:
                continue

            bid = row.get("bid", 0)
            ask = row.get("ask", 0)
            last = row.get("lastPrice", 0)
            iv = row.get("impliedVolatility")

            # Skip zero-bid options (no market)
            if pd.isna(bid) or bid <= 0:
                continue

            quotes.append(OptionQuote(
                symbol=row.get("contractSymbol", ""),
                underlying=symbol,
                strike=Decimal(str(round(float(strike), 2))),
                expiration=expiry_dt,
                option_type=opt_type,
                bid=Decimal(str(round(float(bid), 4))) if pd.notna(bid) else Decimal("0"),
                ask=Decimal(str(round(float(ask), 4))) if pd.notna(ask) else Decimal("0"),
                last=Decimal(str(round(float(last), 4))) if pd.notna(last) else Decimal("0"),
                volume=int(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                open_interest=int(row.get("openInterest", 0)) if pd.notna(row.get("openInterest")) else 0,
                iv=Decimal(str(round(float(iv), 4))) if pd.notna(iv) and 0 < iv < 5.0 else None,
            ))

    return quotes
