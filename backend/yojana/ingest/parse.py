"""Turn raw HTML and PDF files into documents split into canonical scheme sections."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

from yojana.ingest.models import DocumentMeta, ParsedDocument, Section, Segment
from yojana.taxonomy import (
    ALL_STATES,
    canonical_section,
    detect_script_language,
    find_states,
    guess_category,
    normalize_state,
    normalize_text,
    slugify,
)

SUPPORTED_SUFFIXES = {".html", ".htm", ".pdf"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5"}
_BLOCKS = {"p", "li", "tr", "dd", "dt", "pre", "blockquote", "div", "section"}
_NOISE = [
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "footer",
    "header",
    "form",
    "button",
    "iframe",
]
_MINISTRY = re.compile(
    r"\b((?:Ministry|Department) of [A-Z][A-Za-z&,\- ]{3,80}?)(?=[.,;\n(]|\s{2}|$)"
)
_MINISTRY_HI = re.compile(r"([\u0900-\u097F ]{2,40}(?:मंत्रालय|विभाग))")
_GOVT_OF = re.compile(r"Government of ([A-Z][A-Za-z ]{2,40})")
_TITLE_SUFFIX = re.compile(r"\s*[|–-]\s*(myScheme|My Scheme|Government of India).*$", re.I)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sidecar(path: Path) -> dict[str, Any]:
    """Read `<file>.meta.yaml` or `<file>.meta.json` next to a manually added file."""
    for suffix in (".meta.yaml", ".meta.yml", ".meta.json"):
        candidate = path.with_name(path.name + suffix)
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
            data = json.loads(text) if suffix.endswith("json") else yaml.safe_load(text)
            return data or {}
    return {}


def _leaf_block(tag: Tag) -> bool:
    return not any(isinstance(child, Tag) and child.name in _BLOCKS for child in tag.descendants)


def _block_text(tag: Tag) -> str:
    if tag.name == "tr":
        cells = [c.get_text(" ", strip=True) for c in tag.find_all(["td", "th"])]
        return " | ".join(c for c in cells if c)
    text = tag.get_text(" ", strip=True)
    if tag.name == "li" and text:
        return f"- {text}"
    return text


class _SectionBuilder:
    """Accumulates text under the most recent canonical heading."""

    def __init__(self) -> None:
        self.sections: list[Section] = []
        self.current: Section | None = None
        self._seen: set[str] = set()

    def heading(self, text: str, page: int | None = None) -> None:
        key = canonical_section(text)
        if key is not None:
            self.current = Section(name=key, heading=text.strip().rstrip(":"))
            self.sections.append(self.current)
        elif self.current is None:
            self.current = Section(name="overview", heading=text.strip())
            self.sections.append(self.current)
        else:
            self.add(text, page)

    def add(self, text: str, page: int | None = None) -> None:
        text = normalize_text(text)
        if not text:
            return
        fingerprint = f"{page}:{text}"
        if fingerprint in self._seen:
            return
        self._seen.add(fingerprint)
        if self.current is None:
            self.current = Section(name="overview", heading="Overview")
            self.sections.append(self.current)
        self.current.segments.append(Segment(text=text, page=page))

    def result(self) -> list[Section]:
        merged: dict[str, Section] = {}
        order: list[str] = []
        for section in self.sections:
            if not section.segments:
                continue
            if section.name in merged:
                merged[section.name].segments.extend(section.segments)
            else:
                merged[section.name] = section.model_copy(deep=True)
                order.append(section.name)
        return [merged[name] for name in order]


def parse_html(html: str) -> tuple[str | None, list[Section], str]:
    """Return (title, sections, plain text) for an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1")
    title = title_tag.get_text(" ", strip=True) if title_tag else None
    if not title and soup.title and soup.title.string:
        title = _TITLE_SUFFIX.sub("", soup.title.string.strip())
    for tag in soup(_NOISE):
        tag.decompose()
    root = soup.find("main") or soup.body or soup

    builder = _SectionBuilder()
    for element in root.descendants:
        if not isinstance(element, Tag):
            continue
        if element.name in _HEADINGS:
            text = element.get_text(" ", strip=True)
            if text and text != title:
                builder.heading(text)
            continue
        section_id = element.get("id")
        if isinstance(section_id, str) and canonical_section(section_id.replace("-", " ")):
            heading = element.find(list(_HEADINGS))
            if heading is None:
                builder.heading(section_id.replace("-", " ").title())
        if element.name in _BLOCKS and _leaf_block(element):
            if element.find_parent(list(_HEADINGS)):
                continue
            direct = "".join(
                str(c) for c in element.children if isinstance(c, NavigableString)
            ).strip()
            if element.name in {"div", "section"} and not direct and not element.find(True):
                continue
            builder.add(_block_text(element))
    plain = normalize_text(root.get_text("\n", strip=True))
    return title, builder.result(), plain


