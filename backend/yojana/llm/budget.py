"""Proactive per-provider usage budgeting backed by SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from yojana.config import ProviderConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    ts REAL NOT NULL,
    requests INTEGER NOT NULL DEFAULT 1,
    tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_provider_ts ON usage (provider, ts);
"""


class Usage(BaseModel):
    requests: int = 0
    tokens: int = 0


def _day_start(now: float) -> float:
    dt = datetime.fromtimestamp(now, tz=UTC)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class UsageTracker:
    """Records requests and tokens per provider and checks them against limits.

    Daily windows follow the UTC calendar day, which is how the free tiers used
    here reset. Minute windows are rolling.
    """

    def __init__(self, db_path: Path | str, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def record(self, provider: str, tokens: int, requests: int = 1) -> int:
        """Record a request and return its row id so tokens can be corrected later."""
        now = self._clock()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO usage (provider, ts, requests, tokens) VALUES (?, ?, ?, ?)",
                (provider, now, requests, max(tokens, 0)),
            )
            self._conn.execute("DELETE FROM usage WHERE ts < ?", (now - 3 * 86400,))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def update_tokens(self, row_id: int, tokens: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE usage SET tokens = ? WHERE id = ?", (max(tokens, 0), row_id))
            self._conn.commit()

    def _sum_since(self, provider: str, since: float) -> Usage:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(tokens), 0) "
                "FROM usage WHERE provider = ? AND ts >= ?",
                (provider, since),
            ).fetchone()
        return Usage(requests=int(row[0]), tokens=int(row[1]))

    def minute(self, provider: str) -> Usage:
        return self._sum_since(provider, self._clock() - 60.0)

    def today(self, provider: str) -> Usage:
        return self._sum_since(provider, _day_start(self._clock()))

    def check(self, cfg: ProviderConfig, estimated_tokens: int) -> str | None:
        """Return why calling `cfg` now would exceed a limit, or None if it fits."""
        minute = self.minute(cfg.name)
        day = self.today(cfg.name)
        if cfg.rpm is not None and minute.requests + 1 > cfg.rpm:
            return f"requests per minute limit ({cfg.rpm}) reached"
        if cfg.tpm is not None and minute.tokens + estimated_tokens > cfg.tpm:
            return f"tokens per minute limit ({cfg.tpm}) would be exceeded"
        if cfg.rpd is not None and day.requests + 1 > cfg.rpd:
            return f"requests per day limit ({cfg.rpd}) reached"
        if cfg.tpd is not None and day.tokens + estimated_tokens > cfg.tpd:
            return f"tokens per day limit ({cfg.tpd}) would be exceeded"
        return None

    def daily_exhausted(self, cfg: ProviderConfig) -> bool:
        day = self.today(cfg.name)
        return (cfg.rpd is not None and day.requests >= cfg.rpd) or (
            cfg.tpd is not None and day.tokens >= cfg.tpd
        )
