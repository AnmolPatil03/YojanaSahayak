"""Extract structured eligibility rules from scheme chunks via the LLM gateway.

Extracted rules are always saved with `needs_review: true`; the engine ignores them
until they are checked with `review_cli.py` (unless explicitly configured not to).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from yojana.config import Settings, get_settings
from yojana.index.store import ChunkStore
from yojana.ingest.models import Chunk
from yojana.ingest.registry import SchemeRegistry
from yojana.llm.gateway import AllProvidersExhausted, LLMGateway
from yojana.logging_setup import configure_logging
from yojana.rules import RULE_FIELDS, EligibilityRules, OtherCondition, RulesRecord, RulesStore
from yojana.taxonomy import EDUCATION_LEVELS, OCCUPATIONS, SOCIAL_CATEGORIES

logger = logging.getLogger(__name__)

RULE_SECTIONS = ("eligibility", "exclusions", "overview", "benefits")
MAX_CONTEXT_CHUNKS = 12


class _IntRule(BaseModel):
    value: int | None = None
    chunk_id: str | None = None


class _ListRule(BaseModel):
    value: list[str] | None = None
    chunk_id: str | None = None


class _BoolRule(BaseModel):
    value: bool | None = None
    chunk_id: str | None = None


class _StrRule(BaseModel):
    value: str | None = None
    chunk_id: str | None = None


class ExtractedRules(BaseModel):
    """Schema the LLM fills in; kept flat so small models handle it reliably."""

    min_age: _IntRule = Field(default_factory=_IntRule)
    max_age: _IntRule = Field(default_factory=_IntRule)
    genders: _ListRule = Field(default_factory=_ListRule)
    states: _ListRule = Field(default_factory=_ListRule)
    max_annual_family_income: _IntRule = Field(default_factory=_IntRule)
    social_categories: _ListRule = Field(default_factory=_ListRule)
    occupations: _ListRule = Field(default_factory=_ListRule)
    education_levels: _ListRule = Field(default_factory=_ListRule)
    disability_required: _BoolRule = Field(default_factory=_BoolRule)
    residence: _StrRule = Field(default_factory=_StrRule)
    other_conditions: list[OtherCondition] = Field(default_factory=list)


SYSTEM_PROMPT = f"""You extract eligibility rules for an Indian government scheme from \
the numbered source passages you are given.

