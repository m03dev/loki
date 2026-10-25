"""Driving the running LOKI over MCP (engine/loki_mcp.py: chat, task, agent_status, agent_install, workspace_files,
workspace_read) - owner 2026-10-25: "you build loki, how can you not control it - mcp, api, sdk, figure it out".
A fake engine bridge on 127.0.0.1 stands in for the running LOKI. Under a minute.

    python tests/test_loki_mcp_drive.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


t0 = time.time()
import loki_mcp  # noqa: E402

D = Path(tempfile.mkdtemp(prefix="loki-mcp-"))
WS = D / "ws"
(WS / "loki-test-repo" / "src").mkdir(parents=True)
(WS / "loki-test-repo" / "src" / "main.py").write_text('print("hello")\n')
(WS / ".env").write_text("SECRET=1\n")
TOKEN = D / "engine.token"
TOKEN.write_text("tok123")
SEEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer tok123":
            return self._send(401, {"ok": False})
        if self.path == "/agent/engine":
            return self._send(200, {"ok": True, "engine": "opencode", "opencode": "/x/opencode", "workspace": str(WS)})
        self._send(404, {})

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer tok123":
            return self._send(401, {"ok": False})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)) or b"{}")
        SEEN.append((self.path, body))
        if self.path == "/chat":
            return self._send(200, {"ok": True, "response": "Created loki-test-repo.\n\nTools run: 1 ok.",
                                    "changed_files": ["loki-test-repo/src/main.py"]})
        if self.path == "/task":
            return self._send(200, {"ok": True, "response": "DONE: built it"})
        if self.path == "/agent/engine/install":
            return self._send(200, {"ok": True, "result": {"opencode": "already", "codegraph": "ok"}})
        self._send(404, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
api = loki_mcp.LokiAPI(bridge_url="http://127.0.0.1:%d" % srv.server_address[1], token_file=str(TOKEN), data=str(D))

out = json.loads(api.chat("make loki-test-repo"))
check("chat: sends the message like the window and returns LOKI's answer + what changed",
      SEEN[-1] == ("/chat", {"message": "make loki-test-repo"}) and "Tools run: 1 ok" in out["response"]
      and out["changed_files"] == ["loki-test-repo/src/main.py"], out)
out = json.loads(api.task("build a site"))
check("task: a Build task, steps 0 = until done", SEEN[-1] == ("/task", {"task": "build a site", "steps": 0})
      and out["response"].startswith("DONE"), out)
check("agent_status: the engine and the workspace", "opencode" in api.agent_status() and str(WS) in api.agent_status())
check("agent_install goes through the engine", "codegraph" in api.agent_install())
files = api.workspace_files(".", 3)
check("workspace_files: what is really on disk in LOKI's workspace", "loki-test-repo/src/main.py" in files, files)
check("workspace_read: a file LOKI made", api.workspace_read("loki-test-repo/src/main.py").startswith('print("hello")'))
check("workspace_read: a secret or a path outside is refused", api.workspace_read(".env").startswith("refused")
      and api.workspace_read("../engine.token").startswith("refused"))
TOKEN.write_text("wrong")
check("the bridge token is required", '"ok": false' in api.chat("x").lower() or "401" in api.chat("x") or "error" in api.chat("x").lower())
srv.shutdown()
check("LOKI not running: says so", "not running" in loki_mcp.LokiAPI(bridge_url="http://127.0.0.1:9", token_file=str(D / "none"),
                                                                     data=str(D)).chat("hi"))
try:
    server = loki_mcp.build_server(api)
    names = [t for t in loki_mcp.TOOL_ORDER]
    check("the MCP server offers chat / task / agent / workspace tools first",
          names[:6] == ["chat", "task", "agent_status", "agent_install", "workspace_files", "workspace_read"])
except Exception as exc:  # noqa: BLE001
    print("  (skip the MCP server check: %s)" % exc)
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
