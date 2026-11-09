"""Single entry point for every LLM call, with ordered failover across providers."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx
import openai
from pydantic import BaseModel, ValidationError

from yojana.config import ProviderConfig, Settings
from yojana.llm.budget import UsageTracker
from yojana.llm.cache import ResponseCache, cache_key
from yojana.llm.providers import Message, Provider
from yojana.llm.tokens import TokenCounter

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_TRANSIENT_COOLDOWN_S = 30.0
_MAX_BACKOFF_S = 300.0
_BASE_BACKOFF_S = 5.0


@dataclass(slots=True)
class Attempt:
    provider: str
    reason: str


class AllProvidersExhausted(RuntimeError):
    """Raised when no configured provider could serve a request."""

    def __init__(self, attempts: list[Attempt]) -> None:
        self.attempts = attempts
        summary = "; ".join(f"{a.provider}: {a.reason}" for a in attempts) or "none configured"
        super().__init__(f"All LLM providers are unavailable ({summary})")


class StructuredOutputError(ValueError):
    """Raised internally when a response does not match the requested schema."""


@dataclass(slots=True)
class LLMResult:
    text: str
    provider: str
    model: str
    cached: bool = False
    parsed: BaseModel | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class ProviderStarted:
    provider: str
    label: str
    model: str
    offline: bool
    cached: bool = False


@dataclass(slots=True)
class ProviderSwitched:
    from_provider: str
    to_provider: str
    to_label: str
    reason: str


@dataclass(slots=True)
class TokenDelta:
    text: str


@dataclass(slots=True)
class StreamDone:
    provider: str
    text: str
    cached: bool = False


StreamEvent = ProviderStarted | ProviderSwitched | TokenDelta | StreamDone


@dataclass(slots=True)
class _ProviderState:
    cooldown_until: float = 0.0
    consecutive_429: int = 0
    disabled_reason: str | None = None
    last_error: str | None = None


class _RetryableError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_duration(value: str) -> float | None:
    """Parse reset values such as `7.66s`, `2m59.56s`, `1h2m`, `250ms` or `12`."""
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    parts = _DURATION_PART.findall(value)
    if not parts:
        return None
    scale = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    return sum(float(num) * scale[unit] for num, unit in parts)


def reset_seconds(headers: Mapping[str, str], now: float) -> float | None:
    """Seconds until a rate limit resets, from whichever headers the provider sent."""
    lower = {k.lower(): v for k, v in headers.items()}
    retry_after = lower.get("retry-after")
    if retry_after:
        seconds = parse_duration(retry_after)
        if seconds is None:
            try:
                seconds = parsedate_to_datetime(retry_after).timestamp() - now
            except (TypeError, ValueError):
                seconds = None
        if seconds is not None:
            return max(seconds, 0.0)

    exhausted: list[float] = []
    present: list[float] = []
    for kind in ("requests", "tokens"):
        raw = lower.get(f"x-ratelimit-reset-{kind}")
        seconds = parse_duration(raw) if raw else None
        if seconds is None:
            continue
        present.append(seconds)
        remaining = lower.get(f"x-ratelimit-remaining-{kind}")
        try:
            if remaining is None or float(remaining) <= 0:
                exhausted.append(seconds)
        except ValueError:
            exhausted.append(seconds)
    if exhausted:
        return max(exhausted)
    if present:
        return min(present)

    generic = lower.get("x-ratelimit-reset")
    if generic:
        try:
            number = float(generic)
        except ValueError:
            return parse_duration(generic)
        # OpenRouter sends an epoch timestamp in milliseconds; others send seconds.
        if number > 1e12:
            return max(number / 1000.0 - now, 0.0)
        if number > 1e9:
            return max(number - now, 0.0)
        return max(number, 0.0)
    return None


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may be fenced or padded with prose."""
    stripped = _FENCE.sub("", text.strip()).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        raise StructuredOutputError("no JSON object found in response")
    return stripped[start : end + 1]


