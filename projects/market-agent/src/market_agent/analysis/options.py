"""Options chain analysis — IV rank, skew, strike selection, strategy resolution.

Uses yfinance options data (no Greeks available — delta approximated via moneyness).
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import pandas as pd

from ..analysis.technical import historical_volatility, bars_to_df
from ..data.fetcher import get_bars, get_expirations, get_option_chain
from ..data.models import Bar, OptionQuote


def iv_rank(bars: list[Bar], current_iv: float, period: int = 252) -> float:
    """Calculate IV rank: where current IV sits in the historical range.

    IV Rank = (current_iv - min_HV) / (max_HV - min_HV) * 100

    Uses historical volatility from price bars as proxy for IV range.
    Returns 0-100.
    """
    if len(bars) < period:
        return 50.0  # insufficient data, return neutral

    hv = historical_volatility(bars, period=20)
    valid_hv = hv.dropna()
    if len(valid_hv) < 20:
        return 50.0

    hv_min = float(valid_hv.min())
    hv_max = float(valid_hv.max())
    hv_range = hv_max - hv_min

    if hv_range <= 0:
        return 50.0

    rank = (current_iv - hv_min) / hv_range * 100
    return max(0.0, min(100.0, rank))


def iv_percentile(bars: list[Bar], current_iv: float, period: int = 252) -> float:
    """Calculate IV percentile: % of days historical vol was below current IV.

    Returns 0-100.
    """
    if len(bars) < period:
        return 50.0

    hv = historical_volatility(bars, period=20)
    valid_hv = hv.dropna()
    if len(valid_hv) < 20:
        return 50.0

    below = (valid_hv < current_iv).sum()
    return float(below / len(valid_hv) * 100)


def put_call_oi_ratio(chain: list[OptionQuote]) -> float:
    """Calculate put/call open interest ratio.

    > 1.0 = more put OI (bearish sentiment or hedging)
    < 1.0 = more call OI (bullish sentiment)
    """
    call_oi = sum(q.open_interest for q in chain if q.option_type == "call")
    put_oi = sum(q.open_interest for q in chain if q.option_type == "put")

    if call_oi == 0:
        return float("inf") if put_oi > 0 else 1.0
    return put_oi / call_oi


def iv_skew(chain: list[OptionQuote], underlying_price: Decimal) -> dict:
    """Analyze implied volatility skew between puts and calls.

    Compares average IV of OTM puts vs OTM calls at similar distances from ATM.

    Returns dict with:
        - skew_direction: "put_skew", "call_skew", or "neutral"
        - magnitude: absolute IV difference in percentage points
        - avg_put_iv: average OTM put IV
        - avg_call_iv: average OTM call IV
    """
    price = float(underlying_price)
    if price <= 0:
        return {"skew_direction": "neutral", "magnitude": 0.0, "avg_put_iv": 0.0, "avg_call_iv": 0.0}

    # OTM options within 3-10% of underlying
    otm_puts = [q for q in chain
                if q.option_type == "put" and q.iv
                and 0.90 * price <= float(q.strike) < price]
    otm_calls = [q for q in chain
                 if q.option_type == "call" and q.iv
                 and price < float(q.strike) <= 1.10 * price]

    avg_put_iv = sum(float(q.iv) for q in otm_puts) / len(otm_puts) if otm_puts else 0.0
    avg_call_iv = sum(float(q.iv) for q in otm_calls) / len(otm_calls) if otm_calls else 0.0

    diff = avg_put_iv - avg_call_iv

    if abs(diff) < 0.02:
        direction = "neutral"
    elif diff > 0:
        direction = "put_skew"
    else:
        direction = "call_skew"

    return {
        "skew_direction": direction,
        "magnitude": round(abs(diff) * 100, 2),  # percentage points
        "avg_put_iv": round(avg_put_iv * 100, 2),
        "avg_call_iv": round(avg_call_iv * 100, 2),
    }


def find_strike_by_delta(
    chain: list[OptionQuote],
    target_delta: float,
    option_type: str,
    underlying_price: Decimal,
) -> Optional[OptionQuote]:
    """Find the strike closest to target delta using moneyness approximation.

    Delta approximation via OTM percentage (yfinance has no Greeks):
        - 0.50 delta ≈ ATM
        - 0.30 delta ≈ 5% OTM
        - 0.20 delta ≈ 7% OTM
        - 0.16 delta ≈ 8-10% OTM
        - 0.10 delta ≈ 12% OTM

    Args:
        chain: Option chain
        target_delta: Target delta (0-1, always positive)
        option_type: "call" or "put"
        underlying_price: Current underlying price
    """
    price = float(underlying_price)
    if price <= 0:
        return None

    # Map delta to approximate OTM percentage
    # Using a simple linear interpolation
    delta_to_otm = {0.50: 0.0, 0.40: 0.02, 0.30: 0.05, 0.25: 0.06,
                    0.20: 0.07, 0.16: 0.09, 0.10: 0.12, 0.05: 0.18}

    # Interpolate target OTM %
    deltas = sorted(delta_to_otm.keys(), reverse=True)
    target_otm = None
    for i, d in enumerate(deltas):
        if target_delta >= d:
            if i == 0:
                target_otm = delta_to_otm[d]
            else:
                # Linear interpolation
                d_high = deltas[i - 1]
                d_low = d
                otm_high = delta_to_otm[d_high]
                otm_low = delta_to_otm[d_low]
                frac = (target_delta - d_low) / (d_high - d_low) if d_high != d_low else 0
                target_otm = otm_low + frac * (otm_high - otm_low)
            break
    if target_otm is None:
        target_otm = 0.20  # very far OTM

    # Calculate target strike
    if option_type == "put":
        target_strike = price * (1 - target_otm)
    else:
        target_strike = price * (1 + target_otm)

    # Find closest matching option
    candidates = [q for q in chain if q.option_type == option_type and float(q.bid) > 0]
    if not candidates:
        return None

    return min(candidates, key=lambda q: abs(float(q.strike) - target_strike))


def find_optimal_expiry(
    expirations: list[str],
    dte_min: int,
    dte_max: int,
) -> Optional[str]:
    """Find expiration date within DTE range, preferring middle of range.

    Args:
        expirations: List of expiration date strings (YYYY-MM-DD)
        dte_min: Minimum days to expiration
        dte_max: Maximum days to expiration

    Returns:
        Best expiration string, or None if none in range.
    """
    today = datetime.now().date()
    target_dte = (dte_min + dte_max) / 2
    best = None
    best_dist = float("inf")

    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp_date - today).days
        if dte_min <= dte <= dte_max:
            dist = abs(dte - target_dte)
            if dist < best_dist:
                best = exp_str
                best_dist = dist

    return best


def resolve_strategy(
    symbol: str,
    strategy_type: str,
    underlying_price: Decimal,
    delta_target: float = 0.16,
    dte_range: tuple[int, int] = (30, 45),
    width: Optional[int] = None,
) -> Optional[dict]:
    """Resolve abstract strategy parameters into concrete strikes and pricing.

    Args:
        symbol: Underlying ticker
        strategy_type: "short_put", "iron_condor", "strangle", "vertical_spread"
        underlying_price: Current underlying price
        delta_target: Target delta for short strikes
        dte_range: (min_dte, max_dte) range
        width: Spread width in strike units (for condors/verticals)

    Returns:
        Dict with expiration, dte, legs, credit, max_loss, breakevens.
        None if chain data unavailable.
    """
    expirations = get_expirations(symbol)
    if not expirations:
        return None

    expiry = find_optimal_expiry(expirations, dte_range[0], dte_range[1])
    if not expiry:
        # Fall back to nearest available
        expiry = expirations[0] if expirations else None
        if not expiry:
            return None

    chain = get_option_chain(symbol, expiry)
    if not chain:
        return None

    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    dte = (exp_date - datetime.now().date()).days

    if strategy_type == "short_put":
        return _resolve_short_put(chain, underlying_price, delta_target, expiry, dte)
    elif strategy_type == "iron_condor":
        return _resolve_iron_condor(chain, underlying_price, delta_target, expiry, dte, width or 5)
    elif strategy_type == "strangle":
        return _resolve_strangle(chain, underlying_price, delta_target, expiry, dte)
    elif strategy_type == "vertical_spread":
        return _resolve_vertical_spread(chain, underlying_price, delta_target, expiry, dte, width or 5)
    else:
        return None


def _resolve_short_put(chain, underlying_price, delta, expiry, dte):
    strike = find_strike_by_delta(chain, delta, "put", underlying_price)
    if not strike:
        return None

    mid = (strike.bid + strike.ask) / 2
    return {
        "expiration": expiry,
        "dte": dte,
        "legs": [{"strike": float(strike.strike), "type": "put", "side": "sell",
                  "bid": float(strike.bid), "ask": float(strike.ask)}],
        "credit": float(mid),
        "max_loss": float(strike.strike - mid),
        "breakevens": [float(strike.strike - mid)],
    }


def _resolve_iron_condor(chain, underlying_price, delta, expiry, dte, width):
    short_put = find_strike_by_delta(chain, delta, "put", underlying_price)
    short_call = find_strike_by_delta(chain, delta, "call", underlying_price)

    if not short_put or not short_call:
        return None

    # Find long wings (further OTM by width strikes)
    puts = sorted([q for q in chain if q.option_type == "put"], key=lambda q: q.strike)
    calls = sorted([q for q in chain if q.option_type == "call"], key=lambda q: q.strike)

    long_put = _find_wing(puts, short_put.strike, -width)
    long_call = _find_wing(calls, short_call.strike, width)

    if not long_put or not long_call:
        return None

    credit = float(
        (short_put.bid + short_call.bid - long_put.ask - long_call.ask) / 2 +
        (short_put.ask + short_call.ask - long_put.bid - long_call.bid) / 2
    ) / 2  # midpoint of credit

    put_width = float(short_put.strike - long_put.strike)
    call_width = float(long_call.strike - short_call.strike)
    max_width = max(put_width, call_width)
    max_loss = max_width - credit if credit > 0 else max_width

    return {
        "expiration": expiry,
        "dte": dte,
        "legs": [
            {"strike": float(long_put.strike), "type": "put", "side": "buy",
             "bid": float(long_put.bid), "ask": float(long_put.ask)},
            {"strike": float(short_put.strike), "type": "put", "side": "sell",
             "bid": float(short_put.bid), "ask": float(short_put.ask)},
            {"strike": float(short_call.strike), "type": "call", "side": "sell",
             "bid": float(short_call.bid), "ask": float(short_call.ask)},
            {"strike": float(long_call.strike), "type": "call", "side": "buy",
             "bid": float(long_call.bid), "ask": float(long_call.ask)},
        ],
        "credit": round(credit, 2),
        "max_loss": round(max_loss, 2),
        "breakevens": [
            round(float(short_put.strike) - credit, 2),
            round(float(short_call.strike) + credit, 2),
        ],
    }


def _resolve_strangle(chain, underlying_price, delta, expiry, dte):
    short_put = find_strike_by_delta(chain, delta, "put", underlying_price)
    short_call = find_strike_by_delta(chain, delta, "call", underlying_price)

    if not short_put or not short_call:
        return None

    credit = float(
        (short_put.bid + short_call.bid) / 2 +
        (short_put.ask + short_call.ask) / 2
    ) / 2

    return {
        "expiration": expiry,
        "dte": dte,
        "legs": [
            {"strike": float(short_put.strike), "type": "put", "side": "sell",
             "bid": float(short_put.bid), "ask": float(short_put.ask)},
            {"strike": float(short_call.strike), "type": "call", "side": "sell",
             "bid": float(short_call.bid), "ask": float(short_call.ask)},
        ],
        "credit": round(credit, 2),
        "max_loss": None,  # undefined risk
        "breakevens": [
            round(float(short_put.strike) - credit, 2),
            round(float(short_call.strike) + credit, 2),
        ],
    }


def _resolve_vertical_spread(chain, underlying_price, delta, expiry, dte, width):
    """Resolve a put credit spread (bull put spread)."""
    short_put = find_strike_by_delta(chain, delta, "put", underlying_price)
    if not short_put:
        return None

    puts = sorted([q for q in chain if q.option_type == "put"], key=lambda q: q.strike)
    long_put = _find_wing(puts, short_put.strike, -width)
    if not long_put:
        return None

    credit = float((short_put.bid - long_put.ask) + (short_put.ask - long_put.bid)) / 2
    spread_width = float(short_put.strike - long_put.strike)
    max_loss = spread_width - credit if credit > 0 else spread_width

    return {
        "expiration": expiry,
        "dte": dte,
        "legs": [
            {"strike": float(long_put.strike), "type": "put", "side": "buy",
             "bid": float(long_put.bid), "ask": float(long_put.ask)},
            {"strike": float(short_put.strike), "type": "put", "side": "sell",
             "bid": float(short_put.bid), "ask": float(short_put.ask)},
        ],
        "credit": round(credit, 2),
        "max_loss": round(max_loss, 2),
        "breakevens": [round(float(short_put.strike) - credit, 2)],
    }


def _find_wing(sorted_options: list[OptionQuote], anchor_strike: Decimal, offset: int) -> Optional[OptionQuote]:
    """Find an option approximately 'offset' strike widths from anchor.

    offset < 0 = lower strikes, offset > 0 = higher strikes.
    """
    if not sorted_options:
        return None

    # Find index of anchor
    anchor_idx = None
    for i, q in enumerate(sorted_options):
        if q.strike == anchor_strike:
            anchor_idx = i
            break

    if anchor_idx is None:
        # Find closest
        anchor_idx = min(range(len(sorted_options)),
                         key=lambda i: abs(sorted_options[i].strike - anchor_strike))

    target_idx = anchor_idx + offset
    target_idx = max(0, min(len(sorted_options) - 1, target_idx))

    if target_idx == anchor_idx:
        return None

    return sorted_options[target_idx]


def options_summary(symbol: str) -> Optional[dict]:
    """Generate a comprehensive options summary for a symbol.

    Returns dict with IV rank, skew, put/call ratio, and nearest chain info.
    """
    bars = get_bars(symbol, period="1y")
    if not bars or len(bars) < 50:
        return None

    chain = get_option_chain(symbol)
    if not chain:
        return None

    # Get ATM IV as representative current IV
    price = float(bars[-1].close)
    atm_options = [q for q in chain if q.iv and abs(float(q.strike) - price) / price < 0.03]
    if not atm_options:
        return None

    current_iv = sum(float(q.iv) for q in atm_options) / len(atm_options)

    return {
        "symbol": symbol,
        "underlying_price": price,
        "iv_rank": round(iv_rank(bars, current_iv), 1),
        "iv_percentile": round(iv_percentile(bars, current_iv), 1),
        "current_iv": round(current_iv * 100, 1),
        "put_call_oi_ratio": round(put_call_oi_ratio(chain), 2),
        "skew": iv_skew(chain, Decimal(str(price))),
        "expirations_count": len(get_expirations(symbol)),
        "chain_size": len(chain),
    }
