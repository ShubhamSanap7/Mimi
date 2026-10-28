from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from PIL import Image

from config.settings import Settings
from database.store import Store
from main import split_message
from services.provider import ProviderError, XKiroProvider


def write_valid_gif(path: Path) -> None:
    first = Image.new("RGB", (4, 4), (255, 128, 180))
    second = Image.new("RGB", (4, 4), (255, 160, 200))
    first.save(path, format="GIF", save_all=True, append_images=[second], duration=50, loop=0)


def test_missing_secrets(tmp_path: Path, monkeypatch):
    for key in ("DISCORD_TOKEN", "XKIRO_API_KEY", "OWNER_DISCORD_IDS"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.load(tmp_path)
    assert "DISCORD_TOKEN is missing" in settings.validate_runtime()
    assert "XKIRO_API_KEY is missing" in settings.validate_runtime()


def test_memory_isolation_expiry_and_update(tmp_path: Path):
    store = Store(tmp_path / "data.sqlite3")
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 3
    store.add_memory(1, 10, "I like tea")
    store.add_memory(1, 10, "I like tea")
    store.add_memory(2, 10, "I like coffee")
    assert len(store.list_memories(1, 10, 30, frozenset())) == 1
    assert len(store.list_memories(2, 10, 30, frozenset())) == 1
    assert store.list_memories(1, 11, 30, frozenset()) == []
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    store.conn.execute("UPDATE memories SET last_used_at=? WHERE user_id IN (1,2)", (old,))
    store.conn.commit()
    assert store.list_memories(1, 10, 30, frozenset({1}))
    assert store.list_memories(2, 10, 30, frozenset({1}))
    assert store.sweep_expired_memories(30, frozenset({1})) == 1
    assert store.list_memories(2, 10, 30, frozenset({1})) == []
    assert store.delete_all(1, 10) == 1
    assert store.list_memories(1, 10, 30, frozenset({1})) == []
    store.close()


def test_memory_schema_migrates_old_database_without_losing_rows(tmp_path: Path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, fact TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT NOT NULL, UNIQUE(user_id,guild_id,fingerprint))")
    conn.execute("INSERT INTO memories(user_id,guild_id,fact,fingerprint,created_at,last_used_at) VALUES(1,2,'old fact','old fact','2026-01-01','2026-01-01')")
    conn.commit()
    conn.close()
    store = Store(path)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert store.list_memories(1, 2, 30)[0]["fact"] == "old fact"
    assert "memory_key" in {row[1] for row in store.conn.execute("PRAGMA table_info(memories)")}
    store.close()


def test_memory_pagination_and_scoped_count(tmp_path: Path):
    store = Store(tmp_path / "pages.sqlite3")
    for index in range(25):
        store.add_memory(1, 10, f"fact {index}")
    assert store.count_memories(1, 10) == 25
    assert len(store.list_memories(1, 10, 30, limit=10, offset=0)) == 10
    assert len(store.list_memories(1, 10, 30, limit=10, offset=20)) == 5
    assert store.count_memories(2, 10) == 0
    store.close()


def test_split_message_respects_limit():
    parts = split_message("word " * 1000, 100)
    assert all(len(part) <= 100 for part in parts)
    assert "".join(parts).replace(" ", "")


def test_provider_uses_fallback_model(tmp_path: Path):
    import asyncio

    settings = Settings.load(tmp_path)
    settings.xkiro_api_key = "test-key"
    settings.primary_model = "primary"
    settings.fallback_model = "fallback"
    provider = XKiroProvider(settings)
    calls = []

    async def fake_request(path, payload=None):
        calls.append(payload["model"])
        if payload["model"] == "primary":
            raise ProviderError("primary unavailable")
        return {"choices": [{"message": {"content": "fallback worked"}}]}

    provider._request = fake_request
    answer, model, _, usage = asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))
    asyncio.run(provider.close())
    assert (answer, model) == ("fallback worked", "fallback")
    assert usage["exact"] is False
    assert calls == ["primary", "fallback"]


def test_usage_persists_and_budget_stops(tmp_path: Path):
    store = Store(tmp_path / "data.sqlite3")
    store.add_usage("2026-10-26", 100, 50, False, web_search=True, vision=True)
    store.add_usage("2026-10-26", 25, 10, True)
    usage = store.usage("2026-10-26")
    assert usage["input_tokens"] == 125
    assert usage["output_tokens"] == 60
    assert usage["estimated_tokens"] == 35
    assert usage["web_searches"] == 1
    assert usage["vision_requests"] == 1
    store.close()


