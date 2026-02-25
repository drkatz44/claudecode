"""Tests for the screener module."""

from decimal import Decimal

from tastytrade_strategy.models import MarketMetrics
from tastytrade_strategy.screener import ScreenCriteria, screen


def _metrics(
    symbol: str,
    iv_rank: str = "0.50",
    liquidity: str | None = None,
    iv: str | None = None,
    hv: str | None = None,
    beta: str | None = None,
    earnings: str | None = None,
    borrow_rate: str | None = None,
    market_cap: str | None = None,
) -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        iv_rank=Decimal(iv_rank),
        liquidity_rating=Decimal(liquidity) if liquidity else None,
        implied_volatility=Decimal(iv) if iv else None,
        historical_volatility=Decimal(hv) if hv else None,
        beta=Decimal(beta) if beta else None,
        earnings_date=earnings,
        borrow_rate=Decimal(borrow_rate) if borrow_rate else None,
        market_cap=Decimal(market_cap) if market_cap else None,
    )


class TestScreenFiltering:
    def test_filters_by_iv_rank_min(self):
        metrics = [
            _metrics("LOW", iv_rank="0.10"),
            _metrics("HIGH", iv_rank="0.60"),
        ]
        results = screen(metrics, ScreenCriteria(iv_rank_min=Decimal("0.30")))
        assert len(results) == 1
        assert results[0].symbol == "HIGH"

    def test_filters_by_iv_rank_max(self):
        metrics = [
            _metrics("MID", iv_rank="0.50"),
            _metrics("EXTREME", iv_rank="0.95"),
        ]
        results = screen(
            metrics,
            ScreenCriteria(iv_rank_min=Decimal("0.30"), iv_rank_max=Decimal("0.80")),
        )
        assert len(results) == 1
        assert results[0].symbol == "MID"

    def test_filters_by_liquidity(self):
        metrics = [
            _metrics("LIQUID", iv_rank="0.50", liquidity="5"),
            _metrics("ILLIQUID", iv_rank="0.50", liquidity="1"),
        ]
        results = screen(metrics, ScreenCriteria(liquidity_min=Decimal("3")))
        assert len(results) == 1
        assert results[0].symbol == "LIQUID"

    def test_filters_by_borrow_rate(self):
        metrics = [
            _metrics("CHEAP", iv_rank="0.50", borrow_rate="0.5"),
            _metrics("EXPENSIVE", iv_rank="0.50", borrow_rate="15.0"),
        ]
        results = screen(metrics, ScreenCriteria(borrow_rate_max=Decimal("5.0")))
        assert len(results) == 1
        assert results[0].symbol == "CHEAP"

    def test_filters_by_beta(self):
        metrics = [
            _metrics("CALM", iv_rank="0.50", beta="0.8"),
            _metrics("WILD", iv_rank="0.50", beta="2.5"),
        ]
        results = screen(metrics, ScreenCriteria(beta_max=Decimal("1.5")))
        assert len(results) == 1
        assert results[0].symbol == "CALM"

    def test_filters_by_market_cap(self):
        metrics = [
            _metrics("BIG", iv_rank="0.50", market_cap="50000000000"),
            _metrics("SMALL", iv_rank="0.50", market_cap="100000000"),
        ]
        results = screen(
            metrics, ScreenCriteria(market_cap_min=Decimal("1000000000"))
        )
        assert len(results) == 1
        assert results[0].symbol == "BIG"

    def test_default_criteria(self):
        metrics = [
            _metrics("A", iv_rank="0.10"),
            _metrics("B", iv_rank="0.40"),
            _metrics("C", iv_rank="0.70"),
        ]
        results = screen(metrics)
        assert len(results) == 2  # B and C pass iv_rank_min=0.30


class TestScreenScoring:
    def test_higher_iv_rank_scores_higher(self):
        metrics = [
            _metrics("LOW", iv_rank="0.35"),
            _metrics("HIGH", iv_rank="0.80"),
        ]
        results = screen(metrics)
        assert results[0].symbol == "HIGH"
        assert results[1].symbol == "LOW"

    def test_iv_hv_edge_boosts_score(self):
        metrics = [
            _metrics("EDGE", iv_rank="0.50", iv="0.40", hv="0.20"),
            _metrics("NO_EDGE", iv_rank="0.50", iv="0.20", hv="0.30"),
        ]
        results = screen(metrics)
        assert results[0].symbol == "EDGE"

    def test_reasons_populated(self):
        metrics = [
            _metrics("A", iv_rank="0.70", liquidity="5", iv="0.40", hv="0.25"),
        ]
        results = screen(metrics)
        assert len(results) == 1
        assert any("IV rank" in r for r in results[0].reasons)
        assert any("liquidity" in r.lower() for r in results[0].reasons)

    def test_sorted_descending(self):
        metrics = [
            _metrics("C", iv_rank="0.90"),
            _metrics("A", iv_rank="0.30"),
            _metrics("B", iv_rank="0.60"),
        ]
        results = screen(metrics)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
