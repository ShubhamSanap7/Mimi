from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

from config.settings import Settings
from main import MimiBot
from services.reactions import MAX_REACTION_FILE_BYTES, ReactionLibrary


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_gif(path: Path, color: tuple[int, int, int] = (255, 128, 180)) -> None:
    first = Image.new("RGB", (8, 8), color)
    second = Image.new("RGB", (8, 8), tuple(min(255, value + 10) for value in color))
    first.save(path, format="GIF", save_all=True, append_images=[second], duration=50, loop=0)


def write_png(path: Path, color: tuple[int, int, int] = (128, 180, 255)) -> None:
    Image.new("RGB", (8, 8), color).save(path, format="PNG")


def test_manifest_parsing_and_asset_discovery(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    write_gif(root / "happy.gif")
    (root / "anime").mkdir()
    write_png(root / "anime" / "anime_happy.png")
    library = ReactionLibrary(root)
    payload = library.write_manifest({
        "happy.gif": {"category": "root", "tags": ["happy"], "license_status": "original-local"},
        "anime/anime_happy.png": {"category": "anime", "tags": ["anime", "happy"], "license_status": "unknown"},
    })
    assert library.load_manifest() == payload
    assets = library.discover_assets(library.manifest_metadata())
    assert {asset.relative_path for asset in assets} == {"happy.gif", "anime/anime_happy.png"}
    assert all(asset.valid and asset.sha256 for asset in assets)
    assert payload["summary"]["valid_unique"] == 2


def test_category_matching_and_generic_request_are_local():
    assert ReactionLibrary.request_category("send me a shocked anime GIF") == "shock"
    assert ReactionLibrary.request_category("send me a GIF") == "auto"
    assert ReactionLibrary.request_category("send me a wave") == "wave"
    assert ReactionLibrary.request_category("explain this code") is None
    assert ReactionLibrary.infer_category("I'm having a terrible day") == "sad"
    assert ReactionLibrary.infer_category("Explain this code") is None


def test_automatic_mood_selection_is_contextual_and_suppresses_ambiguous_or_sensitive_text():
    assert ReactionLibrary.automatic_category("That joke was hilarious") == "laughing"
    assert ReactionLibrary.automatic_category("An unexpected tournament victory") == "shock"
    assert ReactionLibrary.automatic_category("An exciting personal achievement") == "excited"
    assert ReactionLibrary.automatic_category("We won the game, let's go!") in {"happy", "gaming_victory", "gaming_clutch", "excited"}
    assert ReactionLibrary.automatic_category("Hi there") is None
    assert ReactionLibrary.automatic_category("Please explain the schedule", "Great question — here is the schedule.") is None
    assert ReactionLibrary.automatic_category("I'm not angry, just tired") is None
    assert ReactionLibrary.automatic_category("yeah right, very funny /s") is None
    assert ReactionLibrary.automatic_category("This is a medical emergency") is None
    exact_distress = "Mimi, I'm having a genuinely rough day and don't really feel like joking right now."
    assert ReactionLibrary.is_serious_context(exact_distress) is True
    assert ReactionLibrary.automatic_category(exact_distress, "I hear you.") is None
    assert ReactionLibrary.is_serious_context("I'm frustrated with this bug") is False


def test_backward_compatible_root_names_are_selectable(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    for name, color in {
        "happy": (255, 128, 180),
        "confused": (128, 180, 255),
        "shock": (255, 200, 80),
        "sad": (100, 140, 255),
        "angry": (235, 90, 90),
    }.items():
        write_gif(root / f"{name}.gif", color)
    library = ReactionLibrary(root)
    assert library.choose("send me a shocked GIF", requested_category="shock").relative_path == "shock.gif"
    assert {asset.relative_path for asset in library.discover_assets()} == {
        "happy.gif", "confused.gif", "shock.gif", "sad.gif", "angry.gif"
    }


def test_invalid_signatures_and_oversized_files_are_rejected(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    (root / "bad.gif").write_bytes(b"not a gif")
    oversized = root / "oversized.gif"
    oversized.write_bytes(b"GIF89a")
    with oversized.open("r+b") as stream:
        stream.seek(MAX_REACTION_FILE_BYTES)
        stream.write(b"x")
    scan = ReactionLibrary(root).scan()
    assert scan["assets"] == []
    assert len(scan["invalid"]) == 2


def test_static_image_disguised_as_gif_is_rejected(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(root / "static.gif", format="GIF")
    result = ReactionLibrary(root).validate_file(root / "static.gif")
    assert result["valid"] is False
    assert result["reason"] == "GIF is not animated"


def test_duplicate_detection_and_safe_paths(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    first = root / "first.gif"
    second = root / "second.gif"
    write_gif(first)
    second.write_bytes(first.read_bytes())
    library = ReactionLibrary(root)
    scan = library.scan()
    assert len(scan["assets"]) == 1
    assert len(scan["duplicates"]) == 1
    assert library.safe_asset_path("../outside.gif") is None
    assert library.validate_file(tmp_path / "outside.gif")["valid"] is False


def test_no_suitable_reaction_and_local_selection_do_not_change_usage(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    write_gif(root / "happy.gif")
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = root
    settings.reaction_probability = 1.0
    bot = MimiBot(settings)
    before = bot.store.usage(bot.date_key())
    assert bot._select_local_reaction("explain this code", force=True) is None
    assert bot._select_local_reaction("yay, thanks", force=True) is not None
    after = bot.store.usage(bot.date_key())
    assert after == before
    asyncio.run(bot.close())


def test_reaction_attachment_and_cooldown_are_local(tmp_path: Path):
    root = tmp_path / "reactions"
    root.mkdir()
    write_gif(root / "happy.gif", (255, 128, 180))
    write_gif(root / "happy_alt.gif", (128, 255, 180))
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = root
    settings.reaction_probability = 1.0
    settings.reaction_cooldown_seconds = 60.0
    bot = MimiBot(settings)
    selected = bot._select_local_reaction("yay", force=True, scope_id=77)
    assert selected is not None

    class Channel:
        id = 77

        def __init__(self):
            self.sent_file = None

        async def send(self, *, file, allowed_mentions):
            self.sent_file = file
            assert allowed_mentions.everyone is False
            assert allowed_mentions.roles is False

    channel = Channel()
    assert asyncio.run(bot._send_local_reaction(channel, selected, scope_id=77)) is True
    assert channel.sent_file.filename == selected.name
    channel.sent_file.close()
    assert bot._select_local_reaction("yay", force=False, scope_id=77) is None
    asyncio.run(bot.close())


def test_full_automatic_reaction_dispatch_after_ai_reply(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = PROJECT_ROOT / "config" / "reactions"
    settings.reaction_probability = 1.0
    settings.reaction_cooldown_seconds = 0.0
    bot = MimiBot(settings)

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class Channel:
        def __init__(self, channel_id=808):
            self.id = channel_id
            self.files = []

        def typing(self):
            return Typing()

        async def send(self, *, file, allowed_mentions):
            assert allowed_mentions.everyone is False
            self.files.append(file)

    class Author:
        id = 42
        bot = False

    class Guild:
        id = 77

    class Message:
        def __init__(self, message_id: int, content: str, channel: Channel):
            self.id = message_id
            self.content = content
            self.channel = channel
            self.author = Author()
            self.guild = Guild()
            self.attachments = []
            self.reference = None
            self.replies = []

        async def reply(self, content, **kwargs):
            assert kwargs["allowed_mentions"].everyone is False
            self.replies.append(content)

    async def fake_complete(messages, *, use_web_search=False, model=None):
        return "Here is a concise reply.", "test", {}, {"input_tokens": 10, "output_tokens": 8, "exact": True}

    async def run():
        bot.provider.complete = fake_complete
        channel = Channel()
        funny = Message(1, "My classroom story was hilarious", channel)
        await bot._generate_reply(funny)
        assert len(channel.files) == 1
        assert funny.replies
        channel.files[0].close()

        ordinary = Message(2, "Please explain the schedule", channel)
        await bot._generate_reply(ordinary)
        assert len(channel.files) == 1

        serious = Message(3, "This is a medical emergency", channel)
        await bot._generate_reply(serious)
        assert len(channel.files) == 1

        distress = Message(5, "Mimi, I'm having a genuinely rough day and don't really feel like joking right now.", channel)
        await bot._generate_reply(distress)
        assert len(channel.files) == 1

        duplicate_channel = Channel(809)
        duplicate = Message(4, "That joke was hilarious", duplicate_channel)
        await bot._generate_reply(duplicate)
        await bot._generate_reply(duplicate)
        assert len(duplicate_channel.files) == 1
        duplicate_channel.files[0].close()
        await bot.close()

    asyncio.run(run())


def test_highlight_moods_get_a_separate_chance_without_reacting_to_ordinary_text(tmp_path: Path, monkeypatch):
    root = tmp_path / "reactions"
    root.mkdir()
    write_gif(root / "laughing.gif")
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = root
    settings.reaction_probability = 0.12
    settings.reaction_highlight_probability = 0.30
    bot = MimiBot(settings)
    monkeypatch.setattr("main.random.random", lambda: 0.20)
    assert bot._select_local_reaction("That classroom story was hilarious", scope_id=1) is not None
    assert bot._select_local_reaction("Please explain the schedule", scope_id=2) is None
    asyncio.run(bot.close())


def test_explicit_gif_requests_dispatch_locally_without_ai(tmp_path: Path):
    settings = Settings.load(PROJECT_ROOT)
    settings.xkiro_api_key = "test-key"
    settings.database_path = tmp_path / "data.sqlite3"
    settings.reaction_library_dir = PROJECT_ROOT / "config" / "reactions"
    settings.user_cooldown_seconds = 0.0
    settings.channel_cooldown_seconds = 0.0
    bot = MimiBot(settings)

    class Channel:
        id = 990

        def __init__(self):
            self.files = []

        async def send(self, *, file, allowed_mentions):
            assert allowed_mentions.everyone is False
            self.files.append(file)

    class Author:
        bot = False

        def __init__(self, user_id):
            self.id = user_id

    class Guild:
        id = 991

    class Message:
        def __init__(self, message_id, content, user_id, channel):
            self.id = message_id
            self.content = content
            self.author = Author(user_id)
            self.guild = Guild()
            self.channel = channel
            self.attachments = []
            self.reference = None
            self.mentions = []

        async def reply(self, *_args, **_kwargs):
            raise AssertionError("an explicit GIF request should not need a text fallback")

    async def unexpected_ai_call(*_args, **_kwargs):
        raise AssertionError("explicit GIF requests must not call the AI provider")

    async def run():
        bot.provider.complete = unexpected_ai_call
        channel = Channel()
        messages = [
            Message(1, "heyy, express how u feel rn with a GIF", 1, channel),
            Message(2, "USE HAPPY GIF", 2, channel),
            Message(3, "send a GIF", 3, channel),
        ]
        for message in messages:
            await bot.handle_message(message)
        assert len(channel.files) == 3
        for file in channel.files:
            file.close()
        await bot.close()

    asyncio.run(run())
