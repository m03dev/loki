"""What LOKI made: the pictures, videos, sketches, sounds and games in the workspace, newest
first, for Settings > Creations and the creations hall in LOKI World.

Files are read straight from the workspace folders the makers write to (images/ from the image
specialist and Higgsfield, videos/ from the video tools, sketches/ from the sketch pad, media/
from the media specialist, music/ from make_music, voice/ from speak, games/ from the Pixel
Engine). Nothing is copied or indexed.

Session 28: every picture or video made from Creations gets a small metadata sidecar,
`<kind>/.meta/<file>.json` = {idea, prompt, negative, style, backend, seed, aspect, liked, daily,
parent}, so the wall can show the prompt on hover, star a favourite, "make more like this"
(same prompt and style, the next seeds) and "animate this" (image-to-video). Delete never
deletes: the file and its sidecar move to `<workspace>/trash/<kind>/`.

API kept for other callers (the MMO, the bridge): list_creations(workspace, limit),
creation_file(workspace, route), make_image(agent, prompt) - new arguments are keywords only.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

AUDIO = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}
KINDS = {
    "images": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "videos": {".mp4", ".webm", ".mov"},
    "sketches": {".png"},
    "media": {".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".webm"},
    "music": set(AUDIO),
    "voice": set(AUDIO),
}
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mp3": "audio/mpeg",
         ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac"}
SHOWN = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
         ".mp4": "video", ".webm": "video", ".mov": "video", ".mp3": "audio", ".m4a": "audio", ".wav": "audio",
         ".ogg": "audio", ".flac": "audio"}
META_DIR = ".meta"
TRASH = "trash"
META_KEYS = ("idea", "prompt", "negative", "style", "backend", "seed", "aspect", "liked", "daily", "parent", "model")
# Sizes for each aspect ratio, about one megapixel, multiples of 64 (Z-Image / FLUX / SDXL all like these).
ASPECTS = {"1:1": (1024, 1024), "4:3": (1152, 896), "3:4": (896, 1152), "3:2": (1216, 832), "2:3": (832, 1216),
           "16:9": (1344, 768), "9:16": (768, 1344)}


def title_of(name: str) -> str:
    """'20261014-201742-red-fox-in-studio-light.jpg' -> 'Red fox in studio light'."""
    stem = Path(name).stem
    stem = re.sub(r"^(sketch-|higgsfield-)?\d{8}-\d{6}-?", "", stem)
    words = re.sub(r"[-_]+", " ", stem).strip()
    return (words[:1].upper() + words[1:])[:90] if words else Path(name).stem[:90]


# ----------------------------------------------------------------------------- metadata sidecars
def _split(rel: str) -> tuple:
    rel = str(rel or "").replace("\\", "/").strip("/")
    if rel.startswith("creations/"):
        rel = rel[len("creations/"):]
    parts = rel.split("/")
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")


def resolve(workspace: Path, rel: str) -> Path | None:
    """'images/fox.png' -> that file, only inside the creation folders (same rules as the files route)."""
    kind, name = _split(rel)
    return creation_file(workspace, "/creations/%s/%s" % (kind, name)) if kind else None


def meta_path(workspace: Path, rel: str) -> Path | None:
    kind, name = _split(rel)
    if kind not in KINDS or not name or name in (".", "..") or "/" in name:
        return None
    return Path(workspace) / kind / META_DIR / (name + ".json")


def read_meta(workspace: Path, rel: str) -> dict:
    path = meta_path(workspace, rel)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_meta(workspace: Path, rel: str, **fields) -> dict:
    """Merge fields into a creation's sidecar (written atomically)."""
    path = meta_path(workspace, rel)
    if path is None:
        return {}
    data = {**read_meta(workspace, rel), **{k: v for k, v in fields.items() if k in META_KEYS or k == "t"}}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return {}
    return data


def set_liked(workspace: Path, rel: str, liked: bool = True) -> dict:
    """The star on a tile. {"ok", "liked"}."""
    if resolve(workspace, rel) is None:
        return {"ok": False, "error": "no such creation"}
    data = write_meta(workspace, rel, liked=bool(liked))
    return {"ok": bool(data), "liked": bool(data.get("liked")), "path": rel}


