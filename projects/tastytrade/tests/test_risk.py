"""Tests for risk management module."""

from datetime import date, timedelta
from decimal import Decimal

from tastytrade_strategy.models import OrderLeg, RiskProfile
from tastytrade_strategy.risk import (
    PortfolioSnapshot,
    PositionSummary,
    RiskCheckResult,
    RiskRules,
    check_trade,
    portfolio_from_positions,
)

# Always use a future expiration for tests that should pass DTE checks
_FUTURE_EXP = (date.today() + timedelta(days=45)).strftime("%Y-%m-%d")


def _portfolio(nlv: str = "100000", bp: str = "50000") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        net_liquidating_value=Decimal(nlv),
        buying_power=Decimal(bp),
    )


def _legs(symbol: str = "SPY", expiration: str | None = None) -> list[OrderLeg]:
    if expiration is None:
        expiration = _FUTURE_EXP
    return [
        OrderLeg(
            symbol=symbol,
            action="Sell to Open",
            quantity=1,
            option_type="P",
            strike_price=450.0,
            expiration_date=expiration,
        )
    ]


def _risk_profile(max_loss: str = "3000", max_profit: str = "1500") -> RiskProfile:
    return RiskProfile(
        max_profit=Decimal(max_profit),
        max_loss=Decimal(max_loss),
        breakevens=[Decimal("447")],
    )


class TestCheckTrade:
    def test_approved_within_limits(self):
        result = check_trade(
            risk_profile=_risk_profile("3000"),
            legs=_legs(),
            portfolio=_portfolio("100000"),
        )
        assert result.approved is True
        assert len(result.violations) == 0

    def test_position_size_violation(self):
        # 10000 max_loss on 100000 NLV = 10% > 5% default
        result = check_trade(
            risk_profile=_risk_profile("10000"),
            legs=_legs(),
            portfolio=_portfolio("100000"),
        )
        assert result.approved is False
        assert any("Position risk" in v for v in result.violations)

    def test_position_size_warning(self):
        # 4500 / 100000 = 4.5% > 80% of 5% threshold
        result = check_trade(
            risk_profile=_risk_profile("4500"),
            legs=_legs(),
            portfolio=_portfolio("100000"),
        )
        assert result.approved is True
        assert any("approaching" in w for w in result.warnings)

    def test_dte_violation(self):
        result = check_trade(
            risk_profile=_risk_profile("3000"),
            legs=_legs(expiration="2020-01-01"),  # in the past
            portfolio=_portfolio(),
        )
        assert result.approved is False
        assert any("DTE" in v for v in result.violations)

    def test_correlated_positions_violation(self):
        portfolio = PortfolioSnapshot(
            net_liquidating_value=Decimal("100000"),
            buying_power=Decimal("50000"),
            positions=[
                PositionSummary(underlying="SPY", quantity=1),
                PositionSummary(underlying="SPY", quantity=1),
                PositionSummary(underlying="SPY", quantity=1),
            ],
        )
        result = check_trade(
            risk_profile=_risk_profile("3000"),
            legs=_legs(symbol="SPY"),
            portfolio=portfolio,
        )
        assert result.approved is False
        assert any("positions in SPY" in v for v in result.violations)

    def test_buying_power_violation(self):
        # 30000 max_loss on 50000 BP = 60% usage > 50% default
        result = check_trade(
            risk_profile=_risk_profile("30000"),
            legs=_legs(),
            portfolio=_portfolio("200000", "50000"),
        )
        assert result.approved is False
        assert any("BP usage" in v for v in result.violations)

    def test_risk_reward_warning(self):
        result = check_trade(
            risk_profile=_risk_profile("3000", "500"),  # 6:1 ratio
            legs=_legs(),
            portfolio=_portfolio(),
        )
        assert any("risk/reward" in w for w in result.warnings)

    def test_custom_rules(self):
        rules = RiskRules(
            max_position_pct=Decimal("0.10"),
            max_bp_usage_pct=Decimal("0.80"),
            min_dte=3,
        )
        result = check_trade(
            risk_profile=_risk_profile("8000"),
            legs=_legs(),
            portfolio=_portfolio("100000"),
            rules=rules,
        )
        assert result.approved is True


class TestPortfolioFromPositions:
    def test_basic_construction(self):
        positions = [
            {"underlying-symbol": "AAPL", "quantity": "10", "mark": "150.5"},
            {"underlying-symbol": "SPY", "quantity": "5", "mark": "450.0"},
        ]
        balances = {
            "net-liquidating-value": "100000",
            "derivative-buying-power": "50000",
        }
        portfolio = portfolio_from_positions(positions, balances)
        assert portfolio.net_liquidating_value == Decimal("100000")
        assert portfolio.buying_power == Decimal("50000")
        assert len(portfolio.positions) == 2
        assert portfolio.positions[0].underlying == "AAPL"

    def test_empty_positions(self):
        portfolio = portfolio_from_positions(
            [], {"net-liquidating-value": "50000", "derivative-buying-power": "25000"}
        )
        assert len(portfolio.positions) == 0
        assert portfolio.net_liquidating_value == Decimal("50000")

    def test_missing_fields_fallback(self):
        positions = [{"symbol": "AAPL"}]
        balances = {}
        portfolio = portfolio_from_positions(positions, balances)
        assert portfolio.positions[0].underlying == "AAPL"
        assert portfolio.net_liquidating_value == Decimal("0")
