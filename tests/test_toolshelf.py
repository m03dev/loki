"""The Tool Shelf (engine/toolshelf.py): every shipped recipe is valid and every action's command line can be built;
installing (pip into the tool's own venv, a GitHub release zip, a git clone) and running work with fakes; paths stay in
the workspace; installs ask the owner. Offline, a few seconds.

    python tests/test_toolshelf.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-shelf-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


import toolshelf as ts  # noqa: E402

# ------------------------------------------------------------------ the shipped recipes
shipped = ts.recipes()
problems = [p for r in shipped.values() for p in ts.validate(r)]
check("every shipped recipe is valid (%d tools)" % len(shipped), shipped and not problems, problems[:12])
ws = TMP / "ws"
ws.mkdir()
for r in shipped.values():                 # a sample file of every kind a recipe takes
    for act in (r.get("actions") or {}).values():
        for spec in (act.get("args") or {}).values():
            for ext in spec.get("exts") or [".png"]:
                (ws / ("sample" + ext)).write_bytes(b"x")
(ws / "frames").mkdir()
(ws / "project").mkdir()
(ws / "project" / "project.godot").write_text("")
bad = []
for r in shipped.values():
    for name, act in (r.get("actions") or {}).items():
        args = {}
        for an, spec in (act.get("args") or {}).items():
            t = spec.get("type", "text")
            if t == "file":
                args[an] = "sample" + ((spec.get("exts") or [".png"])[0])
            elif t == "dir":
                args[an] = "project" if "project" in an else "frames"
            elif t == "out":
                args[an] = spec.get("default") or ("out/" + an + (spec.get("ext") or ".bin"))
            elif t in ("number", "int"):
                args[an] = spec.get("default", 1)
            elif t == "choice":
                args[an] = spec.get("default", (spec.get("choices") or [""])[0])
            elif t == "bool":
                args[an] = spec.get("default", False)
            else:
                args[an] = spec.get("default", "a test")
        try:
            cmd, outs, _ = ts.build_command(r, name, args, ws, TMP / "tools" / r["id"])
            if any("{" in c and "}" in c and not c.startswith("{\"") and "{" + "input_stem}" not in c
                   and not c.startswith("import") and "lambda" not in c for c in cmd if len(c) < 40):
                bad.append("%s.%s left a placeholder: %s" % (r["id"], name, cmd))
        except ts.ShelfError as exc:
            if "not installed" not in str(exc):
                bad.append("%s.%s: %s" % (r["id"], name, exc))
check("every action's command line builds from its own defaults", not bad, bad[:10])

r = ts.tool({"action": "run", "id": "postiz", "run": "publish", "args": {"text": "Out now!", "accounts": "x1"}}, ws)
check("publishing a post never happens without the owner's OK", not r["ok"] and "owner" in r["error"], r)
seen = []
r = ts.tool({"action": "run", "id": "postiz", "run": "publish", "args": {"text": "Out now!", "accounts": "x1"}}, ws,
            ask=lambda tool, detail: seen.append(detail) or False)
check("the owner sees the exact post and accounts before it goes out", seen and "Out now!" in seen[0] and "x1" in seen[0], seen)
check("godot-ai, Postiz, OpenShorts and Agent Sprite Forge are on the shelf",
      {"godot-ai", "postiz", "openshorts", "agent-sprite-forge"} <= set(shipped))
import opencode_engine as oe  # noqa: E402
proj = TMP / "proj"
(proj / "addons" / "godot_ai").mkdir(parents=True)
(proj / "addons" / "godot_ai" / "plugin.cfg").write_text('[plugin]\nname="Godot AI"\nversion="4.3.1"\n')
e = oe.godot_ai_mcp([proj], uvx="/usr/bin/uvx")
check("OpenCode gets godot-ai attach pinned to the project's add-on version", e.get("command", [])[:1] == ["/usr/bin/uvx"]
      and "godot-ai==4.3.1" in e["command"] and e["command"][-5:] == ["attach", "--port", "8000", "--ws-port", "9500"], e)
check("no add-on, or no uv: no godot-ai entry", oe.godot_ai_mcp([TMP], uvx="/usr/bin/uvx") == {} and oe.godot_ai_mcp([proj], uvx="") == {})
import subprocess as _sp  # noqa: E402
gp = TMP / "game"
gp.mkdir()
(gp / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="Game"\n')
out = _sp.run([sys.executable, str(REPO / "engine" / "runners" / "godot_addon.py"), str(proj / "addons" / "godot_ai"), str(gp)],
              capture_output=True, text=True)
pg = (gp / "project.godot").read_text()
check("the add-on helper copies an add-on into a project and switches it on", out.returncode == 0
      and (gp / "addons" / "godot_ai" / "plugin.cfg").is_file()
      and 'enabled=PackedStringArray("res://addons/godot_ai/plugin.cfg")' in pg, (out.stdout, pg))
out = _sp.run([sys.executable, str(REPO / "engine" / "runners" / "godot_addon.py"), str(proj / "addons" / "godot_ai"), str(gp)],
              capture_output=True, text=True)
check("never over an existing copy, never enabled twice", '"copied": false' in out.stdout
      and (gp / "project.godot").read_text().count("godot_ai/plugin.cfg") == 1, out.stdout)

here = "%d.%d" % sys.version_info[:2]
check("a tool's venv uses this Python when it is the version asked for",
      ts.venv_command(here, TMP / "v", which=lambda n: None)[:3] == [sys.executable, "-m", "venv"])
check("another version: pythonX.Y from the PATH", ts.venv_command("3.8", TMP / "v", which=lambda n: "/opt/py38" if n == "python3.8" else None)[0] == "/opt/py38")
check("none here: uv fetches it (with pip seeded)", ts.venv_command("3.8", TMP / "v", which=lambda n: "/bin/uv" if n == "uv" else None)
      == ["/bin/uv", "venv", "--seed", "--python", "3.8", str(TMP / "v")])
try:
    ts.venv_command("3.8", TMP / "v", which=lambda n: None)
    check("no such Python and no uv: says how to get it", False)
except ts.ShelfError as exc:
    check("no such Python and no uv: says how to get it", "astral.sh/uv" in str(exc))

# ------------------------------------------------------------------ install + run with fake recipes
fake_dir = TMP / "recipes"
fake_dir.mkdir()
(fake_dir / "fake.json").write_text(json.dumps([
    {"id": "zipper", "name": "Zipper", "area": "3d", "what": "a release binary", "repo": "https://github.com/a/zipper",
     "license": "MIT", "hardware": "cpu",
     "install": {"kind": "release", "release": {"repo": "a/zipper", "tag": "v1", "exe": "zipper",
                                               "assets": {"darwin": "z-mac.zip", "win32": "z-win.zip", "linux": "z-linux.zip"}}},
     "check": ["{exe}", "--version"],
     "actions": {"lod": {"what": "make a LOD", "cmd": ["{exe}", "-i", "{input}", "-o", "{output}", "-si", "{ratio}", "{fast}"],
                         "args": {"input": {"type": "file", "exts": [".glb"]},
                                  "output": {"type": "out", "ext": ".glb", "default": "{input_stem}-lod.glb"},
                                  "ratio": {"type": "number", "default": 0.5, "min": 0.01, "max": 1},
                                  "fast": {"type": "bool", "flag": "--fast", "optional": True}}}}},
    {"id": "pipper", "name": "Pipper", "area": "audio", "what": "a pip tool", "repo": "https://github.com/a/pipper",
     "license": "Apache-2.0", "install": {"kind": "pip", "pip": ["pipper==1.0"], "pip_platform": {sys.platform: ["extra-dep"]}},
     "check": ["{python}", "-c", "import pipper"],
     "actions": {"sfx": {"what": "a sound", "cmd": ["{python}", "-m", "pipper", "{prompt}", "-o", "{output}"],
                         "args": {"prompt": {"type": "text"}, "output": {"type": "out", "ext": ".wav", "default": "audio/sfx.wav"}}}}},
    {"id": "byhand", "name": "By hand", "area": "2d", "what": "manual", "repo": "https://github.com/a/b", "license": "GPL-3.0",
     "install": {"kind": "manual", "manual": "Download it from its site."}},
]))
ts.RECIPES = fake_dir
calls = []


class Proc:
    def __init__(self, rc=0, out="ok"):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def fake_run(cmd, **kw):
    calls.append(list(cmd))
    if cmd[1:3] == ["-m", "venv"]:
        py = Path(cmd[3]) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("")
    if "-o" in cmd:                                    # the tool "makes" its output
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"made")
    return Proc()


zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w") as z:
    z.writestr("zipper-1/zipper" + (".exe" if sys.platform == "win32" else ""), b"#!bin")
    z.writestr("../evil.txt", b"no")


class Resp:
    def __init__(self, data):
        self._b, self.headers = io.BytesIO(data), {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


urls = []
asked = []
r = ts.tool({"action": "install", "id": "zipper"}, ws, ask=lambda *a: asked.append(a) or False, runner=fake_run)
check("install asks the owner first, with the repo and licence; 'no' installs nothing", not r["ok"] and asked
      and "github.com/a/zipper" in asked[0][1] and "MIT" in asked[0][1] and not ts.installed("zipper"), (r, asked))
r = ts.tool({"action": "install", "id": "zipper"}, ws, ask=lambda *a: True, runner=fake_run,
            opener=lambda req, timeout=0: (urls.append(req.full_url), Resp(zbuf.getvalue()))[1])
exe = ts.find_exe(ts.tool_dir("zipper"), "zipper")
plat = "linux" if sys.platform.startswith("linux") else sys.platform
check("a release install downloads this OS's asset from GitHub and unpacks the program",
      r.get("ok") and urls == ["https://github.com/a/zipper/releases/download/v1/z-%s.zip" % {"darwin": "mac", "win32": "win", "linux": "linux"}[plat]]
      and exe and ts.installed("zipper"), (r, urls))
check("an archive cannot write outside the tool's folder", not (ts.tool_dir("zipper").parent / "evil.txt").exists()
      and not (ts.tool_dir("zipper") / "evil.txt").exists())
(ws / "sword.glb").write_bytes(b"glTF")
r = ts.tool({"action": "run", "id": "zipper", "run": "lod", "args": {"input": "sword.glb", "ratio": 5, "fast": True}}, ws,
            runner=fake_run)
cmd = calls[-1]
check("run fills the command: the program, workspace paths, a clamped number, a flag", r["ok"] and cmd[0] == exe
      and cmd[cmd.index("-i") + 1] == str((ws / "sword.glb").resolve()) and cmd[cmd.index("-si") + 1] == "1"
      and cmd[-1] == "--fast" and r["outputs"] == ["sword-lod.glb"], (r, cmd))
r = ts.tool({"action": "run", "id": "zipper", "run": "lod", "args": {"input": "sword.glb"}}, ws, runner=fake_run)
check("an optional flag left out is left out", "--fast" not in calls[-1], calls[-1])
r = ts.tool({"action": "run", "id": "zipper", "run": "lod", "args": {"input": "../../etc/passwd.glb"}}, ws, runner=fake_run)
check("a path outside the workspace is refused", not r["ok"] and "inside the workspace" in r["error"], r)
r = ts.tool({"action": "run", "id": "zipper", "run": "lod", "args": {"input": "sample.png"}}, ws, runner=fake_run)
check("a file of the wrong kind is refused", not r["ok"] and ".glb" in r["error"], r)
r = ts.tool({"action": "run", "id": "pipper", "run": "sfx", "args": {"prompt": "laser"}}, ws, runner=fake_run)
check("running a tool that is not installed says how to install it", not r["ok"] and "action=install" in r["error"], r)
calls.clear()
r = ts.install("pipper", run=fake_run)
venv_py = str(ts.venv_python(ts.tool_dir("pipper")))
check("a pip install makes the tool's OWN venv and installs into it (with this OS's extras)", r["ok"]
      and calls[0][1:3] == ["-m", "venv"] and calls[1][0] == venv_py and "pipper==1.0" in calls[1] and "extra-dep" in calls[1], calls)
r = ts.tool({"action": "run", "id": "pipper", "run": "sfx", "args": {"prompt": "laser zap"}}, ws, runner=fake_run)
check("its actions run with its own Python", r["ok"] and calls[-1][0] == venv_py and "laser zap" in calls[-1]
      and r["outputs"] == ["audio/sfx.wav"], (r, calls[-1]))
r = ts.tool({"action": "install", "id": "byhand"}, ws, ask=lambda *a: True)
check("a manual tool says how to get it instead of installing", not r["ok"] and r.get("manual") and "site" in r["error"], r)
lst = ts.tool({"action": "list", "area": "3d"}, ws)
check("list by area", [t["id"] for t in lst["tools"]] == ["zipper"] and lst["tools"][0]["installed"], lst)
code, d = ts.route(None, "GET", "/tools/shelf", {}, {})
check("GET /tools/shelf for the window", code == 200 and {t["id"] for t in d["tools"]} == {"zipper", "pipper", "byhand"})
r = ts.tool({"action": "remove", "id": "zipper"}, ws, ask=lambda *a: True)
check("remove deletes the tool's folder", r["ok"] and not ts.tool_dir("zipper").exists())
check("a bad id cannot reach outside the tools folder", ts.tool({"action": "remove", "id": "../x"}, ws)["ok"] is False)
js = (REPO / "app" / "ui" / "toolshelf.js").read_text()
check("Settings > Add-ons has the Tool Shelf (install asks in the row)", "/tools/shelf/install" in js and "confirmRow" in js
      and "toolshelf.js" in (REPO / "app" / "ui" / "index.html").read_text())
import make_mcp  # noqa: E402
check("the agents' tool server has 'toolshelf' and loki-make shelf", any(t["name"] == "toolshelf" for t in make_mcp.TOOLS)
      and make_mcp.CLI["shelf"] == "toolshelf")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
