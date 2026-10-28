from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Deque


TOPIC_STOPWORDS = {
    "about", "after", "again", "also", "best", "could", "does", "from", "have", "just", "like",
    "make", "most", "much", "only", "question", "quick", "really", "should", "that", "the", "their",
    "them", "there", "this", "what", "when", "which", "with", "would", "your", "you", "mimi",
}


def topic_fingerprint(text: str) -> str:
    """Create a small deterministic topic key; no model call or transcript storage is needed."""
    words = re.findall(r"[a-z0-9]{3,}", re.sub(r"https?://\S+|<@!?\d+>", " ", text.lower()))
    useful = sorted({word for word in words if word not in TOPIC_STOPWORDS})
    return " ".join(useful[:12]) or "general"


def opener_fingerprint(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]{3,}", text.lower()))[:200]


def topics_overlap(first: str, second: str) -> bool:
    left, right = set(first.split()), set(second.split())
    if not left or not right or left == {"general"} or right == {"general"}:
        return False
    return len(left & right) >= max(2, min(len(left), len(right)) // 2)


@dataclass(slots=True)
class MultiBotConversation:
    participant_id: int
    started_at: datetime
    last_activity_at: datetime
    channel_id: int = 0
    message_count: int = 1
    last_message_id: int | None = None
    opening_key: str = ""
    last_reply_at: datetime | None = None
    repeat_count: int = 0
    history: Deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=8))
    topic_keys: Deque[str] = field(default_factory=lambda: deque(maxlen=8))
    recent_input_keys: Deque[str] = field(default_factory=lambda: deque(maxlen=4))
    summary: str = ""

    def expired(self, now: datetime, *, inactivity_seconds: float, max_duration_seconds: float) -> str | None:
        if (now - self.started_at).total_seconds() >= max_duration_seconds:
            return "duration_limit"
        if (now - self.last_activity_at).total_seconds() >= inactivity_seconds:
            return "inactivity_timeout"
        return None

    def reached_limit(self, maximum: int) -> bool:
        return self.message_count >= maximum

    def record_message(self, role: str, content: str) -> str:
        clean = content.strip()[:800]
        self.history.append({"role": role, "content": clean})
        key = topic_fingerprint(clean)
        self.topic_keys.append(key)
        self.recent_input_keys.append(opener_fingerprint(clean))
        recent = list(self.history)[-4:]
        topics = ", ".join(dict.fromkeys(self.topic_keys))[:240]
        callbacks = " | ".join(f"{item['role']}: {item['content'][:140]}" for item in recent)
        self.summary = f"Topics: {topics}\nRecent callbacks: {callbacks}"[:900]
        return key


def configured_participants(chromix_id: int, blaze_id: int) -> tuple[int, ...]:
    """Return unique, positive configured Discord user IDs in stable order."""
    return tuple(dict.fromkeys(value for value in (chromix_id, blaze_id) if isinstance(value, int) and value > 0))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
