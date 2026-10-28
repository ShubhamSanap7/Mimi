from __future__ import annotations

import sqlite3
import threading
import json
import re
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
              last_used_at TEXT NOT NULL, memory_key TEXT NOT NULL DEFAULT '',
              subject_id INTEGER, subject_name TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
              UNIQUE(user_id, guild_id, fingerprint)
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
            CREATE TABLE IF NOT EXISTS pending_tasks (
              task_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
              channel_id INTEGER NOT NULL, capability TEXT NOT NULL, arguments TEXT NOT NULL,
              missing TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
              confirmation_required INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_pending_tasks_scope ON pending_tasks(user_id, guild_id, channel_id, status, expires_at);
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
              task_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
              channel_id INTEGER NOT NULL, content TEXT NOT NULL, due_at TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL, delivered_at TEXT,
              idempotency_key TEXT NOT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due ON scheduled_tasks(status, due_at);
            CREATE TABLE IF NOT EXISTS agent_executions (
              idempotency_key TEXT PRIMARY KEY, capability TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """)
            self._migrate_schema()

    def _migrate_schema(self) -> None:
        version = int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        if version < 1:
            columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(owner_activity)")}
            if "last_ping_at" not in columns:
                self.conn.execute("ALTER TABLE owner_activity ADD COLUMN last_ping_at TEXT")
            self.conn.execute("PRAGMA user_version=1")
            self.conn.commit()
            version = 1
        if version < 2:
            columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(memories)")}
            additions = {
                "memory_key": "TEXT NOT NULL DEFAULT ''",
                "subject_id": "INTEGER",
                "subject_name": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT NOT NULL DEFAULT ''",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    self.conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(user_id, guild_id, memory_key)")
            self.conn.execute("PRAGMA user_version=2")
            self.conn.commit()
            version = 2
        if version < 3:
            self.conn.execute("PRAGMA user_version=3")
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def add_memory(self, user_id: int, guild_id: int, fact: str, *, memory_key: str = "",
                   subject_id: int | None = None, subject_name: str = "", category: str = "") -> int:
        fingerprint = " ".join(fact.lower().split())[:500]
        with self.lock:
            timestamp = now_iso()
            existing = None
            if memory_key:
                existing = self.conn.execute(
                    "SELECT id FROM memories WHERE user_id=? AND guild_id=? AND memory_key=? ORDER BY id LIMIT 1",
                    (user_id, guild_id, memory_key),
                ).fetchone()
            if existing is not None:
                existing_id = int(existing["id"])
                self.conn.execute(
                    "DELETE FROM memories WHERE user_id=? AND guild_id=? AND memory_key=? AND id<>?",
                    (user_id, guild_id, memory_key, existing_id),
                )
                self.conn.execute(
                    "DELETE FROM memories WHERE user_id=? AND guild_id=? AND fingerprint=? AND id<>?",
                    (user_id, guild_id, fingerprint, existing_id),
                )
                self.conn.execute(
                    "UPDATE memories SET fact=?, fingerprint=?, last_used_at=?, subject_id=?, subject_name=?, category=? WHERE id=?",
                    (fact[:500], fingerprint, timestamp, subject_id, subject_name[:100], category[:80], existing_id),
                )
            else:
                self.conn.execute("""INSERT INTO memories(user_id,guild_id,fact,fingerprint,created_at,last_used_at,memory_key,subject_id,subject_name,category)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,guild_id,fingerprint) DO UPDATE SET fact=excluded.fact,last_used_at=excluded.last_used_at,
                    memory_key=CASE WHEN excluded.memory_key<>'' THEN excluded.memory_key ELSE memories.memory_key END,
                    subject_id=COALESCE(excluded.subject_id, memories.subject_id), subject_name=excluded.subject_name, category=excluded.category""",
                    (user_id, guild_id, fact[:500], fingerprint, timestamp, timestamp, memory_key[:120], subject_id, subject_name[:100], category[:80]))
            self.conn.commit()
            row = self.conn.execute(
                "SELECT id FROM memories WHERE user_id=? AND guild_id=? AND fingerprint=?",
                (user_id, guild_id, fingerprint),
            ).fetchone()
            return int(row["id"])

    def find_memory_matches(self, user_id: int, guild_id: int, query: str) -> list[sqlite3.Row]:
        normalized = " ".join(query.lower().split())
        exact_tokens = {token for token in normalized.split() if len(token) >= 3 and token not in {"the", "that", "this", "old", "memory", "fact"}}
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND guild_id=? ORDER BY id",
                (user_id, guild_id),
            ).fetchall()
        exact = [row for row in rows if normalized and normalized in " ".join(row["fact"].lower().split())]
        if exact or not exact_tokens:
            return exact
        scored = []
        for row in rows:
            fact_tokens = set(re.findall(r"[a-z0-9']{3,}", row["fact"].lower()))
            overlap = len(exact_tokens & fact_tokens)
            if overlap:
                scored.append((overlap, int(row["id"]), row))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not scored:
            return []
        best = scored[0][0]
        return [row for score, _, row in scored if score == best]

    def list_memories(self, user_id: int, guild_id: int, expiry_days: int,
                      protected_user_ids: frozenset[int] = frozenset(), *, limit: int | None = None,
                      offset: int = 0) -> list[sqlite3.Row]:
        with self.lock:
            query = "SELECT * FROM memories WHERE user_id=? AND guild_id=? ORDER BY id"
            params: list[object] = [user_id, guild_id]
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params.extend([max(1, min(50, limit)), max(0, offset)])
            return list(self.conn.execute(query, params))

    def count_memories(self, user_id: int, guild_id: int) -> int:
        with self.lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM memories WHERE user_id=? AND guild_id=?", (user_id, guild_id)).fetchone()[0])

    def sweep_expired_memories(self, expiry_days: int, protected_user_ids: frozenset[int] = frozenset()) -> int:
        """Perform expiry cleanup explicitly; read-only memory views do not delete data."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=expiry_days)).isoformat()
        with self.lock:
            if protected_user_ids:
                marks = ",".join("?" for _ in protected_user_ids)
                cur = self.conn.execute(
                    f"DELETE FROM memories WHERE last_used_at < ? AND user_id NOT IN ({marks})",
                    (cutoff, *protected_user_ids),
                )
            else:
                cur = self.conn.execute("DELETE FROM memories WHERE last_used_at < ?", (cutoff,))
            self.conn.commit()
            return cur.rowcount

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

    def create_pending_task(self, task_id: str, user_id: int, guild_id: int, channel_id: int,
                            capability: str, arguments: dict, missing: list[str], expires_at: str,
                            idempotency_key: str) -> bool:
        with self.lock:
            try:
                self.conn.execute(
                    "INSERT INTO pending_tasks(task_id,user_id,guild_id,channel_id,capability,arguments,missing,status,created_at,expires_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, user_id, guild_id, channel_id, capability, json.dumps(arguments, ensure_ascii=False),
                     json.dumps(missing), "pending", now_iso(), expires_at, idempotency_key),
                )
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def pending_task(self, user_id: int, guild_id: int, channel_id: int) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM pending_tasks WHERE user_id=? AND guild_id=? AND channel_id=? AND status='pending' AND expires_at>? ORDER BY created_at DESC LIMIT 1",
                (user_id, guild_id, channel_id, now_iso()),
            ).fetchone()

    def update_pending_task(self, task_id: str, arguments: dict, missing: list[str]) -> bool:
        with self.lock:
            cur = self.conn.execute(
                "UPDATE pending_tasks SET arguments=?, missing=? WHERE task_id=? AND status='pending'",
                (json.dumps(arguments, ensure_ascii=False), json.dumps(missing), task_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def finish_pending_task(self, task_id: str, status: str = "completed") -> bool:
        with self.lock:
            cur = self.conn.execute("UPDATE pending_tasks SET status=? WHERE task_id=? AND status='pending'", (status, task_id))
            self.conn.commit()
            return cur.rowcount > 0

    def sweep_pending_tasks(self) -> int:
        with self.lock:
            cur = self.conn.execute("UPDATE pending_tasks SET status='expired' WHERE status='pending' AND expires_at<=?", (now_iso(),))
            self.conn.commit()
            return cur.rowcount

    def count_scheduled_tasks(self, user_id: int, guild_id: int) -> int:
        with self.lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM scheduled_tasks WHERE user_id=? AND guild_id=? AND status='pending'", (user_id, guild_id)).fetchone()[0])

    def create_scheduled_task(self, task_id: str, user_id: int, guild_id: int, channel_id: int,
                              content: str, due_at: str, idempotency_key: str) -> bool:
        with self.lock:
            try:
                self.conn.execute(
                    "INSERT INTO scheduled_tasks(task_id,user_id,guild_id,channel_id,content,due_at,status,created_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
                    (task_id, user_id, guild_id, channel_id, content[:1900], due_at, "pending", now_iso(), idempotency_key),
                )
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def due_scheduled_tasks(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(
                "SELECT * FROM scheduled_tasks WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT ?",
                (now_iso(), max(1, min(20, limit))),
            ))

    def mark_scheduled_task(self, task_id: str, status: str) -> bool:
        with self.lock:
            cur = self.conn.execute(
                "UPDATE scheduled_tasks SET status=?, delivered_at=? WHERE task_id=? AND status='pending'",
                (status, now_iso() if status == "sent" else None, task_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def claim_agent_execution(self, idempotency_key: str, capability: str) -> bool:
        with self.lock:
            try:
                self.conn.execute("INSERT INTO agent_executions(idempotency_key,capability,created_at) VALUES(?,?,?)", (idempotency_key, capability, now_iso()))
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

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
