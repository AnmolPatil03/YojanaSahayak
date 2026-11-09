"""The per-turn state machine, streamed to the client as events.

understanding -> searching -> fusing -> reranking -> checking_eligibility -> writing
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from yojana.agent.eligibility import SchemeEligibility, evaluate, rank
from yojana.agent.questions import ClarifyQuestion, select_question
from yojana.agent.router import Understanding, understand
from yojana.agent.slots import UserProfile
from yojana.generate.answer import (
    AnswerGenerator,
    citation_payload,
    extractive_answer,
)
from yojana.ingest.models import Chunk
from yojana.ingest.registry import SchemeRegistry
from yojana.llm.gateway import AllProvidersExhausted, LLMGateway
from yojana.retrieve.filters import build_filters
from yojana.retrieve.hybrid import HybridRetriever, RetrievalResult
from yojana.rules import RulesStore

logger = logging.getLogger(__name__)

Event = dict[str, Any]

_NOT_FOUND = {
    "en": (
        "I couldn't find this in the scheme documents I have. Try naming the scheme, "
        "or ask about scholarships, farmer support, startup support, or schemes for "
        "women, students or persons with disabilities."
    ),
    "hi": (
        "मुझे यह जानकारी मेरे पास मौजूद योजना दस्तावेज़ों में नहीं मिली। योजना का नाम लिखकर देखें, "
        "या छात्रवृत्ति, किसान सहायता, स्टार्टअप सहायता, महिलाओं, छात्रों या दिव्यांगजनों की "
        "योजनाओं के बारे में पूछें।"
    ),
}
_OUT_OF_SCOPE = {
    "en": (
        "I can only help with Indian government welfare schemes: finding schemes, "
        "checking eligibility and listing the documents you need."
    ),
    "hi": (
        "मैं केवल भारत सरकार की कल्याण योजनाओं में मदद कर सकता हूँ: योजनाएँ ढूँढना, पात्रता जाँचना "
        "और ज़रूरी दस्तावेज़ बताना।"
    ),
}
_GREETING = {
    "en": (
        "Hello! I can help you find government schemes, check whether you are eligible, "
        "and list the documents you need. What are you looking for?"
    ),
    "hi": (
        "नमस्ते! मैं सरकारी योजनाएँ ढूँढने, आपकी पात्रता जाँचने और ज़रूरी दस्तावेज़ बताने में "
        "मदद कर सकता हूँ। आप क्या ढूँढ रहे हैं?"
    ),
}
_NEED_DETAIL = {
    "en": "To check your eligibility I need one more detail. {question}",
    "hi": "आपकी पात्रता जाँचने के लिए मुझे एक और जानकारी चाहिए। {question}",
}
_EXHAUSTED = {
    "en": "All language model providers are busy or unavailable right now.",
    "hi": "अभी सभी भाषा मॉडल प्रदाता व्यस्त या अनुपलब्ध हैं।",
}


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    """Body of `POST /api/chat`."""

    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    profile: UserProfile = Field(default_factory=UserProfile)
    language: str | None = None
    asked_fields: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class TurnContext:
    request: ChatRequest
    understanding: Understanding | None = None
    profile: UserProfile | None = None
    retrieval: RetrievalResult | None = None


def _event(kind: str, **data: Any) -> Event:
    return {"event": kind, "data": data}


class Orchestrator:
    """Runs one chat turn and yields SSE-ready events."""

    def __init__(
        self,
        *,
        gateway: LLMGateway,
        retriever: Callable[[], HybridRetriever],
        registry: Callable[[], SchemeRegistry],
        rules: RulesStore,
        allow_unreviewed: bool = False,
        history_turns: int = 6,
        use_llm_understanding: bool = True,
    ) -> None:
        self.gateway = gateway
        self._retriever = retriever
        self._registry = registry
        self.rules = rules
        self.allow_unreviewed = allow_unreviewed
        self.history_turns = history_turns
        self.use_llm_understanding = use_llm_understanding
        self.answers = AnswerGenerator(gateway, getattr(gateway, "counter", None))
        self._retrieval_lock = threading.Lock()

    def eligibility_for(
        self, scheme_ids: Sequence[str], profile: UserProfile
    ) -> tuple[list[SchemeEligibility], list[str]]:
        """Engine verdicts for schemes with usable rules, plus ids awaiting review."""
        results: list[SchemeEligibility] = []
        pending: list[str] = []
        for scheme_id in dict.fromkeys(scheme_ids):
            record = self.rules.usable(scheme_id, allow_unreviewed=self.allow_unreviewed)
            if record is None:
                if self.rules.get(scheme_id) is not None:
                    pending.append(scheme_id)
                continue
            results.append(evaluate(record, profile))
        return rank(results), pending

    async def _retrieve(
        self, query: str, filters: Any, queue: asyncio.Queue[Event]
    ) -> RetrievalResult:
        loop = asyncio.get_running_loop()
        retriever = self._retriever()

        def on_stage(name: str, status: str, ms: float) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait, _event("stage", stage=name, status=status, ms=round(ms, 1))
            )

        def work() -> RetrievalResult:
            with self._retrieval_lock:
                return retriever.retrieve(query, filters, on_stage=on_stage)

        return await asyncio.to_thread(work)

    async def run(self, request: ChatRequest) -> AsyncIterator[Event]:
        """Process one message. Yields `stage`, `token`, `citations`, `eligibility`,
        `clarify`, `provider`, `provider_switch`, `error` and finally `done` events."""
        started = time.perf_counter()
        registry = self._registry()
        history = [t.model_dump() for t in request.history]

        yield _event("stage", stage="understanding", status="start", ms=0.0)
        t0 = time.perf_counter()
        mentions = registry.find_mentions(request.message)
        info = await understand(
            self.gateway,
            request.message,
            history=history,
            scheme_mentions=mentions,
            preferred_language=request.language,
            history_turns=self.history_turns,
            use_llm=self.use_llm_understanding,
        )
        if not mentions:
            info.scheme_mentions = registry.find_mentions(info.standalone_query)
        profile = request.profile.merged(info.profile_updates)
        updates = {k: v for k, v in info.profile_updates.model_dump().items() if v is not None}
        sensitive = not profile.is_empty()
        language = info.language
        yield _event(
            "stage",
            stage="understanding",
            status="end",
            ms=round((time.perf_counter() - t0) * 1000, 1),
            intent=info.intent,
            language=language,
            query=info.standalone_query,
            profile_updates=updates,
            schemes=info.scheme_mentions,
        )

        done_extra: dict[str, Any] = {"intent": info.intent, "language": language}

        if info.intent in ("chitchat", "out_of_scope"):
            async for event in self._small_talk(request.message, info, sensitive):
                yield event
            yield self._done(started, done_extra)
            return

        retriever = self._retriever()
        if not retriever.ready:
            yield _event("stage", stage="writing", status="start", ms=0.0)
            yield _event("token", text=_NOT_FOUND[language])
            yield _event("stage", stage="writing", status="end", ms=0.0)
            yield self._done(started, {**done_extra, "abstained": True, "empty_index": True})
            return

        sections = ["documents"] if info.intent == "documents" else None
        pinned = info.scheme_mentions if info.intent in ("explain", "documents", "compare") else []
        filters = build_filters(
            info.standalone_query,
            profile_state=profile.state,
            scheme_ids=pinned or None,
            sections=sections if pinned else None,
        )
        queue: asyncio.Queue[Event] = asyncio.Queue()
        task = asyncio.create_task(self._retrieve(info.standalone_query, filters, queue))
        while not task.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.05)
            except TimeoutError:
                continue
        retrieval = task.result()
        sources = [] if retrieval.abstained else [c.chunk for c in retrieval.chunks]

        verdicts: list[SchemeEligibility] = []
        question: ClarifyQuestion | None = None
        wants_engine = info.intent in ("eligibility_check", "discover", "compare") or (
            info.intent == "explain" and not profile.is_empty()
        )
        if wants_engine:
            yield _event("stage", stage="checking_eligibility", status="start", ms=0.0)
            t1 = time.perf_counter()
            candidates = list(info.scheme_mentions)
            candidates += [c.scheme_id for c in sources]
            if info.intent == "eligibility_check" and not candidates:
                candidates = [r.scheme_id for r in registry.all()]
            verdicts, pending = self.eligibility_for(candidates, profile)
            question = select_question(verdicts, asked=request.asked_fields)
            yield _event(
                "eligibility",
                results=[v.model_dump() for v in verdicts],
                pending_review=pending,
            )
            if question is not None:
                yield _event("clarify", **question.model_dump())
            yield _event(
                "stage",
                stage="checking_eligibility",
                status="end",
                ms=round((time.perf_counter() - t1) * 1000, 1),
            )

        yield _event("stage", stage="writing", status="start", ms=0.0)
        t2 = time.perf_counter()
        needs_detail = (
            info.intent == "eligibility_check"
            and question is not None
            and verdicts
            and all(v.verdict == "partial" for v in verdicts)
        )
        if needs_detail and question is not None:
            text = question.question_hi if language == "hi" else question.question
            yield _event("token", text=_NEED_DETAIL[language].format(question=text))
            yield _event("citations", sources=citation_payload(sources, []))
        elif retrieval.abstained and not verdicts:
            yield _event("token", text=_NOT_FOUND[language])
            done_extra["abstained"] = True
        else:
            async for event in self._generate(
                info, request, history, sources, verdicts, question, sensitive, language, done_extra
            ):
                yield event
        yield _event(
            "stage", stage="writing", status="end", ms=round((time.perf_counter() - t2) * 1000, 1)
        )
        done_extra["retrieval"] = {
            "top_score": retrieval.top_score,
            "abstained": retrieval.abstained,
            "filters": retrieval.filters.as_dict(),
            "timings": retrieval.timings,
        }
        yield self._done(started, done_extra)

    async def _generate(
        self,
        info: Understanding,
        request: ChatRequest,
        history: list[dict[str, Any]],
        sources: list[Chunk],
        verdicts: list[SchemeEligibility],
        question: ClarifyQuestion | None,
        sensitive: bool,
        language: str,
        outcome: dict[str, Any],
    ) -> AsyncIterator[Event]:
        engine_results = verdicts[:5]
        messages, kept = self.answers.prepare(
            question=request.message,
            language=language,
            intent=info.intent,
            sources=sources,
            engine_results=engine_results,
            history=history[-self.history_turns :],
            missing_question=(question.question if question else None),
            sensitive=sensitive,
        )
        try:
            async for event in self.answers.stream(messages, kept, sensitive=sensitive):
                if event.kind == "final":
                    outcome["provider"] = event.data["provider"]
                    outcome["invalid_citations"] = event.data["invalid"]
                    yield _event("citations", sources=citation_payload(kept, event.data["cited"]))
                else:
                    yield _event(event.kind, **event.data)
        except AllProvidersExhausted as exc:
            logger.warning("Generation failed: %s", exc)
            yield _event(
                "error",
                code="all_providers_exhausted",
                message=_EXHAUSTED[language],
                attempts=[{"provider": a.provider, "reason": a.reason} for a in exc.attempts],
            )
            fallback = extractive_answer(kept, language)
            yield _event("token", text=fallback)
            yield _event(
                "citations", sources=citation_payload(kept, list(range(1, min(len(kept), 3) + 1)))
            )
            outcome["degraded"] = True

    async def _small_talk(
        self, message: str, info: Understanding, sensitive: bool
    ) -> AsyncIterator[Event]:
        yield _event("stage", stage="writing", status="start", ms=0.0)
        if info.intent == "out_of_scope":
            yield _event("token", text=_OUT_OF_SCOPE[info.language])
        else:
            produced = False
            try:
                async for event in self.answers.chitchat(
                    message, info.language, sensitive=sensitive
                ):
                    if event.kind in ("provider", "provider_switch", "token"):
                        produced = produced or event.kind == "token"
                        yield _event(event.kind, **event.data)
            except AllProvidersExhausted:
                if not produced:
                    yield _event("token", text=_GREETING[info.language])
        yield _event("stage", stage="writing", status="end", ms=0.0)

    @staticmethod
    def _done(started: float, extra: dict[str, Any]) -> Event:
        return _event("done", total_ms=round((time.perf_counter() - started) * 1000, 1), **extra)
