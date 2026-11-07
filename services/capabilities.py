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
        Capability("discord_chat", "Discord chat", "Reply to permitted guild messages when mentioned, replied to, or otherwise eligible.", True, True, True, "Incoming DMs are disabled."),
        Capability("memory", "Shared guild memory", "Save, update, view, and delete explicitly requested public facts in one shared memory for the current server.", True, True, True, "Personal/private facts are not automatically stored."),
        Capability("xkiro_fallback", "xKiro fallback", f"Fallback provider using model {settings.primary_model}.", True, bool(settings.xkiro_api_key), bool(settings.xkiro_api_key), "Unavailable until XKIRO_API_KEY is configured."),
        Capability("groq_primary", "Groq primary", f"Primary provider using model {settings.groq_model}.", True, bool(settings.groq_fallback_enabled), groq_ready, "Optional; xKiro is used as the fallback."),
        Capability("local_reactions", "Local GIF reactions", "Select and attach validated local reaction assets for explicit GIF requests and occasional contextual reactions.", True, True, reaction_assets, "Only configured local assets are sent; no image generation."),
        Capability("vision", "Image understanding", "Analyze Discord image attachments.", True, False, False, "Disabled by current product configuration."),
        Capability("multi_bot", "Behavior-based bot conversations", "React to ordinary bots and hold bounded conversations only when a bot replies directly to Mimi in the configured channel.", True, bool(settings.multi_bot_enabled), bool(settings.multi_bot_enabled), "There is no participant allowlist; channel restriction, bot identity, cooldowns, and message limits apply."),
        Capability("web_search", "Provider web search", "Optional current-information search through the configured provider.", True, True, bool(settings.xkiro_api_key), "Only supported by the xKiro route; unavailable when Groq handles the request."),
        Capability("owner_diagnostics", "Owner diagnostics", "Owner-only diagnostic slash command.", True, True, bool(settings.owner_ids), "The interactive dashboard and settings panel are disabled."),
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
