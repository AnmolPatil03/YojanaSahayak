"""SQLite response cache so repeated prompts (evaluation reruns) cost no quota."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""
_WS = re.compile(r"\s+")


def normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Collapse whitespace so formatting-only differences share a cache entry."""
    return [
        {
            "role": str(m.get("role", "")),
            "content": _WS.sub(" ", str(m.get("content") or "")).strip(),
        }
        for m in messages
    ]


def cache_key(
    messages: Sequence[Mapping[str, Any]], params: Mapping[str, Any], task_type: str
) -> str:
    """sha256 over normalized messages, call parameters and task type."""
    payload = json.dumps(
        {"messages": normalize_messages(messages), "params": dict(params), "task": task_type},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    """Key-value store of completed LLM responses with a time-to-live."""

    def __init__(
        self,
        db_path: Path | str,
        ttl_seconds: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, created_at FROM responses WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        if self._clock() - float(row[1]) > self.ttl_seconds:
            with self._lock:
                self._conn.execute("DELETE FROM responses WHERE key = ?", (key,))
                self._conn.commit()
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses (key, value, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(dict(value), ensure_ascii=False), self._clock()),
            )
            self._conn.commit()

    def purge_expired(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM responses WHERE created_at < ?", (self._clock() - self.ttl_seconds,)
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
