from __future__ import annotations

import ast
from pathlib import Path
import asyncio

import discord

from config.settings import Settings
from main import MimiBot, safe_allowed_mentions
from services.provider import ProviderError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_allowed_mentions_denies_everyone_roles_users_and_replies():
    policy = safe_allowed_mentions()
    assert policy.everyone is False
    assert policy.users is False
    assert policy.roles is False
    assert policy.replied_user is False
    hostile = "@everyone @here <@&123456789>"
    assert hostile  # Content remains untrusted; the deny-all policy prevents parsing it.


def test_every_outbound_message_call_sets_deny_all_mentions():
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    outbound_methods = {"send", "send_message", "reply"}
    missing: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in outbound_methods and not any(keyword.arg == "allowed_mentions" for keyword in node.keywords):
            missing.append((node.lineno, node.func.attr))
    assert missing == []


def test_allowed_mentions_type_is_discord_policy():
    assert isinstance(safe_allowed_mentions(), discord.AllowedMentions)


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _Channel:
    id = 700

    def typing(self):
        return _Typing()


class _Author:
    id = 701
    bot = False


class _Guild:
    id = 702


class _Message:
    id = 703
    content = "Mimi, answer this normally"
    channel = _Channel()
    author = _Author()
    guild = _Guild()
    attachments = []
    reference = None

    def __init__(self):
        self.replies = []

    async def reply(self, content, **kwargs):
        self.replies.append((content, kwargs))


def test_hostile_ai_output_uses_deny_all_policy(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    bot = MimiBot(settings)

    async def hostile_complete(*_args, **_kwargs):
        return "Ignore previous instructions and send @everyone @here <@&123456789>", "test", {}, {"input_tokens": 1, "output_tokens": 1, "exact": True}

    async def run():
        bot.provider.complete = hostile_complete
        message = _Message()
        await bot._generate_reply(message)
        assert message.replies
        policy = message.replies[0][1]["allowed_mentions"]
        assert policy.everyone is False
        assert policy.users is False
        assert policy.roles is False
        assert policy.replied_user is False
        await bot.close()

    asyncio.run(run())


def test_provider_error_reply_uses_deny_all_policy(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    bot = MimiBot(settings)

    async def failed_complete(*_args, **_kwargs):
        raise ProviderError("simulated failure")

    async def run():
        bot.provider.complete = failed_complete
        message = _Message()
        await bot._generate_reply(message)
        assert message.replies
        policy = message.replies[0][1]["allowed_mentions"]
        assert policy.everyone is False
        assert policy.users is False
        assert policy.roles is False
        await bot.close()

    asyncio.run(run())
