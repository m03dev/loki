"""Pictures and PDFs in the chat (owner 2026-10-25 11:42: "can you make it so loki gives me jpg or pdf images in the
chat?"). When a reply names a picture or a PDF LOKI made, the window shows it right there (app/ui/chat_media.js):

  GET  /chat/media?path=<p>&page=<n>   a picture (as a data URL, with its size) or a PDF page (rendered to a picture,
                                       with the page count) - only pictures and PDFs, only from the workspace or
                                       ~/LOKI Projects (where Studio's agents work), never anywhere else
  GET  /chat/media/ref?url=<https>     a reference picture from the web, fetched and cached by the engine (data URL)
  POST /chat/media/open     {path}            open it in the computer's own app (Preview / Photos / the PDF reader)
  POST /chat/media/convert  {path, to}        save a copy as JPG or as PDF beside it (Pillow); returns the new path

A path may be absolute (inside those folders), relative to the workspace, or relative to LOKI Projects.
"""
from __future__ import annotations

import base64
import re
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
MEDIA = set(IMAGES) | {".pdf"}
MAX_BYTES = 40 * 1024 * 1024


class MediaError(ValueError):
    pass


def bases(state: Any) -> list:
    out = []
    ws = getattr(getattr(state, "agent", None), "WORKSPACE", None)
    if ws:
        out.append(Path(ws).expanduser().resolve())
    try:
        import agent_folders  # pylint: disable=import-outside-toplevel
        out.append(agent_folders.projects_dir().expanduser().resolve())
    except Exception:  # noqa: BLE001
        pass
    return [b for i, b in enumerate(out) if b not in out[:i]]


def find(state: Any, raw: str) -> Path:
    raw = str(raw or "").strip().strip("`'\"")
    if not raw:
        raise MediaError("which file?")
    p = Path(os.path.expanduser(raw.replace("\\", "/") if sys.platform != "win32" else raw))
    roots = bases(state)
    candidates = [p] if p.is_absolute() else [b / p for b in roots]
    if not p.is_absolute() and len(p.parts) == 1:      # "fox.png": the makers' folders too (images/, sprites/ ...)
        candidates += [b / d / p for b in roots for d in MADE_DIRS]
    for c in candidates:
        try:
            c = c.resolve()
        except OSError:
            continue
        if not any(c == b or b in c.parents for b in roots):
            continue
        if any(part.startswith(".") for part in c.parts[len(Path(c.anchor).parts):]):
            continue                                   # hidden folders stay hidden
        if c.suffix.lower() not in MEDIA:
            raise MediaError("only pictures and PDFs are shown here")
        if c.is_file():
            return c
    raise MediaError("no such picture or PDF in the workspace or LOKI Projects: %s" % raw)


def complete_image(data: bytes) -> bool:
    """Is this a whole picture (not one a maker is still writing)? Pillow's verify; without Pillow, the format's end
    marker (PNG IEND, JPEG FFD9)."""
    if not data:
        return False
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
        with Image.open(io.BytesIO(data)) as im:
            im.load()
        return True
    except ImportError:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return b"IEND" in data[-16:]
        if data[:2] == b"\xff\xd8":
            return data.rstrip(b"\x00")[-2:] == b"\xff\xd9"
        return True
    except Exception:  # noqa: BLE001 - truncated or not a picture
        return False


REF_DIR_NAME = "refcache"


def reference(state: Any, url: str, opener=None) -> dict:
    """A reference picture from the web (the Prompt Expert's matched prompts link pictures on other sites), fetched
    by the engine, cached, and handed to the window as a data URL - the window may only show its own pictures
    (img-src 'self' data:), so a web link stayed blank (2026-10-28, the Mac: cms-assets.youmind.com)."""
    import hashlib  # pylint: disable=import-outside-toplevel
    import ipaddress  # pylint: disable=import-outside-toplevel
    import socket  # pylint: disable=import-outside-toplevel
    import urllib.parse  # pylint: disable=import-outside-toplevel
    import urllib.request  # pylint: disable=import-outside-toplevel
    u = urllib.parse.urlparse(str(url or ""))
    if u.scheme != "https" or not u.hostname:
        raise MediaError("only https pictures")
    agent = getattr(state, "agent", None)
    data_dir = Path(getattr(agent, "DATA_DIR", "") or Path(__file__).resolve().parent.parent / "harness_data")
    cache = data_dir / REF_DIR_NAME
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    hit = next(iter(cache.glob(key + ".*")), None) if cache.is_dir() else None
    if hit is None:
        if opener is None:
            for info in socket.getaddrinfo(u.hostname, 443):          # never a request into the owner's own network
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise MediaError("not a public address")
        req = urllib.request.Request(url, headers={"User-Agent": "Loki/1.0"})
        with (opener or urllib.request.urlopen)(req, timeout=20) as resp:
            kind = str(resp.headers.get("Content-Type", "")).split(";")[0].strip().lower()
            data = resp.read(8 * 1024 * 1024 + 1)
        ext = {v: k for k, v in IMAGES.items()}.get(kind)
        if not ext or len(data) > 8 * 1024 * 1024 or not complete_image(data):
            raise MediaError("not a picture")
        cache.mkdir(parents=True, exist_ok=True)
        hit = cache / (key + ext)
        hit.write_bytes(data)
        for old in sorted(cache.glob("*"), key=lambda p: p.stat().st_mtime)[:-300]:   # a small cache
            try:
                old.unlink()
            except OSError:
                pass
    return {"ok": True, "data_url": "data:%s;base64,%s" % (IMAGES[hit.suffix.lower()], base64.b64encode(hit.read_bytes()).decode())}


