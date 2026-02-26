"""Tests for sector classification and concentration helpers."""

import pytest

from market_agent.analysis.sectors import (
    MAX_SECTOR_BP_PCT,
    SECTOR_MAP,
    get_sector,
    portfolio_sector_bp,
    sector_headroom,
)


class TestGetSector:
    def test_broad_market(self):
        assert get_sector("SPY") == "broad"
        assert get_sector("IWM") == "broad"
        assert get_sector("/ES") == "broad"

    def test_tech(self):
        assert get_sector("QQQ") == "tech"
        assert get_sector("XLK") == "tech"
        assert get_sector("/NQ") == "tech"

    def test_metals(self):
        assert get_sector("GLD") == "metals"
        assert get_sector("/GC") == "metals"
        assert get_sector("/SI") == "metals"

    def test_energy(self):
        assert get_sector("XLE") == "energy"
        assert get_sector("/CL") == "energy"

    def test_rates(self):
        assert get_sector("TLT") == "rates"
        assert get_sector("/ZN") == "rates"

    def test_unknown_returns_other(self):
        assert get_sector("WEIRD") == "other"
        assert get_sector("XYZ123") == "other"

    def test_case_insensitive(self):
        assert get_sector("spy") == get_sector("SPY")
        assert get_sector("gld") == get_sector("GLD")
        assert get_sector("qqq") == get_sector("QQQ")

    def test_futures_slash_prefix(self):
        assert get_sector("/GC") == "metals"
        assert get_sector("/CL") == "energy"
        assert get_sector("/ZB") == "rates"
        assert get_sector("/ZC") == "ag"

    def test_all_mapped_symbols_have_valid_sector(self):
        valid_sectors = {"broad", "tech", "financial", "energy", "metals",
                         "materials", "rates", "consumer", "ag", "volatility"}
        for sym, sector in SECTOR_MAP.items():
            assert sector in valid_sectors, f"{sym} → '{sector}' not in valid set"


class TestPortfolioSectorBp:
    def test_empty_positions_empty_dict(self):
        result = portfolio_sector_bp([], net_liq=75000)
        assert result == {}

    def test_single_position_accumulates(self):
        positions = [{"symbol": "SPY", "position_size_pct": 2.0}]
        result = portfolio_sector_bp(positions, net_liq=75000)
        assert result["broad"] == pytest.approx(2.0)

    def test_two_same_sector_adds(self):
        positions = [
            {"symbol": "SPY", "position_size_pct": 2.0},
            {"symbol": "IWM", "position_size_pct": 3.0},
        ]
        result = portfolio_sector_bp(positions, net_liq=75000)
        assert result["broad"] == pytest.approx(5.0)

    def test_two_different_sectors_separate(self):
        positions = [
            {"symbol": "SPY", "position_size_pct": 2.0},
            {"symbol": "GLD", "position_size_pct": 1.5},
        ]
        result = portfolio_sector_bp(positions, net_liq=75000)
        assert result["broad"] == pytest.approx(2.0)
        assert result["metals"] == pytest.approx(1.5)

    def test_missing_size_treated_as_zero(self):
        positions = [{"symbol": "SPY"}]  # No position_size_pct
        result = portfolio_sector_bp(positions, net_liq=75000)
        assert result.get("broad", 0.0) == pytest.approx(0.0)

    def test_bp_pct_fallback(self):
        positions = [{"symbol": "QQQ", "bp_pct": 2.5}]
        result = portfolio_sector_bp(positions, net_liq=75000)
        assert result["tech"] == pytest.approx(2.5)

    def test_unknown_symbol_goes_to_other(self):
        positions = [{"symbol": "WEIRD", "position_size_pct": 1.0}]
        result = portfolio_sector_bp(positions, net_liq=75000)
        assert result["other"] == pytest.approx(1.0)


class TestSectorHeadroom:
    def test_empty_portfolio_full_headroom(self):
        headroom = sector_headroom("broad", [], net_liq=75000)
        assert headroom == pytest.approx(MAX_SECTOR_BP_PCT)

    def test_partial_usage_reduces_headroom(self):
        positions = [{"symbol": "SPY", "position_size_pct": 10.0}]
        headroom = sector_headroom("broad", positions, net_liq=75000)
        assert headroom == pytest.approx(MAX_SECTOR_BP_PCT - 10.0)

    def test_at_limit_zero_headroom(self):
        positions = [{"symbol": "SPY", "position_size_pct": MAX_SECTOR_BP_PCT}]
        headroom = sector_headroom("broad", positions, net_liq=75000)
        assert headroom == pytest.approx(0.0)

    def test_over_limit_negative_headroom(self):
        positions = [{"symbol": "SPY", "position_size_pct": MAX_SECTOR_BP_PCT + 5.0}]
        headroom = sector_headroom("broad", positions, net_liq=75000)
        assert headroom < 0

    def test_different_sector_no_impact(self):
        positions = [{"symbol": "GLD", "position_size_pct": 20.0}]
        headroom = sector_headroom("broad", positions, net_liq=75000)
        assert headroom == pytest.approx(MAX_SECTOR_BP_PCT)  # metals usage doesn't affect broad

    def test_custom_max_respected(self):
        positions = [{"symbol": "SPY", "position_size_pct": 15.0}]
        headroom = sector_headroom("broad", positions, net_liq=75000, max_sector_pct=20.0)
        assert headroom == pytest.approx(5.0)
