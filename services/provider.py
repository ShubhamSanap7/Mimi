from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from config.settings import Settings

log = logging.getLogger("mimi.provider")


class ProviderError(RuntimeError):
    pass


class XKiroProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.xkiro_base_url,
            headers={"Authorization": f"Bearer {settings.xkiro_api_key}", "Content-Type": "application/json"},
            timeout=settings.request_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await self.client.get(path) if payload is None else await self.client.post(path, json=payload)
                if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < self.settings.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.settings.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
        raise ProviderError(f"xKiro request failed: {type(last_error).__name__}") from last_error

    async def list_models(self) -> list[str]:
        data = await self._request("/models")
        return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]

    async def complete(self, messages: list[dict[str, Any]], *, use_web_search: bool = False,
                       model: str | None = None) -> tuple[str, str, dict[str, Any], dict[str, int | bool]]:
        requested_model = model or self.settings.primary_model
        models = [requested_model]
        if requested_model == self.settings.primary_model and self.settings.fallback_model != requested_model:
            models.append(self.settings.fallback_model)
        last_error: Exception | None = None
        for model_name in models:
            payload: dict[str, Any] = {"model": model_name, "messages": messages,
                                       "temperature": 0.7, "max_tokens": self.settings.max_output_tokens}
            if use_web_search:
                payload["web_search"] = {"enable": True, "count": 5}
            try:
                data = await self._request("/chat/completions", payload)
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    raise ProviderError("xKiro returned no message content")
                provider_usage = data.get("usage") or {}
                exact = isinstance(provider_usage.get("prompt_tokens"), int) and isinstance(provider_usage.get("completion_tokens"), int)
                if exact:
                    input_tokens = int(provider_usage["prompt_tokens"])
                    output_tokens = int(provider_usage["completion_tokens"])
                else:
                    raw = json.dumps(messages, ensure_ascii=False)
                    input_tokens = max(1, len(raw) // 4)
                    output_tokens = max(1, len(str(content)) // 4)
                    if any(isinstance(message.get("content"), list) for message in messages):
                        input_tokens += 1000
                usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "exact": exact}
                return str(content).strip(), model_name, data.get("web_search") or {}, usage
            except ProviderError as exc:
                last_error = exc
                log.warning("Model request failed for configured route %s", model_name)
        raise ProviderError("All configured xKiro models failed") from last_error
