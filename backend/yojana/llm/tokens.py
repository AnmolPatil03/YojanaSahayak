"""Token estimation shared by budgeting and chunking."""

from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_PER_MESSAGE_OVERHEAD = 4


class TokenCounter:
    """Counts tokens with tiktoken, falling back to a character heuristic.

    tiktoken downloads its encoding file on first use. On an offline machine that
    fails, and a conservative estimate is still better than refusing to work.
    """

    def __init__(self, encoding: str = "cl100k_base", cache_dir: Path | None = None) -> None:
        self._encoding_name = encoding
        self._cache_dir = cache_dir
        self._encoding: Any = None
        self._failed = False
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._encoding is not None or self._failed:
            return self._encoding
        with self._lock:
            if self._encoding is not None or self._failed:
                return self._encoding
            if self._cache_dir is not None:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(self._cache_dir))
            try:
                import tiktoken

                self._encoding = tiktoken.get_encoding(self._encoding_name)
            except Exception as exc:
                logger.warning("tiktoken unavailable, using heuristic token counts: %s", exc)
                self._failed = True
        return self._encoding

    @staticmethod
    def heuristic(text: str) -> int:
        """Rough upper-leaning estimate; Devanagari costs far more tokens per char."""
        if not text:
            return 0
        devanagari = len(_DEVANAGARI.findall(text))
        other = len(text) - devanagari
        return math.ceil(other / 3.5 + devanagari / 1.5)

    def count(self, text: str) -> int:
        """Return the number of tokens in `text`."""
        if not text:
            return 0
        encoding = self._load()
        if encoding is None:
            return self.heuristic(text)
        return len(encoding.encode(text, disallowed_special=()))

    def count_messages(self, messages: Iterable[Mapping[str, Any]]) -> int:
        """Return the approximate prompt size of a chat message list."""
        total = 2
        for message in messages:
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            total += self.count(content) + _PER_MESSAGE_OVERHEAD
        return total

    def split_by_tokens(self, text: str, max_tokens: int) -> list[str]:
        """Split text into pieces of at most `max_tokens`, cutting on whitespace."""
        words = text.split()
        pieces: list[str] = []
        current: list[str] = []
        size = 0
        for word in words:
            cost = self.count(" " + word)
            if current and size + cost > max_tokens:
                pieces.append(" ".join(current))
                current, size = [], 0
            current.append(word)
            size += cost
        if current:
            pieces.append(" ".join(current))
        return pieces


_default: TokenCounter | None = None


def default_counter() -> TokenCounter:
    """Process-wide counter that caches the encoding under `data/cache/tiktoken`."""
    global _default
    if _default is None:
        from yojana.config import get_settings

        _default = TokenCounter(cache_dir=get_settings().cache_dir / "tiktoken")
    return _default
