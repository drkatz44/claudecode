"""Core Pydantic v2 types for tastytrade options strategy library.

Models mirror the tasty-agent MCP server schemas so that model_dump() output
can be passed directly to MCP tools like place_order() and get_quotes().
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OptionType(StrEnum):
    CALL = "C"
    PUT = "P"


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class StrategyType(StrEnum):
    SHORT_PUT = "short_put"
    COVERED_CALL = "covered_call"
    VERTICAL_SPREAD = "vertical_spread"
    IRON_CONDOR = "iron_condor"
    STRANGLE = "strangle"
    STRADDLE = "straddle"


class TradeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# MCP I/O models — field-for-field match with tasty-agent server.py
# ---------------------------------------------------------------------------

class InstrumentSpec(BaseModel):
    """Specification for an instrument (stock or option).

    Matches tasty-agent MCP server InstrumentSpec exactly.
    """

    symbol: str = Field(..., description="Stock symbol (e.g., 'AAPL', 'TQQQ')")
    option_type: Literal["C", "P"] | None = Field(
        None, description="Option type: 'C' for call, 'P' for put (omit for stocks)"
    )
    strike_price: float | None = Field(None, description="Strike price (required for options)")
    expiration_date: str | None = Field(
        None, description="Expiration date in YYYY-MM-DD format (required for options)"
    )


class OrderLeg(BaseModel):
    """Specification for an order leg.

    Matches tasty-agent MCP server OrderLeg exactly.
    """

    symbol: str = Field(..., description="Stock symbol (e.g., 'TQQQ', 'AAPL')")
    action: str = Field(
        ...,
        description=(
            "For stocks: 'Buy' or 'Sell'. "
            "For options: 'Buy to Open', 'Buy to Close', 'Sell to Open', 'Sell to Close'"
        ),
    )
    quantity: int = Field(..., description="Number of contracts/shares")
    option_type: Literal["C", "P"] | None = Field(
        None, description="Option type: 'C' for call, 'P' for put (omit for stocks)"
    )
    strike_price: float | None = Field(None, description="Strike price (required for options)")
    expiration_date: str | None = Field(
        None, description="Expiration date in YYYY-MM-DD format (required for options)"
    )


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------

class OptionGreeks(BaseModel):
    """Greeks for an option contract."""

    price: Decimal = Field(..., description="Option mark price")
    implied_volatility: Decimal = Field(..., description="Implied volatility")
    delta: Decimal = Field(..., description="Delta")
    gamma: Decimal = Field(..., description="Gamma")
    theta: Decimal = Field(..., description="Theta (daily)")
    rho: Decimal = Field(..., description="Rho")
    vega: Decimal = Field(..., description="Vega")


# ---------------------------------------------------------------------------
# Option contract
# ---------------------------------------------------------------------------

class OptionContract(BaseModel):
    """Represents a single option contract with metadata."""

    underlying: str
    option_type: OptionType
    strike_price: Decimal
    expiration_date: str  # YYYY-MM-DD
    greeks: OptionGreeks | None = None

    def to_instrument_spec(self) -> InstrumentSpec:
        """Convert to MCP InstrumentSpec for get_quotes/get_greeks calls."""
        return InstrumentSpec(
            symbol=self.underlying,
            option_type=self.option_type.value,
            strike_price=float(self.strike_price),
            expiration_date=self.expiration_date,
        )


# ---------------------------------------------------------------------------
# Risk profile
# ---------------------------------------------------------------------------

class RiskProfile(BaseModel):
    """Risk/reward profile for a strategy."""

    max_profit: Decimal = Field(..., description="Maximum profit (positive)")
    max_loss: Decimal = Field(..., description="Maximum loss (positive = amount at risk)")
    breakevens: list[Decimal] = Field(default_factory=list, description="Breakeven prices")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_reward_ratio(self) -> Decimal | None:
        """Max loss / max profit. None if max_profit is zero."""
        if self.max_profit == 0:
            return None
        return self.max_loss / self.max_profit


# ---------------------------------------------------------------------------
# Spread / strategy models
# ---------------------------------------------------------------------------

class ShortPut(BaseModel):
    """Naked short put."""

    underlying: str
    expiration_date: str
    strike: Decimal
    quantity: int = 1
    credit: Decimal | None = None
    greeks: OptionGreeks | None = None

    def to_order_legs(self) -> list[OrderLeg]:
        return [
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="P",
                strike_price=float(self.strike),
                expiration_date=self.expiration_date,
            )
        ]

    def risk_profile(self) -> RiskProfile:
        credit = self.credit or Decimal("0")
        max_loss = (self.strike - credit) * self.quantity * 100
        max_profit = credit * self.quantity * 100
        breakeven = self.strike - credit
        return RiskProfile(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[breakeven],
        )


class CoveredCall(BaseModel):
    """Covered call: long stock + short call."""

    underlying: str
    expiration_date: str
    strike: Decimal
    stock_price: Decimal
    quantity: int = 1  # number of contracts (each covers 100 shares)
    credit: Decimal | None = None

    def to_order_legs(self) -> list[OrderLeg]:
        return [
            OrderLeg(
                symbol=self.underlying,
                action="Buy",
                quantity=self.quantity * 100,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="C",
                strike_price=float(self.strike),
                expiration_date=self.expiration_date,
            ),
        ]

    def risk_profile(self) -> RiskProfile:
        credit = self.credit or Decimal("0")
        cost_basis = self.stock_price - credit
        max_profit = (self.strike - cost_basis) * self.quantity * 100
        max_loss = cost_basis * self.quantity * 100
        breakeven = cost_basis
        return RiskProfile(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[breakeven],
        )


class VerticalSpread(BaseModel):
    """Bull/bear put or call vertical spread."""

    underlying: str
    expiration_date: str
    short_strike: Decimal
    long_strike: Decimal
    option_type: OptionType
    direction: Direction  # bullish or bearish
    quantity: int = 1
    credit: Decimal | None = None

    def to_order_legs(self) -> list[OrderLeg]:
        return [
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type=self.option_type.value,
                strike_price=float(self.short_strike),
                expiration_date=self.expiration_date,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Buy to Open",
                quantity=self.quantity,
                option_type=self.option_type.value,
                strike_price=float(self.long_strike),
                expiration_date=self.expiration_date,
            ),
        ]

    def risk_profile(self) -> RiskProfile:
        width = abs(self.short_strike - self.long_strike)
        credit = self.credit or Decimal("0")
        max_profit = credit * self.quantity * 100
        max_loss = (width - credit) * self.quantity * 100
        if self.option_type == OptionType.PUT:
            breakeven = self.short_strike - credit
        else:
            breakeven = self.short_strike + credit
        return RiskProfile(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[breakeven],
        )


class IronCondor(BaseModel):
    """Iron condor: bull put spread + bear call spread."""

    underlying: str
    expiration_date: str
    put_long_strike: Decimal   # lower put (protection)
    put_short_strike: Decimal  # higher put (short)
    call_short_strike: Decimal  # lower call (short)
    call_long_strike: Decimal   # higher call (protection)
    quantity: int = 1
    credit: Decimal | None = None

    def to_order_legs(self) -> list[OrderLeg]:
        return [
            OrderLeg(
                symbol=self.underlying,
                action="Buy to Open",
                quantity=self.quantity,
                option_type="P",
                strike_price=float(self.put_long_strike),
                expiration_date=self.expiration_date,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="P",
                strike_price=float(self.put_short_strike),
                expiration_date=self.expiration_date,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="C",
                strike_price=float(self.call_short_strike),
                expiration_date=self.expiration_date,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Buy to Open",
                quantity=self.quantity,
                option_type="C",
                strike_price=float(self.call_long_strike),
                expiration_date=self.expiration_date,
            ),
        ]

    def risk_profile(self) -> RiskProfile:
        credit = self.credit or Decimal("0")
        put_width = self.put_short_strike - self.put_long_strike
        call_width = self.call_long_strike - self.call_short_strike
        max_width = max(put_width, call_width)
        max_profit = credit * self.quantity * 100
        max_loss = (max_width - credit) * self.quantity * 100
        put_breakeven = self.put_short_strike - credit
        call_breakeven = self.call_short_strike + credit
        return RiskProfile(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[put_breakeven, call_breakeven],
        )


class Strangle(BaseModel):
    """Short strangle: short OTM put + short OTM call."""

    underlying: str
    expiration_date: str
    put_strike: Decimal
    call_strike: Decimal
    quantity: int = 1
    credit: Decimal | None = None

    def to_order_legs(self) -> list[OrderLeg]:
        return [
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="P",
                strike_price=float(self.put_strike),
                expiration_date=self.expiration_date,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="C",
                strike_price=float(self.call_strike),
                expiration_date=self.expiration_date,
            ),
        ]

    def risk_profile(self) -> RiskProfile:
        credit = self.credit or Decimal("0")
        max_profit = credit * self.quantity * 100
        # Undefined (theoretically unlimited) loss — use put side as proxy
        max_loss = (self.put_strike - credit) * self.quantity * 100
        put_breakeven = self.put_strike - credit
        call_breakeven = self.call_strike + credit
        return RiskProfile(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[put_breakeven, call_breakeven],
        )


class Straddle(BaseModel):
    """Short straddle: short ATM put + short ATM call at same strike."""

    underlying: str
    expiration_date: str
    strike: Decimal
    quantity: int = 1
    credit: Decimal | None = None

    def to_order_legs(self) -> list[OrderLeg]:
        return [
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="P",
                strike_price=float(self.strike),
                expiration_date=self.expiration_date,
            ),
            OrderLeg(
                symbol=self.underlying,
                action="Sell to Open",
                quantity=self.quantity,
                option_type="C",
                strike_price=float(self.strike),
                expiration_date=self.expiration_date,
            ),
        ]

    def risk_profile(self) -> RiskProfile:
        credit = self.credit or Decimal("0")
        max_profit = credit * self.quantity * 100
        max_loss = (self.strike - credit) * self.quantity * 100
        put_breakeven = self.strike - credit
        call_breakeven = self.strike + credit
        return RiskProfile(
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[put_breakeven, call_breakeven],
        )


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

class MarketMetrics(BaseModel):
    """Parsed market metrics from MCP get_market_metrics.

    iv_rank is normalized to 0-1 range (e.g. 0.42 = 42nd percentile).
    """

    symbol: str
    iv_rank: Decimal = Field(..., description="IV rank normalized to 0-1")
    iv_percentile: Decimal | None = Field(None, description="IV percentile normalized to 0-1")
    implied_volatility: Decimal | None = Field(None, description="Current IV")
    historical_volatility: Decimal | None = Field(None, description="Historical volatility")
    liquidity_rating: Decimal | None = Field(None, description="Liquidity rating")
    beta: Decimal | None = None
    market_cap: Decimal | None = None
    earnings_date: str | None = None  # YYYY-MM-DD
    borrow_rate: Decimal | None = None


# ---------------------------------------------------------------------------
# Screen output
# ---------------------------------------------------------------------------

class ScreenResult(BaseModel):
    """Result of screening a symbol against criteria."""

    symbol: str
    metrics: MarketMetrics
    score: Decimal = Field(..., description="Composite score (higher = better candidate)")
    reasons: list[str] = Field(default_factory=list, description="Why this symbol scored well")
