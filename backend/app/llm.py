"""OpenRouter broker.

One provider, one model per advisor, streaming by default. The client owns
retries and timeouts so the route handler only ever deals with
`Completion` or `ProviderError`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from app.config import Settings

logger = logging.getLogger("advisor.llm")

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class ProviderError(RuntimeError):
    def __init__(self, detail: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.retryable = retryable


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None
    latency_ms: int
    usage_reported: bool = False


@dataclass
class StreamResult:
    """Accumulated state of a streamed completion."""

    text: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None
    usage_reported: bool = False
    chunks: int = 0
    _started: float = field(default_factory=time.perf_counter)

    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    def to_completion(self, fallback_model: str) -> Completion:
        return Completion(
            text=self.text,
            model=self.model or fallback_model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            finish_reason=self.finish_reason,
            latency_ms=self.latency_ms,
            usage_reported=self.usage_reported,
        )


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._settings.openrouter_api_key:
                raise ProviderError("OPENROUTER_API_KEY is not configured")
            self._client = httpx.AsyncClient(
                base_url=self._settings.openrouter_base_url,
                timeout=httpx.Timeout(self._settings.request_timeout_seconds, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    # OpenRouter attribution headers; harmless if unset upstream.
                    "HTTP-Referer": "https://eskwelabs.com",
                    "X-Title": self._settings.app_name,
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _payload(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion:
        payload = self._payload(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, stream=False
        )
        started = time.perf_counter()
        data = await self._post_with_retry("/chat/completions", payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"malformed provider response: {str(data)[:200]}") from exc

        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=data.get("model", model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=choice.get("finish_reason"),
            latency_ms=latency_ms,
            usage_reported=bool(usage),
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]:
        """Yield text deltas, mutating `result` so the caller can persist the turn
        even if the client disconnects mid-stream."""
        payload = self._payload(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, stream=True
        )
        client = await self._http()
        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise ProviderError(
                        f"provider returned {response.status_code}: {body[:300]}",
                        status=response.status_code,
                        retryable=response.status_code in _RETRYABLE_STATUS,
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = self._consume_event(event, result)
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider transport error: {exc}", retryable=True) from exc

    @staticmethod
    def _consume_event(event: dict, result: StreamResult) -> str:
        if event.get("model"):
            result.model = event["model"]
        usage = event.get("usage")
        if usage:
            result.prompt_tokens = int(usage.get("prompt_tokens") or result.prompt_tokens)
            result.completion_tokens = int(
                usage.get("completion_tokens") or result.completion_tokens
            )
            result.usage_reported = True
        for choice in event.get("choices") or []:
            if choice.get("finish_reason"):
                result.finish_reason = choice["finish_reason"]
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                result.text += piece
                result.chunks += 1
                return piece
        return ""

    async def _post_with_retry(self, path: str, payload: dict) -> dict:
        client = await self._http()
        last: ProviderError | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await client.post(path, json=payload)
            except httpx.HTTPError as exc:
                last = ProviderError(f"provider transport error: {exc}", retryable=True)
            else:
                if response.status_code < 400:
                    return response.json()
                last = ProviderError(
                    f"provider returned {response.status_code}: {response.text[:300]}",
                    status=response.status_code,
                    retryable=response.status_code in _RETRYABLE_STATUS,
                )
            if not last.retryable or attempt == _MAX_ATTEMPTS:
                break
            backoff = 0.5 * (2 ** (attempt - 1))
            logger.warning("provider attempt %s failed, retrying in %.1fs", attempt, backoff)
            await asyncio.sleep(backoff)
        raise last or ProviderError("provider call failed")
