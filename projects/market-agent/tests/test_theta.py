"""Tests for options data provider (theta.py)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from market_agent.data.theta import (
    YFinanceOptionsProvider,
    ThetaDataProvider,
    _cache_key,
    _dicts_to_quotes,
    _quotes_to_dicts,
    get_provider,
)
from market_agent.data.models import OptionQuote


def _make_quote(**kwargs) -> OptionQuote:
    defaults = dict(
        symbol="SPY241220P00440000",
        underlying="SPY",
        strike=Decimal("440"),
        expiration=datetime(2024, 12, 20),
        option_type="put",
        bid=Decimal("3.50"),
        ask=Decimal("3.80"),
        last=Decimal("3.65"),
        volume=1000,
        open_interest=5000,
        iv=Decimal("0.22"),
    )
    defaults.update(kwargs)
    return OptionQuote(**defaults)


class TestCacheHelpers:
    def test_cache_key_deterministic(self):
        k1 = _cache_key("SPY", date(2024, 1, 15), "2024-02-16")
        k2 = _cache_key("SPY", date(2024, 1, 15), "2024-02-16")
        assert k1 == k2

    def test_cache_key_differs_by_date(self):
        k1 = _cache_key("SPY", date(2024, 1, 15), "2024-02-16")
        k2 = _cache_key("SPY", date(2024, 1, 16), "2024-02-16")
        assert k1 != k2

    def test_cache_key_differs_by_symbol(self):
        k1 = _cache_key("SPY", date(2024, 1, 15), "2024-02-16")
        k2 = _cache_key("QQQ", date(2024, 1, 15), "2024-02-16")
        assert k1 != k2


class TestQuoteSerialization:
    def test_round_trip(self):
        quotes = [_make_quote(), _make_quote(option_type="call", strike=Decimal("450"))]
        dicts = _quotes_to_dicts(quotes)
        restored = _dicts_to_quotes(dicts)

        assert len(restored) == 2
        assert restored[0].symbol == quotes[0].symbol
        assert restored[0].strike == quotes[0].strike
        assert restored[1].option_type == "call"

    def test_handles_none_greeks(self):
        q = _make_quote(iv=None, delta=None)
        dicts = _quotes_to_dicts([q])
        restored = _dicts_to_quotes(dicts)
        assert restored[0].iv is None
        assert restored[0].delta is None

    def test_preserves_iv(self):
        q = _make_quote(iv=Decimal("0.2567"))
        dicts = _quotes_to_dicts([q])
        restored = _dicts_to_quotes(dicts)
        assert restored[0].iv == Decimal("0.2567")

    def test_skips_malformed_rows(self):
        bad = [{"symbol": "SPY"}, {"bad_field": 1}]
        result = _dicts_to_quotes(bad)
        assert result == []


class TestYFinanceProvider:
    @patch("market_agent.data.fetcher.get_option_chain")
    @patch("market_agent.data.fetcher.get_bars")
    def test_get_chain_returns_option_quotes(self, mock_bars, mock_chain):
        from market_agent.data.models import Bar

        mock_bars.return_value = [
            Bar(
                timestamp=datetime(2024, 1, 1) + timedelta(days=i),
                open=Decimal("450"), high=Decimal("455"),
                low=Decimal("445"), close=Decimal("450"), volume=1000000,
            )
            for i in range(5)
        ]
        mock_chain.return_value = [_make_quote()]

        provider = YFinanceOptionsProvider()
        chain = provider.get_chain("SPY", date(2024, 1, 15), "2024-02-16")

        assert isinstance(chain, list)
        assert len(chain) == 1
        mock_chain.assert_called_once()

    @patch("market_agent.data.fetcher.get_option_chain")
    @patch("market_agent.data.fetcher.get_bars")
    def test_get_chain_enriches_greeks(self, mock_bars, mock_chain):
        """Provider should attach BS greeks to quotes that have IV."""
        from market_agent.data.models import Bar

        mock_bars.return_value = [
            Bar(timestamp=datetime(2024, 1, 1), open=Decimal("450"),
                high=Decimal("455"), low=Decimal("445"), close=Decimal("450"), volume=1000000),
        ]
        q = _make_quote(iv=Decimal("0.22"), delta=None)
        mock_chain.return_value = [q]

        provider = YFinanceOptionsProvider()
        chain = provider.get_chain("SPY", date(2024, 1, 15), "2024-02-16")

        # Delta should be enriched via BS
        assert chain[0].delta is not None

    @patch("market_agent.data.fetcher.get_expirations")
    def test_get_expirations_delegates(self, mock_exp):
        mock_exp.return_value = ["2024-02-16", "2024-03-15"]
        provider = YFinanceOptionsProvider()
        exps = provider.get_expirations("SPY")
        assert exps == ["2024-02-16", "2024-03-15"]


class TestThetaDataProvider:
    def test_rejects_empty_key(self):
        with pytest.raises(ValueError):
            ThetaDataProvider("")

    def test_rejects_none_key(self):
        with pytest.raises((ValueError, TypeError)):
            ThetaDataProvider(None)


class TestGetProvider:
    def test_returns_yfinance_without_key(self):
        # Patch config path to not exist → falls through to YFinance
        from unittest.mock import patch as _patch
        from pathlib import Path
        with _patch.object(Path, "exists", return_value=False):
            provider = get_provider()
        assert isinstance(provider, YFinanceOptionsProvider)

    def test_returns_yfinance_by_default(self):
        # With no config file / no key, should return YFinance
        provider = get_provider()
        assert isinstance(provider, YFinanceOptionsProvider)
