"""Retrieval configurations compared by the evaluation harness."""

from __future__ import annotations

from yojana.config import RetrievalConfig

ABLATIONS: dict[str, dict[str, object]] = {
    "dense": {"mode": "dense", "rerank": False, "contextual_headers": False},
    "bm25": {"mode": "bm25", "rerank": False, "contextual_headers": False},
    "hybrid": {"mode": "hybrid", "rerank": False, "contextual_headers": False},
    "hybrid_rerank": {"mode": "hybrid", "rerank": True, "contextual_headers": False},
    "hybrid_rerank_headers": {"mode": "hybrid", "rerank": True, "contextual_headers": True},
}

LABELS = {
    "dense": "Dense only",
    "bm25": "BM25 only",
    "hybrid": "Hybrid (RRF)",
    "hybrid_rerank": "Hybrid + rerank",
    "hybrid_rerank_headers": "Hybrid + rerank + contextual headers",
}


def ablation_configs(base: RetrievalConfig, depth: int = 10) -> dict[str, RetrievalConfig]:
    """One config per ablation, each returning `depth` results for Recall@10."""
    return {
        name: base.model_copy(update={**changes, "final_top_k": depth})
        for name, changes in ABLATIONS.items()
    }


def needs_models(cfg: RetrievalConfig) -> tuple[bool, bool]:
    """(needs the embedding model, needs the cross-encoder)."""
    return cfg.mode in ("dense", "hybrid"), cfg.rerank
