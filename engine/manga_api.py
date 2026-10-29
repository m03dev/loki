"""HTTP for Manga Studio (engine/manga.py) - the window's Forge > Manga workspace (app/ui/forge_manga.js).

GET  /manga/meta                 formats, styles, layouts, shots, angles, balloon kinds, endings
GET  /manga/list                 the projects and the character library
GET  /manga/project?id=          one project (with its review)
GET  /manga/file?path=           a picture inside <workspace>/manga (pages, panels, sheets)
GET  /manga/job?id=              a running step (outline, script, drawing ...)
POST /manga/do  {action, ...}    the same actions as the agents' `manga` tool; writing and drawing steps run in the
                                 background and answer {"job": id}. The owner's own clicks draw at once - the For you
                                 OK is for pictures an AGENT asks for (owner's rule 8).
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import manga

SLOW = {"outline", "characters", "script", "sheet", "draw_page", "draw", "edit_panel"}
JOBS: dict = {}
SLOW: dict = {}          # provider -> until when it is tried last (it just timed out on a writing step)
SLOW_FOR_S = 20 * 60
_LOCK = threading.Lock()


def _ws(state) -> Path:
    return Path(getattr(getattr(state, "agent", None), "WORKSPACE", "."))


def _ask(state, timeout_s: float = 150):
    """The writer for outline / cast / script: every usable model in turn (loki.port_ladder) until one answers
    with JSON Manga Studio can read. On 2026-10-28 the main driver timed out on an outline and the step 'succeeded'
    with the premise pasted onto every page; now each model gets its turn and the reasons come back when all fail."""
    agent, loop = getattr(state, "agent", None), getattr(state, "loop", None)
    if agent is None or loop is None or not hasattr(agent, "_port_ask"):
        return None

    def once(prompt: str, provider: str, limit: float) -> str:
        fut = asyncio.run_coroutine_threadsafe(agent._port_ask(prompt, max_tokens=4000, provider=provider), loop)  # pylint: disable=protected-access
        try:
            return fut.result(timeout=limit)
        except Exception:  # noqa: BLE001
            fut.cancel()
            raise

    def ask(prompt: str) -> str:
        try:
            ladder = list(agent.port_ladder()) if hasattr(agent, "port_ladder") else [""]
        except Exception:  # noqa: BLE001
            ladder = [""]
        now = time.time()
        # a model that just timed out goes last for a while (the main driver timed out on every
        # outline / cast step on 2026-10-28 - 150 s lost each time before the PC's model wrote it)
        ladder.sort(key=lambda prov: SLOW.get(prov, 0) > now)
        why = []
        for i, provider in enumerate(ladder or [""]):
            limit = timeout_s if i == 0 else min(timeout_s, 90.0)
            t0 = time.time()
            try:
                raw = once(prompt, provider, limit)
                manga._json(raw)   # pylint: disable=protected-access - the same check the caller makes
                SLOW.pop(provider, None)
                if i:
                    print("[manga] written by %s after: %s" % (provider, "; ".join(why)), flush=True)
                return raw
            except Exception as exc:  # noqa: BLE001 - next model
                timed_out = isinstance(exc, TimeoutError) or type(exc).__name__ == "TimeoutError"
                if timed_out:
                    SLOW[provider] = time.time() + SLOW_FOR_S
                kind = "timed out after %ds" % int(time.time() - t0) if timed_out else \
                    "%s: %s" % (type(exc).__name__, str(exc)[:160])
                why.append("%s %s" % (provider or "main model", kind))
        print("[manga] every model failed: %s" % "; ".join(why), flush=True)
        raise RuntimeError("every model failed - " + "; ".join(why))
    return ask


def _make(ws: Path):
    def make(args: dict) -> dict:
        import make_mcp  # pylint: disable=import-outside-toplevel
        return make_mcp.make_image(args, ws)
    return make


def _start(fn, label: str) -> str:
    jid = uuid.uuid4().hex[:10]
    with _LOCK:
        JOBS[jid] = {"id": jid, "label": label, "status": "running", "t": time.time()}
        for old in [k for k, v in JOBS.items() if time.time() - v["t"] > 6 * 3600]:
            JOBS.pop(old, None)

    def run():
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 - the window shows why
            out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        with _LOCK:
            JOBS[jid].update(status="done" if (out or {}).get("ok") else "failed", result=out, finished=time.time())
    threading.Thread(target=run, daemon=True, name="manga-" + jid).start()
    return jid


def route(state, method: str, path: str, data: dict | None = None) -> tuple:
    r = urlparse(path).path
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    ws = _ws(state)
    if method == "GET":
        if r == "/manga/meta":
            return 200, {"ok": True, "formats": list(manga.FORMATS), "styles": list(manga.STYLES),
                         "layouts": list(manga.LAYOUTS) + ["strip", "column", "grid5", "grid6", "grid7", "grid8"],
                         "shots": list(manga.SHOTS), "angles": list(manga.ANGLES), "kinds": list(manga.KINDS),
                         "endings": manga.ENDINGS}
        if r == "/manga/list":
            return 200, manga.tool({"action": "list"}, ws)
        if r == "/manga/project":
            out = manga.tool({"action": "status", "project": q.get("id", "")}, ws)
            if out.get("ok"):                     # each page's panels as boxes in % (the window's click targets)
                proj = out["project"]
                for pg in proj.get("pages") or []:
                    if pg.get("panels"):
                        W, H, boxes = manga.rects(proj, pg)
                        pg["boxes"] = [{"n": p["n"], "x": round(100.0 * x / W, 2), "y": round(100.0 * y / H, 2),
                                        "w": round(100.0 * w / W, 2), "h": round(100.0 * h / H, 2)}
                                       for p, (x, y, w, h) in zip(pg["panels"], boxes)]
            return (200 if out.get("ok") else 404), out
        if r == "/manga/job":
            j = JOBS.get(q.get("id", ""))
            return (200, dict(j, ok=True)) if j else (404, {"ok": False, "error": "no such job"})
        if r == "/manga/file":
            base = manga.root(ws).resolve()
            try:
                p = (ws / q.get("path", "")).resolve()
                p.relative_to(base)
            except (OSError, ValueError):
                return 403, {"ok": False, "error": "outside the manga folder"}
            if not p.is_file():
                return 404, {"ok": False, "error": "no such file"}
            kind = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                    ".pdf": "application/pdf", ".cbz": "application/zip"}.get(p.suffix.lower(), "application/octet-stream")
            return 200, p.read_bytes(), kind
        return 404, {"ok": False, "error": "Unknown endpoint."}
    if r == "/manga/do":
        a = dict(data or {})
        act = str(a.get("action") or "")
        if act in SLOW:
            jid = _start(lambda: manga.tool(a, ws, make=_make(ws), ask=_ask(state)), "%s %s" % (act, a.get("project", "")))
            return 200, {"ok": True, "job": jid}
        out = manga.tool(a, ws, make=_make(ws), ask=_ask(state))
        return (200 if out.get("ok") else 400), out
    return 404, {"ok": False, "error": "Unknown endpoint."}
