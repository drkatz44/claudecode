"""Tests for options analysis module (mocked data)."""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from market_agent.analysis.options import (
    iv_rank,
    iv_percentile,
    put_call_oi_ratio,
    iv_skew,
    find_strike_by_delta,
    find_optimal_expiry,
    resolve_strategy,
    _find_wing,
    _resolve_short_put,
    _resolve_strangle,
    _resolve_iron_condor,
    _resolve_vertical_spread,
)
from market_agent.data.models import OptionQuote
from conftest import generate_bars


# --- Fixtures ---

def _make_option(strike, option_type, bid, ask, iv=None, oi=100, volume=50):
    """Create a synthetic OptionQuote with ~35 DTE expiry (future-dated)."""
    from datetime import date
    expiry = datetime.now() + timedelta(days=35)
    return OptionQuote(
        symbol=f"AAPL{expiry.strftime('%y%m%d')}{option_type[0].upper()}{int(strike*1000):08d}",
        underlying="AAPL",
        strike=Decimal(str(strike)),
        expiration=expiry,
        option_type=option_type,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        last=Decimal(str(round((bid + ask) / 2, 2))),
        volume=volume,
        open_interest=oi,
        iv=Decimal(str(iv)) if iv is not None else None,
    )


def _make_chain(underlying_price=100.0, strikes_below=5, strikes_above=5, strike_width=5):
    """Build a synthetic option chain around underlying_price."""
    chain = []
    for i in range(-strikes_below, strikes_above + 1):
        strike = underlying_price + i * strike_width
        if strike <= 0:
            continue
        distance = abs(i) * strike_width / underlying_price

        # IV smile: higher for further OTM, puts slightly higher
        base_iv = 0.25
        iv_put = base_iv + distance * 0.5 + 0.02
        iv_call = base_iv + distance * 0.4

        # Bid/ask: ATM options worth more, further OTM worth less
        put_val = max(0.10, 5.0 - i * 1.2 if i < 0 else max(0.10, 1.0 - i * 0.3))
        call_val = max(0.10, 5.0 + i * 1.2 if i > 0 else max(0.10, 1.0 + i * 0.3))

        chain.append(_make_option(strike, "put", round(put_val * 0.95, 2),
                                  round(put_val * 1.05, 2), iv=round(iv_put, 4),
                                  oi=200 + i * 10))
        chain.append(_make_option(strike, "call", round(call_val * 0.95, 2),
                                  round(call_val * 1.05, 2), iv=round(iv_call, 4),
                                  oi=180 - i * 10))
    return chain


# --- IV Rank/Percentile ---

class TestIVRank:
    def test_returns_neutral_for_short_data(self):
        bars = generate_bars(50, trend="up")
        result = iv_rank(bars, 0.25, period=252)
        assert result == 50.0

    def test_high_iv_ranks_high(self):
        bars = generate_bars(300, trend="up", volatility=0.02)
        # Very high current IV should rank high
        result = iv_rank(bars, 0.80)
        assert result > 50.0

    def test_low_iv_ranks_low(self):
        bars = generate_bars(300, trend="flat", volatility=0.02)
        result = iv_rank(bars, 0.01)
        assert result < 50.0

    def test_clamped_0_100(self):
        bars = generate_bars(300, trend="up", volatility=0.02)
        # Extremely high IV
        result = iv_rank(bars, 5.0)
        assert result == 100.0
        # Extremely low IV
        result = iv_rank(bars, 0.0)
        assert result == 0.0


class TestIVPercentile:
    def test_returns_neutral_for_short_data(self):
        bars = generate_bars(50, trend="up")
        result = iv_percentile(bars, 0.25, period=252)
        assert result == 50.0

    def test_high_iv_percentile_high(self):
        bars = generate_bars(300, trend="flat", volatility=0.01)
        result = iv_percentile(bars, 1.0)
        assert result > 80.0

    def test_low_iv_percentile_low(self):
        bars = generate_bars(300, trend="flat", volatility=0.05)
        result = iv_percentile(bars, 0.001)
        assert result < 20.0


# --- Put/Call OI Ratio ---

class TestPutCallOIRatio:
    def test_equal_oi(self):
        chain = [
            _make_option(100, "call", 1.0, 1.1, oi=500),
            _make_option(95, "put", 1.0, 1.1, oi=500),
        ]
        assert put_call_oi_ratio(chain) == 1.0

    def test_more_puts(self):
        chain = [
            _make_option(100, "call", 1.0, 1.1, oi=100),
            _make_option(95, "put", 1.0, 1.1, oi=300),
        ]
        assert put_call_oi_ratio(chain) == 3.0

    def test_no_calls(self):
        chain = [_make_option(95, "put", 1.0, 1.1, oi=100)]
        result = put_call_oi_ratio(chain)
        assert result == float("inf")

    def test_empty_chain(self):
        assert put_call_oi_ratio([]) == 1.0


