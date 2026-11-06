## Project at a glance

A lightweight Discord AI chatbot with SQLite-backed memory, provider fallback, moderation-safe controls, optional vision/search features, and owner diagnostics.

---

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

`RANDOM_RESPONSE_PROBABILITY=0.02` means a 2% random response chance. `EXCLUDED_CHANNEL_IDS` disables replies in selected channels. Image understanding is disabled in the current build. Current-information wording such as “latest” or “today” enables the configured provider's search flag; Mimi reports when live search is unavailable.

The default daily AI accounting budget is 1,000,000 tokens, with a conservative stop threshold at 85% (`BUDGET_SAFETY_MARGIN`). xKiro `usage.prompt_tokens` and `usage.completion_tokens` are recorded as exact when present; otherwise Mimi records a bounded character-based estimate and labels diagnostics as estimated. Usage is persisted in SQLite and resets by `BOT_TIMEZONE` local date. Search and vision have separate daily caps, requests are concurrency-limited, and low/stop modes disable optional activity or defer AI requests while local commands continue to work.

Groq is the primary AI provider using `GROQ_API_KEY`, `GROQ_MODEL` (`qwen/qwen3.8-27b`), and `GROQ_BASE_URL` (default `https://api.groq.com/openai/v1`). xKiro is the fallback. `AI_PRIMARY_PROVIDER` and `AI_FALLBACK_PROVIDER` control the route. Mimi attempts the fallback only once after a retryable provider failure; permanent authentication and invalid-request failures do not trigger it. Image fallback is disabled. Diagnostics shows only configured/unconfigured status and model name, never keys.

To enable the owner inactivity ping, configure `INACTIVITY_PING_ENABLED=true`, `INACTIVITY_OWNER_ID`, `INACTIVITY_GUILD_ID`, and `INACTIVITY_CHANNEL_ID`. Mimi records only the owner's observed messages in that configured server, persists the timestamp, and sends at most one local-template ping after the configured threshold. A missing channel is logged and skipped. This does not infer activity outside messages Mimi can observe.

Reaction media is local-only. The checkout includes 120 verified animated GIFs from real anime scenes under `config/reactions/`, plus the backward-compatible root files `happy.gif`, `confused.gif`, `shock.gif`, `sad.gif`, and `angry.gif`. `manifest.json` records actual hashes, dimensions, frame counts, sizes, tags, pinned source URLs, provenance, and validation results. The source repository's MIT license is recorded separately from the individual media rights, which remain explicitly unknown. Mimi selects assets locally for explicit requests such as “send me a shocked anime GIF”; ordinary replies only get occasional matching reactions, with a per-channel cooldown and recent-file avoidance. Mimi never downloads arbitrary reaction files. Image analysis is separate and uses only approved Discord CDN attachments. For moderation, set `MODERATION_ALERT_CHANNEL_ID` and optionally `MODERATION_ALERT_KEYWORDS`; Mimi only reports matching messages to that human channel and never bans, kicks, or times out users.

Edit `config/personality.md` to change Mimi's voice without changing Python code.

## 4. Run

```powershell
python main.py
```

The bot responds to mentions, replies to Mimi, and configured low-probability guild triggers. Incoming DMs are disabled. Per-user and per-channel cooldowns prevent spam. Reply context is fetched from Discord when available. Long messages are split below Discord's limit.

Mimi does not send or answer DMs. There is no `create_dm`, `user.send`, or background-DM path.

The optional multi-bot reply feature is disabled by default. To enable it, set `MULTI_BOT_ENABLED=true` and configure the channel. Mimi reacts locally to ordinary bot messages. If any bot replies directly to Mimi in that channel, Mimi may hold a bounded 3-message conversation with it; no participant allowlist is used. Cooldowns, duplicate protection, bot checks, and safe per-bot mention handling remain active.

## Commands

`/help` lists the registered slash commands and arguments dynamically. `/memory` shows shared public memories for the current server privately; `/forget memory_id:<id>` deletes one shared memory; `/forget-all confirm:true` deletes all shared memories in that server. `/diagnostics` is owner-only. The previous `/settings` and `/dashboard` controls are disabled.

Natural-language actions are limited to registered capabilities: mention or reply to Mimi with an explicit request to send one message, create a native Discord poll, or schedule a bounded follow-up in the current server channel. Missing details are collected in a scoped SQLite pending task for 15 minutes; tasks cannot cross users, servers, or channels. Native polls use the installed `discord.py` poll API and require a whole-hour duration from 1 to 168 hours. Follow-ups are limited to 10 pending tasks per user/server and 7 days ahead. These actions use Python validation and deny-all mentions; they do not rely on provider tool-calling or execute code. A request to add a new bot feature is treated as a development request and is never executed from Discord.

## 5. Tests

```powershell
python -m pytest -q
```

Tests use a temporary SQLite database and do not require real credentials. An opt-in connectivity check is available through `/settings` after the bot is running; it never prints API keys.

Explicit messages such as “remember that…” use a deterministic application memory path
and are confirmed only after SQLite persistence is verified. Mimi's stable identity is
defined in `config/identity.md`; runtime capability status is generated by
`services/capabilities.py`, including the configured provider/model and feature limits.

## 6. Memory and privacy

Mimi stores only explicit, small public facts in one shared memory scope per server; automatic conversational memory saving is disabled. Passwords, tokens, API keys, personal/private facts, and similar secret-shaped text are rejected. Only keyword-relevant memories are supplied to a reply, and memories expire after 30 days without use. `/memory`, `/forget`, and `/forget-all` operate on the current server's shared scope.

## 7. Wispbyte deployment

Upload the project including `config/`, `database/`, and `services/`, install `requirements.txt`, set the environment variables in the Wispbyte panel, and set the start command to `python main.py`. Keep the SQLite database on persistent storage if your plan provides it. Do not upload `.env` to public repositories.

## 8. Logs and backups

The process logs error classes and operational details but not prompts, responses, or secrets. For a backup, stop the bot briefly and copy `data/mimi.sqlite3` to a private location. Restore by replacing that file while the bot is stopped. If startup says configuration errors, compare `.env` with `.env.example`; if xKiro calls fail, use `/settings` and check the configured model IDs, API key, and provider status.

## Current limitations

The bot does not claim web-search success unless the configured provider returns a successful search status. Vision, incoming DMs, moderation alerts, owner inactivity pings, and the interactive dashboard are disabled in this build. A running Discord token and configured provider key are required for live connectivity.
