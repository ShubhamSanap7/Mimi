# Mimi runtime settings inventory

`services/runtime_settings.py` is the authoritative registry used by `/dashboard`.
The registry is loaded in this order:

1. Built-in dataclass defaults in `config/settings.py`.
2. Environment values from `.env` (environment wins over built-in defaults).
3. Persisted, validated SQLite dashboard overrides (overrides win over environment values).

The dashboard currently exposes 63 eligible settings in these categories:

- Personality and responses: personality prompt, response limits, vision default, exclusions, random replies, and cooldowns.
- Multi-bot conversations: participant/channel IDs, enablement, quiet period, initiation/cooldowns, turn/duration limits, topic and duplicate protection, pacing, creativity, reply length, and task interval.
- GIFs and reactions: probabilities, cooldown, recent-asset window, and upload size.
- Memory and privacy: expiry, protected IDs, context limits, and relevant-memory count.
- AI and token budgets: output budgets, budget thresholds, model choices, Groq enablement/vision capability, search/vision limits, search result count, and concurrency.
- Moderation and safety: human-review channel/keywords and owner inactivity feature values.
- Commands and scheduled tasks: inactivity and multi-bot scheduler intervals.
- Status and diagnostics: timezone, provider timeout, and retry count.
- Storage and resource limits: vision attachment size.

Each registry entry defines its type, safe range or choices, description, and whether it
applies live. Changes are recorded in SQLite audit metadata using the owner ID and
timestamp; secrets and full personality text are not recorded.

The following are deliberately excluded from Discord editing:

- `DISCORD_TOKEN`, `XKIRO_API_KEY`, and `GROQ_API_KEY`: secret credentials; environment-only.
- `OWNER_DISCORD_IDS`: authorization invariant.
- Provider base URLs: secret-bearing routing configuration requiring host review.
- `REACTION_LIBRARY_DIR`, `DATABASE_PATH`, and `base_dir`: host filesystem paths.

These exclusions are asserted by `tests/test_dashboard.py`. Fixed safety behavior such
as deny-all mentions and duplicate-message protection is visible as a non-editable
dashboard item, but cannot be disabled.
