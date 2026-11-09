"""Deterministic stand-ins for the embedding and cross-encoder models."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from yojana.index.bm25 import tokenize

DIM = 128


def _bucket(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % DIM


class HashingModel:
    """Bag-of-words hashing 'embedding': similar wording gives similar vectors."""

    def __init__(self) -> None:
        self.calls = 0

    def get_sentence_embedding_dimension(self) -> int:
        return DIM

    def encode(self, texts: Sequence[str], **_: object) -> np.ndarray:
        self.calls += 1
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text.removeprefix("query: ").removeprefix("passage: ")):
                out[row, _bucket(token)] += 1.0
            norm = np.linalg.norm(out[row])
            if norm:
                out[row] /= norm
        return out


class OverlapCrossEncoder:
    """Scores a pair by the share of query terms that appear in the passage."""

    def predict(self, pairs: Sequence[tuple[str, str]], **_: object) -> list[float]:
        scores = []
        for query, passage in pairs:
            terms = set(tokenize(query))
            words = set(tokenize(passage))
            scores.append(len(terms & words) / len(terms) if terms else 0.0)
        return scores


class FakeGateway:
    """Answers `complete_json` / `complete` / `stream` from canned replies."""

    def __init__(self, replies: list[object] | None = None, provider: str = "fake") -> None:
        from yojana.llm.tokens import TokenCounter

        class _Counter(TokenCounter):
            def count(self, text: str) -> int:
                return self.heuristic(text)

        self.counter = _Counter()
        self.replies = list(replies or [])
        self.provider = provider
        self.calls: list[dict[str, object]] = []

    def _next(self) -> object:
        if not self.replies:
            raise AssertionError("FakeGateway ran out of replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def complete_json(self, messages, schema, **kwargs):
        from yojana.llm.gateway import LLMResult

        self.calls.append({"messages": messages, "schema": schema, **kwargs})
        parsed = schema.model_validate(self._next())
        text = parsed.model_dump_json()
        return parsed, LLMResult(text=text, provider=self.provider, model="fake-1", parsed=parsed)

    async def complete(self, messages, **kwargs):
        from yojana.llm.gateway import LLMResult

        self.calls.append({"messages": messages, **kwargs})
        return LLMResult(text=str(self._next()), provider=self.provider, model="fake-1")

    async def stream(self, messages, **kwargs):
        from yojana.llm.gateway import ProviderStarted, StreamDone, TokenDelta

        self.calls.append({"messages": messages, **kwargs})
        text = str(self._next())
        yield ProviderStarted(self.provider, self.provider.title(), "fake-1", offline=False)
        for piece in text.split(" "):
            yield TokenDelta(piece + " ")
        yield StreamDone(self.provider, text)

    def max_input_tokens(self, *, sensitive: bool = False) -> int:
        return 6000

    def status(self) -> list[dict[str, object]]:
        return []

    async def aclose(self) -> None:
        return None
