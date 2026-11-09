from __future__ import annotations

from pathlib import Path

import pytest

from yojana.agent.orchestrator import ChatRequest, Orchestrator
from yojana.agent.slots import UserProfile
from yojana.config import Settings
from yojana.ingest.registry import SchemeRegistry
from yojana.llm.gateway import AllProvidersExhausted, Attempt
from yojana.rules import RulesStore

from fakes import FakeGateway
from test_pipeline import build_sample_index

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def make_orchestrator(settings: Settings):
    retriever = build_sample_index(settings)
    registry = SchemeRegistry.load(settings.processed_dir / "schemes.json")
    rules = RulesStore(settings.processed_dir / "rules")
    rules.install_samples(REPO / "data" / "sample" / "rules")

    def make(replies: list[object], use_llm: bool = False) -> tuple[Orchestrator, FakeGateway]:
        gateway = FakeGateway(replies)
        orchestrator = Orchestrator(
            gateway=gateway,  # type: ignore[arg-type]
            retriever=lambda: retriever,
            registry=lambda: registry,
            rules=rules,
            use_llm_understanding=use_llm,
        )
        return orchestrator, gateway

    return make


async def run(orchestrator: Orchestrator, **kwargs) -> list[dict]:
    return [event async for event in orchestrator.run(ChatRequest(**kwargs))]


def kinds(events: list[dict]) -> list[str]:
    return [e["event"] for e in events]


def text_of(events: list[dict]) -> str:
    return "".join(e["data"]["text"] for e in events if e["event"] == "token")


def stages(events: list[dict]) -> list[str]:
    return [
        e["data"]["stage"] for e in events if e["event"] == "stage" and e["data"]["status"] == "end"
    ]


async def test_documents_question_streams_cited_answer(make_orchestrator) -> None:
    orchestrator, gateway = make_orchestrator(
        ["You need an Aadhaar card [1], a disability certificate [1] and a pass [9]."]
    )
    events = await run(orchestrator, message="What documents are required for Test Scheme Delta?")

    assert stages(events) == ["understanding", "searching", "fusing", "reranking", "writing"]
    assert kinds(events)[-1] == "done"
    assert text_of(events).strip() == (
        "You need an Aadhaar card [1], a disability certificate [1] and a pass."
    )
    citations = next(e for e in events if e["event"] == "citations")["data"]["sources"]
    assert citations[0]["scheme_id"] == "test-scheme-delta"
    assert citations[0]["section"] == "documents"
    assert citations[0]["cited"] is True
    provider = next(e for e in events if e["event"] == "provider")["data"]
    assert provider["name"] == "fake"
    assert gateway.calls[0]["sensitive"] is False
    prompt = gateway.calls[0]["messages"][-1]["content"]
    assert "[1] Test Scheme Delta" in prompt


async def test_eligibility_check_with_missing_details_asks_instead_of_guessing(
    make_orchestrator,
) -> None:
    orchestrator, gateway = make_orchestrator([])
    events = await run(orchestrator, message="Am I eligible for Test Scheme Alpha?")

    assert "checking_eligibility" in stages(events)
    eligibility = next(e for e in events if e["event"] == "eligibility")["data"]
    alpha = next(r for r in eligibility["results"] if r["scheme_id"] == "test-scheme-alpha")
    assert alpha["verdict"] == "partial"
    clarify = next(e for e in events if e["event"] == "clarify")["data"]
    assert clarify["field"] in alpha["missing_fields"]
    assert "one more detail" in text_of(events)
    assert gateway.calls == []


