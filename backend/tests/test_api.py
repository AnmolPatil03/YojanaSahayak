from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yojana.api.main import create_app
from yojana.api.services import Services
from yojana.config import Settings
from yojana.ingest.registry import SchemeRegistry
from yojana.logging_setup import PiiMaskingFilter, mask_pii
from yojana.rules import RulesStore

from fakes import FakeGateway
from test_pipeline import build_sample_index

REPO = Path(__file__).resolve().parents[2]


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def services(settings: Settings) -> Services:
    retriever = build_sample_index(settings)
    rules = RulesStore(settings.processed_dir / "rules")
    rules.install_samples(REPO / "data" / "sample" / "rules")
    svc = Services(
        settings=settings,
        gateway=FakeGateway([]),  # type: ignore[arg-type]
        retriever=retriever,
        registry=SchemeRegistry.load(settings.processed_dir / "schemes.json"),
        rules=rules,
    )
    svc.orchestrator.use_llm_understanding = False
    return svc


@pytest.fixture
def client(settings: Settings, services: Services) -> TestClient:
    settings.warmup_models = False
    with TestClient(create_app(settings, services)) as test_client:
        yield test_client


def test_chat_streams_sse_events(client: TestClient, services: Services) -> None:
    services.gateway.replies.append("Seed grant for prototypes [1].")
    response = client.post(
        "/api/chat",
        json={"message": "What are the benefits of Test Scheme Gamma?", "history": []},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(response.headers["x-request-id"]) == 16
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "stage" and names[-1] == "done"
    assert {"token", "citations", "provider"} <= set(names)


def test_chat_validates_input(client: TestClient) -> None:
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_list_and_filter_schemes(client: TestClient) -> None:
    everything = client.get("/api/schemes").json()
    assert everything["total"] == 4
    assert {"Karnataka", "Maharashtra", "ALL"} <= set(everything["facets"]["states"])
    karnataka = client.get("/api/schemes", params={"state": "Karnataka"}).json()
    assert {i["scheme_id"] for i in karnataka["items"]} == {
        "test-scheme-alpha",
        "test-scheme-gamma",
        "test-scheme-delta",
    }
    startup = client.get("/api/schemes", params={"category": "business"}).json()
    assert [i["scheme_id"] for i in startup["items"]] == ["test-scheme-gamma"]
    searched = client.get("/api/schemes", params={"q": "delta"}).json()
    assert searched["total"] == 1
    paged = client.get("/api/schemes", params={"page": 2, "page_size": 3}).json()
    assert len(paged["items"]) == 1


def test_scheme_detail_and_checklist(client: TestClient) -> None:
    detail = client.get("/api/schemes/test-scheme-alpha").json()
    assert detail["is_sample"] is True
    assert detail["rules_usable"] is True
    assert [s["name"] for s in detail["sections"]][:3] == ["overview", "benefits", "eligibility"]
    assert detail["rule_sources"]
    checklist = client.get("/api/schemes/test-scheme-alpha/checklist").json()
    texts = [i["text"] for i in checklist["items"]]
    assert texts[0] == "Aadhaar card"
    assert "Bank passbook copy" in texts
    assert all(i["chunk_id"].endswith("documents::000") for i in checklist["items"])
    assert client.get("/api/schemes/nope").status_code == 404


def test_eligibility_ranking_with_citations(client: TestClient) -> None:
    profile = {
        "age": 30,
        "gender": "female",
        "state": "Karnataka",
        "annual_family_income": 150000,
        "disability": True,
    }
    data = client.post("/api/eligibility", json={"profile": profile}).json()
    assert data["results"][0]["scheme_id"] == "test-scheme-delta"
    assert data["results"][0]["verdict"] == "eligible"
    verdicts = {r["scheme_id"]: r["verdict"] for r in data["results"]}
    assert verdicts["test-scheme-alpha"] == "ineligible"
    assert verdicts["test-scheme-beta"] == "ineligible"
    criterion = data["results"][0]["criteria"][0]
    assert criterion["source"]["source_url"].startswith("https://example.org/fictional/")
    assert data["counts"]["eligible"] == 1


def test_eligibility_question_for_empty_profile(client: TestClient) -> None:
    data = client.post("/api/eligibility", json={"profile": {}}).json()
    assert data["question"] is not None
    assert data["counts"]["partial"] == 4


def test_provider_health_and_health(client: TestClient) -> None:
    assert client.get("/api/health/providers").json()["providers"] == []
    health = client.get("/api/health").json()
    assert health["schemes"] == 4 and health["chunks"] > 0


def test_eval_latest_reads_newest_report(client: TestClient, settings: Settings) -> None:
    assert client.get("/api/eval/latest").status_code == 404
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "eval-20260101T000000.json").write_text('{"runs": []}', "utf-8")
    (settings.reports_dir / "eval-20260201T000000.json").write_text('{"runs": [1]}', "utf-8")
    report = client.get("/api/eval/latest").json()
    assert report["runs"] == [1] and report["example"] is False


def test_admin_ingest_is_local_only(client: TestClient, settings: Settings, services) -> None:
    assert client.post("/api/admin/ingest").status_code == 403
    with TestClient(create_app(settings, services), client=("127.0.0.1", 5000)) as local:
        assert local.get("/api/admin/ingest").json()["state"] == "idle"


def test_pii_is_masked_in_logs() -> None:
    masked = mask_pii(
        'profile {"age": 22, "annual_family_income": 250000} mail a@b.co phone 9876543210 '
        "aadhaar 1234 5678 9012 key gsk_abcdefghijklmnop1234"
    )
    assert "22" not in masked and "250000" not in masked
    assert "[email]" in masked and "[phone]" in masked and "[id]" in masked and "[key]" in masked

    record = logging.LogRecord("t", logging.INFO, "x", 1, "age=%s", (40,), None)
    PiiMaskingFilter().filter(record)
    assert record.getMessage() == "age=[masked]"
