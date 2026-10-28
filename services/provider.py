from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from config.settings import Settings

log = logging.getLogger("mimi.provider")


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, category: str = "unknown", status_code: int | None = None,
                 provider_code: str | None = None, retryable: bool = False,
                 exception_type: str | None = None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.provider_code = provider_code
        self.retryable = retryable
        self.exception_type = exception_type or type(self).__name__


def _response_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    source = error if isinstance(error, dict) else payload if isinstance(payload, dict) else {}
    value = source.get("code") or source.get("type") or source.get("error_code")
    candidate = str(value)[:100] if value is not None else ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", candidate) else None


def _classify_status(status_code: int, provider_code: str | None) -> tuple[str, bool]:
    code = (provider_code or "").lower()
    if status_code in {408, 429}:
        return "rate_limit", True
    if status_code == 401:
        return "authentication", False
    if status_code == 403:
        if any(token in code for token in ("auth", "credential", "token", "key", "permission", "access")):
            return "authentication", False
        return "unknown", False
    if status_code in {400, 404, 422}:
        return "invalid_request", False
    if 500 <= status_code <= 599:
        return "server", True
    return "unknown", False


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
        last_error: ProviderError | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await self.client.get(path) if payload is None else await self.client.post(path, json=payload)
                if response.is_error:
                    code = _response_error_code(response)
                    category, retryable = _classify_status(response.status_code, code)
                    raise ProviderError(
                        "xKiro request returned an HTTP error",
                        category=category,
                        status_code=response.status_code,
                        provider_code=code,
                        retryable=retryable,
                        exception_type="HTTPStatusError",
                    )
                try:
                    return response.json()
                except (ValueError, TypeError) as exc:
                    raise ProviderError(
                        "xKiro returned invalid JSON",
                        category="server", retryable=True, exception_type=type(exc).__name__,
                    ) from exc
            except ProviderError as exc:
                last_error = exc
                if exc.retryable and attempt < self.settings.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise
            except httpx.TimeoutException as exc:
                last_error = ProviderError("xKiro request timed out", category="network", retryable=True, exception_type=type(exc).__name__)
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_error = ProviderError("xKiro network request failed", category="network", retryable=True, exception_type=type(exc).__name__)
            except httpx.HTTPError as exc:
                last_error = ProviderError("xKiro transport request failed", category="network", retryable=True, exception_type=type(exc).__name__)
            except ValueError as exc:
                last_error = ProviderError("xKiro request configuration was invalid", category="invalid_request", exception_type=type(exc).__name__)
            if last_error and last_error.retryable and attempt < self.settings.max_retries:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if last_error:
                raise last_error from exc
        raise last_error or ProviderError("xKiro request failed", category="unknown")

    async def list_models(self) -> list[str]:
        data = await self._request("/models")
        return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]

    async def complete(self, messages: list[dict[str, Any]], *, use_web_search: bool = False,
                       model: str | None = None, temperature: float = 0.7,
                       max_tokens: int | None = None) -> tuple[str, str, dict[str, Any], dict[str, int | bool]]:
        requested_model = model or self.settings.primary_model
        models = [requested_model]
        if requested_model == self.settings.primary_model and self.settings.fallback_model != requested_model:
            models.append(self.settings.fallback_model)
        last_error: Exception | None = None
        for model_name in models:
            payload: dict[str, Any] = {"model": model_name, "messages": messages,
                                       "temperature": temperature,
                                       "max_tokens": max_tokens or self.settings.max_output_tokens}
            if use_web_search:
                payload["web_search"] = {"enable": True, "count": 5}
            try:
                data = await self._request("/chat/completions", payload)
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    raise ProviderError("xKiro returned no message content", category="invalid_request")
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
                log.warning(
                    "Model request failed route=%s category=%s status=%s code=%s exception=%s",
                    model_name, exc.category, exc.status_code, exc.provider_code, exc.exception_type,
                )
        if last_error is not None:
            raise ProviderError(
                "All configured xKiro models failed",
                category=last_error.category,
                status_code=last_error.status_code,
                provider_code=last_error.provider_code,
                retryable=last_error.retryable,
                exception_type=last_error.exception_type,
            ) from last_error
        raise ProviderError("All configured xKiro models failed", category="unknown")
