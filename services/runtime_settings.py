from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Callable

from config.settings import Settings
from database.store import Store


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    category: str
    label: str
    description: str
    kind: str
    minimum: float | int | None = None
    maximum: float | int | None = None
    live: bool = True
    editable: bool = True
    choices: tuple[str, ...] = ()


def _specs() -> tuple[SettingSpec, ...]:
    return (
        SettingSpec("personality_prompt", "Personality and responses", "Personality instructions", "Editable system personality text; edited through bounded Discord modal chunks and applied immediately.", "long_text", 0, 16000),
        SettingSpec("max_output_tokens", "Personality and responses", "Max output tokens", "Upper bound for ordinary AI replies.", "int", 64, 2000),
        SettingSpec("max_input_chars", "Personality and responses", "Input characters", "Maximum user text sent to the model.", "int", 200, 20000),
        SettingSpec("vision_default", "Personality and responses", "Vision enabled", "Allow approved Discord image attachments to be sent to the vision model.", "bool"),
        SettingSpec("excluded_channel_ids", "Personality and responses", "Excluded channel IDs", "Comma-separated channels where Mimi will not answer.", "csv_ints"),
        SettingSpec("random_probability", "Personality and responses", "Random reply probability", "Chance of answering an unmentioned server message.", "float", 0, 1),
        SettingSpec("user_cooldown_seconds", "Personality and responses", "User cooldown", "Minimum time between AI replies for one user.", "float", 0, 3600),
        SettingSpec("channel_cooldown_seconds", "Personality and responses", "Channel cooldown", "Minimum time between AI replies in one channel.", "float", 0, 3600),
        SettingSpec("multi_bot_enabled", "Multi-bot conversations", "Enabled", "Allow the bounded multi-bot scheduler to initiate conversations.", "bool"),
        SettingSpec("multi_bot_chromix_id", "Multi-bot conversations", "Chromix user ID", "Discord user ID; names are never used for authorization.", "int", 0, 2**63 - 1),
        SettingSpec("multi_bot_blaze_id", "Multi-bot conversations", "Blaze user ID", "Discord user ID; names are never used for authorization.", "int", 0, 2**63 - 1),
        SettingSpec("multi_bot_channel_id", "Multi-bot conversations", "Conversation channel ID", "Only this channel may be used.", "int", 0, 2**63 - 1),
        SettingSpec("multi_bot_quiet_seconds", "Multi-bot conversations", "Quiet-channel timeout", "Required observed quiet period before initiation.", "float", 0, 86400),
        SettingSpec("multi_bot_inactivity_seconds", "Multi-bot conversations", "Conversation inactivity timeout", "Ends an active conversation after no participant activity.", "float", 1, 86400),
        SettingSpec("multi_bot_max_messages", "Multi-bot conversations", "Maximum turns/messages", "Hard bound on Mimi replies per conversation.", "int", 3, 6),
        SettingSpec("multi_bot_max_duration_seconds", "Multi-bot conversations", "Maximum duration", "Hard duration bound for one conversation.", "float", 60, 86400),
        SettingSpec("multi_bot_cooldown_seconds", "Multi-bot conversations", "Conversation cooldown", "Minimum time between initiated conversations.", "float", 0, 604800),
        SettingSpec("multi_bot_initiation_probability", "Multi-bot conversations", "Initiation probability", "Chance checked after the quiet period.", "float", 0, 1),
        SettingSpec("multi_bot_response_creativity", "Multi-bot conversations", "Response creativity", "Temperature used for bounded multi-bot replies.", "float", 0, 1),
        SettingSpec("multi_bot_typical_reply_length", "Multi-bot conversations", "Typical reply length", "Approximate character target for multi-bot replies.", "int", 80, 600),
        SettingSpec("multi_bot_opener_cooldown_seconds", "Multi-bot conversations", "Opener cooldown", "Do not reuse an opening question for this period.", "float", 0, 2_592_000),
        SettingSpec("multi_bot_topic_repeat_protection", "Multi-bot conversations", "Topic repetition protection", "Avoid starting a recently covered topic.", "bool"),
        SettingSpec("multi_bot_reply_cooldown_seconds", "Multi-bot conversations", "Reply pacing cooldown", "Minimum time between Mimi replies in one active exchange.", "float", 0, 300),
        SettingSpec("multi_bot_natural_end_enabled", "Multi-bot conversations", "Natural ending behavior", "Allow concise model-led endings and stop markers.", "bool"),
        SettingSpec("multi_bot_duplicate_protection", "Multi-bot conversations", "Duplicate-message protection", "Each Discord message ID is processed at most once.", "fixed", live=True, editable=False),
        SettingSpec("reaction_probability", "GIFs and reactions", "Reaction probability", "Chance of an eligible automatic local reaction.", "float", 0, 1),
        SettingSpec("reaction_highlight_probability", "GIFs and reactions", "Highlight probability", "Higher chance for strong moods such as victories.", "float", 0, 1),
        SettingSpec("reaction_cooldown_seconds", "GIFs and reactions", "Reaction cooldown", "Minimum time between automatic reactions per channel.", "float", 0, 86400),
        SettingSpec("reaction_repeat_window", "GIFs and reactions", "Recent asset window", "Number of recent assets avoided.", "int", 1, 50),
        SettingSpec("reaction_max_file_bytes", "GIFs and reactions", "Maximum reaction file size", "Upload validation limit for local reaction files.", "int", 1024, 8 * 1024 * 1024),
        SettingSpec("memory_expiry_days", "Memory and privacy", "Memory expiry days", "Inactive ordinary memories expire after this many days.", "int", 1, 3650),
        SettingSpec("memory_never_expire_user_ids", "Memory and privacy", "Protected memory user IDs", "Comma-separated IDs whose memories do not auto-expire; deletion commands remain available.", "csv_ints"),
        SettingSpec("max_context_messages", "Memory and privacy", "Context messages", "Maximum recent messages retained in memory; restart required for existing history buffers.", "int", 2, 50, live=False),
        SettingSpec("max_context_chars", "Memory and privacy", "Context characters", "Maximum recent context characters sent to the model.", "int", 1000, 50000),
        SettingSpec("daily_token_budget", "AI and token budgets", "Daily token budget", "Configured daily input plus output accounting budget.", "int", 1000, 10_000_000),
        SettingSpec("budget_safety_margin", "AI and token budgets", "Budget stop margin", "Stop threshold as a fraction of the daily budget.", "float", 0.5, 0.99),
        SettingSpec("budget_warning_fraction", "AI and token budgets", "Budget warning fraction", "Diagnostic warning threshold.", "float", 0.1, 0.95),
        SettingSpec("budget_low_fraction", "AI and token budgets", "Low-budget fraction", "Threshold that disables optional work.", "float", 0.05, 0.9),
        SettingSpec("primary_model", "AI and token budgets", "Primary model", "Configured xKiro model identifier.", "str", live=True),
        SettingSpec("fallback_model", "AI and token budgets", "Fallback model", "Configured fallback model identifier.", "str", live=True),
        SettingSpec("groq_model", "AI and token budgets", "Groq fallback model", "Model used only after a retryable xKiro failure.", "str", live=True),
        SettingSpec("groq_fallback_enabled", "AI and token budgets", "Groq fallback enabled", "Enable the Groq route when a key is configured; no key is ever created by this control.", "bool"),
        SettingSpec("groq_supports_vision", "AI and token budgets", "Groq vision fallback", "Allow image payloads on Groq only when the selected model is known to support vision.", "bool"),
        SettingSpec("max_web_searches_per_day", "AI and token budgets", "Daily web-search limit", "Maximum optional searches per local day.", "int", 0, 1000),
        SettingSpec("max_vision_requests_per_day", "AI and token budgets", "Daily vision limit", "Maximum optional vision requests per local day.", "int", 0, 1000),
        SettingSpec("max_web_search_results", "AI and token budgets", "Search result count", "Maximum result count requested from the provider search feature.", "int", 1, 10),
        SettingSpec("max_concurrent_requests", "AI and token budgets", "Concurrent AI requests", "Maximum simultaneous provider requests; restart required for the semaphore.", "int", 1, 8, live=False),
        SettingSpec("vision_max_attachment_bytes", "Storage and resource limits", "Vision attachment limit", "Maximum approved Discord image attachment size.", "int", 64 * 1024, 5 * 1024 * 1024),
        SettingSpec("max_relevant_memories", "Memory and privacy", "Relevant memory count", "Maximum matching memories added to one prompt.", "int", 1, 12),
        SettingSpec("moderation_alert_channel_id", "Moderation and safety", "Alert channel ID", "Human-review channel for configured alert keywords; zero disables alerts.", "int", 0, 2**63 - 1),
        SettingSpec("moderation_alert_keywords", "Moderation and safety", "Moderation keywords", "Comma-separated words that create human-review alerts.", "csv_strings"),
        SettingSpec("inactivity_enabled", "Moderation and safety", "Owner inactivity ping", "Enable the existing local-template owner ping.", "bool"),
        SettingSpec("inactivity_threshold_hours", "Moderation and safety", "Owner inactivity threshold", "Hours before the owner ping is eligible.", "float", 1, 168),
        SettingSpec("inactivity_ping_cooldown_hours", "Moderation and safety", "Owner ping cooldown", "Minimum hours between owner pings.", "float", 1, 720),
        SettingSpec("inactivity_owner_id", "Moderation and safety", "Inactivity owner ID", "Discord ID to observe for the existing owner inactivity feature.", "int", 0, 2**63 - 1),
        SettingSpec("inactivity_guild_id", "Moderation and safety", "Inactivity server ID", "Only this server is observed for owner inactivity.", "int", 0, 2**63 - 1),
        SettingSpec("inactivity_channel_id", "Moderation and safety", "Inactivity channel ID", "Only this channel may receive the local-template ping.", "int", 0, 2**63 - 1),
        SettingSpec("inactivity_template", "Moderation and safety", "Inactivity message template", "Local-only template; `{owner}` is replaced with a safe non-notifying ID string.", "str", 1, 1900),
        SettingSpec("inactivity_check_interval_seconds", "Commands and scheduled tasks", "Owner task interval", "How often the owner-inactivity task checks eligibility.", "float", 60, 3600),
        SettingSpec("bot_timezone", "Status and diagnostics", "Bot timezone", "Timezone used for daily accounting and local timestamps.", "str"),
        SettingSpec("request_timeout_seconds", "Status and diagnostics", "Provider timeout", "Provider request timeout; restart required because the client is constructed at startup.", "float", 5, 120, live=False),
        SettingSpec("max_retries", "Status and diagnostics", "Provider retries", "Bounded provider retry count; the provider clients capture this at startup, so restart is required.", "int", 0, 4, live=False),
        SettingSpec("multi_bot_check_interval_seconds", "Commands and scheduled tasks", "Multi-bot task interval", "How often the bounded multi-bot scheduler checks state.", "float", 15, 3600),
    )


