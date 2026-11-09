from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

from yojana.config import Settings
from yojana.index.store import ChunkStore
from yojana.ingest.models import Chunk
from yojana.ingest.review_cli import ReviewError, parse_value, render, run, set_field
from yojana.ingest.rules_extract import extract_all, extract_for_scheme, select_rule_chunks
from yojana.rules import RulesRecord, RulesStore

from fakes import FakeGateway

REPO = Path(__file__).resolve().parents[2]


def chunk(cid: str, section: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid,
        doc_id="d",
        scheme_id="test-scheme-omega",
        scheme_name="Test Scheme Omega",
        state="ALL",
        category="education",
        section=section,
        heading=section.title(),
        source_url="https://example.org/omega",
        language="en",
        last_seen="2026-01-01",
        text=text,
        header="Test Scheme Omega",
    )


CHUNKS = [
    chunk("omega::documents", "documents", "Aadhaar card."),
    chunk("omega::eligibility", "eligibility", "Students aged 18 to 30. Income below 2 lakh."),
    chunk("omega::overview", "overview", "A fictional scheme."),
]

REPLY = {
    "min_age": {"value": 18, "chunk_id": "omega::eligibility"},
    "max_age": {"value": 30, "chunk_id": "omega::eligibility"},
    "max_annual_family_income": {"value": 200000, "chunk_id": "omega::eligibility"},
    "occupations": {"value": ["Student"], "chunk_id": "omega::invented"},
    "other_conditions": [{"text": "Must be enrolled full time.", "chunk_id": "omega::overview"}],
}


def test_rule_chunks_prefer_eligibility_sections() -> None:
    assert [c.chunk_id for c in select_rule_chunks(CHUNKS)] == [
        "omega::eligibility",
        "omega::overview",
    ]


async def test_extraction_validates_citations_and_needs_review() -> None:
    gateway = FakeGateway([REPLY])
    record = await extract_for_scheme(gateway, "omega", "Test Scheme Omega", CHUNKS, None)

    assert record is not None and record.needs_review
    assert record.rules.min_age.value == 18
    assert record.rules.occupations.value == ["student"]
    assert record.rules.occupations.chunk_id is None
    assert record.rules.other_conditions[0].chunk_id == "omega::overview"
    assert record.extracted_by == "fake:fake-1"
    call = gateway.calls[0]
    assert call["sensitive"] is False and call["task"] == "rules_extract"
    assert "[omega::eligibility]" in call["messages"][1]["content"]


async def test_unchanged_content_is_skipped_and_review_history_kept() -> None:
    gateway = FakeGateway([REPLY, REPLY])
    first = await extract_for_scheme(gateway, "omega", "Omega", CHUNKS, None)
    assert first is not None
    first.mark_reviewed("tester")
    assert await extract_for_scheme(gateway, "omega", "Omega", CHUNKS, first) is None

    edited = [*CHUNKS[:1], chunk("omega::eligibility", "eligibility", "Students aged 18 to 35.")]
    second = await extract_for_scheme(gateway, "omega", "Omega", edited, first)
    assert second is not None and second.needs_review
    assert second.previous == first.rules


async def test_extract_all_keeps_sample_rules(settings: Settings) -> None:
    from test_pipeline import build_sample_index

    build_sample_index(settings)
    store = RulesStore(settings.processed_dir / "rules")
    store.install_samples(REPO / "data" / "sample" / "rules")
    outcome = await extract_all(settings, gateway=FakeGateway([]))
    assert set(outcome.values()) == {"sample rules kept"}


def test_sample_rules_cite_real_chunks(settings: Settings) -> None:
    from test_pipeline import build_sample_index

    retriever = build_sample_index(settings)
    store = RulesStore(settings.processed_dir / "rules")
    assert store.install_samples(REPO / "data" / "sample" / "rules") == 4
    for record in store.all():
        assert not record.needs_review
        for cid in record.rules.cited_chunk_ids():
            assert cid in retriever.chunks, cid


def test_usable_respects_review_flag(tmp_path: Path) -> None:
    store = RulesStore(tmp_path)
    shutil.copy(REPO / "data" / "sample" / "rules" / "test-scheme-alpha.json", tmp_path)
    record = store.get("test-scheme-alpha")
    assert record is not None
    record.needs_review = True
    store.save(record)
    assert store.usable("test-scheme-alpha", allow_unreviewed=False) is None
    assert store.usable("test-scheme-alpha", allow_unreviewed=True) is not None


def test_review_cli_set_and_approve(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    store = RulesStore(settings.processed_dir / "rules")
    store.install_samples(REPO / "data" / "sample" / "rules")

    assert run(["set", "test-scheme-alpha", "max_age", "27"], settings) == 0
    record = store.get("test-scheme-alpha")
    assert record is not None and record.rules.max_age.value == 27 and record.needs_review

    assert run(["list", "--pending"], settings) == 0
    assert "test-scheme-alpha" in capsys.readouterr().out

    assert run(["approve", "test-scheme-alpha", "--reviewer", "me"], settings) == 0
    approved = store.get("test-scheme-alpha")
    assert approved is not None and not approved.needs_review and approved.reviewed_by == "me"

    assert run(["show", "missing-scheme"], settings) == 1


def test_review_value_parsing() -> None:
    assert parse_value("social_categories", "SC, ST") == ["SC", "ST"]
    assert parse_value("max_annual_family_income", "2,50,000") == 250000
    assert parse_value("disability_required", "yes") is True
    assert parse_value("min_age", "null") is None
    with pytest.raises(ReviewError):
        parse_value("min_age", "eighteen")


def test_set_field_normalises_and_render_shows_sources() -> None:
    record = RulesRecord.model_validate_json(
        (REPO / "data" / "sample" / "rules" / "test-scheme-alpha.json").read_text(encoding="utf-8")
    )
    updated = set_field(record, "genders", "women", None)
    assert updated.rules.genders.value == ["female"]
    with pytest.raises(ReviewError):
        set_field(record, "favourite_colour", "x", None)

    out = io.StringIO()
    chunks = ChunkStore(
        [
            chunk(
                "test-scheme-alpha::b0a15e::eligibility::000",
                "eligibility",
                "Students aged 17 to 25.",
            )
        ]
    )
    render(record, chunks, out)
    text = out.getvalue()
    assert "min_age" in text and "Students aged 17 to 25." in text
    assert "chunk no longer exists" in text
