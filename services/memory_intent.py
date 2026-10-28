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


def memory_key_for_fact(fact: str, subject_id: str | int | None = None) -> str | None:
    """Return a conservative stable key for explicit facts that are updateable."""
    normalized = " ".join(fact.lower().split())
    prefix = f"subject:{subject_id}:" if subject_id and str(subject_id).isdigit() else ""
    patterns = (
        r"^(?:.+?['’]s|my|i)\s+(birthday|birth date|preferred language|favorite language|timezone|time zone|name)\b",
        r"^(?:i\s+)?prefer(?:s|red)?\s+([^.!?]{2,40})\b",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            label = re.sub(r"\s+", "_", match.group(1).strip())
            return f"{prefix}{label[:80]}"
    return None

def detect_memory_intent(text: str) -> MemoryIntent | None:
    """Detect explicit memory operations; ordinary facts remain automatic-policy input."""
    cleaned = " ".join(text.strip().split())
    if not cleaned or QUESTION.search(cleaned):
        return None
    explicit_forget = re.match(r"(?i)^\s*(?:please\s+)?(?:forget|delete|remove|erase)\b", cleaned)
    if explicit_forget:
        query = re.sub(r"(?i)^.*?\b(?:forget|delete|remove|erase)\b", "", cleaned).strip(" .:,-")
        query = re.sub(r"(?i)^(?:that|this|the fact)\b", "", query).strip(" .:,-")
        return MemoryIntent("forget", query=query)
    if not SAVE.search(cleaned) or FORGET.search(cleaned):
        return None
    update_request = bool(re.match(r"(?i)^\s*update\b", cleaned))
    remainder = re.sub(r"(?i)^.*?\b(?:remember|store|save|keep|don't forget|do not forget|update)\b", "", cleaned, count=1).strip(" .:,-")
    remainder = re.sub(r"(?i)^(?:that|this(?: in your memory)?|for next time)\b", "", remainder).strip(" .:,-")
    if not remainder or len(remainder) < 4 or SENSITIVE.search(remainder):
        return MemoryIntent("save", ambiguous=True)
    if update_request and re.search(r"(?i)\b(?:earlier|before|previous|already told)\b", remainder):
        return MemoryIntent("save", ambiguous=True)
    if re.match(r"(?i)^(?:the birthday|that fact|this fact|what i told you earlier)$", remainder):
        return MemoryIntent("save", ambiguous=True)
    return MemoryIntent("save", fact=remainder[:500])
