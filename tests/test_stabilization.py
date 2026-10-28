import asyncio
from pathlib import Path

import pytest

from config.settings import Settings
from database.store import Store
from main import MimiBot
from services.reactions import ReactionLibrary
from services.runtime_settings import RuntimeSettings, SettingSpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_manifest_metadata_is_cached_and_invalidated(tmp_path: Path, monkeypatch):
    root = tmp_path / "reactions"
    root.mkdir()
    library = ReactionLibrary(root)
    (root / "manifest.json").write_text('{"assets": [{"path": "happy.gif", "tags": ["happy"]}]}', encoding="utf-8")
    calls = 0
    original = library.load_manifest

    def counted_load():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(library, "load_manifest", counted_load)
    assert library.manifest_metadata()["happy.gif"]["tags"] == ["happy"]
    assert library.manifest_metadata()["happy.gif"]["tags"] == ["happy"]
    assert calls == 1
    (root / "manifest.json").write_text('{"assets": [{"path": "happy.gif", "tags": ["updated"]}]}', encoding="utf-8")
    assert library.manifest_metadata()["happy.gif"]["tags"] == ["updated"]
    assert calls == 2


def test_category_patterns_are_precompiled_and_keep_matching_behavior():
    from services.reactions import CATEGORY_PATTERNS

    assert all(hasattr(pattern, "search") for _, pattern in CATEGORY_PATTERNS)
    assert ReactionLibrary.infer_category("that was hilarious") == "laughing"
    assert ReactionLibrary.infer_category("unexpected tournament victory") == "shock"


def test_runtime_choices_are_enforced_and_invalid_templates_rejected(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    store = Store(tmp_path / "settings.sqlite3")
    registry = RuntimeSettings(settings, store)
    spec = SettingSpec("choice", "test", "Choice", "", "str", choices=("one", "two"))
    with pytest.raises(ValueError):
        registry._coerce(spec, "three")
    with pytest.raises(ValueError):
        registry.set("inactivity_template", "{unsupported}")
    store.close()


def test_concurrent_budget_reservations_and_requests_do_not_hold_lock_over_network(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "budget.sqlite3"
    settings.daily_token_budget = 10_000
    settings.budget_safety_margin = 0.9
    settings.max_concurrent_requests = 2
    bot = MimiBot(settings)

    async def run():
        active = 0
        peak = 0

        async def complete(*_args, **_kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            assert not bot.ai_budget_lock.locked()
            await asyncio.sleep(0.02)
            active -= 1
            return "ok", "test", {}, {"input_tokens": 30, "output_tokens": 20, "exact": True}

        bot.provider.complete = complete

        class Author:
            def __init__(self, user_id):
                self.id = user_id

        class Channel:
            id = 123

            class Typing:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

            def typing(self):
                return self.Typing()

        class Message:
            def __init__(self, message_id, user_id):
                self.id = message_id
                self.content = "hello"
                self.author = Author(user_id)
                self.guild = None
                self.channel = Channel()
                self.reference = None
                self.attachments = []

            async def reply(self, *_args, **_kwargs):
                return None

        await asyncio.gather(bot._generate_reply(Message(1, 1)), bot._generate_reply(Message(2, 2)))
        assert peak == 2
        assert bot.usage_status()["reserved_tokens"] == 0
        assert bot.store.usage(bot.date_key())["input_tokens"] == 60
        await bot.close()

    asyncio.run(run())


def test_resolved_reply_reference_is_used_without_fetching(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "reply.sqlite3"
    bot = MimiBot(settings)

    class Author:
        display_name = "ReferencedUser"

    class Resolved:
        author = Author()
        content = "already loaded"

    class Reference:
        message_id = 42
        resolved = Resolved()

    class Channel:
        def get_partial_message(self, _message_id):
            raise AssertionError("resolved references should not be fetched")

    class Message:
        reference = Reference()
        channel = Channel()

    assert asyncio.run(bot._reply_context(Message())) == "Referenced message by ReferencedUser: already loaded"
    asyncio.run(bot.close())