async def test_profile_from_message_reaches_engine(make_orchestrator) -> None:
    orchestrator, gateway = make_orchestrator(["Explanation [1]."])
    events = await run(
        orchestrator,
        message=(
            "Am I eligible for Test Scheme Alpha? I am a 20 year old SC graduate student "
            "and my family income is 2 lakh"
        ),
    )
    understanding = next(
        e
        for e in events
        if e["event"] == "stage"
        and e["data"]["stage"] == "understanding"
        and e["data"]["status"] == "end"
    )["data"]
    assert understanding["profile_updates"]["age"] == 20
    eligibility = next(e for e in events if e["event"] == "eligibility")["data"]
    alpha = next(r for r in eligibility["results"] if r["scheme_id"] == "test-scheme-alpha")
    assert alpha["verdict"] == "eligible"
    assert gateway.calls[0]["sensitive"] is True
    assert "ENGINE RESULT" in gateway.calls[0]["messages"][-1]["content"]


async def test_asked_fields_are_not_asked_again(make_orchestrator) -> None:
    orchestrator, _ = make_orchestrator([])
    first = await run(orchestrator, message="Am I eligible for Test Scheme Alpha?")
    field = next(e for e in first if e["event"] == "clarify")["data"]["field"]
    second = await run(
        orchestrator,
        message="Am I eligible for Test Scheme Alpha?",
        asked_fields=[field],
        profile=UserProfile(),
    )
    clarify = [e for e in second if e["event"] == "clarify"]
    assert not clarify or clarify[0]["data"]["field"] != field


async def test_unanswerable_question_abstains_without_llm(make_orchestrator) -> None:
    orchestrator, gateway = make_orchestrator([])
    events = await run(orchestrator, message="pension rules for retired railway staff overseas")
    assert "couldn't find" in text_of(events)
    assert events[-1]["data"]["abstained"] is True
    assert gateway.calls == []


async def test_out_of_scope_and_greeting(make_orchestrator) -> None:
    orchestrator, _gateway = make_orchestrator([AllProvidersExhausted([])])
    off_topic = await run(orchestrator, message="Who won the football match yesterday evening?")
    assert "only help with Indian government welfare schemes" in text_of(off_topic)
    hello = await run(orchestrator, message="नमस्ते")
    assert text_of(hello).startswith("नमस्ते!")


async def test_all_providers_down_gives_error_and_extractive_answer(make_orchestrator) -> None:
    exhausted = AllProvidersExhausted([Attempt("groq", "rate limited (429)")])
    orchestrator, _ = make_orchestrator([exhausted])
    events = await run(
        orchestrator, message="Seed grant benefits for startups in Test Scheme Gamma"
    )

    error = next(e for e in events if e["event"] == "error")["data"]
    assert error["code"] == "all_providers_exhausted"
    assert error["attempts"] == [{"provider": "groq", "reason": "rate limited (429)"}]
    assert "passages match your question" in text_of(events)
    assert events[-1]["data"]["degraded"] is True


async def test_hindi_question_gets_hindi_prompt(make_orchestrator) -> None:
    orchestrator, gateway = make_orchestrator(["उत्तर [1]।"])
    events = await run(orchestrator, message="परीक्षण योजना बीटा के लिए आवश्यक दस्तावेज़ क्या हैं?")
    assert events[-1]["data"]["language"] == "hi"
    assert "सरल हिंदी" in gateway.calls[0]["messages"][0]["content"]


async def test_llm_understanding_is_used_when_enabled(make_orchestrator) -> None:
    orchestrator, _gateway = make_orchestrator(
        [
            {
                "intent": "documents",
                "standalone_query": "documents required for Test Scheme Alpha",
                "profile": {},
                "scheme_names": ["Test Scheme Alpha"],
            },
            "Aadhaar card [1].",
        ],
        use_llm=True,
    )
    events = await run(
        orchestrator,
        message="and what about the papers?",
        history=[{"role": "user", "content": "Tell me about Test Scheme Alpha"}],
    )
    understanding = next(
        e["data"]
        for e in events
        if e["event"] == "stage"
        and e["data"]["stage"] == "understanding"
        and e["data"]["status"] == "end"
    )
    assert understanding["intent"] == "documents"
    assert understanding["schemes"] == ["test-scheme-alpha"]
    citations = next(e for e in events if e["event"] == "citations")["data"]["sources"]
    assert all(c["scheme_id"] == "test-scheme-alpha" for c in citations)
