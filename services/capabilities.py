from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Capability:
    identifier: str
    name: str
    description: str
    implemented: bool
    enabled: bool
    available: bool
    limitation: str = ""

def build_capabilities(settings, provider, *, vision_enabled: bool, reaction_assets: bool) -> tuple[Capability, ...]:
    groq_ready = bool(getattr(provider, "groq_configured", False))
    return (
        Capability("discord_chat", "Discord chat", "Reply to permitted Discord messages and DMs.", True, True, True, "Mention and cooldown protections apply."),
        Capability("memory", "Scoped memory", "Save, update, view, and delete useful memories in the current user/server scope.", True, True, True, "Memory is not the same as unsupplied conversation history."),
        Capability("xkiro", "xKiro AI", f"Primary AI provider using model {settings.primary_model}.", True, bool(settings.xkiro_api_key), bool(settings.xkiro_api_key), "Unavailable until XKIRO_API_KEY is configured."),
        Capability("groq_fallback", "Groq fallback", f"One-attempt fallback using model {settings.groq_model}.", True, bool(settings.groq_fallback_enabled), groq_ready, "Optional; only used for eligible transient xKiro failures."),
        Capability("local_reactions", "Local GIF reactions", "Select and attach validated local reaction assets.", True, True, reaction_assets, "Only configured local assets are sent; no image generation."),
        Capability("vision", "Image understanding", "Analyze approved Discord image attachments when enabled and provider-supported.", True, bool(vision_enabled), bool(vision_enabled and settings.xkiro_api_key), "Size, daily-budget, and provider capability limits apply."),
        Capability("multi_bot", "Allowlisted multi-bot conversations", "Bounded conversations with configured bot IDs in one configured channel.", True, bool(settings.multi_bot_enabled), bool(settings.multi_bot_enabled), "Names never authorize participants."),
        Capability("web_search", "Provider web search", "Optional current-information search through the configured xKiro feature.", True, True, bool(settings.xkiro_api_key), "Not used for ordinary messages and unavailable on Groq fallback."),
        Capability("owner_dashboard", "Owner dashboard", "Owner-only settings, diagnostics, and runtime controls.", True, True, bool(settings.owner_ids), "Authorization is enforced by Discord user ID."),
    )

def capability_prompt(capabilities: tuple[Capability, ...]) -> str:
    lines = []
    for item in capabilities:
        state = "available" if item.available and item.enabled else "disabled" if not item.enabled else "unavailable"
        line = f"- {item.name} ({state}): {item.description}"
        if item.limitation:
            line += f" Limitation: {item.limitation}"
        lines.append(line)
    return "\n".join(lines)