def test_budget_enforcement_is_local(tmp_path: Path):
    import asyncio
    from main import MimiBot

    settings = Settings.load(Path(__file__).resolve().parents[1])
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.daily_token_budget = 1000
    settings.budget_safety_margin = 0.8
    bot = MimiBot(settings)
    bot.store.add_usage(bot.date_key(), 800, 0, False)
    allowed, message = bot.can_request(web_search=False, vision=False)
    assert allowed is False
    assert "conservative AI budget" in message
    asyncio.run(bot.close())


def test_owner_activity_ping_state_resets_on_activity(tmp_path: Path):
    store = Store(tmp_path / "data.sqlite3")
    store.record_owner_activity(10, 1, "2026-10-26T00:00:00+00:00")
    store.mark_owner_ping(10, "2026-10-26T13:00:00+00:00")
    assert store.owner_activity(10)["ping_sent_at"] is not None
    store.record_owner_activity(10, 1, "2026-10-26T14:00:00+00:00")
    assert store.owner_activity(10)["ping_sent_at"] is None
    store.close()


def test_interaction_state_distinguishes_new_and_returning_users(tmp_path: Path):
    store = Store(tmp_path / "data.sqlite3")
    assert store.interaction_state(10, 20) is None
    store.record_interaction(10, 20, "2026-10-26T00:00:00+00:00")
    state = store.interaction_state(10, 20)
    assert state["message_count"] == 1
    store.record_interaction(10, 20, "2026-10-26T01:00:00+00:00")
    assert store.interaction_state(10, 20)["message_count"] == 2
    assert store.interaction_state(11, 20) is None
    store.close()


def test_concise_output_setting_is_configurable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "220")
    settings = Settings.load(tmp_path)
    assert settings.max_output_tokens == 220


def test_local_reaction_is_selected_and_sent(tmp_path: Path):
    import asyncio
    from main import MimiBot

    reaction_dir = tmp_path / "reactions"
    reaction_dir.mkdir()
    reaction = reaction_dir / "happy.gif"
    write_valid_gif(reaction)
    settings = Settings.load(Path(__file__).resolve().parents[1])
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = reaction_dir
    settings.reaction_probability = 1.0
    bot = MimiBot(settings)
    selected = bot._select_local_reaction("yay, thanks!", "awesome")
    assert selected == reaction

    class Channel:
        def __init__(self):
            self.sent_file = None

        async def send(self, *, file, allowed_mentions):
            self.sent_file = file
            assert allowed_mentions.everyone is False
            assert allowed_mentions.roles is False

    channel = Channel()
    assert asyncio.run(bot._send_local_reaction(channel, selected)) is True
    assert channel.sent_file.filename == "happy.gif"
    channel.sent_file.close()
    asyncio.run(bot.close())


def test_reaction_request_and_missing_or_invalid_assets(tmp_path: Path):
    import asyncio
    from main import MimiBot

    settings = Settings.load(Path(__file__).resolve().parents[1])
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = tmp_path / "reactions"
    settings.reaction_library_dir.mkdir()
    (settings.reaction_library_dir / "shock.gif").write_bytes(b"not a gif")
    bot = MimiBot(settings)
    assert bot._reaction_request_category("send me a shocked anime GIF") == "shock"
    assert bot._select_local_reaction("send me a shocked anime GIF", requested_category="shock", force=True) is None

    class BrokenChannel:
        async def send(self, *, file, allowed_mentions):
            raise OSError("missing file")

    valid = settings.reaction_library_dir / "shock.gif"
    write_valid_gif(valid)
    assert asyncio.run(bot._send_local_reaction(BrokenChannel(), valid)) is False
    asyncio.run(bot.close())


def test_help_uses_registered_commands():
    from main import bot, command_help_text

    names = {command.name for command in bot.tree.get_commands()}
    assert names == {"help", "memory", "forget", "forget-all", "diagnostics", "settings", "dashboard"}
    text = command_help_text(bot.tree)
    for name in names:
        assert f"/{name}" in text
    assert "<memory_id>" in text
    assert "owner-only" in text
