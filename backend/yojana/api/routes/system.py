"""Health, provider status, evaluation reports and the admin ingestion trigger."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from yojana.api.services import IngestJob, Services

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _svc(request: Request) -> Services:
    return request.app.state.services


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    svc = _svc(request)
    retriever = svc.retriever
    return {
        "status": "ok",
        "schemes": len(svc.registry),
        "chunks": len(retriever.chunks),
        "dense_index": retriever.store is not None and retriever.store.count() > 0,
        "models": {
            "embedder": bool(retriever.embedder and retriever.embedder.loaded),
            "reranker": bool(retriever.reranker and retriever.reranker.loaded),
        },
    }


@router.get("/health/providers")
def provider_health(request: Request) -> dict[str, Any]:
    """Each provider's status (ok, cooldown, disabled, budget_exhausted) and usage today."""
    return {
        "providers": _svc(request).gateway.status(),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def latest_report(reports_dir: Path, example: Path) -> dict[str, Any] | None:
    candidates = sorted(reports_dir.glob("eval-*.json"))
    if candidates:
        data = json.loads(candidates[-1].read_text(encoding="utf-8"))
        data["file"] = candidates[-1].name
        data["example"] = False
        return data
    if example.is_file():
        data = json.loads(example.read_text(encoding="utf-8"))
        data["file"] = example.name
        data["example"] = True
        return data
    return None


@router.get("/eval/latest")
def eval_latest(request: Request) -> dict[str, Any]:
    settings = _svc(request).settings
    report = latest_report(settings.reports_dir, settings.root_dir / "docs" / "example-eval.json")
    if report is None:
        raise HTTPException(status_code=404, detail="No evaluation report yet")
    return report


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in _LOCAL_HOSTS


@router.post("/admin/ingest", status_code=202)
async def admin_ingest(request: Request, sample: bool = False, rules: bool = False) -> Any:
    """Start incremental ingestion in the background. Only accepted from localhost."""
    if not _is_local(request):
        return JSONResponse(status_code=403, content={"detail": "Admin endpoints are local only"})
    svc = _svc(request)
    if svc.ingest_job.state == "running":
        return JSONResponse(status_code=409, content={"detail": "Ingestion already running"})
    svc.ingest_job = IngestJob(
        state="running", started_at=datetime.now(UTC).isoformat(timespec="seconds")
    )

    def work() -> None:
        from yojana.ingest.pipeline import run_pipeline

        job = svc.ingest_job
        try:
            report = run_pipeline(svc.settings, include_sample=sample, extract_rules=rules)
            job.report = report.as_dict()
            svc.reload()
            job.state = "finished"
        except Exception as exc:
            logger.exception("Ingestion failed")
            job.state, job.error = "failed", str(exc)
        finally:
            job.finished_at = datetime.now(UTC).isoformat(timespec="seconds")

    request.app.state.background.add(asyncio.create_task(asyncio.to_thread(work)))
    return {"state": "running", "started_at": svc.ingest_job.started_at}


@router.get("/admin/ingest")
def admin_ingest_status(request: Request) -> Any:
    if not _is_local(request):
        return JSONResponse(status_code=403, content={"detail": "Admin endpoints are local only"})
    job = _svc(request).ingest_job
    return {
        "state": job.state,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "report": job.report,
        "error": job.error,
    }
