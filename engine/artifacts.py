"""Artifacts: a live preview of what LOKI writes in the chat (research round 3; Claude's artifacts,
Open WebUI's artifact window, LibreChat's and Lobe Chat's previews).

A ```html or ```svg block in a reply gets a Preview button (a ```mermaid diagram is drawn the same way, in
place, with the Mermaid library vendored in app/ui/vendor/mermaid - MIT); the canvas beside the chat shows it
running. The window's own security policy forbids inline scripts (and a srcdoc/blob frame would
inherit that policy), so the page is served from the engine on its own address with ITS OWN policy:

  GET /artifact/<id>   the page, in a frame the window opens with sandbox="allow-scripts" (no
                       allow-same-origin: an opaque origin - it cannot read LOKI's token, call the
                       engine or touch the window) and a CSP `sandbox allow-scripts` header so it is
                       sandboxed even when opened directly; connect-src 'none' (no fetch/XHR/websocket),
                       images only data:/blob:, scripts inline or from three big CDNs (three.js,
                       d3, chart.js examples work), no forms, no base, no plugins.

Ids are the content's hash, so the same block always gets the same page (and re-opening an old
chat finds it again). Pages live in DATA_DIR/artifacts/ (at most MAX_KEEP; oldest go first).
`save` copies one into the workspace as artifacts/<name>.html, keeping every earlier version as
<name>.v2.html, <name>.v3.html ... (Open WebUI keeps versions the same way).
"""
from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

MAX_BYTES = 2_000_000
MAX_KEEP = 400
CDNS = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com"
CSP = ("default-src 'none'; script-src 'unsafe-inline' %s __VENDOR__; style-src 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src data: https://fonts.gstatic.com; img-src data: blob:; media-src data: blob:; connect-src 'none'; "
       "form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'self'; sandbox allow-scripts" % CDNS)
ID = re.compile(r"^[a-f0-9]{24}$")
KINDS = ("html", "svg", "mermaid")
ORIGIN = "__LOKI_ORIGIN__"      # replaced by http://127.0.0.1:<port> when served (the vendored Mermaid lives there)
MERMAID_PAGE = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><style>html,body{margin:0;background:#fff}"
    "body{padding:8px;font:14px system-ui,sans-serif}.err{color:#a33;white-space:pre-wrap}</style></head><body>"
    "<pre class=\"mermaid\">%s</pre><script src=\"" + ORIGIN + "/ui/vendor/mermaid/mermaid.min.js\"></script><script>"
    "function tell(){parent.postMessage({lokiArtifact:1,height:Math.ceil(document.documentElement.scrollHeight)},'*')}"
    "try{mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'default'});"
    "mermaid.run({querySelector:'.mermaid'}).then(tell).catch(function(e){var d=document.createElement('div');"
    "d.className='err';d.textContent='This diagram has an error: '+(e&&e.message||e);document.body.append(d);tell()})}"
    "catch(e){document.body.textContent='Diagrams are not available: '+e.message;tell()}</script></body></html>")


def wrap(code: str, kind: str) -> str:
    """A complete page for a block: HTML as it is (a fragment gets a page around it), SVG centred."""
    code = str(code or "")
    if kind == "mermaid":
        return MERMAID_PAGE % html.escape(code, quote=False)
    if kind == "svg":
        return ("<!doctype html><html><head><meta charset=\"utf-8\"><style>html,body{margin:0;height:100%;"
                "background:#fff}body{display:flex;align-items:center;justify-content:center}svg{max-width:100%;"
                "max-height:100vh}</style></head><body>" + code + "</body></html>")
    if re.search(r"<html[\s>]|<!doctype", code[:500], re.I):
        return code
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,"
            "initial-scale=1\"><style>body{font:15px/1.5 system-ui,sans-serif;margin:16px}</style></head><body>"
            + code + "</body></html>")


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, code: str, kind: str = "html") -> dict:
        kind = kind if kind in KINDS else "html"
        page = wrap(code, kind)
        data = page.encode("utf-8")
        if not code.strip():
            return {"ok": False, "error": "the block is empty"}
        if len(data) > MAX_BYTES:
            return {"ok": False, "error": "too big to preview (%d KB; the limit is %d KB)" % (len(data) // 1024, MAX_BYTES // 1024)}
        aid = hashlib.sha256(data).hexdigest()[:24]
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (aid + ".html")
        if not path.exists():
            path.write_bytes(data)
            self._prune()
        return {"ok": True, "id": aid, "url": "/artifact/" + aid, "bytes": len(data)}

    def get(self, aid: str) -> bytes | None:
        if not ID.match(str(aid or "")):
            return None
        path = self.root / (aid + ".html")
        try:
            return path.read_bytes()
        except OSError:
            return None

    def _prune(self) -> None:
        pages = sorted(self.root.glob("*.html"), key=lambda p: p.stat().st_mtime)
        for old in pages[:max(0, len(pages) - MAX_KEEP)]:
            try:
                old.unlink()
            except OSError:
                pass

    def save(self, aid: str, workspace: Path, name: str = "") -> dict:
        data = self.get(aid)
        if data is None:
            return {"ok": False, "error": "that preview is gone; open it again from the chat"}
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name or "artifact")).strip("-")[:40] or "artifact"
        folder = Path(workspace) / "artifacts"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (stem + ".html")
        version = 1
        while target.exists():
            if target.read_bytes() == data:
                return {"ok": True, "path": str(target.relative_to(workspace)).replace("\\", "/"), "version": version,
                        "same": True}
            version += 1
            target = folder / ("%s.v%d.html" % (stem, version))
        target.write_bytes(data)
        return {"ok": True, "path": str(target.relative_to(workspace)).replace("\\", "/"), "version": version}


def page(body: bytes, origin: str) -> bytes:
    """The stored page as served: the placeholder origin becomes LOKI's own address."""
    return body.replace(ORIGIN.encode(), origin.encode())


def headers(origin: str = "") -> list:
    csp = CSP.replace("__VENDOR__", (origin + "/ui/vendor/") if origin else "")
    return [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "SAMEORIGIN"),
            ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", csp)]
