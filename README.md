# Mimi Bot 2.0

Mimi is a lightweight Discord AI chatbot built with `discord.py`, SQLite, and the OpenAI-compatible xKiro API. It is designed for a small Wispbyte instance: no web dashboard, vector database, voice features, or unbounded background workers.

## 1. Install

Use Python 3.11+.

```powershell
cd "D:\Projects\Mimi"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`Pillow` is included for safe local image decoding and manifest validation; it is not used to send media or to call the AI provider.

## 2. Discord setup

Create a bot in the Discord Developer Portal. Enable the **Message Content Intent**. Invite it with the `bot` and `applications.commands` scopes and permissions to view channels, send messages, embed links, and read message history. The bot needs access to every channel where it should answer.

## 3. Environment

Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN`, `XKIRO_API_KEY`, and at least one numeric ID in `OWNER_DISCORD_IDS`. Never commit `.env`. The configured primary and fallback models are tested independently by the owner control panel; the bot automatically attempts the fallback after a primary request failure.

`RANDOM_RESPONSE_PROBABILITY=0.02` means a 2% random response chance. `EXCLUDED_CHANNEL_IDS` disables replies in selected channels. Vision only accepts Discord-hosted image attachments up to 5 MB and can be toggled from `/settings`. Current-information wording such as “latest” or “today” enables xKiro's documented `web_search` flag; Mimi reports when live search was unavailable.

The default daily AI accounting budget is 1,000,000 tokens, with a conservative stop threshold at 85% (`BUDGET_SAFETY_MARGIN`). xKiro `usage.prompt_tokens` and `usage.completion_tokens` are recorded as exact when present; otherwise Mimi records a bounded character-based estimate and labels diagnostics as estimated. Usage is persisted in SQLite and resets by `BOT_TIMEZONE` local date. Search and vision have separate daily caps, requests are concurrency-limited, and low/stop modes disable optional activity or defer AI requests while local commands continue to work.

xKiro remains the primary AI provider. Optional Groq fallback uses `GROQ_API_KEY`, `GROQ_MODEL` (default `llama-3.3-70b-versatile`), and `GROQ_BASE_URL` (default `https://api.groq.com/openai/v1`). Set `GROQ_FALLBACK_ENABLED=false` to disable it. Mimi attempts Groq only once after a retryable xKiro network, timeout, rate-limit, or 5xx failure; permanent authentication and invalid-request failures do not trigger it. Groq fallback does not receive xKiro web-search flags, and image fallback remains disabled unless `GROQ_SUPPORTS_VISION=true` is explicitly configured for a compatible model. Diagnostics shows only configured/unconfigured status and model name, never keys.

To enable the owner inactivity ping, configure `INACTIVITY_PING_ENABLED=true`, `INACTIVITY_OWNER_ID`, `INACTIVITY_GUILD_ID`, and `INACTIVITY_CHANNEL_ID`. Mimi records only the owner's observed messages in that configured server, persists the timestamp, and sends at most one local-template ping after the configured threshold. A missing channel is logged and skipped. This does not infer activity outside messages Mimi can observe.

Reaction media is local-only. The checkout includes 120 verified animated GIFs from real anime scenes under `config/reactions/`, plus the backward-compatible root files `happy.gif`, `confused.gif`, `shock.gif`, `sad.gif`, and `angry.gif`. `manifest.json` records actual hashes, dimensions, frame counts, sizes, tags, pinned source URLs, provenance, and validation results. The source repository's MIT license is recorded separately from the individual media rights, which remain explicitly unknown. Mimi selects assets locally for explicit requests such as “send me a shocked anime GIF”; ordinary replies only get occasional matching reactions, with a per-channel cooldown and recent-file avoidance. Mimi never downloads arbitrary reaction files. Image analysis is separate and uses only approved Discord CDN attachments. For moderation, set `MODERATION_ALERT_CHANNEL_ID` and optionally `MODERATION_ALERT_KEYWORDS`; Mimi only reports matching messages to that human channel and never bans, kicks, or times out users.

