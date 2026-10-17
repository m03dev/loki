"""What LOKI made: the pictures, videos, sketches, sounds and games in the workspace, newest
first, for Settings > Creations and the creations hall in LOKI World.

Files are read straight from the workspace folders the makers write to (images/ from the image
specialist and Higgsfield, videos/ from the video tools, sketches/ from the sketch pad, media/
from the media specialist, games/ from the Pixel Engine). Nothing is copied or indexed.
"""
from __future__ import annotations

import re
from pathlib import Path

KINDS = {
    "images": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "videos": {".mp4", ".webm", ".mov"},
    "sketches": {".png"},
    "media": {".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".webm"},
}
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mp3": "audio/mpeg",
         ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg"}
SHOWN = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
         ".mp4": "video", ".webm": "video", ".mov": "video", ".mp3": "audio", ".m4a": "audio", ".wav": "audio", ".ogg": "audio"}


def title_of(name: str) -> str:
    """'20261014-201742-red-fox-in-studio-light.jpg' -> 'Red fox in studio light'."""
    stem = Path(name).stem
    stem = re.sub(r"^(sketch-)?\d{8}-\d{6}-?", "", stem)
    words = re.sub(r"[-_]+", " ", stem).strip()
    return (words[:1].upper() + words[1:])[:90] if words else Path(name).stem[:90]


def list_creations(workspace: Path, limit: int = 120) -> list:
    """Every creation, newest first: {kind, show, path, title, t, size}."""
    out = []
    for kind, exts in KINDS.items():
        folder = Path(workspace) / kind
        if not folder.is_dir():
            continue
        try:
            files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
        except OSError:
            continue
        for p in files:
            try:
                st = p.stat()
            except OSError:
                continue
            out.append({"kind": kind, "show": SHOWN.get(p.suffix.lower(), "file"), "path": kind + "/" + p.name,
                        "title": title_of(p.name), "t": st.st_mtime, "size": st.st_size})
    out.sort(key=lambda c: c["t"], reverse=True)
    return out[:limit]


def creation_file(workspace: Path, route: str) -> Path | None:
    """Map /creations/<kind>/<file> to that file in the workspace, refusing anything else."""
    rel = route[len("/creations/"):]
    parts = rel.split("/")
    if len(parts) != 2 or parts[0] not in KINDS or not parts[1] or "\\" in rel or parts[1] in (".", ".."):
        return None
    root = (Path(workspace) / parts[0]).resolve()
    try:
        candidate = (root / parts[1]).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.suffix.lower() not in KINDS[parts[0]] or not candidate.is_file():
        return None
    return candidate


IDEAS = [
    "a red fox curled up asleep in fresh snow, soft morning light",
    "a pixel-art floating island with a tiny lighthouse at dusk",
    "a fox and a rabbit sharing tea in a mossy forest, storybook style",
    "a cel-shaded fox running through tall golden grass",
    "a cosy workshop full of little robots building a sky ship",
]

