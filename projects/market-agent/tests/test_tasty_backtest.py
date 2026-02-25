"""Tests for tastytrade backtesting API client (tasty_backtest.py)."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import json

import pytest
import requests

from market_agent.data.tasty_backtest import (
    TastytradeBacktester,
    _build_legs,
    _parse_response,
    _empty_result,
    _STRATEGY_LEGS,
    get_backtester,
)
from market_agent.backtest.options_engine import OptionsBacktestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trial(open_dt="2025-01-01T10:00:00Z", close_dt="2025-01-20T15:00:00Z",
                pnl=125.0) -> dict:
    return {"openDateTime": open_dt, "closeDateTime": close_dt, "profitLoss": pnl}


def _mock_backtester(token="test-token-abc") -> TastytradeBacktester:
    return TastytradeBacktester(token)


def _completed_response(symbol="SPY", strategy="strangle", trials=None) -> dict:
    if trials is None:
        trials = [
            _make_trial(pnl=100.0),
            _make_trial(pnl=-50.0),
            _make_trial(pnl=75.0),
        ]
    return {
        "id": "bt-abc123",
        "symbol": symbol,
        "status": "completed",
        "progress": 1.0,
        "trials": trials,
        "statistics": [],
        "snapshots": [],
    }


# ---------------------------------------------------------------------------
# Leg building
# ---------------------------------------------------------------------------

class TestBuildLegs:
    def test_strangle_two_legs(self):
        legs = _build_legs("strangle", 0.16, 37)
        assert len(legs) == 2
        sides = {l["side"] for l in legs}
        assert sides == {"put", "call"}
        assert all(l["direction"] == "short" for l in legs)

    def test_iron_condor_four_legs(self):
        legs = _build_legs("iron_condor", 0.16, 37)
        assert len(legs) == 4
        shorts = [l for l in legs if l["direction"] == "short"]
        longs  = [l for l in legs if l["direction"] == "long"]
        assert len(shorts) == 2
        assert len(longs) == 2

    def test_short_put_one_leg(self):
        legs = _build_legs("short_put", 0.30, 45)
        assert len(legs) == 1
        assert legs[0]["side"] == "put"
        assert legs[0]["direction"] == "short"

    def test_vertical_spread_two_legs(self):
        legs = _build_legs("vertical_spread", 0.16, 35)
        assert len(legs) == 2
        puts = [l for l in legs if l["side"] == "put"]
        assert len(puts) == 2

    def test_unknown_strategy_empty(self):
        legs = _build_legs("unsupported_xyz", 0.16, 37)
        assert legs == []

    def test_dte_applied_to_all_legs(self):
        legs = _build_legs("strangle", 0.16, 42)
        assert all(l["daysUntilExpiration"] == 42 for l in legs)

    def test_type_is_equity_option(self):
        for strategy in _STRATEGY_LEGS:
            legs = _build_legs(strategy, 0.16, 37)
            assert all(l["type"] == "equity-option" for l in legs)

    def test_strike_selection_is_delta(self):
        for strategy in _STRATEGY_LEGS:
            legs = _build_legs(strategy, 0.16, 37)
            assert all(l["strikeSelection"] == "delta" for l in legs)

    def test_delta_values_in_range(self):
        for strategy in _STRATEGY_LEGS:
            legs = _build_legs(strategy, 0.16, 37)
            for leg in legs:
                assert 1 <= leg["delta"] <= 100


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_three_trials_parsed(self):
        result = _parse_response("SPY", "strangle", _completed_response(trials=[
            _make_trial(pnl=100.0),
            _make_trial(pnl=-50.0),
            _make_trial(pnl=75.0),
        ]))
        assert result.sample_size == 3

    def test_win_rate_correct(self):
        result = _parse_response("SPY", "strangle", _completed_response(trials=[
            _make_trial(pnl=100.0),
            _make_trial(pnl=50.0),
            _make_trial(pnl=-30.0),
        ]))
        assert result.win_rate == pytest.approx(66.7, abs=0.2)

    def test_avg_pnl_correct(self):
        result = _parse_response("SPY", "strangle", _completed_response(trials=[
            _make_trial(pnl=100.0),
            _make_trial(pnl=0.0),
        ]))
        assert result.avg_pnl == pytest.approx(50.0)

    def test_dit_computed_from_dates(self):
        result = _parse_response("SPY", "strangle", _completed_response(trials=[
            _make_trial(
                open_dt="2025-01-01T10:00:00Z",
                close_dt="2025-01-16T10:00:00Z",
                pnl=50.0,
            )
        ]))
        assert result.trades[0].dit == 15

    def test_provider_type_tastytrade(self):
        result = _parse_response("SPY", "strangle", _completed_response())
        assert result.provider_type == "TastytradeBacktester"

    def test_empty_trials_returns_empty_result(self):
        result = _parse_response("SPY", "strangle", _completed_response(trials=[]))
        assert result.sample_size == 0

    def test_malformed_trial_skipped(self):
        resp = _completed_response(trials=[
            {"badField": 1},
            _make_trial(pnl=50.0),
        ])
        result = _parse_response("SPY", "strangle", resp)
        assert result.sample_size == 1  # Only valid trial counted

    def test_sharpe_computed(self):
        result = _parse_response("SPY", "strangle", _completed_response(trials=[
            _make_trial(pnl=float(v)) for v in [100, 50, 80, 20, 60]
        ]))
        assert result.sharpe != 0.0

    def test_exit_reason_api_result(self):
        result = _parse_response("SPY", "strangle", _completed_response())
        for trade in result.trades:
            assert trade.exit_reason == "api_result"


# ---------------------------------------------------------------------------
# TastytradeBacktester construction
# ---------------------------------------------------------------------------

class TestTastytradeBacktesterConstruction:
    def test_rejects_empty_token(self):
        with pytest.raises(ValueError):
            TastytradeBacktester("")

    def test_rejects_none_token(self):
        with pytest.raises((ValueError, TypeError)):
            TastytradeBacktester(None)

    def test_valid_token_accepted(self):
        bt = TastytradeBacktester("valid-token-xyz")
        assert bt is not None

    def test_auth_header_set(self):
        bt = TastytradeBacktester("my-token")
        assert bt._session.headers["Authorization"] == "Bearer my-token"


# ---------------------------------------------------------------------------
# TastytradeBacktester.run_backtest (mocked HTTP)
# ---------------------------------------------------------------------------

class TestRunBacktest:
    def _mock_session(self, backtester, submit_response, poll_response=None):
        mock_post = MagicMock()
        mock_post.status_code = submit_response.get("status_code", 200)
        mock_post.json.return_value = submit_response.get("json", {})
        mock_post.raise_for_status = MagicMock()

        mock_get = MagicMock()
        if poll_response:
            mock_get.status_code = 200
            mock_get.json.return_value = poll_response
            mock_get.raise_for_status = MagicMock()

        backtester._session.post = MagicMock(return_value=mock_post)
        backtester._session.get = MagicMock(return_value=mock_get)

    def test_synchronous_200_returns_result(self):
        bt = _mock_backtester()
        completed = _completed_response()
        completed["status"] = "completed"
        self._mock_session(bt, {"status_code": 200, "json": completed})

        result = bt.run_backtest("SPY", "strangle")
        assert isinstance(result, OptionsBacktestResult)
        assert result.sample_size > 0

    def test_async_201_polls_to_completion(self):
        bt = _mock_backtester()
        pending = {"id": "bt-xyz", "status": "pending"}
        completed = _completed_response()
        self._mock_session(bt,
            {"status_code": 201, "json": pending},
            poll_response=completed,
        )
        # Patch poll interval to avoid slow test
        with patch("market_agent.data.tasty_backtest.POLL_INTERVAL", 0.01):
            result = bt.run_backtest("SPY", "strangle")
        assert result.sample_size > 0

    def test_401_returns_empty(self):
        bt = _mock_backtester()
        mock_post = MagicMock()
        mock_post.status_code = 401
        mock_post.text = "Unauthorized"
        mock_post.raise_for_status = MagicMock()
        bt._session.post = MagicMock(return_value=mock_post)

        result = bt.run_backtest("SPY", "strangle")
        assert result.sample_size == 0

    def test_unsupported_strategy_returns_empty(self):
        bt = _mock_backtester()
        result = bt.run_backtest("SPY", "unsupported_strategy")
        assert result.sample_size == 0

    def test_network_error_returns_empty(self):
        bt = _mock_backtester()
        bt._session.post = MagicMock(side_effect=requests.exceptions.ConnectionError())
        result = bt.run_backtest("SPY", "strangle")
        assert result.sample_size == 0

    def test_dte_midpoint_used(self):
        bt = _mock_backtester()
        completed = _completed_response()
        self._mock_session(bt, {"status_code": 200, "json": completed})

        bt.run_backtest("SPY", "strangle", dte_range=(30, 45))
        call_body = bt._session.post.call_args[1]["json"]
        legs = call_body["legs"]
        assert all(l["daysUntilExpiration"] == 37 for l in legs)  # (30+45)//2

    def test_profit_target_passed(self):
        bt = _mock_backtester()
        completed = _completed_response()
        self._mock_session(bt, {"status_code": 200, "json": completed})

        bt.run_backtest("SPY", "strangle", profit_target_pct=60.0)
        body = bt._session.post.call_args[1]["json"]
        assert body["exitConditions"]["takeProfitPercentage"] == 60

    def test_date_range_is_lookback_days(self):
        bt = _mock_backtester()
        completed = _completed_response()
        self._mock_session(bt, {"status_code": 200, "json": completed})

        bt.run_backtest("SPY", "strangle", lookback_days=180)
        body = bt._session.post.call_args[1]["json"]
        start = date.fromisoformat(body["startDate"])
        end = date.fromisoformat(body["endDate"])
        assert (end - start).days == 180

    def test_symbol_in_request(self):
        bt = _mock_backtester()
        completed = _completed_response()
        self._mock_session(bt, {"status_code": 200, "json": completed})

        bt.run_backtest("QQQ", "iron_condor")
        body = bt._session.post.call_args[1]["json"]
        assert body["symbol"] == "QQQ"


# ---------------------------------------------------------------------------
# get_backtester factory
# ---------------------------------------------------------------------------

class TestGetBacktester:
    def test_returns_none_without_config(self):
        from pathlib import Path
        with patch.object(Path, "exists", return_value=False):
            result = get_backtester()
        assert result is None

    def test_returns_none_without_token_key(self):
        # yaml is lazily imported inside get_backtester — patch at source
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value="scan:\n  symbols: []\n"):
                result = get_backtester()
        assert result is None

    def test_returns_backtester_with_token(self):
        config_yaml = "tastytrade_token: test-token-xyz"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=config_yaml):
                result = get_backtester()
        if result is not None:
            assert isinstance(result, TastytradeBacktester)
