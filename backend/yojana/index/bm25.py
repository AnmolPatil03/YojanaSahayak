"""BM25 sparse index with a tokenizer that handles English and Devanagari."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Collection, Sequence
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

# Devanagari vowel signs and viramas are combining marks, which `\w` does not
# match, so a plain `\w+` would cut Hindi words apart at every matra. The danda
# (U+0964/U+0965) is punctuation and is excluded from the range.
_TOKEN = re.compile(r"[a-z0-9]+|[\u0900-\u0963\u0966-\u097F]+")

_STOPWORDS = frozenset(
    """
    a an and are as at be by can do does for from has have how i if in is it its me my
    of on or our so that the their them there these this to was what when where which
    who whom why will with you your am i'm im any all also about under
    का की के को से में है हैं और या पर एक यह वह ये वे भी तो ही था थी थे हो कि जो
    लिए क्या कौन कैसे मुझे मेरा मेरी मैं हम आप
    """.split()
)


def _stem(token: str) -> str:
    if not token.isascii() or len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, NFC-normalise, split into English/Devanagari words, drop stopwords."""
    text = unicodedata.normalize("NFC", text).lower()
    return [_stem(t) for t in _TOKEN.findall(text) if t not in _STOPWORDS]


class _PositiveIdfBM25(BM25Okapi):
    """BM25 with Lucene's idf, log(1 + (N - n + 0.5) / (n + 0.5)).

    The classic Okapi idf is zero or negative for terms found in half the corpus or
    more, which on a small corpus (a handful of schemes) wipes out real matches.
    """

    def _calc_idf(self, nd: dict[str, int]) -> None:
        for word, freq in nd.items():
            self.idf[word] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
        self.average_idf = sum(self.idf.values()) / len(self.idf) if self.idf else 0.0


class BM25Index:
    """BM25Okapi over chunk texts, persisted as tokens so it rebuilds without pickle."""

    def __init__(self, ids: Sequence[str], tokens: Sequence[list[str]]) -> None:
        self.ids = list(ids)
        self._tokens = [list(t) for t in tokens]
        self._position = {cid: i for i, cid in enumerate(self.ids)}
        self._bm25 = _PositiveIdfBM25(self._tokens) if any(self._tokens) else None

    @classmethod
    def build(cls, ids: Sequence[str], texts: Sequence[str]) -> BM25Index:
        return cls(ids, [tokenize(t) for t in texts])

    def __len__(self) -> int:
        return len(self.ids)

    def search(
        self, query: str, k: int, allowed: Collection[str] | None = None
    ) -> list[tuple[str, float]]:
        """Top-k (chunk_id, score) pairs with positive scores, optionally filtered."""
        if self._bm25 is None:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        scores = np.asarray(self._bm25.get_scores(terms), dtype=np.float64)
        if allowed is not None:
            mask = np.zeros(len(self.ids), dtype=bool)
            for cid in allowed:
                pos = self._position.get(cid)
                if pos is not None:
                    mask[pos] = True
            scores = np.where(mask, scores, -np.inf)
        order = np.argsort(-scores, kind="stable")[:k]
        return [(self.ids[i], float(scores[i])) for i in order if scores[i] > 0]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ids": self.ids, "tokens": self._tokens}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> BM25Index:
        if not path.is_file():
            return cls([], [])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["ids"], data["tokens"])
