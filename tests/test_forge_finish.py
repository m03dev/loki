"""Forge + Blender: Clean up, FBX / glTF export, cleanup after a make, ComfyUI auto-start (owner 2026-10-26: "i should
be able to open inside forge make them fbx and glb or gltf files clean up everything and make sure things are
working ... some of the models come out like garbage"). Blender and ComfyUI are faked; the real runs are on the PC.

    python tests/test_forge_finish.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-finish-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_COMFY_AUTOSTART"] = "0"
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import blender_link  # noqa: E402
import forge3d  # noqa: E402
import forge_api  # noqa: E402


class St:
    class agent:  # noqa: N801
        WORKSPACE = TMP


st = St()
models = forge_api.models_dir(st)
models.mkdir(parents=True, exist_ok=True)
(models / "creature.glb").write_bytes(b"glTF\x02\x00\x00\x00raw")
calls = {}


def fake_polish(model, out_dir, name="", **kw):
    calls["polish"] = (Path(model).name, kw)
    out = Path(out_dir)
    glb = out / "models" / "creature-polished_20261026-1500.glb"
    (out / "renders").mkdir(parents=True, exist_ok=True)
    (out / "renders" / "creature-polished_20261026-1500.png").write_bytes(b"\x89PNG")
    files = [glb, glb.with_suffix(".fbx"), out / "models" / "creature-polished_20261026-1500_gltf" / "x.gltf", glb.with_suffix(".blend")]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"glTF" if f.suffix == ".glb" else b"x")
    return {"ok": True, "via": "window", "files": {"render": str(out / "renders" / "creature-polished_20261026-1500.png"),
                                                   "models": [str(f) for f in files]},
            "quality": {"verdict": "rough", "problems": ["bumpy surface (14 deg)"]}}


def fake_convert(path, to, out_dir=None, **kw):
    calls["convert"] = (Path(path).name, to)
    f = Path(path).with_suffix("." + to)
    f.write_bytes(b"FBX")
    return {"ok": True, "file": str(f)}


blender_link.polish, blender_link.convert, blender_link.find_blender = fake_polish, fake_convert, lambda: "/x/blender"


def run(route, body):
    code, job = forge_api.handle_post(st, route, json.dumps(body).encode(), thread=False)
    return code, (forge3d.job(job.get("id", "")) or {}).get("result", {}) if code == 200 else job


code, r = run("/forge/finish", {"name": "creature.glb", "symmetric": True})
check("Clean up: the model goes through Blender's repair + polish", code == 200 and r.get("ok") and calls["polish"][0] == "creature.glb"
      and calls["polish"][1].get("symmetric") is True, (code, r))
check("... Forge gets the cleaned .glb to open, every format made, the render and the quality verdict",
      r.get("name") == "creature-polished_20261026-1500.glb" and len(r.get("files", [])) == 4
      and r.get("render", "").startswith("renders/") and r.get("quality", {}).get("verdict") == "rough", r)
code, r = run("/forge/convert", {"name": "creature.glb", "to": "fbx"})
check("FBX: Blender converts the saved .glb", code == 200 and r.get("ok") and r.get("file") == "creature.fbx"
      and calls["convert"] == ("creature.glb", "fbx"), r)
code, r = forge_api.handle_post(st, "/forge/finish", json.dumps({"name": "../secrets.glb"}).encode(), thread=False)
check("only models/ files", code == 404, r)
blender_link.find_blender = lambda: ""
code, r = forge_api.handle_post(st, "/forge/finish", json.dumps({"name": "creature.glb"}).encode(), thread=False)
check("no Blender: says how to install it", code == 400 and "setup --install" in r.get("error", ""), r)
blender_link.find_blender = lambda: "/x/blender"

# a make: cleaned up afterwards (and a failed cleanup keeps the raw model)
forge3d.make_3d = lambda *a, **k: {"ok": True, "glb": str(models / "creature.glb"), "name": "creature.glb", "backend": "pixal3d",
                                   "prompt": "a little dragon"}
code, r = run("/forge/make", {"prompt": "a little dragon"})
check("make -> Blender cleanup -> Forge opens the cleaned model, the raw one kept",
      r.get("ok") and r.get("finished") and r.get("name") == "creature-polished_20261026-1500.glb" and r.get("raw") == "creature.glb", r)
blender_link.polish = lambda *a, **k: {"ok": False, "results": [{"status": "error", "message": "bake failed"}]}
code, r = run("/forge/make", {"prompt": "a little dragon"})
check("a cleanup that fails keeps the raw model and says why", r.get("ok") and r.get("name") == "creature.glb"
      and "bake failed" in r.get("finish_error", ""), r)
calls.clear()
blender_link.polish = fake_polish
code, r = run("/forge/make", {"prompt": "x", "finish": False})
check("finish=false skips the cleanup", r.get("ok") and "polish" not in calls, r)
forge3d.make_3d = lambda *a, **k: {"ok": True, "glb": str(models / "creature.glb"), "name": "creature.glb", "backend": "lift"}
code, r = run("/forge/make", {"prompt": "x", "backend": "lift"})
check("a lift draft is not dressed up as a finished model", r.get("ok") and "polish" not in calls and not r.get("finished"), r)

# ComfyUI auto-start
import comfy_autostart as ca  # noqa: E402
os.environ["LOKI_COMFY_AUTOSTART"] = "1"
state = {"up": False, "started": 0}


def opener(url, timeout=0):
    if not state["up"]:
        raise OSError("refused")
    return types.SimpleNamespace(__enter__=lambda s: s, __exit__=lambda s, *a: False, status=200)


class R:
    status = 200

    def __enter__(self):
        if not state["up"]:
            raise OSError("refused")
        return self

    def __exit__(self, *a):
        return False


op = lambda url, timeout=0: R()   # noqa: E731
t = {"now": 0.0}


def starter():
    state["started"] += 1
    state["up"] = True


r = ca.ensure("http://127.0.0.1:8188", wait=30, opener=op, starter=starter, sleep=lambda s: t.update(now=t["now"] + s), clock=lambda: t["now"])
check("ComfyUI on this computer, not running -> started and waited for", r == {"ok": True, "started": True} and state["started"] == 1, r)
r = ca.ensure("http://127.0.0.1:8188", opener=op, starter=starter)
check("already running -> nothing started", r == {"ok": True, "started": False} and state["started"] == 1, r)
state["up"] = False
r = ca.ensure("http://192.168.1.20:8188", opener=op, starter=starter)
check("a ComfyUI on another computer is never started from here", not r["ok"] and "another computer" in r["why"] and state["started"] == 1, r)
r = ca.ensure("http://127.0.0.1:8188", opener=op)
check("not installed here -> says how to install it", not r["ok"] and "--install" in r["why"], r)
os.environ["LOKI_COMFY_AUTOSTART"] = "0"
check("LOKI_COMFY_AUTOSTART=0 turns it off", "off" in ca.ensure("http://127.0.0.1:8188", opener=op, starter=starter)["why"])

# the ComfyUI prompt ids are real UUIDs (the PC: "prompt_id must be a valid UUID")
import re  # noqa: E402
for f in ("forge_trellis.py", "comfy_jobs.py", "forge_hunyuan.py", "ai_renderer.py"):
    text = (REPO / "engine" / f).read_text(encoding="utf-8")
    check("%s: prompt ids are dashed UUIDs" % f, not re.search(r"pid(, t0)? = uuid\.uuid4\(\)\.hex", text))

# the Forge window: Clean up + FBX/glTF in Export
js = (REPO / "app/ui/forge.js").read_text(encoding="utf-8")
check("Forge has Clean up and FBX / glTF export", 'forgeBtn("sparkle", "Clean up"' in js and '["fbx", "FBX (.fbx)"' in js
      and '["gltf", "glTF + files (.gltf)"' in js and "/forge/convert" in js and "/forge/finish" in js)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
