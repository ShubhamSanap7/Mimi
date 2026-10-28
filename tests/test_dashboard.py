from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from config.settings import Settings
from database.store import Store
from main import DashboardView, MimiBot
from services.runtime_settings import RuntimeSettings
from services.runtime_settings import EXCLUDED_SETTINGS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_registry(tmp_path: Path) -> tuple[Settings, Store, RuntimeSettings]:
    settings = Settings.load(PROJECT_ROOT)
    settings.database_path = tmp_path / "dashboard.sqlite3"
    store = Store(settings.database_path)
    return settings, store, RuntimeSettings(settings, store)


def test_dashboard_settings_persist_and_override_environment_defaults(tmp_path: Path):
    settings, store, registry = make_registry(tmp_path)
    settings.reaction_probability = 0.12
    assert registry.set("reaction_probability", "0.75") == 0.75
    assert settings.reaction_probability == 0.75
    store.close()

    settings2 = Settings.load(tmp_path)
    settings2.database_path = tmp_path / "dashboard.sqlite3"
    store2 = Store(settings2.database_path)
    registry2 = RuntimeSettings(settings2, store2)
    assert registry2.value("reaction_probability") == 0.75
    assert registry2.is_overridden("reaction_probability")
    registry2.reset("reaction_probability")
    assert registry2.value("reaction_probability") == 0.12
    assert not registry2.is_overridden("reaction_probability")
    store2.close()


def test_dashboard_validates_bounds_and_fixed_safety_controls(tmp_path: Path):
    _, store, registry = make_registry(tmp_path)
    with pytest.raises(ValueError):
        registry.set("multi_bot_initiation_probability", 2)
    with pytest.raises(ValueError):
        registry.set("multi_bot_duplicate_protection", False)
    assert registry.set("excluded_channel_ids", "10, 20") == frozenset({10, 20})
    assert registry.set("moderation_alert_keywords", "scam, phishing") == ("scam", "phishing")
    assert registry.set("daily_token_budget", 2_000_000) == 2_000_000
    assert registry.set("multi_bot_response_creativity", 0.4) == 0.4
    assert registry.set("multi_bot_typical_reply_length", 180) == 180
    assert registry.set("multi_bot_topic_repeat_protection", False) is False
    store.close()


def test_dashboard_reset_all_keeps_security_settings_out_of_registry(tmp_path: Path):
    settings, store, registry = make_registry(tmp_path)
    assert "discord_token" not in registry.specs
    assert "xkiro_api_key" not in registry.specs
    assert "owner_ids" not in registry.specs
    registry.set("multi_bot_enabled", True)
    registry.set("reaction_probability", 0.9)
    registry.reset_all()
    assert settings.multi_bot_enabled == registry.environment_defaults["multi_bot_enabled"]
    assert settings.reaction_probability == registry.environment_defaults["reaction_probability"]
    store.close()


def test_dashboard_categories_only_reference_existing_settings(tmp_path: Path):
    _, store, registry = make_registry(tmp_path)
    for spec in registry.specs.values():
        if spec.kind != "fixed":
            assert hasattr(registry.settings, spec.key)
    assert "Multi-bot conversations" in registry.categories()
    assert "GIFs and reactions" in registry.categories()
    store.close()


def test_registry_covers_every_settings_field_except_documented_exclusions(tmp_path: Path):
    from dataclasses import fields

    _, store, registry = make_registry(tmp_path)
    settings_keys = {field.name for field in fields(registry.settings)}
    missing = settings_keys - set(registry.specs) - set(EXCLUDED_SETTINGS)
    assert missing == set()
    assert {"discord_token", "xkiro_api_key", "groq_api_key", "owner_ids"} <= set(EXCLUDED_SETTINGS)
    assert registry.inventory()["excluded"] == EXCLUDED_SETTINGS
    store.close()


def test_runtime_change_updates_consumer_and_records_nonsecret_audit(tmp_path: Path):
    settings, store, registry = make_registry(tmp_path)
    assert registry.set("personality_prompt", "A concise test personality.", changed_by=123) == "A concise test personality."
    assert settings.personality_prompt == "A concise test personality."
    rows = store.recent_setting_audit()
    assert rows[0]["changed_by"] == 123
    assert rows[0]["setting_key"] == "personality_prompt"
    assert "A concise" not in rows[0]["old_value"] or "length=" in rows[0]["new_value"]
    store.close()


def test_dashboard_marks_startup_captured_settings_and_allows_empty_prompt_reset(tmp_path: Path):
    _, store, registry = make_registry(tmp_path)
    assert registry.specs["max_retries"].live is False
    assert registry.specs["request_timeout_seconds"].live is False
    assert registry.set("personality_prompt", "") == ""
    assert registry.value("personality_prompt") == ""
    store.close()


def test_dashboard_view_requires_owner_on_every_interaction(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "bot.sqlite3"
    settings.owner_ids = frozenset({123})
    bot = MimiBot(settings)
    view = DashboardView(bot)

    class Response:
        def __init__(self):
            self.calls = []

        async def send_message(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class Interaction:
        def __init__(self, user_id):
            self.user = type("User", (), {"id": user_id})()
            self.response = Response()

    async def run():
        authorized = Interaction(123)
        unauthorized = Interaction(999)
        assert await view.interaction_check(authorized) is True
        assert await view.interaction_check(unauthorized) is False
        assert unauthorized.response.calls
        await bot.close()

    asyncio.run(run())
