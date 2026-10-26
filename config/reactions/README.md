# Mimi local reaction library

Mimi sends reaction media only from this directory. She never downloads random files at runtime and never makes a second AI request just to choose an asset.

## Layout

- `happy.gif`, `confused.gif`, `shock.gif`, `sad.gif`, and `angry.gif` remain at the root for backward compatibility.
- `anime/emotions/`, `anime/social/`, and `anime/gaming/` contain the broader curated collection.
- `manifest.json` is generated from the files that are actually present. It records relative path, tags, format, byte size, dimensions, frame count, SHA-256, provenance, and validation status.

The bundled collection contains real animated GIFs from existing anime scenes, curated from the pinned `iceefruit/giffycdn` repository. The active files were previewed, checked for actual animation, decoded successfully, deduplicated, and kept below the existing 8 MiB limit. The repository's MIT license is recorded, but individual anime-media rights are explicitly marked unknown because they were not independently verified.

## Adding an asset

Use a descriptive filename and one of `.gif`, `.png`, `.jpg`, `.jpeg`, or `.webp`. Keep files below the configured 8 MiB limit; smaller reactions are preferred. The validator checks path safety, extension/signature agreement, decodability, dimensions, size, and duplicate SHA-256 hashes. Invalid or duplicate files are ignored by selection.

After adding files manually, rebuild the manifest with the existing library scanner or repeat the reviewed acquisition process. Do not rename a static image to `.gif`: animated GIFs must decode with at least two frames.

The curation record is retained in `tools/curate_real_reactions.py`; it downloads individual pinned source files only and does not run at bot runtime.

## Selection behaviour

- Explicit requests such as `send me a shocked anime GIF` are mapped locally to tags and do not consume AI tokens.
- Generic requests such as `send me a GIF` choose from the valid local collection.
- Ordinary messages only receive an occasional contextual reaction when `REACTION_PROBABILITY` permits it and the text has a clear matching emotion. Explanations and serious distress do not get random celebratory media.
- Automatic reactions use a per-channel cooldown and recent-path avoidance. Explicit requests bypass the automatic cooldown but still use safe validation.
- Uploads use `discord.File(...)`; failures are logged by exception class and do not expose private conversation content.
