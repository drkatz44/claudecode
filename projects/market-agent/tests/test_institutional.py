"""Tests for institutional flow analysis (COT + COMEX aggregation)."""

from datetime import datetime
from unittest.mock import patch

import pytest

from market_agent.analysis.institutional import (
    METALS_TICKER_MAP,
    format_institutional_summary,
    institutional_bias,
    is_metals_ticker,
    ticker_to_commodity,
)
from market_agent.data.models import ComexAnalysis, CotAnalysis


def _make_cot(
    commodity: str = "GOLD",
    mm_net: int = 150000,
    mm_net_pct: float = 30.0,
    z_score: float = 0.5,
    positioning_signal: str = "neutral",
    weekly_change: int = 5000,
) -> CotAnalysis:
    return CotAnalysis(
        commodity=commodity,
        report_date=datetime(2024, 6, 11),
        mm_net=mm_net,
        mm_net_pct=mm_net_pct,
        z_score=z_score,
        positioning_signal=positioning_signal,
        weekly_change=weekly_change,
    )


def _make_comex(
    metal: str = "gold",
    registered_pct: float = 40.0,
    trend: str = "stable",
    change_30d_pct: float = 1.0,
) -> ComexAnalysis:
    return ComexAnalysis(
        metal=metal,
        date=datetime(2024, 6, 11),
        registered_pct=registered_pct,
        trend=trend,
        change_30d_pct=change_30d_pct,
    )


class TestTickerMapping:
    def test_metals_etfs(self):
        assert is_metals_ticker("GLD") is True
        assert is_metals_ticker("SLV") is True
        assert is_metals_ticker("CPER") is True

    def test_metals_miners(self):
        assert is_metals_ticker("NEM") is True
        assert is_metals_ticker("FCX") is True
        assert is_metals_ticker("GDX") is True

    def test_non_metals(self):
        assert is_metals_ticker("AAPL") is False
        assert is_metals_ticker("SPY") is False

    def test_case_insensitive(self):
        assert is_metals_ticker("gld") is True
        assert ticker_to_commodity("gld") == "GOLD"

    def test_commodity_mapping(self):
        assert ticker_to_commodity("GLD") == "GOLD"
        assert ticker_to_commodity("FCX") == "COPPER"
        assert ticker_to_commodity("PPLT") == "PLATINUM"
        assert ticker_to_commodity("PALL") == "PALLADIUM"
        assert ticker_to_commodity("AAPL") is None


class TestInstitutionalBias:
    def test_extreme_long_drawing(self):
        cot = _make_cot(positioning_signal="extreme_long", z_score=2.0)
        comex = _make_comex(trend="drawing", change_30d_pct=-5.0)
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "bullish_crowded"
        assert result["confidence_adj"] == 0.85

    def test_extreme_short_drawing(self):
        cot = _make_cot(positioning_signal="extreme_short", z_score=-2.0)
        comex = _make_comex(trend="drawing")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "bullish_capitulation"
        assert result["confidence_adj"] == 1.2

    def test_neutral_building(self):
        cot = _make_cot(positioning_signal="neutral")
        comex = _make_comex(trend="building")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "neutral_abundant"
        assert result["confidence_adj"] == 0.9

    def test_extreme_long_building(self):
        cot = _make_cot(positioning_signal="extreme_long")
        comex = _make_comex(trend="building")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "bearish_excess"
        assert result["confidence_adj"] == 0.8

    def test_extreme_short_building(self):
        cot = _make_cot(positioning_signal="extreme_short")
        comex = _make_comex(trend="building")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "neutral_rebuilding"
        assert result["confidence_adj"] == 0.95

    def test_neutral_no_comex(self):
        cot = _make_cot(positioning_signal="neutral")
        result = institutional_bias("GOLD", cot, None)
        assert result["bias"] == "neutral"
        assert result["confidence_adj"] == 1.0

    def test_no_data(self):
        result = institutional_bias("GOLD", None, None)
        assert result["bias"] == "neutral"
        assert result["confidence_adj"] == 1.0

    def test_extreme_long_only(self):
        cot = _make_cot(positioning_signal="extreme_long")
        comex = _make_comex(trend="stable")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "bullish_crowded"
        assert result["confidence_adj"] == 0.85

    def test_extreme_short_only(self):
        cot = _make_cot(positioning_signal="extreme_short")
        comex = _make_comex(trend="stable")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "bullish_capitulation"
        assert result["confidence_adj"] == 1.1

    def test_drawing_only(self):
        cot = _make_cot(positioning_signal="neutral")
        comex = _make_comex(trend="drawing")
        result = institutional_bias("GOLD", cot, comex)
        assert result["bias"] == "bullish_physical"
        assert result["confidence_adj"] == 1.05

    def test_rationale_has_content(self):
        cot = _make_cot(mm_net=150000, mm_net_pct=30.0, z_score=0.5)
        comex = _make_comex(registered_pct=40.0, trend="stable")
        result = institutional_bias("GOLD", cot, comex)
        assert "MM net" in result["rationale"]
        assert "COMEX" in result["rationale"]


class TestFormatSummary:
    def test_with_full_data(self):
        context = {
            "cot": {"GOLD": _make_cot(), "SILVER": None},
            "comex": {"gold": _make_comex(), "silver": None},
        }
        md = format_institutional_summary(context)
        assert "## Institutional Flow Summary" in md
        assert "COT Managed Money" in md
        assert "COMEX Warehouse" in md
        assert "Combined Bias" in md
        assert "GOLD" in md

    def test_empty_data(self):
        context = {"cot": {}, "comex": {}}
        md = format_institutional_summary(context)
        assert "## Institutional Flow Summary" in md

    def test_all_none(self):
        context = {
            "cot": {"GOLD": None, "SILVER": None},
            "comex": {"gold": None, "silver": None},
        }
        md = format_institutional_summary(context)
        assert "Combined Bias" in md
        assert "neutral" in md
