"""Black-Scholes option pricing, Greeks, and implied volatility solver.

Uses only the standard library (math) — no scipy dependency.
Normal CDF implemented via the complementary error function (math.erfc).

All functions use annualized inputs (T in years, sigma as decimal e.g. 0.25 = 25% vol).
"""

import math
from typing import Optional

# Risk-free rate used when none is provided (~current Fed funds proxy)
DEFAULT_RISK_FREE_RATE = 0.045


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function via erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    """Compute Black-Scholes d1 and d2 parameters."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes option price.

    Args:
        S: Underlying spot price
        K: Strike price
        T: Time to expiry in years (e.g., 30/365)
        r: Risk-free rate (annualized decimal, e.g., 0.05 = 5%)
        sigma: Implied volatility (annualized decimal, e.g., 0.25 = 25%)
        option_type: "call" or "put"

    Returns:
        Option price in same units as S and K.
    """
    if T <= 0:
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0 or S <= 0 or K <= 0:
        return 0.0

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = math.exp(-r * T)

    if option_type == "call":
        return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes delta.

    Returns:
        Delta in range [0, 1] for calls, [-1, 0] for puts.
    """
    if T <= 0 or sigma <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0

    d1, _ = _d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes gamma (identical for calls and puts).

    Returns:
        Gamma: rate of change of delta per unit price move.
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma)
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def bs_theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes theta in dollars per calendar day.

    Returns:
        Theta: typically negative — the option loses this value each day.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = math.exp(-r * T)
    sqrt_T = math.sqrt(T)

    decay_term = -S * _norm_pdf(d1) * sigma / (2 * sqrt_T)

    if option_type == "call":
        rate_term = -r * K * disc * _norm_cdf(d2)
    else:
        rate_term = r * K * disc * _norm_cdf(-d2)

    # Divide by 365 to get per calendar day
    return (decay_term + rate_term) / 365.0


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes vega: dollar change per 1% (0.01) move in implied vol.

    Returns:
        Vega per 1 percentage point change in IV (e.g., 25% → 26%).
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma)
    # Raw vega is per unit sigma; divide by 100 for per 1%
    return S * _norm_pdf(d1) * math.sqrt(T) * 0.01


def bs_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> Optional[float]:
    """Implied volatility via Newton-Raphson iteration.

    Args:
        market_price: Observed option mid price
        S: Underlying spot price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate
        option_type: "call" or "put"
        tol: Convergence tolerance in price units
        max_iter: Maximum iterations

    Returns:
        Implied volatility as decimal (e.g., 0.25 = 25%), or None if fails.
    """
    if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
        return None

    # Intrinsic value check
    intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    if market_price < intrinsic - tol:
        return None

    # Brenner-Subrahmanyam initial guess
    atm_approx = math.sqrt(2 * math.pi / T) * market_price / S
    sigma = max(0.01, min(atm_approx, 4.0))

    # Raw vega (dPrice/dSigma) for Newton-Raphson — uses sigma, not %
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, option_type)
        diff = price - market_price
        if abs(diff) < tol:
            return sigma

        # Raw vega = bs_vega * 100
        d1, _ = _d1_d2(S, K, T, r, sigma)
        raw_vega = S * _norm_pdf(d1) * math.sqrt(T)
        if raw_vega < 1e-10:
            break

        sigma -= diff / raw_vega
        sigma = max(0.001, min(sigma, 5.0))

    # Final check
    if 0.001 < sigma < 5.0:
        return sigma
    return None


def bs_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> dict:
    """Compute all Black-Scholes Greeks at once.

    Returns:
        Dict with price, delta, gamma, theta, vega.
    """
    return {
        "price": bs_price(S, K, T, r, sigma, option_type),
        "delta": bs_delta(S, K, T, r, sigma, option_type),
        "gamma": bs_gamma(S, K, T, r, sigma),
        "theta": bs_theta(S, K, T, r, sigma, option_type),
        "vega": bs_vega(S, K, T, r, sigma),
    }


def enrich_option_quote_greeks(
    quote,  # OptionQuote
    underlying_price: float,
    r: float = DEFAULT_RISK_FREE_RATE,
) -> None:
    """Compute and attach BS Greeks to an OptionQuote in-place.

    Only fills in fields that are currently None (respects broker-provided Greeks).

    Args:
        quote: OptionQuote instance to enrich
        underlying_price: Current spot price of the underlying
        r: Risk-free rate
    """
    from decimal import Decimal

    if not quote.iv or float(quote.iv) <= 0:
        return

    today = __import__("datetime").datetime.now().date()
    exp_date = quote.expiration.date() if hasattr(quote.expiration, "date") else quote.expiration
    T = max((exp_date - today).days / 365.0, 1 / 365.0)
    sigma = float(quote.iv)
    S = underlying_price
    K = float(quote.strike)

    if quote.delta is None:
        quote.delta = Decimal(str(round(bs_delta(S, K, T, r, sigma, quote.option_type), 4)))
    if quote.gamma is None:
        quote.gamma = Decimal(str(round(bs_gamma(S, K, T, r, sigma), 6)))
    if quote.theta is None:
        quote.theta = Decimal(str(round(bs_theta(S, K, T, r, sigma, quote.option_type), 4)))
    if quote.vega is None:
        quote.vega = Decimal(str(round(bs_vega(S, K, T, r, sigma), 4)))
