from __future__ import annotations

from pathlib import Path

import pytest

from yojana.config import Settings
from yojana.ingest.registry import SchemeRegistry
from yojana.mcp_server import Backend, build_server
from yojana.rules import RulesStore

from test_pipeline import build_sample_index

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def server(settings: Settings):
    retriever = build_sample_index(settings)
    rules = RulesStore(settings.processed_dir / "rules")
    rules.install_samples(REPO / "data" / "sample" / "rules")
    backend = Backend(
        settings,
        retriever=retriever,
        registry=SchemeRegistry.load(settings.processed_dir / "schemes.json"),
        rules=rules,
    )
    return build_server(backend)


async def call(server, name: str, arguments: dict) -> dict:
    result = await server.call_tool(name, arguments)
    return result.structured_content or result.structuredContent


async def test_lists_the_four_tools(server) -> None:
    names = sorted(tool.name for tool in await server.list_tools())
    assert names == [
        "check_eligibility",
        "get_scheme_details",
        "list_required_documents",
        "search_schemes",
    ]


async def test_search_returns_cited_passages(server) -> None:
    data = await call(
        server, "search_schemes", {"query": "documents disability certificate delta", "top_k": 3}
    )
    assert not data["abstained"]
    first = data["results"][0]
    assert first["citation"] == "[1]"
    assert first["scheme_id"] == "test-scheme-delta"
    assert first["source_url"].startswith("https://example.org/")
    assert len(data["results"]) <= 3


async def test_search_respects_state_filter(server) -> None:
    data = await call(server, "search_schemes", {"query": "farmers seed", "state": "Karnataka"})
    assert all(r["scheme_id"] != "test-scheme-beta" for r in data["results"])


async def test_details_and_documents(server) -> None:
    details = await call(server, "get_scheme_details", {"scheme_id": "test-scheme-gamma"})
    assert details["name"] == "Test Scheme Gamma"
    assert details["rules"]["rules"]["min_age"]["value"] == 21
    docs = await call(server, "list_required_documents", {"scheme_id": "test-scheme-gamma"})
    assert [d["text"] for d in docs["documents"]][:2] == ["Aadhaar card", "PAN card"]
    missing = await call(server, "get_scheme_details", {"scheme_id": "nope"})
    assert "error" in missing


async def test_check_eligibility_uses_engine(server) -> None:
    data = await call(
        server,
        "check_eligibility",
        {"profile": {"age": 28, "occupation": "entrepreneur", "education_level": "graduate"}},
    )
    gamma = next(r for r in data["results"] if r["scheme_id"] == "test-scheme-gamma")
    assert gamma["verdict"] == "eligible"
    assert all(c["source_url"] for c in gamma["criteria"] if c["chunk_id"])
    assert data["results"][0]["scheme_id"] == "test-scheme-gamma"
