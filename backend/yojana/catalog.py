"""Read-only views of schemes shared by the HTTP API and the MCP server."""

from __future__ import annotations

import re
from typing import Any

from yojana.index.store import ChunkStore
from yojana.ingest.models import SchemeRecord
from yojana.rules import RulesStore
from yojana.taxonomy import CATEGORIES, section_label

_BULLET = re.compile(r"^\s*(?:[-•*▪●]|\d{1,2}[.)]|[a-z][.)])\s+", re.I)
SECTION_ORDER = [
    "overview",
    "benefits",
    "eligibility",
    "exclusions",
    "documents",
    "application",
    "faq",
    "other",
]


def scheme_summary(record: SchemeRecord, rules: RulesStore) -> dict[str, Any]:
    """Card-sized description of a scheme."""
    stored = rules.get(record.scheme_id)
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
        "has_rules": stored is not None,
        "rules_reviewed": bool(stored and not stored.needs_review),
        "last_seen": record.last_seen,
    }


def checklist_items(record: SchemeRecord, chunks: ChunkStore) -> list[dict[str, Any]]:
    """Split the Documents Required section into items, each citing its chunk."""
    items: list[dict[str, Any]] = []
    for chunk in chunks.by_scheme(record.scheme_id, "documents"):
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


def scheme_details(
    record: SchemeRecord,
    rules: RulesStore,
    chunks: ChunkStore,
    *,
    allow_unreviewed: bool,
) -> dict[str, Any]:
    """Everything about one scheme: sections, rules with their sources, checklist."""
    stored = rules.get(record.scheme_id)
    usable = rules.usable(record.scheme_id, allow_unreviewed=allow_unreviewed)
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
        key=lambda s: SECTION_ORDER.index(s["name"]) if s["name"] in SECTION_ORDER else 99,
    )
    rule_sources = {
        cid: {
            "chunk_id": cid,
            "text": chunk.text,
            "section": chunk.section,
            "source_url": chunk.source_url,
            "page": chunk.page,
        }
        for cid in (stored.rules.cited_chunk_ids() if stored else set())
        if (chunk := chunks.get(cid)) is not None
    }
    return {
        **scheme_summary(record, rules),
        "sections": sections,
        "source_urls": record.source_urls,
        "rules": stored.model_dump(mode="json") if stored else None,
        "rules_usable": usable is not None,
        "rule_sources": rule_sources,
        "checklist": checklist_items(record, chunks),
    }
