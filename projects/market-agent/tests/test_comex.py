"""Tests for COMEX warehouse stock data fetching and analysis."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from market_agent.data.comex import (
    VALID_METALS,
    _is_numeric,
    _validate_metal,
    analyze_comex,
    fetch_all_metals_comex,
    fetch_comex_stocks,
)
from market_agent.data.models import ComexAnalysis, ComexWarehouse


def _make_warehouse(
    metal: str = "gold",
    registered: float = 8_000_000.0,
    eligible: float = 12_000_000.0,
    date: datetime = None,
) -> ComexWarehouse:
    """Create a ComexWarehouse for testing."""
    return ComexWarehouse(
        metal=metal,
        date=date or datetime(2024, 6, 11),
        registered=registered,
        eligible=eligible,
        total=registered + eligible,
        unit="troy_oz",
    )


class TestValidation:
    def test_valid_metals(self):
        assert _validate_metal("gold") == "gold"
        assert _validate_metal("GOLD") == "gold"
        assert _validate_metal("  Silver ") == "silver"

    def test_invalid_metal(self):
        with pytest.raises(ValueError, match="Unknown metal"):
            _validate_metal("unobtanium")

    def test_all_five_metals(self):
        assert len(VALID_METALS) == 5
        assert "gold" in VALID_METALS
        assert "copper" in VALID_METALS


class TestIsNumeric:
    def test_numeric_values(self):
        assert _is_numeric(42) is True
        assert _is_numeric(3.14) is True
        assert _is_numeric("100") is True

    def test_non_numeric(self):
        assert _is_numeric("abc") is False
        assert _is_numeric(None) is False
        assert _is_numeric(float("nan")) is False


class TestAnalyzeComex:
    def test_basic_analysis(self):
        current = _make_warehouse(registered=8_000_000, eligible=12_000_000)
        result = analyze_comex(current)
        assert isinstance(result, ComexAnalysis)
        assert result.registered_pct == 40.0  # 8M / 20M * 100
        assert result.trend == "stable"
        assert result.change_30d_pct == 0.0

    def test_drawing_trend(self):
        """When stocks decrease >3%, trend should be 'drawing'."""
        old = _make_warehouse(
            registered=10_000_000,
            eligible=15_000_000,
            date=datetime(2024, 5, 11),
        )
        current = _make_warehouse(
            registered=7_000_000,
            eligible=10_000_000,
            date=datetime(2024, 6, 11),
        )
        result = analyze_comex(current, history=[old, current])
        assert result.trend == "drawing"
        assert result.change_30d_pct < -3.0

    def test_building_trend(self):
        """When stocks increase >3%, trend should be 'building'."""
        old = _make_warehouse(
            registered=5_000_000,
            eligible=8_000_000,
            date=datetime(2024, 5, 11),
        )
        current = _make_warehouse(
            registered=8_000_000,
            eligible=12_000_000,
            date=datetime(2024, 6, 11),
        )
        result = analyze_comex(current, history=[old, current])
        assert result.trend == "building"
        assert result.change_30d_pct > 3.0

    def test_stable_trend(self):
        """Small changes should be 'stable'."""
        old = _make_warehouse(
            registered=8_000_000,
            eligible=12_000_000,
            date=datetime(2024, 5, 11),
        )
        current = _make_warehouse(
            registered=8_100_000,
            eligible=12_100_000,
            date=datetime(2024, 6, 11),
        )
        result = analyze_comex(current, history=[old, current])
        assert result.trend == "stable"

    def test_no_history(self):
        current = _make_warehouse()
        result = analyze_comex(current, history=None)
        assert result.trend == "stable"
        assert result.change_30d_pct == 0.0

    def test_zero_total(self):
        current = _make_warehouse(registered=0, eligible=0)
        # Override total to 0
        current.total = 0
        result = analyze_comex(current)
        assert result.registered_pct == 0.0


class TestFetchComexStocks:
    @patch("market_agent.data.comex._load_cache", return_value=None)
    @patch("market_agent.data.comex._save_cache")
    @patch("market_agent.data.comex._parse_comex_xls")
    @patch("market_agent.data.comex.requests.get")
    def test_fetch_success(self, mock_get, mock_parse, mock_save, mock_load):
        mock_resp = MagicMock()
        mock_resp.content = b"fake xls"
        mock_get.return_value = mock_resp

        expected = _make_warehouse()
        mock_parse.return_value = expected

        result = fetch_comex_stocks("gold")
        assert result is not None
        assert result.metal == "gold"
        mock_save.assert_called_once()

    @patch("market_agent.data.comex._load_cache", return_value=None)
    @patch("market_agent.data.comex.requests.get")
    def test_fetch_network_error(self, mock_get, mock_load):
        mock_get.side_effect = Exception("timeout")
        result = fetch_comex_stocks("silver")
        assert result is None

    @patch("market_agent.data.comex._load_cache", return_value=None)
    @patch("market_agent.data.comex._parse_comex_xls", return_value=None)
    @patch("market_agent.data.comex.requests.get")
    def test_fetch_unparseable(self, mock_get, mock_parse, mock_load):
        mock_resp = MagicMock()
        mock_resp.content = b"bad data"
        mock_get.return_value = mock_resp

        result = fetch_comex_stocks("copper")
        assert result is None

    def test_fetch_invalid_metal(self):
        with pytest.raises(ValueError):
            fetch_comex_stocks("unobtanium")

    @patch("market_agent.data.comex._load_cache")
    def test_fetch_from_cache(self, mock_load):
        cached = _make_warehouse().model_dump(mode="json")
        mock_load.return_value = cached
        result = fetch_comex_stocks("gold")
        assert result is not None
        assert result.metal == "gold"


class TestFetchAllMetals:
    @patch("market_agent.data.comex.fetch_comex_stocks")
    def test_fetches_all_five(self, mock_fetch):
        mock_fetch.return_value = _make_warehouse()
        results = fetch_all_metals_comex()
        assert len(results) == 5
        assert set(results.keys()) == VALID_METALS
        assert mock_fetch.call_count == 5

    @patch("market_agent.data.comex.fetch_comex_stocks")
    def test_handles_partial_failure(self, mock_fetch):
        mock_fetch.side_effect = [
            _make_warehouse(metal="gold"),
            None,
            _make_warehouse(metal="copper"),
            None,
            None,
        ]
        results = fetch_all_metals_comex()
        assert results["gold"] is not None
        assert results["silver"] is None
        assert results["copper"] is not None
