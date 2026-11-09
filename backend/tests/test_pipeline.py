from __future__ import annotations

import json
import shutil
from pathlib import Path

from yojana.config import Settings
from yojana.ingest.pipeline import build_documents, load_chunks
from yojana.ingest.registry import SchemeRegistry
from yojana.llm.tokens import TokenCounter

REPO = Path(__file__).resolve().parents[2]


class OfflineCounter(TokenCounter):
    def count(self, text: str) -> int:
        return self.heuristic(text)


def write_page(path: Path, name: str, eligibility: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<h1>{name}</h1><h2>Benefits</h2><p>Fictional benefit.</p>"
        f"<h2>Eligibility</h2><p>{eligibility}</p>",
        encoding="utf-8",
    )


def test_ingestion_is_incremental(settings: Settings) -> None:
    counter = OfflineCounter()
    write_page(settings.raw_dir / "a.html", "Test Scheme Alpha", "Must be a student.")
    write_page(settings.raw_dir / "b.html", "Test Scheme Beta", "Must be a farmer.")
    changes: list[tuple[int, int]] = []

    def on_changed(new, removed) -> None:
        changes.append((len(new), len(removed)))

    first = build_documents(settings, counter=counter, on_changed=on_changed)
    assert sorted(first.added) == ["data/raw/a.html", "data/raw/b.html"]
    assert first.schemes_total == 2

    second = build_documents(settings, counter=counter, on_changed=on_changed)
    assert not second.changed and second.unchanged == 2

    write_page(settings.raw_dir / "a.html", "Test Scheme Alpha", "Must be a graduate student.")
    third = build_documents(settings, counter=counter, on_changed=on_changed)
    assert third.updated == ["data/raw/a.html"]
    assert third.changed_schemes == {"test-scheme-alpha"}

    (settings.raw_dir / "b.html").unlink()
    fourth = build_documents(settings, counter=counter, on_changed=on_changed)
    assert fourth.removed == ["data/raw/b.html"]
    assert fourth.schemes_total == 1

    assert changes[0] == (4, 0)
    # Updated chunks keep their ids, so they are upserted rather than reported removed.
    assert changes[1] == (2, 0)
    assert changes[2] == (0, 2)
    chunks = load_chunks(settings.processed_dir)
    assert {c.scheme_id for c in chunks} == {"test-scheme-alpha"}
    assert any("graduate student" in c.text for c in chunks)


def test_sample_documents_ingest_with_manifest_urls(settings: Settings) -> None:
    shutil.copytree(REPO / "data" / "sample", settings.sample_dir)
    page = settings.raw_dir / "site.test" / "schemes-x.html"
    write_page(page, "Test Scheme Omega", "Must be fictional.")
    (settings.raw_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "url": "https://site.test/schemes/test-scheme-omega",
                "path": "site.test/schemes-x.html",
                "sha256": "x",
                "content_type": "text/html",
                "status": 200,
                "fetched_at": "2026-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_documents(settings, include_sample=True, counter=OfflineCounter())

    assert not report.failed
    registry = SchemeRegistry.load(settings.processed_dir / "schemes.json")
    ids = {r.scheme_id for r in registry.all()}
    assert {
        "test-scheme-alpha",
        "test-scheme-beta",
        "test-scheme-gamma",
        "test-scheme-delta",
    } <= ids
    omega = registry.get("test-scheme-omega")
    assert omega is not None and omega.source_urls == [
        "https://site.test/schemes/test-scheme-omega"
    ]
    assert registry.get("test-scheme-alpha").is_sample
    assert registry.get("test-scheme-beta").state == "Maharashtra"
    assert registry.find_mentions("tell me about test scheme delta") == ["test-scheme-delta"]


def build_sample_index(settings: Settings):
    from fakes import HashingModel, OverlapCrossEncoder

    from yojana.index.bm25 import BM25Index
    from yojana.index.builder import BM25_FILE, BM25_PLAIN_FILE, IndexBuilder
    from yojana.index.embedder import Embedder
    from yojana.index.store import ChunkStore
    from yojana.retrieve.hybrid import HybridRetriever
    from yojana.retrieve.rerank import Reranker

    shutil.copytree(REPO / "data" / "sample", settings.sample_dir, dirs_exist_ok=True)
    cfg = settings.retrieval()
    embedder = Embedder(cfg.embedding, factory=lambda c: HashingModel())
    builder = IndexBuilder(settings, embedder=embedder)
    build_documents(
        settings, include_sample=True, counter=OfflineCounter(), on_changed=builder.apply_changes
    )
    builder.rebuild_sparse()
    return HybridRetriever(
        cfg.model_copy(update={"abstain_threshold": 0.3}),
        ChunkStore.load(settings.processed_dir),
        store=builder.store,
        bm25=BM25Index.load(settings.index_dir / BM25_FILE),
        bm25_plain=BM25Index.load(settings.index_dir / BM25_PLAIN_FILE),
        embedder=embedder,
        reranker=Reranker(cfg.reranker, factory=lambda c: OverlapCrossEncoder()),
    )


def test_sample_set_is_searchable_end_to_end(settings: Settings) -> None:
    from yojana.retrieve.filters import build_filters

    retriever = build_sample_index(settings)

    docs = retriever.retrieve("documents required for test scheme delta disability certificate")
    assert docs.chunks[0].chunk.chunk_id.startswith("test-scheme-delta")
    assert docs.chunks[0].chunk.section == "documents"

    hindi = retriever.retrieve("परीक्षण योजना बीटा आवश्यक दस्तावेज़ भूमि रिकॉर्ड")
    assert hindi.chunks[0].chunk.scheme_id == "test-scheme-beta"

    filters = build_filters("schemes for farmers", profile_state="Karnataka")
    karnataka = retriever.retrieve("seed assistance for farmers", filters)
    assert all(c.chunk.state in ("Karnataka", "ALL") for c in karnataka.candidates)
