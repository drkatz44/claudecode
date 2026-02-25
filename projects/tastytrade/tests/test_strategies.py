"""Tests for strategy utilities."""

from decimal import Decimal

from tastytrade_strategy.models import OptionContract, OptionGreeks, OptionType
from tastytrade_strategy.strategies import find_strike_by_delta


def _make_contract(strike: Decimal, delta: Decimal, opt_type: OptionType) -> OptionContract:
    return OptionContract(
        underlying="SPY",
        option_type=opt_type,
        strike_price=strike,
        expiration_date="2025-03-21",
        greeks=OptionGreeks(
            price=Decimal("2.00"),
            implied_volatility=Decimal("0.25"),
            delta=delta,
            gamma=Decimal("0.01"),
            theta=Decimal("-0.05"),
            rho=Decimal("0.005"),
            vega=Decimal("0.10"),
        ),
    )


class TestFindStrikeByDelta:
    def test_finds_closest_delta(self):
        chain = [
            _make_contract(Decimal("440"), Decimal("-0.40"), OptionType.PUT),
            _make_contract(Decimal("445"), Decimal("-0.32"), OptionType.PUT),
            _make_contract(Decimal("450"), Decimal("-0.25"), OptionType.PUT),
        ]
        result = find_strike_by_delta(chain, Decimal("-0.30"), OptionType.PUT)
        assert result is not None
        assert result.strike_price == Decimal("445")

    def test_empty_chain(self):
        assert find_strike_by_delta([], Decimal("-0.30"), OptionType.PUT) is None

    def test_no_greeks(self):
        chain = [
            OptionContract(
                underlying="SPY",
                option_type=OptionType.PUT,
                strike_price=Decimal("450"),
                expiration_date="2025-03-21",
            )
        ]
        assert find_strike_by_delta(chain, Decimal("-0.30"), OptionType.PUT) is None

    def test_filters_by_option_type(self):
        chain = [
            _make_contract(Decimal("450"), Decimal("-0.30"), OptionType.PUT),
            _make_contract(Decimal("460"), Decimal("0.30"), OptionType.CALL),
        ]
        result = find_strike_by_delta(chain, Decimal("0.30"), OptionType.CALL)
        assert result is not None
        assert result.strike_price == Decimal("460")
