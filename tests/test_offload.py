"""The Mac gives heavy work to the PC (owner 2026-10-26: "why cant i send work to my pc from here most of these jobs
should be done there the mac isnt the power house ... it needs to give windows work without pushing git").

engine/offload.py over a REAL signed peer server on loopback (engine/peers.py): who works (light / main), what a
linked machine says it can take, chunked files both ways with their checksums, a failed job's reason, an older LOKI,
the serving side's whitelists (names, paths, settings), and the four places that use it - area edits, pictures, 3D
models, Blender clean-ups. No GPU, no Blender: the runners are fakes.

    python tests/test_offload.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-offload-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PEER_SECRET"] = "s" * 40
os.environ["LOKI_PEER_NAME"] = "mac"
os.environ.pop("LOKI_PEERS", None)
os.environ["LOKI_COMFY_AUTOSTART"] = "0"
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import offload  # noqa: E402
import peers  # noqa: E402

# ------------------------------------------------------------------ who works
check("a Mac is a light machine (gives heavy work away)", offload.role({}, {"os": "darwin", "apple_silicon": True}) == "light")
check("the PC with its NVIDIA card is the main one", offload.role({}, {"os": "win32", "nvidia": True}) == "main")
check("LOKI_MACHINE_ROLE overrides", offload.role({"LOKI_MACHINE_ROLE": "main"}, {"os": "darwin"}) == "main")

# ------------------------------------------------------------------ a real peer server playing the PC
SEEN = {}


def fake_image(params, inputs, out, rec):
    SEEN["params"], SEEN["inputs"] = dict(params), {k: Path(v).read_bytes() for k, v in inputs.items()}
    (out / "renders").mkdir()
    (out / "renders" / "pic.png").write_bytes(b"P" * 5_000_000 + b"end")       # two chunks back
    (out / ".meta").mkdir()
    (out / ".meta" / "x.json").write_text("{}")                                 # never sent back
    return {"backend": "sdcpp", "file": str(out / "renders" / "pic.png"), "elsewhere": "C:\\Users\\macul\\x.png"}


def fake_fail(params, inputs, out, rec):
    raise RuntimeError("sd.cpp ran out of VRAM")


offload.serves = lambda env=None: (["image", "img2img", "make_3d", "polish"], {})
offload.RUNNERS = {"image": fake_image, "img2img": fake_image, "make_3d": fake_image, "polish": fake_image}
HELLO = {"name": "pc", "work": ["image", "img2img", "make_3d", "polish"]}
server = peers.PeerServer({"hello": lambda: HELLO, "work": lambda origin, data: offload.serve(origin, data)},
                          host="127.0.0.1", port_number=0).start()
PC = {"name": "pc", "url": "http://127.0.0.1:%d" % server.address[1]}
offload._HELLO.clear()
mac_env = {"LOKI_PEERS": "pc=%s" % PC["url"], "LOKI_PEER_SECRET": "s" * 40}
mac = {"os": "darwin", "apple_silicon": True}
check("the Mac gives pictures to the PC when the PC says it can take them",
      (offload.target("image", mac_env, info=mac) or {}).get("name") == "pc")
check("... the PC itself never gives its work away", offload.target("image", {**mac_env}, info={"os": "win32", "nvidia": True}) is None)
check("... LOKI_OFFLOAD=off keeps everything here", offload.target("image", {**mac_env, "LOKI_OFFLOAD": "off"}, info=mac) is None)

big = TMP / "init.png"
big.write_bytes(os.urandom(9_000_000))                                     # three chunks up
dest = TMP / "dest"
got = offload.run("image", {"prompt": "a red dragon", "width": 512, "run": "rm -rf /"}, {"init.png": big}, dest,
                  peer=PC, sleep=lambda s: None)
check("files go up in chunks and arrive whole", SEEN["inputs"].get("init.png") == big.read_bytes(),
      len(SEEN["inputs"].get("init.png", b"")))
check("only the kind's own settings reach the PC (a 'run' keyword is dropped)",
      SEEN["params"] == {"prompt": "a red dragon", "width": 512}, SEEN["params"])
back = dest / "renders" / "pic.png"
check("results come back into their folders, checked by sha256", got["files"] == [str(back)] and back.read_bytes().endswith(b"end")
      and back.stat().st_size == 5_000_003, got["files"])
check("... sidecars of the PC (.meta) stay there", not (dest / ".meta").exists())
check("... the PC's own paths become relative or just a name", got["result"].get("file") == "renders/pic.png"
      and got["result"].get("elsewhere") == "x.png" or got["result"].get("elsewhere", "").endswith("x.png"), got["result"])
check("... and the PC cleans the job up after the Mac took it", not any((TMP / "data" / "offload").iterdir()))

offload.RUNNERS["img2img"] = fake_fail
try:
    offload.run("img2img", {"prompt": "x"}, {"init.png": big}, dest, peer=PC, sleep=lambda s: None)
    check("a failed job raises with the PC's reason", False)
except offload.OffloadError as exc:
    check("a failed job raises with the PC's reason", "out of VRAM" in str(exc), str(exc))

# ------------------------------------------------------------------ the serving side's whitelists
code, r = offload.serve("mac", {"op": "put", "id": "abc", "name": "../../evil.py", "offset": 0, "data": "aGk="})
check("an upload name with ../ stays a plain name inside the job's in folder",
      code == 200 and (TMP / "data" / "offload" / "abc" / "in" / "evil.py").is_file()
      and not (TMP / "evil.py").exists() and not (TMP / "data" / "evil.py").exists(), (code, r))
code, r = offload.serve("mac", {"op": "put", "id": "abc", "name": "sub/x.png", "offset": 0, "data": "aGk="})
check("... and a folder in an upload name is refused", code == 400, (code, r))
code, r = offload.serve("mac", {"op": "put", "id": "abc", "name": "ok.png", "offset": 0, "data": "aGk="})
code, r = offload.serve("mac", {"op": "start", "id": "abc", "kind": "shell", "params": {}})
check("an unknown kind of work is refused", code == 400 and "unknown kind" in r["error"], r)
offload.JOBS["abc"] = {"id": "abc", "status": "done"}
code, r = offload.serve("mac", {"op": "get", "id": "abc", "path": "../in/ok.png"})
check("results are read only from the job's out folder", code == 404, (code, r))
real = offload.serves
offload.serves = lambda env=None: ([], {"polish": "Blender is not installed here"})
offload.JOBS.pop("abc", None)
code, r = offload.serve("mac", {"op": "start", "id": "abd", "kind": "polish", "params": {}})
check("a kind this machine cannot run is refused with why", code == 409 and "Blender is not installed" in r["error"], r)
offload.serves = real

# ------------------------------------------------------------------ an older LOKI on the PC
asked = []


def old_pc(peer, method, path, payload=None, timeout=0):
    if path == "/peer/hello":
        return {"name": "pc"}                 # no "work": an older LOKI
    if path == "/peer/update/apply":
        asked.append(path)
        return {"ok": True}
    raise peers.PeerError("pc answered HTTP 404: unknown peer endpoint")


offload._HELLO.clear()
offload._ASKED_UPDATE.clear()
check("an older LOKI on the PC takes no work ...", offload.target("image", mac_env, call=old_pc, info=mac) is None)
time.sleep(0.2)
check("... and is asked (once an hour) to update itself", asked == ["/peer/update/apply"], asked)
check("... the reason says so", "older LOKI" in offload.why_not("image", mac_env, call=old_pc), offload.why_not("image", mac_env, call=old_pc))

# ------------------------------------------------------------------ the four places that use it
import region_edit  # noqa: E402

init, mask, out = TMP / "i.png", TMP / "m.png", TMP / "o.png"
init.write_bytes(b"i"); mask.write_bytes(b"m")


def send_edit(kind, params, inputs, d, peer=None, **kw):
    (Path(d) / "out.png").write_bytes(b"EDITED")
    return {"peer": "pc", "files": [str(Path(d) / "out.png")], "result": {}}


region_edit.model_step(init, mask, "a gold crown", 512, 512, 0.7, 5, out, target=lambda k: PC, send=send_edit)
check("an area edit on the Mac is made on the PC", out.read_bytes() == b"EDITED")
os.environ["LOKI_MACHINE_ROLE"] = "light"
try:
    region_edit.model_step(init, mask, "x", 512, 512, 0.7, 5, out, target=lambda k: None)
    check("no PC and no model here: the edit says the PC is where it runs (not 'install mflux')", False)
except region_edit.EditError as exc:
    check("no PC and no model here: the edit says the PC is where it runs (not 'install mflux')",
          "run on your PC" in str(exc) and "Add-ons" not in str(exc), str(exc))

import creative  # noqa: E402

real_target, real_run = offload.target, offload.run


def fake_run(kind, params, inputs, d, peer=None, **kw):
    for i in range(int(params.get("count") or 1)):
        (Path(d) / ("pc_%d.png" % i)).write_bytes(b"pic%d" % i)
    return {"peer": "pc", "files": sorted(str(p) for p in Path(d).iterdir()), "result": {"backend": "sdcpp", "seeds": [7, 8]},
            "seconds": 3.0}


offload.target, offload.run = (lambda kind, *a, **k: PC), fake_run
res = creative.run_local_image("red dragon", "", 512, 512, 7, 2, TMP / "imgs")
check("pictures asked for on the Mac are made on the PC and saved here under LOKI's names",
      len(res["files"]) == 2 and all(Path(f).parent == TMP / "imgs" and Path(f).is_file() for f in res["files"])
      and res["backend"] == "pc:sdcpp" and "red-dragon" in Path(res["file"]).name, res)

import forge3d  # noqa: E402
from PIL import Image  # noqa: E402

pic = TMP / "golem.png"
Image.new("RGB", (64, 64), "white").save(pic)
im = Image.open(pic)
im.paste((120, 60, 40), (20, 10, 44, 54))
im.save(pic)
started = []
import comfy_autostart  # noqa: E402
comfy_autostart.ensure = lambda *a, **k: started.append(1) or {"ok": False}


def fake_3d(kind, params, inputs, d, peer=None, **kw):
    SEEN["3d"] = (kind, params.get("backend"))
    import struct
    js = json.dumps({"asset": {"version": "2.0"}}).encode() + b"  "
    glb = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js)) + struct.pack("<II", len(js), 0x4E4F534A) + js
    (Path(d) / "golem.glb").write_bytes(glb)
    return {"peer": "pc", "files": [str(Path(d) / "golem.glb")], "result": {"backend": "pixal3d", "meta": {}}, "seconds": 40}


offload.run = fake_3d
real_read = forge3d.read_glb
forge3d.read_glb = lambda p: ([], [])
forge3d.glb_counts = lambda p: {"triangles": 50000}
res = forge3d.make_3d(str(pic), TMP / "models", prompt="stone golem", backend="pixal3d")
check("a 3D model asked for on the Mac is made on the PC (and ComfyUI is not started on the Mac)",
      res.get("ok") and res["backend"] == "pc:pixal3d" and SEEN["3d"] == ("make_3d", "pixal3d") and not started
      and Path(res["glb"]).parent == TMP / "models", res)

import blender_link  # noqa: E402

model = TMP / "ws" / "models" / "golem_1.glb"
model.parent.mkdir(parents=True)
model.write_bytes(b"glTF")


def fake_polish(kind, params, inputs, d, peer=None, **kw):
    SEEN["polish"] = params
    files = {"renders/golem_polished.png": b"png", "models/golem_polished.glb": b"glb", "models/golem_polished.fbx": b"fbx"}
    for rel, data in files.items():
        (Path(d) / rel).parent.mkdir(parents=True, exist_ok=True)
        (Path(d) / rel).write_bytes(data)
    return {"peer": "pc", "files": [str(Path(d) / r) for r in files], "rel": list(files), "seconds": 90,
            "result": {"files": {"render": "renders/golem_polished.png",
                                 "models": ["models/golem_polished.glb", "models/golem_polished.fbx"]},
                       "topology": {"verdict": "quads"}, "info": {"triangles": 14000}}}


offload.run = fake_polish
called = []
blender_link.run = lambda *a, **k: called.append(1) or {"ok": False}
res = blender_link.polish(model, TMP / "ws", retopo=8000, formats=("glb", "fbx"))
side = json.loads((TMP / "ws" / "models" / ".meta" / "golem_polished.glb.json").read_text())
check("a Blender clean-up asked for on the Mac runs on the PC (not in the Mac's Blender)",
      res.get("ok") and not called and res["machine"] == "pc" and SEEN["polish"]["retopo"] == 8000
      and res["files"]["models"][0].endswith("golem_polished.glb"), res)
check("... and Forge / Home get their sidecar here, saying where it was made",
      side.get("made_on") == "pc" and side.get("image") == "renders/golem_polished.png" and side.get("triangles") == 14000, side)
offload.target, offload.run = real_target, real_run

# ------------------------------------------------------------------ pictures: the PC after the hosted models the owner liked
from runners import imagegen  # noqa: E402

imagegen._pc_for_pictures = lambda: "pc"
imagegen._light = lambda: True
imagegen.zimage_status = lambda: (True, "")
imagegen.local_status = lambda: ("mflux", False, "mflux is not installed")
os.environ["NVIDIA_API_KEY"] = "x"
plan = imagegen.plan_order("auto")
check("picture order on the Mac: hosted first, then the PC; never a big local torch model",
      plan["order"][-1] == "local" and "zimage" not in plan["order"] and plan["order"].index("nvidia") < plan["order"].index("local")
      and plan.get("pc") == "pc", plan)

import importlib  # noqa: E402
ca = importlib.reload(comfy_autostart)
os.environ["LOKI_COMFY_AUTOSTART"] = "1"
os.environ["LOKI_MACHINE_ROLE"] = "light"


def refused(url, timeout=0):
    raise OSError("refused")


(ca.comfy_root() / "ComfyUI").mkdir(parents=True, exist_ok=True)
(ca.comfy_root() / "ComfyUI" / "main.py").write_text("# installed")
r = ca.ensure("http://127.0.0.1:8188", opener=refused)
check("the Mac never starts its own ComfyUI for 3D (the PC does 3D) - unless forced",
      not r["ok"] and not r["started"] and "PC" in r["why"], r)
os.environ["LOKI_COMFY_AUTOSTART"] = "0"
server.stop()
check("peer hello lists the work a machine takes (engine/peer_link.py)",
      '"work": work' in (REPO / "engine" / "peer_link.py").read_text(encoding="utf-8"))
check("/peer/work is a peer endpoint", '"/peer/work"' in (REPO / "engine" / "peers.py").read_text(encoding="utf-8"))
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
