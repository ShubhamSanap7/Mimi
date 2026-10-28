from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from config.settings import Settings
from services.error_messages import ErrorMessageSelector, MESSAGES, category_for_error
from services.provider import ProviderError, XKiroProvider, _classify_status


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