EXCLUDED_SETTINGS: dict[str, str] = {
    "discord_token": "secret credential; environment-only",
    "xkiro_api_key": "secret credential; environment-only",
    "groq_api_key": "secret credential; environment-only",
    "owner_ids": "authorization invariant; changing it would undermine dashboard access control",
    "xkiro_base_url": "secret-bearing endpoint; changing it could redirect credentials and requires host review",
    "groq_base_url": "secret-bearing endpoint; changing it could redirect credentials and requires host review",
    "reaction_library_dir": "host filesystem path; dashboard cannot safely write or relocate assets",
    "database_path": "host filesystem path; dashboard cannot safely relocate persistent storage",
    "base_dir": "host filesystem path; implementation detail",
}


class RuntimeSettings:
    """Authoritative registry: environment-loaded Settings, then SQLite overrides."""

    def __init__(self, settings: Settings, store: Store, on_change: Callable[[str], None] | None = None):
        self.settings = settings
        self.store = store
        self.on_change = on_change
        self.specs = {spec.key: spec for spec in _specs()}
        self.revisions: dict[str, int] = defaultdict(int)
        self.environment_defaults = {key: getattr(settings, key) for key in self.specs if hasattr(settings, key)}
        self._load_persisted()

    def _coerce(self, spec: SettingSpec, value: Any) -> Any:
        if spec.kind == "fixed":
            return True
        if spec.kind == "bool":
            if isinstance(value, bool):
                return value
            if str(value).lower() in {"1", "true", "yes", "on"}:
                return True
            if str(value).lower() in {"0", "false", "no", "off"}:
                return False
            raise ValueError("expected true or false")
        if spec.kind == "csv_ints":
            try:
                values = value if isinstance(value, (list, tuple, set, frozenset)) else str(value).split(",")
                result = frozenset(int(item) if not isinstance(item, str) else int(item.strip()) for item in values if str(item).strip())
            except ValueError as exc:
                raise ValueError("expected comma-separated numeric IDs") from exc
            if any(item < 0 or item > 2**63 - 1 for item in result):
                raise ValueError("IDs must be between 0 and 2^63-1")
            return result
        if spec.kind == "csv_strings":
            values = value if isinstance(value, (list, tuple, set, frozenset)) else str(value).split(",")
            result = tuple(str(item).strip().lower() for item in values if str(item).strip())
            if not result:
                raise ValueError("at least one value is required")
            return result
        if spec.kind == "int":
            result: Any = int(value)
        elif spec.kind == "float":
            result = float(value)
        elif spec.kind in {"str", "long_text"}:
            result = str(value).strip()
            if not result:
                if spec.kind == "long_text" and (spec.minimum is None or spec.minimum == 0):
                    return ""
                raise ValueError("value cannot be empty")
            if spec.minimum is not None and len(result) < spec.minimum:
                raise ValueError(f"must contain at least {spec.minimum} characters")
            if spec.maximum is not None and len(result) > spec.maximum:
                raise ValueError(f"must contain at most {spec.maximum} characters")
            return result
        else:
            result = value
        if spec.minimum is not None and result < spec.minimum:
            raise ValueError(f"must be at least {spec.minimum}")
        if spec.maximum is not None and result > spec.maximum:
            raise ValueError(f"must be at most {spec.maximum}")
        return result

    def _load_persisted(self) -> None:
        for key, raw in self.store.runtime_overrides().items():
            if key in self.specs and self.specs[key].editable:
                try:
                    self._apply(key, raw, persist=False)
                except (TypeError, ValueError):
                    self.store.delete_runtime_override(key)

    def _apply(self, key: str, value: Any, *, persist: bool, changed_by: int = 0,
               expected_revision: int | None = None) -> Any:
        spec = self.specs[key]
        if expected_revision is not None and self.revisions[key] != expected_revision:
            raise ValueError("This dashboard value changed elsewhere; refresh before saving.")
        old_value = self.value(key)
        coerced = self._coerce(spec, value)
        setattr(self.settings, key, coerced)
        self.revisions[key] += 1
        if persist:
            stored = sorted(coerced) if isinstance(coerced, (set, frozenset)) else coerced
            self.store.set_runtime_override(key, stored)
        if changed_by and old_value != coerced:
            def audit_value(value: Any) -> Any:
                if key == "personality_prompt":
                    return f"<text length={len(str(value))}>"
                if isinstance(value, str) and len(value) > 200:
                    return value[:200] + "…"
                return value
            self.store.record_setting_audit(changed_by, datetime.now(timezone.utc).isoformat(), key, audit_value(old_value), audit_value(coerced))
        if self.on_change:
            self.on_change(key)
        return coerced

    def set(self, key: str, value: Any, *, changed_by: int = 0, expected_revision: int | None = None) -> Any:
        if key not in self.specs:
            raise KeyError(key)
        if not self.specs[key].editable:
            raise ValueError("this safety setting is fixed")
        return self._apply(key, value, persist=True, changed_by=changed_by, expected_revision=expected_revision)

    def reset(self, key: str, *, changed_by: int = 0, expected_revision: int | None = None) -> Any:
        if key not in self.specs or not self.specs[key].editable:
            raise ValueError("this setting cannot be reset from the dashboard")
        self.store.delete_runtime_override(key)
        return self._apply(key, self.environment_defaults[key], persist=False, changed_by=changed_by, expected_revision=expected_revision)

    def reset_category(self, category: str, *, changed_by: int = 0) -> None:
        keys = [spec.key for spec in self.specs.values() if spec.category == category and spec.editable]
        self.store.clear_runtime_overrides(keys)
        for key in keys:
            self._apply(key, self.environment_defaults[key], persist=False, changed_by=changed_by)

    def reset_all(self, *, changed_by: int = 0) -> None:
        keys = [spec.key for spec in self.specs.values() if spec.editable]
        self.store.clear_runtime_overrides(keys)
        for key in keys:
            self._apply(key, self.environment_defaults[key], persist=False, changed_by=changed_by)

    def value(self, key: str) -> Any:
        if self.specs[key].kind == "fixed":
            return "enabled"
        return getattr(self.settings, key)

    def revision(self, key: str) -> int:
        return self.revisions[key]

    def is_overridden(self, key: str) -> bool:
        return key in self.store.runtime_overrides()

    def specs_for(self, category: str) -> list[SettingSpec]:
        return [spec for spec in self.specs.values() if spec.category == category]

    def categories(self) -> list[str]:
        return list(dict.fromkeys(spec.category for spec in self.specs.values()))

    def inventory(self) -> dict[str, object]:
        return {"editable_or_fixed": list(self.specs.values()), "excluded": dict(EXCLUDED_SETTINGS)}
