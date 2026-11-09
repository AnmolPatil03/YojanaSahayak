from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel

from yojana.config import ProviderConfig
from yojana.llm.budget import UsageTracker
from yojana.llm.cache import ResponseCache
from yojana.llm.gateway import (
    AllProvidersExhausted,
    LLMGateway,
    ProviderStarted,
    ProviderSwitched,
    StreamDone,
    TokenDelta,
    parse_duration,
    reset_seconds,
)
from yojana.llm.tokens import TokenCounter

ALPHA = "https://alpha.test/v1/chat/completions"
BETA = "https://beta.test/v1/chat/completions"
GAMMA = "https://gamma.test/v1/chat/completions"
MESSAGES = [{"role": "user", "content": "Which documents does Test Scheme Alpha need?"}]


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class HeuristicCounter(TokenCounter):
    def count(self, text: str) -> int:
        return self.heuristic(text)


def provider(name: str, **overrides: Any) -> ProviderConfig:
    data: dict[str, Any] = {
        "name": name,
        "label": name.title(),
        "base_url": f"https://{name}.test/v1",
        "api_key_env": f"{name.upper()}_KEY",
        "model": f"{name}-model",
        "max_input_tokens": 4000,
        "supports_json_mode": True,
    }
    data.update(overrides)
    return ProviderConfig.model_validate(data)


def completion(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "cmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
    )


def sse_events(pieces: list[str]) -> list[bytes]:
    events = []
    for piece in pieces:
        chunk = {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
        }
        events.append(f"data: {json.dumps(chunk)}\n\n".encode())
    return events


def stream_response(pieces: list[str]) -> httpx.Response:
    body = b"".join([*sse_events(pieces), b"data: [DONE]\n\n"])
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


class BrokenStream(httpx.AsyncByteStream):
    def __init__(self, pieces: list[str]) -> None:
        self._events = sse_events(pieces)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for event in self._events:
            yield event
        raise httpx.ReadError("connection dropped")


def broken_stream_response(pieces: list[str]) -> httpx.Response:
    return httpx.Response(
        200, stream=BrokenStream(pieces), headers={"content-type": "text/event-stream"}
    )


