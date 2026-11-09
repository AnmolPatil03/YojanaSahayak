"""Retrieval and generation metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel, Field

from yojana.ingest.models import Chunk


class Target(BaseModel):
    """A passage that answers a golden question: a scheme, optionally one section."""

    scheme_id: str
    section: str | None = None

    def matches(self, chunk: Chunk) -> bool:
        return chunk.scheme_id == self.scheme_id and (
            self.section is None or chunk.section == self.section
        )


class GoldenItem(BaseModel):
    """One line of `golden.jsonl`."""

    id: str
    question: str
    language: str = "en"
    answerable: bool = True
    relevant: list[Target] = Field(default_factory=list)
    reference_answer: str | None = None
    verified: bool = False
    notes: str | None = None


def is_relevant(chunk: Chunk, targets: Sequence[Target]) -> bool:
    return any(t.matches(chunk) for t in targets)


def recall_at_k(ranked: Sequence[Chunk], targets: Sequence[Target], k: int) -> float:
    """Share of targets matched by at least one of the top-k chunks."""
    if not targets:
        return 0.0
    top = ranked[:k]
    hits = sum(1 for target in targets if any(target.matches(c) for c in top))
    return hits / len(targets)


def reciprocal_rank(ranked: Sequence[Chunk], targets: Sequence[Target]) -> float:
    for rank, chunk in enumerate(ranked, start=1):
        if is_relevant(chunk, targets):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked: Sequence[Chunk], targets: Sequence[Target], k: int, relevant_available: int
) -> float:
    """Binary-gain nDCG@k; the ideal list has `relevant_available` relevant chunks."""
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk in enumerate(ranked[:k], start=1)
        if is_relevant(chunk, targets)
    )
    ideal_hits = min(k, relevant_available)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def citation_precision(cited: Sequence[Chunk], targets: Sequence[Target]) -> float | None:
    """Share of cited chunks that are relevant; None when nothing was cited."""
    if not cited:
        return None
    return sum(1 for chunk in cited if is_relevant(chunk, targets)) / len(cited)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def sweep_threshold(
    scores: Sequence[tuple[float | None, bool]],
    thresholds: Sequence[float] | None = None,
) -> tuple[float | None, list[dict[str, float]]]:
    """Pick the abstention threshold with the best balanced accuracy.

    Args:
        scores: (top retrieval score, question is answerable) pairs.
        thresholds: Candidate thresholds; 0.00 to 0.95 in steps of 0.05 by default.

    Returns:
        The best threshold (None without both kinds of question) and the full sweep.
    """
    thresholds = thresholds or [round(i * 0.05, 2) for i in range(20)]
    answerable = [s for s, ok in scores if ok]
    unanswerable = [s for s, ok in scores if not ok]
    sweep: list[dict[str, float]] = []
    best: tuple[float, float] | None = None
    for tau in thresholds:
        tp = sum(1 for s in answerable if s is not None and s >= tau)
        tn = sum(1 for s in unanswerable if s is None or s < tau)
        accuracy = (tp + tn) / len(scores) if scores else 0.0
        parts = []
        if answerable:
            parts.append(tp / len(answerable))
        if unanswerable:
            parts.append(tn / len(unanswerable))
        balanced = sum(parts) / len(parts) if parts else 0.0
        sweep.append(
            {"threshold": tau, "accuracy": round(accuracy, 4), "balanced": round(balanced, 4)}
        )
        if answerable and unanswerable and (best is None or balanced > best[1]):
            best = (tau, balanced)
    return (best[0] if best else None), sweep
