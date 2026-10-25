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

# the server, started the way Ziva starts it
srv = cfg["mcpServers"]["loki"]
msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_command", "arguments": {
            "command": "mkdir -p ziva-demo && cd ziva-demo && git init -q -b main && echo '# ziva-demo' > README.md && git add -A && "
                       "git -c user.name=t -c user.email=t@t commit -qm 'first from Ziva' && git log --oneline"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "run_command", "arguments": {"command": "rm -rf ~"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "run_command", "arguments": {"command": "ls", "folder": "/etc"}}}]
env = dict(os.environ)
p = subprocess.run([srv["command"], *srv["args"]], input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True,
                   text=True, timeout=40, cwd=str(agent), env=env)
out = {m["id"]: m for m in (json.loads(x) for x in p.stdout.splitlines() if x.strip())}
names = [t["name"] for t in out[2]["result"]["tools"]]
check("the server offers run_command (plus pictures, 3D, video, the other machine)", "run_command" in names and "make_image" in names
      and "run_on_machine" in names, names)
res = json.loads(out[3]["result"]["content"][0]["text"])
log = subprocess.run(["git", "-C", str(PROJ / "Home" / "ziva-demo"), "log", "--oneline"], capture_output=True, text=True)
check("run_command REALLY made a git repo with a commit in ~/LOKI Projects/Home", res["ok"] and "first from Ziva" in log.stdout, (res, log.stdout))
check("a dangerous command is refused", "refused" in out[4]["result"]["content"][0]["text"])
check("a folder outside home is refused", "inside your home" in out[5]["result"]["content"][0]["text"])
check("without --shell (OpenCode's copy) there is no run_command", "run_command" not in [t["name"] for t in __import__("make_mcp").TOOLS])
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
