"""Scheme listing, details and document checklists."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from yojana.api.services import Services
from yojana.index.store import ChunkStore
from yojana.ingest.models import SchemeRecord
from yojana.taxonomy import CATEGORIES, section_label

router = APIRouter(prefix="/api/schemes", tags=["schemes"])

_BULLET = re.compile(r"^\s*(?:[-•*▪●]|\d{1,2}[.)]|[a-z][.)])\s+", re.I)
_SECTION_ORDER = [
    "overview",
    "benefits",
    "eligibility",
    "exclusions",
    "documents",
    "application",
    "faq",
    "other",
]


def services(request: Request) -> Services:
    return request.app.state.services


def summary(record: SchemeRecord, svc: Services) -> dict[str, Any]:
    rules = svc.rules.get(record.scheme_id)
    return {
        "scheme_id": record.scheme_id,
        "name": record.name,
        "names": record.names,
        "ministry": record.ministry,
        "state": record.state,
        "category": record.category,
        "category_label": CATEGORIES.get(record.category, CATEGORIES["other"]),
        "tags": record.tags,
        "summary": record.summary(),
        "languages": record.languages,
        "is_sample": record.is_sample,
        "has_rules": rules is not None,
        "rules_reviewed": bool(rules and not rules.needs_review),
        "last_seen": record.last_seen,
    }


def checklist_items(record: SchemeRecord, chunks: ChunkStore) -> list[dict[str, Any]]:
    """Split the Documents Required section into items, each citing its chunk."""
    items: list[dict[str, Any]] = []
    documents = chunks.by_scheme(record.scheme_id, "documents")
    for chunk in documents:
        lines = [ln.strip() for ln in chunk.text.split("\n") if ln.strip()]
        if len(lines) == 1 and ";" in lines[0]:
            lines = [part.strip() for part in lines[0].split(";") if part.strip()]
        for line in lines:
            text = _BULLET.sub("", line).strip().rstrip(";")
            if len(text) < 2:
                continue
            key = re.sub(r"\W+", "-", text.lower()).strip("-")[:60]
            if any(item["id"] == key for item in items):
                continue
            items.append(
                {
                    "id": key,
                    "text": text,
                    "chunk_id": chunk.chunk_id,
                    "source_url": chunk.source_url,
                    "page": chunk.page,
                    "language": chunk.language,
                }
            )
    return items


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
    rules = svc.rules.get(scheme_id)
    usable = svc.rules.usable(scheme_id, allow_unreviewed=svc.settings.allow_unreviewed_rules)
    sections = sorted(
        (
            {
                "name": s.name,
                "label": section_label(s.name, s.language),
                "heading": s.heading,
                "text": s.text,
                "language": s.language,
                "source_url": s.source_url,
                "page": s.page,
                "chunk_ids": s.chunk_ids,
            }
            for s in record.sections
        ),
        key=lambda s: _SECTION_ORDER.index(s["name"]) if s["name"] in _SECTION_ORDER else 99,
    )
    chunk_lookup = {
        cid: {
            "chunk_id": cid,
            "text": chunk.text,
            "section": chunk.section,
            "source_url": chunk.source_url,
            "page": chunk.page,
        }
        for cid in (rules.rules.cited_chunk_ids() if rules else set())
        if (chunk := svc.chunks.get(cid)) is not None
    }
    return {
        **summary(record, svc),
        "sections": sections,
        "source_urls": record.source_urls,
        "rules": rules.model_dump(mode="json") if rules else None,
        "rules_usable": usable is not None,
        "rule_sources": chunk_lookup,
        "checklist": checklist_items(record, svc.chunks),
    }


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