def delete_creation(workspace: Path, rel: str) -> dict:
    """Move a creation (and its sidecar) to <workspace>/trash/<kind>/ - never a hard delete."""
    found = resolve(workspace, rel)
    if found is None:
        return {"ok": False, "error": "no such creation"}
    kind, name = _split(rel)
    bin_dir = Path(workspace) / TRASH / kind
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / name
    if target.exists():
        target = bin_dir / ("%s-%d%s" % (Path(name).stem, int(time.time()), Path(name).suffix))
    try:
        os.replace(found, target)
        meta = meta_path(workspace, rel)
        if meta is not None and meta.is_file():
            (bin_dir / META_DIR).mkdir(parents=True, exist_ok=True)
            os.replace(meta, bin_dir / META_DIR / (target.name + ".json"))
    except OSError as exc:
        return {"ok": False, "error": "could not move it to the trash: %s" % exc}
    return {"ok": True, "trash": target.relative_to(Path(workspace)).as_posix()}


def liked_meta(workspace: Path, limit: int = 60) -> list:
    """Sidecars of the starred creations (the daily creation learns from these)."""
    out = []
    for kind in ("images", "videos"):
        folder = Path(workspace) / kind / META_DIR
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True)[:400]:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("liked"):
                out.append(data)
    return out[:limit]


# ----------------------------------------------------------------------------- the wall
def list_creations(workspace: Path, limit: int = 120) -> list:
    """Every creation, newest first: {kind, show, path, title, t, size} + its metadata
    (prompt, style, backend, seed, liked, ...) when it has a sidecar."""
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
    out = out[:limit]
    for c in out:
        meta = read_meta(workspace, c["path"])
        for key in META_KEYS:
            if key in meta:
                c[key] = meta[key]
        c["liked"] = bool(meta.get("liked"))
    return out


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


def styles() -> list:
    """The Fooocus style names for the style picker (engine/data/image_styles.json)."""
    try:
        import image_prompt  # pylint: disable=import-outside-toplevel
        return list(image_prompt.styles().keys())
    except Exception:  # noqa: BLE001
        return []


# ----------------------------------------------------------------------------- making
_MAKING: dict = {}
_LOCK = threading.Lock()


def making() -> list:
    """Pieces being made right now, and the last few results (for the wall's status line)."""
    with _LOCK:
        cutoff = time.time() - 600
        for key in [k for k, v in _MAKING.items() if v.get("end") and v["end"] < cutoff]:
            _MAKING.pop(key, None)
        return [dict(v) for v in _MAKING.values()]


def _start(kind: str, prompt: str, count: int = 1) -> tuple:
    key = "%d" % (time.time() * 1000)
    with _LOCK:
        while key in _MAKING:
            key = str(int(key) + 1)
        if sum(1 for v in _MAKING.values() if not v.get("end")) >= 3:
            return "", {"ok": False, "error": "three pieces are already being made - wait for one"}
        _MAKING[key] = {"id": key, "kind": kind, "prompt": prompt, "count": count, "start": time.time(), "end": 0,
                        "result": ""}
    return key, None


def _finish(key: str, out: str, ok: bool, **extra) -> None:
    with _LOCK:
        if key in _MAKING:
            _MAKING[key].update(end=time.time(), result=str(out)[:300], ok=bool(ok), **extra)


def prepare_prompt(agent, idea: str, style: str = "", enhance: bool = False, seed: int = 0) -> dict:
    """{"prompt", "negative", "style", "source"}: Fooocus' style template and, with enhance, the
    prompt expansion by LOKI's own model (offline expansion when no model answers)."""
    import image_prompt  # pylint: disable=import-outside-toplevel
    if enhance:
        ask = getattr(agent, "_port_ask", None)
        try:
            out = asyncio.run(image_prompt.enhance(idea, style, ask=ask, seed=int(seed or 0)))
        except Exception:  # noqa: BLE001 - the model is optional; the style still applies
            out = {"ok": False}
        if out.get("ok"):
            return {"prompt": out["prompt"], "negative": out["negative"], "style": out["style"], "source": out["source"]}
    positive, negative = image_prompt.apply_style(idea, style)
    found = image_prompt.find_style(style)
    return {"prompt": positive, "negative": negative, "style": found["name"] if found else "", "source": "style" if found else ""}


