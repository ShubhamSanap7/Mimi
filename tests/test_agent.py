import asyncio
from pathlib import Path

from config.settings import Settings
from main import MimiBot
from services.agent import CapabilityRegistry, NaturalLanguagePlanner


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class User:
    def __init__(self, user_id=42):
        self.id = user_id
        self.bot = False


class Guild:
    id = 7


class Channel:
    id = 8

    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return type("Sent", (), {"id": 9001})()


class Message:
    _next = 1

    def __init__(self, content, channel, *, guild=True):
        self.id = Message._next
        Message._next += 1
        self.content = content
        self.author = User()
        self.channel = channel
        self.guild = Guild() if guild else None
        self.replies = []

    async def reply(self, content, **kwargs):
        self.replies.append((content, kwargs))


def make_bot(tmp_path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "agent.sqlite3"
    return MimiBot(settings)


def test_registry_and_strict_planner_reject_unknown_actions():
    planner = NaturalLanguagePlanner()
    assert planner.is_candidate("Mimi, make a poll")
    assert planner.plan("Mimi, make a poll").missing == ("question", "options", "duration")
    assert not planner.is_candidate("What do you think about polls?")
    assert not planner.is_candidate("Mimi, I need to send a message later")
    assert planner.plan("Mimi, add a poll feature").capability == "code_change"
    assert set(CapabilityRegistry().names()) == set()


def test_poll_clarification_continuation_and_native_send(tmp_path):
    bot = make_bot(tmp_path)

    async def run():
        first_channel = Channel()
        first = Message("Mimi, make a poll", first_channel)
        assert await bot.agent.handle_message(first) is True
        assert "poll" in first.replies[0][0].lower()

        question = Message("Which game should we play tonight?", first_channel)
        assert await bot.agent.handle_message(question) is True
        assert "options" in question.replies[0][0].lower()

        options = Message("Minecraft, Valorant, and Free Fire for 1 hour", first_channel)
        assert await bot.agent.handle_message(options) is True
        assert any("poll" in str(kwargs) for _, kwargs in first_channel.sent)
        poll_kwargs = first_channel.sent[0][1]
        assert poll_kwargs["allowed_mentions"].everyone is False
        assert poll_kwargs["poll"].question == "Which game should we play tonight"
        assert options.replies and "created successfully" in options.replies[0][0]
        await bot.close()

    asyncio.run(run())


def test_send_message_is_real_and_mention_safe(tmp_path):
    bot = make_bot(tmp_path)

    async def run():
        channel = Channel()
        message = Message("Mimi, send a message saying @everyone meeting at 8", channel)
        assert await bot.agent.handle_message(message) is True
        assert channel.sent[0][0][0].endswith("meeting at 8")
        assert channel.sent[0][1]["allowed_mentions"].everyone is False
        assert "Sent it successfully" in message.replies[0][0]
        await bot.close()

    asyncio.run(run())


def test_schedule_followup_persists_bounded_task(tmp_path):
    bot = make_bot(tmp_path)

    async def run():
        channel = Channel()
        message = Message("Mimi, remind me in 10 minutes to drink water", channel)
        assert await bot.agent.handle_message(message) is True
        assert "follow-up" in message.replies[0][0]
        assert bot.store.count_scheduled_tasks(42, 7) == 1
        await bot.close()

    asyncio.run(run())
