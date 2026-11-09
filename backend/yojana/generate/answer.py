"""Grounded answer generation with streaming citation validation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from yojana.agent.eligibility import SchemeEligibility
from yojana.generate.citations import CitationStreamFilter, validate_citations
from yojana.generate.prompts import CHITCHAT_SYSTEM, build_answer_messages
from yojana.ingest.models import Chunk
from yojana.llm.gateway import (
    LLMGateway,
    ProviderStarted,
    ProviderSwitched,
    StreamDone,
    TokenDelta,
)
from yojana.llm.tokens import TokenCounter
from yojana.taxonomy import section_label

_PROMPT_RESERVE = 900


@dataclass(slots=True)
class AnswerEvent:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


def fit_sources(
    sources: Sequence[Chunk], budget: int, counter: TokenCounter, overhead: int
) -> list[Chunk]:
    """Keep the best-ranked sources that fit within the provider's input budget."""
    kept: list[Chunk] = []
    used = overhead
    for chunk in sources:
        cost = counter.count(chunk.header) + counter.count(chunk.text) + 8
        if kept and used + cost > budget:
            break
        kept.append(chunk)
        used += cost
    return kept


def citation_payload(sources: Sequence[Chunk], cited: Sequence[int]) -> list[dict[str, Any]]:
    return [
        {
            "n": number,
            "chunk_id": chunk.chunk_id,
            "scheme_id": chunk.scheme_id,
            "scheme_name": chunk.scheme_name,
            "section": chunk.section,
            "section_label": section_label(chunk.section, chunk.language),
            "heading": chunk.heading,
            "source_url": chunk.source_url,
            "page": chunk.page,
            "text": chunk.text,
            "language": chunk.language,
            "is_sample": chunk.is_sample,
            "cited": number in cited,
        }
        for number, chunk in enumerate(sources, start=1)
    ]


def extractive_answer(sources: Sequence[Chunk], language: str) -> str:
    """Answer built only from source text, used when no LLM provider is available."""
    intro = (
        "मैं अभी पूरा उत्तर नहीं लिख पा रहा हूँ, लेकिन ये अंश आपके प्रश्न से सबसे अधिक मेल खाते हैं:"
        if language == "hi"
        else "I can't write a full answer right now, but these passages match your question best:"
    )
    lines = [intro, ""]
    for number, chunk in enumerate(sources[:3], start=1):
        snippet = " ".join(chunk.text.split())
        if len(snippet) > 280:
            snippet = snippet[:279].rsplit(" ", 1)[0] + "…"
        label = section_label(chunk.section, language)
        lines.append(f"- **{chunk.scheme_name}, {label}:** {snippet} [{number}]")
    return "\n".join(lines)


class AnswerGenerator:
    """Builds the prompt, streams tokens through the citation filter, reports citations."""

    def __init__(self, gateway: LLMGateway, counter: TokenCounter | None = None) -> None:
        self.gateway = gateway
        self.counter = counter or TokenCounter()

    def prepare(
        self,
        *,
        question: str,
        language: str,
        intent: str,
        sources: Sequence[Chunk],
        engine_results: Sequence[SchemeEligibility],
        history: Sequence[dict[str, Any]],
        missing_question: str | None,
        sensitive: bool,
    ) -> tuple[list[dict[str, str]], list[Chunk]]:
        budget = self.gateway.max_input_tokens(sensitive=sensitive) or 3500
        skeleton = build_answer_messages(
            question=question,
            language=language,
            intent=intent,
            sources=[],
            engine_results=engine_results,
            history=history,
            missing_question=missing_question,
        )
        overhead = self.counter.count_messages(skeleton) + _PROMPT_RESERVE
        kept = fit_sources(sources, budget, self.counter, overhead)
        messages = build_answer_messages(
            question=question,
            language=language,
            intent=intent,
            sources=kept,
            engine_results=engine_results,
            history=history,
            missing_question=missing_question,
        )
        return messages, kept

    async def stream(
        self,
        messages: list[dict[str, str]],
        sources: Sequence[Chunk],
        *,
        sensitive: bool,
    ) -> AsyncIterator[AnswerEvent]:
        """Yield provider, provider_switch, token and final events.

        Raises:
            AllProvidersExhausted: When no provider can answer.
        """
        citation_filter = CitationStreamFilter(len(sources))
        async for event in self.gateway.stream(
            messages, task="answer", sensitive=sensitive, temperature=0.2, max_tokens=900
        ):
            if isinstance(event, ProviderStarted):
                yield AnswerEvent(
                    "provider",
                    {
                        "name": event.provider,
                        "label": event.label,
                        "model": event.model,
                        "offline": event.offline,
                        "cached": event.cached,
                    },
                )
            elif isinstance(event, ProviderSwitched):
                citation_filter = CitationStreamFilter(len(sources))
                yield AnswerEvent(
                    "provider_switch",
                    {
                        "from": event.from_provider,
                        "to": event.to_provider,
                        "label": event.to_label,
                        "reason": event.reason,
                    },
                )
            elif isinstance(event, TokenDelta):
                text = citation_filter.feed(event.text)
                if text:
                    yield AnswerEvent("token", {"text": text})
            elif isinstance(event, StreamDone):
                tail = citation_filter.flush()
                if tail:
                    yield AnswerEvent("token", {"text": tail})
                check = validate_citations(event.text, len(sources))
                yield AnswerEvent(
                    "final",
                    {
                        "text": check.text,
                        "cited": check.cited,
                        "invalid": check.invalid,
                        "provider": event.provider,
                    },
                )

    async def chitchat(
        self, message: str, language: str, *, sensitive: bool
    ) -> AsyncIterator[AnswerEvent]:
        lang_name = "Hindi" if language == "hi" else "English"
        messages = [
            {"role": "system", "content": CHITCHAT_SYSTEM.format(language=lang_name)},
            {"role": "user", "content": message},
        ]
        async for event in self.stream(messages, [], sensitive=sensitive):
            yield event
