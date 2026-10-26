"""Output names, Blender MCP and Home's scroll bar (owner 2026-10-26: "get blender mcp going on both ...
orangize output files names better ... mac scroll bar at home doesnt work but windows works"). Offline: Blender
and uvx are faked, nothing is installed or started.

    python tests/test_outputs_blender.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-outnames-"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import out_names  # noqa: E402

AT = 1793037600.0
n = out_names.name("knight with sword and shield, professional concept art", "png", at=AT)
check("subject words first, filler and style words dropped", n.startswith("knight-sword-shield_"), n)
check("date stays in the name (YYYYMMDD-HHMM)", n.endswith(".png") and len(n.split("_")[1].split(".")[0]) == 13, n)
long = out_names.subject("painterly fantasy game concept art, wide cinematic shot of an ancient mountain shrine")
check("never cut mid-word ('cinemati')", long == "ancient-mountain-shrine", long)
check("all-filler prompt keeps its own words", out_names.subject("a beautiful concept art") != "untitled")
check("empty prompt -> fallback", out_names.subject("", "image") == "image")
check("a tag names the variant", out_names.name("fox", "png", tag="sprite64", at=AT).endswith("_sprite64.png"))
p1 = out_names.path(TMP / "images", "red fox", "png", at=AT)
p1.write_bytes(b"x")
p2 = out_names.path(TMP / "images", "red fox", "png", at=AT)
check("a taken name gets _2", p2.name == p1.stem + "_2.png", p2.name)
for fname, want in (("knight-sword-shield_20261026-1021_sprite64-x8.png", "knight sword shield"),
                    ("20261026-022217-red-fox-cub.jpg", "red fox cub"),
                    ("fox_20261026-1021_2.glb", "fox")):
    check("display name of %s" % fname, out_names.display_name(fname) == want, out_names.display_name(fname))
import creations  # noqa: E402
check("Home titles read new names", creations.title_of("knight-sword-shield_20261026-1021.png") == "Knight sword shield",
      creations.title_of("knight-sword-shield_20261026-1021.png"))

# every maker uses the one rule (no hand-rolled "%Y%m%d-%H%M%S-<slug>" names left in the makers)
makers = ["creative.py", "forge3d.py", "turnaround.py", "voice.py", "runners/imagegen.py"]
old = [m for m in makers if 'strftime("%Y%m%d-%H%M%S")' in (REPO / "engine" / m).read_text(encoding="utf-8")
       and "out_names" not in (REPO / "engine" / m).read_text(encoding="utf-8")]
check("makers name files through out_names", not old, old)

# ---- Blender MCP
import blender_link  # noqa: E402

cfg = json.loads((REPO / "engine" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
b = cfg.get("blender") or {}
check("blender MCP server registered, pinned to the add-on's commit (same protocol)", b.get("command") == "uvx"
      and b.get("args") == ["--from", "git+https://github.com/ahujasid/mcp-for-blender@febcd90", "mcp-for-blender"], b)
proto = [ln for ln in (REPO / "contrib/blender_mcp/addon.py").read_text(encoding="utf-8").splitlines()
         if ln.startswith("ADDON_PROTOCOL_VERSION")]
check("vendored add-on speaks protocol 15 (the pinned server's EXPECTED_ADDON_PROTOCOL_VERSION)",
      proto == ["ADDON_PROTOCOL_VERSION = 15"], proto)
import ast  # noqa: E402
_proof_src = (REPO / "engine/blender_scripts/mcp_proof.py").read_text(encoding="utf-8")
_q = "'" * 3
_build = _proof_src.split("BUILD = r" + _q, 1)[1].split(_q, 1)[0]
try:
    ast.parse(_proof_src)
    ast.parse(_build)
    check("the proof script and the campfire code the add-on runs are valid Python", bool(_build.strip()))
except SyntaxError as exc:
    check("the proof script and the campfire code the add-on runs are valid Python", False, exc)
check("telemetry off", (b.get("env") or {}).get("DISABLE_TELEMETRY") == "true")
check("starts only where Blender is installed", b.get("requires_check") == "blender_link.find_blender")
check("vendored add-on and its MIT licence", (REPO / "contrib/blender_mcp/addon.py").is_file()
      and "MIT" in (REPO / "contrib/blender_mcp/LICENSE").read_text(encoding="utf-8"))
mac = blender_link.candidates("darwin", Path("/Users/x"))
win = blender_link.candidates("win32", Path(r"C:\Users\x"))
check("looks on both OSes", isinstance(mac, list) and isinstance(win, list))

calls = []


def fake_run(argv, **kw):
    calls.append(argv)
    script = argv[argv.index("--python-expr") + 1] if "--python-expr" in argv else ""
    if "LOKI_ADDONS" in script:
        return types.SimpleNamespace(returncode=0, stdout="LOKI_ADDONS %s\n" % TMP, stderr="")
    src = Path(argv[argv.index("--") + 1])
    check("the vendored add-on is what gets installed", src.name == "addon.py" and src.is_file(), src)
    check("... copied into Blender's add-ons folder as blender_mcp.py (no addon_install operator: Blender 4.2+ safe)",
          "blender_mcp.py" in script and "addon_install" not in script, script[:200])
    check("... and LOKI's startup script (add-on on at launch + file inbox) into scripts/startup",
          "'startup'" in script and Path(argv[argv.index("--") + 2]).name == "loki_blender_startup.py")
    (TMP / "blender_mcp.py").write_text("x")
    return types.SimpleNamespace(returncode=0, stdout="LOKI_BLENDER_ADDON_OK (True, True)\n", stderr="")


fake = TMP / "blender"
fake.write_text("")
os.environ["LOKI_BLENDER"] = str(fake)
res = blender_link.setup(run=fake_run)
check("setup installs and enables the add-on", res.get("ok") and res.get("addon"), res)
check("setup runs Blender in the background (no window)", all("--background" in c for c in calls))


def fake_proof_run(argv, **kw):
    calls.append(argv)
    a = argv[argv.index("--") + 1:]
    Path(a[1]).write_bytes(b"glTF")
    rep = {"blender": "4.5.0", "ping": {"pong": True}, "objects": 22, "render_engine": "BLENDER_EEVEE_NEXT",
           "triangles": 1200, "glb": a[1], "png": a[2]}
    return types.SimpleNamespace(returncode=0, stdout="noise\nLOKI_PROOF " + json.dumps(rep) + "\n", stderr="")


pr = blender_link.proof(TMP / "ws", run=fake_proof_run)
check("proof: Blender runs mcp_proof.py with the vendored add-on, in the background",
      calls[-1][1:4] == ["--background", "--factory-startup", "--python"] and calls[-1][4].endswith("mcp_proof.py")
      and calls[-1][6].endswith("addon.py"), calls[-1])
check("proof: the model goes to models/, the render to renders/, named by out_names",
      pr.get("ok") and Path(pr["glb"]).parent.name == "models" and Path(pr["png"]).parent.name == "renders"
      and Path(pr["glb"]).name.startswith("campfire-blender-mcp_"), pr)
os.environ.pop("LOKI_BLENDER")
try:
    import loki  # noqa: E402  pylint: disable=wrong-import-position
except ImportError as exc:     # a cloud session without LOKI's venv: the machines run this part
    print("SKIP the MCP gate check (%s)" % exc)
    loki = None
if loki:
    blender_link.find_blender = lambda: ""
    check("MCP gate skips blender when it is not installed",
          "found nothing" in loki._server_skip_reason({"requires_check": "blender_link.find_blender"}, "blender"))
    blender_link.find_blender = lambda: "/x/blender"
    check("MCP gate passes when Blender is there",
          loki._server_skip_reason({"requires_check": "blender_link.find_blender"}, "blender") == "")

# the startup script, run against a fake bpy: a job in the inbox goes through the add-on's execute_command
fake_bpy = types.ModuleType("bpy")
fake_bpy.types = types.SimpleNamespace()
fake_bpy.app = types.SimpleNamespace(version_string="5.2.0", timers=types.SimpleNamespace(register=lambda *a, **k: None,
                                     is_registered=lambda f: False, unregister=lambda f: None))
fake_bpy.data = types.SimpleNamespace(filepath="")
ran = []
fake_bpy.types.blendermcp_server = types.SimpleNamespace(running=True, execute_command=lambda c: (ran.append(c) or
                                                         {"status": "success", "result": {"pong": True}}))
sys.modules["bpy"] = fake_bpy
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("loki_blender", REPO / "engine/blender_scripts/loki_blender_startup.py")
lb = importlib.util.module_from_spec(spec); spec.loader.exec_module(lb)
os.environ["LOKI_BLENDER_INBOX"] = str(TMP / "bl")
(TMP / "bl" / "inbox").mkdir(parents=True)
job = TMP / "bl" / "inbox" / "j1.json"
job.write_text(json.dumps([{"type": "ping", "params": {}}, {"type": "execute_code", "params": {"code": "print(1)"}}]))
os.utime(job, (time.time() - 5,) * 2)
lb.poll()
ans = json.loads((TMP / "bl" / "outbox" / "j1.json").read_text())
check("inbox: each command goes through the add-on's execute_command, the answer lands in outbox, the job in done",
      [c["type"] for c in ran] == ["ping", "execute_code"] and ans["ok"] and (TMP / "bl" / "done" / "j1.json").is_file(), ans)
lb._heartbeat()
check("heartbeat says Blender's version and whether the MCP socket is up",
      json.loads((TMP / "bl" / "status.json").read_text())["mcp_socket"] is True)
del sys.modules["bpy"]
os.environ.pop("LOKI_BLENDER_INBOX")

# ---- Home's scroll bar on the Mac (WebKit)
css = (REPO / "app/ui/home_layout.css").read_text(encoding="utf-8")
check("Home pane has a WebKit scroll bar you can grab", ".home-hub::-webkit-scrollbar {" in css
      and ".home-hub::-webkit-scrollbar-thumb {" in css)
check("the split's row is the window's height (WebKit sized it to content)", "grid-template-rows: minmax(0, 1fr); }" in css)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
