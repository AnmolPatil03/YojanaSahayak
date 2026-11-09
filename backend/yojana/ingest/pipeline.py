"""Incremental ingestion: scrape, parse, chunk, index and extract rules.

Documents are tracked by content hash in `data/processed/ingest_state.json`, so a
re-run only touches files that are new, changed or deleted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from yojana.config import Settings, get_settings
from yojana.ingest.chunk import chunk_document
from yojana.ingest.models import Chunk, ParsedDocument
from yojana.ingest.parse import SUPPORTED_SUFFIXES, file_hash, parse_file
from yojana.ingest.registry import SchemeRegistry, build_records
from yojana.ingest.scrape import Manifest
from yojana.llm.tokens import TokenCounter
from yojana.logging_setup import configure_logging

logger = logging.getLogger(__name__)

STATE_FILE = "ingest_state.json"
DOCS_DIR = "docs"
SCHEMES_FILE = "schemes.json"
CHUNKS_FILE = "chunks.jsonl"


@dataclass(slots=True)
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    chunks_total: int = 0
    schemes_total: int = 0
    changed_schemes: set[str] = field(default_factory=set)
    rules: dict[str, str] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)

    def as_dict(self) -> dict[str, object]:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "chunks_total": self.chunks_total,
            "schemes_total": self.schemes_total,
            "changed_schemes": sorted(self.changed_schemes),
            "rules": self.rules,
        }


def iter_source_files(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if ".meta." in path.name:
            continue
        yield path


class DocumentStore:
    """Parsed documents and their chunks, one JSON file per document."""

    def __init__(self, processed_dir: Path) -> None:
        self.root = processed_dir
        self.docs_dir = processed_dir / DOCS_DIR
        self.state_path = processed_dir / STATE_FILE

    def load_state(self) -> dict[str, dict[str, str]]:
        if not self.state_path.is_file():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: dict[str, dict[str, str]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")

    def save(self, doc: ParsedDocument, chunks: list[Chunk]) -> None:
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "document": doc.model_dump(mode="json"),
            "chunks": [c.model_dump(mode="json") for c in chunks],
        }
        (self.docs_dir / f"{doc.doc_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def delete(self, doc_id: str) -> None:
        (self.docs_dir / f"{doc_id}.json").unlink(missing_ok=True)

    def load(self, doc_id: str) -> tuple[ParsedDocument, list[Chunk]] | None:
        path = self.docs_dir / f"{doc_id}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            ParsedDocument.model_validate(data["document"]),
            [Chunk.model_validate(c) for c in data["chunks"]],
        )

    def all(self) -> Iterator[tuple[ParsedDocument, list[Chunk]]]:
        if not self.docs_dir.is_dir():
            return
        for path in sorted(self.docs_dir.glob("*.json")):
            loaded = self.load(path.stem)
            if loaded is not None:
                yield loaded

    def all_chunks(self) -> list[Chunk]:
        return [chunk for _, chunks in self.all() for chunk in chunks]


def load_chunks(processed_dir: Path) -> list[Chunk]:
    """Read every chunk from `chunks.jsonl`."""
    path = processed_dir / CHUNKS_FILE
    if not path.is_file():
        return []
    return [
        Chunk.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_documents(
    settings: Settings,
    *,
    include_sample: bool = False,
    force: bool = False,
    counter: TokenCounter | None = None,
    on_changed: Callable[[list[Chunk], list[str]], None] | None = None,
) -> IngestReport:
    """Parse and chunk new or changed files under `data/raw/` (and the sample set).

    Args:
        settings: Application settings.
        include_sample: Also ingest the fictional documents in `data/sample/docs`.
        force: Reprocess every file regardless of content hash.
        counter: Token counter used for chunk sizes.
        on_changed: Called with (new chunks, removed chunk ids) so an index can update.
    """
    counter = counter or TokenCounter(cache_dir=settings.cache_dir / "tiktoken")
    chunking = settings.retrieval().chunking
    store = DocumentStore(settings.processed_dir)
    state = {} if force else store.load_state()
    manifest = Manifest(settings.raw_dir).by_path()
    report = IngestReport()

    roots: list[tuple[Path, bool]] = [(settings.raw_dir, False)]
    if include_sample:
        roots.append((settings.sample_dir / "docs", True))

    seen: set[str] = set()
    new_chunks: list[Chunk] = []
    removed_ids: list[str] = []
    for root, is_sample in roots:
        for path in iter_source_files(root):
            key = path.resolve().relative_to(settings.root_dir.resolve()).as_posix()
            seen.add(key)
            digest = file_hash(path)
            sidecar_mtime = max(
                (p.stat().st_mtime for p in path.parent.glob(path.name + ".meta.*")), default=0.0
            )
            previous = state.get(key)
            if (
                previous
                and previous.get("sha256") == digest
                and float(previous.get("sidecar_mtime", 0.0)) >= sidecar_mtime
            ):
                report.unchanged += 1
                continue
            raw_rel = (
                path.resolve().relative_to(settings.raw_dir.resolve()).as_posix()
                if not is_sample
                else None
            )
            source_url = manifest[raw_rel].url if raw_rel and raw_rel in manifest else None
            try:
                doc = parse_file(
                    path, relative_to=settings.root_dir, source_url=source_url, is_sample=is_sample
                )
            except Exception as exc:
                logger.warning("Could not parse %s: %s", key, exc)
                report.failed[key] = str(exc)
                continue
            if not doc.sections:
                report.failed[key] = "no text extracted"
                continue
            chunks = chunk_document(doc, chunking, counter)
            if previous:
                old = store.load(previous["doc_id"])
                if old is not None:
                    removed_ids.extend(c.chunk_id for c in old[1])
                    report.changed_schemes.add(old[0].meta.scheme_id)
                    if previous["doc_id"] != doc.doc_id:
                        store.delete(previous["doc_id"])
                report.updated.append(key)
            else:
                report.added.append(key)
            store.save(doc, chunks)
            new_chunks.extend(chunks)
            report.changed_schemes.add(doc.meta.scheme_id)
            state[key] = {
                "sha256": digest,
                "doc_id": doc.doc_id,
                "scheme_id": doc.meta.scheme_id,
                "sidecar_mtime": str(sidecar_mtime),
            }

    for key in sorted(set(state) - seen):
        if not include_sample and key.startswith("data/sample/"):
            continue
        entry = state.pop(key)
        old = store.load(entry["doc_id"])
        if old is not None:
            removed_ids.extend(c.chunk_id for c in old[1])
            report.changed_schemes.add(old[0].meta.scheme_id)
        store.delete(entry["doc_id"])
        report.removed.append(key)

    new_ids = {c.chunk_id for c in new_chunks}
    removed_ids = [cid for cid in dict.fromkeys(removed_ids) if cid not in new_ids]
    store.save_state(state)

    docs = list(store.all())
    registry = SchemeRegistry(build_records(docs))
    registry.save(settings.processed_dir / SCHEMES_FILE)
    all_chunks = [chunk for _, chunks in docs for chunk in chunks]
    with (settings.processed_dir / CHUNKS_FILE).open("w", encoding="utf-8") as fh:
        for chunk in all_chunks:
            fh.write(chunk.model_dump_json() + "\n")
    report.chunks_total = len(all_chunks)
    report.schemes_total = len(registry)

    if on_changed is not None and (new_chunks or removed_ids or force):
        on_changed(new_chunks, removed_ids)
    return report


def run_pipeline(
    settings: Settings,
    *,
    scrape: bool = False,
    include_sample: bool = False,
    force: bool = False,
    max_pages: int | None = None,
    extract_rules: bool = False,
) -> IngestReport:
    """Run the incremental pipeline used by the CLI and the admin endpoint."""
    from yojana.index.builder import IndexBuilder
    from yojana.rules import RulesStore

    settings.ensure_dirs()
    if scrape:
        from yojana.ingest import scrape as scraper

        scraper.run(settings, max_pages=max_pages)

    builder = IndexBuilder(settings)
    if force:
        builder.store.reset()
    report = build_documents(
        settings, include_sample=include_sample, force=force, on_changed=builder.apply_changes
    )
    if report.chunks_total and builder.store.count() == 0:
        logger.info("Vector index is empty; embedding all %d chunks", report.chunks_total)
        builder.rebuild_dense()
    builder.rebuild_sparse()
    if include_sample:
        RulesStore(settings.processed_dir / "rules").install_samples(settings.sample_dir / "rules")
    if extract_rules and (report.changed_schemes or force):
        from yojana.ingest.rules_extract import extract_all

        only = None if force else report.changed_schemes
        report.rules = asyncio.run(extract_all(settings, only=only, force=force))
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Incremental ingestion for Yojana Sahayak.")
    parser.add_argument("--scrape", action="store_true", help="Run the scraper first")
    parser.add_argument("--max-pages", type=int, help="Limit pages per source when scraping")
    parser.add_argument("--sample", action="store_true", help="Include the fictional sample set")
    parser.add_argument("--force", action="store_true", help="Reprocess every document")
    parser.add_argument(
        "--rules", action="store_true", help="Extract eligibility rules for changed schemes"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    report = run_pipeline(
        settings,
        scrape=args.scrape,
        include_sample=args.sample,
        force=args.force,
        max_pages=args.max_pages,
        extract_rules=args.rules,
    )
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