def _rel_in(workspace: Path, kind: str, file: str) -> str:
    """An absolute or relative file the maker reported -> 'images/<name>' when it is in that folder."""
    if not file:
        return ""
    p = Path(file)
    if not p.is_absolute():
        p = Path(workspace) / p
    try:
        if p.resolve().parent == (Path(workspace) / kind).resolve():
            return kind + "/" + p.name
    except OSError:
        pass
    return ""


def make_image(agent, prompt: str, *, style: str = "", enhance: bool = False, aspect: str = "1:1", count: int = 1,
               seed: int = 0, negative: str = "", raw: bool = False, idea: str = "", parent: str = "",
               daily: bool = False, thread: bool = True) -> dict:
    """Start the image specialist on `prompt` in a thread; returns at once.
    style = a Fooocus style name, enhance = expand the prompt with LOKI's model, aspect = '1:1' |
    '16:9' | ..., count = 1-4 variations (seeds seed, seed+1, ...), raw = use `prompt` as it is
    (make more like this), parent = the creation it came from."""
    count = max(1, min(int(count or 1), 4))
    key, refused = _start("image", prompt, count)
    if refused:
        return refused
    workspace = getattr(agent, "WORKSPACE", None)
    width, height = ASPECTS.get(str(aspect or "1:1"), ASPECTS["1:1"])
    aspect = aspect if aspect in ASPECTS else "1:1"
    seed = int(seed or 0)

    def work():
        try:
            if raw:
                ready = {"prompt": prompt, "negative": negative, "style": style, "source": "again"}
            else:
                ready = prepare_prompt(agent, prompt, style, enhance, seed)
            conductor = getattr(agent, "CONDUCTOR", None)
            result: dict = {}
            if conductor is not None and hasattr(conductor, "make_image"):
                result = conductor.make_image(ready["prompt"], {"width": width, "height": height, "seed": seed,
                                                                "count": count, "negative": ready["negative"]})
                if not result.get("ok"):
                    _finish(key, "error: " + str(result.get("error")), False)
                    return
                files = list(result.get("files") or [result.get("file")])
                seeds = list(result.get("seeds") or [result.get("seed", seed)])
                backend = result.get("backend", "")
                out = "made %s with %s%s" % (", ".join(map(str, files)), backend,
                                             (" (%s)" % result["note"]) if result.get("note") else "")
            else:   # an agent without the new conductor call (and the older tests)
                out = str(agent.conductor_tool("image", ready["prompt"]))
                match = re.match(r"made (.+?) with (\S+)", out)
                files, seeds = ([match.group(1)], [seed]) if match else ([], [])
                backend = match.group(2) if match else ""
            made = []
            if workspace is not None:
                for i, f in enumerate(files):
                    rel = _rel_in(Path(workspace), "images", str(f))
                    if not rel:
                        continue
                    write_meta(Path(workspace), rel, idea=idea or prompt, prompt=ready["prompt"],
                               negative=ready["negative"], style=ready["style"], backend=backend,
                               seed=seeds[i] if i < len(seeds) else seed, aspect=aspect, liked=False,
                               daily=bool(daily), parent=parent, model=str(result.get("model", "")), t=time.time())
                    made.append(rel)
            _finish(key, out, out.startswith("made "), files=made)
        except Exception as exc:  # noqa: BLE001
            _finish(key, "error: %s" % exc, False)

    if thread:
        threading.Thread(target=work, daemon=True, name="loki-make-image").start()
    else:
        work()
    return {"ok": True, "id": key}


# ----------------------------------------------------------------------------- likes (hearts)
# Settings > Creations: the owner gives a creation 0-5 hearts. LOKI World turns a picture's hearts
# into its painting's rarity (engine/mmo_state.py). Kept in <data>/creations/likes.json.
LIKES_MAX = 5
_LIKES_LOCK = threading.Lock()


def _likes_file(data_dir: Path) -> Path:
    return Path(data_dir) / "creations" / "likes.json"


