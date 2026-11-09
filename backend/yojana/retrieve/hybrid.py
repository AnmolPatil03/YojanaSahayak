"""Hybrid retrieval: dense + BM25, fused with RRF, reranked, with abstention."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from yojana.config import RetrievalConfig, Settings
from yojana.index.bm25 import BM25Index
from yojana.index.builder import BM25_FILE, BM25_PLAIN_FILE, VECTORS_DIR
from yojana.index.embedder import Embedder
from yojana.index.store import ChunkStore, VectorStore
from yojana.ingest.models import Chunk
from yojana.retrieve.filters import SearchFilters
from yojana.retrieve.fusion import reciprocal_rank_fusion
from yojana.retrieve.rerank import Reranker

logger = logging.getLogger(__name__)

StageCallback = Callable[[str, str, float], None]


@dataclass(slots=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    dense_rank: int | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    dense_similarity: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk.chunk_id,
            "score": round(self.score, 4),
            "dense_rank": self.dense_rank,
            "bm25_rank": self.bm25_rank,
            "fused_score": None if self.fused_score is None else round(self.fused_score, 5),
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
        }


@dataclass(slots=True)
class RetrievalResult:
    query: str
    chunks: list[ScoredChunk]
    abstained: bool
    top_score: float | None
    mode: str
    filters: SearchFilters
    timings: dict[str, float] = field(default_factory=dict)
    candidates: list[ScoredChunk] = field(default_factory=list)

    @property
    def chunk_ids(self) -> list[str]:
        return [c.chunk.chunk_id for c in self.chunks]


class HybridRetriever:
    """Runs the configured retrieval pipeline over the chunk indexes.

    Every stage reads its switch from `RetrievalConfig`, and a different config can
    be passed per call so the evaluation ablations share one loaded retriever.
    """

    def __init__(
        self,
        cfg: RetrievalConfig,
        chunks: ChunkStore,
        *,
        store: VectorStore | None,
        bm25: BM25Index,
        bm25_plain: BM25Index | None,
        embedder: Embedder | None,
        reranker: Reranker | None,
    ) -> None:
        self.cfg = cfg
        self.chunks = chunks
        self.store = store
        self.bm25 = bm25
        self.bm25_plain = bm25_plain
        self.embedder = embedder
        self.reranker = reranker

    @classmethod
    def from_settings(cls, settings: Settings) -> HybridRetriever:
        cfg = settings.retrieval()
        models = settings.cache_dir / "models"
        vectors_path = settings.index_dir / VECTORS_DIR
        store = VectorStore(vectors_path) if vectors_path.exists() else None
        return cls(
            cfg,
            ChunkStore.load(settings.processed_dir),
            store=store,
            bm25=BM25Index.load(settings.index_dir / BM25_FILE),
            bm25_plain=BM25Index.load(settings.index_dir / BM25_PLAIN_FILE),
            embedder=Embedder(cfg.embedding, cache_folder=models),
            reranker=Reranker(cfg.reranker, cache_folder=models),
        )

    @property
    def ready(self) -> bool:
        return len(self.chunks) > 0

    def warmup(self) -> None:
        if self.embedder is not None and self.cfg.mode != "bm25":
            self.embedder.warmup()
        if self.reranker is not None and self.cfg.rerank:
            self.reranker.warmup()

    def _allowed_ids(self, filters: SearchFilters) -> set[str] | None:
        if filters.empty:
            return None
        return {c.chunk_id for c in self.chunks.all() if filters.allows(c)}

    def _dense(
        self, query: str, filters: SearchFilters, cfg: RetrievalConfig
    ) -> list[tuple[str, float]]:
        if self.store is None or self.embedder is None:
            return []
        vector = self.embedder.encode_query(query)
        hits = self.store.search(
            vector, cfg.dense_top_k, filters.where(), plain=not cfg.contextual_headers
        )
        return [(cid, sim) for cid, sim in hits if cid in self.chunks]

    def _sparse(
        self, query: str, filters: SearchFilters, cfg: RetrievalConfig
    ) -> list[tuple[str, float]]:
        index = self.bm25 if cfg.contextual_headers or self.bm25_plain is None else self.bm25_plain
        hits = index.search(query, cfg.bm25_top_k, self._allowed_ids(filters))
        return [(cid, score) for cid, score in hits if cid in self.chunks]

    def _search(
        self, query: str, filters: SearchFilters, cfg: RetrievalConfig
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        dense = self._dense(query, filters, cfg) if cfg.mode in ("dense", "hybrid") else []
        sparse = self._sparse(query, filters, cfg) if cfg.mode in ("bm25", "hybrid") else []
        return dense, sparse

    def retrieve(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        cfg: RetrievalConfig | None = None,
        on_stage: StageCallback | None = None,
    ) -> RetrievalResult:
        """Retrieve the top passages for `query`.

        Args:
            query: Standalone search query.
            filters: Metadata filters applied to both retrievers.
            cfg: Override of the retrieval config (used by ablations).
            on_stage: Called as (stage, "start" | "end", elapsed_ms) for progress events.
        """
        cfg = cfg or self.cfg
        filters = filters or SearchFilters()
        timings: dict[str, float] = {}

        def stage(name: str) -> _Stage:
            return _Stage(name, timings, on_stage)

        with stage("searching"):
            dense, sparse = self._search(query, filters, cfg)
            if not dense and not sparse and filters.categories:
                filters = filters.without_categories()
                dense, sparse = self._search(query, filters, cfg)

        with stage("fusing"):
            dense_rank = {cid: i for i, (cid, _) in enumerate(dense, start=1)}
            dense_sim = dict(dense)
            sparse_rank = {cid: i for i, (cid, _) in enumerate(sparse, start=1)}
            rankings = [r for r in ([c for c, _ in dense], [c for c, _ in sparse]) if r]
            fused = reciprocal_rank_fusion(rankings, k=cfg.rrf_k) if rankings else []
            candidates = [
                ScoredChunk(
                    chunk=self.chunks.get(cid),  # type: ignore[arg-type]
                    score=score,
                    dense_rank=dense_rank.get(cid),
                    bm25_rank=sparse_rank.get(cid),
                    fused_score=score,
                    dense_similarity=dense_sim.get(cid),
                )
                for cid, score in fused
            ]

        top_score: float | None = None
        if cfg.rerank and self.reranker is not None and candidates:
            with stage("reranking"):
                pool = candidates[: cfg.rerank_candidates]
                text_of = {
                    c.chunk.chunk_id: c.chunk.embed_text if cfg.contextual_headers else c.chunk.text
                    for c in pool
                }
                ranked = self.reranker.rerank(
                    query, [(cid, text_of[cid]) for cid in text_of], cfg.final_top_k
                )
                by_id = {c.chunk.chunk_id: c for c in pool}
                final = []
                for cid, score in ranked:
                    item = by_id[cid]
                    item.rerank_score = score
                    item.score = score
                    final.append(item)
                top_score = final[0].rerank_score if final else None
                abstained = top_score is None or top_score < cfg.abstain_threshold
        else:
            final = candidates[: cfg.final_top_k]
            similarities = [c.dense_similarity for c in final if c.dense_similarity is not None]
            if similarities:
                top_score = max(similarities)
                abstained = top_score < cfg.dense_abstain_threshold
            else:
                top_score = final[0].score if final else None
                abstained = not final

        return RetrievalResult(
            query=query,
            chunks=final,
            abstained=abstained,
            top_score=top_score,
            mode=cfg.mode,
            filters=filters,
            timings=timings,
            candidates=candidates,
        )


class _Stage:
    def __init__(
        self, name: str, timings: dict[str, float], callback: StageCallback | None
    ) -> None:
        self.name = name
        self.timings = timings
        self.callback = callback
        self.start = 0.0

    def __enter__(self) -> _Stage:
        self.start = time.perf_counter()
        if self.callback:
            self.callback(self.name, "start", 0.0)
        return self

    def __exit__(self, *exc: object) -> None:
        elapsed = (time.perf_counter() - self.start) * 1000
        self.timings[self.name] = round(elapsed, 1)
        if self.callback:
            self.callback(self.name, "end", elapsed)
