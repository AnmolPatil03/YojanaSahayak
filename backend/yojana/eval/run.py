"""Evaluation harness: retrieval ablations, answer quality, abstention and latency.

python -m yojana.eval.run --golden data/eval/golden.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from yojana.config import RetrievalConfig, Settings, get_settings
from yojana.eval.ablations import LABELS, ablation_configs, needs_models
from yojana.eval.metrics import (
    GoldenItem,
    citation_precision,
    mean,
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    sweep_threshold,
)
from yojana.eval.report import write_report
from yojana.generate.answer import AnswerGenerator
from yojana.generate.prompts import format_sources
from yojana.llm.gateway import AllProvidersExhausted, LLMGateway
from yojana.logging_setup import configure_logging
from yojana.retrieve.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

K_VALUES = (1, 3, 5, 10)


class _Claim(BaseModel):
    claim: str
    supported: bool


class JudgeVerdict(BaseModel):
    claims: list[_Claim] = Field(default_factory=list)


JUDGE_PROMPT = """You check whether an answer is faithful to its sources. Split the \
answer into its factual claims about schemes (ignore greetings and suggestions). For each \
claim decide whether the numbered sources explicitly support it. Return JSON: \
{"claims": [{"claim": "...", "supported": true}]}"""


def load_golden(path: Path) -> tuple[list[GoldenItem], int]:
    """Verified items from a golden file, plus the count of unverified lines skipped."""
    if not path.is_file():
        return [], 0
    items: list[GoldenItem] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = GoldenItem.model_validate_json(line)
        if item.verified:
            items.append(item)
        else:
            skipped += 1
    return items, skipped


class Evaluator:
    """Runs every measurement against one loaded retriever and gateway."""

    def __init__(
        self,
        retriever: HybridRetriever,
        golden: Sequence[GoldenItem],
        gateway: LLMGateway | None = None,
        *,
        use_cache: bool = True,
    ) -> None:
        self.retriever = retriever
        self.golden = list(golden)
        self.gateway = gateway
        self.use_cache = use_cache

    def _relevant_available(self, item: GoldenItem) -> int:
        return sum(
            1
            for chunk in self.retriever.chunks.all()
            if any(t.matches(chunk) for t in item.relevant)
        )

    def missing_requirement(self, cfg: RetrievalConfig) -> str | None:
        """Why `cfg` cannot run as configured, or None.

        The serving path quietly falls back to BM25 when the dense index or a model is
        missing; an evaluation must not, or a "hybrid" score would really be BM25.
        """
        dense_needed, rerank_needed = needs_models(cfg)
        retriever = self.retriever
        if dense_needed:
            if retriever.store is None or retriever.store.count() == 0:
                return "no dense index (run ingestion with the embedding model available)"
            if retriever.embedder is None:
                return "no embedding model configured"
            try:
                retriever.embedder.encode_query("probe")
            except Exception as exc:
                return f"embedding model unavailable: {_first_line(exc)}"
        if rerank_needed:
            if retriever.reranker is None:
                return "no reranker configured"
            try:
                retriever.reranker.score("probe", ["probe"])
            except Exception as exc:
                return f"reranker unavailable: {_first_line(exc)}"
        return None

    def retrieval_run(self, name: str, cfg: RetrievalConfig) -> dict[str, Any]:
        """Recall@k, MRR and nDCG@5 for one configuration over answerable questions."""
        answerable = [g for g in self.golden if g.answerable and g.relevant]
        per_question = []
        try:
            missing = self.missing_requirement(cfg)
            if missing:
                raise RuntimeError(missing)
            for item in answerable:
                result = self.retriever.retrieve(item.question, cfg=cfg)
                ranked = [c.chunk for c in result.chunks]
                per_question.append(
                    {
                        "id": item.id,
                        **{f"recall@{k}": recall_at_k(ranked, item.relevant, k) for k in K_VALUES},
                        "mrr": reciprocal_rank(ranked, item.relevant),
                        "ndcg@5": ndcg_at_k(
                            ranked, item.relevant, 5, self._relevant_available(item)
                        ),
                    }
                )
        except Exception as exc:
            reason = _first_line(exc)
            logger.warning("Skipping %s: %s", name, reason)
            return {
                "name": name,
                "label": LABELS.get(name, name),
                "status": "skipped",
                "reason": reason,
                "config": _config_summary(cfg),
                "questions": 0,
                "retrieval": {},
            }
        metrics = {
            key: round(mean([q[key] for q in per_question]) or 0.0, 4)
            for key in [*(f"recall@{k}" for k in K_VALUES), "mrr", "ndcg@5"]
        }
        return {
            "name": name,
            "label": LABELS.get(name, name),
            "status": "ok",
            "config": _config_summary(cfg),
            "questions": len(per_question),
            "retrieval": metrics,
            "per_question": per_question,
        }

    def abstention(self, cfg: RetrievalConfig) -> dict[str, Any]:
        """Threshold sweep over top scores for answerable vs unanswerable questions."""
        missing = self.missing_requirement(cfg)
        if missing:
            raise RuntimeError(missing)
        scores: list[tuple[float | None, bool]] = []
        for item in self.golden:
            result = self.retriever.retrieve(item.question, cfg=cfg)
            scores.append((result.top_score, item.answerable))
        best, sweep = sweep_threshold(scores)
        current = cfg.abstain_threshold if cfg.rerank else cfg.dense_abstain_threshold
        correct = sum(
            1
            for score, answerable in scores
            if (score is not None and score >= current) == answerable
        )
        return {
            "score": "rerank" if cfg.rerank else "dense similarity",
            "current_threshold": current,
            "accuracy_at_current": round(correct / len(scores), 4) if scores else None,
            "recommended_threshold": best,
            "sweep": sweep,
        }

    async def _judge(self, answer: str, sources_text: str, exclude: str) -> float | None:
        if self.gateway is None:
            return None
        verdict, _ = await self.gateway.complete_json(
            [
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": f"SOURCES\n{sources_text}\n\nANSWER\n{answer}"},
            ],
            JudgeVerdict,
            task="judge",
            exclude=[exclude],
            use_cache=self.use_cache,
            max_tokens=700,
        )
        if not verdict.claims:
            return None
        return sum(1 for c in verdict.claims if c.supported) / len(verdict.claims)

    async def generation(self, cfg: RetrievalConfig) -> dict[str, Any]:
        """Faithfulness (judged by a different provider), citation precision,
        abstention accuracy and end-to-end latency."""
        if self.gateway is None:
            return {"status": "skipped", "reason": "no LLM gateway"}
        generator = AnswerGenerator(self.gateway, self.gateway.counter)
        faithfulness: list[float | None] = []
        precision: list[float | None] = []
        latencies: list[float] = []
        abstain_correct: list[bool] = []
        cached = 0
        errors = 0
        for item in self.golden:
            started = time.perf_counter()
            result = self.retriever.retrieve(item.question, cfg=cfg)
            if not item.answerable:
                abstain_correct.append(result.abstained)
                latencies.append((time.perf_counter() - started) * 1000)
                continue
            abstain_correct.append(not result.abstained)
            if result.abstained:
                continue
            sources = [c.chunk for c in result.chunks]
            messages, kept = generator.prepare(
                question=item.question,
                language=item.language,
                intent="explain",
                sources=sources,
                engine_results=[],
                history=[],
                missing_question=None,
                sensitive=False,
            )
            final: dict[str, Any] | None = None
            was_cached = False
            try:
                async for event in generator.stream(messages, kept, sensitive=False):
                    if event.kind == "provider":
                        was_cached = bool(event.data.get("cached"))
                    if event.kind == "final":
                        final = event.data
            except AllProvidersExhausted as exc:
                logger.warning("Generation failed for %s: %s", item.id, exc)
                errors += 1
                continue
            latencies.append((time.perf_counter() - started) * 1000)
            cached += int(was_cached)
            if final is None:
                continue
            cited_chunks = [kept[n - 1] for n in final["cited"] if 0 < n <= len(kept)]
            precision.append(citation_precision(cited_chunks, item.relevant))
            try:
                faithfulness.append(
                    await self._judge(final["text"], format_sources(kept), final["provider"])
                )
            except AllProvidersExhausted:
                faithfulness.append(None)
        unanswerable = [g for g in self.golden if not g.answerable]
        return {
            "status": "ok",
            "faithfulness": _round(mean(faithfulness)),
            "judged": sum(1 for f in faithfulness if f is not None),
            "citation_precision": _round(mean(precision)),
            "abstention_accuracy": _round(
                sum(abstain_correct) / len(abstain_correct) if abstain_correct else None
            ),
            "unanswerable_questions": len(unanswerable),
            "latency": {
                "p50_ms": round(percentile(latencies, 50), 1),
                "p95_ms": round(percentile(latencies, 95), 1),
                "cached_share": round(cached / len(latencies), 3) if latencies else 0.0,
            },
            "errors": errors,
        }


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0][:300] if text else repr(exc)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _config_summary(cfg: RetrievalConfig) -> dict[str, Any]:
    return {
        "mode": cfg.mode,
        "rerank": cfg.rerank,
        "contextual_headers": cfg.contextual_headers,
        "rrf_k": cfg.rrf_k,
        "embedding": cfg.embedding.model,
        "reranker": cfg.reranker.model if cfg.rerank else None,
    }


async def evaluate(
    settings: Settings,
    golden_path: Path,
    *,
    retriever: HybridRetriever | None = None,
    gateway: LLMGateway | None = None,
    run_ablations: bool = True,
    run_generation: bool = True,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Run the suite and return the report as a dict."""
    golden, skipped = load_golden(golden_path)
    if not golden:
        raise SystemExit(
            f"No verified questions in {golden_path}. Add some with "
            "`python -m yojana.eval.bootstrap propose` and `verify`."
        )
    retriever = retriever or HybridRetriever.from_settings(settings)
    owns_gateway = gateway is None and run_generation
    if owns_gateway:
        gateway = LLMGateway.from_settings(settings)
    evaluator = Evaluator(retriever, golden, gateway, use_cache=use_cache)
    base = settings.retrieval()
    notes: list[str] = []
    if skipped:
        notes.append(f"{skipped} unverified questions were ignored.")
    if retriever.store is not None and not retriever.store.has_plain_vectors:
        notes.append(
            "The index has no plain vectors, so header-free dense runs reused header vectors."
        )

    runs = []
    if run_ablations:
        for name, cfg in ablation_configs(base).items():
            runs.append(evaluator.retrieval_run(name, cfg))
    runs.append(evaluator.retrieval_run("configured", base.model_copy(update={"final_top_k": 10})))
    runs[-1]["label"] = "Configured pipeline (retrieval.yaml)"

    abstention: dict[str, Any] | None = None
    generation: dict[str, Any] | None = None
    try:
        abstention = evaluator.abstention(base)
    except Exception as exc:
        notes.append(f"Abstention sweep skipped: {_first_line(exc)}")
    if run_generation:
        try:
            generation = await evaluator.generation(base)
        except Exception as exc:
            generation = {"status": "skipped", "reason": _first_line(exc)}
    if owns_gateway and gateway is not None:
        await gateway.aclose()

    corpus = "sample" if all(c.is_sample for c in retriever.chunks.all()) else "data"
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": corpus,
        "golden_file": golden_path.name,
        "questions": len(golden),
        "answerable": sum(1 for g in golden if g.answerable),
        "unanswerable": sum(1 for g in golden if not g.answerable),
        "chunks": len(retriever.chunks),
        "runs": runs,
        "abstention": abstention,
        "generation": generation,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the Yojana Sahayak evaluation suite.")
    parser.add_argument("--golden", type=Path, default=settings.eval_dir / "golden.jsonl")
    parser.add_argument("--no-ablations", action="store_true")
    parser.add_argument("--no-generation", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the LLM response cache")
    parser.add_argument("--output", type=Path, default=settings.reports_dir)
    args = parser.parse_args(argv)
    configure_logging(settings.log_level, json_output=False)
    report = asyncio.run(
        evaluate(
            settings,
            args.golden,
            run_ablations=not args.no_ablations,
            run_generation=not args.no_generation,
            use_cache=not args.no_cache,
        )
    )
    json_path, md_path = write_report(report, args.output)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
