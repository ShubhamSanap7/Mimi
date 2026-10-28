from __future__ import annotations

from collections import defaultdict, deque
import random
from typing import Callable


ERROR_CATEGORIES = (
    "network",
    "rate_limit",
    "authentication",
    "server",
    "invalid_request",
    "unknown",
)

MESSAGES: dict[str, tuple[str, ...]] = {
    "network": (
        "H-hello?? The AI service wandered off mid-conversation. Give me a sec!",
        "My brain tried to connect, tripped over the Wi-Fi, and faceplanted. Retry?",
        "The connection is being dramatic today. One more try in a bit?",
        "My thoughts got stuck in transit. Please poke me again shortly!",
        "The signal ran away from my tiny brain. I’ll try again in a moment!",
        "The AI road to my brain has a pothole today. Retry me soon?",
    ),
    "rate_limit": (
        "Whoa, whoa! The AI service says we’re going too fast. Tiny cooldown?",
        "Brain requests are on timeout. Apparently, even my neurons need a break.",
        "We’ve hit the request limit. I’ll be back when the service lets me cook again.",
        "My brain queue is full and waving a tiny red flag. Try again shortly!",
        "The provider asked me to slow my sparkle down. Give it a little breather?",
        "Too many thoughts at once! My AI allowance needs a short cooldown.",
    ),
    "authentication": (
        "Something’s wrong with my AI setup. I need my owner to check the control panel.",
        "My brain configuration seems broken. Owner intervention required!",
        "I can’t access my AI service right now. I’ve flagged this for my owner.",
        "My AI credentials need a responsible grown-up to inspect them. I’ll stay put!",
        "The brain door is locked from my side. My owner needs to check the setup.",
        "I found a configuration snag and refused to guess around it. Owner help, please!",
    ),
    "server": (
        "The AI service is having a moment. Even big brains need a reboot sometimes.",
        "My brain supplier appears to be having a tiny meltdown. Try again soon?",
        "The provider isn’t cooperating. I’ll try again when it recovers.",
        "The other side of the brain line is wobbling. Please retry in a little bit!",
        "The AI server fell over dramatically. I’m giving it a moment to recover.",
        "The provider is currently doing the digital equivalent of staring at a wall.",
    ),
    "invalid_request": (
        "My AI request got rejected. Something in the request needs fixing.",
        "The AI service didn’t understand what I sent. My owner may need to inspect this.",
        "My brain request hit a snag. I’ll flag it rather than keep retrying blindly.",
        "That request bounced back with a tiny error stamp. I need to adjust the wiring.",
        "The model rejected my request before it could think. I’ll report the snag safely.",
        "My request format tripped over its own shoelaces. This one needs a proper fix.",
    ),
    "unknown": (
        "Welp. My brain just made a Windows error noise internally.",
        "That was not supposed to happen. My AI call hit an unexpected snag.",
        "My thoughts got tangled somewhere. Try again in a moment?",
        "A mysterious brain gremlin interfered with that request. Please try again soon.",
        "I hit an error I don’t recognize, which is extremely rude of it.",
        "My little thought engine coughed up an unfamiliar problem. Retry me shortly?",
    ),
}


class ErrorMessageSelector:
    """Friendly, non-sensitive fallback selection with per-scope recent avoidance."""

    def __init__(self, chooser: Callable[[list[str]], str] | None = None):
        self.chooser = chooser or random.choice
        self.recent: dict[tuple[str, int], deque[str]] = defaultdict(lambda: deque(maxlen=2))

    def choose(self, category: str, scope_id: int = 0) -> str:
        category = category if category in MESSAGES else "unknown"
        messages = list(MESSAGES[category])
        recent = self.recent[(category, scope_id)]
        available = [message for message in messages if message not in recent] or messages
        selected = self.chooser(available)
        recent.append(selected)
        return selected


def category_for_error(error: BaseException) -> str:
    category = getattr(error, "category", None)
    return category if category in MESSAGES else "unknown"