def get(state: Any, raw: str, page: int = 1) -> dict:
    path = find(state, raw)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise MediaError("too large to show (%d MB)" % (size // 1_000_000))
    out = {"ok": True, "name": path.name, "path": str(path), "size": size}
    suffix = path.suffix.lower()
    if suffix in IMAGES:
        data = path.read_bytes()
        if not complete_image(data):
            # caught while a maker is still writing it (2026-10-28: previews of the pictures agents were working on
            # came out blank - the window cached a half-written file); the window asks again on its next redraw
            raise MediaError("still being written")
        w = h = 0
        try:
            import doc_read  # pylint: disable=import-outside-toplevel
            w, h = doc_read.image_size(data)
        except Exception:  # noqa: BLE001
            pass
        return {**out, "kind": "image", "width": w, "height": h,
                "data_url": "data:%s;base64,%s" % (IMAGES[suffix], base64.b64encode(data).decode())}
    import doc_read  # pylint: disable=import-outside-toplevel
    pages = 0
    try:
        pages = int(doc_read.pdf_page_count(path) or 0)
    except Exception:  # noqa: BLE001
        pages = 0
    page = max(1, min(int(page or 1), max(1, pages)))
    png = b""
    try:
        if doc_read.can_render_pdf():
            png = doc_read._pdf_render_page(path, page - 1, scale=1.3)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        png = b""
    return {**out, "kind": "pdf", "pages": pages, "page": page,
            "image": ("data:image/png;base64," + base64.b64encode(png).decode()) if png else "",
            "note": "" if png else "The page picture needs the documents add-on (pypdfium2) - Open shows the PDF."}


def open_file(state: Any, raw: str, run=None) -> dict:
    path = find(state, raw)
    run = run or subprocess.Popen
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # pylint: disable=no-member
    elif sys.platform == "darwin":
        run(["open", str(path)])
    else:
        run(["xdg-open", str(path)])
    return {"ok": True, "path": str(path)}


def convert(state: Any, raw: str, to: str) -> dict:
    path = find(state, raw)
    to = str(to or "").lower().lstrip(".")
    if to == "jpeg":
        to = "jpg"
    if to not in ("jpg", "pdf", "pixel"):
        raise MediaError("save as jpg, pdf or pixel")
    if path.suffix.lower() not in IMAGES:
        raise MediaError("only a picture can be saved as %s" % to.upper())
    if to == "pixel":                       # a game sprite of it (engine/pixel_art.py)
        import pixel_art  # pylint: disable=import-outside-toplevel
        try:
            res = pixel_art.pixelize(path, size=64)
        except pixel_art.PixelError as exc:
            raise MediaError(str(exc)) from None
        return {"ok": True, "path": res["file"], "name": Path(res["file"]).name, "preview": res["preview"]}
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise MediaError("saving as %s needs Pillow (pip install pillow)" % to.upper()) from exc
    target = path.with_suffix("." + to)
    k = 2
    while target.exists() and target != path:
        target = path.with_name("%s-%d.%s" % (path.stem, k, to))
        k += 1
    if target == path:
        return {"ok": True, "path": str(path), "name": path.name, "same": True}
    with Image.open(path) as im:
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[-1])
            im2 = flat
        else:
            im2 = im.convert("RGB")
        buf = io.BytesIO()
        if to == "jpg":
            im2.save(buf, "JPEG", quality=92)
        else:
            im2.save(buf, "PDF", resolution=150.0)
    target.write_bytes(buf.getvalue())
    return {"ok": True, "path": str(target), "name": target.name}


def route(state: Any, method: str, path: str, query: dict, body: dict) -> tuple:
    try:
        if method == "GET" and path == "/chat/media":
            return 200, get(state, query.get("path", ""), int(query.get("page") or 1))
        if method == "GET" and path == "/chat/media/ref":
            return 200, reference(state, query.get("url", ""))
        if method == "POST" and path == "/chat/media/open":
            return 200, open_file(state, str(body.get("path") or ""))
        if method == "POST" and path == "/chat/media/convert":
            return 200, convert(state, str(body.get("path") or ""), str(body.get("to") or ""))
    except MediaError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except (OSError, ValueError) as exc:
        return 400, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}


# ----------------------------------------------------------------------------- what a turn made, always shown
MADE_DIRS = ("images", "sprites", "turnarounds", "renders", "videos", "sketches", "media", "qa", "brand", "models", "audio")


def made_since(state: Any, t0: float, limit: int = 8) -> list:
    """Pictures and PDFs written into the workspace since t0 (a chat turn's start), newest last - whatever made them
    (the image tool, OpenCode, the shell agent, a Tool Shelf tool) and whether or not the reply names them."""
    roots = bases(state)[:1]
    found = []
    for root in roots:
        for sub in MADE_DIRS + ("",):
            folder = root / sub if sub else root
            if not folder.is_dir():
                continue
            pattern = "**/*" if sub else "*"
            try:
                for p in folder.glob(pattern):
                    if p.suffix.lower() in MEDIA and p.is_file() and p.stat().st_mtime >= t0 - 1 and not any(
                            part.startswith(".") for part in p.relative_to(root).parts):
                        found.append((p.stat().st_mtime, p.relative_to(root).as_posix()))
            except OSError:
                continue
    out = []
    for _, rel in sorted(set(found)):
        if rel not in out and not re.search(r"-x\d+\.png$", rel):      # pixel previews: the sprite itself is shown
            out.append(rel)
    return out[-limit:]


def with_made(text: str, made: list) -> str:
    """The reply, plus a line naming the files it made but did not name (the window shows each one in the chat)."""
    missing = [m for m in made if m not in (text or "") and Path(m).name not in (text or "")]
    if not missing:
        return text
    return (text or "").rstrip() + "\n\nMade: " + "  ".join("`%s`" % m for m in missing)
