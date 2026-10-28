from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from config.settings import Settings
from services.error_messages import ErrorMessageSelector, MESSAGES, category_for_error
from services.provider import AIProviderRouter, ProviderError, XKiroProvider, _classify_status


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_all_error_categories_have_multiple_friendly_messages_without_secrets():
    for category, messages in MESSAGES.items():
        assert len(messages) >= 5
        assert len(set(messages)) == len(messages)
        assert all("API_KEY" not in message and "Bearer" not in message for message in messages)
        assert category_for_error(ProviderError("hidden", category=category)) == category
    assert category_for_error(RuntimeError("unexpected secret token")) == "unknown"


def test_selector_avoids_recent_message_per_category_and_scope():
    selector = ErrorMessageSelector(chooser=lambda options: options[0])
    first = selector.choose("network", 42)
    second = selector.choose("network", 42)
    third_scope = selector.choose("network", 99)
    assert first != second
    assert third_scope == first
    assert selector.choose("not-a-category", 42) in MESSAGES["unknown"]


def test_http_status_classification_is_specific_for_403():
    assert _classify_status(429, "insufficient_quota")[0] == "rate_limit"
    assert _classify_status(401, None)[0] == "authentication"
    assert _classify_status(403, None)[0] == "unknown"
    assert _classify_status(403, "invalid_api_key")[0] == "authentication"
    assert _classify_status(422, "bad_payload")[0] == "invalid_request"
    assert _classify_status(503, "overloaded")[0] == "server"


def test_provider_preserves_sanitized_category_metadata(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "errors.sqlite3"
    settings.max_retries = 0
    provider = XKiroProvider(settings)

    class Response:
        status_code = 429
        is_error = True

        def json(self):
            return {"error": {"code": "insufficient_quota", "message": "secret bearer token must not be shown"}}

    class Client:
        async def post(self, *_args, **_kwargs):
            return Response()

        async def aclose(self):
            return None

    provider.client = Client()

    async def run():
        with pytest.raises(ProviderError) as raised:
            await provider._request("/chat/completions", {"model": "test"})
        error = raised.value
        assert error.category == "rate_limit"
        assert error.status_code == 429
        assert error.provider_code == "insufficient_quota"
        assert "bearer" not in str(error).lower()
        await provider.close()

    asyncio.run(run())


def test_router_primary_success_never_calls_groq(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.groq_api_key = "groq-test-key"
    settings.database_path = tmp_path / "router.sqlite3"
    router = AIProviderRouter(settings)
    calls = []

    class Primary:
        async def complete(self, *args, **kwargs):
            calls.append("xkiro")
            return "primary answer", "primary", {}, {"input_tokens": 2, "output_tokens": 1, "exact": True}

        async def close(self):
            return None

    class Secondary:
        async def complete(self, *args, **kwargs):
            calls.append("groq")
            return "groq answer", "groq-model", {}, {"input_tokens": 2, "output_tokens": 1, "exact": True}

        async def close(self):
            return None

    router.xkiro = Primary()
    router.groq = Secondary()

    async def run():
        answer, _, _, _ = await router.complete([{"role": "user", "content": "hi"}])
        assert answer == "primary answer"
        assert calls == ["xkiro"]
        await router.close()

    asyncio.run(run())


def test_router_uses_groq_once_only_for_transient_xkiro_failure(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.groq_api_key = "groq-test-key"
    settings.database_path = tmp_path / "router.sqlite3"
    router = AIProviderRouter(settings)
    calls = []

    class Primary:
        async def complete(self, *args, **kwargs):
            calls.append("xkiro")
            raise ProviderError("temporary", category="network", retryable=True)

        async def close(self):
            return None

    class Secondary:
        async def complete(self, *args, **kwargs):
            calls.append("groq")
            return "groq answer", "llama", {}, {"input_tokens": 2, "output_tokens": 1, "exact": True}

        async def close(self):
            return None

    router.xkiro = Primary()
    router.groq = Secondary()

    async def run():
        answer, model, _, _ = await router.complete([{"role": "user", "content": "hi"}])
        assert answer == "groq answer"
        assert model == "groq/llama"
        assert calls == ["xkiro", "groq"]
        await router.close()

    asyncio.run(run())


def test_router_does_not_use_groq_for_permanent_xkiro_error_or_missing_key(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.groq_api_key = ""
    settings.database_path = tmp_path / "router.sqlite3"
    router = AIProviderRouter(settings)
    calls = []

    class Primary:
        async def complete(self, *args, **kwargs):
            calls.append("xkiro")
            raise ProviderError("bad key", category="authentication", retryable=False)

        async def close(self):
            return None

    router.xkiro = Primary()
    assert router.groq is None

    async def run():
        with pytest.raises(ProviderError) as raised:
            await router.complete([{"role": "user", "content": "hi"}])
        assert raised.value.category == "authentication"
        assert calls == ["xkiro"]
        await router.close()

    asyncio.run(run())


def test_both_provider_failure_path_produces_one_custom_reply(tmp_path: Path):
    from main import MimiBot

    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "bot.sqlite3"
    bot = MimiBot(settings)

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Channel:
        id = 991

        def typing(self):
            return Typing()

    class Author:
        id = 992
        bot = False

    class Guild:
        id = 993

    class Message:
        id = 994
        content = "Mimi, answer this"
        channel = Channel()
        author = Author()
        guild = Guild()
        attachments = []
        reference = None

        def __init__(self):
            self.replies = []

        async def reply(self, content, **kwargs):
            self.replies.append((content, kwargs))

    class FailedRouter:
        async def complete(self, *args, **kwargs):
            raise ProviderError("both routes failed", category="server", status_code=503, retryable=True)

        @property
        def groq_configured(self):
            return True

        async def close(self):
            return None

    async def run():
        bot.provider = FailedRouter()
        message = Message()
        await bot._generate_reply(message)
        assert len(message.replies) == 1
        assert "503" not in message.replies[0][0]
        assert "both routes failed" not in message.replies[0][0]
        await bot.close()

    asyncio.run(run())
