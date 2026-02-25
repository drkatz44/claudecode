"""Historical options data provider with pluggable backends.

Two implementations:
  YFinanceOptionsProvider — works today (current chains only, IV from yfinance)
  ThetaDataProvider      — full historical chains + pre-computed Greeks ($40/mo)
                           activated by setting theta_data_key in config.yaml

Usage:
    provider = get_provider()
    chain = provider.get_chain("SPY", date(2024, 1, 15), "2024-02-16")
    expirations = provider.get_expirations("SPY", date(2024, 1, 15))
"""

import hashlib
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..data.models import OptionQuote

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".market-agent" / "cache" / "theta"
CACHE_TTL_HOURS = 24.0  # Historical data doesn't change — 24hr cache


# ---------------------------------------------------------------------------
# Cache helpers (mirrors fetcher.py pattern)
# ---------------------------------------------------------------------------

def _cache_key(symbol: str, as_of: date, expiry: str) -> str:
    raw = f"theta|{symbol}|{as_of.isoformat()}|{expiry}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache(key: str, ttl_hours: float) -> list[dict] | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age = (time.time() - path.stat().st_mtime) / 3600
    if age > ttl_hours:
        path.unlink(missing_ok=True)
        return None
    return json.loads(path.read_text())


def _save_cache(key: str, data: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)


def _quotes_to_dicts(quotes: list[OptionQuote]) -> list[dict]:
    return [
        {
            "symbol": q.symbol,
            "underlying": q.underlying,
            "strike": str(q.strike),
            "expiration": q.expiration.isoformat(),
            "option_type": q.option_type,
            "bid": str(q.bid),
            "ask": str(q.ask),
            "last": str(q.last),
            "volume": q.volume,
            "open_interest": q.open_interest,
            "iv": str(q.iv) if q.iv is not None else None,
            "delta": str(q.delta) if q.delta is not None else None,
            "gamma": str(q.gamma) if q.gamma is not None else None,
            "theta": str(q.theta) if q.theta is not None else None,
            "vega": str(q.vega) if q.vega is not None else None,
        }
        for q in quotes
    ]


def _dicts_to_quotes(data: list[dict]) -> list[OptionQuote]:
    from decimal import Decimal
    quotes = []
    for d in data:
        try:
            quotes.append(OptionQuote(
                symbol=d["symbol"],
                underlying=d["underlying"],
                strike=Decimal(d["strike"]),
                expiration=datetime.fromisoformat(d["expiration"]),
                option_type=d["option_type"],
                bid=Decimal(d["bid"]),
                ask=Decimal(d["ask"]),
                last=Decimal(d["last"]),
                volume=d["volume"],
                open_interest=d["open_interest"],
                iv=Decimal(d["iv"]) if d.get("iv") else None,
                delta=Decimal(d["delta"]) if d.get("delta") else None,
                gamma=Decimal(d["gamma"]) if d.get("gamma") else None,
                theta=Decimal(d["theta"]) if d.get("theta") else None,
                vega=Decimal(d["vega"]) if d.get("vega") else None,
            ))
        except (KeyError, ValueError):
            continue
    return quotes


# ---------------------------------------------------------------------------
# Protocol / interface
# ---------------------------------------------------------------------------

@runtime_checkable
class OptionsDataProvider(Protocol):
    """Common interface for options data providers."""

    def get_chain(
        self,
        symbol: str,
        as_of: date,
        expiry: str,
        use_cache: bool = True,
    ) -> list[OptionQuote]:
        """Fetch option chain for symbol as of a historical date.

        Args:
            symbol: Underlying ticker
            as_of: Historical date (ignored by YFinanceProvider, which uses today)
            expiry: Expiration date string "YYYY-MM-DD"
            use_cache: Whether to use the local cache

        Returns:
            List of OptionQuote objects, empty if unavailable.
        """
        ...

    def get_expirations(self, symbol: str, as_of: date | None = None) -> list[str]:
        """Return available expiration date strings for a symbol."""
        ...


# ---------------------------------------------------------------------------
# YFinance implementation (works today, current chains only)
# ---------------------------------------------------------------------------

class YFinanceOptionsProvider:
    """Options data provider backed by yfinance.

    Limitations:
    - Only returns the current option chain (no historical data)
    - The `as_of` date parameter is ignored
    - IV is available but Greeks are computed via Black-Scholes

    Suitable for: live scanning, proposal generation, current risk checks.
    Not suitable for: historical backtesting of option structures.
    """

    def get_chain(
        self,
        symbol: str,
        as_of: date | None = None,
        expiry: str | None = None,
        use_cache: bool = True,
    ) -> list[OptionQuote]:
        from ..data.fetcher import get_option_chain
        from ..analysis.black_scholes import enrich_option_quote_greeks
        from ..data.fetcher import get_bars

        chain = get_option_chain(symbol, expiry, use_cache=use_cache)

        # Enrich with BS Greeks using current underlying price
        if chain:
            bars = get_bars(symbol, period="5d", interval="1d")
            if bars:
                spot = float(bars[-1].close)
                for q in chain:
                    enrich_option_quote_greeks(q, spot)

        return chain

    def get_expirations(self, symbol: str, as_of: date | None = None) -> list[str]:
        from ..data.fetcher import get_expirations
        return get_expirations(symbol)


