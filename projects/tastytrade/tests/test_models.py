"""Tests for core models."""

from decimal import Decimal

from tastytrade_strategy.models import (
    CoveredCall,
    Direction,
    IronCondor,
    MarketMetrics,
    OptionContract,
    OptionGreeks,
    OptionType,
    OrderLeg,
    ScreenResult,
    ShortPut,
    Straddle,
    Strangle,
    VerticalSpread,
)


# ---------------------------------------------------------------------------
# MCP schema compatibility
# ---------------------------------------------------------------------------

def test_order_leg_model_dump_matches_mcp():
    """OrderLeg.model_dump() must match tasty-agent MCP server schema."""
    leg = OrderLeg(
        symbol="AAPL",
        action="Sell to Open",
        quantity=1,
        option_type="P",
        strike_price=150.0,
        expiration_date="2025-03-21",
    )
    d = leg.model_dump()
    assert d == {
        "symbol": "AAPL",
        "action": "Sell to Open",
        "quantity": 1,
        "option_type": "P",
        "strike_price": 150.0,
        "expiration_date": "2025-03-21",
    }


def test_order_leg_stock():
    """Stock legs omit option fields."""
    leg = OrderLeg(symbol="AAPL", action="Buy", quantity=100)
    d = leg.model_dump()
    assert d["option_type"] is None
    assert d["strike_price"] is None
    assert d["expiration_date"] is None


def test_instrument_spec_model_dump_matches_mcp():
    """InstrumentSpec.model_dump() must match tasty-agent MCP server schema."""
    from tastytrade_strategy.models import InstrumentSpec

    spec = InstrumentSpec(
        symbol="TQQQ",
        option_type="C",
        strike_price=45.0,
        expiration_date="2025-04-17",
    )
    d = spec.model_dump()
    assert d == {
        "symbol": "TQQQ",
        "option_type": "C",
        "strike_price": 45.0,
        "expiration_date": "2025-04-17",
    }


# ---------------------------------------------------------------------------
# OptionContract
# ---------------------------------------------------------------------------

def test_option_contract_to_instrument_spec():
    contract = OptionContract(
        underlying="SPY",
        option_type=OptionType.PUT,
        strike_price=Decimal("450"),
        expiration_date="2025-03-21",
    )
    spec = contract.to_instrument_spec()
    d = spec.model_dump()
    assert d["symbol"] == "SPY"
    assert d["option_type"] == "P"
    assert d["strike_price"] == 450.0
    assert d["expiration_date"] == "2025-03-21"


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------

def test_option_greeks():
    g = OptionGreeks(
        price=Decimal("2.50"),
        implied_volatility=Decimal("0.35"),
        delta=Decimal("-0.30"),
        gamma=Decimal("0.02"),
        theta=Decimal("-0.05"),
        rho=Decimal("0.01"),
        vega=Decimal("0.15"),
    )
    assert g.delta == Decimal("-0.30")


# ---------------------------------------------------------------------------
# RiskProfile
# ---------------------------------------------------------------------------

def test_risk_profile_ratio():
    from tastytrade_strategy.models import RiskProfile

    rp = RiskProfile(
        max_profit=Decimal("100"),
        max_loss=Decimal("400"),
        breakevens=[Decimal("96")],
    )
    assert rp.risk_reward_ratio == Decimal("4")


def test_risk_profile_ratio_zero_profit():
    from tastytrade_strategy.models import RiskProfile

    rp = RiskProfile(
        max_profit=Decimal("0"),
        max_loss=Decimal("500"),
    )
    assert rp.risk_reward_ratio is None


# ---------------------------------------------------------------------------
# ShortPut
# ---------------------------------------------------------------------------

def test_short_put_order_legs():
    sp = ShortPut(
        underlying="AAPL",
        expiration_date="2025-03-21",
        strike=Decimal("150"),
        quantity=2,
    )
    legs = sp.to_order_legs()
    assert len(legs) == 1
    d = legs[0].model_dump()
    assert d["symbol"] == "AAPL"
    assert d["action"] == "Sell to Open"
    assert d["quantity"] == 2
    assert d["option_type"] == "P"
    assert d["strike_price"] == 150.0


def test_short_put_risk_profile():
    sp = ShortPut(
        underlying="AAPL",
        expiration_date="2025-03-21",
        strike=Decimal("100"),
        credit=Decimal("2.00"),
    )
    rp = sp.risk_profile()
    assert rp.max_profit == Decimal("200")   # 2.00 * 1 * 100
    assert rp.max_loss == Decimal("9800")     # (100 - 2) * 1 * 100
    assert rp.breakevens == [Decimal("98")]


# ---------------------------------------------------------------------------
# CoveredCall
# ---------------------------------------------------------------------------

def test_covered_call_order_legs():
    cc = CoveredCall(
        underlying="AAPL",
        expiration_date="2025-03-21",
        strike=Decimal("160"),
        stock_price=Decimal("155"),
    )
    legs = cc.to_order_legs()
    assert len(legs) == 2
    assert legs[0].action == "Buy"
    assert legs[0].quantity == 100
    assert legs[1].action == "Sell to Open"
    assert legs[1].option_type == "C"


def test_covered_call_risk_profile():
    cc = CoveredCall(
        underlying="AAPL",
        expiration_date="2025-03-21",
        strike=Decimal("160"),
        stock_price=Decimal("155"),
        credit=Decimal("3.00"),
    )
    rp = cc.risk_profile()
    # cost_basis = 155 - 3 = 152
    # max_profit = (160 - 152) * 100 = 800
    assert rp.max_profit == Decimal("800")
    assert rp.breakevens == [Decimal("152")]


