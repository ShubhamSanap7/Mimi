from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import random
from typing import Iterable, Mapping, TypedDict

from PIL import Image, UnidentifiedImageError


MAX_REACTION_FILE_BYTES = 8 * 1024 * 1024
MAX_REACTION_DIMENSION = 4096
ALLOWED_SUFFIXES = frozenset({".gif", ".png", ".jpg", ".jpeg", ".webp"})
MANIFEST_FILENAME = "manifest.json"

ACTION_WORDS = r"\b(send|show|give|find|want|need|drop|post|share|use|express|react|respond|reply)\b"
MEDIA_WORDS = r"\b(gif|reaction|meme|image|picture|photo|pic)\b"

# These rules are intentionally local and conservative. They are used both for
# explicit media requests and for occasional contextual reactions after a text
# reply; neither path needs another model call.
CATEGORY_PATTERN_SOURCES: tuple[tuple[str, str], ...] = (
    ("shock", r"\b(shock(?:ed)?|surpris(?:e|ed|ing)|unexpected|wtf|no way|seriously|you did what)\b"),
    ("excited", r"\b(excited|exciting|excitement|hype|can't wait|cannot wait|let's go|lets go)\b"),
    ("happy", r"\b(happy|glad|yay|awesome|great|congrats?|won|joy|thank(?:s| you))\b"),
    ("laughing", r"\b(laugh|laughing|lol|lmao|hilarious|funny|joke)\b"),
    ("confused", r"\b(confus(?:e|ed|ing)|huh|what do you mean|weird|unclear)\b"),
    ("thinking", r"\b(think(?:ing)?|hmm|wait a second|consider|let me see)\b"),
    ("curious", r"\b(curious|interesting|tell me more|how does)\b"),
    ("crying", r"\b(cry(?:ing)?|sob(?:bing)?|tears?|heartbroken)\b"),
    ("sad", r"\b(sad|terrible day|upset|hurt|disappoint(?:ed|ing)?|down)\b"),
    ("angry", r"\b(angry|mad|rage|furious|frustrat(?:ed|ing)?)\b"),
    ("embarrassed", r"\b(embarrass(?:ed|ing)?|awkward|oops)\b"),
    ("sleepy", r"\b(sleepy|tired|exhausted|good night|bedtime)\b"),
    ("bored", r"\b(bored|boring|nothing to do)\b"),
    ("proud", r"\b(proud|nailed it|did it|achievement)\b"),
    ("smug", r"\b(smug|told you|i knew it|obvious)\b"),
    ("mischievous", r"\b(mischievous|evil plan|hehe|gotcha|sneaky)\b"),
    ("facepalm", r"\b(facepalm|face palm|what was i thinking|critical mistake)\b"),
    ("nervous", r"\b(nervous|anxious|panic|panicking|scared)\b"),
    ("relieved", r"\b(relieved|phew|close one|made it)\b"),
    ("apologetic", r"\b(sorry|apolog(?:y|etic)|my bad)\b"),
    ("supportive", r"\b(support|you got this|good luck|here for you|i believe)\b"),
    ("celebrating", r"\b(celebrat(?:e|ing|ion)|party|achievement unlocked|victory)\b"),
    ("thankful", r"\b(thankful|thanks|thank you|appreciate)\b"),
    ("greeting", r"\b(hello|hi|hey|welcome|good morning)\b"),
    ("goodbye", r"\b(bye|goodbye|see you|good night)\b"),
    ("wave", r"\b(wave|waving)\b"),
    ("nod", r"\b(nod|nodding|agreed|agree)\b"),
    ("head_shake", r"\b(head shake|shaking my head|nope)\b"),
    ("clap", r"\b(clap|clapping|bravo|applause)\b"),
    ("joke_laugh", r"\b(laugh at|laughing at|good joke)\b"),
    ("terrible_joke", r"\b(terrible joke|bad joke|dad joke)\b"),
    ("what_did_i_read", r"\b(what did i just read|did i just read)\b"),
    ("wait_a_second", r"\b(wait a second|hold on|one second)\b"),
    ("you_did_what", r"\b(you did what|what did you do)\b"),
    ("skill_issue", r"\b(skill issue|skill diff)\b"),
    ("fair_enough", r"\b(fair enough|that's fair|thats fair)\b"),
    ("listening", r"\b(i'm listening|im listening|listening)\b"),
    ("judging", r"\b(judging you|i'm judging|im judging)\b"),
    ("attention", r"\b(have your attention|you have my attention|pay attention)\b"),
    ("mission_accomplished", r"\b(mission accomplished|we did it|success)\b"),
    ("went_wrong", r"\b(went wrong|failed|disaster|that went badly)\b"),
    ("good_luck", r"\b(good luck|best of luck)\b"),
    ("you_got_this", r"\b(you got this|you can do it)\b"),
    ("gaming_victory", r"\b(victory|won the game|gg|win)\b"),
    ("gaming_defeat", r"\b(defeat|lost the game|game over|loss)\b"),
    ("gaming_rage", r"\b(rage quit|gaming rage|tilted|tilt)\b"),
    ("gaming_clutch", r"\b(clutch|clutched|last second save)\b"),
    ("plot_twist", r"\b(plot twist|unexpected twist|didn't see that coming|didnt see that coming)\b"),
    ("big_brain", r"\b(big brain|galaxy brain|genius move)\b"),
    ("lag", r"\b(lag|lagging|ping spike|rubber banding)\b"),
    ("achievement_unlocked", r"\b(achievement unlocked|unlocked an achievement)\b"),
    ("absolute_chaos", r"\b(absolute chaos|chaos|everything is on fire)\b"),
    ("suspicion", r"\b(suspicious|suspicion|hmm\.\.\.?)\b"),
    ("betrayal", r"\b(betray(?:al|ed)|backstab)\b"),
    ("gaming_facepalm", r"\b(gaming facepalm|throwing the game|critical fail)\b"),
)

