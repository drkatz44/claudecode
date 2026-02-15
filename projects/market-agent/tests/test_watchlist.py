"""Tests for watchlist management."""

import pytest

from market_agent.data.watchlist import (
    Watchlist,
    WatchlistEntry,
    _safe_name,
    delete_watchlist,
    get_or_create,
    list_watchlists,
    load_watchlist,
    save_watchlist,
)


class TestSafeName:
    def test_normal_name(self):
        assert _safe_name("my_watchlist") == "my_watchlist"

    def test_strips_path_traversal(self):
        result = _safe_name("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_strips_special_chars(self):
        result = _safe_name("my list!@#$%")
        assert "!" not in result
        assert "@" not in result

    def test_preserves_hyphens(self):
        assert _safe_name("my-watchlist") == "my-watchlist"


class TestWatchlist:
    def test_add_symbol(self):
        wl = Watchlist(name="test", description="Test")
        wl.add("AAPL")
        assert wl.has("AAPL")
        assert len(wl.symbols) == 1

    def test_add_duplicate(self):
        wl = Watchlist(name="test", description="Test")
        wl.add("AAPL")
        wl.add("AAPL")  # should update, not duplicate
        assert len(wl.symbols) == 1

    def test_remove_symbol(self):
        wl = Watchlist(name="test", description="Test")
        wl.add("AAPL")
        wl.remove("AAPL")
        assert not wl.has("AAPL")
        assert len(wl.symbols) == 0

    def test_remove_nonexistent(self):
        wl = Watchlist(name="test", description="Test")
        wl.remove("AAPL")  # should not raise
        assert len(wl.symbols) == 0

    def test_case_insensitive_has(self):
        wl = Watchlist(name="test", description="Test")
        wl.add("AAPL")
        assert wl.has("aapl")
        assert wl.has("Aapl")

    def test_add_with_notes_and_tags(self):
        wl = Watchlist(name="test", description="Test")
        wl.add("AAPL", notes="Tech giant", tags=["tech", "large_cap"])
        entry = next(e for e in wl.entries if e.symbol == "AAPL")
        assert entry.notes == "Tech giant"
        assert "tech" in entry.tags

    def test_symbol_list(self):
        wl = Watchlist(name="test", description="Test")
        wl.add("AAPL")
        wl.add("MSFT")
        wl.add("GOOG")
        assert set(wl.symbols) == {"AAPL", "MSFT", "GOOG"}


class TestWatchlistPersistence:
    def test_save_and_load(self, temp_watchlist_dir):
        wl = Watchlist(name="test_persist", description="Persistence test")
        wl.add("AAPL", notes="Test note")
        wl.add("MSFT")
        save_watchlist(wl)

        loaded = load_watchlist("test_persist")
        assert loaded is not None
        assert loaded.name == "test_persist"
        assert loaded.has("AAPL")
        assert loaded.has("MSFT")
        assert len(loaded.symbols) == 2

    def test_load_nonexistent(self, temp_watchlist_dir):
        result = load_watchlist("does_not_exist")
        assert result is None

    def test_list_watchlists(self, temp_watchlist_dir):
        save_watchlist(Watchlist(name="wl1", description="First"))
        save_watchlist(Watchlist(name="wl2", description="Second"))
        names = list_watchlists()
        assert "wl1" in names
        assert "wl2" in names

    def test_delete_watchlist(self, temp_watchlist_dir):
        wl = Watchlist(name="to_delete", description="Delete me")
        save_watchlist(wl)
        assert load_watchlist("to_delete") is not None
        delete_watchlist("to_delete")
        assert load_watchlist("to_delete") is None

    def test_get_or_create_new(self, temp_watchlist_dir):
        wl = get_or_create("new_list", "New watchlist")
        assert wl.name == "new_list"
        assert wl.description == "New watchlist"

    def test_get_or_create_existing(self, temp_watchlist_dir):
        wl = Watchlist(name="existing", description="Already here")
        wl.add("AAPL")
        save_watchlist(wl)

        loaded = get_or_create("existing", "Should not overwrite")
        assert loaded.has("AAPL")

    def test_roundtrip_preserves_data(self, temp_watchlist_dir):
        wl = Watchlist(name="roundtrip", description="Full roundtrip")
        wl.add("AAPL", notes="Apple Inc", tags=["tech"])
        wl.add("BTC-USD", notes="Bitcoin", tags=["crypto"])
        save_watchlist(wl)

        loaded = load_watchlist("roundtrip")
        assert loaded.description == "Full roundtrip"
        aapl = next(e for e in loaded.entries if e.symbol == "AAPL")
        assert aapl.notes == "Apple Inc"
        assert "tech" in aapl.tags
