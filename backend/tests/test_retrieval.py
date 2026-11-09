from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fakes import HashingModel, OverlapCrossEncoder

from yojana.config import EmbeddingConfig, RerankerConfig, RetrievalConfig
from yojana.index.bm25 import BM25Index
from yojana.index.embedder import Embedder
from yojana.index.store import ChunkStore, VectorStore
from yojana.ingest.models import Chunk
from yojana.retrieve.filters import SearchFilters, build_filters
from yojana.retrieve.hybrid import HybridRetriever
from yojana.retrieve.rerank import Reranker


def chunk(cid: str, scheme: str, state: str, category: str, section: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid,
        doc_id="d",
        scheme_id=scheme,
        scheme_name=scheme.replace("-", " ").title(),
        state=state,
        category=category,
        section=section,
        heading=section.title(),
        source_url=f"https://example.org/{scheme}",
        language="en",
        last_seen="2026-01-01",
        text=text,
        header=f"{scheme.replace('-', ' ').title()} | {section.title()}",
    )


CHUNKS = [
    chunk("alpha-1", "test-scheme-alpha", "ALL", "education", "eligibility",
          "Graduate students aged 17 to 25 with family income below the limit can apply."),
    chunk("alpha-2", "test-scheme-alpha", "ALL", "education", "documents",
          "Aadhaar card, income certificate, caste certificate and bonafide certificate."),
    chunk("beta-1", "test-scheme-beta", "Maharashtra", "agriculture", "eligibility",
          "Farmers living in rural Maharashtra aged 18 or more are eligible."),
    chunk("beta-2", "test-scheme-beta", "Maharashtra", "agriculture", "benefits",
          "Seed assistance every crop season and an irrigation equipment subsidy."),
    chunk("gamma-1", "test-scheme-gamma", "ALL", "business", "benefits",
          "Seed grant for startup prototype development and one year of mentoring."),
    chunk("delta-1", "test-scheme-delta", "Karnataka", "women_child", "eligibility",
          "Women with a disability living in Karnataka who want to start a business."),
]  # fmt: skip


@pytest.fixture
def retriever(tmp_path: Path) -> HybridRetriever:
    embedder = Embedder(EmbeddingConfig(), factory=lambda cfg: HashingModel())
    store = VectorStore(tmp_path / "lancedb")
    vectors = embedder.encode_passages([c.embed_text for c in CHUNKS])
    plain = embedder.encode_passages([c.text for c in CHUNKS])
    store.upsert(CHUNKS, vectors, plain)
    ids = [c.chunk_id for c in CHUNKS]
    return HybridRetriever(
        RetrievalConfig(abstain_threshold=0.3, dense_abstain_threshold=0.2),
        ChunkStore(CHUNKS),
        store=store,
        bm25=BM25Index.build(ids, [c.embed_text for c in CHUNKS]),
        bm25_plain=BM25Index.build(ids, [c.text for c in CHUNKS]),
        embedder=embedder,
        reranker=Reranker(RerankerConfig(), factory=lambda cfg: OverlapCrossEncoder()),
    )


def test_hybrid_rerank_finds_the_right_chunk(retriever: HybridRetriever) -> None:
    stages: list[tuple[str, str]] = []
    result = retriever.retrieve(
        "documents needed income certificate aadhaar",
        on_stage=lambda name, status, ms: stages.append((name, status)),
    )
    assert result.chunks[0].chunk.chunk_id == "alpha-2"
    assert not result.abstained
    assert result.chunks[0].rerank_score is not None
    assert [s for s, status in stages if status == "end"] == ["searching", "fusing", "reranking"]
    assert set(result.timings) == {"searching", "fusing", "reranking"}
    assert len(result.chunks) <= retriever.cfg.final_top_k


def test_state_filter_applies_to_both_retrievers(retriever: HybridRetriever) -> None:
    filters = SearchFilters(states=("Karnataka", "ALL"))
    for mode in ("dense", "bm25", "hybrid"):
        cfg = retriever.cfg.model_copy(update={"mode": mode, "rerank": False})
        result = retriever.retrieve("farmers seed assistance eligibility", filters, cfg=cfg)
        assert all(c.chunk.state in ("Karnataka", "ALL") for c in result.candidates), mode


def test_category_filter_falls_back_when_empty(retriever: HybridRetriever) -> None:
    filters = SearchFilters(states=("Karnataka", "ALL"), categories=("agriculture",))
    result = retriever.retrieve("seed grant startup", filters)
    assert result.filters.categories == ()
    assert result.chunks[0].chunk.scheme_id == "test-scheme-gamma"


