"""Pictures and PDFs in the chat (owner 2026-10-25 11:42: "can you make it so loki gives me jpg or pdf images in the
chat?"). When a reply names a picture or a PDF LOKI made, the window shows it right there (app/ui/chat_media.js):

  GET  /chat/media?path=<p>&page=<n>   a picture (as a data URL, with its size) or a PDF page (rendered to a picture,
                                       with the page count) - only pictures and PDFs, only from the workspace or
                                       ~/LOKI Projects (where Studio's agents work), never anywhere else
  POST /chat/media/open     {path}            open it in the computer's own app (Preview / Photos / the PDF reader)
  POST /chat/media/convert  {path, to}        save a copy as JPG or as PDF beside it (Pillow); returns the new path

A path may be absolute (inside those folders), relative to the workspace, or relative to LOKI Projects.
"""
from __future__ import annotations

import base64
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


def get(state: Any, raw: str, page: int = 1) -> dict:
    path = find(state, raw)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise MediaError("too large to show (%d MB)" % (size // 1_000_000))
    out = {"ok": True, "name": path.name, "path": str(path), "size": size}
    suffix = path.suffix.lower()
    if suffix in IMAGES:
        data = path.read_bytes()
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
        if method == "POST" and path == "/chat/media/open":
            return 200, open_file(state, str(body.get("path") or ""))
        if method == "POST" and path == "/chat/media/convert":
            return 200, convert(state, str(body.get("path") or ""), str(body.get("to") or ""))
    except MediaError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except (OSError, ValueError) as exc:
        return 400, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
