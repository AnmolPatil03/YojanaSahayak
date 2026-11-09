"""Section-aware chunking with token limits, overlap and contextual headers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from yojana.config import ChunkingConfig
from yojana.ingest.models import Chunk, ParsedDocument, Section
from yojana.llm.tokens import TokenCounter
from yojana.taxonomy import detect_script_language, section_label

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


@dataclass(slots=True)
class _Unit:
    text: str
    page: int | None
    tokens: int


def contextual_header(scheme_name: str, ministry_or_state: str | None, section: str) -> str:
    """`"{Scheme name} | {Ministry/State} | {Section}"`, prepended before embedding."""
    return " | ".join(part for part in (scheme_name, ministry_or_state or "", section) if part)


def _units(section: Section, counter: TokenCounter, max_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    for segment in section.segments:
        for paragraph in segment.text.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            tokens = counter.count(paragraph)
            if tokens <= max_tokens:
                units.append(_Unit(paragraph, segment.page, tokens))
                continue
            for sentence in _SENTENCE_END.split(paragraph):
                sentence = sentence.strip()
                if not sentence:
                    continue
                size = counter.count(sentence)
                if size <= max_tokens:
                    units.append(_Unit(sentence, segment.page, size))
                else:
                    for piece in counter.split_by_tokens(sentence, max_tokens):
                        units.append(_Unit(piece, segment.page, counter.count(piece)))
    return units


def _pack(units: list[_Unit], max_tokens: int, overlap_tokens: int) -> list[list[_Unit]]:
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    size = 0
    for unit in units:
        if current and size + unit.tokens > max_tokens:
            groups.append(current)
            carry: list[_Unit] = []
            carried = 0
            for previous in reversed(current):
                if carried + previous.tokens > overlap_tokens:
                    break
                carry.insert(0, previous)
                carried += previous.tokens
            if carried + unit.tokens > max_tokens:
                carry, carried = [], 0
            current, size = carry, carried
        current.append(unit)
        size += unit.tokens
    if current:
        groups.append(current)
    return groups


def chunk_document(
    doc: ParsedDocument,
    config: ChunkingConfig,
    counter: TokenCounter,
) -> list[Chunk]:
    """Split each section into ~`max_tokens` chunks with `overlap` carried forward.

    Sections never share a chunk, so a retrieved passage always belongs to exactly
    one of Overview, Benefits, Eligibility, Exclusions, Documents or How to Apply.
    """
    meta = doc.meta
    overlap_tokens = int(config.max_tokens * config.overlap)
    context = meta.ministry or (meta.state if meta.state != "ALL" else None)
    chunks: list[Chunk] = []
    for section in doc.sections:
        units = _units(section, counter, config.max_tokens)
        groups = _pack(units, config.max_tokens, overlap_tokens)
        if len(groups) > 1:
            tail_tokens = sum(u.tokens for u in groups[-1])
            extra = [u for u in groups[-1] if u not in groups[-2]]
            merged_tokens = sum(u.tokens for u in groups[-2]) + sum(u.tokens for u in extra)
            if tail_tokens < config.min_tokens and merged_tokens <= config.max_tokens:
                groups.pop()
                groups[-1].extend(extra)
        for index, group in enumerate(groups):
            text = "\n".join(u.text for u in group)
            language = detect_script_language(text)
            header = contextual_header(
                meta.scheme_name, context, section_label(section.name, language)
            )
            chunks.append(
                Chunk(
                    chunk_id=f"{meta.scheme_id}::{doc.doc_id[:6]}::{section.name}::{index:03d}",
                    doc_id=doc.doc_id,
                    scheme_id=meta.scheme_id,
                    scheme_name=meta.scheme_name,
                    ministry=meta.ministry,
                    state=meta.state,
                    category=meta.category,
                    section=section.name,
                    heading=section.heading,
                    source_url=meta.source_url,
                    page=next((u.page for u in group if u.page is not None), None),
                    language=language,
                    last_seen=doc.parsed_at,
                    is_sample=meta.is_sample,
                    text=text,
                    header=header,
                )
            )
    return chunks
