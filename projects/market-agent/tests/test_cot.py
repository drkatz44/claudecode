"""Tests for CFTC COT data fetching and analysis."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from market_agent.data.cot import (
    CFTC_CODES,
    VALID_COMMODITIES,
    _validate_commodity,
    analyze_cot,
    fetch_all_metals_cot,
    fetch_cot,
)
from market_agent.data.models import CotAnalysis, CotReport


def _make_cot_row(
    date: str,
    mm_long: int = 200000,
    mm_short: int = 50000,
    mm_spread: int = 30000,
    comm_long: int = 100000,
    comm_short: int = 150000,
    nonrept_long: int = 20000,
    nonrept_short: int = 25000,
    oi: int = 500000,
) -> dict:
    """Create a mock Socrata API response row."""
    return {
        "report_date_as_yyyy_mm_dd": f"{date}T00:00:00.000",
        "m_money_positions_long_all": str(mm_long),
        "m_money_positions_short_all": str(mm_short),
        "m_money_positions_spread_all": str(mm_spread),
        "prod_merc_positions_long_all": str(comm_long),
        "prod_merc_positions_short_all": str(comm_short),
        "nonrept_positions_long_all": str(nonrept_long),
        "nonrept_positions_short_all": str(nonrept_short),
        "open_interest_all": str(oi),
    }


def _make_report(
    commodity: str = "GOLD",
    date: datetime = None,
    mm_long: int = 200000,
    mm_short: int = 50000,
    oi: int = 500000,
) -> CotReport:
    """Create a CotReport for testing."""
    return CotReport(
        commodity=commodity,
        report_date=date or datetime(2024, 6, 11),
        managed_money_long=mm_long,
        managed_money_short=mm_short,
        managed_money_spreading=30000,
        commercial_long=100000,
        commercial_short=150000,
        non_reportable_long=20000,
        non_reportable_short=25000,
        open_interest=oi,
    )


class TestValidation:
    def test_valid_commodity(self):
        assert _validate_commodity("GOLD") == "GOLD"
        assert _validate_commodity("gold") == "GOLD"
        assert _validate_commodity("  Silver ") == "SILVER"

    def test_invalid_commodity(self):
        with pytest.raises(ValueError, match="Unknown commodity"):
            _validate_commodity("URANIUM")

    def test_all_codes_have_valid_commodities(self):
        assert set(CFTC_CODES.keys()) == VALID_COMMODITIES


class TestFetchCot:
    @patch("market_agent.data.cot._load_cache", return_value=None)
    @patch("market_agent.data.cot._save_cache")
    @patch("market_agent.data.cot.requests.get")
    def test_fetch_success(self, mock_get, mock_save, mock_load):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            _make_cot_row("2024-06-11"),
            _make_cot_row("2024-06-04", mm_long=190000),
        ]
        mock_get.return_value = mock_resp

        reports = fetch_cot("GOLD", weeks=4)
        assert len(reports) == 2
        assert reports[0].commodity == "GOLD"
        assert reports[0].managed_money_long == 200000
        assert reports[1].managed_money_long == 190000
        mock_save.assert_called_once()

    @patch("market_agent.data.cot._load_cache", return_value=None)
    @patch("market_agent.data.cot.requests.get")
    def test_fetch_network_error(self, mock_get, mock_load):
        mock_get.side_effect = Exception("connection failed")
        reports = fetch_cot("GOLD", weeks=4)
        assert reports == []

    @patch("market_agent.data.cot._load_cache", return_value=None)
    @patch("market_agent.data.cot.requests.get")
    def test_fetch_invalid_response(self, mock_get, mock_load):
        mock_resp = MagicMock()
        mock_resp.json.return_value = "not a list"
        mock_get.return_value = mock_resp

        reports = fetch_cot("SILVER")
        assert reports == []

    @patch("market_agent.data.cot._load_cache", return_value=None)
    @patch("market_agent.data.cot._save_cache")
    @patch("market_agent.data.cot.requests.get")
    def test_fetch_skips_malformed_rows(self, mock_get, mock_save, mock_load):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            _make_cot_row("2024-06-11"),
            {"bad": "row"},  # Missing required fields
        ]
        mock_get.return_value = mock_resp

        reports = fetch_cot("COPPER", weeks=4)
        assert len(reports) == 1

    def test_fetch_invalid_commodity(self):
        with pytest.raises(ValueError):
            fetch_cot("UNOBTANIUM")


class TestAnalyzeCot:
    def test_basic_analysis(self):
        reports = [
            _make_report(mm_long=200000, mm_short=50000, oi=500000),
            _make_report(mm_long=180000, mm_short=60000),
        ]
        result = analyze_cot(reports)
        assert result is not None
        assert result.mm_net == 150000  # 200k - 50k
        assert result.mm_net_pct == 30.0  # 150k / 500k * 100
        assert result.weekly_change == 30000  # 150k - (180k-60k)

    def test_empty_reports(self):
        assert analyze_cot([]) is None

    def test_single_report(self):
        result = analyze_cot([_make_report()])
        assert result is not None
        assert result.weekly_change == 0
        assert result.z_score == 0.0

    def test_extreme_long_classification(self):
        """When MM net is far above mean, should classify as extreme_long."""
        base_date = datetime(2024, 6, 11)
        reports = []
        # Most weeks: moderate net position
        for i in range(50):
            reports.append(_make_report(
                date=base_date - timedelta(weeks=i),
                mm_long=100000,
                mm_short=80000,
            ))
        # Latest: huge net long
        reports[0] = _make_report(
            date=base_date,
            mm_long=300000,
            mm_short=20000,
        )

        result = analyze_cot(reports)
        assert result is not None
        assert result.positioning_signal == "extreme_long"
        assert result.z_score > 1.5

    def test_extreme_short_classification(self):
        """When MM net is far below mean, should classify as extreme_short."""
        base_date = datetime(2024, 6, 11)
        reports = []
        for i in range(50):
            reports.append(_make_report(
                date=base_date - timedelta(weeks=i),
                mm_long=100000,
                mm_short=80000,
            ))
        # Latest: huge net short
        reports[0] = _make_report(
            date=base_date,
            mm_long=20000,
            mm_short=300000,
        )

        result = analyze_cot(reports)
        assert result is not None
        assert result.positioning_signal == "extreme_short"
        assert result.z_score < -1.5

    def test_neutral_classification(self):
        """When positioning is near mean, should classify as neutral."""
        reports = [
            _make_report(mm_long=100000, mm_short=80000),
            _make_report(mm_long=100000, mm_short=80000),
            _make_report(mm_long=100000, mm_short=80000),
        ]
        result = analyze_cot(reports)
        assert result is not None
        assert result.positioning_signal == "neutral"

    def test_zero_open_interest(self):
        reports = [_make_report(oi=0)]
        result = analyze_cot(reports)
        assert result is not None
        assert result.mm_net_pct == 0.0


class TestFetchAllMetals:
    @patch("market_agent.data.cot.fetch_cot")
    def test_fetches_all_five(self, mock_fetch):
        mock_fetch.return_value = [_make_report()]
        results = fetch_all_metals_cot(weeks=4)
        assert len(results) == 5
        assert set(results.keys()) == VALID_COMMODITIES
        assert mock_fetch.call_count == 5

    @patch("market_agent.data.cot.fetch_cot")
    def test_handles_partial_failure(self, mock_fetch):
        mock_fetch.side_effect = [
            [_make_report(commodity="GOLD")],
            [],  # Silver fails
            [_make_report(commodity="COPPER")],
            [],
            [],
        ]
        results = fetch_all_metals_cot(weeks=4)
        assert results["GOLD"] is not None
        assert results["SILVER"] is None
        assert results["COPPER"] is not None
