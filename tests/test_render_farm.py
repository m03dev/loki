"""Studio's render farm manager (engine/render_farm.py) and the Engine tab's Carbon Editor (engine/carbon_editor.py).

Fake workers (no ComfyUI, no GPU): planning by priority / pools / dependencies, best worker by free VRAM, a failure
requeued on another worker, blacklisting after 2 errors, max errors, suspend / resume / requeue / delete, the farm
doctor's readings, ETA from history; Carbon: status without a build, open / build with a fake Popen. Offline, a few s.

    python tests/test_render_farm.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-farm-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PEERS"] = ""
os.environ["LOKI_COMFYUI_URL"] = "http://127.0.0.1:8188"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import ai_renderer as AR  # noqa: E402
import carbon_editor as CE  # noqa: E402
import render_farm as RF  # noqa: E402

PC, MAC = "http://192.168.50.7:8188", "http://127.0.0.1:8188"
LIVE = {PC: {"online": True, "gpu": "RTX 3070 Ti", "vram_total": 8e9, "vram_free": 7e9, "queue": 0},
        MAC: {"online": True, "gpu": "Apple M2", "vram_total": 16e9, "vram_free": 2e9, "queue": 0}}
started = []


def probe(url):
    r = LIVE.get(url)
    if not r:
        raise OSError("connection refused")
    return dict(r)


def starter(state, job, url):
    started.append((job, url))
    AR._set(state, job, "running", "fake run", comfy_url=url)


def ai_job(name, frames=8):
    return AR.new_job(None, {"name": name, "kind": "ai", "workflow": "vace_render", "frames": frames})["job"]


f = RF.Farm(None, probe=probe, starter=starter)
f.set_worker({"url": PC, "name": "PC"})
names = {w["url"]: w["name"] for w in f.workers()}
check("workers: the Studio's ComfyUI and an added one, probed", names.get(PC) == "PC" and MAC in names and all(w["online"] for w in f.workers()), names)

# ---- priorities, best worker
a = f.submit({"render_job": ai_job("low"), "priority": 10})
b = f.submit({"render_job": ai_job("high"), "priority": 90})
c = f.submit({"render_job": ai_job("after high"), "priority": 100, "depends": [b["id"]]})
got = f.tick()
check("the high-priority job goes first, to the worker with the most free VRAM (the PC)", got[0] == (b["id"], PC), got)
check("both idle workers get a job; the dependent one waits", {j for j, _ in got} == {a["id"], b["id"]} and f.data["jobs"][c["id"]]["status"] == "queued", got)
check("the farm job is active on its worker", f.data["jobs"][b["id"]]["status"] == "active" and f.data["jobs"][b["id"]]["worker"] == PC)

# ---- completion frees the worker, dependency runs
AR._set(None, b["render_job"], "succeeded", "done")
f.tick()
check("a finished render completes the farm job (history kept)", f.data["jobs"][b["id"]]["status"] == "completed" and f.data["history"][-1]["id"] == b["id"])
check("...and the job that waited for it starts on the freed worker", f.data["jobs"][c["id"]]["status"] == "active" and f.data["jobs"][c["id"]]["worker"] == PC)

# ---- failure: requeue on another, blacklist, max errors
d = f.submit({"render_job": ai_job("flaky"), "max_errors": 3, "pool": "gpu"})
AR._set(None, f.data["jobs"][a["id"]]["attempts"][-1], "succeeded", "done")
AR._set(None, f.data["jobs"][c["id"]]["attempts"][-1], "succeeded", "done")
f.tick()
w1 = f.data["jobs"][d["id"]]["worker"]
AR._set(None, f.data["jobs"][d["id"]]["attempts"][-1], "failed", "CUDA out of memory. Tried to allocate 2 GiB")
f.tick()
j = f.data["jobs"][d["id"]]
check("a failed render is requeued with a fresh attempt (a retry copy)", len(j["attempts"]) == 2 and j["status"] in ("queued", "active"), j["status"])
check("the farm doctor reads it: out of VRAM, with the fix", "video memory" in RF.diagnose(j["errors"])[0]["cause"], RF.diagnose(j["errors"]))
for _ in range(3):
    if f.data["jobs"][d["id"]]["status"] != "active":
        f.tick()
    jj = f.data["jobs"][d["id"]]
    if jj["status"] == "active":
        AR._set(None, jj["attempts"][-1], "failed", "connection refused")
        f.tick()
j = f.data["jobs"][d["id"]]
check("after max errors the job fails", j["status"] == "failed" and len(j["errors"]) == 3, (j["status"], len(j["errors"])))
check("a worker that failed it twice is blacklisted for it", any(j["errors"].count(e) for e in j["errors"]) and (len(j["blacklist"]) >= 1), j["blacklist"])
check("worker stats count the failures", sum(s.get("failed", 0) for s in f.data["stats"].values()) == 3, f.data["stats"])

# ---- actions
e = f.submit({"render_job": ai_job("held")})
f.action(e["id"], "suspend")
check("suspend: it doesn't start", (e["id"] not in [x for x, _ in f.tick()]) and f.data["jobs"][e["id"]]["status"] == "suspended")
f.action(e["id"], "resume"); f.action(e["id"], "priority", 77)
check("resume + priority", f.data["jobs"][e["id"]]["status"] == "queued" and f.data["jobs"][e["id"]]["priority"] == 77)
f.action(d["id"], "requeue")
check("requeue a failed job: errors cleared, new attempt", f.data["jobs"][d["id"]]["status"] == "queued" and not f.data["jobs"][d["id"]]["errors"])
f.action(e["id"], "cancel")
check("cancel", f.data["jobs"][e["id"]]["status"] == "cancelled")
f.action(e["id"], "delete")
check("delete", e["id"] not in f.data["jobs"])
try:
    f.submit({"render_job": "nope"}); ok = False
except AR.RenderError:
    ok = True
check("submitting an unknown render job is refused", ok)

# ---- pools, offline, disabled
LIVE.pop(MAC)
f.refresh_workers(force=True)
f.set_worker({"url": PC, "enabled": False})
g = f.submit({"render_job": ai_job("nowhere")})
check("offline and disabled workers get nothing", g["id"] not in [x for x, _ in f.tick()])
f.set_worker({"url": PC, "enabled": True, "pools": "gpu,hero"})
h = f.submit({"render_job": ai_job("pool"), "pool": "lookdev"})
check("a job in a pool no worker has waits", h["id"] not in [x for x, _ in f.tick()])
check("workers keep their pools", next(w for w in f.workers() if w["url"] == PC)["pools"] == ["gpu", "hero"])
st = f.status()
check("status: workers, jobs, stats, history", st["ok"] and st["stats"]["workers"] >= 1 and st["history"] and isinstance(st["jobs"], list))
check("ETA from the farm's own history", RF.eta({"workflow": "vace_render", "frames": 4}, [{"status": "completed", "secs": 80, "frames": 8, "workflow": "vace_render"}]) == 40)
check("the doctor knows a missing node and an offline worker",
      [x["cause"][:20] for x in RF.diagnose([{"msg": "missing node type WanVaceToVideo"}, {"msg": "connection refused"}])] ==
      ["The worker could not", "The worker's ComfyUI"])
code, body = RF.route(None, "POST", "/farm/worker", {"url": "ftp://x"})
check("a bad worker address is refused", code == 400 and not body["ok"])

# ---- AI speed-ups of a path-traced render (render less, AI does the rest)
import json as _json  # noqa: E402
import struct as _struct  # noqa: E402
import zlib as _zlib  # noqa: E402


def _png(w, h, rgb=(200, 10, 10)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def ch(k, d):
        return _struct.pack(">I", len(d)) + k + d + _struct.pack(">I", _zlib.crc32(k + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", _struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", _zlib.compress(raw)) + ch(b"IEND", b"")


src = AR.new_job(None, {"kind": "path", "name": "Turntable", "frames": 3, "fps": 12, "size": [64, 36]})["job"]
for i in range(3):
    AR.save_pass(None, src, "beauty", i, _png(64, 36, (i * 60, 0, 0)))
try:
    AR.post_job(None, src, "upscale", 2); ok = False
except AR.RenderError:
    ok = True
check("a speed-up waits for the render to finish", ok)
AR.finish(None, src, {"status": "succeeded"})
up = AR.post_job(None, src, "upscale", 2)
um = up["manifest"]
check("Upscale 2x: an AI job on ai_upscale with the render's frames as its beauty pass, 2x the size",
      um["workflow"] == "ai_upscale" and um["passes"]["beauty"]["frames"] == 3 and um["size"] == [128, 72] and um["params"]["scale_by"] == 0.5, um)
it = AR.post_job(None, src, "interpolate", 4)["manifest"]
check("In-betweens x4: RIFE multiplier 4, 4x the frame rate, (n-1)*4+1 frames",
      it["workflow"] == "ai_interpolate" and it["params"]["multiplier"] == 4 and it["fps"] == 48 and it["frames"] == 9, it)
for bad in (("upscale", 3), ("blur", 2)):
    try:
        AR.post_job(None, src, *bad); ok = False
    except AR.RenderError:
        ok = True
    check("refused: %s %s" % bad, ok)
FIX = _json.loads((REPO / "tests" / "fixtures" / "comfyui_object_info.json").read_text())["object_info"]
for name, params in (("ai_upscale", um["params"]), ("ai_interpolate", it["params"])):
    wf = AR.workflow(name)
    pr, probs = AR.build_prompt(wf, params, {"beauty": "loki/beauty.png"})
    check("%s: the graph with the job's values is valid against the node sources" % name, not probs and not AR.check_graph(pr, FIX), (probs, AR.check_graph(pr, FIX)))
old_rife = {k: v for k, v in FIX.items()}
old_rife["RIFE VFI"] = _json.loads(_json.dumps(FIX["RIFE VFI"]))
for k in ("dtype", "torch_compile", "batch_size"):
    old_rife["RIFE VFI"]["input"]["required"].pop(k)
pr, _ = AR.build_prompt(AR.workflow("ai_interpolate"), {}, {"beauty": "x"})
pr = AR.adapt(pr, AR.workflow("ai_interpolate"), old_rife)
check("an older RIFE pack (no dtype / torch_compile / batch_size): those inputs are dropped, the graph stays valid",
      "dtype" not in pr["2"]["inputs"] and not AR.check_graph(pr, old_rife))
check("Render Studio's own workflow list can tell the speed-ups apart (post)", AR.describe(AR.workflow("ai_upscale")).get("post") is True)
fs = RF.Farm(None, probe=probe, starter=starter)
RF._FARMS[str(AR.data_dir(None))] = fs
code, body = RF.route(None, "POST", "/farm/post", {"job": src, "op": "interpolate", "factor": 2})
check("/farm/post makes the speed-up job and queues it on the farm", code == 200 and body["job"]["status"] == "queued" and body["job"]["workflow"] == "ai_interpolate", body)

# ---- Carbon
os.environ["LOKI_CARBON_BUILD"] = str(TMP / "carbon" / "build")
s = CE.status()
check("Carbon: no build yet says so (Build)", s["ok"] and not s["found"] and "Build" in s["note"], s)
calls = []


class P:
    def __init__(self, argv, **kw):
        calls.append(argv)

    def poll(self):
        return None


r = CE.build(popen=P)
check("Carbon: Build runs native/carbon_mmo/tools/build.py into the build dir", r["ok"] and calls and calls[-1][1].endswith("build.py") and str(TMP / "carbon" / "build") in calls[-1], calls)
check("Carbon: a second Build while building is a no-op", CE.build(popen=P).get("already"))
exe = TMP / "carbon" / "build" / "bin" / CE.EXE
exe.parent.mkdir(parents=True, exist_ok=True); exe.write_text("x")
r = CE.open_editor(popen=P)
check("Carbon: Open starts the editor with its content folder", r["ok"] and calls[-1][0] == str(exe) and calls[-1][1] == "--content", calls[-1])
check("Carbon: routes", CE.route("GET", "/carbon/status")[0] == 200 and CE.route("GET", "/carbon/nope")[0] == 404)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
