from __future__ import annotations

import sqlite3
import threading
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
              fact TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
              last_used_at TEXT NOT NULL, UNIQUE(user_id, guild_id, fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(user_id, guild_id);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS setting_audit (
              id INTEGER PRIMARY KEY, changed_by INTEGER NOT NULL, changed_at TEXT NOT NULL,
              setting_key TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS summaries (
              guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
              summary TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(guild_id, channel_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
              date_key TEXT PRIMARY KEY, input_tokens INTEGER NOT NULL DEFAULT 0,
              output_tokens INTEGER NOT NULL DEFAULT 0, estimated_tokens INTEGER NOT NULL DEFAULT 0,
              web_searches INTEGER NOT NULL DEFAULT 0, vision_requests INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS owner_activity (
              guild_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,
              last_seen_at TEXT NOT NULL, ping_sent_at TEXT, last_ping_at TEXT
            );
            CREATE TABLE IF NOT EXISTS interactions (
              user_id INTEGER NOT NULL, scope_id INTEGER NOT NULL,
              first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
              message_count INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY(user_id, scope_id)
            );
            CREATE TABLE IF NOT EXISTS multi_bot_topics (
              id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, participant_id INTEGER NOT NULL,
              opening_key TEXT NOT NULL, topic_key TEXT NOT NULL, opened_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_multi_bot_topics_scope ON multi_bot_topics(channel_id, participant_id, opened_at);
            """)
            try:
                self.conn.execute("ALTER TABLE owner_activity ADD COLUMN last_ping_at TEXT")
            except sqlite3.OperationalError:
                pass

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def add_memory(self, user_id: int, guild_id: int, fact: str) -> int:
        fingerprint = " ".join(fact.lower().split())[:500]
        with self.lock:
            self.conn.execute("""INSERT INTO memories(user_id,guild_id,fact,fingerprint,created_at,last_used_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,guild_id,fingerprint) DO UPDATE SET fact=excluded.fact,last_used_at=excluded.last_used_at""",
                (user_id, guild_id, fact[:500], fingerprint, now_iso(), now_iso()))
            self.conn.commit()
            row = self.conn.execute(
                "SELECT id FROM memories WHERE user_id=? AND guild_id=? AND fingerprint=?",
                (user_id, guild_id, fingerprint),
            ).fetchone()
            return int(row["id"])

    def find_memory_matches(self, user_id: int, guild_id: int, query: str) -> list[sqlite3.Row]:
        normalized = " ".join(query.lower().split())
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND guild_id=? ORDER BY id",
                (user_id, guild_id),
            ).fetchall()
        return [row for row in rows if normalized and normalized in " ".join(row["fact"].lower().split())]

    def list_memories(self, user_id: int, guild_id: int, expiry_days: int, protected_user_ids: frozenset[int] = frozenset()) -> list[sqlite3.Row]:
        with self.lock:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=expiry_days)).isoformat()
            if protected_user_ids:
                marks = ",".join("?" for _ in protected_user_ids)
                self.conn.execute(f"DELETE FROM memories WHERE last_used_at < ? AND user_id NOT IN ({marks})", (cutoff, *protected_user_ids))
            else:
                self.conn.execute("DELETE FROM memories WHERE last_used_at < ?", (cutoff,))
            self.conn.commit()
            return list(self.conn.execute("SELECT * FROM memories WHERE user_id=? AND guild_id=? ORDER BY id", (user_id, guild_id)))

    def touch(self, ids: list[int]) -> None:
        if not ids: return
        with self.lock:
            self.conn.executemany("UPDATE memories SET last_used_at=? WHERE id=?", [(now_iso(), i) for i in ids])
            self.conn.commit()

    def delete_memory(self, user_id: int, guild_id: int, memory_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM memories WHERE id=? AND user_id=? AND guild_id=?", (memory_id, user_id, guild_id))
            self.conn.commit()
            return cur.rowcount > 0

    def delete_all(self, user_id: int, guild_id: int) -> int:
        with self.lock:
            cur = self.conn.execute("DELETE FROM memories WHERE user_id=? AND guild_id=?", (user_id, guild_id))
            self.conn.commit()
            return cur.rowcount

    def stats(self) -> tuple[int, int]:
        with self.lock:
            return tuple(self.conn.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM memories").fetchone())

    def runtime_overrides(self) -> dict[str, object]:
        with self.lock:
            rows = self.conn.execute("SELECT key, value FROM settings WHERE key LIKE 'runtime.%'").fetchall()
        result: dict[str, object] = {}
        for row in rows:
            try:
                result[str(row["key"])[8:]] = json.loads(row["value"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    def set_runtime_override(self, key: str, value: object) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            self.conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"runtime.{key}", encoded),
            )
            self.conn.commit()

    def delete_runtime_override(self, key: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM settings WHERE key=?", (f"runtime.{key}",))
            self.conn.commit()

    def clear_runtime_overrides(self, keys: list[str] | None = None) -> None:
        with self.lock:
            if keys is None:
                self.conn.execute("DELETE FROM settings WHERE key LIKE 'runtime.%'")
            else:
                self.conn.executemany("DELETE FROM settings WHERE key=?", [(f"runtime.{key}",) for key in keys])
            self.conn.commit()

    def record_setting_audit(self, changed_by: int, changed_at: str, setting_key: str, old_value: object, new_value: object) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO setting_audit(changed_by,changed_at,setting_key,old_value,new_value) VALUES(?,?,?,?,?)",
                (changed_by, changed_at, setting_key, json.dumps(old_value, ensure_ascii=False, default=str), json.dumps(new_value, ensure_ascii=False, default=str)),
            )
            self.conn.commit()

    def recent_setting_audit(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(
                "SELECT changed_by,changed_at,setting_key,old_value,new_value FROM setting_audit ORDER BY id DESC LIMIT ?",
                (max(1, min(100, limit)),),
            ))

    def record_multi_bot_topic(self, channel_id: int, participant_id: int, opening_key: str, topic_key: str, opened_at: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO multi_bot_topics(channel_id,participant_id,opening_key,topic_key,opened_at) VALUES(?,?,?,?,?)",
                (channel_id, participant_id, opening_key[:200], topic_key[:200], opened_at),
            )
            self.conn.execute(
                "DELETE FROM multi_bot_topics WHERE channel_id=? AND participant_id=? AND id NOT IN "
                "(SELECT id FROM multi_bot_topics WHERE channel_id=? AND participant_id=? ORDER BY id DESC LIMIT 100)",
                (channel_id, participant_id, channel_id, participant_id),
            )
            self.conn.commit()

    def recent_multi_bot_topics(self, channel_id: int, participant_id: int, since: str) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(
                "SELECT opening_key, topic_key, opened_at FROM multi_bot_topics WHERE channel_id=? AND participant_id=? AND opened_at>=? ORDER BY id DESC LIMIT 50",
                (channel_id, participant_id, since),
            ))

    def interaction_state(self, user_id: int, scope_id: int) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM interactions WHERE user_id=? AND scope_id=?",
                (user_id, scope_id),
            ).fetchone()

    def record_interaction(self, user_id: int, scope_id: int, at: str) -> None:
        with self.lock:
            self.conn.execute("""INSERT INTO interactions(user_id,scope_id,first_seen_at,last_seen_at,message_count)
                VALUES(?,?,?,?,1) ON CONFLICT(user_id,scope_id) DO UPDATE SET
                last_seen_at=excluded.last_seen_at, message_count=message_count+1""",
                (user_id, scope_id, at, at))
            self.conn.commit()

    def usage(self, date_key: str) -> dict[str, int]:
        with self.lock:
            row = self.conn.execute("SELECT * FROM daily_usage WHERE date_key=?", (date_key,)).fetchone()
            if row is None:
                return {"input_tokens": 0, "output_tokens": 0, "estimated_tokens": 0, "web_searches": 0, "vision_requests": 0}
            return dict(row)

    def add_usage(self, date_key: str, input_tokens: int, output_tokens: int, estimated: bool,
                  web_search: bool = False, vision: bool = False) -> None:
        with self.lock:
            self.conn.execute("""INSERT INTO daily_usage(date_key,input_tokens,output_tokens,estimated_tokens,web_searches,vision_requests)
                VALUES(?,?,?,?,?,?) ON CONFLICT(date_key) DO UPDATE SET
                input_tokens=input_tokens+excluded.input_tokens,
                output_tokens=output_tokens+excluded.output_tokens,
                estimated_tokens=estimated_tokens+excluded.estimated_tokens,
                web_searches=web_searches+excluded.web_searches,
                vision_requests=vision_requests+excluded.vision_requests""",
                (date_key, input_tokens, output_tokens, input_tokens + output_tokens if estimated else 0,
                 1 if web_search else 0, 1 if vision else 0))
            self.conn.commit()

    def record_owner_activity(self, guild_id: int, owner_id: int, at: str) -> None:
        with self.lock:
            self.conn.execute("""INSERT INTO owner_activity(guild_id,owner_id,last_seen_at,ping_sent_at)
                VALUES(?,?,?,NULL) ON CONFLICT(guild_id) DO UPDATE SET
                owner_id=excluded.owner_id, last_seen_at=excluded.last_seen_at, ping_sent_at=NULL""",
                (guild_id, owner_id, at))
            self.conn.commit()

    def owner_activity(self, guild_id: int) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute("SELECT * FROM owner_activity WHERE guild_id=?", (guild_id,)).fetchone()

    def mark_owner_ping(self, guild_id: int, at: str) -> None:
        with self.lock:
            self.conn.execute("UPDATE owner_activity SET ping_sent_at=?, last_ping_at=? WHERE guild_id=?", (at, at, guild_id))
            self.conn.commit()
