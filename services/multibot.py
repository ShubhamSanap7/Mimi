from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque
from collections import deque


@dataclass(slots=True)
class MultiBotConversation:
    participant_id: int
    started_at: datetime
    last_activity_at: datetime
    message_count: int = 1
    last_message_id: int | None = None
    history: Deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=8))

    def expired(self, now: datetime, *, inactivity_seconds: float, max_duration_seconds: float) -> str | None:
        if (now - self.started_at).total_seconds() >= max_duration_seconds:
            return "duration_limit"
        if (now - self.last_activity_at).total_seconds() >= inactivity_seconds:
            return "inactivity_timeout"
        return None

    def reached_limit(self, maximum: int) -> bool:
        return self.message_count >= maximum


def configured_participants(chromix_id: int, blaze_id: int) -> tuple[int, ...]:
    """Return unique, positive configured Discord user IDs in stable order."""
    return tuple(dict.fromkeys(value for value in (chromix_id, blaze_id) if isinstance(value, int) and value > 0))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
