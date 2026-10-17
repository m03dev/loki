"""LOKI Apps: small apps LOKI builds and runs for the owner (docs/APPS.md).

A mini-app is one folder <workspace>/apps/<name>/:

    manifest.json   {"name": "budget", "title": "Budget", "description": "...", "icon": "💰",
                     "entry": "index.html", "template": "budget", "created": t, "updated": t, "by": "loki"}
    index.html      loads /ui/appkit/appkit.css + /ui/appkit/appkit.js, then its own app.js
    app.js          the app (no inline scripts: the page's CSP is script-src 'self')
    app.css         optional

It runs in a sandboxed frame (allow-scripts only, an opaque origin: no token, no cookies, no
storage, no network - APP_CSP has connect-src 'none') and reaches LOKI only through the window's
postMessage bridge (app/ui/apps.js), which gives it:

  * storage   - per-app JSON key/values kept HERE, engine side (DATA_DIR/app_data/<app>.json),
                last-writer-wins per key with tombstones, synced to the owner's other machines
                over the signed peer link (sync_summary / sync_receive / sync_with);
  * ask LOKI  - one model call with the app's context (loki.app_ask);
  * files     - save into <workspace>/App files/<app>/ after the owner approves in the window,
                open a file the owner picks.

Templates (12+) ship in app/ui/appkit/templates/<name>/ and install with one click. Extensions can
bring an app too (extensions.py). Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import threading
import time
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
APP_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
             ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}
# The page of a mini-app: its own scripts and LOKI's kit only, no network at all, and sandboxed even
# when opened outside the frame. Inline styles are allowed (generated apps use them); inline scripts not.
APP_CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
           "font-src 'self' data:; media-src 'self' data: blob:; connect-src 'none'; frame-ancestors 'self'; "
           "base-uri 'none'; form-action 'none'; sandbox allow-scripts")
MAX_VALUE = 256_000          # one stored value, as JSON
MAX_STORE = 2_000_000        # one app's whole store
MAX_KEYS = 2000
MAX_APP_BYTES = 1_500_000    # one app's code (what is synced between machines)
MAX_FILE_SAVE = 5_000_000
KIT_LINKS = ('<link rel="stylesheet" href="/ui/appkit/appkit.css">', '<script src="/ui/appkit/appkit.js"></script>')
_LOCK = threading.RLock()


# ------------------------------------------------------------------ places

def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def templates_dir() -> Path:
    return repo_root() / "app" / "ui" / "appkit" / "templates"


def apps_dir(workspace: Path) -> Path:
    return Path(workspace) / "apps"


def data_dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root) / "app_data"
    explicit = os.getenv("LOKI_DATA", "").strip()
    return (Path(explicit) if explicit else repo_root() / "harness_data") / "app_data"


def host_name() -> str:
    try:
        import memory_store  # pylint: disable=import-outside-toplevel
        return memory_store.host_name()
    except Exception:  # noqa: BLE001
        return (socket.gethostname() or "this-machine")[:40]


def clean_name(name: str) -> str:
    name = str(name or "").strip().lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9_-]", "", name)[:40]
    if name and not name[0].isalpha():
        name = "app-" + name
    return name[:40]


def check_name(name: str) -> str:
    if not NAME_RE.match(str(name or "")):
        raise ValueError("an app name is 2-40 lowercase letters, digits, - or _ and starts with a letter")
    return name


def namespace(key: str) -> str:
    """The storage file for an app key ('budget', 't:budget' for a gallery preview, 'x:ext' for an extension app)."""
    key = str(key or "")
    kind, _, rest = key.partition(":") if ":" in key else ("", "", key)
    check_name(rest)
    if kind not in ("", "t", "x", "p"):
        raise ValueError("unknown app kind %r" % kind)
    return (kind + "--" + rest) if kind else rest


# ------------------------------------------------------------------ manifests and listing

def read_manifest(folder: Path) -> dict:
    try:
        meta = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp%d" % threading.get_ident())
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _present(folder: Path, kind: str, key: str) -> dict:
    meta = read_manifest(folder)
    entry = str(meta.get("entry") or "index.html")
    return {"key": key, "name": folder.name, "kind": kind, "title": str(meta.get("title") or folder.name)[:60],
            "description": str(meta.get("description") or "")[:300], "icon": str(meta.get("icon") or "")[:8],
            "category": str(meta.get("category") or "")[:30], "template": str(meta.get("template") or ""),
            "updated": float(meta.get("updated") or 0), "by": str(meta.get("by") or ""),
            "starters": [str(s)[:160] for s in (meta.get("customize") or [])][:4],
            "url": "/apps/%s/%s/%s" % (kind, folder.name, entry)}


def list_apps(workspace: Path) -> list:
    out = []
    root = apps_dir(workspace)
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and NAME_RE.match(folder.name) and (folder / "manifest.json").is_file():
                out.append(_present(folder, "w", folder.name))
    return out


def list_templates() -> list:
    out = []
    root = templates_dir()
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and NAME_RE.match(folder.name) and (folder / "manifest.json").is_file():
                out.append(_present(folder, "t", "t:" + folder.name))
    return out


def app_folder(kind: str, name: str, workspace: Path, ext_root: Path | None = None) -> Path | None:
    """The folder a served app lives in: w = workspace app, t = template (preview), x/p = extension app/panel."""
    if not NAME_RE.match(str(name or "")):
        return None
    if kind == "w":
        return apps_dir(workspace) / name
    if kind == "t":
        return templates_dir() / name
    if kind in ("x", "p") and ext_root is not None:
        try:
            import extensions  # pylint: disable=import-outside-toplevel
            return extensions.ui_folder(name, "app" if kind == "x" else "panel", ext_root)
        except Exception:  # noqa: BLE001
            return None
    return None


def app_file(route: str, workspace: Path, ext_root: Path | None = None) -> Path | None:
    """/apps/<w|t|x|p>/<name>/<file...> -> the file, refusing anything outside that app's folder."""
    parts = route.split("/", 4)   # '', 'apps', kind, name, rest
    if len(parts) < 5 or parts[1] != "apps" or not parts[4]:
        return None
    kind, name, rest = parts[2], parts[3], parts[4]
    if "\\" in rest or rest.startswith("/") or ".." in rest.split("/") or any(p.startswith(".") for p in rest.split("/")):
        return None
    folder = app_folder(kind, name, workspace, ext_root)
    if folder is None or not folder.is_dir():
        return None
    try:
        root = folder.resolve()
        candidate = (root / rest).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.suffix.lower() not in APP_TYPES or not candidate.is_file():
        return None
    return candidate


