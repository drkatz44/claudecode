"""Tests for mcp_parser module."""

from decimal import Decimal

import pytest

from tastytrade_strategy.mcp_parser import parse_market_metrics, parse_market_metrics_response


class TestParseMarketMetrics:
    def test_parses_tastytrade_api_format(self):
        """Handles dasherized keys from the real tastytrade REST API."""
        raw = {
            "symbol": "AAPL",
            "implied-volatility-rank": "42.5",
            "implied-volatility-percentile": "38.0",
            "implied-volatility-index": "0.25",
            "historical-volatility-30-day": "0.22",
            "liquidity-rating": 5,
            "beta": "1.2",
            "market-cap": "3000000000000",
            "earnings-next-date-estimate": "2024-08-01",
            "borrow-rate": "0.5",
        }
        m = parse_market_metrics(raw)
        assert m.symbol == "AAPL"
        assert m.iv_rank == Decimal("0.425")   # normalized from 42.5
        assert m.iv_percentile == Decimal("0.38")
        assert m.implied_volatility == Decimal("0.25")
        assert m.historical_volatility == Decimal("0.22")
        assert m.liquidity_rating == Decimal("5")
        assert m.beta == Decimal("1.2")
        assert m.earnings_date == "2024-08-01"
        assert m.borrow_rate == Decimal("0.5")

    def test_iv_rank_already_normalized(self):
        """If iv_rank is already 0-1 it is not divided again."""
        raw = {"symbol": "SPY", "implied-volatility-rank": "0.42"}
        m = parse_market_metrics(raw)
        assert m.iv_rank == Decimal("0.42")

    def test_iv_rank_100_scale_normalized(self):
        """Values > 1 are divided by 100."""
        raw = {"symbol": "SPY", "implied-volatility-rank": "85"}
        m = parse_market_metrics(raw)
        assert m.iv_rank == Decimal("0.85")

    def test_fallback_key_names(self):
        """Accepts snake_case and camelCase variants."""
        raw = {
            "symbol": "TSLA",
            "iv_rank": "0.60",
            "historical_volatility": "0.45",
            "liquidity_rating": "4",
        }
        m = parse_market_metrics(raw)
        assert m.iv_rank == Decimal("0.60")
        assert m.historical_volatility == Decimal("0.45")
        assert m.liquidity_rating == Decimal("4")

    def test_missing_optional_fields_are_none(self):
        raw = {"symbol": "IWM", "implied-volatility-rank": "0.50"}
        m = parse_market_metrics(raw)
        assert m.symbol == "IWM"
        assert m.iv_rank == Decimal("0.50")
        assert m.iv_percentile is None
        assert m.implied_volatility is None
        assert m.historical_volatility is None
        assert m.liquidity_rating is None
        assert m.beta is None
        assert m.market_cap is None
        assert m.earnings_date is None
        assert m.borrow_rate is None

    def test_earnings_date_truncated_to_date(self):
        """Datetime strings are truncated to YYYY-MM-DD."""
        raw = {
            "symbol": "NVDA",
            "implied-volatility-rank": "0.70",
            "earnings-next-date-estimate": "2024-08-28T20:00:00.000+00:00",
        }
        m = parse_market_metrics(raw)
        assert m.earnings_date == "2024-08-28"

    def test_invalid_decimal_values_become_none(self):
        raw = {
            "symbol": "X",
            "implied-volatility-rank": "0.50",
            "beta": "N/A",
            "liquidity-rating": "unknown",
        }
        m = parse_market_metrics(raw)
        assert m.beta is None
        assert m.liquidity_rating is None

    def test_hv_prefers_30_day(self):
        """30-day HV is preferred over 60/90/99-day."""
        raw = {
            "symbol": "QQQ",
            "implied-volatility-rank": "0.50",
            "historical-volatility-30-day": "0.18",
            "historical-volatility-60-day": "0.20",
        }
        m = parse_market_metrics(raw)
        assert m.historical_volatility == Decimal("0.18")


class TestParseMarketMetricsResponse:
    def test_parses_api_envelope(self):
        """Handles the standard tastytrade response envelope."""
        response = {
            "data": {
                "items": [
                    {"symbol": "AAPL", "implied-volatility-rank": "0.50"},
                    {"symbol": "TSLA", "implied-volatility-rank": "0.80"},
                ]
            },
            "context": "/market-metrics",
        }
        results = parse_market_metrics_response(response)
        assert len(results) == 2
        assert results[0].symbol == "AAPL"
        assert results[1].symbol == "TSLA"

    def test_parses_bare_list(self):
        """Handles a plain list of items."""
        response = [
            {"symbol": "SPY", "implied-volatility-rank": "0.30"},
            {"symbol": "IWM", "implied-volatility-rank": "0.45"},
        ]
        results = parse_market_metrics_response(response)
        assert len(results) == 2

    def test_parses_data_as_list(self):
        """Handles {"data": [...]} without items key."""
        response = {
            "data": [
                {"symbol": "GLD", "implied-volatility-rank": "0.55"},
            ]
        }
        results = parse_market_metrics_response(response)
        assert len(results) == 1
        assert results[0].symbol == "GLD"

    def test_parses_single_item_dict(self):
        """Handles a single dict (no array wrapping)."""
        response = {"symbol": "AMZN", "implied-volatility-rank": "0.60"}
        results = parse_market_metrics_response(response)
        assert len(results) == 1
        assert results[0].symbol == "AMZN"

    def test_empty_items_returns_empty_list(self):
        response = {"data": {"items": []}}
        results = parse_market_metrics_response(response)
        assert results == []

    def test_invalid_input_returns_empty_list(self):
        assert parse_market_metrics_response(None) == []  # type: ignore
        assert parse_market_metrics_response("bad") == []  # type: ignore