# ---------------------------------------------------------------------------
# Theta Data implementation (stub — activated by config key)
# ---------------------------------------------------------------------------

class ThetaDataProvider:
    """Historical options data provider via Theta Data REST API.

    Requires:
        - Active Theta Data subscription ($40/mo at thetadata.net)
        - API key in ~/.market-agent/config.yaml under `theta_data_key`

    Provides:
        - Full historical end-of-day option chains
        - Pre-computed NBBO bid/ask, IV, delta, gamma, theta, vega
        - Data from 2010 onwards for major underlyings

    Cache: 24-hour TTL at ~/.market-agent/cache/theta/
    """

    BASE_URL = "https://api.thetadata.us/v2"

    def __init__(self, api_key: str):
        if not api_key or not isinstance(api_key, str):
            raise ValueError("Theta Data API key required")
        self._api_key = api_key

    def get_chain(
        self,
        symbol: str,
        as_of: date | None = None,
        expiry: str | None = None,
        use_cache: bool = True,
    ) -> list[OptionQuote]:
        if as_of is None:
            as_of = date.today()
        if expiry is None:
            return []

        key = _cache_key(symbol, as_of, expiry)
        if use_cache:
            cached = _load_cache(key, CACHE_TTL_HOURS)
            if cached is not None:
                return _dicts_to_quotes(cached)

        quotes = self._fetch_chain(symbol, as_of, expiry)
        if use_cache and quotes:
            _save_cache(key, _quotes_to_dicts(quotes))

        return quotes

    def _fetch_chain(self, symbol: str, as_of: date, expiry: str) -> list[OptionQuote]:
        """Call Theta Data API. Returns empty list if unavailable."""
        import requests
        from decimal import Decimal

        exp_fmt = expiry.replace("-", "")  # Theta Data uses YYYYMMDD
        as_of_fmt = as_of.strftime("%Y%m%d")

        url = f"{self.BASE_URL}/bulk_snapshot/option/quote"
        params = {
            "root": symbol,
            "exp": exp_fmt,
            "start_date": as_of_fmt,
            "end_date": as_of_fmt,
        }
        headers = {"X-API-Key": self._api_key}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Theta Data API error for %s", symbol)
            return []

        return self._parse_response(data, symbol, expiry)

    def _parse_response(self, data: dict, symbol: str, expiry: str) -> list[OptionQuote]:
        """Parse Theta Data API response into OptionQuote list."""
        from decimal import Decimal

        quotes = []
        for row in data.get("response", []):
            try:
                mid_price = (row["ask"] + row["bid"]) / 2
                quotes.append(OptionQuote(
                    symbol=f"{symbol}{expiry}{row['right']}{row['strike']}",
                    underlying=symbol,
                    strike=Decimal(str(row["strike"] / 1000)),  # Theta uses millicents
                    expiration=datetime.strptime(expiry, "%Y-%m-%d"),
                    option_type="call" if row["right"] == "C" else "put",
                    bid=Decimal(str(row["bid"] / 100)),
                    ask=Decimal(str(row["ask"] / 100)),
                    last=Decimal(str(mid_price / 100)),
                    volume=row.get("volume", 0),
                    open_interest=row.get("open_interest", 0),
                    iv=Decimal(str(row["iv"])) if row.get("iv") else None,
                    delta=Decimal(str(row["delta"])) if row.get("delta") else None,
                    gamma=Decimal(str(row["gamma"])) if row.get("gamma") else None,
                    theta=Decimal(str(row["theta"])) if row.get("theta") else None,
                    vega=Decimal(str(row["vega"])) if row.get("vega") else None,
                ))
            except (KeyError, ValueError, TypeError):
                continue

        return [q for q in quotes if float(q.bid) >= 0 and float(q.ask) >= float(q.bid)]

    def get_expirations(self, symbol: str, as_of: date | None = None) -> list[str]:
        """Return available expiration dates from Theta Data."""
        import requests

        if as_of is None:
            as_of = date.today()

        url = f"{self.BASE_URL}/list/expirations"
        params = {"root": symbol}
        headers = {"X-API-Key": self._api_key}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            exps = [
                datetime.strptime(str(e), "%Y%m%d").strftime("%Y-%m-%d")
                for e in data.get("response", [])
                if int(str(e)) >= int(as_of.strftime("%Y%m%d"))
            ]
            return sorted(exps)
        except Exception:
            logger.exception("Theta Data expirations error for %s", symbol)
            return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider() -> OptionsDataProvider:
    """Return the best available options data provider.

    Checks ~/.market-agent/config.yaml for `theta_data_key`.
    Falls back to YFinanceOptionsProvider if key is absent or empty.
    """
    try:
        from ..data.config import load_config
        # Config object doesn't have theta_data_key yet — check raw YAML
        import yaml
        from pathlib import Path
        config_path = Path.home() / ".market-agent" / "config.yaml"
        if config_path.exists():
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            key = raw.get("theta_data_key", "").strip()
            if key:
                logger.info("Using Theta Data provider")
                return ThetaDataProvider(key)
    except Exception:
        pass

    logger.debug("Using YFinance options provider (no Theta Data key configured)")
    return YFinanceOptionsProvider()