# ------------------------------------------------------------------ making and installing

def _fingerprint(folder: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() in APP_TYPES):
        rel = path.relative_to(folder).as_posix()
        if rel == "manifest.json":
            continue
        h.update(rel.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def standard_html(title: str, has_css: bool) -> str:
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>%s</title>\n%s\n%s%s\n"
            "<script src=\"app.js\" defer></script>\n</head>\n<body>\n<main id=\"app\" class=\"lk-app\"></main>\n</body>\n</html>\n"
            % (_esc(title), KIT_LINKS[0], KIT_LINKS[1], "\n<link rel=\"stylesheet\" href=\"app.css\">" if has_css else ""))


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def html_problems(html: str) -> list:
    """What would stop a page working under APP_CSP, said so a model can fix it."""
    problems = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL):
        attrs, body = m.group(1), m.group(2)
        if body.strip():
            problems.append("an inline <script> will not run (the page allows script files only): move it into app.js")
        src = re.search(r"src\s*=\s*[\"']([^\"']+)", attrs)
        if src and re.match(r"(?i)^(https?:)?//", src.group(1)):
            problems.append("%s is on the internet: apps run offline - use LOKI's kit (window.kit) or write it yourself"
                            % src.group(1)[:80])
    for m in re.finditer(r"<link\b[^>]*href\s*=\s*[\"']((?:https?:)?//[^\"']+)", html, flags=re.IGNORECASE):
        problems.append("%s is on the internet: apps cannot load it" % m.group(1)[:80])
    if re.search(r"\son[a-z]+\s*=\s*[\"']", html, flags=re.IGNORECASE):
        problems.append("inline event handlers (onclick=...) do not run: add listeners in app.js")
    return sorted(set(problems))


