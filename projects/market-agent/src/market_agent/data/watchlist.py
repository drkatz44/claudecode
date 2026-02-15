"""Watchlist manager — persistent YAML-based symbol watchlists.

Watchlists are stored in ~/.market-agent/watchlists/ as YAML files.
Each watchlist has a name, symbols, and optional metadata per symbol.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

WATCHLIST_DIR = Path.home() / ".market-agent" / "watchlists"


@dataclass
class WatchlistEntry:
    """A symbol in a watchlist with optional notes."""
    symbol: str
    added_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"symbol": self.symbol, "added_at": self.added_at.isoformat()}
        if self.notes:
            d["notes"] = self.notes
        if self.tags:
            d["tags"] = self.tags
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WatchlistEntry":
        return cls(
            symbol=d["symbol"],
            added_at=datetime.fromisoformat(d.get("added_at", datetime.utcnow().isoformat())),
            notes=d.get("notes", ""),
            tags=d.get("tags", []),
        )


@dataclass
class Watchlist:
    """Named collection of symbols."""
    name: str
    description: str = ""
    entries: list[WatchlistEntry] = field(default_factory=list)

    @property
    def symbols(self) -> list[str]:
        return [e.symbol for e in self.entries]

    def add(self, symbol: str, notes: str = "", tags: Optional[list[str]] = None) -> bool:
        """Add a symbol. Returns False if already present."""
        symbol = symbol.upper()
        if symbol in self.symbols:
            return False
        self.entries.append(WatchlistEntry(
            symbol=symbol, notes=notes, tags=tags or [],
        ))
        return True

    def remove(self, symbol: str) -> bool:
        """Remove a symbol. Returns False if not found."""
        symbol = symbol.upper()
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.symbol != symbol]
        return len(self.entries) < before

    def has(self, symbol: str) -> bool:
        return symbol.upper() in self.symbols

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Watchlist":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            entries=[WatchlistEntry.from_dict(e) for e in d.get("entries", [])],
        )


def _safe_name(name: str) -> str:
    """Sanitize watchlist name to prevent path traversal."""
    return re.sub(r'[^\w\-]', '_', name)


def _watchlist_path(name: str) -> Path:
    safe = _safe_name(name)
    path = WATCHLIST_DIR / f"{safe}.yaml"
    # Verify resolved path stays within watchlist dir
    if WATCHLIST_DIR.exists() and not path.resolve().is_relative_to(WATCHLIST_DIR.resolve()):
        raise ValueError(f"Invalid watchlist name: {name}")
    return path


def save_watchlist(wl: Watchlist) -> Path:
    """Save watchlist to disk."""
    WATCHLIST_DIR.mkdir(parents=True, exist_ok=True)
    path = _watchlist_path(wl.name)
    with open(path, "w") as f:
        yaml.dump(wl.to_dict(), f, default_flow_style=False, sort_keys=False)
    return path


def load_watchlist(name: str) -> Optional[Watchlist]:
    """Load a watchlist by name. Returns None if not found."""
    path = _watchlist_path(name)
    if not path.exists():
        return None
    with open(path) as f:
        data = yaml.safe_load(f)
    return Watchlist.from_dict(data) if data else None


def list_watchlists() -> list[str]:
    """List all saved watchlist names."""
    if not WATCHLIST_DIR.exists():
        return []
    return [p.stem for p in sorted(WATCHLIST_DIR.glob("*.yaml"))]


def delete_watchlist(name: str) -> bool:
    """Delete a watchlist. Returns False if not found."""
    path = _watchlist_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def get_or_create(name: str, description: str = "") -> Watchlist:
    """Load existing watchlist or create a new one."""
    wl = load_watchlist(name)
    if wl is None:
        wl = Watchlist(name=name, description=description)
    return wl
