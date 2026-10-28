from __future__ import annotations

import asyncio
from pathlib import Path

from config.settings import Settings
from database.store import Store
from main import MimiBot
from services.capabilities import build_capabilities, capability_prompt
from services.memory_intent import detect_memory_intent


ROOT = Path(__file__).resolve().parents[1]


def test_explicit_memory_intent_is_distinct_from_ordinary_fact():
    assert detect_memory_intent("I like tea") is None
    intent = detect_memory_intent("Remember that Alex's birthday is 14 March.")
    assert intent and intent.action == "save" and "birthday" in intent.fact
    assert detect_memory_intent("Do you remember my birthday?") is None
    assert detect_memory_intent("Forget that fact")


def test_explicit_memory_save_is_persisted_and_visible(tmp_path: Path):
    settings = Settings.load(ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "mimi.sqlite3"
    settings.owner_ids = frozenset({1})
    bot = MimiBot(settings)

    class Channel:
        id = 20
        async def send(self, *args, **kwargs):
            return None

    class Message:
        id = 100
        content = "Remember that my birthday is 14 March."
        author = type("User", (), {"id": 1, "bot": False})()
        guild = type("Guild", (), {"id": 10, "members": []})()
        channel = Channel()
        mentions = []
        reference = None
        attachments = []
        async def reply(self, content, **kwargs):
            self.reply_content = content

    message = Message()

    async def run():
        await bot.handle_message(message)
        rows = bot.store.list_memories(1, 10, 30)
        assert len(rows) == 1
        assert "birthday" in rows[0]["fact"]
        assert "saved" in message.reply_content.lower()
        await bot.close()

    asyncio.run(run())


def test_identity_and_capability_prompt_reflect_live_groq_model(tmp_path: Path):
    settings = Settings.load(ROOT)
    settings.xkiro_api_key = "test-key"
    settings.groq_api_key = "groq-test-key"
    settings.groq_model = "qwen/qwen3.8-27b"
    settings.database_path = tmp_path / "mimi.sqlite3"
    bot = MimiBot(settings)
    text = bot._identity_prompt()
    assert "Mimi" in text and "AI agent" in text
    assert "qwen/qwen3.8-27b" in text
    assert "test-key" not in text and "groq-test-key" not in text
    assert "Scoped memory" in text
    asyncio.run(bot.close())


def test_named_server_member_memory_gets_stable_discord_identity(tmp_path: Path):
    settings = Settings.load(ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "mimi.sqlite3"
    bot = MimiBot(settings)
    member = type("Member", (), {"id": 77, "name": "Alex", "display_name": "Alex"})()
    message = type("Message", (), {
        "guild": type("Guild", (), {"members": [member]})(),
        "author": type("User", (), {"id": 1})(),
    })()
    fact, subject = bot._resolve_memory_subject(message, "Alex's birthday is 14 March")
    assert subject == "77"
    assert "Discord user ID 77" in fact
    asyncio.run(bot.close())


def test_capability_registry_marks_optional_features_unavailable(tmp_path: Path):
    settings = Settings.load(ROOT)
    settings.xkiro_api_key = ""
    settings.groq_api_key = ""
    settings.database_path = tmp_path / "mimi.sqlite3"
    bot = MimiBot(settings)
    capabilities = build_capabilities(settings, bot.provider, vision_enabled=False, reaction_assets=False)
    by_id = {item.identifier: item for item in capabilities}
    assert by_id["xkiro"].available is False
    assert by_id["groq_fallback"].available is False
    assert by_id["local_reactions"].available is False
    asyncio.run(bot.close())
