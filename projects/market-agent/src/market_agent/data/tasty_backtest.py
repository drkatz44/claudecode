"""Tastytrade Backtesting API client.

Wraps https://backtester.vast.tastyworks.com to run server-side multi-leg
options backtests with real historical fills and IV — a step up from
options_engine.py's theta decay + price move proxy.

Requires `tastytrade_token` in ~/.market-agent/config.yaml.
Tokens expire; the user must refresh via tastytrade OAuth or tasty-agent MCP.

Usage:
    backtester = get_backtester()
    if backtester:
        result = backtester.run_backtest("SPY", "strangle", delta_target=0.16)
        print(result.win_rate, result.avg_dit)
"""

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from ..backtest.options_engine import OptionsBacktestResult, OptionsTrade

logger = logging.getLogger(__name__)

BASE_URL = "https://backtester.vast.tastyworks.com"
POLL_INTERVAL = 3.0    # seconds between status polls
POLL_TIMEOUT = 120.0   # max seconds to wait for completion
REQUEST_TIMEOUT = 30   # seconds for individual HTTP calls

# Strategy → leg builder
# Each tuple: (side, option_type, delta, direction)
# delta is 1-100 (tastytrade convention)
_STRATEGY_LEGS: dict[str, list[dict]] = {
    "short_put": [
        {"direction": "short", "side": "put", "delta": 30},
    ],
    "strangle": [
        {"direction": "short", "side": "put",  "delta": 16},
        {"direction": "short", "side": "call", "delta": 16},
    ],
    "iron_condor": [
        {"direction": "short", "side": "put",  "delta": 16},
        {"direction": "long",  "side": "put",  "delta": 5},
        {"direction": "short", "side": "call", "delta": 16},
        {"direction": "long",  "side": "call", "delta": 5},
    ],
    "vertical_spread": [
        {"direction": "short", "side": "put", "delta": 30},
        {"direction": "long",  "side": "put", "delta": 16},
    ],
    "jade_lizard": [
        {"direction": "short", "side": "put",  "delta": 30},
        {"direction": "short", "side": "call", "delta": 20},
        {"direction": "long",  "side": "call", "delta": 8},
    ],
    "back_ratio": [
        {"direction": "short", "side": "put", "delta": 30},
        {"direction": "long",  "side": "put", "delta": 16},
        {"direction": "long",  "side": "put", "delta": 16},
    ],
}


def _build_legs(strategy_type: str, delta_target: float, dte: int) -> list[dict]:
    """Build the `legs` array for the backtest POST body."""
    template = _STRATEGY_LEGS.get(strategy_type)
    if not template:
        return []

    # Override delta from template with scaled delta_target if caller specifies
    # non-default delta. Default template uses sensible per-leg deltas.
    legs = []
    for leg in template:
        legs.append({
            "type": "equity-option",
            "direction": leg["direction"],
            "side": leg["side"],
            "quantity": 1,
            "strikeSelection": "delta",
            "delta": leg["delta"],
            "daysUntilExpiration": dte,
        })
    return legs


