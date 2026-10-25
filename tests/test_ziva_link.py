"""Ziva works for the owner through LOKI's tools (engine/ziva_link.py + make_mcp.py --shell; owner 2026-10-25: "i have
ziva inside my loki godot live link i want that agent to work for me").

Ziva has no outside API, but it loads a Godot project's .mcp.json. LOKI writes itself into every project that has
addons/ziva_agent (keeping other servers, never touching projects without Ziva), and the server it points at - started
exactly as Ziva starts it - offers run_command: a real git repo is made and committed in LOKI Projects; dangerous
commands are refused; the folder stays inside home. Under a minute.

    python tests/test_ziva_link.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-ziva-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
HOME = TMP / "home"; HOME.mkdir()
os.environ["HOME"] = str(HOME)
PROJ = HOME / "LOKI Projects"
os.environ["LOKI_PROJECTS_DIR"] = str(PROJ)
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import ziva_link  # noqa: E402

agent = PROJ / "Agent"; (agent / "addons" / "ziva_agent").mkdir(parents=True); (agent / "project.godot").write_text("")
(agent / ".mcp.json").write_text(json.dumps({"mcpServers": {"context7": {"command": "npx", "args": ["-y", "c7"]}}}))
plain = PROJ / "Home" / "project.tps"; plain.mkdir(parents=True); (plain / "project.godot").write_text("")
r = ziva_link.link()
cfg = json.loads((agent / ".mcp.json").read_text())
check("a Godot project with Ziva gets LOKI in its .mcp.json (python + make_mcp.py --shell)", r["projects"] == {str(agent): "added"}
      and cfg["mcpServers"]["loki"]["args"][-1] == "--shell" and cfg["mcpServers"]["loki"]["args"][0].endswith("make_mcp.py"), (r, cfg))
check("... the servers already there are kept", "context7" in cfg["mcpServers"])
check("... a project without Ziva is not touched", not (plain / ".mcp.json").exists())
check("... linking again changes nothing", ziva_link.link()["projects"] == {str(agent): "same"})

# a stand-in for the running LOKI: its /approval/ask answers like the owner clicking (Allow, Deny, Allow ...)
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
ASKED, ANSWERS = [], [True, False, True]


class Engine(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ok = self.path == "/approval/ask" and self.headers.get("Authorization") == "Bearer tok"
        ASKED.append(body)
        data = json.dumps({"ok": True, "approved": ok and ANSWERS.pop(0)}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


eng = ThreadingHTTPServer(("127.0.0.1", 0), Engine)
threading.Thread(target=eng.serve_forever, daemon=True).start()
(HOME / ".loki").mkdir()
(HOME / ".loki" / "engine_connect.json").write_text(json.dumps({"url": "http://127.0.0.1:%d" % eng.server_address[1], "token": "tok"}))
OUTSIDE = TMP / "outside-home" / "work"

# the server, started the way Ziva starts it
srv = cfg["mcpServers"]["loki"]
REPO_CMD = ("mkdir -p ziva-demo && cd ziva-demo && git init -q -b main && echo '# ziva-demo' > README.md && git add -A && "
            "git -c user.name=t -c user.email=t@t commit -qm 'first from Ziva' && git log --oneline")
msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_command", "arguments": {
            "plan": "Make a new git repo ziva-demo with a README and commit it.", "command": REPO_CMD, "folder": str(OUTSIDE)}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "run_command", "arguments": {
            "plan": "Clean the whole home folder.", "command": "rm -rf ~/nothing-here"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "run_command", "arguments": {"command": "ls"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "run_command", "arguments": {
            "plan": "List the files in the Home project.", "command": "ls"}}}]
p = subprocess.run([srv["command"], *srv["args"]], input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True,
                   text=True, timeout=40, cwd=str(agent), env=dict(os.environ))
out = {m["id"]: m for m in (json.loads(x) for x in p.stdout.splitlines() if x.strip())}
txt = lambda i: out[i]["result"]["content"][0]["text"]  # noqa: E731
names = [t["name"] for t in out[2]["result"]["tools"]]
check("the server offers run_command (plus pictures, 3D, video, the other machine)", "run_command" in names and "make_image" in names
      and "run_on_machine" in names, names)
check("run_command asks the owner FIRST, in LOKI, with the plan, the exact command and the folder", ASKED and "Plan: Make a new git repo" in ASKED[0]["details"]
      and "$ mkdir -p ziva-demo" in ASKED[0]["details"] and str(OUTSIDE) in ASKED[0]["details"] and "will be made" in ASKED[0]["details"], ASKED[:1])
log = subprocess.run(["git", "-C", str(OUTSIDE / "ziva-demo"), "log", "--oneline"], capture_output=True, text=True)
check("Allowed: it REALLY made the repo - in a folder outside home, made for it", json.loads(txt(3))["ok"] and "first from Ziva" in log.stdout, (txt(3), log.stdout))
check("Denied: nothing ran", "not run" in txt(4) and not (HOME / "nothing-here").exists(), txt(4))
check("... and a command that can wreck things is marked DANGEROUS on the card", ASKED[1]["details"].startswith("DANGEROUS"), ASKED[1]["details"][:80])
check("no plan given: refused before anything is asked or run", "say in plan=" in txt(5) and len(ASKED) == 3, txt(5))
check("Allowed again: runs in ~/LOKI Projects/Home by default", json.loads(txt(6))["folder"].endswith("LOKI Projects/Home"), txt(6))
# the real engine side: /approval/ask puts the same Allow / Deny card up and waits for the click
import http.client  # noqa: E402
try:
    import loki_bridge  # noqa: E402
except Exception as exc:  # noqa: BLE001
    loki_bridge = None
    print("SKIP bridge part (%s)" % exc)
if loki_bridge is not None:
    class _Agent:
        model_name = "local"
        WORKSPACE = TMP

        def env_file_path(self):
            return str(TMP / "data" / ".env")

    bstate = loki_bridge.BridgeState(_Agent(), "s3cret")
    bsrv = loki_bridge.BridgeHTTPServer(bstate)
    threading.Thread(target=bsrv.serve_forever, daemon=True).start()

    def hc(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", bsrv.server_address[1], timeout=30)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Authorization": "Bearer s3cret", "Content-Type": "application/json"})
        r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")

    got = {}
    t = threading.Thread(target=lambda: got.update(hc("POST", "/approval/ask", {"tool": "run_command", "details": "Plan: x\n$ ls", "timeout_s": 20})[1]))
    t.start()
    ticket = None
    for _ in range(40):
        ticket = hc("GET", "/approval")[1].get("approval")
        if ticket:
            break
        time.sleep(0.1)
    check("the engine shows the ask as an approval card (GET /approval: the tool and the details)", ticket and ticket["tool"] == "run_command"
          and "$ ls" in ticket["details"], ticket)
    hc("POST", "/approval", {"id": ticket["id"], "approved": True})
    t.join(10)
    check("... Allow -> the waiting ask returns approved", got.get("approved") is True, got)

# the window: on Home (the chat hidden) the card floats on top, Allow posts the answer
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


async def ui():
    import asyncio as _a  # noqa: F401
    UI = REPO / "app" / "ui"
    posted, tk = [], {"id": "t1", "tool": "run_command", "details": "DANGEROUS - x\n\nPlan: make a repo\n\nCommand:\n$ git init demo"}
    async with async_playwright() as pw:
        try:
            b = await pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            print("SKIP window part (%s)" % str(exc)[:80]); return
        page = await b.new_page(viewport={"width": 1300, "height": 860})

        async def route(r):
            bare = r.request.url.split("8902", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/approval" and r.request.method == "GET":
                return await r.fulfill(json={"ok": True, "approval": None if posted else tk})
            if bare == "/approval":
                posted.append(json.loads(r.request.post_data)); return await r.fulfill(json={"ok": True})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8902/**", route)
        await page.goto("http://127.0.0.1:8902/#token=s")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_selector(".approval.floating", timeout=8000)
        info = await page.evaluate("""(() => { const c = document.querySelector('.approval.floating'), r = c.getBoundingClientRect();
          return { text: c.textContent, inView: r.top >= 0 && r.bottom <= innerHeight && r.width > 200 }; })()""")
        check("on Home the approval card floats on screen (marked dangerous, with plan and command)", info["inView"]
              and "⚠" in info["text"] and "$ git init demo" in info["text"], info)
        await page.click(".approval.floating .allow")
        await page.wait_for_timeout(300)
        check("... Allow sends the answer", posted == [{"id": "t1", "approved": True}], posted)
        await b.close()

if async_playwright:
    import asyncio  # noqa: E402
    asyncio.run(asyncio.wait_for(ui(), 45))

check("without --shell (OpenCode's copy) there is no run_command", "run_command" not in [t["name"] for t in __import__("make_mcp").TOOLS])
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
