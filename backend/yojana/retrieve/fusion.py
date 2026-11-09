"""Reciprocal Rank Fusion."""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists with RRF(d) = sum_i w_i / (k + rank_i(d)).

    Ranks are 1-based. Documents missing from a list contribute nothing for it.
    Ties keep the order in which a document was first seen, so results are stable.

    Args:
        rankings: One ranked list of ids per retriever, best first.
        k: Smoothing constant; 60 is the value from the original RRF paper.
        weights: Optional per-retriever weights (default 1.0 each).

    Returns:
        (id, score) pairs sorted by descending fused score.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights must match rankings")
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for index, ranking in enumerate(rankings):
        weight = 1.0 if weights is None else float(weights[index])
        seen_in_list: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen_in_list:
                continue
            seen_in_list.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank)
            if doc_id not in first_seen:
                first_seen[doc_id] = order
                order += 1
    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))