class TastytradeBacktester:
    """Run options structure backtests via tastytrade's backtesting API.

    Requires valid Bearer token in config.yaml (key: tastytrade_token).
    Tokens expire; refresh via tastytrade OAuth or by running tasty-agent MCP
    and noting the session token.

    Returns OptionsBacktestResult — same format as options_engine.backtest_structure(),
    so TradeEvaluator uses it transparently.
    """

    def __init__(self, token: str):
        if not token or not isinstance(token, str):
            raise ValueError("tastytrade_token required")
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_backtest(
        self,
        symbol: str,
        strategy_type: str,
        delta_target: float = 0.16,
        dte_range: tuple[int, int] = (30, 45),
        lookback_days: int = 252,
        profit_target_pct: float = 50.0,
        stop_loss_pct: float = 200.0,
        max_dte_exit: int = 21,
    ) -> OptionsBacktestResult:
        """Run a server-side backtest and return standardised results.

        Args:
            symbol: Underlying ticker (must be in available-dates list)
            strategy_type: One of the keys in _STRATEGY_LEGS
            delta_target: Short-delta target (0-1, used for context/logging)
            dte_range: (min_dte, max_dte) — midpoint used for entry DTE
            lookback_days: Calendar days of history to cover
            profit_target_pct: Close at this % of credit collected
            stop_loss_pct: Stop out at this % of credit as loss
            max_dte_exit: Roll/close at this DTE remaining

        Returns:
            OptionsBacktestResult with win_rate, avg_dit, sharpe, etc.
        """
        dte = (dte_range[0] + dte_range[1]) // 2
        legs = _build_legs(strategy_type, delta_target, dte)
        if not legs:
            logger.warning("No leg template for strategy %s", strategy_type)
            return _empty_result(symbol, strategy_type, "TastytradeBacktester")

        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)

        body = {
            "symbol": symbol,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "legs": legs,
            "entryConditions": {
                "frequency": "every day",
                "maximumActiveTrials": 1,
                "maximumActiveTrialsBehavior": "don't enter",
            },
            "exitConditions": {
                "takeProfitPercentage": int(profit_target_pct),
                "stopLossPercentage": int(stop_loss_pct),
                "atDaysToExpiration": max_dte_exit,
            },
        }

        try:
            backtest_id = self._submit(body)
            if not backtest_id:
                return _empty_result(symbol, strategy_type, "TastytradeBacktester")

            response = self._poll(backtest_id)
            if not response:
                return _empty_result(symbol, strategy_type, "TastytradeBacktester")

            return _parse_response(symbol, strategy_type, response)

        except requests.exceptions.RequestException:
            logger.exception("Tastytrade backtest request failed for %s %s", symbol, strategy_type)
            return _empty_result(symbol, strategy_type, "TastytradeBacktester")

    def get_available_symbols(self) -> list[str]:
        """Return symbols that have historical data available."""
        try:
            resp = self._session.get(
                f"{BASE_URL}/available-dates",
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            # Response is a dict of symbol → date ranges
            if isinstance(data, dict):
                return list(data.keys())
            return []
        except requests.exceptions.RequestException:
            logger.exception("Failed to fetch available symbols")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _submit(self, body: dict) -> str | None:
        """POST to /backtests and return backtest ID."""
        resp = self._session.post(
            f"{BASE_URL}/backtests",
            json=body,
            timeout=REQUEST_TIMEOUT,
        )

        if resp.status_code == 401:
            logger.error(
                "Tastytrade backtest: 401 Unauthorized — "
                "token may be expired. Refresh tastytrade_token in config.yaml."
            )
            return None

        if resp.status_code not in (200, 201):
            logger.warning(
                "Tastytrade backtest submit failed: HTTP %d — %s",
                resp.status_code, resp.text[:200],
            )
            return None

        data = resp.json()
        backtest_id = data.get("id")
        if not backtest_id:
            logger.warning("Tastytrade backtest: no id in response")
            return None

        status = data.get("status", "")
        if status == "completed":
            # 200 — synchronous result, store and return early
            self._cached_response = data
            return backtest_id

        logger.debug("Tastytrade backtest %s submitted, status=%s", backtest_id, status)
        self._cached_response = None
        return backtest_id

    def _poll(self, backtest_id: str) -> dict | None:
        """Poll GET /backtests/{id} until completed or timeout."""
        # Check if we already have a completed response from _submit
        if getattr(self, "_cached_response", None):
            result = self._cached_response
            self._cached_response = None
            return result

        deadline = time.monotonic() + POLL_TIMEOUT
        while time.monotonic() < deadline:
            try:
                resp = self._session.get(
                    f"{BASE_URL}/backtests/{backtest_id}",
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()

                status = data.get("status", "")
                progress = data.get("progress", 0)
                logger.debug("Backtest %s: status=%s progress=%.0f%%", backtest_id, status, progress * 100)

                if status == "completed":
                    return data
                if status in ("failed", "cancelled"):
                    logger.warning("Tastytrade backtest %s: %s", backtest_id, status)
                    return None

                time.sleep(POLL_INTERVAL)

            except requests.exceptions.RequestException:
                logger.exception("Poll error for backtest %s", backtest_id)
                return None

        logger.warning("Tastytrade backtest %s timed out after %.0fs", backtest_id, POLL_TIMEOUT)
        # Attempt cancellation on timeout
        try:
            self._session.post(f"{BASE_URL}/backtests/{backtest_id}/cancel", timeout=5)
        except Exception:
            pass
        return None


# ------------------------------------------------------------------
# Response parsing
# ------------------------------------------------------------------

def _parse_response(
    symbol: str,
    strategy_type: str,
    data: dict,
) -> OptionsBacktestResult:
    """Convert tastytrade backtest response to OptionsBacktestResult."""
    import math
    import numpy as np

    trials_raw = data.get("trials") or []
    trades: list[OptionsTrade] = []

    for t in trials_raw:
        try:
            open_dt = datetime.fromisoformat(t["openDateTime"].replace("Z", "+00:00"))
            close_dt = datetime.fromisoformat(t["closeDateTime"].replace("Z", "+00:00"))
            pnl = float(t["profitLoss"])
            dit = max((close_dt.date() - open_dt.date()).days, 0)

            trades.append(OptionsTrade(
                entry_date=open_dt.date(),
                exit_date=close_dt.date(),
                strategy_type=strategy_type,
                symbol=symbol,
                credit=0.0,    # Not returned by API at trial level
                exit_pnl=pnl,  # Raw dollar P&L
                dit=dit,
                mae=0.0,       # Not available per-trial from API
                exit_reason="api_result",
            ))
        except (KeyError, ValueError, TypeError):
            continue

    if not trades:
        return _empty_result(symbol, strategy_type, "TastytradeBacktester")

    pnl_values = [t.exit_pnl for t in trades]
    winners = [p for p in pnl_values if p > 0]
    win_rate = len(winners) / len(trades) * 100
    avg_pnl = sum(pnl_values) / len(pnl_values)
    avg_dit = sum(t.dit for t in trades) / len(trades)

    arr = np.array(pnl_values)
    sharpe = float(arr.mean() / arr.std()) if arr.std() > 0 else 0.0

    # Check for API-level statistics if present
    stats = data.get("statistics") or []
    for stat in stats:
        name = stat.get("name", "")
        value = stat.get("value")
        if name == "Win Rate" and value is not None:
            try:
                win_rate = float(value) * 100  # API may return 0-1
            except (TypeError, ValueError):
                pass

    return OptionsBacktestResult(
        symbol=symbol,
        strategy_type=strategy_type,
        sample_size=len(trades),
        win_rate=round(win_rate, 1),
        avg_pnl=round(avg_pnl, 2),
        avg_dit=round(avg_dit, 1),
        max_adverse_excursion=0.0,  # Not available from API
        pnl_distribution=pnl_values,
        sharpe=round(sharpe, 2),
        trades=trades,
        provider_type="TastytradeBacktester",
    )


def _empty_result(symbol: str, strategy_type: str, provider_type: str) -> OptionsBacktestResult:
    return OptionsBacktestResult(
        symbol=symbol, strategy_type=strategy_type,
        sample_size=0, win_rate=0, avg_pnl=0, avg_dit=0,
        max_adverse_excursion=0, provider_type=provider_type,
    )


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def get_backtester() -> "TastytradeBacktester | None":
    """Return TastytradeBacktester if token is configured, else None.

    Token source: `tastytrade_token` key in ~/.market-agent/config.yaml
    Tokens expire (15-min OAuth access token or session token). Keep fresh
    by noting the token from an active tasty-agent MCP session.

    Example config.yaml:
        tastytrade_token: "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1..."
    """
    try:
        import yaml
        config_path = Path.home() / ".market-agent" / "config.yaml"
        if not config_path.exists():
            return None
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        token = raw.get("tastytrade_token", "").strip()
        if token:
            return TastytradeBacktester(token)
    except Exception:
        logger.debug("Could not load tastytrade_token from config")
    return None
