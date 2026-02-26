"""Tests for chain_parser and chain_builder modules."""

from decimal import Decimal

import pytest

from tastytrade_strategy.chain_builder import (
    ChainBuilderError,
    build_iron_condor,
    build_short_put,
    build_strangle,
    build_vertical_spread,
)
from tastytrade_strategy.chain_parser import (
    find_expiration_by_dte,
    parse_greeks_response,
    parse_nested_chain,
)
from tastytrade_strategy.models import Direction, OptionContract, OptionGreeks, OptionType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NESTED_CHAIN = {
    "data": {
        "items": [
            {
                "underlying-symbol": "SPY",
                "expirations": [
                    {
                        "expiration-date": "2024-03-15",
                        "days-to-expiration": 21,
                        "strikes": [
                            {"strike-price": "490.0", "call": "SPY   240315C00490000", "put": "SPY   240315P00490000"},
                            {"strike-price": "495.0", "call": "SPY   240315C00495000", "put": "SPY   240315P00495000"},
                            {"strike-price": "500.0", "call": "SPY   240315C00500000", "put": "SPY   240315P00500000"},
                            {"strike-price": "505.0", "call": "SPY   240315C00505000", "put": "SPY   240315P00505000"},
                            {"strike-price": "510.0", "call": "SPY   240315C00510000", "put": "SPY   240315P00510000"},
                        ],
                    },
                    {
                        "expiration-date": "2024-04-19",
                        "days-to-expiration": 56,
                        "strikes": [
                            {"strike-price": "485.0", "call": "SPY   240419C00485000", "put": "SPY   240419P00485000"},
                            {"strike-price": "495.0", "call": "SPY   240419C00495000", "put": "SPY   240419P00495000"},
                            {"strike-price": "500.0", "call": "SPY   240419C00500000", "put": "SPY   240419P00500000"},
                            {"strike-price": "505.0", "call": "SPY   240419C00505000", "put": "SPY   240419P00505000"},
                            {"strike-price": "515.0", "call": "SPY   240419C00515000", "put": "SPY   240419P00515000"},
                        ],
                    },
                ],
            }
        ]
    }
}

GREEKS_RESPONSE = [
    # Puts: OTM → ITM (490 furthest OTM, 510 deepest ITM)
    {"symbol": "SPY   240315P00490000", "delta": -0.08, "gamma": 0.01, "theta": -0.03, "rho": -0.002, "vega": 0.08, "volatility": 0.24, "price": 0.75},
    {"symbol": "SPY   240315P00495000", "delta": -0.16, "gamma": 0.02, "theta": -0.05, "rho": -0.003, "vega": 0.12, "volatility": 0.22, "price": 1.50},
    {"symbol": "SPY   240315P00500000", "delta": -0.30, "gamma": 0.03, "theta": -0.08, "rho": -0.005, "vega": 0.18, "volatility": 0.20, "price": 3.20},
    {"symbol": "SPY   240315P00505000", "delta": -0.50, "gamma": 0.03, "theta": -0.10, "rho": -0.007, "vega": 0.20, "volatility": 0.20, "price": 6.00},
    {"symbol": "SPY   240315P00510000", "delta": -0.70, "gamma": 0.02, "theta": -0.12, "rho": -0.009, "vega": 0.15, "volatility": 0.22, "price": 10.50},
    # Calls: ITM → OTM (490 deepest ITM, 510 furthest OTM)
    {"symbol": "SPY   240315C00490000", "delta": 0.70, "gamma": 0.02, "theta": -0.12, "rho": 0.009, "vega": 0.15, "volatility": 0.22, "price": 11.00},
    {"symbol": "SPY   240315C00495000", "delta": 0.50, "gamma": 0.03, "theta": -0.10, "rho": 0.007, "vega": 0.20, "volatility": 0.20, "price": 7.00},
    {"symbol": "SPY   240315C00500000", "delta": 0.30, "gamma": 0.03, "theta": -0.08, "rho": 0.005, "vega": 0.18, "volatility": 0.20, "price": 3.50},
    {"symbol": "SPY   240315C00505000", "delta": 0.16, "gamma": 0.02, "theta": -0.05, "rho": 0.003, "vega": 0.12, "volatility": 0.22, "price": 1.60},
    {"symbol": "SPY   240315C00510000", "delta": 0.08, "gamma": 0.01, "theta": -0.03, "rho": 0.002, "vega": 0.08, "volatility": 0.24, "price": 0.80},
]


# ---------------------------------------------------------------------------
# find_expiration_by_dte
# ---------------------------------------------------------------------------

class TestFindExpirationByDte:
    def test_finds_closest_dte(self):
        expirations = [
            {"expiration-date": "2024-03-15", "days-to-expiration": 21},
            {"expiration-date": "2024-04-19", "days-to-expiration": 56},
            {"expiration-date": "2024-05-17", "days-to-expiration": 84},
        ]
        result = find_expiration_by_dte(expirations, 45)
        assert result["expiration-date"] == "2024-04-19"

    def test_exact_dte_match(self):
        expirations = [
            {"expiration-date": "2024-03-15", "days-to-expiration": 21},
            {"expiration-date": "2024-04-19", "days-to-expiration": 45},
        ]
        result = find_expiration_by_dte(expirations, 45)
        assert result["expiration-date"] == "2024-04-19"

    def test_empty_returns_none(self):
        assert find_expiration_by_dte([], 45) is None


# ---------------------------------------------------------------------------
# parse_greeks_response
# ---------------------------------------------------------------------------

