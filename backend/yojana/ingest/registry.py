"""Scheme registry: per-scheme records merged from parsed documents."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from yojana.ingest.models import Chunk, ParsedDocument, SchemeRecord, SchemeSection
from yojana.taxonomy import ALL_STATES


def build_records(docs: Iterable[tuple[ParsedDocument, list[Chunk]]]) -> list[SchemeRecord]:
    """Merge documents that share a scheme_id (for example English and Hindi pages)."""
    records: dict[str, SchemeRecord] = {}
    for doc, chunks in sorted(docs, key=lambda item: item[0].path):
        meta = doc.meta
        record = records.get(meta.scheme_id)
        if record is None:
            record = SchemeRecord(
                scheme_id=meta.scheme_id,
                name=meta.scheme_name,
                ministry=meta.ministry,
                state=meta.state,
                category=meta.category,
                last_seen=doc.parsed_at,
                is_sample=meta.is_sample,
            )
            records[meta.scheme_id] = record
        record.names.setdefault(meta.language, meta.scheme_name)
        if meta.language == "en":
            record.name = meta.scheme_name
        record.ministry = record.ministry or meta.ministry
        if record.state == ALL_STATES and meta.state != ALL_STATES:
            record.state = meta.state
        if record.category == "other":
            record.category = meta.category
        record.tags = sorted(set(record.tags) | set(meta.tags))
        if meta.source_url not in record.source_urls:
            record.source_urls.append(meta.source_url)
        if meta.language not in record.languages:
            record.languages.append(meta.language)
        record.last_seen = max(record.last_seen, doc.parsed_at)
        for section in doc.sections:
            record.sections.append(
                SchemeSection(
                    name=section.name,
                    heading=section.heading,
                    text=section.text,
                    language=meta.language,
                    source_url=meta.source_url,
                    page=section.first_page,
                    chunk_ids=[c.chunk_id for c in chunks if c.section == section.name],
                )
            )
    return sorted(records.values(), key=lambda r: r.name.lower())


class SchemeRegistry:
    """In-memory lookup over `data/processed/schemes.json`."""

    def __init__(self, records: Iterable[SchemeRecord]) -> None:
        self._records = {r.scheme_id: r for r in records}

    @classmethod
    def load(cls, path: Path) -> SchemeRegistry:
        if not path.is_file():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(SchemeRecord.model_validate(item) for item in data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [r.model_dump(mode="json") for r in self.all()]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def all(self) -> list[SchemeRecord]:
        return sorted(self._records.values(), key=lambda r: r.name.lower())

    def get(self, scheme_id: str) -> SchemeRecord | None:
        return self._records.get(scheme_id)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, scheme_id: object) -> bool:
        return scheme_id in self._records

    def find_mentions(self, text: str) -> list[str]:
        """Scheme ids whose name (in any language) appears in `text`, longest first."""
        lowered = text.lower()
        hits: list[tuple[int, str]] = []
        for record in self._records.values():
            names = {record.name, *record.names.values(), record.scheme_id.replace("-", " ")}
            for name in names:
                name_l = name.lower().strip()
                if len(name_l) >= 4 and name_l in lowered:
                    hits.append((len(name_l), record.scheme_id))
                    break
        return [sid for _, sid in sorted(hits, reverse=True)]

    def search(
        self,
        *,
        query: str | None = None,
        state: str | None = None,
        category: str | None = None,
    ) -> list[SchemeRecord]:
        """Simple metadata and substring filter used by the explorer endpoint."""
        results = []
        q = (query or "").lower().strip()
        for record in self.all():
            if state and record.state not in (state, ALL_STATES):
                continue
            if category and record.category != category:
                continue
            if q:
                haystack = " ".join(
                    [record.name, *record.names.values(), record.ministry or "", *record.tags]
                ).lower()
                if q not in haystack and q not in record.summary(1000).lower():
                    continue
            results.append(record)
        return results
