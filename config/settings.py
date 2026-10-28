from __future__ import annotations

import os
import logging
import string
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("mimi.settings")


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
        log.warning("Invalid integer configuration %s; using safe default", name)
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        log.warning("Invalid numeric configuration %s; using safe default", name)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    log.warning("Invalid boolean configuration %s; using safe default", name)
    return default


def _safe_inactivity_template(value: str, default: str) -> str:
    try:
        fields = {field for _, field, _, _ in string.Formatter().parse(value) if field}
    except ValueError:
        log.warning("Invalid inactivity template; using safe default")
        return default
    if not fields <= {"owner"}:
        log.warning("Inactivity template contains unsupported placeholders; using safe default")
        return default
    return value[:1900]


@dataclass(slots=True)
class Settings:
    base_dir: Path
    discord_token: str = ""
    xkiro_api_key: str = ""
    xkiro_base_url: str = "https://api.xkiro.com/v1"
    primary_model: str = "qwen/qwen3.8-max:free"
    fallback_model: str = "qwen/qwen3-max:free"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_fallback_enabled: bool = True
    groq_supports_vision: bool = False
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
    bot_timezone: str = "Asia/Kolkata"
    daily_token_budget: int = 1_000_000
    budget_safety_margin: float = 0.85
    budget_warning_fraction: float = 0.75
    budget_low_fraction: float = 0.60
    max_concurrent_requests: int = 2
    max_web_searches_per_day: int = 10
    max_vision_requests_per_day: int = 50
    max_web_search_results: int = 5
    vision_max_attachment_bytes: int = 5 * 1024 * 1024
    max_relevant_memories: int = 4
    inactivity_enabled: bool = False
    inactivity_owner_id: int = 0
    inactivity_guild_id: int = 0
    inactivity_channel_id: int = 0
    inactivity_threshold_hours: float = 12.0
    inactivity_ping_cooldown_hours: float = 24.0
    inactivity_template: str = "Where did you vanish to, {owner}? Mimi was about to file a tiny missing-person report."
    inactivity_check_interval_seconds: float = 900.0
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
    multi_bot_response_creativity: float = 0.7
    multi_bot_typical_reply_length: int = 220
    multi_bot_opener_cooldown_seconds: float = 604800.0
    multi_bot_topic_repeat_protection: bool = True
    multi_bot_reply_cooldown_seconds: float = 5.0
    multi_bot_natural_end_enabled: bool = True
    multi_bot_check_interval_seconds: float = 60.0
    database_path: Path = Path("data/mimi.sqlite3")
    personality_prompt: str = ""

    @classmethod
    def load(cls, base_dir: Path) -> "Settings":
        load_dotenv(base_dir / ".env")
        probability = min(1.0, max(0.0, _env_float("RANDOM_RESPONSE_PROBABILITY", 0.02)))
        personality_path = base_dir / "config" / "personality.md"
        try:
            personality_prompt = personality_path.read_text(encoding="utf-8")[:30000].strip()
        except OSError:
            personality_prompt = ""
        return cls(
            base_dir=base_dir,
            discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
            xkiro_api_key=os.getenv("XKIRO_API_KEY", "").strip(),
            xkiro_base_url=os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1").rstrip("/"),
            primary_model=os.getenv("XKIRO_PRIMARY_MODEL", "qwen/qwen3.8-max:free"),
            fallback_model=os.getenv("XKIRO_FALLBACK_MODEL", "qwen/qwen3-max:free"),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
            groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
            groq_fallback_enabled=os.getenv("GROQ_FALLBACK_ENABLED", "true").lower() in {"1", "true", "yes"},
            groq_supports_vision=os.getenv("GROQ_SUPPORTS_VISION", "false").lower() in {"1", "true", "yes"},
            owner_ids=_csv_ints(os.getenv("OWNER_DISCORD_IDS", "")),
            memory_never_expire_user_ids=_csv_ints(os.getenv("MEMORY_NEVER_EXPIRE_USER_IDS", "")),
            excluded_channel_ids=_csv_ints(os.getenv("EXCLUDED_CHANNEL_IDS", "")),
            random_probability=probability,
            user_cooldown_seconds=max(0.0, _env_float("USER_COOLDOWN_SECONDS", 8)),
            channel_cooldown_seconds=max(0.0, _env_float("CHANNEL_COOLDOWN_SECONDS", 2)),
            memory_expiry_days=max(1, _env_int("MEMORY_EXPIRY_DAYS", 30)),
            max_context_messages=max(2, _env_int("MAX_CONTEXT_MESSAGES", 12)),
            max_context_chars=max(1000, _env_int("MAX_CONTEXT_CHARS", 12000)),
            max_input_chars=max(200, _env_int("MAX_INPUT_CHARS", 4000)),
            max_output_tokens=max(64, _env_int("MAX_OUTPUT_TOKENS", 300)),
            request_timeout_seconds=max(5.0, _env_float("XKIRO_TIMEOUT_SECONDS", 25)),
            max_retries=min(4, max(0, _env_int("XKIRO_MAX_RETRIES", 2))),
            vision_default=_env_bool("VISION_DEFAULT_ENABLED", True),
            bot_timezone=os.getenv("BOT_TIMEZONE", "Asia/Kolkata").replace("Asia/Calcutta", "Asia/Kolkata"),
            daily_token_budget=max(1000, _env_int("DAILY_TOKEN_BUDGET", 1000000)),
            budget_safety_margin=min(0.99, max(0.5, _env_float("BUDGET_SAFETY_MARGIN", 0.85))),
            budget_warning_fraction=min(0.95, max(0.1, _env_float("BUDGET_WARNING_FRACTION", 0.75))),
            budget_low_fraction=min(0.9, max(0.05, _env_float("BUDGET_LOW_FRACTION", 0.60))),
            max_concurrent_requests=min(8, max(1, _env_int("MAX_CONCURRENT_REQUESTS", 2))),
            max_web_searches_per_day=max(0, _env_int("MAX_WEB_SEARCHES_PER_DAY", 10)),
            max_vision_requests_per_day=max(0, _env_int("MAX_VISION_REQUESTS_PER_DAY", 50)),
            max_web_search_results=min(10, max(1, _env_int("MAX_WEB_SEARCH_RESULTS", 5))),
            vision_max_attachment_bytes=min(5 * 1024 * 1024, max(64 * 1024, _env_int("VISION_MAX_ATTACHMENT_BYTES", 5 * 1024 * 1024))),
            max_relevant_memories=min(12, max(1, _env_int("MAX_RELEVANT_MEMORIES", 4))),
            inactivity_enabled=_env_bool("INACTIVITY_PING_ENABLED", False),
            inactivity_owner_id=_env_int("INACTIVITY_OWNER_ID", 0),
            inactivity_guild_id=_env_int("INACTIVITY_GUILD_ID", 0),
            inactivity_channel_id=_env_int("INACTIVITY_CHANNEL_ID", 0),
            inactivity_threshold_hours=max(1.0, _env_float("INACTIVITY_THRESHOLD_HOURS", 12)),
            inactivity_ping_cooldown_hours=max(1.0, _env_float("INACTIVITY_PING_COOLDOWN_HOURS", 24)),
            inactivity_template=_safe_inactivity_template(os.getenv("INACTIVITY_TEMPLATE", "Where did you vanish to, {owner}? Mimi was about to file a tiny missing-person report."), "Where did you vanish to, {owner}? Mimi was about to file a tiny missing-person report."),
            inactivity_check_interval_seconds=min(3600.0, max(60.0, _env_float("INACTIVITY_CHECK_INTERVAL_SECONDS", 900))),
            reaction_library_dir=base_dir / os.getenv("REACTION_LIBRARY_DIR", "config/reactions"),
            reaction_probability=min(1.0, max(0.0, float(os.getenv("REACTION_PROBABILITY", "0.12")))),
            reaction_highlight_probability=min(1.0, max(0.0, float(os.getenv("REACTION_HIGHLIGHT_PROBABILITY", "0.30")))),
            reaction_cooldown_seconds=max(0.0, float(os.getenv("REACTION_COOLDOWN_SECONDS", "45"))),
            reaction_repeat_window=min(50, max(1, int(os.getenv("REACTION_REPEAT_WINDOW", "6")))),
            reaction_max_file_bytes=min(8 * 1024 * 1024, max(1024, _env_int("REACTION_MAX_FILE_BYTES", 8 * 1024 * 1024))),
            moderation_alert_channel_id=int(os.getenv("MODERATION_ALERT_CHANNEL_ID", "0")),
            moderation_alert_keywords=_csv_strings(os.getenv("MODERATION_ALERT_KEYWORDS", "scam,phishing,doxx,raid")),
            multi_bot_enabled=_env_bool("MULTI_BOT_ENABLED", False),
            multi_bot_chromix_id=_env_int("MULTI_BOT_CHROMIX_ID", 1547663515077185711),
            multi_bot_blaze_id=_env_int("MULTI_BOT_BLAZE_ID", 1563544804468723884),
            multi_bot_channel_id=_env_int("MULTI_BOT_CHANNEL_ID", 1564399737224954047),
            multi_bot_initiation_probability=min(1.0, max(0.0, _env_float("MULTI_BOT_INITIATION_PROBABILITY", 0.02))),
            multi_bot_cooldown_seconds=max(0.0, _env_float("MULTI_BOT_COOLDOWN_SECONDS", 21600)),
            multi_bot_quiet_seconds=max(0.0, _env_float("MULTI_BOT_QUIET_SECONDS", 600)),
            multi_bot_max_messages=min(6, max(3, _env_int("MULTI_BOT_MAX_MESSAGES", 5))),
            multi_bot_inactivity_seconds=max(1.0, _env_float("MULTI_BOT_INACTIVITY_SECONDS", 900)),
            multi_bot_max_duration_seconds=max(60.0, _env_float("MULTI_BOT_MAX_DURATION_SECONDS", 3600)),
            multi_bot_response_creativity=min(1.0, max(0.0, _env_float("MULTI_BOT_RESPONSE_CREATIVITY", 0.7))),
            multi_bot_typical_reply_length=min(600, max(80, _env_int("MULTI_BOT_TYPICAL_REPLY_LENGTH", 220))),
            multi_bot_opener_cooldown_seconds=max(0.0, _env_float("MULTI_BOT_OPENER_COOLDOWN_SECONDS", 604800)),
            multi_bot_topic_repeat_protection=_env_bool("MULTI_BOT_TOPIC_REPEAT_PROTECTION", True),
            multi_bot_reply_cooldown_seconds=max(0.0, _env_float("MULTI_BOT_REPLY_COOLDOWN_SECONDS", 5)),
            multi_bot_natural_end_enabled=_env_bool("MULTI_BOT_NATURAL_END_ENABLED", True),
            multi_bot_check_interval_seconds=min(3600.0, max(15.0, _env_float("MULTI_BOT_CHECK_INTERVAL_SECONDS", 60))),
            database_path=base_dir / os.getenv("DATABASE_PATH", "data/mimi.sqlite3"),
            personality_prompt=personality_prompt,
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
