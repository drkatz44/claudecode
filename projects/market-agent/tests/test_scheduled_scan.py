"""Tests for scheduled scan change detection logic."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

# Import the functions we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from market_agent.signals.recommender import Recommendation, OptionsStrategy


def _make_rec(symbol, action="buy_equity", direction="long", confidence=0.7, strategy="momentum"):
    return Recommendation(
        symbol=symbol,
        action=action,
        direction=direction,
        confidence=confidence,
        strategy_name=strategy,
    )


class TestChangeDetection:
    """Test the change detection logic from scheduled_scan.py."""

    def test_find_new_empty_previous(self):
        # Import here to avoid import issues with script module
        from scheduled_scan import _find_new
        recs = [_make_rec("AAPL"), _make_rec("NVDA")]
        new = _find_new(recs, {})
        assert len(new) == 2

    def test_find_new_unchanged(self):
        from scheduled_scan import _find_new
        recs = [_make_rec("AAPL", action="buy_equity", direction="long")]
        previous = {
            "AAPL": {"action": "buy_equity", "direction": "long"}
        }
        new = _find_new(recs, previous)
        assert len(new) == 0

    def test_find_new_action_changed(self):
        from scheduled_scan import _find_new
        recs = [_make_rec("AAPL", action="sell_premium", direction="neutral")]
        previous = {
            "AAPL": {"action": "buy_equity", "direction": "long"}
        }
        new = _find_new(recs, previous)
        assert len(new) == 1
        assert new[0].symbol == "AAPL"

    def test_find_new_symbol_added(self):
        from scheduled_scan import _find_new
        recs = [_make_rec("AAPL"), _make_rec("NVDA")]
        previous = {
            "AAPL": {"action": "buy_equity", "direction": "long"}
        }
        new = _find_new(recs, previous)
        assert len(new) == 1
        assert new[0].symbol == "NVDA"


class TestLoadSavePrevious:
    def test_load_missing_file(self, tmp_path, monkeypatch):
        from scheduled_scan import _load_previous
        import scheduled_scan as ss_mod
        monkeypatch.setattr(ss_mod, "LAST_SCAN_PATH", tmp_path / "missing.json")
        assert _load_previous() == {}

    def test_load_invalid_json(self, tmp_path, monkeypatch):
        from scheduled_scan import _load_previous
        import scheduled_scan as ss_mod
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json{{{")
        monkeypatch.setattr(ss_mod, "LAST_SCAN_PATH", bad_file)
        assert _load_previous() == {}

    def test_load_non_dict_json(self, tmp_path, monkeypatch):
        from scheduled_scan import _load_previous
        import scheduled_scan as ss_mod
        list_file = tmp_path / "list.json"
        list_file.write_text("[1, 2, 3]")
        monkeypatch.setattr(ss_mod, "LAST_SCAN_PATH", list_file)
        assert _load_previous() == {}

    def test_save_and_load(self, tmp_path, monkeypatch):
        from scheduled_scan import _save_current, _load_previous
        import scheduled_scan as ss_mod

        scan_path = tmp_path / "scan.json"
        monkeypatch.setattr(ss_mod, "LAST_SCAN_PATH", scan_path)
        monkeypatch.setattr(ss_mod, "DATA_DIR", tmp_path)

        recs = [_make_rec("AAPL"), _make_rec("NVDA", action="sell_premium")]
        _save_current(recs)

        data = _load_previous()
        assert "AAPL" in data
        assert data["AAPL"]["action"] == "buy_equity"
        assert "NVDA" in data
        assert data["NVDA"]["action"] == "sell_premium"


class TestReportGeneration:
    def test_generates_markdown(self):
        from scheduled_scan import _generate_report
        recs = [_make_rec("AAPL"), _make_rec("NVDA")]
        new_recs = [_make_rec("NVDA")]

        report = _generate_report(recs, new_recs)
        assert "# Scheduled Scan Report" in report
        assert "AAPL" in report
        assert "NVDA" in report
        assert "New Signals" in report
        assert "Total recommendations: 2" in report
        assert "New/changed signals: 1" in report

    def test_no_new_signals(self):
        from scheduled_scan import _generate_report
        recs = [_make_rec("AAPL")]
        report = _generate_report(recs, [])
        assert "New Signals" not in report
        assert "All Recommendations" in report
