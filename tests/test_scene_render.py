"""Renders without the window (engine/scene_passes.py + engine/render_agent.py): passes from a .glb, and the
render_scene tool's still / turntable jobs with a stand-in for ComfyUI. Offline, a few seconds.

    python tests/test_scene_render.py
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-scenerender-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import ai_renderer  # noqa: E402
import forge3d  # noqa: E402
import render_agent  # noqa: E402
import scene_passes  # noqa: E402


def sphere(n, r=1.0, c=(0.0, 0.0, 0.0)):
    u, v = np.meshgrid(np.linspace(0, np.pi, n), np.linspace(0, 2 * np.pi, 2 * n))
    p = np.stack([np.sin(u) * np.cos(v), np.cos(u), np.sin(u) * np.sin(v)], -1).reshape(-1, 3)
    cols = n
    f = []
    for i in range(2 * n - 1):
        for j in range(cols - 1):
            a = i * cols + j
            f += [[a, a + cols, a + 1], [a + 1, a + cols, a + cols + 1]]
    return p * r + np.array(c), p, np.array(f)


def write(path, parts):
    pos, nrm, col, idx, base = [], [], [], [], 0
    for (p, n, f), c in parts:
        pos += [tuple(map(float, x)) for x in p]
        nrm += [tuple(map(float, x)) for x in n]
        col += [c] * len(p)
        idx += [int(i) + base for i in f.reshape(-1)]
        base += len(p)
    forge3d.write_glb(path, {"positions": pos, "normals": nrm, "colors": col, "indices": idx})
    return path


WS = TMP / "ws"
(WS / "models").mkdir(parents=True)
small = write(WS / "models" / "pair.glb", [(sphere(24), (0.9, 0.3, 0.2)), (sphere(16, 0.5, (1.2, 0, 0.3)), (0.2, 0.5, 0.9))])

# ------------------------------------------------------------------ the passes
res = scene_passes.render(small, TMP / "p1", frames=1, passes=scene_passes.PASSES, width=320, height=192)
imgs = {p: np.asarray(Image.open(res["passes"][p][0]).convert("L"), np.float32) for p in scene_passes.PASSES}
check("all four passes are written at the asked size", all(Image.open(res["passes"][p][0]).size == (320, 192)
                                                           for p in scene_passes.PASSES), res["passes"])
d = imgs["depth"]
check("depth: the background is black and the model is lit up", d[0, 0] == 0 and d.max() > 150, (d[0, 0], d.max()))
check("depth: the near side is whiter than the far side (VACE's polarity)",
      d[96, 160] > np.percentile(d[d > 0], 10), (d[96, 160], np.percentile(d[d > 0], 10)))
la = imgs["lineart"]
check("lineart: white lines on black - a thin outline, not a filled shape", 0.003 < (la > 128).mean() < 0.12,
      (la > 128).mean())
nrm = np.asarray(Image.open(res["passes"]["normal"][0]).convert("RGB"), np.float32)
top = nrm[np.nonzero(d > 0)[0].min() + 3, 160]
check("normal: the top of the sphere faces up (green)", top[1] > top[0] and top[1] > 160, top)
b = np.asarray(Image.open(res["passes"]["beauty"][0]).convert("RGB"), np.float32)
check("beauty: the vertex colours come through (red sphere)", b[96, 160, 0] > b[96, 160, 2] + 40, b[96, 160])

turn = scene_passes.render(small, TMP / "p2", frames=4, passes=["depth"], width=160, height=96)
a0 = np.asarray(Image.open(turn["passes"]["depth"][0]))
a2 = np.asarray(Image.open(turn["passes"]["depth"][2]))
check("a turntable writes one frame per step and the view turns", len(turn["passes"]["depth"]) == 4
      and np.abs(a0.astype(int) - a2).mean() > 1)
fills = [float((np.asarray(Image.open(p)) > 0).mean()) for p in turn["passes"]["depth"]]
check("the camera keeps the whole model in frame on every frame", all(0.05 < f < 0.9 for f in fills), fills)

# depth stays put across a turntable: a sphere at the centre looks the same from every side
ball = write(TMP / "ball.glb", [(sphere(24), (1, 1, 1))])
bt = scene_passes.render(ball, TMP / "p3", frames=3, passes=["depth"], width=96, height=96)
vals = [np.asarray(Image.open(p))[48, 48, 0] for p in bt["passes"]["depth"]]
check("depth is normalised the same on every frame (no pumping)", max(vals) - min(vals) <= 2, vals)

big = write(TMP / "big.glb", [(sphere(160), (0.8, 0.8, 0.8)), (sphere(40, 0.5, (1.2, 0, 0.3)), (0.2, 0.5, 0.9))])
t0 = time.time()
r = scene_passes.render(big, TMP / "p4", frames=1, passes=scene_passes.PASSES, width=832, height=480)
took = time.time() - t0
check("100k triangles, all four passes at 832x480 in under 3 s", r["triangles"] > 100000 and took < 3, (r["triangles"], took))

draco = TMP / "draco.glb"
js = json.dumps({"asset": {"version": "2.0"}, "extensionsRequired": ["KHR_draco_mesh_compression"]}).encode()
js += b" " * ((-len(js)) % 4)
draco.write_bytes(struct.pack("<III", 0x46546C67, 2, 20 + len(js)) + struct.pack("<II", len(js), 0x4E4F534A) + js)
try:
    scene_passes.load(draco)
    check("a Draco-compressed model is refused with how to fix it", False)
except scene_passes.PassError as exc:
    check("a Draco-compressed model is refused with how to fix it", "gltf-transform" in str(exc), exc)

# ------------------------------------------------------------------ the render_scene tool
out = render_agent.render({"model": "pair.glb"}, WS)
check("no prompt: passes and a contact sheet in renders/, no GPU", out["ok"] and Path(out["sheet"]).is_file()
      and "/renders/" in out["sheet"].replace("\\", "/") and out["passes"]["depth"] == 1, out)
check("a missing model says where models live", not render_agent.render({"model": "nope.glb"}, WS)["ok"])

started = []


def fake_start(state, job, wait):
    started.append((job, wait))
    m = ai_renderer.manifest(state, job)
    ext = ".png" if m["workflow"] == render_agent.STILL else ".mp4"
    target = ai_renderer.job_dir(state, job) / ("result" + ext)
    if ext == ".png":
        Image.new("RGB", (32, 32), (90, 30, 20)).save(target)
    else:
        target.write_bytes(b"not really a video")
    if wait:
        ai_renderer.update(state, job, lambda mm: mm.update(status="succeeded", outputs=["result" + ext]))
    else:
        ai_renderer.update(state, job, lambda mm: mm.update(status="running"))
    return ai_renderer.manifest(state, job)


still = render_agent.render({"model": "pair.glb", "prompt": "a red planet and its moon, painted", "size": "500x300"},
                            WS, starter=fake_start)
sm = ai_renderer.manifest(None, still.get("job", "")) or {}
check("prompt + 1 frame: a depth-steered still job, waited for, its picture in renders/",
      still["ok"] and still["files"] and Path(still["files"][0]).is_file() and sm.get("workflow") == render_agent.STILL
      and started[-1][1] is True, still)
check("the still's size is snapped to 16 and the depth pass was handed over",
      sm.get("params", {}).get("width") == 496 and sm.get("params", {}).get("height") == 304
      and sm.get("passes", {}).get("depth", {}).get("frames") == 1, sm.get("params"))

vid = render_agent.render({"model": "pair.glb", "prompt": "a red planet turning", "frames": 30, "size": "320x192"},
                          WS, starter=fake_start)
vm = ai_renderer.manifest(None, vid["job"]) if vid.get("job") else {}
check("prompt + frames: a still is made first, then the turntable runs in the background",
      vid["ok"] and vm.get("workflow") == render_agent.VIDEO and started[-1][1] is False
      and started[-2][1] is True and Path(vid["start_image"]).is_file(), vid)
check("frames are rounded up to 4n+1 and every pass frame is there",
      vid["frames"] == 33 and vm["passes"]["depth"]["frames"] == 33 and vm["passes"]["lineart"]["frames"] == 33
      and vm["passes"]["start"]["frames"] == 1, (vid.get("frames"), vm.get("passes")))
st = render_agent.render({"action": "status", "job": vid["job"]}, WS)
check("status while running says so and brings nothing yet", st["status"] == "running" and "files" not in st, st)
ai_renderer.update(None, vid["job"], lambda mm: mm.update(status="succeeded", outputs=["result.mp4"]))
st = render_agent.render({"action": "status", "job": vid["job"]}, WS)
check("status when done copies the video into renders/", st.get("files") and st["files"][0].endswith(".mp4")
      and Path(st["files"][0]).is_file(), st)

jpg = WS / "look.jpg"
Image.new("RGB", (64, 64), (200, 40, 40)).save(jpg)
n = len(started)
v2 = render_agent.render({"model": "pair.glb", "prompt": "x", "frames": 5, "start": "look.jpg", "size": "160x96"},
                         WS, starter=fake_start)
check("start= given: no still is made, a JPEG start is turned into PNG", v2["ok"] and len(started) == n + 1
      and (ai_renderer.manifest(None, v2["job"]) or {}).get("passes", {}).get("start"), v2)


def failing(state, job, wait):
    ai_renderer.update(state, job, lambda mm: (mm.update(status="failed"),
                                               mm["log"].append({"t": 0, "msg": "ComfyUI is not reachable"})))
    return ai_renderer.manifest(state, job)


bad = render_agent.render({"model": "pair.glb", "prompt": "x"}, WS, starter=failing)
check("a failed still says why", not bad["ok"] and "not reachable" in bad["error"], bad)

import make_mcp  # noqa: E402
check("loki-make lists render_scene and `loki-make render` maps to it",
      any(t["name"] == "render_scene" for t in make_mcp.TOOLS) and make_mcp.CLI.get("render") == "render_scene")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