def js_problems(js: str) -> list:
    problems = []
    if re.search(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(", js):
        problems.append("the app has no network (connect-src 'none'): use loki.ask() for LOKI or loki.store for data")
    if re.search(r"\blocalStorage\b|\bsessionStorage\b|\bindexedDB\b", js):
        problems.append("localStorage/sessionStorage/indexedDB are blocked in the sandbox: use await loki.store.get/set (synced to your machines)")
    if re.search(r"(?<![\w.])(alert|confirm|prompt)\s*\(", js):
        problems.append("alert/confirm/prompt are blocked in the sandbox: use kit.toast / await kit.confirm / await kit.ask")
    if re.search(r"\beval\s*\(|new\s+Function\s*\(", js):
        problems.append("eval/new Function are blocked: write plain code")
    return problems


def make_app(workspace: Path, name: str, title: str = "", description: str = "", icon: str = "", html: str = "",
             js: str = "", css: str = "", files: dict | None = None, by: str = "loki", template: str = "",
             category: str = "", customize=None) -> dict:
    """Write (or update) <workspace>/apps/<name>/. Only the parts given are replaced."""
    name = clean_name(name)
    try:
        check_name(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    folder = apps_dir(workspace) / name
    old = read_manifest(folder)
    files = dict(files or {})
    if js:
        files["app.js"] = js
    if css:
        files["app.css"] = css
    if html:
        if "<html" not in html.lower():   # body markup only: wrap it in the standard page
            page = standard_html(title or old.get("title") or name, bool(css) or (folder / "app.css").is_file() or "app.css" in files)
            html = page.replace('<main id="app" class="lk-app"></main>', '<main id="app" class="lk-app">\n%s\n</main>' % html)
        files["index.html"] = html
    if not old and "index.html" not in files:
        files["index.html"] = standard_html(title or name, "app.css" in files)
    if not old and "app.js" not in files:
        return {"ok": False, "error": "a new app needs js (its app.js) - read app_builder_guide first"}
    problems, warnings = [], []
    total = 0
    for rel, text in files.items():
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel or ".." in rel.split("/") or rel.startswith(".") or Path(rel).suffix.lower() not in (".html", ".js", ".css", ".json", ".svg"):
            problems.append("%s: only .html/.js/.css/.json/.svg files inside the app folder" % rel)
            continue
        text = str(text)
        total += len(text.encode("utf-8"))
        if rel.endswith(".html"):
            problems += html_problems(text)
            if "/ui/appkit/appkit.js" not in text:
                warnings.append("%s does not load /ui/appkit/appkit.js - without it the app has no loki.* bridge" % rel)
        if rel.endswith(".js"):
            problems += js_problems(text)
    if total > MAX_APP_BYTES:
        problems.append("the app is larger than %d bytes" % MAX_APP_BYTES)
    if problems:
        return {"ok": False, "error": "not saved: " + "; ".join(sorted(set(problems)))}
    syntax = []
    for rel, text in files.items():
        if rel.endswith(".js"):
            err = _js_syntax(str(text))
            if err:
                syntax.append("%s: %s" % (rel, err))
    if syntax:
        return {"ok": False, "error": "not saved, JavaScript syntax error: " + "; ".join(syntax)}
    with _LOCK:
        folder.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            target = folder / str(rel).replace("\\", "/").strip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(text), encoding="utf-8")
        now = time.time()
        meta = dict(old)
        meta.update({"name": name, "title": str(title or old.get("title") or name.replace("-", " ").title())[:60],
                     "description": str(description or old.get("description") or "")[:300],
                     "icon": str(icon or old.get("icon") or "")[:8], "entry": old.get("entry") or "index.html",
                     "created": old.get("created") or now, "updated": now, "by": old.get("by") or by,
                     "template": template or old.get("template") or ""})
        if category:
            meta["category"] = str(category)[:30]
        if customize:
            meta["customize"] = [str(c)[:160] for c in customize][:4]
        meta["fingerprint"] = _fingerprint(folder)
        _write_json(folder / "manifest.json", meta)
        _unremove(name, None)
    nudge()
    return {"ok": True, "name": name, "updated": not not old, "warnings": warnings, "path": str(folder),
            "url": "/apps/w/%s/index.html" % name}


def _js_syntax(code: str) -> str:
    """A syntax error in JavaScript: node --check when node is here, else LOKI's bracket check; '' when fine."""
    node = shutil.which("node")
    if node:
        import subprocess  # pylint: disable=import-outside-toplevel
        import tempfile  # pylint: disable=import-outside-toplevel
        with tempfile.TemporaryDirectory(prefix="loki-app-") as tmp:
            path = Path(tmp) / "app.js"
            path.write_text(code, encoding="utf-8")
            try:
                proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                return ""
            if proc.returncode == 0:
                return ""
            lines = [ln for ln in (proc.stderr or "").splitlines() if ln.strip() and tmp not in ln]
            where = re.search(r"app\.js:(\d+)", proc.stderr or "")
            return (("line %s: " % where.group(1)) if where else "") + (" ".join(lines[-3:]) or "does not parse")[:400]
    try:
        import lint_guard  # pylint: disable=import-outside-toplevel
        return "; ".join(lint_guard.check("app.js", code))[:400]
    except Exception:  # noqa: BLE001 - no checker: the window shows the error instead
        return ""


def install_template(workspace: Path, template: str, name: str = "") -> dict:
    """Copy a gallery template into the workspace. The installed copy is the owner's to change."""
    template = str(template or "").strip()
    src = templates_dir() / template
    if not NAME_RE.match(template) or not (src / "manifest.json").is_file():
        return {"ok": False, "error": "no template %r" % template}
    name = clean_name(name or template)
    try:
        check_name(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    dest = apps_dir(workspace) / name
    if dest.exists():
        base, n = name, 2
        while (apps_dir(workspace) / ("%s-%d" % (base[:36], n))).exists():
            n += 1
        name = "%s-%d" % (base[:36], n)
        dest = apps_dir(workspace) / name
    with _LOCK:
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".*"))
        meta = read_manifest(dest)
        now = time.time()
        meta.update({"name": name, "template": template, "created": now, "updated": now, "by": "template"})
        meta["fingerprint"] = _fingerprint(dest)
        _write_json(dest / "manifest.json", meta)
        _unremove(name, None)
    nudge()
    return {"ok": True, "name": name, "app": _present(dest, "w", name)}


def remove_app(workspace: Path, name: str, root: Path | None = None, keep_data: bool = True) -> dict:
    try:
        check_name(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    folder = apps_dir(workspace) / name
    if not (folder / "manifest.json").is_file():
        return {"ok": False, "error": "no app %s" % name}
    with _LOCK:
        trash = Path(root or data_dir().parent) / "app_data" / ".removed" / ("%s-%d" % (name, int(time.time())))
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), str(trash))          # kept, not deleted: an app can be brought back by hand
        removed = _removed(root)
        removed[name] = time.time()
        _write_json(data_dir(root) / "_removed.json", removed)
        if not keep_data:
            clear_store(name, root)
    nudge()
    return {"ok": True, "name": name, "kept_at": str(trash)}


