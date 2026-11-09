"""Write evaluation reports as JSON and Markdown."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_METRICS = ["recall@1", "recall@3", "recall@5", "recall@10", "mrr", "ndcg@5"]


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def to_markdown(report: dict[str, Any]) -> str:
    """Human-readable summary of a report."""
    lines = [
        f"# Evaluation report ({report['created_at']})",
        "",
        f"- Corpus: {report['corpus']} ({report.get('chunks', '?')} chunks)",
        f"- Golden file: `{report['golden_file']}` with {report['questions']} verified questions "
        f"({report['answerable']} answerable, {report['unanswerable']} unanswerable)",
        "",
        "## Retrieval",
        "",
        "| Configuration | " + " | ".join(_METRICS) + " |",
        "|---|" + "---|" * len(_METRICS),
    ]
    for run in report["runs"]:
        if run["status"] != "ok":
            lines.append(f"| {run['label']} | " + " | ".join("skipped" for _ in _METRICS) + " |")
            continue
        values = " | ".join(_fmt(run["retrieval"].get(m)) for m in _METRICS)
        lines.append(f"| {run['label']} | {values} |")
    skipped = [r for r in report["runs"] if r["status"] != "ok"]
    if skipped:
        lines.append("")
        for run in skipped:
            lines.append(f"- {run['label']} skipped: {run.get('reason', '')}")

    generation = report.get("generation") or {}
    lines += ["", "## Answers", ""]
    if generation.get("status") == "ok":
        latency = generation.get("latency", {})
        p50, p95 = _fmt(latency.get("p50_ms")), _fmt(latency.get("p95_ms"))
        faithfulness = _fmt(generation.get("faithfulness"))
        lines += [
            "| Metric | Value |",
            "|---|---|",
            f"| Faithfulness (judged by a different provider) | {faithfulness} |",
            f"| Citation precision | {_fmt(generation.get('citation_precision'))} |",
            f"| Abstention accuracy | {_fmt(generation.get('abstention_accuracy'))} |",
            f"| Latency p50 / p95 | {p50} ms / {p95} ms |",
            f"| Share of cached answers | {_fmt(latency.get('cached_share'))} |",
        ]
    else:
        lines.append(f"Skipped: {generation.get('reason', 'not requested')}")

    abstention = report.get("abstention")
    lines += ["", "## Abstention threshold", ""]
    if abstention:
        lines += [
            f"- Score used: {abstention['score']}",
            f"- Current threshold: {abstention['current_threshold']} "
            f"(accuracy {_fmt(abstention['accuracy_at_current'])})",
            f"- Recommended threshold: {_fmt(abstention['recommended_threshold'])}",
        ]
    else:
        lines.append("Not computed.")
    if report.get("notes"):
        lines += ["", "## Notes", ""] + [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    """Save `eval-<timestamp>.json` and `.md`; per-question details stay in the JSON."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    json_path = directory / f"eval-{stamp}.json"
    md_path = directory / f"eval-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path