def rate_limited(headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(429, json={"error": {"message": "rate limited"}}, headers=headers or {})


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


def make_gateway(
    configs: list[ProviderConfig],
    clock: FakeClock,
    sleeps: Sleeps,
    *,
    cache: ResponseCache | None = None,
    secrets: dict[str, str] | None = None,
) -> LLMGateway:
    keys = secrets if secrets is not None else {f"{c.name.upper()}_KEY": "k" for c in configs}
    return LLMGateway(
        configs,
        secrets=lambda name: keys.get(name or ""),
        usage=UsageTracker(":memory:", clock=clock),
        cache=cache,
        counter=HeuristicCounter(),
        clock=clock,
        sleep=sleeps,
        rng=lambda: 0.0,
    )


@respx.mock
async def test_first_provider_answers_and_usage_is_recorded(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    alpha = respx.post(ALPHA).mock(return_value=completion("hello", 12, 3))
    beta = respx.post(BETA).mock(return_value=completion("unused"))

    result = await gw.complete(MESSAGES, task="test")

    assert result.text == "hello"
    assert result.provider == "alpha"
    assert alpha.call_count == 1
    assert beta.call_count == 0
    assert gw.usage.today("alpha").requests == 1
    assert gw.usage.today("alpha").tokens == 15


@respx.mock
async def test_429_with_retry_after_cools_down_and_fails_over(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    alpha = respx.post(ALPHA).mock(return_value=rate_limited({"retry-after": "20"}))
    respx.post(BETA).mock(return_value=completion("from beta"))

    result = await gw.complete(MESSAGES, task="test", use_cache=False)
    assert result.provider == "beta"

    status = {s["name"]: s for s in gw.status()}
    assert status["alpha"]["status"] == "cooldown"
    assert status["alpha"]["cooldown_seconds"] == pytest.approx(20.0)

    await gw.complete(MESSAGES, task="test", use_cache=False)
    assert alpha.call_count == 1

    clock.now += 21
    alpha.mock(return_value=completion("alpha is back"))
    result = await gw.complete(MESSAGES, task="test", use_cache=False)
    assert result.provider == "alpha"
    assert sleeps.calls == []


@respx.mock
async def test_429_uses_groq_style_reset_headers(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(
        return_value=rate_limited(
            {
                "x-ratelimit-remaining-requests": "100",
                "x-ratelimit-reset-requests": "2m59.56s",
                "x-ratelimit-remaining-tokens": "0",
                "x-ratelimit-reset-tokens": "7.66s",
            }
        )
    )
    respx.post(BETA).mock(return_value=completion("ok"))

    await gw.complete(MESSAGES, task="test")

    alpha = next(s for s in gw.status() if s["name"] == "alpha")
    assert alpha["cooldown_seconds"] == pytest.approx(7.66)


@respx.mock
async def test_429_without_headers_backs_off_exponentially(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=rate_limited())
    respx.post(BETA).mock(return_value=completion("ok"))

    await gw.complete(MESSAGES, task="test", use_cache=False)
    first = next(s for s in gw.status() if s["name"] == "alpha")["cooldown_seconds"]

    clock.now += first + 1
    await gw.complete(MESSAGES, task="test", use_cache=False)
    second = next(s for s in gw.status() if s["name"] == "alpha")["cooldown_seconds"]

    assert first == pytest.approx(5.0)
    assert second == pytest.approx(10.0)


@pytest.mark.parametrize("code", [401, 402, 403])
@respx.mock
async def test_auth_and_payment_errors_disable_provider_for_process(clock, sleeps, code) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    alpha = respx.post(ALPHA).mock(return_value=httpx.Response(code, json={"error": {}}))
    respx.post(BETA).mock(return_value=completion("ok"))

    assert (await gw.complete(MESSAGES, task="test", use_cache=False)).provider == "beta"
    clock.now += 10_000
    assert (await gw.complete(MESSAGES, task="test", use_cache=False)).provider == "beta"

    assert alpha.call_count == 1
    alpha_status = next(s for s in gw.status() if s["name"] == "alpha")
    assert alpha_status["status"] == "disabled"
    assert str(code) in alpha_status["detail"]


@respx.mock
async def test_timeout_is_retried_once_then_falls_through(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    alpha = respx.post(ALPHA).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.post(BETA).mock(return_value=completion("ok"))

    result = await gw.complete(MESSAGES, task="test")

    assert result.provider == "beta"
    assert alpha.call_count == 2
    assert len(sleeps.calls) == 1
    assert 0.5 <= sleeps.calls[0] <= 1.5


@respx.mock
async def test_server_error_recovers_on_retry(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(side_effect=[httpx.Response(503), completion("second try")])
    beta = respx.post(BETA).mock(return_value=completion("unused"))

    result = await gw.complete(MESSAGES, task="test")

    assert result.text == "second try"
    assert beta.call_count == 0


@respx.mock
async def test_sensitive_requests_skip_providers_that_train_on_data(clock, sleeps) -> None:
    gw = make_gateway(
        [provider("alpha", trains_on_free_tier_data=True), provider("beta")], clock, sleeps
    )
    alpha = respx.post(ALPHA).mock(return_value=completion("generic"))
    respx.post(BETA).mock(return_value=completion("private"))

    private = await gw.complete(MESSAGES, task="answer", sensitive=True, use_cache=False)
    generic = await gw.complete(MESSAGES, task="answer", sensitive=False, use_cache=False)

    assert private.provider == "beta"
    assert generic.provider == "alpha"
    assert alpha.call_count == 1


@respx.mock
async def test_sensitive_request_fails_if_only_training_providers_exist(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha", trains_on_free_tier_data=True)], clock, sleeps)
    route = respx.post(ALPHA).mock(return_value=completion("x"))

    with pytest.raises(AllProvidersExhausted) as info:
        await gw.complete(MESSAGES, task="answer", sensitive=True)

    assert route.call_count == 0
    assert "privacy" in info.value.attempts[0].reason


@respx.mock
async def test_budget_limits_skip_provider_before_calling(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha", rpm=1), provider("beta")], clock, sleeps)
    alpha = respx.post(ALPHA).mock(return_value=completion("a"))
    respx.post(BETA).mock(return_value=completion("b"))

    assert (await gw.complete(MESSAGES, task="t", use_cache=False)).provider == "alpha"
    assert (await gw.complete(MESSAGES, task="t", use_cache=False)).provider == "beta"
    assert alpha.call_count == 1

    clock.now += 61
    assert (await gw.complete(MESSAGES, task="t", use_cache=False)).provider == "alpha"


@respx.mock
async def test_daily_token_budget_and_status(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha", tpd=100), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=completion("a", prompt_tokens=60, completion_tokens=40))
    respx.post(BETA).mock(return_value=completion("b"))

    assert (
        await gw.complete(MESSAGES, task="t", max_tokens=10, use_cache=False)
    ).provider == "alpha"
    assert (
        await gw.complete(MESSAGES, task="t", max_tokens=10, use_cache=False)
    ).provider == "beta"
    alpha = next(s for s in gw.status() if s["name"] == "alpha")
    assert alpha["status"] == "budget_exhausted"
    assert alpha["usage_today"] == {"requests": 1, "tokens": 100}


@respx.mock
async def test_prompt_larger_than_max_input_tokens_is_skipped(clock, sleeps) -> None:
    gw = make_gateway(
        [provider("alpha", max_input_tokens=20), provider("beta", max_input_tokens=5000)],
        clock,
        sleeps,
    )
    alpha = respx.post(ALPHA).mock(return_value=completion("a"))
    respx.post(BETA).mock(return_value=completion("b"))
    long_prompt = [{"role": "user", "content": "word " * 200}]

    assert (await gw.complete(long_prompt, task="t")).provider == "beta"
    assert alpha.call_count == 0
    assert gw.max_input_tokens() == 5000


@respx.mock
async def test_cache_hit_avoids_network_and_can_be_bypassed(clock, sleeps) -> None:
    cache = ResponseCache(":memory:", ttl_seconds=3600, clock=clock)
    gw = make_gateway([provider("alpha")], clock, sleeps, cache=cache)
    route = respx.post(ALPHA).mock(return_value=completion("cached answer"))

    first = await gw.complete(MESSAGES, task="eval")
    second = await gw.complete(MESSAGES, task="eval")
    other_task = await gw.complete(MESSAGES, task="different")
    bypass = await gw.complete(MESSAGES, task="eval", use_cache=False)

    assert not first.cached
    assert second.cached and second.text == "cached answer" and second.provider == "alpha"
    assert not other_task.cached
    assert not bypass.cached
    assert route.call_count == 3

    clock.now += 3601
    assert not (await gw.complete(MESSAGES, task="eval")).cached


@respx.mock
async def test_all_providers_exhausted_lists_every_reason(clock, sleeps) -> None:
    gw = make_gateway(
        [provider("alpha"), provider("beta"), provider("gamma", enabled=False)],
        clock,
        sleeps,
        secrets={"ALPHA_KEY": "k"},
    )
    respx.post(ALPHA).mock(return_value=rate_limited({"retry-after": "5"}))

    with pytest.raises(AllProvidersExhausted) as info:
        await gw.complete(MESSAGES, task="t")

    reasons = {a.provider: a.reason for a in info.value.attempts}
    assert "429" in reasons["alpha"]
    assert "no API key" in reasons["beta"]
    assert "disabled in config" in reasons["gamma"]


@respx.mock
async def test_provider_without_key_requirement_needs_no_secret(clock, sleeps) -> None:
    local = provider("alpha", api_key_env=None, requires_key=False, offline=True)
    gw = make_gateway([local], clock, sleeps, secrets={})
    respx.post(ALPHA).mock(return_value=completion("offline answer"))

    assert (await gw.complete(MESSAGES, task="t")).text == "offline answer"


class Verdict(BaseModel):
    answer: str
    confidence: float


@respx.mock
async def test_json_mode_is_requested_when_supported(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha")], clock, sleeps)
    route = respx.post(ALPHA).mock(return_value=completion('{"answer": "yes", "confidence": 0.9}'))

    parsed, result = await gw.complete_json(MESSAGES, Verdict, task="t")

    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert parsed == Verdict(answer="yes", confidence=0.9)
    assert result.provider == "alpha"


@respx.mock
async def test_invalid_json_gets_one_repair_retry(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha", supports_json_mode=False)], clock, sleeps)
    route = respx.post(ALPHA).mock(
        side_effect=[
            completion("Sure! Here you go: {answer: yes}"),
            completion('```json\n{"answer": "yes", "confidence": 0.5}\n```'),
        ]
    )

    parsed, _ = await gw.complete_json(MESSAGES, Verdict, task="t")

    assert parsed.confidence == 0.5
    assert route.call_count == 2
    first_body = json.loads(route.calls[0].request.content)
    assert "response_format" not in first_body
    repair_body = json.loads(route.calls[1].request.content)
    assert "did not match the required schema" in repair_body["messages"][-1]["content"]


@respx.mock
async def test_invalid_json_after_repair_falls_through(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    alpha = respx.post(ALPHA).mock(return_value=completion("not json at all"))
    respx.post(BETA).mock(return_value=completion('{"answer": "b", "confidence": 1}'))

    parsed, result = await gw.complete_json(MESSAGES, Verdict, task="t")

    assert alpha.call_count == 2
    assert result.provider == "beta"
    assert parsed.answer == "b"


async def collect(gw: LLMGateway, **kwargs: Any) -> list[Any]:
    return [event async for event in gw.stream(MESSAGES, task="answer", **kwargs)]


@respx.mock
async def test_stream_success_emits_provider_tokens_and_done(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=stream_response(["Hel", "lo"]))

    events = await collect(gw)

    assert isinstance(events[0], ProviderStarted) and events[0].provider == "alpha"
    assert [e.text for e in events if isinstance(e, TokenDelta)] == ["Hel", "lo"]
    assert isinstance(events[-1], StreamDone) and events[-1].text == "Hello"


@respx.mock
async def test_stream_failure_before_first_token_switches_silently(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=rate_limited({"retry-after": "30"}))
    respx.post(BETA).mock(return_value=stream_response(["from ", "beta"]))

    events = await collect(gw)

    assert not any(isinstance(e, ProviderSwitched) for e in events)
    started = [e for e in events if isinstance(e, ProviderStarted)]
    assert [s.provider for s in started] == ["beta"]
    assert events[-1].text == "from beta"


@respx.mock
async def test_stream_failure_mid_stream_emits_provider_switch(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=broken_stream_response(["partial ", "answ"]))
    respx.post(BETA).mock(return_value=stream_response(["full ", "answer"]))

    events = await collect(gw)
    kinds = [type(e).__name__ for e in events]

    assert kinds == [
        "ProviderStarted",
        "TokenDelta",
        "TokenDelta",
        "ProviderSwitched",
        "ProviderStarted",
        "TokenDelta",
        "TokenDelta",
        "StreamDone",
    ]
    switch = next(e for e in events if isinstance(e, ProviderSwitched))
    assert (switch.from_provider, switch.to_provider) == ("alpha", "beta")
    assert "mid-stream" in switch.reason
    assert events[-1].text == "full answer"


@respx.mock
async def test_stream_uses_cache(clock, sleeps) -> None:
    cache = ResponseCache(":memory:", ttl_seconds=60, clock=clock)
    gw = make_gateway([provider("alpha")], clock, sleeps, cache=cache)
    route = respx.post(ALPHA).mock(return_value=stream_response(["a", "b"]))

    await collect(gw)
    events = await collect(gw)

    assert route.call_count == 1
    assert isinstance(events[0], ProviderStarted) and events[0].cached
    assert events[-1].text == "ab"


@respx.mock
async def test_stream_raises_when_everything_fails(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=httpx.Response(402, json={}))

    with pytest.raises(AllProvidersExhausted):
        await collect(gw)


@respx.mock
async def test_exclude_skips_named_provider(clock, sleeps) -> None:
    gw = make_gateway([provider("alpha"), provider("beta")], clock, sleeps)
    respx.post(ALPHA).mock(return_value=completion("a"))
    respx.post(BETA).mock(return_value=completion("judge"))

    result = await gw.complete(MESSAGES, task="judge", exclude=["alpha"])
    assert result.provider == "beta"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7.66s", 7.66), ("2m59.56s", 179.56), ("1h2m", 3720.0), ("250ms", 0.25), ("12", 12.0)],
)
def test_parse_duration(raw: str, expected: float) -> None:
    assert parse_duration(raw) == pytest.approx(expected)


def test_reset_seconds_handles_epoch_and_http_dates() -> None:
    now = 1_700_000_000.0
    assert reset_seconds({"X-RateLimit-Reset": str(int((now + 42) * 1000))}, now) == pytest.approx(
        42.0
    )
    assert reset_seconds({"Retry-After": "Tue, 14 Nov 2023 22:13:27 GMT"}, now) == pytest.approx(
        7.0
    )
    assert reset_seconds({}, now) is None
