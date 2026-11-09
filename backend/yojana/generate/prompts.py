"""Prompt templates for grounded, cited answers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from yojana.agent.eligibility import SchemeEligibility
from yojana.ingest.models import Chunk

_SYSTEM_EN = """You are Yojana Sahayak, an assistant that helps people in India understand \
government welfare schemes.

Answer only from the numbered sources below. Every sentence that states a fact about a \
scheme must end with the citation of the source it comes from, like [1] or [2][3]. Never \
cite a number that is not in the source list. If the sources do not contain the answer, \
say that you could not find it in the scheme documents and suggest what the user could \
ask instead. Do not use outside knowledge, and never invent amounts, dates, deadlines or \
criteria.

Eligibility is decided by a separate rule engine, never by you. When an ENGINE RESULT is \
given, explain it in plain words: what is met, what is not, and what is still unknown. Do \
not change its verdicts. If information is missing, say which detail is needed.

Write clearly and briefly for a general audience. Use short paragraphs or bullet points. \
Reply in English."""

_SYSTEM_HI = """आप योजना सहायक हैं, जो भारत में लोगों को सरकारी कल्याण योजनाएँ समझने में \
मदद करते हैं।

केवल नीचे दिए गए क्रमांकित स्रोतों से उत्तर दें। किसी योजना के बारे में तथ्य बताने वाला हर वाक्य \
अपने स्रोत के उद्धरण के साथ खत्म हो, जैसे [1] या [2][3]। सूची में न होने वाला क्रमांक कभी न लिखें। \
यदि स्रोतों में उत्तर नहीं है, तो बताएं कि योजना दस्तावेज़ों में यह जानकारी नहीं मिली। बाहरी जानकारी \
का उपयोग न करें और राशि, तिथि या शर्तें कभी न गढ़ें।

पात्रता एक अलग नियम इंजन तय करता है, आप नहीं। ENGINE RESULT दिया गया हो तो उसे सरल शब्दों में \
समझाएं: कौन सी शर्त पूरी है, कौन सी नहीं, और कौन सी जानकारी अभी बाकी है। उसके निर्णय न बदलें।

साफ़ और संक्षिप्त लिखें। उत्तर सरल हिंदी में दें।"""

_INTENT_HINTS = {
    "documents": "The user wants the list of documents required. List them as bullet points.",
    "compare": "The user wants a comparison. Compare the schemes point by point.",
    "eligibility_check": "The user wants to know if they qualify. Explain the ENGINE RESULT.",
    "discover": "The user is looking for suitable schemes. Name each relevant scheme and say "
    "briefly what it offers and who it is for.",
    "explain": "The user wants details about a scheme: what it offers, who can apply and how.",
}

CHITCHAT_SYSTEM = (
    "You are Yojana Sahayak, an assistant for Indian government welfare schemes. Reply "
    "to the greeting or small talk in one or two friendly sentences, then offer to help "
    "find schemes, check eligibility or list documents. Do not state any scheme facts. "
    "Reply in {language}."
)


def system_prompt(language: str) -> str:
    return _SYSTEM_HI if language == "hi" else _SYSTEM_EN


def format_sources(sources: Sequence[Chunk]) -> str:
    blocks = []
    for number, chunk in enumerate(sources, start=1):
        location = f", page {chunk.page}" if chunk.page else ""
        blocks.append(f"[{number}] {chunk.header}{location}\n{chunk.text}")
    return "\n\n".join(blocks)


def format_engine_result(
    results: Sequence[SchemeEligibility], source_numbers: dict[str, int]
) -> str:
    """Render engine output with source numbers the model can cite."""
    lines = []
    for result in results:
        lines.append(f"- {result.scheme_name}: {result.verdict} ({result.met}/{result.total} met)")
        for criterion in result.criteria:
            ref = source_numbers.get(criterion.chunk_id or "")
            cite = f" [{ref}]" if ref else ""
            actual = f"; user: {criterion.actual}" if criterion.actual else ""
            lines.append(
                f"    {criterion.status}: {criterion.label} - {criterion.expected}{actual}{cite}"
            )
    return "\n".join(lines)


def build_answer_messages(
    *,
    question: str,
    language: str,
    intent: str,
    sources: Sequence[Chunk],
    engine_results: Sequence[SchemeEligibility] = (),
    history: Sequence[dict[str, Any]] = (),
    missing_question: str | None = None,
) -> list[dict[str, str]]:
    """Assemble the generation prompt: system rules, sources, engine output, question."""
    numbers = {chunk.chunk_id: i for i, chunk in enumerate(sources, start=1)}
    parts = [f"SOURCES\n{format_sources(sources)}"]
    if engine_results:
        parts.append(f"ENGINE RESULT\n{format_engine_result(engine_results, numbers)}")
    if missing_question:
        parts.append(
            "The user will also be asked this follow-up question, so you may mention "
            f"that this detail is needed: {missing_question}"
        )
    hint = _INTENT_HINTS.get(intent)
    if hint:
        parts.append(f"TASK\n{hint}")
    parts.append(f"QUESTION\n{question}")
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt(language)}]
    for turn in list(history)[-4:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": str(turn.get("content", ""))[:1500]})
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages
