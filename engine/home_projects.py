"""The home screen's preview hub: everything the owner is making, newest first, in one list.

    GET /home/projects        {ok, items: [...], errors: {source: "why"}, counts: {kind: n}}

Each item: {kind, name, path_or_id, updated (epoch seconds), thumb, status?, open: {mode, ...}}

  kind "made"    a picture, sprite, sketch or video LOKI made in the workspace (thumb / video = /creations/<path>)
  kind "render"  a render job: <data>/renders/<job>/manifest.json {name, kind, status, created, outputs, thumb}
                 (the Render tab writes them); open {mode: "render", job}
  kind "forge"   a Forge model or scene in the workspace's models/ (.glb, engine/forge3d.list_models);
                 open {mode: "forge", model}
  kind "godot"   a Godot game project in ~/LOKI Projects/<name> (engine/godot_web.projects);
                 open {mode: "godot", project}
  kind "studio"  a LOKI Studio session (<data>/studio/sessions/<id>/session.json); open {mode: "studio", session}
  kind "job"     a background / AI job on this machine or the worker farm (the job supervisor);
                 open {mode: "job", id}

`thumb` is a /creations/... URL the window can show (a picture LOKI made in the workspace) or a small data: URL
(a render's or a Godot project's own icon, at most THUMB_MAX bytes), else null. One source failing never fails the
whole answer: its error is reported under `errors` and the other kinds are still listed.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
KINDS = ("made", "render", "forge", "godot", "studio", "content", "job")
THUMB_MAX = 400_000
PER_KIND = 24
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}$")


def _data(state: Any) -> Path:
    agent = getattr(state, "agent", None)
    return Path(getattr(agent, "DATA_DIR", "") or os.getenv("LOKI_DATA") or (REPO / "harness_data"))


def _workspace(state: Any) -> Path:
    return Path(getattr(getattr(state, "agent", None), "WORKSPACE", "") or ".")


_THUMBS: dict = {}   # path -> ((mtime, size), url): Home asks every 5-15 s, a picture is read and encoded once
_THUMBS_MAX = 512


def data_url(path: Path) -> str | None:
    """A small picture as a data: URL (the window's CSP allows img-src data:), else None. Cached by path, mtime and
    size (owner 2026-10-25: "home is slow" - every refresh used to re-read and base64 every picture)."""
    try:
        p = Path(path)
        kind = IMAGE_TYPES.get(p.suffix.lower())
        if not kind:
            return None
        st = p.stat()
        if not p.is_file() or st.st_size > THUMB_MAX:
            return None
        key, sig = str(p), (st.st_mtime_ns, st.st_size)
        hit = _THUMBS.get(key)
        if hit and hit[0] == sig:
            return hit[1]
        url = "data:%s;base64,%s" % (kind, base64.b64encode(p.read_bytes()).decode("ascii"))
        if len(_THUMBS) >= _THUMBS_MAX:
            _THUMBS.clear()
        _THUMBS[key] = (sig, url)
        return url
    except OSError:
        return None


def _creation_url(workspace: Path, path: str) -> str | None:
    """A picture LOKI made inside the workspace's images/ (served at /creations/images/<file>)."""
    if not path:
        return None
    try:
        p = Path(path)
        p = p if p.is_absolute() else workspace / p
        rel = p.resolve().relative_to(workspace.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if rel.count("/") == 1 and rel.split("/")[0] in ("images", "sketches") and Path(rel).suffix.lower() in IMAGE_TYPES:
        return "/creations/" + rel
    return None


# ------------------------------------------------------------------ the sources
def renders(state: Any) -> list:
    root = _data(state) / "renders"
    out = []
    if not root.is_dir():
        return out
    for folder in root.iterdir():
        man = folder / "manifest.json"
        if not folder.is_dir() or not man.is_file() or not SAFE_ID.match(folder.name):
            continue
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):
            continue
        thumb = None
        cand = str(m.get("thumb") or "") or next((str(o) for o in (m.get("outputs") or []) if isinstance(o, str)
                                                 and Path(o).suffix.lower() in IMAGE_TYPES), "")
        if cand and "/" not in cand.replace("\\", "/").strip("/") and ".." not in cand:
            thumb = data_url(folder / cand)
        try:
            updated = float(m.get("updated") or m.get("created") or man.stat().st_mtime)
        except (TypeError, ValueError, OSError):
            updated = 0.0
        out.append({"kind": "render", "name": str(m.get("name") or folder.name)[:120], "path_or_id": folder.name,
                    "updated": updated, "thumb": thumb, "status": str(m.get("status") or "")[:40],
                    "detail": str(m.get("kind") or "")[:40], "outputs": len(m.get("outputs") or []),
                    "open": {"mode": "render", "job": folder.name}})
    return out


def forge(state: Any) -> list:
    import forge3d  # pylint: disable=import-outside-toplevel
    ws = _workspace(state)
    out = []
    for it in forge3d.list_models(ws / "models", limit=PER_KIND):
        name = str(it.get("prompt") or re.sub(r"^\d{8}-\d{6}-", "", it["name"]).rsplit(".", 1)[0] or it["name"])
        out.append({"kind": "forge", "name": name[:120], "path_or_id": "models/" + it["name"], "updated": float(it.get("t") or 0),
                    "thumb": _creation_url(ws, str(it.get("image") or "")), "status": "",
                    "detail": "%s triangles" % format(int(it["triangles"]), ",") if it.get("triangles") else "",
                    "open": {"mode": "forge", "model": it["name"]}})
    return out


def godot(state: Any) -> list:
    import godot_web  # pylint: disable=import-outside-toplevel
    out = []
    for pr in godot_web.projects():
        root = Path(pr["path"])
        try:
            updated = max([root.stat().st_mtime] + [p.stat().st_mtime for p in root.iterdir() if p.is_file()])
        except OSError:
            updated = 0.0
        thumb = None
        for icon in ("icon.png", "icon.svg", "icon.webp", "icon.jpg"):
            thumb = data_url(root / icon)
            if thumb:
                break
        out.append({"kind": "godot", "name": pr.get("label") or pr["name"], "path_or_id": pr["name"], "updated": updated,
                    "thumb": thumb, "status": "", "detail": "", "open": {"mode": "godot", "project": pr["name"]}})
    return out


def studio(state: Any) -> list:
    root = _data(state) / "studio" / "sessions"
    out = []
    if not root.is_dir():
        return out
    for meta in root.glob("*/session.json"):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or not m.get("id"):
            continue
        dest = m.get("destination") or {}
        what = "Godot project" if m.get("kind") == "godot" else str(dest.get("name") or dest.get("kind") or "LOKI")
        out.append({"kind": "studio", "name": str(m.get("title") or m["id"])[:120], "path_or_id": str(m["id"]),
                    "updated": float(m.get("updated") or m.get("created") or 0), "thumb": None,
                    "status": str(m.get("status") or "")[:40], "detail": what[:60],
                    "open": {"mode": "studio", "session": str(m["id"])}})
    return out


def jobs(state: Any) -> list:
    sup = getattr(state, "jobs", None)
    if sup is None:
        return []
    out = []
    for j in sup.store.all():
        if not j.get("id"):
            continue
        out.append({"kind": "job", "name": str(j.get("title") or j.get("prompt") or j["id"])[:120], "path_or_id": str(j["id"]),
                    "updated": float(j.get("finished") or j.get("updated") or j.get("started") or j.get("created") or 0),
                    "thumb": None, "status": str(j.get("status") or "")[:40],
                    "detail": str(j.get("machine") or j.get("backend") or "")[:60], "open": {"mode": "job", "id": str(j["id"])}})
    return out


CONTENT_DIR = "brand"            # what LOKI's agents make for the app's brand and marketing (name, logo, posts, ads)
CONTENT_TYPES = {".md", ".txt", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".gif", ".html", ".json"}


def content(state: Any) -> list:
    """Brand and marketing work in <workspace>/brand/ (owner 2026-10-22: "give them a task to make a logo and come up
    with a new name ... start doing ads and making social media content for the app") - every file, newest first,
    pictures with a thumbnail; a card opens the file in Files."""
    ws = _workspace(state)
    root = ws / CONTENT_DIR
    out: list = []
    if not root.is_dir():
        return out
    found: list = []   # (mtime, path): stat first, encode a thumbnail only for the newest PER_KIND
    for p in root.rglob("*"):
        try:
            if not p.is_file() or p.suffix.lower() not in CONTENT_TYPES or any(x.startswith(".") for x in p.relative_to(root).parts):
                continue
            found.append((p.stat().st_mtime, p))
        except (OSError, ValueError):
            continue
        if len(found) > 2000:
            break
    found.sort(key=lambda t: -t[0])
    for updated, p in found[:PER_KIND]:
        rel = p.relative_to(ws).as_posix()
        parts = p.relative_to(root).parts
        sub = parts[0] if len(parts) > 1 else ""
        out.append({"kind": "content", "name": p.stem.replace("_", " ").replace("-", " ")[:120], "path_or_id": rel,
                    "updated": updated, "thumb": data_url(p), "status": "",
                    "detail": (sub + " · " if sub else "") + p.suffix.lower().lstrip("."),
                    "open": {"mode": "files", "path": rel}})
    return out


MADE_KINDS = {"images": "image", "sprites": "image", "sketches": "image", "turnarounds": "image", "videos": "video"}


def made(state: Any) -> list:
    """What LOKI's makers wrote into the workspace - pictures, sprites, sketches, videos - as real previews (owner
    2026-10-26: "whats the point of the home middle collum if it doesnt have a thumbnail preview ... i dont wanna see
    folders or text i wanna see real results"). The picture itself is the thumbnail, served at /creations/<kind>/<file>
    (any size, no data URL in the payload)."""
    import creations  # pylint: disable=import-outside-toplevel
    ws = _workspace(state)
    out: list = []
    for c in creations.list_creations(ws, limit=PER_KIND * 3):
        kind = c["path"].split("/", 1)[0]
        show = MADE_KINDS.get(kind)
        if not show or c.get("show") != show:
            continue
        url = "/creations/" + c["path"]
        what = {"sprites": "sprite", "sketches": "sketch", "videos": "video", "turnarounds": "turnaround sheet"}.get(kind, "picture")
        out.append({"kind": "made", "name": c.get("title") or Path(c["path"]).stem, "path_or_id": c["path"],
                    "updated": float(c.get("t") or 0), "thumb": url if show == "image" else None,
                    "video": url if show == "video" else None, "status": "",
                    "detail": what + (" · " + str(c["prompt"])[:80] if c.get("prompt") else ""),
                    "open": {"mode": "files", "path": c["path"]}})
        if len(out) >= PER_KIND * 2:
            break
    return out


SOURCES: dict = {"made": made, "render": renders, "forge": forge, "godot": godot, "studio": studio, "content": content,
                 "job": jobs}


def collect(state: Any, sources: dict | None = None, clock: Callable[[], float] = time.time) -> dict:
    """Every kind, newest first; a source that fails is reported in `errors`, never fatal."""
    items: list = []
    errors: dict = {}
    counts: dict = {}
    for kind, fn in (sources or SOURCES).items():
        try:
            got = sorted(fn(state), key=lambda i: -float(i.get("updated") or 0))[:PER_KIND * (2 if kind == "made" else 1)]
        except Exception as exc:  # noqa: BLE001 - one source never takes the home screen down
            errors[kind] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            got = []
        counts[kind] = len(got)
        items.extend(got)
    items.sort(key=lambda i: -float(i.get("updated") or 0))
    return {"ok": True, "items": items, "errors": errors, "counts": counts, "t": clock()}


def route(state: Any, path: str) -> tuple | None:
    if path != "/home/projects":
        return None
    return 200, collect(state)
