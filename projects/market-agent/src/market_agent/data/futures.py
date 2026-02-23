"""Futures contract specifications for the trading universe.

Covers CME/COMEX/NYMEX/ICE contracts traded on tastytrade.
Each spec includes multiplier, tick size, exchange, micro symbol,
and option-relevant fields.
"""

from pydantic import BaseModel
from typing import Optional


class FuturesSpec(BaseModel):
    """Specification for a single futures contract."""

    symbol: str
    name: str
    multiplier: int
    tick_size: float
    exchange: str
    micro: Optional[str] = None
    option_tick: float = 0.01  # Minimum option price increment
    margin_initial: Optional[int] = None  # Approx initial margin per contract
    trading_hours: str = "ETH"  # ETH = electronic trading hours
    sector: str = "index"


FUTURES_SPECS: dict[str, FuturesSpec] = {
    # Equity indices
    "ES": FuturesSpec(
        symbol="ES", name="E-mini S&P 500", multiplier=50, tick_size=0.25,
        exchange="CME", micro="MES", margin_initial=12650, sector="index",
    ),
    "NQ": FuturesSpec(
        symbol="NQ", name="E-mini Nasdaq 100", multiplier=20, tick_size=0.25,
        exchange="CME", micro="MNQ", margin_initial=17600, sector="index",
    ),
    "RTY": FuturesSpec(
        symbol="RTY", name="E-mini Russell 2000", multiplier=50, tick_size=0.10,
        exchange="CME", micro="M2K", margin_initial=7150, sector="index",
    ),
    "YM": FuturesSpec(
        symbol="YM", name="E-mini Dow", multiplier=5, tick_size=1.0,
        exchange="CME", micro="MYM", margin_initial=9900, sector="index",
    ),
    # Metals
    "GC": FuturesSpec(
        symbol="GC", name="Gold", multiplier=100, tick_size=0.10,
        exchange="COMEX", micro="MGC", margin_initial=11000, sector="metals",
    ),
    "SI": FuturesSpec(
        symbol="SI", name="Silver", multiplier=5000, tick_size=0.005,
        exchange="COMEX", micro="SIL", margin_initial=15400, sector="metals",
    ),
    "HG": FuturesSpec(
        symbol="HG", name="Copper", multiplier=25000, tick_size=0.0005,
        exchange="COMEX", micro="MHG", margin_initial=7700, sector="metals",
    ),
    "PL": FuturesSpec(
        symbol="PL", name="Platinum", multiplier=50, tick_size=0.10,
        exchange="NYMEX", margin_initial=4400, sector="metals",
    ),
    # Energy
    "CL": FuturesSpec(
        symbol="CL", name="Crude Oil WTI", multiplier=1000, tick_size=0.01,
        exchange="NYMEX", micro="MCL", margin_initial=6600, sector="energy",
    ),
    "NG": FuturesSpec(
        symbol="NG", name="Natural Gas", multiplier=10000, tick_size=0.001,
        exchange="NYMEX", margin_initial=3300, sector="energy",
    ),
    # Currencies
    "6E": FuturesSpec(
        symbol="6E", name="Euro FX", multiplier=125000, tick_size=0.00005,
        exchange="CME", micro="M6E", margin_initial=2750, sector="currency",
    ),
    "6J": FuturesSpec(
        symbol="6J", name="Japanese Yen", multiplier=12500000, tick_size=0.0000005,
        exchange="CME", margin_initial=4400, sector="currency",
    ),
    "6B": FuturesSpec(
        symbol="6B", name="British Pound", multiplier=62500, tick_size=0.0001,
        exchange="CME", margin_initial=2750, sector="currency",
    ),
    # Crypto
    "BTC": FuturesSpec(
        symbol="BTC", name="Bitcoin", multiplier=5, tick_size=5.0,
        exchange="CME", micro="MBT", margin_initial=44000, sector="crypto",
    ),
}


# Default trading universe for scanning
FUTURES_UNIVERSE = list(FUTURES_SPECS.keys())

# High-liquidity ETF universe (options on these are very liquid)
ETF_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA",    # Index
    "GLD", "SLV",                    # Metals
    "USO", "XLE",                    # Energy
    "TLT", "IEF",                    # Bonds
    "EEM", "FXI",                    # International
    "XLF", "XLK", "XLV",            # Sectors
    "ARKK", "NVDA", "AAPL", "TSLA", # High-vol names
]

# Combined universe
FULL_UNIVERSE = FUTURES_UNIVERSE + ETF_UNIVERSE


def get_spec(symbol: str) -> Optional[FuturesSpec]:
    """Get futures contract spec by symbol. Returns None for non-futures."""
    return FUTURES_SPECS.get(symbol.upper())


def is_futures(symbol: str) -> bool:
    """Check if symbol is a futures contract."""
    return symbol.upper() in FUTURES_SPECS


def notional_value(symbol: str, price: float) -> Optional[float]:
    """Calculate notional value of one futures contract."""
    spec = get_spec(symbol)
    if not spec:
        return None
    return price * spec.multiplier


def tick_value(symbol: str) -> Optional[float]:
    """Calculate dollar value of one tick move."""
    spec = get_spec(symbol)
    if not spec:
        return None
    return spec.tick_size * spec.multiplier
