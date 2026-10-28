from pathlib import Path


def load_personality(base_dir: Path) -> str:
    path = base_dir / "config" / "personality.md"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("config/personality.md is empty")
    return text


def load_identity(base_dir: Path) -> str:
    path = base_dir / "config" / "identity.md"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("config/identity.md is empty")
    return text
