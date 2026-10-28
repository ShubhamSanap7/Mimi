from __future__ import annotations

import re
from dataclasses import dataclass

SENSITIVE = re.compile(r"(?i)\b(?:password|token|api[_ -]?key|secret|otp|authorization|bearer|cookie|session|private key|credit card|ssn)\b")
QUESTION = re.compile(r"(?i)^\s*(?:do you remember|what do you remember|what memories|can you remember)\b")
FORGET = re.compile(r"(?i)\b(?:forget|delete|remove|erase)\b")
SAVE = re.compile(r"(?i)\b(?:remember|store|save|keep|don't forget|do not forget|update)\b")

@dataclass(frozen=True, slots=True)
class MemoryIntent:
    action: str
    fact: str = ""
    query: str = ""
    ambiguous: bool = False

def detect_memory_intent(text: str) -> MemoryIntent | None:
    """Detect explicit memory operations; ordinary facts remain automatic-policy input."""
    cleaned = " ".join(text.strip().split())
    if not cleaned or QUESTION.search(cleaned):
        return None
    if FORGET.search(cleaned) and re.search(r"(?i)\b(?:memory|fact|that|this)\b", cleaned):
        query = re.sub(r"(?i)^.*?\b(?:forget|delete|remove|erase)\b", "", cleaned).strip(" .:,-")
        query = re.sub(r"(?i)^(?:that|this|the fact)\b", "", query).strip(" .:,-")
        return MemoryIntent("forget", query=query)
    if not SAVE.search(cleaned) or FORGET.search(cleaned):
        return None
    remainder = re.sub(r"(?i)^.*?\b(?:remember|store|save|keep|don't forget|do not forget|update)\b", "", cleaned, count=1).strip(" .:,-")
    remainder = re.sub(r"(?i)^(?:that|this(?: in your memory)?|for next time)\b", "", remainder).strip(" .:,-")
    if not remainder or len(remainder) < 4 or SENSITIVE.search(remainder):
        return MemoryIntent("save", ambiguous=True)
    if re.match(r"(?i)^(?:the birthday|that fact|this fact|what i told you earlier)$", remainder):
        return MemoryIntent("save", ambiguous=True)
    return MemoryIntent("save", fact=remainder[:500])
