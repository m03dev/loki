"""The Files view's API (session 29: documents & data) - browse the workspace, drop files in, preview them,
recent files, document collections. Called from engine/loki_bridge.py (behind the bearer token):

    GET  /files/list?dir=&root=          folders + files (no hidden files, no harness_data)
    GET  /files/preview?path=&root=&page=&sheet=   image | pdf page (picture + text) | table | markdown
    GET  /files/recent                   the files used lately (previewed, dropped in, made by LOKI)
    GET  /files/collections              document collections + their index status
    POST /files/collections {action: add|remove|index|search, folder, name, ocr, query}
    POST /files/open {path, root}        open in this computer's default app (documents/pictures/data only)
    POST /files/convert {path, root}     save the file as Markdown next to it (<name>.md)
    POST /files/upload?name=&dir=        the raw file bytes (drag & drop) -> copied into the workspace

`root` is "" (the workspace) or a collection's name (its folder). Every path is resolved inside its root;
anything that escapes, any hidden part and harness_data are refused. Standard library only.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HIDE = {"harness_data", "__pycache__", "node_modules", ".git", ".venv", "venv"}
MAX_UPLOAD_BYTES = int(os.getenv("LOKI_UPLOAD_MAX_MB", "500")) * 1024 * 1024
MAX_PREVIEW_IMAGE = 15 * 1024 * 1024
MAX_PREVIEW_CHARS = 200_000
MAX_LIST = 2000
OPEN_OK = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".tsv", ".txt", ".md", ".png", ".jpg",
           ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".epub", ".eml", ".odt", ".ods", ".odp", ".rtf",
           ".json", ".html", ".htm", ".mp3", ".wav", ".mp4", ".mov", ".m4a", ".ipynb"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml"}


class FilesError(ValueError):
    pass


def _agent(state):
    return getattr(state, "agent", None)


def workspace(state) -> Path:
    return Path(getattr(_agent(state), "WORKSPACE", "") or os.getenv("LOKI_WORKSPACE", "") or ".").resolve()


def data_dir(state) -> Path:
    agent = _agent(state)
    found = getattr(agent, "DATA_DIR", "") if agent is not None else ""
    return Path(found or os.getenv("LOKI_DATA", "") or "harness_data")


def root_of(state, root: str = "") -> Path:
    if not root:
        return workspace(state)
    import knowledge  # pylint: disable=import-outside-toplevel
    for coll in knowledge.list_collections(data_dir(state)):
        if coll["name"].lower() == str(root).lower():
            return Path(coll["folder"]).resolve()
    raise FilesError("no collection called %s" % root)


def resolve(base: Path, rel: str) -> Path:
    rel = str(rel or "").replace("\\", "/").strip().lstrip("/")
    target = (base / rel).resolve() if rel else base
    if target != base and base not in target.parents:
        raise FilesError("that path is outside the folder")
    parts = target.relative_to(base).parts
    if any(p.startswith(".") or p in HIDE for p in parts):
        raise FilesError("hidden and system folders are not shown")
    return target


def kind(path: Path) -> str:
    import doc_read  # pylint: disable=import-outside-toplevel
    return "dir" if path.is_dir() else doc_read.kind_of(path)


def listing(state, rel: str = "", root: str = "") -> dict:
    base = root_of(state, root)
    folder = resolve(base, rel)
    if not folder.is_dir():
        raise FilesError("no such folder")
    entries = []
    try:
        children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise FilesError("cannot open the folder: %s" % exc) from exc
    for child in children[:MAX_LIST]:
        if child.name.startswith(".") or child.name in HIDE or child.name.startswith("~$"):
            continue
        try:
            st = child.stat()
        except OSError:
            continue
        entries.append({"name": child.name, "path": child.relative_to(base).as_posix(), "dir": child.is_dir(),
                        "kind": kind(child), "size": 0 if child.is_dir() else st.st_size, "mtime": st.st_mtime})
    crumbs = [{"name": root or "Workspace", "path": ""}]
    acc = []
    for part in folder.relative_to(base).parts:
        acc.append(part)
        crumbs.append({"name": part, "path": "/".join(acc)})
    return {"ok": True, "root": root, "base": str(base), "dir": "" if folder == base else folder.relative_to(base).as_posix(),
            "crumbs": crumbs, "entries": entries,
            "truncated": len(children) > MAX_LIST}


# --------------------------------------------------------------------------- recent files
def _recent_file(state) -> Path:
    return data_dir(state) / "documents" / "recent.json"


def recent(state) -> list:
    try:
        items = json.loads(_recent_file(state).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        try:
            base = root_of(state, it.get("root", ""))
            p = resolve(base, it.get("path", ""))
        except (FilesError, OSError):
            continue
        if p.is_file():
            out.append({**it, "name": p.name, "kind": kind(p), "size": p.stat().st_size})
    return out[:20]


def touch(data: Path, rel: str, root: str = "", how: str = "opened") -> None:
    """Remember a file as recently used (data = harness_data). Never raises."""
    path = Path(data) / "documents" / "recent.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
        items = items if isinstance(items, list) else []
    except (OSError, ValueError):
        items = []
    items = [i for i in items if not (i.get("path") == rel and i.get("root", "") == root)]
    items.insert(0, {"path": rel, "root": root, "t": time.time(), "how": how})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[:40], indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


# --------------------------------------------------------------------------- preview
def preview(state, rel: str, root: str = "", page: int = 1, sheet: str = "") -> dict:
    import doc_read  # pylint: disable=import-outside-toplevel
    base = root_of(state, root)
    path = resolve(base, rel)
    if not path.is_file():
        raise FilesError("no such file")
    st = path.stat()
    k = doc_read.kind_of(path)
    out = {"ok": True, "name": path.name, "path": path.relative_to(base).as_posix(), "root": root, "size": st.st_size,
           "mtime": st.st_mtime, "type": k}
    touch(data_dir(state), out["path"], root)
    suffix = path.suffix.lower()
    if suffix in IMAGE_MIME:
        if st.st_size > MAX_PREVIEW_IMAGE:
            return {**out, "kind": "other", "note": "too large to preview"}
        data = path.read_bytes()
        w, h = doc_read.image_size(data)
        return {**out, "kind": "image", "width": w, "height": h,
                "data_url": "data:%s;base64,%s" % (IMAGE_MIME[suffix], base64.b64encode(data).decode())}
    if k == "pdf":
        doc = doc_read.convert_cached(path, data_dir(state) / "documents" / "cache", ocr="off")
        pages = doc.get("pages") or doc_read.pdf_page_count(path)
        page = max(1, min(int(page or 1), max(1, pages)))
        sec = next((s for s in doc.get("sections") or [] if s.get("page") == page), None)
        png = doc_read._pdf_render_page(path, page - 1, scale=1.4) if doc_read.can_render_pdf() else b""  # noqa: SLF001
        return {**out, "kind": "pdf", "pages": pages, "page": page, "text": (sec or {}).get("text", "")[:40_000],
                "image": ("data:image/png;base64," + base64.b64encode(png).decode()) if png else "",
                "warnings": doc.get("warnings", []), "error": doc.get("error", ""),
                "note": "" if png else "Page pictures need the documents add-on (pypdfium2); the text is shown."}
    if suffix in doc_read.CSVS or suffix in doc_read.XLSX:
        if suffix in doc_read.CSVS:
            rows, total, _d = doc_read.csv_rows(path, 201)
            sheets, chosen = [], ""
        else:
            tables = doc_read.xlsx_tables(path, max_rows=201)
            sheets = [t["name"] for t in tables]
            pick = next((t for t in tables if t["name"] == sheet), tables[0] if tables else {"rows": [], "total_rows": 0, "name": ""})
            rows, total, chosen = pick["rows"], pick["total_rows"], pick["name"]
        return {**out, "kind": "table", "sheets": sheets, "sheet": chosen, "columns": [str(c) for c in (rows[0] if rows else [])],
                "rows": [[("" if c is None else str(c)) for c in r] for r in rows[1:201]], "total": max(0, total - 1)}
    doc = doc_read.convert_cached(path, data_dir(state) / "documents" / "cache", ocr="auto")
    if not doc.get("ok"):
        return {**out, "kind": "other", "error": doc.get("error", "")}
    md = doc_read.strip_anchors(doc.get("markdown", ""))
    return {**out, "kind": "markdown", "markdown": md[:MAX_PREVIEW_CHARS], "truncated": len(md) > MAX_PREVIEW_CHARS,
            "sections": [{"anchor": s["anchor"], "title": s["title"]} for s in doc.get("sections") or []][:300],
            "backend": doc.get("backend", ""), "warnings": doc.get("warnings", [])}


# --------------------------------------------------------------------------- actions
def open_default(state, rel: str, root: str = "", run=None) -> dict:
    base = root_of(state, root)
    path = resolve(base, rel)
    if not path.exists():
        raise FilesError("no such file")
    if path.is_file() and path.suffix.lower() not in OPEN_OK:
        raise FilesError("LOKI only opens documents, pictures and data files this way (not %s)" % (path.suffix or "files without a type"))
    run = run or subprocess.Popen
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # pylint: disable=no-member
    elif sys.platform == "darwin":
        run(["open", str(path)])
    else:
        run(["xdg-open", str(path)])
    touch(data_dir(state), path.relative_to(base).as_posix(), root)
    return {"ok": True}


def save_markdown(state, rel: str, root: str = "") -> dict:
    import doc_read  # pylint: disable=import-outside-toplevel
    base = root_of(state, root)
    path = resolve(base, rel)
    doc = doc_read.convert_cached(path, data_dir(state) / "documents" / "cache", ocr="auto")
    if not doc.get("ok"):
        raise FilesError(doc.get("error") or "could not read it")
    ws = workspace(state)
    target = (path.with_suffix(".md") if root == "" else ws / "converted" / (path.stem + ".md"))
    if target == path:
        target = path.with_name(path.stem + ".converted.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc["markdown"], encoding="utf-8")
    rel_out = target.relative_to(ws).as_posix()
    touch(data_dir(state), rel_out, "", "made")
    return {"ok": True, "path": rel_out}


_NAME_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    name = _NAME_BAD.sub("_", Path(str(name or "").replace("\\", "/")).name).strip().lstrip(".")
    if name.upper().split(".")[0] in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
        name = "_" + name
    return name[:180] or "file"


def save_upload(state, query: str, stream, length: int) -> tuple:
    """(status, json) - the raw body of a dropped file, copied into the workspace (uploads/ by default)."""
    q = parse_qs(query or "")
    name = safe_name((q.get("name") or ["file"])[0])
    folder_rel = (q.get("dir") or ["uploads"])[0]
    if length <= 0:
        return 400, {"ok": False, "error": "empty file"}
    if length > MAX_UPLOAD_BYTES:
        return 413, {"ok": False, "error": "the file is larger than %d MB" % (MAX_UPLOAD_BYTES // 1048576)}
    try:
        ws = workspace(state)
        folder = resolve(ws, folder_rel)
    except FilesError as exc:
        return 400, {"ok": False, "error": str(exc)}
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    stem, suffix, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / ("%s (%d)%s" % (stem, n, suffix))
        n += 1
    part = target.with_name(target.name + ".part")
    left = length
    try:
        with open(part, "wb") as fh:
            while left > 0:
                chunk = stream.read(min(1 << 20, left))
                if not chunk:
                    break
                fh.write(chunk)
                left -= len(chunk)
        if left:
            part.unlink(missing_ok=True)
            return 400, {"ok": False, "error": "the upload was cut off"}
        os.replace(part, target)
    except OSError as exc:
        part.unlink(missing_ok=True)
        return 500, {"ok": False, "error": "could not save it: %s" % exc}
    rel = target.relative_to(ws).as_posix()
    touch(data_dir(state), rel, "", "dropped in")
    return 200, {"ok": True, "path": rel, "name": target.name, "size": length}


def collections(state) -> dict:
    import knowledge  # pylint: disable=import-outside-toplevel
    data = data_dir(state)
    out = []
    for c in knowledge.list_collections(data):
        st = knowledge.collection_index(data, c).status()
        out.append({**c, "files": st["files"], "documents": st.get("documents", 0), "chunks": st["chunks"],
                    "indexed": st["t"], "complete": st["complete"], "indexing": st["indexing"],
                    "exists": Path(c["folder"]).is_dir()})
    return {"ok": True, "collections": out}


def collections_post(state, body: dict) -> dict:
    import knowledge  # pylint: disable=import-outside-toplevel
    data = data_dir(state)
    action = str(body.get("action") or "").lower()
    if action == "add":
        folder = str(body.get("folder") or "").strip()
        if not folder:
            raise FilesError("give a folder")
        target = Path(folder).expanduser()
        if not target.is_absolute():   # a folder of the workspace
            target = resolve(workspace(state), folder)
        got = knowledge.add_collection(data, target, str(body.get("name") or ""), bool(body.get("ocr")))
        if got.get("ok"):
            knowledge.collection_index(data, got["collection"]).ensure_fresh(max_age_s=0, background=True)
        return got
    if action == "remove":
        return knowledge.remove_collection(data, str(body.get("name") or ""))
    if action == "index":
        found = [c for c in knowledge.list_collections(data) if c["name"].lower() == str(body.get("name") or "").lower()]
        if not found:
            raise FilesError("no such collection")
        return {"ok": True, **knowledge.collection_index(data, found[0]).refresh(budget_s=float(body.get("budget") or 30))}
    if action == "search":
        return {"ok": True, "hits": knowledge.search_documents(data, str(body.get("query") or ""), top=int(body.get("top") or 6),
                                                              collection=str(body.get("name") or ""))}
    raise FilesError("action must be add, remove, index or search")


def handle(state, method: str, raw_path: str, body: dict) -> tuple:
    """(status, json) for a /files/* request."""
    parsed = urlparse(raw_path)
    route = parsed.path
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    try:
        if method == "GET":
            if route == "/files/list":
                return 200, listing(state, q.get("dir", ""), q.get("root", ""))
            if route == "/files/preview":
                return 200, preview(state, q.get("path", ""), q.get("root", ""), int(q.get("page") or 1), q.get("sheet", ""))
            if route == "/files/recent":
                return 200, {"ok": True, "files": recent(state)}
            if route == "/files/collections":
                return 200, collections(state)
        else:
            if route == "/files/collections":
                return 200, collections_post(state, body or {})
            if route == "/files/open":
                return 200, open_default(state, str(body.get("path") or ""), str(body.get("root") or ""))
            if route == "/files/convert":
                return 200, save_markdown(state, str(body.get("path") or ""), str(body.get("root") or ""))
    except FilesError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except (OSError, ValueError) as exc:
        return 400, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