def parse_structured(text: str, schema: type[T]) -> T:
    try:
        return schema.model_validate_json(extract_json(text))
    except ValidationError as exc:
        raise StructuredOutputError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"invalid JSON: {exc}") from exc


def _schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "Respond with one JSON object and nothing else. It must validate against this "
        f"JSON Schema:\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )


class LLMGateway:
    """Routes LLM calls across providers with budgeting, cooldowns, privacy and caching.

    Providers are tried in configured order. A provider is skipped up front when it
    is disabled, cooling down after a 429, out of budget, too small for the prompt,
    or (for requests carrying a user's eligibility profile) flagged as training on
    free-tier data.
    """

    def __init__(
        self,
        providers: Sequence[ProviderConfig],
        *,
        secrets: Callable[[str | None], str | None],
        usage: UsageTracker,
        cache: ResponseCache | None = None,
        counter: TokenCounter | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._configs = list(providers)
        self._providers = [
            Provider(cfg, secrets(cfg.api_key_env), http_client) for cfg in providers
        ]
        self._state = {cfg.name: _ProviderState() for cfg in providers}
        self.usage = usage
        self.cache = cache
        self.counter = counter or TokenCounter()
        self._clock = clock
        self._sleep = sleep
        self._rng = rng

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMGateway:
        """Build a gateway from `providers.yaml` and the SQLite files in `data/cache`."""
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        cache = (
            ResponseCache(
                settings.cache_dir / "llm_cache.sqlite3", settings.llm_cache_ttl_hours * 3600
            )
            if settings.llm_cache_enabled
            else None
        )
        return cls(
            settings.providers(),
            secrets=settings.secret,
            usage=UsageTracker(settings.cache_dir / "usage.sqlite3"),
            cache=cache,
            counter=TokenCounter(cache_dir=settings.cache_dir / "tiktoken"),
        )

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    def label(self, name: str) -> str:
        for provider in self._providers:
            if provider.name == name:
                return provider.cfg.display_name
        return name

    def _skip_reason(
        self,
        provider: Provider,
        estimated_tokens: int,
        prompt_tokens: int,
        sensitive: bool,
        exclude: set[str],
    ) -> str | None:
        cfg = provider.cfg
        state = self._state[cfg.name]
        if cfg.name in exclude:
            return "excluded for this request"
        if not cfg.enabled:
            return "disabled in config"
        if state.disabled_reason:
            return f"disabled: {state.disabled_reason}"
        if not provider.has_credentials:
            return f"no API key ({cfg.api_key_env} not set)"
        if sensitive and cfg.trains_on_free_tier_data:
            return "skipped for privacy: provider may train on free-tier data"
        now = self._clock()
        if state.cooldown_until > now:
            return f"cooling down for {state.cooldown_until - now:.0f}s"
        if prompt_tokens > cfg.max_input_tokens:
            return (
                f"prompt of ~{prompt_tokens} tokens exceeds max_input_tokens {cfg.max_input_tokens}"
            )
        return self.usage.check(cfg, estimated_tokens)

    def _candidates(
        self,
        messages: Sequence[Message],
        max_tokens: int,
        sensitive: bool,
        exclude: set[str],
        attempts: list[Attempt],
    ) -> Iterator[tuple[Provider, int]]:
        prompt_tokens = self.counter.count_messages(messages)
        for provider in self._providers:
            estimated = prompt_tokens + min(max_tokens, provider.cfg.max_output_tokens)
            reason = self._skip_reason(provider, estimated, prompt_tokens, sensitive, exclude)
            if reason:
                attempts.append(Attempt(provider.name, reason))
                continue
            yield provider, prompt_tokens

    def max_input_tokens(self, *, sensitive: bool = False) -> int:
        """Largest prompt any currently usable provider would accept."""
        best = 0
        for provider in self._providers:
            reason = self._skip_reason(provider, 1, 1, sensitive, set())
            if reason is None:
                best = max(best, provider.cfg.max_input_tokens)
        return best

    def _on_success(self, provider: Provider) -> None:
        state = self._state[provider.name]
        state.consecutive_429 = 0
        state.last_error = None

    def _classify(self, provider: Provider, exc: BaseException) -> tuple[str, bool]:
        """Update provider state for an error. Returns (reason, retry_same_provider)."""
        state = self._state[provider.name]
        now = self._clock()
        if isinstance(exc, openai.RateLimitError):
            wait = reset_seconds(exc.response.headers, now)
            if wait is None:
                wait = min(_BASE_BACKOFF_S * (2**state.consecutive_429), _MAX_BACKOFF_S)
                wait *= 1.0 + 0.25 * self._rng()
            state.consecutive_429 += 1
            state.cooldown_until = now + wait
            reason = f"rate limited (429), cooling down {wait:.1f}s"
            state.last_error = reason
            return reason, False
        if isinstance(exc, openai.APIStatusError) and exc.status_code in (401, 402, 403):
            label = {401: "unauthorized", 402: "payment required", 403: "forbidden"}[
                exc.status_code
            ]
            state.disabled_reason = f"HTTP {exc.status_code} {label}"
            logger.warning(
                "Disabling provider %s for this process: HTTP %s %s. Check %s.",
                provider.name,
                exc.status_code,
                label,
                provider.cfg.api_key_env or "the provider configuration",
            )
            return state.disabled_reason, False
        if isinstance(exc, openai.APITimeoutError):
            state.last_error = "timeout"
            return "timeout", True
        if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
            state.last_error = f"HTTP {exc.status_code}"
            return f"server error {exc.status_code}", True
        if isinstance(exc, openai.APIConnectionError | httpx.TransportError):
            state.last_error = "connection error"
            return "connection error", True
        if isinstance(exc, openai.APIStatusError):
            state.last_error = f"HTTP {exc.status_code}"
            return f"HTTP {exc.status_code}", False
        state.last_error = type(exc).__name__
        return f"unexpected error: {type(exc).__name__}", False

    def _transient_cooldown(self, provider: Provider) -> None:
        state = self._state[provider.name]
        state.cooldown_until = max(state.cooldown_until, self._clock() + _TRANSIENT_COOLDOWN_S)

    async def _jitter(self) -> None:
        await self._sleep(0.5 + self._rng())

    def _cache_lookup(self, key: str | None) -> dict[str, Any] | None:
        if key is None or self.cache is None:
            return None
        return self.cache.get(key)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        sensitive: bool = False,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        use_cache: bool = True,
        exclude: Sequence[str] = (),
    ) -> LLMResult:
        """Run a non-streaming completion, failing over until one provider succeeds.

        Args:
            messages: Chat messages in OpenAI format.
            task: Task label; part of the cache key and logged for usage analysis.
            sensitive: True when the prompt contains the user's eligibility profile.
            schema: Optional Pydantic model the reply must validate against.
            temperature: Sampling temperature.
            max_tokens: Upper bound on completion tokens.
            use_cache: Read and write the response cache.
            exclude: Provider names to leave out (for example an LLM judge).

        Raises:
            AllProvidersExhausted: When every provider was skipped or failed.
        """
        messages = list(messages)
        if schema is not None:
            messages = [{"role": "system", "content": _schema_instruction(schema)}, *messages]
        params = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "schema": schema.__name__ if schema else None,
        }
        key = cache_key(messages, params, task) if use_cache and self.cache else None
        hit = self._cache_lookup(key)
        if hit is not None:
            try:
                parsed = parse_structured(hit["text"], schema) if schema else None
                return LLMResult(
                    text=hit["text"],
                    provider=hit["provider"],
                    model=hit.get("model", ""),
                    cached=True,
                    parsed=parsed,
                )
            except StructuredOutputError:
                pass

        attempts: list[Attempt] = []
        excluded = set(exclude)
        for provider, prompt_tokens in self._candidates(
            messages, max_tokens, sensitive, excluded, attempts
        ):
            try:
                result = await self._complete_on(
                    provider, messages, prompt_tokens, schema, temperature, max_tokens
                )
            except _RetryableError as exc:
                attempts.append(Attempt(provider.name, exc.reason))
                continue
            if key is not None and self.cache is not None:
                self.cache.set(
                    key, {"text": result.text, "provider": result.provider, "model": result.model}
                )
            logger.info("llm task=%s provider=%s", task, provider.name)
            return result
        raise AllProvidersExhausted(attempts)

    async def _call_with_retry(
        self,
        provider: Provider,
        messages: Sequence[Message],
        prompt_tokens: int,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> tuple[str, int, int]:
        for attempt in range(2):
            row = self.usage.record(provider.name, prompt_tokens)
            try:
                completion = await provider.complete(
                    messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
                )
            except Exception as exc:
                reason, retry = self._classify(provider, exc)
                if retry and attempt == 0:
                    await self._jitter()
                    continue
                if retry:
                    self._transient_cooldown(provider)
                raise _RetryableError(reason) from exc
            p_tokens = completion.prompt_tokens or prompt_tokens
            c_tokens = completion.completion_tokens or self.counter.count(completion.text)
            self.usage.update_tokens(row, p_tokens + c_tokens)
            if not completion.text.strip():
                raise _RetryableError("empty response")
            self._on_success(provider)
            return completion.text, p_tokens, c_tokens
        raise _RetryableError("retry budget spent")

    async def _complete_on(
        self,
        provider: Provider,
        messages: list[Message],
        prompt_tokens: int,
        schema: type[BaseModel] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        text, p_tokens, c_tokens = await self._call_with_retry(
            provider, messages, prompt_tokens, temperature, max_tokens, schema is not None
        )
        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = parse_structured(text, schema)
            except StructuredOutputError as first_error:
                repair = [
                    *messages,
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            "That reply did not match the required schema "
                            f"({str(first_error)[:500]}). Return only the corrected JSON object."
                        ),
                    },
                ]
                repair_tokens = self.counter.count_messages(repair)
                text, p2, c2 = await self._call_with_retry(
                    provider, repair, repair_tokens, temperature, max_tokens, True
                )
                p_tokens, c_tokens = p_tokens + p2, c_tokens + c2
                try:
                    parsed = parse_structured(text, schema)
                except StructuredOutputError as exc:
                    raise _RetryableError("invalid structured output after repair") from exc
        return LLMResult(
            text=text,
            provider=provider.name,
            model=provider.cfg.model,
            parsed=parsed,
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
        )

    async def complete_json(
        self,
        messages: Sequence[Message],
        schema: type[T],
        *,
        task: str,
        sensitive: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 800,
        use_cache: bool = True,
        exclude: Sequence[str] = (),
    ) -> tuple[T, LLMResult]:
        """Like `complete`, but returns the reply parsed into `schema`."""
        result = await self.complete(
            messages,
            task=task,
            sensitive=sensitive,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=use_cache,
            exclude=exclude,
        )
        if not isinstance(result.parsed, schema):
            raise TypeError(f"expected {schema.__name__}, got {type(result.parsed).__name__}")
        return result.parsed, result

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        sensitive: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
        use_cache: bool = True,
        exclude: Sequence[str] = (),
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion as events, failing over between providers.

        A provider that fails before its first token is replaced silently. One that
        fails after streaming has begun is replaced too, and a `ProviderSwitched`
        event tells the caller to discard the partial text it already received.

        Raises:
            AllProvidersExhausted: When every provider was skipped or failed.
        """
        messages = list(messages)
        params = {"temperature": temperature, "max_tokens": max_tokens, "stream": True}
        key = cache_key(messages, params, task) if use_cache and self.cache else None
        hit = self._cache_lookup(key)
        if hit is not None:
            yield ProviderStarted(
                hit["provider"],
                self.label(hit["provider"]),
                hit.get("model", ""),
                offline=self._is_offline(hit["provider"]),
                cached=True,
            )
            yield TokenDelta(hit["text"])
            yield StreamDone(hit["provider"], hit["text"], cached=True)
            return

        attempts: list[Attempt] = []
        switched_from: tuple[str, str] | None = None
        for provider, prompt_tokens in self._candidates(
            messages, max_tokens, sensitive, set(exclude), attempts
        ):
            pieces: list[str] = []
            started = False
            for attempt in range(2):
                row = self.usage.record(provider.name, prompt_tokens)
                try:
                    async for delta in provider.stream(
                        messages, temperature=temperature, max_tokens=max_tokens
                    ):
                        if not started:
                            started = True
                            if switched_from is not None:
                                yield ProviderSwitched(
                                    switched_from[0],
                                    provider.name,
                                    provider.cfg.display_name,
                                    switched_from[1],
                                )
                                switched_from = None
                            yield ProviderStarted(
                                provider.name,
                                provider.cfg.display_name,
                                provider.cfg.model,
                                offline=provider.cfg.offline,
                            )
                        pieces.append(delta)
                        yield TokenDelta(delta)
                except Exception as exc:
                    reason, retry = self._classify(provider, exc)
                    self.usage.update_tokens(
                        row, prompt_tokens + self.counter.count("".join(pieces))
                    )
                    if retry and not started and attempt == 0:
                        await self._jitter()
                        continue
                    if retry:
                        self._transient_cooldown(provider)
                    if started:
                        reason = f"failed mid-stream: {reason}"
                        switched_from = (provider.name, reason)
                    attempts.append(Attempt(provider.name, reason))
                    break
                text = "".join(pieces)
                self.usage.update_tokens(row, prompt_tokens + self.counter.count(text))
                if not text.strip():
                    attempts.append(Attempt(provider.name, "empty response"))
                    break
                self._on_success(provider)
                if key is not None and self.cache is not None:
                    self.cache.set(
                        key, {"text": text, "provider": provider.name, "model": provider.cfg.model}
                    )
                logger.info("llm stream task=%s provider=%s", task, provider.name)
                yield StreamDone(provider.name, text)
                return
        raise AllProvidersExhausted(attempts)

    def _is_offline(self, name: str) -> bool:
        return any(p.cfg.offline for p in self._providers if p.name == name)

    def status(self) -> list[dict[str, Any]]:
        """Per-provider health and today's usage, for the health endpoint."""
        now = self._clock()
        report: list[dict[str, Any]] = []
        for provider in self._providers:
            cfg = provider.cfg
            state = self._state[cfg.name]
            today = self.usage.today(cfg.name)
            minute = self.usage.minute(cfg.name)
            cooldown_until: str | None = None
            if not cfg.enabled:
                status, detail = "disabled", "disabled in config"
            elif state.disabled_reason:
                status, detail = "disabled", state.disabled_reason
            elif not provider.has_credentials:
                status, detail = "disabled", f"{cfg.api_key_env} not set"
            elif state.cooldown_until > now:
                status = "cooldown"
                cooldown_until = datetime.fromtimestamp(state.cooldown_until, tz=UTC).isoformat()
                detail = f"cooling down until {cooldown_until}"
            elif self.usage.daily_exhausted(cfg):
                status, detail = "budget_exhausted", "daily limit reached"
            elif self.usage.check(cfg, 1) is not None:
                status, detail = "budget_exhausted", self.usage.check(cfg, 1) or ""
            else:
                status = "ok"
                detail = f"last error: {state.last_error}" if state.last_error else ""
            report.append(
                {
                    "name": cfg.name,
                    "label": cfg.display_name,
                    "model": cfg.model,
                    "status": status,
                    "detail": detail,
                    "cooldown_until": cooldown_until,
                    "cooldown_seconds": max(state.cooldown_until - now, 0.0)
                    if status == "cooldown"
                    else 0.0,
                    "offline": cfg.offline,
                    "trains_on_free_tier_data": cfg.trains_on_free_tier_data,
                    "limits": {"rpm": cfg.rpm, "rpd": cfg.rpd, "tpm": cfg.tpm, "tpd": cfg.tpd},
                    "usage_today": today.model_dump(),
                    "usage_last_minute": minute.model_dump(),
                }
            )
        return report

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()
