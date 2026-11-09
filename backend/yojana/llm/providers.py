"""Thin async wrapper around one OpenAI-compatible provider endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI

from yojana.config import ProviderConfig

Message = dict[str, Any]


@dataclass(slots=True)
class Completion:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Provider:
    """A configured provider. Only the gateway talks to these."""

    def __init__(
        self,
        cfg: ProviderConfig,
        api_key: str | None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cfg = cfg
        self.api_key = api_key
        # The SDK refuses an empty key; local servers such as Ollama ignore it.
        self._client = AsyncOpenAI(
            base_url=cfg.base_url,
            api_key=api_key or "unused",
            timeout=cfg.timeout_s,
            max_retries=0,
            default_headers=cfg.extra_headers or None,
            http_client=http_client,
        )

    @property
    def name(self) -> str:
        return self.cfg.name

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key) or not self.cfg.requires_key

    def _params(self, temperature: float, max_tokens: int, json_mode: bool) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.cfg.model,
            "temperature": temperature,
            "max_tokens": min(max_tokens, self.cfg.max_output_tokens),
        }
        if json_mode and self.cfg.supports_json_mode:
            params["response_format"] = {"type": "json_object"}
        return params

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Completion:
        response = await self._client.chat.completions.create(
            messages=list(messages),  # type: ignore[arg-type]
            **self._params(temperature, max_tokens, json_mode),
        )
        choice = response.choices[0] if response.choices else None
        text = (choice.message.content if choice and choice.message else None) or ""
        usage = response.usage
        return Completion(
            text=text,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            messages=list(messages),  # type: ignore[arg-type]
            stream=True,
            **self._params(temperature, max_tokens, json_mode=False),
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is not None and delta.content:
                yield delta.content

    async def aclose(self) -> None:
        await self._client.close()
