"""Constrained natural-language action planning and execution.

This module deliberately does not execute model-generated code or trust free-form
model output as a tool call. The initial agent surface is deterministic and only
dispatches capabilities registered below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

import discord

log = logging.getLogger("mimi.agent")


MAX_PENDING_SECONDS = 15 * 60
MAX_SCHEDULE_SECONDS = 7 * 24 * 3600
MAX_SCHEDULES_PER_SCOPE = 10
MAX_POLL_OPTIONS = 10
MAX_POLL_QUESTION = 300
MAX_POLL_OPTION = 55


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    description: str
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...]
    risk: str
    confirmation_required: bool
    retry_safe: bool
    execute: Callable[[Any, dict[str, Any], Any], Awaitable["CapabilityResult"]]


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActionPlan:
    capability: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    cancel: bool = False


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._items:
            raise ValueError(f"duplicate capability: {capability.name}")
        self._items[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._items.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._items)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<@!?\d+>", "", text)).strip(" .,:;!?\n")


def _duration(text: str) -> int | None:
    match = re.search(r"\b(?:in|for|after)\s+(\d{1,4})\s*(minute|minutes|min|hour|hours|day|days)\b", text, re.I)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    multiplier = 60 if unit.startswith("min") else 3600 if unit.startswith("hour") else 86400
    return amount * multiplier


def _split_options(raw: str) -> list[str]:
    values = [item.strip(" `\"'") for item in re.split(r"\s*,\s*|\s*;\s*|\s+and\s+", raw, flags=re.I)]
    return [item for item in values if item]


class NaturalLanguagePlanner:
    """A small, strict planner for known action phrases only."""

    _cancel = re.compile(r"(?i)^\s*(?:cancel|stop|never mind|nevermind|forget it)\b")
    _poll = re.compile(r"(?i)\b(?:make|create|start|set\s+up|setup)\s+(?:a\s+)?poll\b")
    _send = re.compile(r"(?i)\b(?:send|post)\s+(?:(?:a|this|the)\s+)?message\b")
    _schedule = re.compile(r"(?i)\b(?:remind\s+me|set\s+a\s+reminder|schedule\s+(?:a\s+)?follow[- ]?up|send\s+later)\b")
    _development = re.compile(r"(?i)\b(?:add|implement|build|code|program|develop|feature|functionality)\b")

    def is_candidate(self, text: str) -> bool:
        indirect_send = re.search(r"(?i)\b(?:need|want|have|going|trying)\s+to\s+send\b", text)
        direct_send = self._send.search(text) and not indirect_send
        return bool(self._cancel.search(text) or self._poll.search(text) or direct_send or self._schedule.search(text)
                    or (self._development.search(text) and re.search(r"(?i)\b(?:poll|reminder|follow[- ]?up|capability|feature)\b", text)))

    def plan(self, text: str, pending_capability: str | None = None,
             pending_arguments: dict[str, Any] | None = None) -> ActionPlan:
        if self._cancel.search(text):
            return ActionPlan(None, cancel=True)
        if pending_capability:
            if pending_capability == "create_poll":
                return self._poll_plan(text, pending_arguments or {}, continuation=True)
            if pending_capability == "schedule_followup":
                return self._schedule_plan(text, pending_arguments or {}, continuation=True)
            if pending_capability == "send_message":
                return self._send_plan(text, pending_arguments or {}, continuation=True)
        if self._development.search(text) and re.search(r"(?i)\b(?:poll|reminder|follow[- ]?up|capability|feature)\b", text):
            return ActionPlan("code_change")
        if self._poll.search(text):
            return self._poll_plan(text, {})
        if self._schedule.search(text):
            return self._schedule_plan(text, {})
        if self._send.search(text) and not re.search(r"(?i)\b(?:need|want|have|going|trying)\s+to\s+send\b", text):
            return self._send_plan(text, {})
        return ActionPlan(None)

    def _poll_plan(self, text: str, current: dict[str, Any], *, continuation: bool = False) -> ActionPlan:
        source = _clean(text)
        question = current.get("question")
        options = list(current.get("options") or [])
        duration_seconds = current.get("duration_seconds")
        if not question and continuation:
            question = source
        if not question and not continuation:
            match = re.search(r"(?i)\b(?:about|poll\s*[:\-])\s*(.+?)(?=\s+(?:with|options?|for|lasting|duration)\b|$)", source)
            if match:
                question = match.group(1).strip()
        option_match = re.search(r"(?i)\b(?:options?|choices?)\s*(?:are|include|=|:)\s*(.+?)(?=\s+(?:for|lasting|duration)\b|$)", source)
        if option_match:
            options = _split_options(option_match.group(1))
        elif continuation and question:
            candidate_source = re.sub(r"(?i)\s+(?:for|lasting|duration)\s+\d+\s*(?:minute|minutes|min|hour|hours|day|days)\b.*$", "", source)
            candidate = _split_options(candidate_source)
            if len(candidate) >= 2:
                options = candidate
        parsed_duration = _duration(source)
        if parsed_duration is not None:
            duration_seconds = parsed_duration
        args = {"question": question, "options": options, "duration_seconds": duration_seconds}
        missing = []
        if not question:
            missing.append("question")
        if len(options) < 2:
            missing.append("options")
        if duration_seconds is None:
            missing.append("duration")
        if missing:
            return ActionPlan("create_poll", args, tuple(missing))
        if len(question) > MAX_POLL_QUESTION or any(len(item) > MAX_POLL_OPTION for item in options) or len(options) > MAX_POLL_OPTIONS:
            return ActionPlan("create_poll", {**args, "invalid": True}, ("valid poll question/options",))
        # Discord native polls require an integer number of hours; do not claim
        # that a ten-minute poll was created when the API cannot honor it.
        if duration_seconds is not None and (duration_seconds < 3600 or duration_seconds > 168 * 3600 or duration_seconds % 3600):
            return ActionPlan("create_poll", {**args, "invalid": True}, ("duration of 1-168 whole hours",))
        return ActionPlan("create_poll", args)

    def _send_plan(self, text: str, current: dict[str, Any], *, continuation: bool = False) -> ActionPlan:
        source = _clean(text)
        content = current.get("content")
        if not content:
            match = re.search(r"(?is)(?:saying|that\s+says|message\s+is|:\s*)(.+)$", source)
            if match:
                content = match.group(1).strip(" `\"'")
            elif continuation and source:
                content = source
        destination_id = current.get("destination_id")
        destination = re.search(r"<#(\d+)>", text)
        if destination:
            destination_id = int(destination.group(1))
        args = {"content": content, "destination_id": destination_id}
        return ActionPlan("send_message", args, () if content else ("message content",))

    def _schedule_plan(self, text: str, current: dict[str, Any], *, continuation: bool = False) -> ActionPlan:
        source = _clean(text)
        content = current.get("content")
        seconds = current.get("delay_seconds")
        match = re.search(r"(?is)\b(?:to|that\s+says|saying|message)\s+(.+?)(?=\s+in\s+\d|$)", source)
        if match:
            content = match.group(1).strip(" `\"'")
        elif continuation and source and not re.search(r"\b(?:in|after)\s+\d+\s+\w+", source, re.I):
            content = source
        parsed = _duration(source)
        if parsed is not None:
            seconds = parsed
        args = {"content": content, "delay_seconds": seconds}
        missing = []
        if not content:
            missing.append("follow-up message")
        if seconds is None:
            missing.append("delay")
        elif seconds < 60 or seconds > MAX_SCHEDULE_SECONDS:
            missing.append("delay between 1 minute and 7 days")
        return ActionPlan("schedule_followup", args, tuple(missing))


class AgentCore:
    def __init__(self, bot: Any):
        self.bot = bot
        self.planner = NaturalLanguagePlanner()
        self.registry = CapabilityRegistry()
        self.registry.register(Capability("send_message", "Send one user-requested Discord message in the current authorized scope.", ("content",), ("destination_id",), "low", False, False, self._send_message))
        self.registry.register(Capability("create_poll", "Create a native Discord poll with validated options and duration.", ("question", "options"), ("duration_seconds",), "low", False, False, self._create_poll))
        self.registry.register(Capability("schedule_followup", "Schedule one bounded follow-up message in a guild channel.", ("content", "delay_seconds"), (), "low", False, False, self._schedule_followup))

    def pending_for(self, message: Any) -> Any:
        guild_id = getattr(getattr(message, "guild", None), "id", 0) or 0
        return self.bot.store.pending_task(message.author.id, guild_id, message.channel.id)

    def is_candidate(self, text: str) -> bool:
        return self.planner.is_candidate(text)

    async def handle_message(self, message: Any) -> bool:
        guild_id = getattr(getattr(message, "guild", None), "id", 0) or 0
        row = self.pending_for(message)
        pending_capability = str(row["capability"]) if row else None
        pending_arguments = json.loads(row["arguments"]) if row else None
        plan = self.planner.plan(message.content, pending_capability, pending_arguments)
        if not plan.capability and not plan.cancel:
            return False
        if plan.cancel:
            if row:
                self.bot.store.finish_pending_task(str(row["task_id"]), "cancelled")
                await self._reply(message, "Cancelled that pending task.")
            return True
        if plan.capability == "code_change":
            await self._reply(message, "That would be a development change to Mimi's source code, not a runtime action I can perform from Discord.")
            return True
        if plan.missing:
            if row:
                self.bot.store.update_pending_task(str(row["task_id"]), plan.arguments, list(plan.missing))
            else:
                task_id = uuid.uuid4().hex
                self.bot.store.create_pending_task(task_id, message.author.id, guild_id, message.channel.id,
                                                   plan.capability, plan.arguments, list(plan.missing),
                                                   (datetime.now(timezone.utc) + timedelta(seconds=MAX_PENDING_SECONDS)).isoformat(),
                                                   f"pending:{task_id}")
            await self._reply(message, self._clarification(plan))
            return True
        capability = self.registry.get(plan.capability)
        if capability is None:
            await self._reply(message, "I can't perform that action because it isn't registered.")
            return True
        task_key = str(row["task_id"]) if row else f"message:{message.id}"
        if not self.bot.store.claim_agent_execution(task_key, capability.name):
            await self._reply(message, "I already handled that request, so I won't duplicate it.")
            return True
        try:
            result = await capability.execute(self, plan.arguments, message)
        except (discord.Forbidden, discord.HTTPException, OSError, ValueError) as exc:
            log.warning("capability execution failed capability=%s reason=%s", capability.name, type(exc).__name__)
            result = CapabilityResult(False, "I couldn't complete that action because Discord rejected it or it was unavailable.")
        if row:
            self.bot.store.finish_pending_task(str(row["task_id"]), "completed" if result.success else "failed")
        await self._reply(message, result.message)
        return True

    @staticmethod
    def _clarification(plan: ActionPlan) -> str:
        labels = {"question": "What should the poll ask?", "options": "Which options should I include? Please give at least two.", "duration": "How long should it stay open? Use a whole number of hours from 1 to 168.",
                  "valid poll question/options": "The poll question/options are too long or numerous for Discord. Please shorten them.",
                  "follow-up message": "What should I send?", "delay": "How long should I wait?", "delay between 1 minute and 7 days": "Use a delay between 1 minute and 7 days.", "message content": "What message should I send?"}
        return " ".join(labels[item] for item in plan.missing)

    async def _reply(self, message: Any, content: str) -> None:
        await message.reply(content[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    @staticmethod
    def _channel_permission(channel: Any, bot: Any) -> bool:
        user = getattr(bot, "user", None)
        if user is None or not hasattr(channel, "permissions_for"):
            return True
        permissions = channel.permissions_for(user)
        return bool(getattr(permissions, "send_messages", False))

    @staticmethod
    def _requester_can_view(channel: Any, message: Any) -> bool:
        if not hasattr(channel, "permissions_for"):
            return True
        permissions = channel.permissions_for(message.author)
        return bool(getattr(permissions, "view_channel", True))

    async def _send_message(self, _core: Any, args: dict[str, Any], message: Any) -> CapabilityResult:
        channel = message.channel
        destination_id = args.get("destination_id")
        if destination_id is not None:
            guild = getattr(message, "guild", None)
            channel = guild.get_channel(int(destination_id)) if guild and hasattr(guild, "get_channel") else None
            if channel is None:
                return CapabilityResult(False, "I couldn't access that destination channel.")
        if not self._channel_permission(channel, self.bot):
            return CapabilityResult(False, "I don't have permission to send messages there.")
        if not self._requester_can_view(channel, message):
            return CapabilityResult(False, "You aren't authorized to use that destination channel.")
        content = str(args.get("content", "")).strip()
        if not content or len(content) > 2000:
            return CapabilityResult(False, "The message must be between 1 and 2000 characters.")
        sent = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
        return CapabilityResult(True, f"Sent it successfully (message ID {getattr(sent, 'id', 'unknown')}).", {"message_id": getattr(sent, "id", None)})

    async def _create_poll(self, _core: Any, args: dict[str, Any], message: Any) -> CapabilityResult:
        if not getattr(message, "guild", None):
            return CapabilityResult(False, "Native polls are only available in a server channel.")
        if args.get("invalid"):
            return CapabilityResult(False, "That poll does not fit Discord's supported question, option, or duration limits.")
        channel = message.channel
        if not self._channel_permission(channel, self.bot):
            return CapabilityResult(False, "I don't have permission to create a poll in this channel.")
        if not self._requester_can_view(channel, message):
            return CapabilityResult(False, "You aren't authorized to create a poll there.")
        duration = int(args.get("duration_seconds") or 3600)
        poll = discord.Poll(str(args["question"]), timedelta(seconds=duration))
        for option in args["options"]:
            poll.add_answer(text=str(option))
        sent = await channel.send(poll=poll, allowed_mentions=discord.AllowedMentions.none())
        return CapabilityResult(True, f"Poll created successfully (message ID {getattr(sent, 'id', 'unknown')}).", {"message_id": getattr(sent, "id", None)})

    async def _schedule_followup(self, _core: Any, args: dict[str, Any], message: Any) -> CapabilityResult:
        if not getattr(message, "guild", None):
            return CapabilityResult(False, "Scheduled follow-ups currently require a server channel.")
        guild_id = message.guild.id
        if self.bot.store.count_scheduled_tasks(message.author.id, guild_id) >= MAX_SCHEDULES_PER_SCOPE:
            return CapabilityResult(False, "You already have the maximum number of pending follow-ups in this server.")
        seconds = int(args["delay_seconds"])
        if seconds < 60 or seconds > MAX_SCHEDULE_SECONDS:
            return CapabilityResult(False, "Follow-ups must be scheduled between 1 minute and 7 days ahead.")
        task_id = uuid.uuid4().hex
        due = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        if not self.bot.store.create_scheduled_task(task_id, message.author.id, guild_id, message.channel.id,
                                                    str(args["content"]), due.isoformat(), f"schedule:{task_id}"):
            return CapabilityResult(False, "I couldn't save that follow-up safely.")
        return CapabilityResult(True, f"Okay, I'll post that follow-up in about {seconds // 60} minute(s).", {"task_id": task_id})