Edit `config/personality.md` to change Mimi's voice without changing Python code.

## 4. Run

```powershell
python main.py
```

The bot responds to mentions, replies to Mimi, configured low-probability random triggers, and member-initiated DMs. DM memories use a private scope separate from every server. Per-user and per-channel cooldowns prevent spam. Reply context is fetched from Discord when available. Long messages are split below Discord's limit.

Mimi does not send unsolicited outbound DMs. An inbound DM is answered in that same DM channel; there is no `create_dm`, `user.send`, or background-DM path. Mimi records first-contact state per user and server/DM scope and is instructed—and locally guarded—not to claim prior conversations or DM delivery without supported state or a confirmed send result.

The optional multi-bot conversation feature is disabled by default. To enable it, set `MULTI_BOT_ENABLED=true`; the configured IDs default to Chromix `1547663515077185711`, Blaze `1563544804468723884`, and channel `1564399737224954047`. Mimi verifies each configured ID through Discord's live user/member object and requires `.bot == true`; names and nicknames are never used for authorization. It waits for a quiet channel, uses a low probability and cooldown, avoids recently used opening questions and topics, keeps a bounded temporary summary, paces replies, allows 3–6 Mimi replies, and stops on inactivity, duration, repetition, natural ending, or the message limit. Active state is intentionally memory-only, so a restart cancels it cleanly rather than resuming an unverified conversation. Only the initial opener mention-enables the intended participant; replies use deny-all mentions.

## Commands

`/help` lists the registered slash commands and arguments dynamically. `/memory` shows the requesting user's memories privately; `/forget memory_id:<id>` deletes one of that user's memories; `/forget-all confirm:true` deletes all memories in that private/server scope. `/diagnostics`, `/settings`, and `/dashboard` are owner-only. `/dashboard` provides category pages, validated edit modals, immediate SQLite persistence, reset and reset-all confirmation, status diagnostics, and restart-required markers. It does not expose tokens, API keys, or owner IDs, and fixed safety controls such as deny-all mentions and duplicate protection cannot be disabled. No command grants ordinary users access to another user's memories or global settings.

## 5. Tests

```powershell
python -m pytest -q
```

Tests use a temporary SQLite database and do not require real credentials. An opt-in connectivity check is available through `/settings` after the bot is running; it never prints API keys.

## 6. Memory and privacy

Mimi stores only small, heuristic facts such as “I like tea”, scoped to both server and user; DMs use server scope `0`. Passwords, tokens, API keys, and similar secret-shaped text are rejected. Only keyword-relevant memories are supplied to a reply, memories expire after 30 days without use unless the user's ID is in `MEMORY_NEVER_EXPIRE_USER_IDS`, and protected IDs are excluded from global expiry cleanup. `/memory`, `/forget`, and `/forget-all` are private in servers and naturally private in DMs, and database queries always include the requesting user's and scope IDs.

## 7. Wispbyte deployment

Upload the project including `config/`, `database/`, and `services/`, install `requirements.txt`, set the environment variables in the Wispbyte panel, and set the start command to `python main.py`. Keep the SQLite database on persistent storage if your plan provides it. Do not upload `.env` to public repositories.

## 8. Logs and backups

The process logs error classes and operational details but not prompts, responses, or secrets. For a backup, stop the bot briefly and copy `data/mimi.sqlite3` to a private location. Restore by replacing that file while the bot is stopped. If startup says configuration errors, compare `.env` with `.env.example`; if xKiro calls fail, use `/settings` and check the configured model IDs, API key, and provider status.

## Current limitations

The bot does not claim web-search success unless xKiro returns `web_search.status == "ok"`. Vision is URL-based using approved Discord CDN attachments; other arbitrary URLs are ignored. A running Discord token and xKiro key are required for live connectivity, and none were present in the old project under the new provider names, so live service success has not been claimed.