Rules:
- Use only what the passages state explicitly. If a criterion is not stated, set its \
value to null. Never guess or use outside knowledge.
- For every non-null value, set chunk_id to the id of the passage that states it, \
copied exactly from the passage list.
- Ages are whole years. max_annual_family_income is in rupees per year as a plain \
integer (for example 2.5 lakh -> 250000; convert monthly limits to yearly).
- genders uses only: male, female, transgender.
- social_categories uses only: {", ".join(SOCIAL_CATEGORIES)}.
- occupations uses only: {", ".join(OCCUPATIONS)}.
- education_levels lists every education level that qualifies, using only: \
{", ".join(EDUCATION_LEVELS)}.
- states lists Indian states or union territories the applicant must live in; null \
if the scheme is open nationwide.
- residence is "rural" or "urban" only if the scheme requires one of them.
- disability_required is true only if the scheme is restricted to persons with \
disabilities.
- Put every other condition (exclusions, land ownership, prior benefits, marks, \
etc.) in other_conditions as short sentences, each with its chunk_id."""


def content_hash(chunks: Sequence[Chunk]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode())
        digest.update(chunk.text.encode("utf-8"))
    return digest.hexdigest()


def select_rule_chunks(chunks: Iterable[Chunk]) -> list[Chunk]:
    order = {name: i for i, name in enumerate(RULE_SECTIONS)}
    relevant = [c for c in chunks if c.section in order]
    relevant.sort(key=lambda c: (order[c.section], c.chunk_id))
    return relevant[:MAX_CONTEXT_CHUNKS]


def build_messages(scheme_name: str, chunks: Sequence[Chunk]) -> list[dict[str, str]]:
    passages = "\n\n".join(f"[{c.chunk_id}] ({c.heading})\n{c.text}" for c in chunks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Scheme: {scheme_name}\n\nPassages:\n{passages}"},
    ]


def to_rules(extracted: ExtractedRules, allowed_ids: set[str]) -> EligibilityRules:
    """Validate extracted rules; citations to unknown passages are dropped."""
    data = extracted.model_dump()
    for name in RULE_FIELDS:
        if data[name]["chunk_id"] not in allowed_ids:
            data[name]["chunk_id"] = None
    data["other_conditions"] = [
        {"text": c["text"], "chunk_id": c["chunk_id"] if c["chunk_id"] in allowed_ids else None}
        for c in data["other_conditions"]
        if c.get("text", "").strip()
    ]
    return EligibilityRules.model_validate(data)


async def extract_for_scheme(
    gateway: LLMGateway,
    scheme_id: str,
    scheme_name: str,
    chunks: Sequence[Chunk],
    existing: RulesRecord | None,
    *,
    force: bool = False,
) -> RulesRecord | None:
    """Extract rules for one scheme, or return None when nothing changed."""
    selected = select_rule_chunks(chunks)
    if not selected:
        return None
    digest = content_hash(selected)
    if existing is not None and existing.content_hash == digest and not force:
        return None
    extracted, result = await gateway.complete_json(
        build_messages(scheme_name, selected),
        ExtractedRules,
        task="rules_extract",
        sensitive=False,
        max_tokens=900,
    )
    rules = to_rules(extracted, {c.chunk_id for c in selected})
    previous = None
    if existing is not None and not existing.needs_review:
        previous = existing.rules
    return RulesRecord(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        rules=rules,
        needs_review=True,
        extracted_at=datetime.now(UTC).isoformat(timespec="seconds"),
        extracted_by=f"{result.provider}:{result.model}",
        content_hash=digest,
        source_chunk_ids=[c.chunk_id for c in selected],
        previous=previous,
    )


async def extract_all(
    settings: Settings,
    *,
    only: Iterable[str] | None = None,
    force: bool = False,
    gateway: LLMGateway | None = None,
) -> dict[str, str]:
    """Extract rules for every scheme (or `only` these), skipping unchanged ones."""
    registry = SchemeRegistry.load(settings.processed_dir / "schemes.json")
    chunks = ChunkStore.load(settings.processed_dir)
    store = RulesStore(settings.processed_dir / "rules")
    owns_gateway = gateway is None
    gateway = gateway or LLMGateway.from_settings(settings)
    wanted = set(only) if only is not None else None
    outcome: dict[str, str] = {}
    try:
        for record in registry.all():
            if wanted is not None and record.scheme_id not in wanted:
                continue
            existing = store.get(record.scheme_id)
            if record.is_sample and existing is not None:
                outcome[record.scheme_id] = "sample rules kept"
                continue
            try:
                new = await extract_for_scheme(
                    gateway,
                    record.scheme_id,
                    record.name,
                    chunks.by_scheme(record.scheme_id),
                    existing,
                    force=force,
                )
            except AllProvidersExhausted as exc:
                logger.warning("Stopping rule extraction: %s", exc)
                outcome[record.scheme_id] = "skipped: no provider available"
                break
            if new is None:
                outcome[record.scheme_id] = "unchanged"
                continue
            store.save(new)
            outcome[record.scheme_id] = "extracted, needs review"
    finally:
        if owns_gateway:
            await gateway.aclose()
    return outcome


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Extract eligibility rules with the LLM.")
    parser.add_argument("--scheme", action="append", help="Only these scheme ids")
    parser.add_argument("--force", action="store_true", help="Re-extract unchanged schemes")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    outcome = asyncio.run(extract_all(settings, only=args.scheme, force=args.force))
    for scheme_id, status in outcome.items():
        print(f"{scheme_id}: {status}")


if __name__ == "__main__":
    main()
