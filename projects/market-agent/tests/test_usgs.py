"""Tests for USGS commodity data stub."""

import pytest

from market_agent.data.usgs import (
    VALID_COMMODITIES,
    fetch_usgs_production,
    fetch_usgs_reserves,
)


class TestUsgsStub:
    def test_valid_commodities(self):
        assert "GOLD" in VALID_COMMODITIES
        assert "COPPER" in VALID_COMMODITIES
        assert len(VALID_COMMODITIES) == 5

    def test_production_returns_none(self):
        assert fetch_usgs_production("GOLD") is None
        assert fetch_usgs_production("silver") is None

    def test_reserves_returns_none(self):
        assert fetch_usgs_reserves("COPPER") is None

    def test_production_invalid_commodity(self):
        with pytest.raises(ValueError, match="Unknown commodity"):
            fetch_usgs_production("URANIUM")

    def test_reserves_invalid_commodity(self):
        with pytest.raises(ValueError, match="Unknown commodity"):
            fetch_usgs_reserves("UNOBTANIUM")
