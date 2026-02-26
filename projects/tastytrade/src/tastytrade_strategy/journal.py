"""SQLite-backed trade journal for tracking entries, exits, and P&L.

Stores trade data at ~/.tastytrade-strategy/journal.db.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from .models import OrderLeg, StrategyType, TradeStatus

# ---------------------------------------------------------------------------
# Journal entry model
# ---------------------------------------------------------------------------

class JournalEntry(BaseModel):
    """A single trade journal entry."""

    id: int | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    underlying: str
    strategy_type: StrategyType
    legs: list[OrderLeg]
    entry_price: Decimal
    exit_price: Decimal | None = None
    rationale: str = ""
    profit_target: Decimal | None = None
    stop_loss: Decimal | None = None
    pnl: Decimal | None = None
    status: TradeStatus = TradeStatus.OPEN


# ---------------------------------------------------------------------------
# Journal class
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".tastytrade-strategy"
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    underlying TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    legs TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    exit_price TEXT,
    rationale TEXT,
    profit_target TEXT,
    stop_loss TEXT,
    pnl TEXT,
    status TEXT NOT NULL DEFAULT 'open'
)
"""


class Journal:
    """SQLite trade journal."""

    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            _DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
            db_path = _DEFAULT_DB_DIR / "journal.db"
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def log_trade(self, entry: JournalEntry) -> JournalEntry:
        """Log a new trade entry. Returns the entry with its assigned ID."""
        legs_json = json.dumps([leg.model_dump() for leg in entry.legs])
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO trades
                   (timestamp, underlying, strategy_type, legs, entry_price,
                    rationale, profit_target, stop_loss, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.timestamp,
                    entry.underlying,
                    entry.strategy_type.value,
                    legs_json,
                    str(entry.entry_price),
                    entry.rationale,
                    str(entry.profit_target) if entry.profit_target is not None else None,
                    str(entry.stop_loss) if entry.stop_loss is not None else None,
                    entry.status.value,
                ),
            )
            entry.id = cursor.lastrowid
        return entry

    def close_trade(
        self,
        trade_id: int,
        exit_price: Decimal,
        pnl: Decimal | None = None,
    ) -> JournalEntry | None:
        """Close an open trade by ID."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE trades
                   SET exit_price = ?, pnl = ?, status = ?
                   WHERE id = ? AND status = 'open'""",
                (str(exit_price), str(pnl) if pnl is not None else None, "closed", trade_id),
            )
        return self._get_by_id(trade_id)

    def get_open_trades(self) -> list[JournalEntry]:
        """Get all open trades."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY timestamp DESC"
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_history(
        self,
        underlying: str | None = None,
        limit: int = 50,
    ) -> list[JournalEntry]:
        """Get trade history, optionally filtered by underlying."""
        query = "SELECT * FROM trades"
        params: list = []
        if underlying:
            query += " WHERE underlying = ?"
            params.append(underlying)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def summary_stats(self) -> dict:
        """Compute summary statistics for closed trades."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pnl FROM trades WHERE status = 'closed' AND pnl IS NOT NULL"
            ).fetchall()

        if not rows:
            return {
                "total_trades": 0,
                "total_pnl": Decimal("0"),
                "winners": 0,
                "losers": 0,
                "win_rate": Decimal("0"),
                "avg_pnl": Decimal("0"),
            }

        pnls = [Decimal(r[0]) for r in rows]
        winners = sum(1 for p in pnls if p > 0)
        losers = sum(1 for p in pnls if p < 0)
        total = Decimal(sum(pnls))
        count = len(pnls)

        return {
            "total_trades": count,
            "total_pnl": total,
            "winners": winners,
            "losers": losers,
            "win_rate": Decimal(str(winners / count)) if count > 0 else Decimal("0"),
            "avg_pnl": total / count if count > 0 else Decimal("0"),
        }

    def rich_stats(self) -> dict:
        """Extended analytics for closed trades: by-strategy, by-underlying, extremes.

        Returns a dict suitable for JSON serialisation (all Decimals converted to float).
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT strategy_type, underlying, pnl, entry_price, exit_price,
                          timestamp
                   FROM trades
                   WHERE status = 'closed' AND pnl IS NOT NULL"""
            ).fetchall()

        open_rows = self._count_open()

        if not rows:
            return {
                "open_trades": open_rows,
                "closed_trades": 0,
                "total_pnl": 0.0,
                "winners": 0,
                "losers": 0,
                "breakeven": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "max_win": 0.0,
                "max_loss": 0.0,
                "by_strategy": {},
                "by_underlying": {},
            }

        pnls = [float(r[2]) for r in rows]
        winners = sum(1 for p in pnls if p > 0)
        losers = sum(1 for p in pnls if p < 0)
        breakeven = len(pnls) - winners - losers
        count = len(pnls)
        total = sum(pnls)

        # By-strategy breakdown
        by_strategy: dict[str, dict] = {}
        for row in rows:
            strat = row[0]
            pnl = float(row[2])
            if strat not in by_strategy:
                by_strategy[strat] = {"trades": 0, "total_pnl": 0.0, "winners": 0}
            by_strategy[strat]["trades"] += 1
            by_strategy[strat]["total_pnl"] = round(by_strategy[strat]["total_pnl"] + pnl, 2)
            if pnl > 0:
                by_strategy[strat]["winners"] += 1
        for v in by_strategy.values():
            v["win_rate"] = round(v["winners"] / v["trades"], 3) if v["trades"] else 0.0
            v["avg_pnl"] = round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0.0

        # By-underlying breakdown
        by_underlying: dict[str, dict] = {}
        for row in rows:
            sym = row[1]
            pnl = float(row[2])
            if sym not in by_underlying:
                by_underlying[sym] = {"trades": 0, "total_pnl": 0.0, "winners": 0}
            by_underlying[sym]["trades"] += 1
            by_underlying[sym]["total_pnl"] = round(by_underlying[sym]["total_pnl"] + pnl, 2)
            if pnl > 0:
                by_underlying[sym]["winners"] += 1
        for v in by_underlying.values():
            v["win_rate"] = round(v["winners"] / v["trades"], 3) if v["trades"] else 0.0

        return {
            "open_trades": open_rows,
            "closed_trades": count,
            "total_pnl": round(total, 2),
            "winners": winners,
            "losers": losers,
            "breakeven": breakeven,
            "win_rate": round(winners / count, 3) if count else 0.0,
            "avg_pnl": round(total / count, 2) if count else 0.0,
            "max_win": max(pnls),
            "max_loss": min(pnls),
            "by_strategy": by_strategy,
            "by_underlying": by_underlying,
        }

    def _count_open(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status = 'open'"
            ).fetchone()
        return row[0] if row else 0

    def _get_by_id(self, trade_id: int) -> JournalEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE id = ?", (trade_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    @staticmethod
    def _row_to_entry(row: tuple) -> JournalEntry:
        legs_data = json.loads(row[4])
        legs = [OrderLeg(**leg) for leg in legs_data]
        return JournalEntry(
            id=row[0],
            timestamp=row[1],
            underlying=row[2],
            strategy_type=StrategyType(row[3]),
            legs=legs,
            entry_price=Decimal(row[5]),
            exit_price=Decimal(row[6]) if row[6] is not None else None,
            rationale=row[7] or "",
            profit_target=Decimal(row[8]) if row[8] is not None else None,
            stop_loss=Decimal(row[9]) if row[9] is not None else None,
            pnl=Decimal(row[10]) if row[10] is not None else None,
            status=TradeStatus(row[11]),
        )
