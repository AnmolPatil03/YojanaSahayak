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
