from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _csv_ints(value: str) -> frozenset[int]:
    result = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            try:
                result.add(int(item))
            except ValueError:
                continue
    return frozenset(result)


def _csv_strings(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return 0


@dataclass(slots=True)
class Settings:
    base_dir: Path
    discord_token: str = ""
    xkiro_api_key: str = ""
    xkiro_base_url: str = "https://api.xkiro.com/v1"
    primary_model: str = "qwen/qwen3.8-max:free"
    fallback_model: str = "qwen/qwen3-max:free"
    owner_ids: frozenset[int] = field(default_factory=frozenset)
    memory_never_expire_user_ids: frozenset[int] = field(default_factory=frozenset)
    excluded_channel_ids: frozenset[int] = field(default_factory=frozenset)
    random_probability: float = 0.02
    user_cooldown_seconds: float = 8.0
    channel_cooldown_seconds: float = 2.0
    memory_expiry_days: int = 30
    max_context_messages: int = 12
    max_context_chars: int = 12000
    max_input_chars: int = 4000
    max_output_tokens: int = 300
    request_timeout_seconds: float = 25.0
    max_retries: int = 2
    vision_default: bool = True
    bot_timezone: str = "Asia/Calcutta"
    daily_token_budget: int = 1_000_000
    budget_safety_margin: float = 0.85
    budget_warning_fraction: float = 0.75
    budget_low_fraction: float = 0.60
    max_concurrent_requests: int = 2
    max_web_searches_per_day: int = 10
    max_vision_requests_per_day: int = 50
    inactivity_enabled: bool = False
    inactivity_owner_id: int = 0
    inactivity_guild_id: int = 0
    inactivity_channel_id: int = 0
    inactivity_threshold_hours: float = 12.0
    inactivity_ping_cooldown_hours: float = 24.0
    inactivity_template: str = "Where did you vanish to, {owner}? Mimi was about to file a tiny missing-person report."
    reaction_library_dir: Path = Path("config/reactions")
    reaction_probability: float = 0.12
    reaction_highlight_probability: float = 0.30
    reaction_cooldown_seconds: float = 45.0
    reaction_repeat_window: int = 6
    reaction_max_file_bytes: int = 8 * 1024 * 1024
    moderation_alert_channel_id: int = 0
    moderation_alert_keywords: tuple[str, ...] = ("scam", "phishing", "doxx", "raid")
    multi_bot_enabled: bool = False
    multi_bot_chromix_id: int = 1547663515077185711
    multi_bot_blaze_id: int = 1563544804468723884
    multi_bot_channel_id: int = 1564399737224954047
    multi_bot_initiation_probability: float = 0.02
    multi_bot_cooldown_seconds: float = 21600.0
    multi_bot_quiet_seconds: float = 600.0
    multi_bot_max_messages: int = 5
    multi_bot_inactivity_seconds: float = 900.0
    multi_bot_max_duration_seconds: float = 3600.0
    database_path: Path = Path("data/mimi.sqlite3")

    @classmethod
    def load(cls, base_dir: Path) -> "Settings":
        load_dotenv(base_dir / ".env")
        probability = min(1.0, max(0.0, float(os.getenv("RANDOM_RESPONSE_PROBABILITY", "0.02"))))
        return cls(
            base_dir=base_dir,
            discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
            xkiro_api_key=os.getenv("XKIRO_API_KEY", "").strip(),
            xkiro_base_url=os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1").rstrip("/"),
            primary_model=os.getenv("XKIRO_PRIMARY_MODEL", "qwen/qwen3.8-max:free"),
            fallback_model=os.getenv("XKIRO_FALLBACK_MODEL", "qwen/qwen3-max:free"),
            owner_ids=_csv_ints(os.getenv("OWNER_DISCORD_IDS", "")),
            memory_never_expire_user_ids=_csv_ints(os.getenv("MEMORY_NEVER_EXPIRE_USER_IDS", "")),
            excluded_channel_ids=_csv_ints(os.getenv("EXCLUDED_CHANNEL_IDS", "")),
            random_probability=probability,
            user_cooldown_seconds=max(0.0, float(os.getenv("USER_COOLDOWN_SECONDS", "8"))),
            channel_cooldown_seconds=max(0.0, float(os.getenv("CHANNEL_COOLDOWN_SECONDS", "2"))),
            memory_expiry_days=max(1, int(os.getenv("MEMORY_EXPIRY_DAYS", "30"))),
            max_context_messages=max(2, int(os.getenv("MAX_CONTEXT_MESSAGES", "12"))),
            max_context_chars=max(1000, int(os.getenv("MAX_CONTEXT_CHARS", "12000"))),
            max_input_chars=max(200, int(os.getenv("MAX_INPUT_CHARS", "4000"))),
            max_output_tokens=max(64, int(os.getenv("MAX_OUTPUT_TOKENS", "300"))),
            request_timeout_seconds=max(5.0, float(os.getenv("XKIRO_TIMEOUT_SECONDS", "25"))),
            max_retries=min(4, max(0, int(os.getenv("XKIRO_MAX_RETRIES", "2")))),
            vision_default=os.getenv("VISION_DEFAULT_ENABLED", "true").lower() in {"1", "true", "yes"},
            bot_timezone=os.getenv("BOT_TIMEZONE", "Asia/Calcutta"),
            daily_token_budget=max(1000, int(os.getenv("DAILY_TOKEN_BUDGET", "1000000"))),
            budget_safety_margin=min(0.99, max(0.5, float(os.getenv("BUDGET_SAFETY_MARGIN", "0.85")))),
            budget_warning_fraction=min(0.95, max(0.1, float(os.getenv("BUDGET_WARNING_FRACTION", "0.75")))),
            budget_low_fraction=min(0.9, max(0.05, float(os.getenv("BUDGET_LOW_FRACTION", "0.60")))),
            max_concurrent_requests=min(8, max(1, int(os.getenv("MAX_CONCURRENT_REQUESTS", "2")))),
            max_web_searches_per_day=max(0, int(os.getenv("MAX_WEB_SEARCHES_PER_DAY", "10"))),
            max_vision_requests_per_day=max(0, int(os.getenv("MAX_VISION_REQUESTS_PER_DAY", "50"))),
            inactivity_enabled=os.getenv("INACTIVITY_PING_ENABLED", "false").lower() in {"1", "true", "yes"},
            inactivity_owner_id=int(os.getenv("INACTIVITY_OWNER_ID", "0")),
            inactivity_guild_id=int(os.getenv("INACTIVITY_GUILD_ID", "0")),
            inactivity_channel_id=int(os.getenv("INACTIVITY_CHANNEL_ID", "0")),
            inactivity_threshold_hours=max(1.0, float(os.getenv("INACTIVITY_THRESHOLD_HOURS", "12"))),
            inactivity_ping_cooldown_hours=max(1.0, float(os.getenv("INACTIVITY_PING_COOLDOWN_HOURS", "24"))),
            inactivity_template=os.getenv("INACTIVITY_TEMPLATE", "Where did you vanish to, {owner}? Mimi was about to file a tiny missing-person report."),
            reaction_library_dir=base_dir / os.getenv("REACTION_LIBRARY_DIR", "config/reactions"),
            reaction_probability=min(1.0, max(0.0, float(os.getenv("REACTION_PROBABILITY", "0.12")))),
            reaction_highlight_probability=min(1.0, max(0.0, float(os.getenv("REACTION_HIGHLIGHT_PROBABILITY", "0.30")))),
            reaction_cooldown_seconds=max(0.0, float(os.getenv("REACTION_COOLDOWN_SECONDS", "45"))),
            reaction_repeat_window=min(50, max(1, int(os.getenv("REACTION_REPEAT_WINDOW", "6")))),
            reaction_max_file_bytes=min(8 * 1024 * 1024, max(1024, int(os.getenv("REACTION_MAX_FILE_BYTES", str(8 * 1024 * 1024))))),
            moderation_alert_channel_id=int(os.getenv("MODERATION_ALERT_CHANNEL_ID", "0")),
            moderation_alert_keywords=_csv_strings(os.getenv("MODERATION_ALERT_KEYWORDS", "scam,phishing,doxx,raid")),
            multi_bot_enabled=os.getenv("MULTI_BOT_ENABLED", "false").lower() in {"1", "true", "yes"},
            multi_bot_chromix_id=_env_int("MULTI_BOT_CHROMIX_ID", 1547663515077185711),
            multi_bot_blaze_id=_env_int("MULTI_BOT_BLAZE_ID", 1563544804468723884),
            multi_bot_channel_id=_env_int("MULTI_BOT_CHANNEL_ID", 1564399737224954047),
            multi_bot_initiation_probability=min(1.0, max(0.0, float(os.getenv("MULTI_BOT_INITIATION_PROBABILITY", "0.02")))),
            multi_bot_cooldown_seconds=max(0.0, float(os.getenv("MULTI_BOT_COOLDOWN_SECONDS", "21600"))),
            multi_bot_quiet_seconds=max(0.0, float(os.getenv("MULTI_BOT_QUIET_SECONDS", "600"))),
            multi_bot_max_messages=min(6, max(3, int(os.getenv("MULTI_BOT_MAX_MESSAGES", "5")))),
            multi_bot_inactivity_seconds=max(1.0, float(os.getenv("MULTI_BOT_INACTIVITY_SECONDS", "900"))),
            multi_bot_max_duration_seconds=max(60.0, float(os.getenv("MULTI_BOT_MAX_DURATION_SECONDS", "3600"))),
            database_path=base_dir / os.getenv("DATABASE_PATH", "data/mimi.sqlite3"),
        )

    def validate_runtime(self) -> list[str]:
        errors = []
        if not self.discord_token:
            errors.append("DISCORD_TOKEN is missing")
        if not self.xkiro_api_key:
            errors.append("XKIRO_API_KEY is missing")
        if not self.owner_ids:
            errors.append("OWNER_DISCORD_IDS is empty")
        return errors
