from __future__ import annotations

import ast
from pathlib import Path

import discord

from main import safe_allowed_mentions


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
