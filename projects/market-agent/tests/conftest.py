"""Shared test fixtures for market-agent."""

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from market_agent.data.models import Bar


def generate_bars(count: int = 100, trend: str = "up", start_price: float = 100.0,
                  volatility: float = 0.02) -> list[Bar]:
    """Generate synthetic OHLCV bars for testing.

    Args:
        count: Number of bars to generate
        trend: "up", "down", or "flat"
        start_price: Starting close price
        volatility: Daily volatility as fraction of price
    """
    bars = []
    price = start_price
    base_time = datetime(2024, 1, 2, 16, 0, 0)

    drift = {"up": 0.003, "down": -0.003, "flat": 0.0}[trend]

    for i in range(count):
        # Simple deterministic movement for reproducibility
        move = drift + volatility * (0.5 if i % 3 == 0 else -0.3 if i % 3 == 1 else 0.1)
        price *= (1 + move)

        high = price * (1 + volatility * 0.5)
        low = price * (1 - volatility * 0.5)
        open_p = price * (1 + volatility * 0.1 * (1 if i % 2 == 0 else -1))

        bars.append(Bar(
            timestamp=base_time + timedelta(days=i),
            open=Decimal(str(round(open_p, 4))),
            high=Decimal(str(round(high, 4))),
            low=Decimal(str(round(low, 4))),
            close=Decimal(str(round(price, 4))),
            volume=1000000 + i * 10000,
        ))

    return bars


@pytest.fixture
def uptrend_bars():
    """100 bars with upward trend."""
    return generate_bars(100, trend="up")


@pytest.fixture
def downtrend_bars():
    """100 bars with downward trend."""
    return generate_bars(100, trend="down")


@pytest.fixture
def flat_bars():
    """100 bars with flat/sideways movement."""
    return generate_bars(100, trend="flat")


@pytest.fixture
def short_bars():
    """20 bars — insufficient for most indicators."""
    return generate_bars(20, trend="up")


@pytest.fixture
def temp_watchlist_dir(tmp_path, monkeypatch):
    """Redirect watchlist storage to a temp directory."""
    import market_agent.data.watchlist as wl_mod
    monkeypatch.setattr(wl_mod, "WATCHLIST_DIR", tmp_path)
    return tmp_path