# --- IV Skew ---

class TestIVSkew:
    def test_put_skew(self):
        chain = _make_chain(100.0)
        result = iv_skew(chain, Decimal("100"))
        assert result["skew_direction"] in ("put_skew", "neutral", "call_skew")
        assert "magnitude" in result
        assert "avg_put_iv" in result
        assert "avg_call_iv" in result

    def test_zero_price(self):
        result = iv_skew([], Decimal("0"))
        assert result["skew_direction"] == "neutral"
        assert result["magnitude"] == 0.0

    def test_no_otm_options(self):
        # Chain with only ATM strikes
        chain = [
            _make_option(100, "call", 3.0, 3.2, iv=0.25),
            _make_option(100, "put", 3.0, 3.2, iv=0.25),
        ]
        result = iv_skew(chain, Decimal("100"))
        # No OTM options, both IVs should be 0
        assert result["avg_put_iv"] == 0.0
        assert result["avg_call_iv"] == 0.0


# --- Find Strike by Delta ---

class TestFindStrikeByDelta:
    def test_atm_put(self):
        chain = _make_chain(100.0)
        result = find_strike_by_delta(chain, 0.50, "put", Decimal("100"))
        assert result is not None
        # 0.50 delta ≈ ATM
        assert abs(float(result.strike) - 100.0) <= 10

    def test_otm_put(self):
        chain = _make_chain(100.0)
        result = find_strike_by_delta(chain, 0.16, "put", Decimal("100"))
        assert result is not None
        # 0.16 delta put should be below underlying
        assert float(result.strike) < 100.0

    def test_otm_call(self):
        chain = _make_chain(100.0)
        result = find_strike_by_delta(chain, 0.16, "call", Decimal("100"))
        assert result is not None
        # 0.16 delta call should be above underlying
        assert float(result.strike) > 100.0

    def test_no_candidates(self):
        result = find_strike_by_delta([], 0.30, "put", Decimal("100"))
        assert result is None

    def test_zero_price(self):
        chain = _make_chain(100.0)
        result = find_strike_by_delta(chain, 0.30, "put", Decimal("0"))
        assert result is None

    def test_far_otm(self):
        chain = _make_chain(100.0, strikes_below=10, strikes_above=10, strike_width=2)
        result = find_strike_by_delta(chain, 0.05, "put", Decimal("100"))
        assert result is not None
        # Should be well below underlying
        assert float(result.strike) < 90.0


# --- Find Optimal Expiry ---

class TestFindOptimalExpiry:
    def test_finds_midpoint(self):
        today = datetime.now().date()
        exps = [
            (today + timedelta(days=25)).strftime("%Y-%m-%d"),
            (today + timedelta(days=35)).strftime("%Y-%m-%d"),
            (today + timedelta(days=45)).strftime("%Y-%m-%d"),
            (today + timedelta(days=60)).strftime("%Y-%m-%d"),
        ]
        # DTE range 30-45, midpoint=37.5, closest is 35-day expiry
        result = find_optimal_expiry(exps, 30, 45)
        assert result == exps[1]

    def test_none_in_range(self):
        today = datetime.now().date()
        exps = [
            (today + timedelta(days=5)).strftime("%Y-%m-%d"),
            (today + timedelta(days=10)).strftime("%Y-%m-%d"),
        ]
        result = find_optimal_expiry(exps, 30, 45)
        assert result is None

    def test_empty_list(self):
        result = find_optimal_expiry([], 30, 45)
        assert result is None

    def test_single_expiry_in_range(self):
        today = datetime.now().date()
        exps = [(today + timedelta(days=40)).strftime("%Y-%m-%d")]
        result = find_optimal_expiry(exps, 30, 45)
        assert result == exps[0]

    def test_invalid_date_format_skipped(self):
        today = datetime.now().date()
        exps = [
            "not-a-date",
            (today + timedelta(days=35)).strftime("%Y-%m-%d"),
        ]
        result = find_optimal_expiry(exps, 30, 45)
        assert result == exps[1]


# --- Find Wing ---

class TestFindWing:
    def test_finds_lower_wing(self):
        puts = sorted([
            _make_option(90, "put", 0.5, 0.6),
            _make_option(95, "put", 1.0, 1.1),
            _make_option(100, "put", 2.0, 2.2),
            _make_option(105, "put", 3.5, 3.7),
        ], key=lambda q: q.strike)

        result = _find_wing(puts, Decimal("100"), -2)
        assert result is not None
        assert float(result.strike) == 90.0

    def test_finds_upper_wing(self):
        calls = sorted([
            _make_option(100, "call", 3.5, 3.7),
            _make_option(105, "call", 2.0, 2.2),
            _make_option(110, "call", 1.0, 1.1),
            _make_option(115, "call", 0.5, 0.6),
        ], key=lambda q: q.strike)

        result = _find_wing(calls, Decimal("105"), 2)
        assert result is not None
        assert float(result.strike) == 115.0

    def test_returns_none_at_boundary(self):
        puts = [_make_option(100, "put", 2.0, 2.2)]
        result = _find_wing(puts, Decimal("100"), -1)
        assert result is None

    def test_empty_list(self):
        result = _find_wing([], Decimal("100"), -1)
        assert result is None


