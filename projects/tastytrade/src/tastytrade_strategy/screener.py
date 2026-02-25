"""Opportunity screening and ranking.

Filters and scores symbols by IV rank, liquidity, and other criteria.
Input is a list of MarketMetrics (parsed from MCP get_market_metrics output).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .models import MarketMetrics, ScreenResult


class ScreenCriteria(BaseModel):
    """Criteria for screening symbols."""

    iv_rank_min: Decimal = Field(
        default=Decimal("0.30"), description="Minimum IV rank (0-1)"
    )
    iv_rank_max: Decimal = Field(
        default=Decimal("1.0"), description="Maximum IV rank (0-1)"
    )
    liquidity_min: Decimal | None = Field(
        default=None, description="Minimum liquidity rating"
    )
    market_cap_min: Decimal | None = Field(
        default=None, description="Minimum market cap"
    )
    earnings_exclusion_days: int = Field(
        default=7, description="Exclude if earnings within this many days"
    )
    borrow_rate_max: Decimal | None = Field(
        default=None, description="Maximum borrow rate"
    )
    beta_max: Decimal | None = Field(
        default=None, description="Maximum beta"
    )


def _passes_filter(metrics: MarketMetrics, criteria: ScreenCriteria) -> bool:
    """Check if a symbol passes all filter criteria."""
    if not (criteria.iv_rank_min <= metrics.iv_rank <= criteria.iv_rank_max):
        return False

    if criteria.liquidity_min is not None and metrics.liquidity_rating is not None:
        if metrics.liquidity_rating < criteria.liquidity_min:
            return False

    if criteria.market_cap_min is not None and metrics.market_cap is not None:
        if metrics.market_cap < criteria.market_cap_min:
            return False

    if criteria.borrow_rate_max is not None and metrics.borrow_rate is not None:
        if metrics.borrow_rate > criteria.borrow_rate_max:
            return False

    if criteria.beta_max is not None and metrics.beta is not None:
        if abs(metrics.beta) > criteria.beta_max:
            return False

    if metrics.earnings_date and criteria.earnings_exclusion_days > 0:
        try:
            earnings = datetime.strptime(metrics.earnings_date, "%Y-%m-%d").date()
            days_to_earnings = (earnings - date.today()).days
            if 0 <= days_to_earnings <= criteria.earnings_exclusion_days:
                return False
        except ValueError:
            pass

    return True


def _score(metrics: MarketMetrics) -> tuple[Decimal, list[str]]:
    """Compute a composite score for a symbol and collect reasons.

    Scoring components:
    - IV rank (weight: 50): higher is better for premium selling
    - Liquidity bonus (weight: 20): higher liquidity → tighter spreads
    - IV/HV spread edge (weight: 20): IV > HV suggests overpriced premium
    - Beta penalty (weight: -10): higher beta → more risk
    """
    score = Decimal("0")
    reasons: list[str] = []

    # IV rank contribution (0-50)
    iv_score = metrics.iv_rank * 50
    score += iv_score
    if metrics.iv_rank >= Decimal("0.50"):
        reasons.append(f"High IV rank: {metrics.iv_rank}")

    # Liquidity bonus (0-20)
    if metrics.liquidity_rating is not None:
        liq_score = min(metrics.liquidity_rating / Decimal("5"), Decimal("1")) * 20
        score += liq_score
        if metrics.liquidity_rating >= Decimal("4"):
            reasons.append(f"Good liquidity: {metrics.liquidity_rating}")

    # IV/HV spread edge (0-20)
    if metrics.implied_volatility is not None and metrics.historical_volatility is not None:
        if metrics.historical_volatility > 0:
            iv_hv_ratio = metrics.implied_volatility / metrics.historical_volatility
            if iv_hv_ratio > 1:
                edge = min((iv_hv_ratio - 1) * 20, Decimal("20"))
                score += edge
                reasons.append(f"IV/HV edge: {iv_hv_ratio:.2f}x")

    # Beta penalty (0 to -10)
    if metrics.beta is not None:
        beta_penalty = max(abs(metrics.beta) - 1, Decimal("0")) * 10
        beta_penalty = min(beta_penalty, Decimal("10"))
        score -= beta_penalty

    return score, reasons


def screen(
    metrics_list: list[MarketMetrics],
    criteria: ScreenCriteria | None = None,
) -> list[ScreenResult]:
    """Filter and rank symbols by criteria and composite score.

    Args:
        metrics_list: Market metrics for each symbol (from MCP get_market_metrics).
        criteria: Screening criteria. Uses defaults if None.

    Returns:
        Sorted list of ScreenResult, highest score first.
    """
    if criteria is None:
        criteria = ScreenCriteria()

    results: list[ScreenResult] = []
    for m in metrics_list:
        if not _passes_filter(m, criteria):
            continue
        score, reasons = _score(m)
        results.append(ScreenResult(
            symbol=m.symbol,
            metrics=m,
            score=score,
            reasons=reasons,
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results