def parse_pdf(path: Path) -> tuple[str | None, list[Section], str]:
    """Return (title, sections, plain text) for a PDF, keeping page numbers."""
    import pymupdf

    builder = _SectionBuilder()
    plain_parts: list[str] = []
    title: str | None = None
    with pymupdf.open(path) as doc:
        meta_title = (doc.metadata or {}).get("title") or None
        lines: list[tuple[int, str, float, bool]] = []
        sizes: list[float] = []
        for page_index, page in enumerate(doc, start=1):
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in spans).strip()
                    size = max(float(s.get("size", 0)) for s in spans)
                    bold = all(int(s.get("flags", 0)) & 16 for s in spans)
                    lines.append((page_index, text, size, bold))
                    sizes.extend([size] * len(text))
        body_size = statistics.median(sizes) if sizes else 10.0

        paragraph: list[str] = []
        paragraph_page: int | None = None

        def flush() -> None:
            nonlocal paragraph, paragraph_page
            if paragraph:
                builder.add(" ".join(paragraph), paragraph_page)
            paragraph, paragraph_page = [], None

        for page_index, text, size, bold in lines:
            plain_parts.append(text)
            is_heading = len(text) <= 100 and (
                size >= body_size * 1.15 or (bold and len(text) <= 60)
            )
            if is_heading:
                flush()
                if title is None and page_index == 1 and size >= body_size * 1.3:
                    title = text
                    continue
                builder.heading(text, page_index)
                continue
            if paragraph_page is not None and page_index != paragraph_page:
                flush()
            if paragraph_page is None:
                paragraph_page = page_index
            paragraph.append(text)
            if text.endswith((".", ":", "।", "?")) or text.startswith(("-", "•", "*")):
                flush()
        flush()
    return title or meta_title, builder.result(), normalize_text("\n".join(plain_parts))


def _infer_ministry(text: str) -> str | None:
    head = text[:4000]
    match = _MINISTRY.search(head)
    if match:
        return " ".join(match.group(1).split())
    match = _MINISTRY_HI.search(head)
    return match.group(1).strip() if match else None


def _infer_state(title: str, ministry: str | None, text: str) -> str:
    match = _GOVT_OF.search(text[:3000])
    if match:
        state = normalize_state(match.group(1))
        if state and state != "India":
            return state
    for candidate in (title, ministry or ""):
        states = find_states(candidate)
        if states:
            return states[0]
    return ALL_STATES


def build_metadata(
    path: Path,
    title: str | None,
    plain: str,
    sidecar: dict[str, Any],
    source_url: str | None,
    *,
    is_sample: bool,
) -> DocumentMeta:
    name = str(sidecar.get("scheme_name") or title or path.stem.replace("-", " ").title())
    ministry = sidecar.get("ministry") or _infer_ministry(plain)
    state = normalize_state(sidecar.get("state")) or _infer_state(name, ministry, plain)
    tags = [str(t) for t in sidecar.get("tags", [])]
    category = sidecar.get("category") or guess_category(" ".join([name, *tags, plain[:3000]]))
    url_slug = urlslug(source_url) if source_url else None
    scheme_id = str(sidecar.get("scheme_id") or url_slug or slugify(name))
    return DocumentMeta(
        scheme_id=scheme_id,
        scheme_name=name,
        ministry=ministry,
        state=state,
        category=category,
        tags=tags,
        source_url=str(sidecar.get("source_url") or source_url or path.as_uri()),
        language=str(sidecar.get("language") or detect_script_language(plain[:5000])),
        is_sample=bool(sidecar.get("is_sample", is_sample)),
    )


def urlslug(url: str) -> str | None:
    """Scheme slug from URLs like `.../schemes/<slug>` (also the `/hi/` variant)."""
    match = re.search(r"/schemes?/([a-z0-9][a-z0-9-]*)/?$", url, re.I)
    return match.group(1).lower() if match else None


def parse_file(
    path: Path,
    *,
    relative_to: Path,
    source_url: str | None = None,
    is_sample: bool = False,
) -> ParsedDocument:
    """Parse one HTML or PDF file into a `ParsedDocument`."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {path.name}")
    if suffix == ".pdf":
        title, sections, plain = parse_pdf(path)
        kind = "pdf"
    else:
        html = path.read_text(encoding="utf-8", errors="replace")
        title, sections, plain = parse_html(html)
        kind = "html"
    sidecar = load_sidecar(path)
    meta = build_metadata(path, title, plain, sidecar, source_url, is_sample=is_sample)
    try:
        rel = path.resolve().relative_to(relative_to.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    content_hash = file_hash(path)
    return ParsedDocument(
        doc_id=hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16],
        path=rel,
        content_hash=content_hash,
        kind=kind,
        meta=meta,
        sections=sections,
        parsed_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
