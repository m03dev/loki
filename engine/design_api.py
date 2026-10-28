"""HTTP for Design (engine/design.py) - the window's Forge > Design workspace (app/ui/forge_design.js).

GET  /design/list                the designs in <workspace>/designs, the CLI / app state, the phone-test devices
GET  /design/file?path=          a picture or export inside designs/
GET  /design/job?id=             a running step
POST /design/do {action, ...}    the design tool's actions; OpenPencil runs take seconds, so they run in the background
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import design

JOBS: dict = {}
_LOCK = threading.Lock()
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml",
         ".jsx": "text/plain; charset=utf-8", ".html": "text/plain; charset=utf-8"}


def _ws(state) -> Path:
    return Path(getattr(getattr(state, "agent", None), "WORKSPACE", "."))


def route(state, method: str, path: str, data: dict | None = None) -> tuple:
    r = urlparse(path).path
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    ws = _ws(state)
    if method == "GET":
        if r == "/design/list":
            out = design.tool({"action": "list"}, ws)
            try:
                import mobile_test  # pylint: disable=import-outside-toplevel
                out["mobile"] = mobile_test.status()
            except Exception:  # noqa: BLE001
                out["mobile"] = {}
            return 200, out
        if r == "/design/job":
            j = JOBS.get(q.get("id", ""))
            return (200, dict(j, ok=True)) if j else (404, {"ok": False, "error": "no such job"})
        if r == "/design/file":
            base = design.designs(ws).resolve()
            try:
                p = (ws / q.get("path", "")).resolve()
                p.relative_to(base)
            except (OSError, ValueError):
                return 403, {"ok": False, "error": "outside designs/"}
            if not p.is_file() or p.suffix.lower() not in TYPES:
                return 404, {"ok": False, "error": "no such file"}
            return 200, p.read_bytes(), TYPES[p.suffix.lower()]
        return 404, {"ok": False, "error": "Unknown endpoint."}
    if r == "/design/do":
        a = dict(data or {})
        jid = uuid.uuid4().hex[:10]
        with _LOCK:
            JOBS[jid] = {"id": jid, "status": "running", "t": time.time(), "label": str(a.get("action") or "")}

        def run():
            try:
                out = design.tool(a, ws)
            except Exception as exc:  # noqa: BLE001
                out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            with _LOCK:
                JOBS[jid].update(status="done" if out.get("ok") else "failed", result=out, finished=time.time())
        threading.Thread(target=run, daemon=True, name="design-" + jid).start()
        return 200, {"ok": True, "job": jid}
    return 404, {"ok": False, "error": "Unknown endpoint."}