# Compile once at import time. Reaction matching runs on every eligible reply,
# so compiling these expressions inside each call needlessly burns CPU.
CATEGORY_PATTERNS = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in CATEGORY_PATTERN_SOURCES)

AUTOMATIC_SUPPRESS_PATTERN = re.compile(
    r"(?i)(?:\b(?:suicide|suicidal|self[- ]?harm|kill myself|want to die|overdose|abuse|assault|rape|doxx|"
    r"password|api[_ -]?key|token|secret|medical|diagnos(?:e|is)|emergency|funeral|death|dead|grief|trauma|"
    r"depressed|ping everyone|mass ping)\b|@everyone|@here)"
)

AUTOMATIC_SARCASM_PATTERN = re.compile(
    r"(?i)(?:\b(?:sarcasm|sarcastic|yeah right|sure buddy|as if|just kidding|not actually)\b|/s\b)"
)

SERIOUS_CONTEXT_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b(?:having|had|it's been|it has been)\s+(?:a\s+)?(?:genuinely\s+|really\s+|such a\s+)?(?:rough|hard|difficult|terrible|awful|horrible)\s+(?:day|time)\b|"
    r"\b(?:don't|do not|doesn't|does not)\s+(?:really\s+)?feel\s+like\s+jok(?:e|ing)\b|"
    r"\b(?:not|no)\s+in\s+the\s+mood\s+to\s+jok(?:e|ing)\b|"
    r"\b(?:please|just)\s+don't\s+joke\b|"
    r"\b(?:not doing well|not okay|not ok|can't cope|cannot cope|feel hopeless|feeling hopeless|overwhelmed|panic attack|grieving|bereaved|mourning|lost someone|someone died|funeral)\b|"
    r"\b(?:suicide|suicidal|self[- ]?harm|kill myself|want to die|overdose|abuse|assault|rape|doxx|medical emergency|diagnos(?:e|is)|trauma|depressed)\b"
    r")"
)

AUTOMATIC_LOW_SIGNAL_CATEGORIES = frozenset({
    "greeting", "goodbye", "wave", "nod", "listening", "attention", "thinking", "curious",
    "fair_enough", "wait_a_second", "good_luck", "you_got_this", "thankful",
})

@dataclass(frozen=True, slots=True)
class ReactionAsset:
    path: Path
    relative_path: str
    category: str
    tags: tuple[str, ...]
    format: str
    size_bytes: int
    width: int
    height: int
    frame_count: int
    sha256: str
    source_url: str | None
    source_page_url: str | None
    source_license_url: str | None
    source_commit: str | None
    license_status: str
    provenance: str
    valid: bool = True

    def manifest_record(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "category": self.category,
            "tags": list(self.tags),
            "format": self.format,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "sha256": self.sha256,
            "source_url": self.source_url,
            "source_page_url": self.source_page_url,
            "source_license_url": self.source_license_url,
            "source_commit": self.source_commit,
            "license_status": self.license_status,
            "provenance": self.provenance,
            "valid": self.valid,
        }