def test_modes_change_which_retrievers_run(retriever: HybridRetriever) -> None:
    dense = retriever.retrieve(
        "startup seed grant",
        cfg=retriever.cfg.model_copy(update={"mode": "dense", "rerank": False}),
    )
    sparse = retriever.retrieve(
        "startup seed grant", cfg=retriever.cfg.model_copy(update={"mode": "bm25", "rerank": False})
    )
    assert all(c.bm25_rank is None for c in dense.candidates)
    assert all(c.dense_rank is None for c in sparse.candidates)
    assert dense.chunks[0].chunk.chunk_id == sparse.chunks[0].chunk.chunk_id == "gamma-1"


def test_contextual_header_switch_uses_plain_index(retriever: HybridRetriever) -> None:
    cfg = retriever.cfg.model_copy(
        update={"mode": "bm25", "rerank": False, "contextual_headers": False}
    )
    result = retriever.retrieve("test scheme delta", cfg=cfg)
    assert result.chunks == []
    with_headers = retriever.retrieve(
        "test scheme delta", cfg=cfg.model_copy(update={"contextual_headers": True})
    )
    assert with_headers.chunks[0].chunk.scheme_id == "test-scheme-delta"


def test_abstains_when_rerank_score_is_low(retriever: HybridRetriever) -> None:
    result = retriever.retrieve("pension for retired railway employees abroad")
    assert result.abstained
    assert result.top_score is not None and result.top_score < 0.3


def test_abstains_without_rerank_using_dense_similarity(retriever: HybridRetriever) -> None:
    cfg = retriever.cfg.model_copy(update={"rerank": False, "dense_abstain_threshold": 0.95})
    assert retriever.retrieve("startup seed grant", cfg=cfg).abstained


def test_empty_index_abstains(tmp_path: Path) -> None:
    empty = HybridRetriever(
        RetrievalConfig(),
        ChunkStore([]),
        store=None,
        bm25=BM25Index([], []),
        bm25_plain=None,
        embedder=None,
        reranker=None,
    )
    result = empty.retrieve("anything")
    assert result.abstained and result.chunks == []
    assert not empty.ready


def test_build_filters_from_query_and_profile() -> None:
    f = build_filters("scholarship for students in Kerala")
    assert f.states == ("Kerala", "ALL")
    assert f.categories[0] == "education"
    assert "state IN ('Kerala', 'ALL')" in (f.where() or "")

    from_profile = build_filters("any schemes for me?", profile_state="tamil nadu")
    assert from_profile.states == ("Tamil Nadu", "ALL")
    assert from_profile.categories == ()

    pinned = build_filters("documents", scheme_ids=["test-scheme-alpha"], sections=["documents"])
    assert pinned.categories == ()
    assert pinned.where() == "scheme_id IN ('test-scheme-alpha') AND section IN ('documents')"


def test_filters_quote_values_safely() -> None:
    assert SearchFilters(scheme_ids=("a'b",)).where() == "scheme_id IN ('a''b')"


def test_vector_store_upsert_replaces_and_deletes(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "v")
    vec = np.eye(4, dtype=np.float32)
    store.upsert(CHUNKS[:2], vec[:2])
    store.upsert(CHUNKS[:1], vec[2:3])
    assert store.count() == 2
    assert store.search(vec[2], 1)[0][0] == "alpha-1"
    store.delete(["alpha-1"])
    assert store.count() == 1
    assert not store.has_plain_vectors


def test_embedder_prefixes_and_caches_queries() -> None:
    seen: list[list[str]] = []

    class Recorder(HashingModel):
        def encode(self, texts, **kwargs):
            seen.append(list(texts))
            return super().encode(texts, **kwargs)

    embedder = Embedder(EmbeddingConfig(), factory=lambda cfg: Recorder())
    embedder.encode_query("hello")
    embedder.encode_query("hello")
    embedder.encode_passages(["a passage"])
    assert seen == [["query: hello"], ["passage: a passage"]]


def test_reranker_converts_logits_to_probabilities() -> None:
    class Logits:
        def predict(self, pairs, **kwargs):
            return [2.0, -2.0]

    reranker = Reranker(RerankerConfig(), factory=lambda cfg: Logits())
    ranked = reranker.rerank("q", [("a", "x"), ("b", "y")], top_n=1)
    assert ranked[0][0] == "a"
    assert ranked[0][1] == pytest.approx(1 / (1 + np.exp(-2.0)))
    assert len(ranked) == 1
