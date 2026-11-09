"""Data models shared by the ingestion and indexing stages."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Segment(BaseModel):
    text: str
    page: int | None = None


class Section(BaseModel):
    """A canonical scheme section (eligibility, benefits, ...) within one document."""

    name: str
    heading: str
    segments: list[Segment] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments if s.text.strip())

    @property
    def first_page(self) -> int | None:
        return next((s.page for s in self.segments if s.page is not None), None)


class DocumentMeta(BaseModel):
    """Scheme-level metadata, from a sidecar file when present, otherwise inferred."""

    scheme_id: str
    scheme_name: str
    ministry: str | None = None
    state: str = "ALL"
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    source_url: str
    language: str = "en"
    is_sample: bool = False


class ParsedDocument(BaseModel):
    doc_id: str
    path: str
    content_hash: str
    kind: str
    meta: DocumentMeta
    sections: list[Section]
    parsed_at: str


class Chunk(BaseModel):
    """One retrievable passage plus everything needed to cite it."""

    chunk_id: str
    doc_id: str
    scheme_id: str
    scheme_name: str
    ministry: str | None = None
    state: str
    category: str
    section: str
    heading: str
    source_url: str
    page: int | None = None
    language: str
    last_seen: str
    is_sample: bool = False
    text: str
    header: str

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n{self.text}"


class SchemeSection(BaseModel):
    name: str
    heading: str
    text: str
    language: str
    source_url: str
    page: int | None = None
    chunk_ids: list[str] = Field(default_factory=list)


class SchemeRecord(BaseModel):
    """Everything known about one scheme, merged across its source documents."""

    scheme_id: str
    name: str
    names: dict[str, str] = Field(default_factory=dict)
    ministry: str | None = None
    state: str = "ALL"
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    sections: list[SchemeSection] = Field(default_factory=list)
    last_seen: str
    is_sample: bool = False

    def section_text(self, name: str, language: str | None = None) -> str:
        parts = [
            s.text
            for s in self.sections
            if s.name == name and (language is None or s.language == language)
        ]
        return "\n\n".join(parts)

    def summary(self, max_chars: int = 240) -> str:
        text = self.section_text("overview") or self.section_text("benefits")
        text = " ".join(text.split())
        return text if len(text) <= max_chars else text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
