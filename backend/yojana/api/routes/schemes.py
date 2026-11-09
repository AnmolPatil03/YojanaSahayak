"""Scheme listing, details and document checklists."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from yojana.api.services import Services
from yojana.catalog import checklist_items, scheme_details, scheme_summary
from yojana.ingest.models import SchemeRecord
from yojana.taxonomy import CATEGORIES

router = APIRouter(prefix="/api/schemes", tags=["schemes"])


def services(request: Request) -> Services:
    return request.app.state.services


def summary(record: SchemeRecord, svc: Services) -> dict[str, Any]:
    return scheme_summary(record, svc.rules)


@router.get("")
def list_schemes(
    request: Request,
    state: str | None = None,
    category: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> dict[str, Any]:
    svc = services(request)
    matches = svc.registry.search(query=q, state=state, category=category)
    start = (page - 1) * page_size
    everything = svc.registry.all()
    return {
        "items": [summary(r, svc) for r in matches[start : start + page_size]],
        "total": len(matches),
        "page": page,
        "page_size": page_size,
        "facets": {
            "states": sorted({r.state for r in everything}),
            "categories": [
                {"key": key, "label": CATEGORIES[key]}
                for key in CATEGORIES
                if any(r.category == key for r in everything)
            ],
        },
    }


@router.get("/{scheme_id}")
def get_scheme(scheme_id: str, request: Request) -> dict[str, Any]:
    svc = services(request)
    record = svc.registry.get(scheme_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return scheme_details(
        record, svc.rules, svc.chunks, allow_unreviewed=svc.settings.allow_unreviewed_rules
    )


@router.get("/{scheme_id}/checklist")
def get_checklist(scheme_id: str, request: Request) -> dict[str, Any]:
    svc = services(request)
    record = svc.registry.get(scheme_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return {
        "scheme_id": scheme_id,
        "name": record.name,
        "is_sample": record.is_sample,
        "items": checklist_items(record, svc.chunks),
    }
