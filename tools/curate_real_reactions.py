"""Download and index a reviewed subset of real GIFs from giffycdn.

This is an acquisition tool, not a runtime integration. It pins the source
repository commit, downloads individual files only, and writes a candidate
manifest with the source URL and conservative rights status. The caller must
preview the contact sheet and promote only the reviewed files into the active
library.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil
import sys

import httpx
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(r"C:\Users\Admin\AppData\Local\Temp\opencode\mimi-real-reactions")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SOURCE_REPO = "https://github.com/iceefruit/giffycdn"
SOURCE_LICENSE = f"{SOURCE_REPO}/blob/68e7a7837ab469f250cad0dde63a7d6b6d83e95c/LICENSE"
SOURCE_COMMIT = "68e7a7837ab469f250cad0dde63a7d6b6d83e95c"
RAW_BASE = f"https://raw.githubusercontent.com/iceefruit/giffycdn/{SOURCE_COMMIT}"
MAX_BYTES = 8 * 1024 * 1024

SELECTION = {
    "happy": 6,
    "yay": 5,
    "celebrate": 5,
    "laugh": 8,
    "surprised": 8,
    "confused": 6,
    "cry": 8,
    "sad": 5,
    "mad": 8,
    "shy": 8,
    "nervous": 6,
    "facepalm": 6,
    "pout": 6,
    "smile": 6,
    "wave": 6,
    "clap": 5,
    "shrug": 5,
    "stare": 5,
    "sleep": 5,
    "tired": 5,
    "wink": 5,
    "scared": 5,
    "cool": 4,
    "evillaugh": 5,
    "sigh": 5,
    "thumbsup": 5,
}

# Manually reviewed from candidate/contact-sheet previews. The omitted files
# were visibly male, mixed/unclear, non-reaction, or redundant. This keeps the
# active set female-character focused instead of blindly copying a repository.
REVIEWED = {
    "happy": [1, 2, 3, 4, 5, 6],
    "yay": [1, 2, 3, 4, 5],
    "celebrate": [1, 2, 5],
    "laugh": [2, 3, 5, 6, 7],
    "surprised": list(range(1, 9)),
    "confused": [1, 2, 3, 4, 6],
    "cry": [4, 6, 7, 8],
    "sad": list(range(1, 6)),
    "mad": [1, 2, 4, 5, 7],
    "shy": [1, 3, 4, 5, 6, 7, 8],
    "nervous": list(range(1, 7)),
    "facepalm": [3],
    "pout": list(range(1, 7)),
    "smile": list(range(1, 7)),
    "wave": [1, 3, 5, 6],
    "clap": [1, 4],
    "shrug": [1, 2, 3],
    "stare": list(range(1, 6)),
    "sleep": list(range(1, 6)),
    "tired": [2, 3, 4, 5],
    "wink": [2, 3, 4, 5],
    "scared": list(range(1, 6)),
    "cool": list(range(1, 5)),
    "evillaugh": list(range(1, 5)),
    "sigh": list(range(1, 6)),
    "thumbsup": [1, 3, 5],
}

TAGS = {
    "happy": ("happy", "joy"), "yay": ("happy", "celebrating", "excited"),
    "celebrate": ("celebrating", "happy"), "laugh": ("laughing", "joke"),
    "surprised": ("shock", "surprised"), "confused": ("confused", "thinking"),
    "cry": ("crying", "sad"), "sad": ("sad", "disappointed"),
    "mad": ("angry", "frustrated"), "shy": ("shy", "embarrassed"),
    "nervous": ("nervous", "panic"), "facepalm": ("facepalm", "frustrated"),
    "pout": ("disappointed", "angry", "awkward"), "smile": ("happy", "smile"),
    "wave": ("wave", "greeting", "goodbye"), "clap": ("clap", "celebrating"),
    "shrug": ("confused", "fair_enough"), "stare": ("judging", "suspicion"),
    "sleep": ("sleepy", "good_night"), "tired": ("sleepy", "bored"),
    "wink": ("smug", "mischievous"), "scared": ("nervous", "panic", "shock"),
    "cool": ("proud", "smug"), "evillaugh": ("mischievous", "smug"),
    "sigh": ("disappointed", "relieved"), "thumbsup": ("supportive", "proud"),
}


def font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def make_contact_sheet(root: Path, records: list[dict[str, object]]) -> Path:
    columns = 8
    tile_width, tile_height = 180, 145
    rows = (len(records) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "#202020")
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        x, y = (index % columns) * tile_width, (index // columns) * tile_height
        try:
            with Image.open(root / str(record["local_path"])) as image:
                image.seek(0)
                preview = image.convert("RGB")
                preview.thumbnail((170, 110))
                px = x + (tile_width - preview.width) // 2
                py = y + 3
                sheet.paste(preview, (px, py))
        except Exception:
            pass
        label = f"{record['source_category']}/{record['source_number']}"
        draw.text((x + 4, y + 116), label, fill="white", font=font(12))
        draw.text((x + 4, y + 130), f"{int(record['size_bytes']) // 1024} KB", fill="#bbbbbb", font=font(10))
    output = root / "contact-sheet.jpg"
    sheet.save(output, quality=86, optimize=True)
    return output


def main() -> None:
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    candidate_root = TEMP_ROOT / "candidate"
    candidate_root.mkdir(parents=True)
    records: list[dict[str, object]] = []
    with httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": "MimiBot-reaction-curator/1.0"}) as client:
        for category, count in SELECTION.items():
            for number in range(1, count + 1):
                relative = f"{category}/{number}.gif"
                url = f"{RAW_BASE}/{relative}"
                response = client.get(url)
                response.raise_for_status()
                body = response.content
                if len(body) == 0 or len(body) > MAX_BYTES:
                    continue
                local = candidate_root / category / f"{number:02d}.gif"
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(body)
                with Image.open(local) as image:
                    if image.format != "GIF" or int(getattr(image, "n_frames", 1) or 1) < 2:
                        local.unlink()
                        continue
                    width, height = image.size
                    frame_count = int(image.n_frames)
                records.append({
                    "local_path": local.relative_to(candidate_root).as_posix(),
                    "source_category": category,
                    "source_number": number,
                    "source_url": url,
                    "source_page_url": f"{SOURCE_REPO}/blob/{SOURCE_COMMIT}/{relative}",
                    "source_repo": SOURCE_REPO,
                    "source_commit": SOURCE_COMMIT,
                    "source_license_url": SOURCE_LICENSE,
                    "license_status": "repository-MIT; individual-media-rights-unknown",
                    "provenance": "Downloaded as an individual GIF from the pinned giffycdn repository; repository license verified, individual anime-media rights not independently verified.",
                    "tags": list(TAGS[category]),
                    "size_bytes": len(body),
                    "width": width,
                    "height": height,
                    "frame_count": frame_count,
                })
    (candidate_root / "candidates.json").write_text(json.dumps({"source_repo": SOURCE_REPO, "source_commit": SOURCE_COMMIT, "assets": records}, indent=2) + "\n", encoding="utf-8")
    sheet = make_contact_sheet(candidate_root, records)
    print(json.dumps({"candidate_root": str(candidate_root), "count": len(records), "bytes": sum(int(x["size_bytes"]) for x in records), "contact_sheet": str(sheet)}, indent=2))


def promote_reviewed() -> None:
    """Replace the active library with the manually reviewed real GIFs."""
    from services.reactions import ReactionLibrary

    candidate_root = TEMP_ROOT / "candidate"
    candidate_manifest = json.loads((candidate_root / "candidates.json").read_text(encoding="utf-8"))
    by_key = {(str(item["source_category"]), int(item["source_number"])): item for item in candidate_manifest["assets"]}
    root = PROJECT_ROOT / "config" / "reactions"
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".gif", ".png", ".jpg", ".jpeg", ".webp"}:
            path.unlink()
    for path in (root / "manifest.json", root / "manifest.json.tmp"):
        path.unlink(missing_ok=True)

    metadata: dict[str, dict[str, object]] = {}
    root_targets = {"happy": ("happy", 1), "confused": ("confused", 1), "shock": ("surprised", 1), "sad": ("sad", 1), "angry": ("mad", 1)}
    copied = 0
    for source_category, numbers in REVIEWED.items():
        for number in numbers:
            record = by_key[(source_category, number)]
            if (source_category, number) in root_targets.values():
                target_name = next(name for name, key in root_targets.items() if key == (source_category, number))
                target = root / f"{target_name}.gif"
            else:
                semantic_folder = "social" if source_category in {"wave", "clap", "shrug", "wink", "thumbsup"} else "gaming" if source_category in {"cool", "evillaugh", "facepalm"} else "emotions"
                target = root / "anime" / semantic_folder / f"{source_category}_{number:02d}.gif"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate_root / str(record["local_path"]), target)
            relative = target.relative_to(root).as_posix()
            metadata[relative] = {
                "category": "root" if target.parent == root else "anime",
                "tags": list(TAGS[source_category]),
                "source_url": record["source_url"],
                "source_page_url": record["source_page_url"],
                "source_license_url": record["source_license_url"],
                "source_commit": record["source_commit"],
                "license_status": record["license_status"],
                "provenance": record["provenance"],
            }
            copied += 1

    library = ReactionLibrary(root)
    manifest = library.write_manifest(metadata)
    records = manifest["assets"]
    assert isinstance(records, list)
    if len(records) < 100:
        raise RuntimeError(f"Only {len(records)} valid unique reviewed GIFs remain")
    if any(str(item.get("format")) != "gif" or int(item.get("frame_count", 0)) < 2 for item in records if isinstance(item, dict)):
        raise RuntimeError("Active collection contains a non-animated or non-GIF asset")
    print(json.dumps({"copied_reviewed": copied, "valid_unique": len(records), "total_bytes": manifest["summary"]["total_bytes"], "manifest": str(root / "manifest.json")}, indent=2))


if __name__ == "__main__":
    if "--promote" in sys.argv:
        promote_reviewed()
    else:
        main()