# --- Strategy Resolution (unit tests with mock chain) ---

class TestResolveShortPut:
    def test_resolves(self):
        chain = _make_chain(100.0)
        result = _resolve_short_put(chain, Decimal("100"), 0.20, "2025-03-21", 30)
        assert result is not None
        assert result["expiration"] == "2025-03-21"
        assert result["dte"] == 30
        assert len(result["legs"]) == 1
        assert result["legs"][0]["type"] == "put"
        assert result["legs"][0]["side"] == "sell"
        assert result["credit"] > 0
        assert len(result["breakevens"]) == 1

    def test_returns_none_empty_chain(self):
        result = _resolve_short_put([], Decimal("100"), 0.20, "2025-03-21", 30)
        assert result is None


class TestResolveStrangle:
    def test_resolves(self):
        chain = _make_chain(100.0)
        result = _resolve_strangle(chain, Decimal("100"), 0.16, "2025-03-21", 30)
        assert result is not None
        assert len(result["legs"]) == 2
        types = {leg["type"] for leg in result["legs"]}
        assert types == {"put", "call"}
        assert all(leg["side"] == "sell" for leg in result["legs"])
        assert result["max_loss"] is None  # undefined risk
        assert len(result["breakevens"]) == 2


class TestResolveIronCondor:
    def test_resolves(self):
        chain = _make_chain(100.0, strikes_below=8, strikes_above=8, strike_width=5)
        result = _resolve_iron_condor(chain, Decimal("100"), 0.16, "2025-03-21", 30, width=2)
        assert result is not None
        assert len(result["legs"]) == 4
        sides = [leg["side"] for leg in result["legs"]]
        assert sides.count("buy") == 2
        assert sides.count("sell") == 2
        assert result["max_loss"] > 0
        assert len(result["breakevens"]) == 2

    def test_returns_none_narrow_chain(self):
        chain = [
            _make_option(100, "put", 2.0, 2.2),
            _make_option(100, "call", 2.0, 2.2),
        ]
        result = _resolve_iron_condor(chain, Decimal("100"), 0.16, "2025-03-21", 30, width=5)
        assert result is None


class TestResolveVerticalSpread:
    def test_resolves(self):
        chain = _make_chain(100.0, strikes_below=8, strikes_above=3, strike_width=5)
        result = _resolve_vertical_spread(chain, Decimal("100"), 0.20, "2025-03-21", 30, width=2)
        assert result is not None
        assert len(result["legs"]) == 2
        assert result["legs"][0]["side"] == "buy"
        assert result["legs"][1]["side"] == "sell"
        assert result["max_loss"] > 0
        assert len(result["breakevens"]) == 1


# --- Full resolve_strategy with mocked fetcher ---

class TestResolveStrategyIntegration:
    @patch("market_agent.analysis.options.get_option_chain")
    @patch("market_agent.analysis.options.get_expirations")
    def test_short_put_integration(self, mock_exp, mock_chain):
        today = datetime.now().date()
        expiry = (today + timedelta(days=35)).strftime("%Y-%m-%d")
        mock_exp.return_value = [expiry]
        mock_chain.return_value = _make_chain(150.0)

        result = resolve_strategy("AAPL", "short_put", Decimal("150"),
                                  delta_target=0.20, dte_range=(30, 45))
        assert result is not None
        assert result["expiration"] == expiry
        assert len(result["legs"]) == 1

    @patch("market_agent.analysis.options.get_option_chain")
    @patch("market_agent.analysis.options.get_expirations")
    def test_unknown_strategy(self, mock_exp, mock_chain):
        today = datetime.now().date()
        expiry = (today + timedelta(days=35)).strftime("%Y-%m-%d")
        mock_exp.return_value = [expiry]
        mock_chain.return_value = _make_chain(100.0)

        result = resolve_strategy("AAPL", "butterfly", Decimal("100"))
        assert result is None

    @patch("market_agent.analysis.options.get_expirations")
    def test_no_expirations(self, mock_exp):
        mock_exp.return_value = []
        result = resolve_strategy("AAPL", "short_put", Decimal("100"))
        assert result is None

    @patch("market_agent.analysis.options.get_option_chain")
    @patch("market_agent.analysis.options.get_expirations")
    def test_empty_chain(self, mock_exp, mock_chain):
        today = datetime.now().date()
        expiry = (today + timedelta(days=35)).strftime("%Y-%m-%d")
        mock_exp.return_value = [expiry]
        mock_chain.return_value = []

        result = resolve_strategy("AAPL", "short_put", Decimal("100"))
        assert result is None
