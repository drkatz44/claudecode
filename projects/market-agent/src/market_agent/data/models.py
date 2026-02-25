"""Core data models for market data, signals, and positions."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"
    ETF = "etf"


class TimeFrame(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class Bar(BaseModel):
    """Single OHLCV bar."""
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Optional[Decimal] = None


class Quote(BaseModel):
    """Real-time quote snapshot."""
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume: int
    timestamp: datetime

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


class OptionQuote(BaseModel):
    """Option contract quote with Greeks."""
    symbol: str
    underlying: str
    strike: Decimal
    expiration: datetime
    option_type: str  # "call" or "put"
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume: int
    open_interest: int
    iv: Optional[Decimal] = None
    delta: Optional[Decimal] = None
    gamma: Optional[Decimal] = None
    theta: Optional[Decimal] = None
    vega: Optional[Decimal] = None


class Signal(BaseModel):
    """Trading signal output — broker-agnostic."""
    symbol: str
    asset_class: AssetClass
    direction: SignalDirection
    strength: float = Field(ge=0, le=1, description="Signal confidence 0-1")
    strategy: str = Field(description="Strategy name that generated this signal")
    entry_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    timeframe: TimeFrame = TimeFrame.D1
    metadata: dict = Field(default_factory=dict, description="Strategy-specific data")
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def risk_reward(self) -> Optional[float]:
        if self.entry_price and self.stop_loss and self.take_profit:
            risk = abs(float(self.entry_price - self.stop_loss))
            reward = abs(float(self.take_profit - self.entry_price))
            return reward / risk if risk > 0 else None
        return None


class Fundamentals(BaseModel):
    """Company fundamentals snapshot."""
    symbol: str
    market_cap: Optional[int] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    dividend_yield: Optional[float] = None
    eps: Optional[float] = None
    revenue: Optional[int] = None
    profit_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[Decimal] = None
    fifty_two_week_low: Optional[Decimal] = None
    avg_volume: Optional[int] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    next_earnings: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class CotReport(BaseModel):
    """Raw CFTC Commitments of Traders positioning data (disaggregated futures)."""
    commodity: str
    report_date: datetime
    managed_money_long: int
    managed_money_short: int
    managed_money_spreading: int
    commercial_long: int
    commercial_short: int
    non_reportable_long: int
    non_reportable_short: int
    open_interest: int


class CotAnalysis(BaseModel):
    """Derived analytics from COT positioning data."""
    commodity: str
    report_date: datetime
    mm_net: int = Field(description="Managed money net (long - short)")
    mm_net_pct: float = Field(description="MM net as pct of open interest")
    z_score: float = Field(description="Z-score of MM net vs 1yr history")
    positioning_signal: str = Field(description="extreme_long|extreme_short|neutral")
    weekly_change: int = Field(description="Week-over-week change in MM net")


class ComexWarehouse(BaseModel):
    """COMEX warehouse stock levels."""
    metal: str
    date: datetime
    registered: float = Field(description="Registered stocks (eligible for delivery)")
    eligible: float = Field(description="Eligible stocks (stored but not for delivery)")
    total: float = Field(description="Registered + eligible")
    unit: str = Field(default="troy_oz", description="troy_oz or lbs")


class ComexAnalysis(BaseModel):
    """Derived analytics from COMEX warehouse data."""
    metal: str
    date: datetime
    registered_pct: float = Field(description="Registered as pct of total")
    trend: str = Field(description="drawing|building|stable")
    change_30d_pct: float = Field(description="30-day change in total stocks %")