def get_likes(data_dir: Path) -> dict:
    """{"images/fox.png": 3, ...} - only creations with at least one heart."""
    import json  # pylint: disable=import-outside-toplevel
    try:
        raw = json.loads(_likes_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for path, n in raw.items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if isinstance(path, str) and 0 < n:
            out[path[:300]] = min(LIKES_MAX, n)
    return out


def set_likes(data_dir: Path, path: str, hearts: int) -> int:
    """Set a creation's hearts (0 removes them). Returns how many it had before."""
    import json  # pylint: disable=import-outside-toplevel
    import os  # pylint: disable=import-outside-toplevel
    path = str(path or "")[:300]
    parts = path.split("/")
    if len(parts) != 2 or parts[0] not in KINDS or not parts[1] or ".." in path or "\\" in path:
        raise ValueError("not a creation path")
    hearts = max(0, min(LIKES_MAX, int(hearts)))
    with _LIKES_LOCK:
        likes = get_likes(data_dir)
        before = likes.get(path, 0)
        if hearts:
            likes[path] = hearts
        else:
            likes.pop(path, None)
        target = _likes_file(data_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(likes, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
    return before


def more_like(agent, rel: str, count: int = 4, thread: bool = True) -> dict:
    """'Make more like this': the same prompt, style, negative and aspect, the next seeds."""
    workspace = Path(getattr(agent, "WORKSPACE", "."))
    if resolve(workspace, rel) is None:
        return {"ok": False, "error": "no such creation"}
    meta = read_meta(workspace, rel)
    if not meta.get("prompt"):     # made before session 28: start again from its title
        return make_image(agent, title_of(rel.split("/")[-1]), count=count, parent=rel, thread=thread)
    return make_image(agent, meta["prompt"], raw=True, negative=meta.get("negative", ""), style=meta.get("style", ""),
                      aspect=meta.get("aspect", "1:1"), count=count, seed=int(meta.get("seed") or 0) + 1,
                      idea=meta.get("idea", ""), parent=rel, thread=thread)


def make_video(agent, prompt: str, *, image: str = "", seconds: float = 3.0, seed: int = 0, parent: str = "",
               thread: bool = True, maker=None) -> dict:
    """A short video in a thread (engine/creative.py: Wan2GP on the PC, else Higgsfield).
    image = a creation ('images/fox.png') to animate."""
    workspace = Path(getattr(agent, "WORKSPACE", "."))
    if image and resolve(workspace, image) is None:
        return {"ok": False, "error": "no such picture to animate"}
    key, refused = _start("video", prompt)
    if refused:
        return refused

    def work():
        try:
            import creative  # pylint: disable=import-outside-toplevel
            out = (maker or creative.make_video)(prompt, workspace, image=image, seconds=seconds, seed=seed)
            if not out.get("ok"):
                _finish(key, "error: %s" % out.get("error"), False)
                return
            write_meta(workspace, out["file"], idea=prompt, prompt=prompt, backend=out.get("backend", ""),
                       seed=out.get("seed", seed), parent=parent or image, liked=False, model=out.get("model", ""),
                       t=time.time())
            _finish(key, "made %s with %s" % (out["file"], out.get("backend")), True, files=[out["file"]])
        except Exception as exc:  # noqa: BLE001
            _finish(key, "error: %s" % exc, False)

    if thread:
        threading.Thread(target=work, daemon=True, name="loki-make-video").start()
    else:
        work()
    return {"ok": True, "id": key}


def animate(agent, rel: str, prompt: str = "", seconds: float = 3.0, thread: bool = True, maker=None) -> dict:
    """'Animate this': image-to-video from a picture on the wall, with its own prompt by default."""
    workspace = Path(getattr(agent, "WORKSPACE", "."))
    if resolve(workspace, rel) is None or not rel.startswith(("images/", "sketches/")):
        return {"ok": False, "error": "pick a picture to animate"}
    meta = read_meta(workspace, rel)
    text = (prompt or meta.get("idea") or meta.get("prompt") or title_of(rel.split("/")[-1])).strip()
    text += "" if prompt else ", gentle natural motion, the camera slowly pushes in"
    return make_video(agent, text, image=rel, seconds=seconds, seed=int(meta.get("seed") or 0), parent=rel,
                      thread=thread, maker=maker)
