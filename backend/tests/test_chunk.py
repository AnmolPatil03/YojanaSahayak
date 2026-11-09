from __future__ import annotations

import itertools

from yojana.config import ChunkingConfig
from yojana.ingest.chunk import chunk_document, contextual_header
from yojana.ingest.models import DocumentMeta, ParsedDocument, Section, Segment
from yojana.llm.tokens import TokenCounter


class WordCounter(TokenCounter):
    """One token per whitespace-separated word keeps the arithmetic obvious."""

    def count(self, text: str) -> int:
        return len(text.split())


def make_doc(sections: list[Section]) -> ParsedDocument:
    return ParsedDocument(
        doc_id="abcdef1234567890",
        path="data/raw/x.html",
        content_hash="h",
        kind="html",
        meta=DocumentMeta(
            scheme_id="test-scheme-alpha",
            scheme_name="Test Scheme Alpha",
            ministry="Ministry of Fictional Affairs",
            state="ALL",
            category="education",
            source_url="https://example.org/alpha",
        ),
        sections=sections,
        parsed_at="2026-01-01T00:00:00+00:00",
    )


def numbered(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


def test_sections_never_share_a_chunk() -> None:
    doc = make_doc(
        [
            Section(name="benefits", heading="Benefits", segments=[Segment(text="grant here")]),
            Section(name="eligibility", heading="Eligibility", segments=[Segment(text="age 18")]),
        ]
    )
    chunks = chunk_document(doc, ChunkingConfig(max_tokens=300), WordCounter())
    assert [c.section for c in chunks] == ["benefits", "eligibility"]


def test_long_sections_split_with_overlap_and_limit() -> None:
    paragraphs = "\n".join(numbered(f"p{n}w", 40) for n in range(20))
    doc = make_doc(
        [Section(name="overview", heading="Overview", segments=[Segment(text=paragraphs)])]
    )
    config = ChunkingConfig(max_tokens=100, overlap=0.4, min_tokens=10)

    chunks = chunk_document(doc, config, WordCounter())

    assert len(chunks) > 5
    for chunk in chunks:
        assert len(chunk.text.split()) <= 100
    for first, second in itertools.pairwise(chunks):
        last_paragraph = first.text.split("\n")[-1]
        assert second.text.startswith(last_paragraph)


def test_oversized_paragraph_is_split_on_sentences_then_words() -> None:
    sentence = numbered("w", 30) + "."
    text = " ".join([sentence] * 6) + " " + numbered("x", 250)
    doc = make_doc([Section(name="benefits", heading="Benefits", segments=[Segment(text=text)])])

    chunks = chunk_document(doc, ChunkingConfig(max_tokens=80, overlap=0.0), WordCounter())

    assert all(len(c.text.split()) <= 80 for c in chunks)
    joined = " ".join(c.text for c in chunks).split()
    assert joined == text.split()


def test_header_metadata_and_ids() -> None:
    doc = make_doc(
        [
            Section(
                name="documents",
                heading="Documents Required",
                segments=[
                    Segment(text="- Aadhaar card", page=3),
                    Segment(text="- PAN card", page=4),
                ],
            )
        ]
    )
    (chunk,) = chunk_document(doc, ChunkingConfig(), WordCounter())

    assert chunk.header == "Test Scheme Alpha | Ministry of Fictional Affairs | Documents Required"
    assert chunk.embed_text.startswith(chunk.header + "\n")
    assert chunk.text == "- Aadhaar card\n- PAN card"
    assert chunk.page == 3
    assert chunk.chunk_id == "test-scheme-alpha::abcdef::documents::000"
    assert chunk.language == "en"
    assert chunk.source_url == "https://example.org/alpha"


def test_hindi_chunk_gets_hindi_section_label() -> None:
    doc = make_doc(
        [Section(name="eligibility", heading="पात्रता", segments=[Segment(text="आवेदक किसान हो।")])]
    )
    (chunk,) = chunk_document(doc, ChunkingConfig(), WordCounter())
    assert chunk.language == "hi"
    assert chunk.header.endswith("| पात्रता")


def test_contextual_header_skips_missing_parts() -> None:
    assert contextual_header("Scheme", None, "Benefits") == "Scheme | Benefits"


def test_tiny_trailing_chunk_is_merged() -> None:
    text = numbered("a", 95) + "\n" + numbered("b", 3)
    doc = make_doc([Section(name="overview", heading="Overview", segments=[Segment(text=text)])])
    chunks = chunk_document(
        doc, ChunkingConfig(max_tokens=100, overlap=0.0, min_tokens=10), WordCounter()
    )
    assert len(chunks) == 1