# ---------------------------------------------------------------------------
# VerticalSpread
# ---------------------------------------------------------------------------

def test_vertical_spread_order_legs():
    vs = VerticalSpread(
        underlying="SPY",
        expiration_date="2025-03-21",
        short_strike=Decimal("450"),
        long_strike=Decimal("445"),
        option_type=OptionType.PUT,
        direction=Direction.BULLISH,
    )
    legs = vs.to_order_legs()
    assert len(legs) == 2
    short_leg = legs[0].model_dump()
    long_leg = legs[1].model_dump()
    assert short_leg["action"] == "Sell to Open"
    assert short_leg["strike_price"] == 450.0
    assert long_leg["action"] == "Buy to Open"
    assert long_leg["strike_price"] == 445.0


def test_vertical_spread_risk_profile_put():
    vs = VerticalSpread(
        underlying="SPY",
        expiration_date="2025-03-21",
        short_strike=Decimal("450"),
        long_strike=Decimal("445"),
        option_type=OptionType.PUT,
        direction=Direction.BULLISH,
        credit=Decimal("1.50"),
    )
    rp = vs.risk_profile()
    assert rp.max_profit == Decimal("150")   # 1.50 * 100
    assert rp.max_loss == Decimal("350")     # (5 - 1.50) * 100
    assert rp.breakevens == [Decimal("448.50")]


def test_vertical_spread_risk_profile_call():
    vs = VerticalSpread(
        underlying="SPY",
        expiration_date="2025-03-21",
        short_strike=Decimal("450"),
        long_strike=Decimal("455"),
        option_type=OptionType.CALL,
        direction=Direction.BEARISH,
        credit=Decimal("2.00"),
    )
    rp = vs.risk_profile()
    assert rp.breakevens == [Decimal("452")]


# ---------------------------------------------------------------------------
# IronCondor
# ---------------------------------------------------------------------------

def test_iron_condor_order_legs():
    ic = IronCondor(
        underlying="SPY",
        expiration_date="2025-03-21",
        put_long_strike=Decimal("430"),
        put_short_strike=Decimal("440"),
        call_short_strike=Decimal("460"),
        call_long_strike=Decimal("470"),
    )
    legs = ic.to_order_legs()
    assert len(legs) == 4
    actions = [l.action for l in legs]
    assert actions.count("Buy to Open") == 2
    assert actions.count("Sell to Open") == 2


def test_iron_condor_risk_profile():
    ic = IronCondor(
        underlying="SPY",
        expiration_date="2025-03-21",
        put_long_strike=Decimal("430"),
        put_short_strike=Decimal("440"),
        call_short_strike=Decimal("460"),
        call_long_strike=Decimal("470"),
        credit=Decimal("3.00"),
    )
    rp = ic.risk_profile()
    assert rp.max_profit == Decimal("300")
    assert rp.max_loss == Decimal("700")  # (10 - 3) * 100
    assert len(rp.breakevens) == 2


# ---------------------------------------------------------------------------
# Strangle
# ---------------------------------------------------------------------------

def test_strangle_order_legs():
    s = Strangle(
        underlying="AAPL",
        expiration_date="2025-03-21",
        put_strike=Decimal("140"),
        call_strike=Decimal("160"),
    )
    legs = s.to_order_legs()
    assert len(legs) == 2
    assert all(l.action == "Sell to Open" for l in legs)
    types = [l.option_type for l in legs]
    assert "P" in types
    assert "C" in types


def test_strangle_risk_profile():
    s = Strangle(
        underlying="AAPL",
        expiration_date="2025-03-21",
        put_strike=Decimal("140"),
        call_strike=Decimal("160"),
        credit=Decimal("4.00"),
    )
    rp = s.risk_profile()
    assert rp.max_profit == Decimal("400")
    assert rp.breakevens == [Decimal("136"), Decimal("164")]


# ---------------------------------------------------------------------------
# Straddle
# ---------------------------------------------------------------------------

def test_straddle_order_legs():
    s = Straddle(
        underlying="AAPL",
        expiration_date="2025-03-21",
        strike=Decimal("150"),
    )
    legs = s.to_order_legs()
    assert len(legs) == 2
    assert legs[0].strike_price == legs[1].strike_price == 150.0


def test_straddle_risk_profile():
    s = Straddle(
        underlying="AAPL",
        expiration_date="2025-03-21",
        strike=Decimal("150"),
        credit=Decimal("5.00"),
    )
    rp = s.risk_profile()
    assert rp.max_profit == Decimal("500")
    assert rp.breakevens == [Decimal("145"), Decimal("155")]


# ---------------------------------------------------------------------------
# MarketMetrics & ScreenResult
# ---------------------------------------------------------------------------

def test_market_metrics():
    m = MarketMetrics(
        symbol="AAPL",
        iv_rank=Decimal("0.42"),
        implied_volatility=Decimal("0.30"),
        liquidity_rating=Decimal("5"),
    )
    assert m.iv_rank == Decimal("0.42")
    assert m.symbol == "AAPL"


def test_screen_result():
    m = MarketMetrics(symbol="AAPL", iv_rank=Decimal("0.55"))
    sr = ScreenResult(
        symbol="AAPL",
        metrics=m,
        score=Decimal("78.5"),
        reasons=["High IV rank", "Good liquidity"],
    )
    assert sr.score == Decimal("78.5")
    assert len(sr.reasons) == 2
