"""loki-make (engine/make_mcp.py): LOKI's picture / 3D / video makers for the agent as an MCP server over stdio.

The real server in a subprocess speaks MCP (initialize, tools/list, tools/call); the tools save into the agent's
working folder and never outside it; make_image runs LOKI's image runner, make_3d lifts a picture to .glb/.obj;
OpenCode's config starts the server (not in Plan mode). Fakes stand in for the image model and the 3D lift.
Under a minute.

    python tests/test_make_mcp.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import make_mcp  # noqa: E402
import opencode_engine  # noqa: E402

PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


# ---- the protocol, in a real process
work = Path(tempfile.mkdtemp(prefix="loki-make-"))
proc = subprocess.Popen([sys.executable, str(REPO / "engine" / "make_mcp.py")], cwd=str(work), stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def rpc(mid, method, params=None):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}})
check("initialize: the server says it is loki-make and has tools", init["result"]["serverInfo"]["name"] == "loki-make"
      and "tools" in init["result"]["capabilities"], init)
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); proc.stdin.flush()
names = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
check("tools/list: make_image, upscale_image, make_3d, make_video (then the machine tools)", [n for n in names if n not in ("pixelize", "voice", "toolshelf", "make_music", "library", "render_scene", "make_sprite", "make_turnaround")][:4] == ["make_image", "upscale_image", "make_3d", "make_video"] and "pixelize" in names and "voice" in names, names)
r = rpc(3, "tools/call", {"name": "make_image", "arguments": {"prompt": ""}})
check("a call with no prompt is an error answer, not a dead server", r["result"]["isError"] and "describe" in r["result"]["content"][0]["text"], r)
r = rpc(4, "tools/call", {"name": "make_image", "arguments": {"prompt": "a fox", "folder": "../outside"}})
check("a folder outside the working folder is refused", r["result"]["isError"] and "inside the working folder" in r["result"]["content"][0]["text"], r)
check("... and nothing was made outside", not (work.parent / "outside").exists())
r = rpc(5, "nope")
check("an unknown method is a JSON-RPC error", r.get("error", {}).get("code") == -32601, r)
proc.stdin.close(); proc.wait(5)

# ---- the tools, with fakes for the models
seen = {}


def fake_runner(argv, input=None, **kw):   # noqa: A002 - subprocess.run's name
    job = json.loads(input)
    seen.update(job)
    out = Path(job["out_dir"]); out.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(int(job.get("count") or 1)):
        f = out / ("pic%d.png" % i); f.write_bytes(b"\x89PNG fake"); files.append(str(f))
    return types.SimpleNamespace(stdout=json.dumps({"ok": True, "file": files[0], "files": files, "backend": "fake", "seed": 7}), stderr="")


res = make_mcp.make_image({"prompt": "an oil painting of a lighthouse at dusk", "count": 3, "folder": "art/paintings"}, work, runner=fake_runner)
check("make_image: three pictures saved in the folder asked for, paths relative to the working folder",
      res["ok"] and res["files"] == ["art/paintings/pic0.png", "art/paintings/pic1.png", "art/paintings/pic2.png"]
      and all((work / f).is_file() for f in res["files"]), res)
check("... the prompt went to LOKI's image runner as written", seen.get("prompt") == "an oil painting of a lighthouse at dusk" and seen.get("count") == 3, seen)
fail_runner = lambda argv, input=None, **kw: types.SimpleNamespace(stdout=json.dumps({"ok": False, "error": "no image backend"}), stderr="")  # noqa: E731
res = make_mcp.make_image({"prompt": "x"}, work, runner=fail_runner)
check("make_image: a model that fails says so (no fake success)", not res["ok"] and "no image backend" in res["error"], res)


def fake_make(src, out, prompt, backend, image_maker=None):
    pic = image_maker(prompt) if not src else src
    glb = Path(out) / "ship.glb"; glb.write_bytes(b"glTF"); obj = Path(out) / "ship.obj"; obj.write_text("v 0 0 0\n")
    return {"ok": True, "glb": str(glb), "obj": str(obj), "backend": "lift", "meta": {"triangles": 12}, "pic": pic}


res = make_mcp.make_3d({"prompt": "a small wooden boat"}, work, runner=fake_runner, make=fake_make)
check("make_3d from a description: drawn first, then a .glb and .obj in models/", res["ok"] and res["files"] == ["models/ship.glb", "models/ship.obj"]
      and "single object" in seen.get("prompt", ""), (res, seen.get("prompt")))
res = make_mcp.make_3d({"image": "../secret.png"}, work, make=fake_make)
check("make_3d: a picture outside the folder is refused", not res["ok"], res)

# ---- OpenCode starts it
cfg = opencode_engine.build_config({"local": {"base_url": "http://127.0.0.1:11434/v1", "model": "m", "key": ""}}, "")
check("OpenCode's config starts loki-make (python engine/make_mcp.py)", cfg["mcp"]["loki-make"]["command"][-1].endswith("make_mcp.py")
      and cfg["mcp"]["loki-make"]["enabled"], cfg.get("mcp"))
cfg = opencode_engine.build_config({"local": {"base_url": "http://127.0.0.1:11434/v1", "model": "m", "key": ""}}, "", plan=True)
check("... but not in Plan mode (making files is not planning)", "loki-make" not in (cfg.get("mcp") or {}), cfg.get("mcp"))

check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
import contextlib as _cl, io as _io, tempfile as _tf  # noqa: E402
_d = Path(_tf.mkdtemp())
_seen = {}
_orig = make_mcp.call
make_mcp.call = lambda name, args, cwd: (_seen.update({name: dict(args)}), {"ok": True})[1]
(_d / "fox.jpg").write_bytes(b"x")
with _cl.redirect_stdout(_io.StringIO()):
    make_mcp.cli(["render", "models/x.glb", "--frames", "48"], _d)
    make_mcp.cli(["voice", "hello there"], _d)
    make_mcp.cli(["3d", "fox.jpg"], _d)
    make_mcp.cli(["3d", "a red fox"], _d)
make_mcp.call = _orig
check("loki-make render <file> passes the file as the model (it was sent as the prompt)",
      _seen.get("render_scene", {}).get("model") == "models/x.glb" and _seen["render_scene"].get("frames") == 48, _seen)
check("loki-make voice <text> speaks it", _seen.get("voice") == {"text": "hello there", "action": "speak"}, _seen)
check("loki-make 3d <picture> is a picture, <words> a description",
      _seen.get("make_3d", {}).get("prompt") == "a red fox", _seen)
import time as _time  # noqa: E402
_d3 = Path(_tf.mkdtemp())
(_d3 / "images").mkdir()
(_d3 / "images" / "old.png").write_bytes(b"x")
_time.sleep(0.02)
(_d3 / "images" / "golem.png").write_bytes(b"x")
_e = make_mcp.make_3d({"backend": "online"}, _d3)
check("make_3d without a picture says exactly what to send, naming the newest picture here",
      not _e["ok"] and 'image="images/golem.png"' in _e["error"], _e)
_got = {}
make_mcp.make_3d({"image_path": "images/golem.png", "backend": "lift"}, _d3,
                 make=lambda src, out, prompt, backend, **kw: (_got.update(src=src), {"ok": False, "error": "x"})[1])
check("make_3d also takes image_path / path / file for the picture", str(_got.get("src", "")).endswith("golem.png"), _got)
_dw = Path(_tf.mkdtemp())
(_dw / "images").mkdir()
_saved_run = make_mcp.run_imagegen


def _weak(job, runner):
    f = Path(job["out_dir"]) / "orc.jpg"
    f.write_bytes(b"x")
    return {"ok": True, "files": [str(f)], "backend": "pollinations"}


make_mcp.run_imagegen = _weak
_w = make_mcp.make_image({"prompt": "an orc warlord", "style": "game-concept"}, _dw)
check("no special Pollinations path any more (it is gone as a backend, owner 2026-10-26)",
      "pollinations" not in (REPO / "engine" / "make_mcp.py").read_text(encoding="utf-8").lower())
make_mcp.run_imagegen = _saved_run
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
