"""Preview server for LOKI World screenshots: the real app/ui files at /ui/, the preview page at
/preview/, and FAKE engine answers (/world, /settings/general, /world/presence) - no engine,
no token, no model. Used by tests/mmo_preview/shot.py (headless Chromium).

    python tests/mmo_preview/serve.py [port]
"""
from __future__ import annotations

import json
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "app" / "ui"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "engine"))
import presence  # noqa: E402

TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json"}
PRES = presence.Presence(lambda: "Mac mini")


def fake_world() -> dict:
    now = time.time()
    agents = [
        {"id": "loki", "name": "LOKI", "role": "conductor", "state": "idle", "station": "hall", "task": "", "team": "",
         "machine": "Mac mini", "since": 0, "finished": 0, "stage": "", "last_message": ""},
        {"id": "job-a1", "name": "Researcher", "role": "researcher", "state": "working", "station": "library",
         "task": "Research the best local models", "team": "", "machine": "Mac mini", "since": now - 300, "finished": 0,
         "stage": "", "last_message": "Reading three benchmarks now"},
        {"id": "job-b2", "name": "Builder", "role": "builder", "state": "working", "station": "workshop",
         "task": "Make an image of a red fox", "team": "", "machine": "Mac mini", "since": now - 60, "finished": 0,
         "stage": "", "last_message": ""},
        {"id": "job-c3", "name": "Tester", "role": "tester", "state": "failed", "station": "test bench",
         "task": "Run the suites", "team": "", "machine": "Mac mini", "since": now - 900, "finished": now - 100,
         "stage": "", "last_message": ""},
    ]
    return {"ok": True, "machine": "Mac mini", "time": now, "agents": agents,
            "stats": {"working": 2, "waiting": 0, "blocked": 0, "done_today": 4, "failed_today": 1}, "teams": [],
            "cursor": 0, "self": {"name": "Mac mini", "os": "Darwin"},
            "machines": [{"name": "pc", "ok": True, "ms": 120, "relay": True, "os": "Windows", "working": 1, "blocked": 0}],
            "creations": {"count": 2, "latest": [{"title": "red fox in studio light", "kind": "images", "show": "image"}]},
            "presence": presence.world_part() if False else {"players": PRES.snapshot()["players"], "chat": [], "cursor": 0},
            "model": {"model": "qwen3", "local": True}, "usage": {}}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        route = urlparse(self.path).path
        if route.startswith("/ui/"):
            return self._file(UI / route[4:])
        if route.startswith("/preview/"):
            return self._file(HERE / route[9:])
        if route == "/world":
            return self._json(fake_world())
        if route == "/settings/general":
            return self._json({"ok": True, "values": {"LOKI_WORLD": "panel", "LOKI_WORLD_ENGINE": "babylon"}})
        if route == "/world/presence":
            return self._json(PRES.snapshot(0))
        return self._json({"ok": False, "error": "not faked"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(length) or b"{}")
        if urlparse(self.path).path == "/world/presence":
            return self._json(PRES.update_local(data))
        return self._json({"ok": False, "error": "not faked"})


def serve(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    srv = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8790)
    print("preview at http://127.0.0.1:%d/preview/preview.html" % srv.server_address[1])
    srv.serve_forever()
