from __future__ import annotations

import pytest

from yojana.agent.router import detect_language, rule_based_intent, understand
from yojana.llm.gateway import AllProvidersExhausted

from fakes import FakeGateway


@pytest.mark.parametrize(
    ("text", "preferred", "expected"),
    [
        ("Which scholarships can I get?", None, "en"),
        ("मुझे कौन सी छात्रवृत्ति मिल सकती है?", None, "hi"),
        ("mujhe kisan yojana ke liye kya chahiye", None, "hi"),
        ("22", "hi", "hi"),
        ("yes", "hi", "hi"),
        ("Tell me about startup schemes in Karnataka", "hi", "en"),
    ],
)
def test_detect_language(text: str, preferred: str | None, expected: str) -> None:
    assert detect_language(text, preferred) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What documents are needed for Test Scheme Alpha?", "documents"),
        ("Am I eligible for this scholarship?", "eligibility_check"),
        ("Compare scheme A vs scheme B", "compare"),
        ("Scholarships for students", "discover"),
        ("hello", "chitchat"),
        ("Write me a poem about the monsoon rains tonight", "out_of_scope"),
        ("मुझे कौन से दस्तावेज़ चाहिए?", "documents"),
        ("I am a 22 year old farmer from Goa", "eligibility_check"),
    ],
)
def test_rule_based_intent(text: str, expected: str) -> None:
    assert rule_based_intent(text) == expected


def test_scheme_mention_turns_discover_into_explain() -> None:
    assert rule_based_intent("Test Scheme Alpha benefits support", has_scheme_mention=True) in (
        "explain",
        "discover",
    )
    assert rule_based_intent("Test Scheme Alpha", has_scheme_mention=True) == "explain"


async def test_understand_merges_llm_and_regex_profile() -> None:
    gateway = FakeGateway(
        [
            {
                "intent": "eligibility_check",
                "standalone_query": "scholarship eligibility for SC graduate students",
                "profile": {"age": 99, "social_category": "Scheduled Caste", "gender": "female"},
                "scheme_names": [],
            }
        ]
    )
    result = await understand(gateway, "I'm 21, SC, am I eligible?")
    assert result.used_llm
    assert result.intent == "eligibility_check"
    assert result.profile_updates.age == 21
    assert result.profile_updates.social_category == "sc"
    assert result.profile_updates.gender == "female"
    assert gateway.calls[0]["sensitive"] is True


async def test_understand_falls_back_to_rules_without_llm() -> None:
    gateway = FakeGateway([AllProvidersExhausted([])])
    history = [{"role": "user", "content": "scholarships for engineering students"}]
    result = await understand(gateway, "in Kerala?", history=history)
    assert not result.used_llm
    assert result.standalone_query == "scholarships for engineering students in Kerala?"
    assert result.profile_updates.state == "Kerala"


async def test_understand_keeps_documents_intent_from_rules() -> None:
    gateway = FakeGateway(
        [{"intent": "explain", "standalone_query": "documents for alpha", "scheme_names": []}]
    )
    result = await understand(gateway, "Which documents do I need for alpha?")
    assert result.intent == "documents"


async def test_unknown_llm_intent_uses_rule_intent() -> None:
    gateway = FakeGateway([{"intent": "weather", "standalone_query": "x"}])
    result = await understand(gateway, "hello there")
    assert result.intent == "chitchat"
