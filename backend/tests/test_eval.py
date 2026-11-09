from __future__ import annotations

from pathlib import Path

import pytest

from yojana.config import Settings
from yojana.eval.ablations import ablation_configs
from yojana.eval.metrics import (
    GoldenItem,
    Target,
    citation_precision,
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    sweep_threshold,
)
from yojana.eval.report import to_markdown, write_report
from yojana.eval.run import Evaluator, evaluate, load_golden
from yojana.ingest.models import Chunk

from fakes import FakeGateway
from test_pipeline import build_sample_index

REPO = Path(__file__).resolve().parents[2]


def chunk(scheme: str, section: str) -> Chunk:
    return Chunk(
        chunk_id=f"{scheme}::{section}",
        doc_id="d",
        scheme_id=scheme,
        scheme_name=scheme,
        state="ALL",
        category="other",
        section=section,
        heading=section,
        source_url="https://example.org",
        language="en",
        last_seen="2026-01-01",
        text="text",
        header="h",
    )


RANKED = [chunk("a", "benefits"), chunk("b", "documents"), chunk("a", "documents")]


def test_recall_mrr_and_ndcg() -> None:
    targets = [Target(scheme_id="a", section="documents")]
    assert recall_at_k(RANKED, targets, 1) == 0.0
    assert recall_at_k(RANKED, targets, 3) == 1.0
    assert reciprocal_rank(RANKED, targets) == pytest.approx(1 / 3)
    assert ndcg_at_k(RANKED, targets, 5, relevant_available=1) == pytest.approx(0.5)
    two = [Target(scheme_id="a", section="documents"), Target(scheme_id="c")]
    assert recall_at_k(RANKED, two, 5) == 0.5


def test_scheme_level_targets_match_any_section() -> None:
    assert reciprocal_rank(RANKED, [Target(scheme_id="a")]) == 1.0
    assert ndcg_at_k(RANKED, [Target(scheme_id="a")], 5, relevant_available=2) == pytest.approx(
        (1 + 1 / 2) / (1 + 1 / 1.5849625007211562)
    )


def test_citation_precision_and_percentiles() -> None:
    assert citation_precision(RANKED[:2], [Target(scheme_id="a")]) == 0.5
    assert citation_precision([], [Target(scheme_id="a")]) is None
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([5], 95) == 5
    assert percentile([], 50) == 0.0


def test_threshold_sweep_picks_separating_value() -> None:
    best, sweep = sweep_threshold([(0.9, True), (0.7, True), (0.2, False), (None, False)])
    assert best is not None and 0.2 < best <= 0.7
    assert len(sweep) == 20
    assert sweep_threshold([(0.9, True)])[0] is None


def test_golden_loader_skips_unverified(tmp_path: Path) -> None:
    path = tmp_path / "g.jsonl"
    path.write_text(
        GoldenItem(id="1", question="q", verified=True).model_dump_json()
        + "\n"
        + GoldenItem(id="2", question="q", verified=False).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    items, skipped = load_golden(path)
    assert [i.id for i in items] == ["1"] and skipped == 1


def test_ablation_configs_cover_the_five_variants(settings: Settings) -> None:
    configs = ablation_configs(settings.retrieval())
    assert list(configs) == ["dense", "bm25", "hybrid", "hybrid_rerank", "hybrid_rerank_headers"]
    assert configs["hybrid_rerank_headers"].contextual_headers
    assert not configs["hybrid_rerank"].contextual_headers
    assert all(c.final_top_k == 10 for c in configs.values())


async def test_full_suite_on_sample_corpus(settings: Settings) -> None:
    retriever = build_sample_index(settings)
    golden = REPO / "data" / "eval" / "sample_golden.jsonl"
    items, _ = load_golden(golden)
    answers = ["Aadhaar card is needed [1]."] * 40
    judge = [{"claims": [{"claim": "Aadhaar card is needed", "supported": True}]}] * 40
    gateway = FakeGateway([x for pair in zip(answers, judge, strict=True) for x in pair])

    report = await evaluate(settings, golden, retriever=retriever, gateway=gateway)

    names = [r["name"] for r in report["runs"]]
    assert names == [
        "dense",
        "bm25",
        "hybrid",
        "hybrid_rerank",
        "hybrid_rerank_headers",
        "configured",
    ]
    bm25 = next(r for r in report["runs"] if r["name"] == "bm25")
    assert bm25["status"] == "ok"
    assert 0.0 <= bm25["retrieval"]["recall@5"] <= 1.0
    assert bm25["questions"] == sum(1 for i in items if i.answerable)
    assert report["corpus"] == "sample"
    assert report["abstention"]["recommended_threshold"] is not None
    generation = report["generation"]
    assert generation["status"] == "ok"
    assert generation["faithfulness"] == 1.0
    assert generation["unanswerable_questions"] == 4
    judge_calls = [c for c in gateway.calls if c.get("task") == "judge"]
    assert judge_calls and all(c["exclude"] == ["fake"] for c in judge_calls)

    json_path, md_path = write_report(report, settings.reports_dir)
    assert json_path.is_file() and "| BM25 only |" in md_path.read_text(encoding="utf-8")


def test_run_is_marked_skipped_when_models_fail(settings: Settings) -> None:
    retriever = build_sample_index(settings)

    class Broken:
        def encode(self, *args, **kwargs):
            raise OSError("model download blocked\nmore detail")

    retriever.embedder._model = Broken()
    retriever.embedder._query_cache.clear()
    golden, _ = load_golden(REPO / "data" / "eval" / "sample_golden.jsonl")
    evaluator = Evaluator(retriever, golden)
    run = evaluator.retrieval_run("dense", ablation_configs(retriever.cfg)["dense"])
    assert run["status"] == "skipped"
    assert run["reason"] == "embedding model unavailable: model download blocked"
    assert "skipped" in to_markdown(
        {
            "created_at": "x",
            "corpus": "sample",
            "golden_file": "g",
            "questions": 1,
            "answerable": 1,
            "unanswerable": 0,
            "runs": [run],
        }
    )


def test_runs_without_dense_index_are_skipped_not_scored(settings: Settings) -> None:
    retriever = build_sample_index(settings)
    retriever.store = None
    golden, _ = load_golden(REPO / "data" / "eval" / "sample_golden.jsonl")
    evaluator = Evaluator(retriever, golden)
    configs = ablation_configs(retriever.cfg)
    assert evaluator.retrieval_run("hybrid", configs["hybrid"])["status"] == "skipped"
    assert evaluator.retrieval_run("bm25", configs["bm25"])["status"] == "ok"
