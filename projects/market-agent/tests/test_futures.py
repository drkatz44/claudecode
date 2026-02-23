"""Tests for futures contract specifications."""

from market_agent.data.futures import (
    ETF_UNIVERSE,
    FULL_UNIVERSE,
    FUTURES_SPECS,
    FUTURES_UNIVERSE,
    FuturesSpec,
    get_spec,
    is_futures,
    notional_value,
    tick_value,
)


class TestFuturesSpecs:
    def test_all_specs_present(self):
        expected = {"ES", "NQ", "RTY", "YM", "GC", "SI", "HG", "PL", "CL", "NG", "6E", "6J", "6B", "BTC"}
        assert set(FUTURES_SPECS.keys()) == expected

    def test_es_spec(self):
        es = FUTURES_SPECS["ES"]
        assert es.multiplier == 50
        assert es.tick_size == 0.25
        assert es.exchange == "CME"
        assert es.micro == "MES"

    def test_gc_spec(self):
        gc = FUTURES_SPECS["GC"]
        assert gc.multiplier == 100
        assert gc.exchange == "COMEX"
        assert gc.micro == "MGC"
        assert gc.sector == "metals"

    def test_cl_spec(self):
        cl = FUTURES_SPECS["CL"]
        assert cl.multiplier == 1000
        assert cl.exchange == "NYMEX"
        assert cl.sector == "energy"

    def test_btc_spec(self):
        btc = FUTURES_SPECS["BTC"]
        assert btc.multiplier == 5
        assert btc.exchange == "CME"
        assert btc.sector == "crypto"

    def test_all_have_required_fields(self):
        for sym, spec in FUTURES_SPECS.items():
            assert spec.multiplier > 0, f"{sym} multiplier must be positive"
            assert spec.tick_size > 0, f"{sym} tick_size must be positive"
            assert spec.exchange in {"CME", "COMEX", "NYMEX", "ICE"}, f"{sym} unknown exchange"
            assert spec.sector in {"index", "metals", "energy", "currency", "crypto"}, f"{sym} unknown sector"


class TestGetSpec:
    def test_valid_symbol(self):
        spec = get_spec("ES")
        assert spec is not None
        assert spec.name == "E-mini S&P 500"

    def test_lowercase(self):
        spec = get_spec("es")
        assert spec is not None

    def test_invalid_symbol(self):
        assert get_spec("AAPL") is None
        assert get_spec("XYZ") is None


class TestIsFutures:
    def test_futures_symbols(self):
        assert is_futures("ES")
        assert is_futures("GC")
        assert is_futures("CL")

    def test_non_futures(self):
        assert not is_futures("SPY")
        assert not is_futures("AAPL")


class TestNotionalValue:
    def test_es(self):
        # ES at 5000 = 5000 * 50 = 250,000
        assert notional_value("ES", 5000) == 250_000

    def test_gc(self):
        # GC at 2000 = 2000 * 100 = 200,000
        assert notional_value("GC", 2000) == 200_000

    def test_non_futures(self):
        assert notional_value("AAPL", 150) is None


class TestTickValue:
    def test_es(self):
        # ES: 0.25 tick * 50 multiplier = $12.50
        assert tick_value("ES") == 12.50

    def test_gc(self):
        # GC: 0.10 tick * 100 multiplier = $10.00
        assert tick_value("GC") == 10.0

    def test_non_futures(self):
        assert tick_value("SPY") is None


class TestUniverses:
    def test_futures_universe_matches_specs(self):
        assert set(FUTURES_UNIVERSE) == set(FUTURES_SPECS.keys())

    def test_etf_universe_not_empty(self):
        assert len(ETF_UNIVERSE) > 0
        assert "SPY" in ETF_UNIVERSE
        assert "QQQ" in ETF_UNIVERSE

    def test_full_universe_is_combined(self):
        assert len(FULL_UNIVERSE) == len(FUTURES_UNIVERSE) + len(ETF_UNIVERSE)