class ScanResult(TypedDict):
    assets: list[ReactionAsset]
    invalid: list[dict[str, object]]
    duplicates: dict[str, list[str]]


class ReactionLibrary:
    """Safe local discovery, validation, indexing, and selection of reactions."""

    def __init__(self, root: Path, *, max_file_bytes: int = MAX_REACTION_FILE_BYTES):
        self.root = root
        self.max_file_bytes = max_file_bytes
        self._root_resolved = root.resolve(strict=False)
        self._scan_cache: ScanResult | None = None
        self._scan_cache_max_bytes = max_file_bytes
        self._manifest_metadata_cache: dict[str, Mapping[str, object]] | None = None
        self._manifest_signature: tuple[int, int] | None = None

    def refresh(self) -> None:
        """Invalidate the validated asset cache after an operator changes files."""
        self._scan_cache = None
        self._manifest_metadata_cache = None
        self._manifest_signature = None

    def _manifest_file_signature(self) -> tuple[int, int] | None:
        try:
            stat = (self.root / MANIFEST_FILENAME).stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def safe_asset_path(self, relative_path: str | Path) -> Path | None:
        """Resolve a manifest/path value only when it stays under the library root."""
        candidate_value = Path(relative_path)
        if candidate_value.is_absolute() or ".." in candidate_value.parts:
            return None
        candidate = (self.root / candidate_value).resolve(strict=False)
        try:
            if not candidate.is_relative_to(self._root_resolved):
                return None
        except ValueError:
            return None
        return candidate

    def _relative_path(self, path: Path) -> str | None:
        try:
            resolved = path.resolve(strict=False)
            if not resolved.is_relative_to(self._root_resolved):
                return None
            return resolved.relative_to(self._root_resolved).as_posix()
        except (OSError, ValueError):
            return None

    def validate_file(self, path: Path) -> dict[str, object]:
        """Validate path safety, size, signature, dimensions, and image decoding."""
        relative_path = self._relative_path(path)
        invalid = {"path": relative_path or str(path), "valid": False, "reason": "unsafe path"}
        if relative_path is None or path.is_symlink() or not path.is_file():
            return invalid
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            return {**invalid, "reason": "unsupported extension"}
        try:
            size_bytes = path.stat().st_size
            if size_bytes <= 0 or size_bytes > self.max_file_bytes:
                return {**invalid, "reason": "file size outside configured limit", "size_bytes": size_bytes}
            with path.open("rb") as stream:
                prefix = stream.read(12)
            signatures = {
                ".gif": prefix[:6] in {b"GIF87a", b"GIF89a"},
                ".png": prefix.startswith(b"\x89PNG\r\n\x1a\n"),
                ".jpg": prefix.startswith(b"\xff\xd8\xff"),
                ".jpeg": prefix.startswith(b"\xff\xd8\xff"),
                ".webp": prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP",
            }
            if not signatures[suffix]:
                return {**invalid, "reason": "signature does not match extension", "size_bytes": size_bytes}
            with Image.open(path) as image:
                image_format = str(image.format or "").lower()
                width, height = image.size
                frame_count = int(getattr(image, "n_frames", 1) or 1)
                image.verify()
            expected_format = {".jpg": "jpeg", ".jpeg": "jpeg"}.get(suffix, suffix[1:])
            if image_format != expected_format:
                return {**invalid, "reason": "decoded format does not match extension", "size_bytes": size_bytes}
            if suffix == ".gif" and frame_count < 2:
                return {**invalid, "reason": "GIF is not animated", "size_bytes": size_bytes}
            if not (2 <= width <= MAX_REACTION_DIMENSION and 2 <= height <= MAX_REACTION_DIMENSION):
                return {**invalid, "reason": "dimensions outside usable range", "size_bytes": size_bytes}
            digest = sha256(path.read_bytes()).hexdigest()
            return {
                "path": relative_path,
                "valid": True,
                "format": image_format,
                "size_bytes": size_bytes,
                "width": width,
                "height": height,
                "frame_count": frame_count,
                "sha256": digest,
            }
        except (OSError, UnidentifiedImageError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError) as exc:
            return {**invalid, "reason": f"image decode failed: {type(exc).__name__}"}

    def _metadata_for(self, relative_path: str, metadata: Mapping[str, Mapping[str, object]] | None) -> Mapping[str, object]:
        if metadata and relative_path in metadata:
            return metadata[relative_path]
        return {}

    @staticmethod
    def _inferred_category(relative_path: str) -> str:
        parts = relative_path.split("/")
        return parts[0] if len(parts) > 1 else "root"

    @staticmethod
    def _inferred_tags(relative_path: str) -> tuple[str, ...]:
        stem = Path(relative_path).stem.lower().replace("-", "_")
        tokens = {token for token in re.split(r"[^a-z0-9]+", stem) if token}
        if "anime" in relative_path.lower():
            tokens.add("anime")
        return tuple(sorted(tokens))

    def _asset_from_result(self, result: Mapping[str, object], metadata: Mapping[str, Mapping[str, object]] | None) -> ReactionAsset:
        relative_path = str(result["path"])
        extra = self._metadata_for(relative_path, metadata)
        raw_tags_value = extra.get("tags")
        raw_tags = raw_tags_value if isinstance(raw_tags_value, (list, tuple, set)) else self._inferred_tags(relative_path)
        tags = tuple(sorted({str(tag).strip().lower() for tag in raw_tags if str(tag).strip()}))
        return ReactionAsset(
            path=self.root / Path(relative_path),
            relative_path=relative_path,
            category=str(extra.get("category") or self._inferred_category(relative_path)),
            tags=tags,
            format=str(result["format"]),
            size_bytes=int(str(result["size_bytes"])),
            width=int(str(result["width"])),
            height=int(str(result["height"])),
            frame_count=int(str(result["frame_count"])),
            sha256=str(result["sha256"]),
            source_url=str(extra["source_url"]) if extra.get("source_url") else None,
            source_page_url=str(extra["source_page_url"]) if extra.get("source_page_url") else None,
            source_license_url=str(extra["source_license_url"]) if extra.get("source_license_url") else None,
            source_commit=str(extra["source_commit"]) if extra.get("source_commit") else None,
            license_status=str(extra.get("license_status") or "unknown"),
            provenance=str(extra.get("provenance") or "local file; source not recorded"),
        )

    def scan(self, metadata: Mapping[str, Mapping[str, object]] | None = None) -> ScanResult:
        if self._scan_cache is not None and self._scan_cache_max_bytes == self.max_file_bytes:
            return self._scan_cache
        assets: list[ReactionAsset] = []
        invalid: list[dict[str, object]] = []
        duplicates: dict[str, list[str]] = {}
        seen: dict[str, str] = {}
        if not self.root.is_dir():
            result = {"assets": assets, "invalid": invalid, "duplicates": duplicates}
            self._scan_cache = result
            self._scan_cache_max_bytes = self.max_file_bytes
            return result
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name in {MANIFEST_FILENAME, "manifest.json.tmp"}:
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            result = self.validate_file(path)
            if not result.get("valid"):
                invalid.append(dict(result))
                continue
            digest = str(result["sha256"])
            relative_path = str(result["path"])
            if digest in seen:
                duplicates.setdefault(digest, [seen[digest]]).append(relative_path)
                continue
            seen[digest] = relative_path
            assets.append(self._asset_from_result(result, metadata))
        result = {"assets": assets, "invalid": invalid, "duplicates": duplicates}
        self._scan_cache = result
        self._scan_cache_max_bytes = self.max_file_bytes
        return result

    def discover_assets(self, metadata: Mapping[str, Mapping[str, object]] | None = None) -> list[ReactionAsset]:
        return list(self.scan(metadata)["assets"])

    def load_manifest(self) -> dict[str, object] | None:
        path = self.root / MANIFEST_FILENAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
                return None
            return payload
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None

    def manifest_metadata(self) -> dict[str, Mapping[str, object]]:
        signature = self._manifest_file_signature()
        if self._manifest_metadata_cache is not None and signature == self._manifest_signature:
            return dict(self._manifest_metadata_cache)
        payload = self.load_manifest() or {}
        result: dict[str, Mapping[str, object]] = {}
        raw_assets = payload.get("assets", [])
        if not isinstance(raw_assets, list):
            self._manifest_metadata_cache = result
            self._manifest_signature = signature
            return dict(result)
        for item in raw_assets:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                result[item["path"]] = item
        self._manifest_metadata_cache = result
        self._manifest_signature = signature
        return dict(result)

    def build_manifest(self, metadata: Mapping[str, Mapping[str, object]] | None = None) -> dict[str, object]:
        metadata = metadata or self.manifest_metadata()
        scan = self.scan(metadata)
        assets = [asset.manifest_record() for asset in scan["assets"]]
        return {
            "version": 1,
            "max_file_bytes": self.max_file_bytes,
            "assets": assets,
            "summary": {
                "valid_unique": len(assets),
                "invalid": len(scan["invalid"]),
                "duplicate_groups": len(scan["duplicates"]),
                "total_bytes": sum(int(str(asset["size_bytes"])) for asset in assets),
            },
        }

    def write_manifest(self, metadata: Mapping[str, Mapping[str, object]] | None = None) -> dict[str, object]:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = self.build_manifest(metadata)
        temporary = self.root / "manifest.json.tmp"
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.root / MANIFEST_FILENAME)
        return payload

    @staticmethod
    def infer_category(text: str) -> str | None:
        lowered = text.lower()
        return next((category for category, pattern in CATEGORY_PATTERNS if pattern.search(lowered)), None)

    @staticmethod
    def automatic_category(text: str, answer: str = "") -> str | None:
        """Return a conservative local mood for an unsolicited reaction.

        This deliberately suppresses sensitive, private, security-related,
        and mention-manipulation content. Explicit media requests use the
        normal request path and are not silently converted into automatic
        reactions.
        """
        combined = f"{text}\n{answer}"
        if ReactionLibrary.is_serious_context(text, answer) or AUTOMATIC_SUPPRESS_PATTERN.search(combined) or AUTOMATIC_SARCASM_PATTERN.search(text):
            return None
        # The user's message must provide the mood signal. Letting a generic
        # assistant phrase such as "great question" trigger media would make
        # ordinary conversations look excited and cause false-positive GIFs.
        category = ReactionLibrary.infer_category(text)
        if category in AUTOMATIC_LOW_SIGNAL_CATEGORIES:
            return None
        if category and ReactionLibrary._category_match_is_negated(combined, category):
            return None
        return category

    @staticmethod
    def is_serious_context(text: str, context: str = "") -> bool:
        """Return true for explicit distress/sensitive disclosures or no-joke requests.

        This intentionally targets multi-word/contextual signals rather than
        suppressing every negative adjective such as ``frustrated``.
        """
        return bool(SERIOUS_CONTEXT_PATTERN.search(f"{text}\n{context}"))

    @staticmethod
    def _category_match_is_negated(text: str, category: str) -> bool:
        pattern = next((pattern for name, pattern in CATEGORY_PATTERNS if name == category), None)
        if pattern is None:
            return False
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 24):match.start()]
            if re.search(r"(?i)\b(?:not|never|no|isn't|wasn't|aren't|don't|didn't)\s*$", prefix):
                return True
        return False

    @classmethod
    def request_category(cls, text: str) -> str | None:
        lowered = text.lower()
        if not re.search(ACTION_WORDS, lowered):
            return None
        category = cls.infer_category(text)
        if not re.search(MEDIA_WORDS, lowered) and category is None:
            return None
        return category or "auto"

    def choose(self, text: str, answer: str = "", *, requested_category: str | None = None,
               recent_paths: Iterable[str] = ()) -> ReactionAsset | None:
        metadata = self.manifest_metadata()
        assets = self.discover_assets(metadata)
        if not assets:
            return None
        category = requested_category or self.infer_category(f"{text} {answer}")
        if category and category not in {"auto", "random"}:
            candidates = [asset for asset in assets if category in asset.tags]
            if not candidates:
                return None
        else:
            candidates = assets
        recent = set(recent_paths)
        fresh = [asset for asset in candidates if asset.relative_path not in recent]
        pool = fresh or candidates
        # Importing random here would make the asset library unnecessarily
        # stateful; the caller can still seed Python's process-wide RNG in tests.
        return random.choice(pool)
