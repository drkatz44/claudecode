"""Tests for Black-Scholes pricing and Greeks."""

import math
import pytest

from market_agent.analysis.black_scholes import (
    bs_delta, bs_gamma, bs_greeks, bs_iv, bs_price, bs_theta, bs_vega,
    _norm_cdf, _norm_pdf,
)

# Standard test case: S=100, K=100, T=0.25 (91 days), r=0.05, sigma=0.20
S, K, T, r, sig = 100.0, 100.0, 0.25, 0.05, 0.20


class TestNormFunctions:
    def test_norm_cdf_symmetry(self):
        assert abs(_norm_cdf(0) - 0.5) < 1e-6

    def test_norm_cdf_bounds(self):
        assert _norm_cdf(-10) < 0.0001
        assert _norm_cdf(10) > 0.9999

    def test_norm_cdf_known(self):
        # N(1.96) ≈ 0.975
        assert abs(_norm_cdf(1.96) - 0.975) < 0.001

    def test_norm_pdf_max_at_zero(self):
        assert _norm_pdf(0) > _norm_pdf(1)
        assert abs(_norm_pdf(0) - 1 / math.sqrt(2 * math.pi)) < 1e-8


class TestBsPrice:
    def test_atm_call_positive(self):
        price = bs_price(S, K, T, r, sig, "call")
        assert price > 0

    def test_put_call_parity(self):
        call = bs_price(S, K, T, r, sig, "call")
        put = bs_price(S, K, T, r, sig, "put")
        # C - P = S - K * exp(-rT)
        lhs = call - put
        rhs = S - K * math.exp(-r * T)
        assert abs(lhs - rhs) < 0.01

    def test_deep_itm_call(self):
        # Deep ITM call ≈ intrinsic value
        price = bs_price(150, 100, T, r, sig, "call")
        assert price > 49  # > intrinsic (100% of $50 + time value)

    def test_zero_time(self):
        # At expiry, price = intrinsic
        assert bs_price(105, 100, 0, r, sig, "call") == pytest.approx(5.0)
        assert bs_price(95, 100, 0, r, sig, "put") == pytest.approx(5.0)
        assert bs_price(95, 100, 0, r, sig, "call") == 0.0

    def test_zero_sigma(self):
        assert bs_price(S, K, T, r, 0, "call") == 0.0

    def test_known_value(self):
        # Black-Scholes ATM 91-day call: ~$4.76 at these params
        price = bs_price(100, 100, 0.25, 0.05, 0.20, "call")
        assert 4.0 < price < 6.0


class TestBsDelta:
    def test_atm_call_delta_near_half(self):
        delta = bs_delta(S, K, T, r, sig, "call")
        assert 0.45 < delta < 0.65  # Should be ~0.55 with drift

    def test_atm_put_delta_near_neg_half(self):
        delta = bs_delta(S, K, T, r, sig, "put")
        assert -0.65 < delta < -0.35  # Drift shifts ATM put above -0.5

    def test_call_put_delta_sum(self):
        # Call delta - Put delta = 1
        call_d = bs_delta(S, K, T, r, sig, "call")
        put_d = bs_delta(S, K, T, r, sig, "put")
        assert abs(call_d + abs(put_d) - 1.0) < 0.01

    def test_deep_itm_call_delta(self):
        delta = bs_delta(150, 100, T, r, sig, "call")
        assert delta > 0.9

    def test_deep_otm_call_delta(self):
        delta = bs_delta(50, 100, T, r, sig, "call")
        assert delta < 0.05

    def test_zero_time(self):
        assert bs_delta(105, 100, 0, r, sig, "call") == 1.0
        assert bs_delta(95, 100, 0, r, sig, "call") == 0.0


class TestBsGamma:
    def test_atm_gamma_positive(self):
        assert bs_gamma(S, K, T, r, sig) > 0

    def test_gamma_highest_atm(self):
        atm = bs_gamma(100, 100, T, r, sig)
        itm = bs_gamma(130, 100, T, r, sig)
        otm = bs_gamma(70, 100, T, r, sig)
        assert atm > itm
        assert atm > otm

    def test_zero_time(self):
        assert bs_gamma(S, K, 0, r, sig) == 0.0


class TestBsTheta:
    def test_theta_negative_for_long_options(self):
        # Theta should be negative (options lose value over time)
        theta_call = bs_theta(S, K, T, r, sig, "call")
        theta_put = bs_theta(S, K, T, r, sig, "put")
        assert theta_call < 0
        assert theta_put < 0

    def test_theta_magnitude_reasonable(self):
        # ATM 90-day option with sig=20% should have daily decay ~$0.02-$0.05 on $4-5 option
        theta = abs(bs_theta(100, 100, 90 / 365, 0.05, 0.20, "call"))
        assert 0.01 < theta < 0.10


class TestBsVega:
    def test_vega_positive(self):
        assert bs_vega(S, K, T, r, sig) > 0

    def test_vega_per_percent(self):
        # Vega should be change in price for 1% vol change
        price_base = bs_price(S, K, T, r, sig, "call")
        price_up = bs_price(S, K, T, r, sig + 0.01, "call")
        numerical_vega = price_up - price_base
        analytic_vega = bs_vega(S, K, T, r, sig)
        assert abs(numerical_vega - analytic_vega) < 0.001


class TestBsIv:
    def test_round_trip(self):
        """IV(price(S,K,T,r,σ)) should return σ."""
        for sigma_true in [0.10, 0.20, 0.35, 0.60]:
            price = bs_price(S, K, T, r, sigma_true, "call")
            iv = bs_iv(price, S, K, T, r, "call")
            assert iv is not None
            assert abs(iv - sigma_true) < 1e-4, f"sigma_true={sigma_true}, iv={iv}"

    def test_put_round_trip(self):
        price = bs_price(S, K, T, r, 0.25, "put")
        iv = bs_iv(price, S, K, T, r, "put")
        assert iv is not None
        assert abs(iv - 0.25) < 1e-4

    def test_negative_price_returns_none(self):
        assert bs_iv(-1, S, K, T, r, "call") is None

    def test_zero_time_returns_none(self):
        assert bs_iv(5.0, S, K, 0, r, "call") is None

    def test_below_intrinsic_returns_none(self):
        # Price below intrinsic value is impossible
        assert bs_iv(0.001, 110, 100, T, r, "call") is None


class TestBsGreeks:
    def test_all_keys_present(self):
        g = bs_greeks(S, K, T, r, sig, "call")
        assert set(g.keys()) == {"price", "delta", "gamma", "theta", "vega"}

    def test_values_consistent(self):
        g = bs_greeks(S, K, T, r, sig, "call")
        assert g["price"] == pytest.approx(bs_price(S, K, T, r, sig, "call"))
        assert g["delta"] == pytest.approx(bs_delta(S, K, T, r, sig, "call"))
