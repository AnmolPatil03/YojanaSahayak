"""Language detection, intent routing, slot extraction and query condensing."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from yojana.agent.slots import UserProfile, extract_profile
from yojana.llm.gateway import AllProvidersExhausted, LLMGateway
from yojana.taxonomy import devanagari_ratio

logger = logging.getLogger(__name__)

Language = Literal["en", "hi"]
Intent = Literal[
    "discover", "explain", "eligibility_check", "documents", "compare", "chitchat", "out_of_scope"
]
INTENTS: tuple[str, ...] = (
    "discover",
    "explain",
    "eligibility_check",
    "documents",
    "compare",
    "chitchat",
    "out_of_scope",
)

_HINGLISH = re.compile(
    r"\b(kya|hai|hain|mujhe|mera|meri|mere|kaun|kaunsi|kaise|kitna|chahiye|yojana|"
    r"liye|karna|milega|milegi|kisan|sarkari|batao|bataiye|aur|nahi|hoon|hu)\b",
    re.I,
)

_RULES: list[tuple[Intent, re.Pattern[str]]] = [
    (
        "documents",
        re.compile(
            r"document|papers?|certificate|checklist|what (do i|should i) (need|submit|bring)|"
            r"दस्तावेज|कागज|प्रमाण पत्र|kagaz|dastavez",
            re.I,
        ),
    ),
    (
        "compare",
        re.compile(r"\bcompare\b|\bversus\b|\bvs\.?\b|difference between|तुलना|अंतर", re.I),
    ),
    (
        "eligibility_check",
        re.compile(
            r"eligib|am i (able|allowed|qualified)|can i (apply|get|avail)|do i qualify|"
            r"qualify|पात्र|योग्य|क्या मैं|मिल सकता|मिल सकती|kya main",
            re.I,
        ),
    ),
    (
        "explain",
        re.compile(
            r"\bwhat is\b|\btell me about\b|\bexplain\b|\bdetails? of\b|\bbenefits? of\b|"
            r"how (do|can) i apply|how to apply|के बारे में|क्या है|बताइए|आवेदन कैसे",
            re.I,
        ),
    ),
    (
        "discover",
        re.compile(
            r"scheme|yojana|scholarship|subsidy|grant|loan|pension|benefit|support|help for|"
            r"for (farmers|students|women|girls)|योजना|छात्रवृत्ति|सब्सिडी|सहायता|अनुदान",
            re.I,
        ),
    ),
    (
        "chitchat",
        re.compile(
            r"^\s*(hi|hello|hey|namaste|namaskar|thanks|thank you|good (morning|evening)|"
            r"who are you|नमस्ते|धन्यवाद|शुक्रिया)\b",
            re.I,
        ),
    ),
]


def detect_language(text: str, preferred: str | None = None) -> Language:
    """'hi' for Devanagari or clearly romanised Hindi, otherwise 'en'.

    Very short messages ("yes", "22") carry no signal, so the UI language wins.
    """
    if devanagari_ratio(text) >= 0.3:
        return "hi"
    if len(_HINGLISH.findall(text)) >= 2:
        return "hi"
    if preferred in ("en", "hi") and len(re.findall(r"[A-Za-z]{2,}", text)) <= 2:
        return preferred  # type: ignore[return-value]
    return "en"


def rule_based_intent(text: str, *, has_scheme_mention: bool = False) -> Intent:
    """Keyword routing used when no LLM is available (and as the LLM's tie-break)."""
    for intent, pattern in _RULES:
        if pattern.search(text):
            if intent == "discover" and has_scheme_mention:
                return "explain"
            return intent
    if has_scheme_mention:
        return "explain"
    if not extract_profile(text).is_empty():
        return "eligibility_check"
    return "out_of_scope" if len(text.split()) > 3 else "chitchat"


class ProfileUpdate(BaseModel):
    age: int | None = None
    gender: str | None = None
    state: str | None = None
    annual_family_income: int | None = None
    social_category: str | None = None
    occupation: str | None = None
    education_level: str | None = None
    disability: bool | None = None
    residence: str | None = None


class LLMUnderstanding(BaseModel):
    intent: str = "discover"
    standalone_query: str = ""
    profile: ProfileUpdate = Field(default_factory=ProfileUpdate)
    scheme_names: list[str] = Field(default_factory=list)


class Understanding(BaseModel):
    """Result of the first stage of every turn."""

    language: Language
    intent: Intent
    standalone_query: str
    profile_updates: UserProfile
    scheme_mentions: list[str] = Field(default_factory=list)
    used_llm: bool = False


_UNDERSTAND_PROMPT = """You route messages for an assistant that helps people in India \
find government welfare schemes. Read the conversation and the latest message and return \
JSON with:
- intent: one of discover (find schemes), explain (details of a named scheme), \
eligibility_check (whether the user qualifies), documents (documents needed), compare \
(two or more schemes), chitchat (greetings, thanks), out_of_scope (anything unrelated \
to welfare schemes).
- standalone_query: the latest message rewritten as a self-contained search query in \
the user's language, resolving pronouns and follow-ups from the conversation. Do not \
add facts the user did not say.
- profile: only facts the user stated about themselves in the latest message: age \
(years), gender (male/female/transgender), state (Indian state name), \
annual_family_income (rupees per year), social_category (general/obc/sc/st/ews/minority), \
occupation, education_level (below_10th/10th/12th/diploma/graduate/postgraduate/phd), \
disability (true/false), residence (rural/urban). Use null for anything not stated.
- scheme_names: names of specific schemes the user mentions, exactly as written."""


def _history_text(history: Sequence[dict[str, Any]], limit: int) -> str:
    lines = []
    for turn in list(history)[-limit:]:
        role = "User" if turn.get("role") == "user" else "Assistant"
        content = " ".join(str(turn.get("content", "")).split())[:600]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _clean_updates(update: ProfileUpdate) -> UserProfile:
    try:
        return UserProfile.model_validate(update.model_dump())
    except ValueError:
        values = {}
        for key, value in update.model_dump().items():
            try:
                values[key] = UserProfile.model_validate({key: value}).model_dump()[key]
            except ValueError:
                continue
        return UserProfile.model_validate(values)


def _fallback_query(message: str, history: Sequence[dict[str, Any]]) -> str:
    """Without an LLM, prepend the previous user turn to short follow-ups."""
    previous = [t for t in history if t.get("role") == "user"]
    if previous and len(message.split()) <= 6:
        return f"{previous[-1].get('content', '')} {message}".strip()
    return message


async def understand(
    gateway: LLMGateway | None,
    message: str,
    *,
    history: Sequence[dict[str, Any]] = (),
    scheme_mentions: Sequence[str] = (),
    preferred_language: str | None = None,
    history_turns: int = 6,
    use_llm: bool = True,
) -> Understanding:
    """Detect language, classify intent, extract profile facts and condense the query.

    The regex extractor always runs; when an LLM answers, its values fill gaps but
    never override what the extractor found verbatim in the message.
    """
    language = detect_language(message, preferred_language)
    regex_profile = extract_profile(message)
    rule_intent = rule_based_intent(message, has_scheme_mention=bool(scheme_mentions))
    result = Understanding(
        language=language,
        intent=rule_intent,
        standalone_query=_fallback_query(message, history),
        profile_updates=regex_profile,
        scheme_mentions=list(scheme_mentions),
    )
    if gateway is None or not use_llm:
        return result

    convo = _history_text(history, history_turns)
    user = f"Conversation so far:\n{convo or '(none)'}\n\nLatest message:\n{message}"
    try:
        parsed, _ = await gateway.complete_json(
            [{"role": "system", "content": _UNDERSTAND_PROMPT}, {"role": "user", "content": user}],
            LLMUnderstanding,
            task="understand",
            sensitive=True,
            max_tokens=400,
        )
    except AllProvidersExhausted as exc:
        logger.info("Understanding fell back to rules: %s", exc)
        return result

    intent: Intent = parsed.intent if parsed.intent in INTENTS else rule_intent  # type: ignore[assignment]
    if rule_intent in ("documents", "compare") and intent in ("discover", "explain"):
        intent = rule_intent
    llm_profile = _clean_updates(parsed.profile)
    profile = llm_profile.merged(regex_profile)
    query = parsed.standalone_query.strip() or result.standalone_query
    return Understanding(
        language=language,
        intent=intent,
        standalone_query=query,
        profile_updates=profile,
        scheme_mentions=list(scheme_mentions),
        used_llm=True,
    )