def _removed(root: Path | None) -> dict:
    try:
        data = json.loads((data_dir(root) / "_removed.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _unremove(name: str, root: Path | None) -> None:
    removed = _removed(root)
    if name in removed:
        removed.pop(name)
        _write_json(data_dir(root) / "_removed.json", removed)


def read_app(workspace: Path, name: str, limit: int = 60_000) -> dict:
    """An app's files as text, for LOKI to change it."""
    try:
        check_name(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    folder = apps_dir(workspace) / name
    if not (folder / "manifest.json").is_file():
        return {"ok": False, "error": "no app %s (installed: %s)" % (name, ", ".join(a["name"] for a in list_apps(workspace)) or "none")}
    files, used = {}, 0
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".json")):
        text = path.read_text(encoding="utf-8", errors="replace")
        used += len(text)
        files[path.relative_to(folder).as_posix()] = text if used <= limit else text[:2000] + "\n... (cut)"
    return {"ok": True, "name": name, "manifest": read_manifest(folder), "files": files}


# ------------------------------------------------------------------ per-app storage (synced)

def _store_path(app_key: str, root: Path | None) -> Path:
    return data_dir(root) / (namespace(app_key) + ".json")


def _load(app_key: str, root: Path | None) -> dict:
    try:
        data = json.loads(_store_path(app_key, root).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("keys"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"v": 1, "keys": {}}


def _stamp() -> float:
    return round(time.time(), 6)


def _newer(a: dict, b: dict) -> bool:
    """a wins over b: later time, ties broken by machine name (the same answer on every machine)."""
    return (float(a.get("t") or 0), str(a.get("h") or "")) > (float(b.get("t") or 0), str(b.get("h") or ""))


def storage(app_key: str, op: str, key: str = "", value=None, root: Path | None = None) -> dict:
    """get / set / remove / keys / all / clear on one app's store."""
    op = str(op or "").lower()
    try:
        path = _store_path(app_key, root)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    key = str(key or "")
    if op in ("get", "set", "remove") and not (0 < len(key) <= 200):
        return {"ok": False, "error": "a key is 1-200 characters"}
    with _LOCK:
        data = _load(app_key, root)
        keys = data["keys"]
        if op == "get":
            item = keys.get(key)
            return {"ok": True, "value": None if not item or item.get("d") else item.get("v")}
        if op == "keys":
            return {"ok": True, "keys": sorted(k for k, it in keys.items() if not it.get("d"))}
        if op == "all":
            return {"ok": True, "values": {k: it.get("v") for k, it in keys.items() if not it.get("d")}}
        if op in ("set", "remove", "clear"):
            if op == "set":
                raw = json.dumps(value, ensure_ascii=False)
                if len(raw) > MAX_VALUE:
                    return {"ok": False, "error": "that value is larger than %d bytes - split it over several keys" % MAX_VALUE}
                live = [k for k, it in keys.items() if not it.get("d")]
                if key not in keys and len(live) >= MAX_KEYS:
                    return {"ok": False, "error": "this app already keeps %d keys" % MAX_KEYS}
                keys[key] = {"v": value, "t": _stamp(), "h": host_name()}
            elif op == "remove":
                if key in keys:
                    keys[key] = {"v": None, "t": _stamp(), "h": host_name(), "d": 1}
            else:
                for k in list(keys):
                    keys[k] = {"v": None, "t": _stamp(), "h": host_name(), "d": 1}
            if len(json.dumps(data, ensure_ascii=False)) > MAX_STORE:
                return {"ok": False, "error": "this app's storage is full (%d bytes)" % MAX_STORE}
            _write_json(path, data)
            if not app_key.startswith("t:"):
                nudge()
            return {"ok": True}
    return {"ok": False, "error": "unknown storage op %r (get, set, remove, keys, all, clear)" % op}


def clear_store(app_key: str, root: Path | None = None) -> dict:
    return storage(app_key, "clear", root=root)


def data_summary(app_key: str, root: Path | None = None, limit: int = 12_000) -> str:
    """The app's stored data as text (for LOKI's tools and 'ask LOKI')."""
    values = storage(app_key, "all", root=root).get("values") or {}
    text = json.dumps(values, ensure_ascii=False, indent=1, default=str)
    return text if len(text) <= limit else text[:limit] + "\n... (cut, %d bytes in all)" % len(text)


def merge_store(app_key: str, incoming: dict, root: Path | None = None) -> int:
    """Merge another machine's entries (last writer wins per key). Returns how many changed here."""
    if not isinstance(incoming, dict):
        return 0
    changed = 0
    with _LOCK:
        data = _load(app_key, root)
        keys = data["keys"]
        for key, item in list(incoming.items())[:MAX_KEYS]:
            if not isinstance(item, dict) or not (0 < len(str(key)) <= 200):
                continue
            item = {"v": item.get("v"), "t": float(item.get("t") or 0), "h": str(item.get("h") or "")[:40],
                    **({"d": 1} if item.get("d") else {})}
            if len(json.dumps(item["v"], ensure_ascii=False, default=str)) > MAX_VALUE:
                continue
            if key not in keys or _newer(item, keys[key]):
                keys[str(key)] = item
                changed += 1
        if changed:
            _write_json(_store_path(app_key, root), data)
    return changed


def _store_hash(app_key: str, root: Path | None) -> str:
    data = _load(app_key, root)
    return hashlib.sha1(json.dumps(data["keys"], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _stores(root: Path | None) -> list:
    base = data_dir(root)
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.json") if NAME_RE.match(p.stem))   # workspace apps only (no t--/x--)


# ------------------------------------------------------------------ saved files

def files_dir(workspace: Path, app_key: str) -> Path:
    return Path(workspace) / "App files" / namespace(app_key)


def safe_file_name(name: str) -> str:
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = re.sub(r"[^\w .()+-]", "_", name)[:120].strip(" .")
    return name or "file.txt"


def save_file(workspace: Path, app_key: str, name: str, content: str, encoding: str = "text") -> dict:
    import base64  # pylint: disable=import-outside-toplevel
    try:
        folder = files_dir(workspace, app_key)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    name = safe_file_name(name)
    try:
        raw = base64.b64decode(content) if encoding == "base64" else str(content).encode("utf-8")
    except (ValueError, TypeError):
        return {"ok": False, "error": "content is not valid base64"}
    if len(raw) > MAX_FILE_SAVE:
        return {"ok": False, "error": "the file is larger than %d bytes" % MAX_FILE_SAVE}
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if target.exists():   # never overwrite: name (2).ext
        stem, suffix, n = target.stem, target.suffix, 2
        while (folder / ("%s (%d)%s" % (stem, n, suffix))).exists():
            n += 1
        target = folder / ("%s (%d)%s" % (stem, n, suffix))
    target.write_bytes(raw)
    return {"ok": True, "name": target.name, "path": str(target), "bytes": len(raw)}


def list_files(workspace: Path, app_key: str) -> dict:
    try:
        folder = files_dir(workspace, app_key)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    items = []
    if folder.is_dir():
        for p in sorted(folder.iterdir(), key=lambda p: -p.stat().st_mtime):
            if p.is_file() and not p.name.startswith("."):
                items.append({"name": p.name, "bytes": p.stat().st_size, "t": p.stat().st_mtime})
    return {"ok": True, "files": items[:200], "folder": str(folder)}


def read_file(workspace: Path, app_key: str, name: str, limit: int = 2_000_000) -> dict:
    try:
        folder = files_dir(workspace, app_key)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    target = folder / safe_file_name(name)
    if not target.is_file():
        return {"ok": False, "error": "no saved file %s" % name}
    raw = target.read_bytes()[:limit]
    try:
        return {"ok": True, "name": target.name, "text": raw.decode("utf-8")}
    except UnicodeDecodeError:
        import base64  # pylint: disable=import-outside-toplevel
        return {"ok": True, "name": target.name, "base64": base64.b64encode(raw).decode("ascii")}


# ------------------------------------------------------------------ sync between the owner's machines
# POST /peer/apps over the signed link (peers.py). Round 1 {"summary": mine} -> the other side answers
# with its summary and what this side lacks or has different; round 2 {"push": ...} sends what the other
# side lacks. Apps' code: the newer manifest "updated" wins (a removal is a tombstone with a time);
# app data: merged key by key (merge_store). Repeating it changes nothing.

_EVENT = threading.Event()
_RUNNING = {"on": False}
SYNC_EVERY_S = int(os.getenv("LOKI_APPS_SYNC_S", "300") or 300)
LAST_SYNC: dict = {}


def nudge() -> None:
    _EVENT.set()


def _code_bundle(folder: Path) -> dict:
    out = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".json", ".svg")):
        out[path.relative_to(folder).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    return out


def sync_summary(workspace: Path, root: Path | None = None) -> dict:
    apps = {}
    for app in list_apps(workspace):
        meta = read_manifest(apps_dir(workspace) / app["name"])
        apps[app["name"]] = {"updated": float(meta.get("updated") or 0), "fp": str(meta.get("fingerprint") or "")}
    data = {name: _store_hash(name, root) for name in _stores(root)}
    return {"apps": apps, "data": data, "removed": _removed(root), "host": host_name()}


def _accept_code(workspace: Path, name: str, bundle: dict) -> bool:
    if not NAME_RE.match(name) or not isinstance(bundle, dict) or "manifest.json" not in bundle:
        return False
    if sum(len(str(v)) for v in bundle.values()) > MAX_APP_BYTES:
        return False
    try:
        meta = json.loads(bundle["manifest.json"])
    except ValueError:
        return False
    folder = apps_dir(workspace) / name
    tmp = apps_dir(workspace) / (".incoming-" + name)
    shutil.rmtree(tmp, ignore_errors=True)
    for rel, text in bundle.items():
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel or ".." in rel.split("/") or rel.startswith(".") or Path(rel).suffix.lower() not in (".html", ".js", ".css", ".json", ".svg"):
            continue
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_text(str(text), encoding="utf-8")
    meta["name"] = name
    meta["synced_from"] = str(meta.get("synced_from") or "peer")[:40]
    _write_json(tmp / "manifest.json", meta)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    os.replace(tmp, folder)
    return True


def _apply_removed(workspace: Path, removed: dict, root: Path | None) -> int:
    mine = _removed(root)
    n = 0
    for name, t in (removed or {}).items():
        if not NAME_RE.match(str(name)):
            continue
        folder = apps_dir(workspace) / name
        updated = float(read_manifest(folder).get("updated") or 0) if folder.is_dir() else 0
        if float(t or 0) > float(mine.get(name) or 0):
            mine[name] = float(t)
        if folder.is_dir() and float(t or 0) > updated:
            trash = data_dir(root) / ".removed" / ("%s-%d" % (name, int(time.time())))
            trash.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(trash))
            n += 1
    _write_json(data_dir(root) / "_removed.json", mine)
    return n


def _diff(workspace: Path, theirs: dict, root: Path | None) -> dict:
    """What THEY lack or have different, from my side: {"code": {name: bundle}, "data": {name: entries}}."""
    mine = sync_summary(workspace, root)
    code, data = {}, {}
    their_apps = (theirs or {}).get("apps") or {}
    their_removed = (theirs or {}).get("removed") or {}
    for name, info in mine["apps"].items():
        other = their_apps.get(name)
        gone = float(their_removed.get(name) or 0)
        if gone >= info["updated"]:
            continue
        if other is None or (info["updated"] > float(other.get("updated") or 0) and info["fp"] != other.get("fp")):
            code[name] = _code_bundle(apps_dir(workspace) / name)
    their_data = (theirs or {}).get("data") or {}
    for name, h in mine["data"].items():
        if their_data.get(name) != h:
            data[name] = _load(name, root)["keys"]
    return {"code": code, "data": data, "removed": mine["removed"]}


def _take(workspace: Path, push: dict, root: Path | None) -> dict:
    got_code = got_data = 0
    with _LOCK:
        removed = _apply_removed(workspace, (push or {}).get("removed") or {}, root)
        tomb = _removed(root)
        for name, bundle in ((push or {}).get("code") or {}).items():
            folder = apps_dir(workspace) / str(name)
            here = float(read_manifest(folder).get("updated") or 0) if folder.is_dir() else 0
            try:
                there = float(json.loads(bundle.get("manifest.json", "{}")).get("updated") or 0)
            except (ValueError, AttributeError):
                continue
            if there > here and there > float(tomb.get(str(name)) or 0) and _accept_code(workspace, str(name), bundle):
                got_code += 1
        for name, entries in ((push or {}).get("data") or {}).items():
            if NAME_RE.match(str(name)):
                got_data += merge_store(str(name), entries, root)
    return {"code": got_code, "data": got_data, "removed": removed}


def sync_receive(workspace: Path, origin: str, data: dict, root: Path | None = None) -> dict:
    """The peer-server side of POST /peer/apps."""
    if not isinstance(data, dict):
        raise ValueError("expected an object")
    if "push" in data:
        got = _take(workspace, data.get("push") or {}, root)
        LAST_SYNC[str(origin)[:40]] = {"t": time.time(), "in": got, "direction": "in"}
        return {"took": got}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    return {"summary": sync_summary(workspace, root), "send": _diff(workspace, summary, root)}


def sync_with(peer: dict, workspace: Path, root: Path | None = None, call=None) -> dict:
    """Sync apps and their data with one linked machine (two signed calls)."""
    if call is None:
        import peers  # pylint: disable=import-outside-toplevel
        call = peers.call
    name = str(peer.get("name") or "peer")
    try:
        reply = call(peer, "POST", "/peer/apps", {"summary": sync_summary(workspace, root)}, timeout=30)
        got = _take(workspace, reply.get("send") or {}, root)
        push = _diff(workspace, reply.get("summary") or {}, root)
        sent = {"code": len(push["code"]), "data": len(push["data"])}
        if push["code"] or push["data"] or push["removed"]:
            call(peer, "POST", "/peer/apps", {"push": push}, timeout=30)
        LAST_SYNC[name] = {"t": time.time(), "in": got, "out": sent, "error": ""}
        return {"peer": name, "ok": True, "received": got, "sent": sent}
    except Exception as exc:  # noqa: BLE001
        LAST_SYNC[name] = {"t": time.time(), "error": str(exc)[:200]}
        return {"peer": name, "ok": False, "error": str(exc)[:200]}


def sync_all(workspace: Path, root: Path | None = None, peer_list: list | None = None, call=None) -> list:
    if peer_list is None:
        try:
            import peers  # pylint: disable=import-outside-toplevel
            peer_list = peers.peers()
        except Exception:  # noqa: BLE001
            peer_list = []
    return [sync_with(p, workspace, root, call) for p in peer_list]


def ensure_sync_thread(agent) -> None:
    """One background loop per engine: sync a few seconds after a change, and every SYNC_EVERY_S."""
    if _RUNNING["on"] or os.getenv("LOKI_APPS_SYNC", "1") == "0":
        return
    _RUNNING["on"] = True

    def loop() -> None:
        time.sleep(20)
        while True:
            changed = _EVENT.wait(SYNC_EVERY_S)
            if changed:
                time.sleep(5)
            _EVENT.clear()
            try:
                sync_all(Path(getattr(agent, "WORKSPACE", ".")), Path(getattr(agent, "DATA_DIR", "")) if getattr(agent, "DATA_DIR", "") else None)
            except Exception:  # noqa: BLE001 - the loop must never die
                pass
    threading.Thread(target=loop, daemon=True, name="loki-apps-sync").start()


# ------------------------------------------------------------------ the guide LOKI reads before building

GUIDE = """LOKI APPS - build a small app that runs inside LOKI (the Apps area, the grid icon in the sidebar).

WORKFLOW
1. Pick a short name (lowercase letters, digits, - or _), a title, an emoji icon and one line about it.
2. Call make_app(name, title, icon, description, html, js, css?) - html is the BODY markup only (LOKI wraps
   it in the standard page that loads the kit), js is app.js, css is optional extra styles. To change an
   app: make_app(action="read", name) first, then make_app(name, js=..., html=...) with the new files
   (only the parts you pass are replaced). To start from a ready app: make_app(action="install",
   template="budget"); templates: %(templates)s.
3. Tell the user it is in Apps. make_app checks the files; fix what it reports and call it again.

RULES (the app runs in a sealed sandbox - break one and it silently fails)
- No inline <script> and no onclick="..." attributes: all code in app.js, listeners with addEventListener.
- No network (no fetch, no CDN links, no external fonts), no localStorage/indexedDB, no alert/confirm/prompt.
- Data: await loki.store.get(key, fallback) / await loki.store.set(key, value) (JSON values; kept by LOKI,
  synced to the owner's other machines). Read everything at start, save after each change.
- Ask LOKI: const answer = await loki.ask("question", {data: {...}}) - a model call with the app's data.
- Files: await loki.files.save("report.csv", text) (the owner approves; lands in App files/<app>/),
  const f = await loki.files.open({accept: ".csv,.txt"}) -> {name, text} or null.
- Look: use the kit's classes so every app looks like LOKI; dark and light both work by themselves.

THE KIT (window.kit, window.loki; CSS classes from /ui/appkit/appkit.css)
%(kit)s

FULL EXAMPLE (template "%(example)s": index.html body, then app.js)
%(example_html)s
---- app.js ----
%(example_js)s
"""


def guide() -> str:
    kit_doc = ""
    try:
        src = (repo_root() / "app" / "ui" / "appkit" / "appkit.js").read_text(encoding="utf-8")
        kit_doc = src.split('"use strict";', 1)[0].strip()
    except OSError:
        kit_doc = "(appkit.js is missing)"
    example = "habits"
    folder = templates_dir() / example
    try:
        page = (folder / "index.html").read_text(encoding="utf-8")
        body = re.search(r"<body>(.*)</body>", page, flags=re.DOTALL)
        example_html = (body.group(1) if body else page).strip()
        example_js = (folder / "app.js").read_text(encoding="utf-8")
    except OSError:
        example_html = example_js = "(the example template is missing)"
    names = ", ".join(t["name"] for t in list_templates())
    return GUIDE % {"templates": names or "none", "kit": kit_doc, "example": example,
                    "example_html": example_html, "example_js": example_js}