class TestParseGreeksResponse:
    def test_parses_list(self):
        result = parse_greeks_response(GREEKS_RESPONSE)
        assert "SPY   240315P00490000" in result
        g = result["SPY   240315P00490000"]
        assert g.delta == Decimal("-0.08")
        assert g.price == Decimal("0.75")

    def test_parses_api_envelope(self):
        envelope = {"data": {"items": GREEKS_RESPONSE}}
        result = parse_greeks_response(envelope)
        assert len(result) == len(GREEKS_RESPONSE)

    def test_missing_required_fields_skipped(self):
        partial = [{"symbol": "SPY   240315P00490000", "delta": -0.35}]
        result = parse_greeks_response(partial)
        assert len(result) == 0  # missing price, gamma, theta, etc.

    def test_empty_returns_empty(self):
        assert parse_greeks_response([]) == {}


# ---------------------------------------------------------------------------
# parse_nested_chain
# ---------------------------------------------------------------------------

class TestParseNestedChain:
    def test_parses_full_response(self):
        contracts, expiration_date = parse_nested_chain(NESTED_CHAIN, target_dte=21)
        assert expiration_date == "2024-03-15"
        assert len(contracts) == 10  # 5 strikes × 2 sides

    def test_selects_closest_dte(self):
        contracts, exp = parse_nested_chain(NESTED_CHAIN, target_dte=45)
        assert exp == "2024-04-19"

    def test_attaches_greeks(self):
        greeks_map = parse_greeks_response(GREEKS_RESPONSE)
        contracts, _ = parse_nested_chain(NESTED_CHAIN, target_dte=21, greeks_map=greeks_map)
        puts = [c for c in contracts if c.option_type == OptionType.PUT and c.greeks is not None]
        assert len(puts) > 0
        assert puts[0].greeks is not None

    def test_contracts_without_greeks_when_no_map(self):
        contracts, _ = parse_nested_chain(NESTED_CHAIN, target_dte=21)
        assert all(c.greeks is None for c in contracts)

    def test_empty_response_returns_empty(self):
        contracts, exp = parse_nested_chain({})
        assert contracts == []
        assert exp is None


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def _make_chain_with_greeks() -> tuple[list[OptionContract], str]:
    greeks_map = parse_greeks_response(GREEKS_RESPONSE)
    contracts, exp = parse_nested_chain(NESTED_CHAIN, target_dte=21, greeks_map=greeks_map)
    return contracts, exp or "2024-03-15"


# ---------------------------------------------------------------------------
# build_short_put
# ---------------------------------------------------------------------------

class TestBuildShortPut:
    def test_builds_correctly(self):
        chain, exp = _make_chain_with_greeks()
        result = build_short_put(chain, "SPY", exp, target_delta=Decimal("0.30"))
        assert result["strategy_type"] == "short_put"
        assert result["underlying"] == "SPY"
        assert len(result["legs"]) == 1
        assert result["legs"][0]["action"] == "Sell to Open"
        assert result["risk"]["max_profit"] > 0

    def test_raises_on_no_greeks(self):
        contracts, exp = parse_nested_chain(NESTED_CHAIN, target_dte=21)
        with pytest.raises(ChainBuilderError):
            build_short_put(contracts, "SPY", exp or "", target_delta=Decimal("0.30"))


# ---------------------------------------------------------------------------
# build_vertical_spread
# ---------------------------------------------------------------------------

class TestBuildVerticalSpread:
    def test_builds_bull_put(self):
        chain, exp = _make_chain_with_greeks()
        result = build_vertical_spread(
            chain, "SPY", exp,
            option_type=OptionType.PUT, direction=Direction.BULLISH,
            short_delta=Decimal("0.30"), long_delta=Decimal("0.08"),
        )
        assert result["strategy_type"] == "vertical_spread"
        assert len(result["legs"]) == 2
        assert result["short_strike"] != result["long_strike"]

    def test_raises_when_strikes_same(self):
        chain, exp = _make_chain_with_greeks()
        with pytest.raises(ChainBuilderError, match="same"):
            build_vertical_spread(
                chain, "SPY", exp,
                option_type=OptionType.PUT, direction=Direction.BULLISH,
                short_delta=Decimal("0.30"), long_delta=Decimal("0.30"),
            )


# ---------------------------------------------------------------------------
# build_iron_condor
# ---------------------------------------------------------------------------

class TestBuildIronCondor:
    def test_builds_correctly(self):
        chain, exp = _make_chain_with_greeks()
        result = build_iron_condor(
            chain, "SPY", exp,
            put_short_delta=Decimal("0.30"),
            put_long_delta=Decimal("0.15"),
            call_short_delta=Decimal("0.30"),
            call_long_delta=Decimal("0.15"),
        )
        assert result["strategy_type"] == "iron_condor"
        assert len(result["legs"]) == 4
        assert result["credit"] is not None
        assert result["put_strikes"]["short"] > result["put_strikes"]["long"]
        assert result["call_strikes"]["long"] > result["call_strikes"]["short"]

    def test_risk_profile_populated(self):
        chain, exp = _make_chain_with_greeks()
        result = build_iron_condor(chain, "SPY", exp)
        assert result["risk"]["max_profit"] > 0
        assert result["risk"]["max_loss"] > 0
        assert len(result["risk"]["breakevens"]) == 2


# ---------------------------------------------------------------------------
# build_strangle
# ---------------------------------------------------------------------------

class TestBuildStrangle:
    def test_builds_correctly(self):
        chain, exp = _make_chain_with_greeks()
        result = build_strangle(
            chain, "SPY", exp,
            put_delta=Decimal("0.20"), call_delta=Decimal("0.20"),
        )
        assert result["strategy_type"] == "strangle"
        assert len(result["legs"]) == 2
        assert result["put_strike"] < result["call_strike"]
        actions = {leg["action"] for leg in result["legs"]}
        assert actions == {"Sell to Open"}
