"""Hunyuan3D 2.1 (owner-installed Forge backend), CC0 free assets, the training guard and Blender polish - offline,
every server faked (owner 2026-10-26: "lets add this ... blender toolkit ... more open resources for free").

    python tests/test_hunyuan_assets.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "tools"))
TMP = Path(tempfile.mkdtemp(prefix="loki-hy-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
for k in ("LOKI_HUNYUAN_ACCEPTED", "LOKI_HUNYUAN_MODE", "LOKI_HUNYUAN_URL"):
    os.environ.pop(k, None)
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


class Resp(io.BytesIO):
    def __init__(self, data, ctype="application/octet-stream"):
        super().__init__(data)
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


import forge_hunyuan as hy  # noqa: E402

# ------------------------------------------------------------------ licence gate
check("not accepted -> not ready, and says how (licence first)", not hy.ready() and "licence" in hy.why_not())
cut = TMP / "cut.png"
cut.write_bytes(b"\x89PNG fake")
try:
    hy.run(cut, TMP / "m")
    check("not accepted -> run refuses", False)
except hy.HunyuanError:
    check("not accepted -> run refuses", True)
import setup_hunyuan3d as setup  # noqa: E402
setup.main(["accept"])
env = (TMP / "data" / ".env").read_text()
check("setup accept records it in LOKI's .env (accepted + comfy route)", "LOKI_HUNYUAN_ACCEPTED=1" in env
      and "LOKI_HUNYUAN_MODE=comfy" in env and hy.accepted(), env)

# ------------------------------------------------------------------ the ComfyUI route (default)
wf = hy.workflow()
check("workflow: ComfyUI's official 2.1 template (native nodes)",
      [wf["api"][k]["class_type"] for k in ("1", "6", "7", "9", "10", "11")] ==
      ["ImageOnlyCheckpointLoader", "EmptyLatentHunyuan3Dv2", "KSampler", "VAEDecodeHunyuan3D", "VoxelToMesh", "SaveGLB"])
check("workflow: its checkpoint from Comfy-Org's repackaged repo, into checkpoints/",
      wf["models"][0]["folder"] == "checkpoints" and "Comfy-Org/hunyuan3D_2.1_repackaged" in wf["models"][0]["url"])
check("workflow names its licence (not open source)", "NOT open source" in wf["license"])
api = hy.build("loki/x.png", {"seed": 7, "steps": 40, "remesh": 384, "guidance": 4.0})
check("build: picture, seed, steps, cfg, octree resolution", api["2"]["inputs"]["image"] == "loki/x.png"
      and api["7"]["inputs"]["seed"] == 7 and api["7"]["inputs"]["steps"] == 40 and api["7"]["inputs"]["cfg"] == 4.0
      and api["9"]["inputs"]["octree_resolution"] == 384, api["7"]["inputs"])
check("options stay inside the server's limits", hy.options_for({"remesh": 9999, "triangles": 5})["octree_resolution"] <= 512
      and hy.options_for({"triangles": 5})["face_count"] == 1000)


class FakeComfy:
    def __init__(self, fail=""):
        self.fail, self.prompts = fail, []

    def upload_image(self, name, data, subfolder=""):
        return {"name": name, "subfolder": subfolder}

    def queue_prompt(self, prompt, client_id, pid):
        self.prompts.append(prompt)
        self.pid = pid
        return {}

    def history(self, pid):
        if self.fail:
            return {pid: {"status": {"status_str": "error", "messages": [["execution_error", {"node_type": "KSampler",
                                                                                         "exception_message": self.fail}]]}}}
        return {pid: {"status": {"completed": True, "status_str": "success"},
                      "outputs": {"11": {"3d": [{"filename": "hunyuan_00001_.glb", "subfolder": "loki", "type": "output"}]}}}}

    def view(self, filename, subfolder, kind):
        return b"glTF\x02\x00\x00\x00fake"


import forge_trellis  # noqa: E402
forge_trellis.comfy_url = lambda: "http://127.0.0.1:8188"
fc = FakeComfy()
r = hy.run_comfy(cut, TMP / "hy1", {"seed": 3}, cl=fc, sleep=lambda s: None)
check("comfy route: uploads the cut-out, queues the graph, saves the .glb", Path(r["glb"]).read_bytes().startswith(b"glTF")
      and fc.prompts[0]["2"]["inputs"]["image"].startswith("loki/loki-hunyuan-"), r)
check("comfy route: the result carries the licence and no_training", r["no_training"] is True and "Tencent" in r["licence"])
try:
    hy.run_comfy(cut, TMP / "hy2", cl=FakeComfy("CUDA out of memory"), sleep=lambda s: None)
    check("comfy out-of-memory: says what to do", False)
except hy.HunyuanError as exc:
    check("comfy out-of-memory: says what to do", "--lowvram" in str(exc), str(exc))

# ------------------------------------------------------------------ the server route
os.environ["LOKI_HUNYUAN_MODE"] = "server"
hy._READY.clear()
sent = {}


def server(req, timeout=0):
    u = req if isinstance(req, str) else req.full_url
    if u.endswith("/health"):
        return Resp(b'{"status": "healthy", "worker_id": "w"}')
    sent.update(json.loads(req.data))
    return Resp(b"glTF\x02\x00\x00\x00server", "model/gltf-binary")


r = hy.run(cut, TMP / "hy3", {"texture": True, "triangles": 30000}, opener=server)
check("server route: POST /generate with the picture (background already cut out) -> .glb",
      Path(r["glb"]).read_bytes().endswith(b"server") and sent["remove_background"] is False
      and base64.b64decode(sent["image"]) == cut.read_bytes() and sent["texture"] is True and sent["face_count"] == 30000, sent.keys())
try:
    hy.run(cut, TMP / "hy4", opener=lambda req, timeout=0: Resp(b'{"status": "healthy"}') if not hasattr(req, "data") or req.data is None
           else Resp(b'{"text": "NETWORK ERROR", "error_code": 1}', "application/json"))
    check("server route: a JSON error instead of a model is reported", False)
except hy.HunyuanError as exc:
    check("server route: a JSON error instead of a model is reported", "no model" in str(exc), str(exc))
check("server route: no server -> says how to start it", "start it" in hy.why_not(opener=lambda *a, **k: (_ for _ in ()).throw(OSError("refused"))))
os.environ["LOKI_HUNYUAN_MODE"] = "comfy"

# ------------------------------------------------------------------ Forge: the backend, and auto order
import forge3d  # noqa: E402
check("Forge knows the hunyuan backend", "hunyuan" in forge3d.BACKENDS)
forge3d.hunyuan_ready = lambda: True
forge3d.comfy_ready = lambda m: m in ("trellis2", "pixal3d")
check("auto never picks Tencent's Hunyuan, even installed (owner 2026-10-27) - TRELLIS.2 leads",
      "hunyuan" not in forge3d.plan("auto") and forge3d.plan("auto")[0] == "trellis2", forge3d.plan("auto"))
check("... but naming it still runs it", forge3d.plan("hunyuan")[0] == "hunyuan")
forge3d.hunyuan_ready = lambda: False
check("auto: without it nothing changes", forge3d.plan("auto")[0] == "trellis2")

# ------------------------------------------------------------------ the training guard (licence 5.b)
import experience  # noqa: E402
root = TMP / "exp"
experience.trajectories = lambda root=None: [
    {"id": "a", "goal": "make a chest", "messages": [{"role": "user", "content": "x"}], "tools": []},
    {"id": "b", "goal": "make a hunyuan model", "messages": [{"role": "tool", "content": json.dumps({"no_training": True})}], "tools": []}]
info = experience.build_dataset(TMP / "ds", {})
rows = (TMP / "ds" / "train.jsonl").read_text().splitlines()
check("training data skips work that carries no_training (Hunyuan output)", info["skipped_no_training"] == 1
      and len(rows) == 1 and '"id": "a"' in rows[0], info)

# ------------------------------------------------------------------ free assets (CC0)
import free_assets as fa  # noqa: E402
PH_LIST = {"wooden_barrels_01": {"name": "Wooden Barrels 01", "tags": ["barrel", "wood"], "categories": ["props"], "download_count": 5},
           "cannon_01": {"name": "Cannon 01", "tags": ["cannon", "barrel"], "categories": ["props"], "download_count": 9},
           "sofa_02": {"name": "Sofa 02", "tags": ["sofa"], "categories": ["furniture"], "download_count": 99}}
PH_FILES = {"gltf": {"1k": {"gltf": {"url": "https://dl.polyhaven.org/x/cannon_01_1k.gltf",
                                     "include": {"textures/cannon_diff_1k.jpg": {"url": "https://dl/x/d.jpg"},
                                                 "cannon_01.bin": {"url": "https://dl/x/c.bin"}}}}}}
calls = []


def ph(req, timeout=0):
    u = req.full_url
    calls.append((u, req.headers.get("User-agent")))
    if "/assets?" in u:
        return Resp(json.dumps(PH_LIST).encode())
    if "/files/" in u:
        return Resp(json.dumps(PH_FILES).encode())
    return Resp(b"data:" + u.encode())


rs = fa.search("polyhaven", "wood barrel", "models", opener=ph)
check("polyhaven search: best match first, CC0", [x["id"] for x in rs][:2] == ["wooden_barrels_01", "cannon_01"]
      and all(x["licence"] == "CC0-1.0" for x in rs), rs)
check("polyhaven: LOKI's own User-Agent (the API asks for one)", calls[0][1].startswith("LOKI/"))
d = fa.download("polyhaven", "cannon_01", TMP / "ws", opener=ph)
side = json.loads((TMP / "ws" / "assets" / "polyhaven" / "cannon_01" / "loki_asset.json").read_text())
check("polyhaven model: .gltf + its .bin + textures (in their sub-folder), sidecar with licence + credit",
      d["main"].endswith("cannon_01_1k.gltf") and len(d["files"]) == 3
      and (TMP / "ws/assets/polyhaven/cannon_01/textures/cannon_diff_1k.jpg").is_file()
      and side["licence"] == "CC0-1.0" and "Powered by Poly Haven" in side["credit"], (d, side))
evil = {"gltf": {"1k": {"gltf": {"url": "https://x/a.gltf", "include": {"../../escape.txt": {"url": "https://x/e"}}}}}}
try:
    fa.download("polyhaven", "evil_01", TMP / "ws", opener=lambda req, timeout=0: Resp(json.dumps(evil).encode()) if "/files/" in req.full_url else Resp(b"x"))
    check("a file path escaping the asset folder is refused", False)
except fa.AssetError:
    check("a file path escaping the asset folder is refused", True)
check("bad ids are refused", "bad asset id" in fa.tool({"action": "download", "source": "polyhaven", "id": "../x"}, TMP)["error"])

zbuf = io.BytesIO()
with zipfile.ZipFile(zbuf, "w") as z:
    z.writestr("WoodFloor064_1K-JPG_Color.jpg", b"c")
    z.writestr("WoodFloor064_1K-JPG_NormalGL.jpg", b"n")
ACG = {"foundAssets": [{"assetId": "WoodFloor064", "displayName": "Wood Floor 064", "dataType": "Material", "tags": ["wood"],
                        "downloadFolders": {"default": {"downloadFiletypeCategories": {"zip": {"downloads": [
                            {"attribute": "2K-JPG", "downloadLink": "https://acg/2k.zip"},
                            {"attribute": "1K-JPG", "downloadLink": "https://acg/1k.zip"}]}}}}}]}
got = []


def acg(req, timeout=0):
    got.append(req.full_url)
    return Resp(zbuf.getvalue()) if req.full_url.endswith(".zip") else Resp(json.dumps(ACG).encode())


check("ambientcg search", fa.search("ambientcg", "wood", "Material", opener=acg)[0]["id"] == "WoodFloor064")
d = fa.download("ambientcg", "WoodFloor064", TMP / "ws", "1k", opener=acg)
check("ambientcg: the 1K-JPG zip, unpacked, colour map as main", got[-1] == "https://acg/1k.zip" and d["main"].endswith("_Color.jpg")
      and len(d["files"]) == 2, d)
check("kits: Kenney, Quaternius, KayKit (CC0, no API)", {k["name"] for k in fa.tool({"action": "kits"}, TMP)["kits"]} ==
      {"Kenney", "Quaternius", "KayKit"})
import make_mcp  # noqa: E402
names = {t["name"] for t in make_mcp.TOOLS}
check("LOKI's agents have free_assets and blender", {"free_assets", "blender"} <= names)

# ------------------------------------------------------------------ Blender polish: the command chain
import blender_link  # noqa: E402
seen = {}
blender_link.run = lambda cmds, name="", **kw: seen.update(cmds=cmds) or {"ok": True}
model = TMP / "ws" / "models" / "20261026-125900-a-detailed-character.glb"
model.parent.mkdir(parents=True, exist_ok=True)
model.write_bytes(b"glTF")
res = blender_link.polish(model, TMP / "ws", target=15000, turntable=0)
kinds = [c["type"] for c in seen["cmds"]]
check("polish: clear -> import -> cleanup -> normalize -> repair -> bake -> decimate -> uv(missing) -> topology -> shade -> "
      "stage -> render -> export .glb .gltf .fbx .blend -> lods -> scene_info", kinds == ["clear", "import", "cleanup", "normalize",
                                                               "repair", "bake", "decimate", "uv", "topology", "shade", "stage", "render", "export",
                                                               "export", "export", "export", "lods", "scene_info"]
      and seen["cmds"][7]["params"]["mode"] == "missing" and seen["cmds"][6]["params"]["target"] == 15000
      and [Path(c["params"]["path"]).suffix for c in seen["cmds"] if c["type"] == "export"] == [".glb", ".gltf", ".fbx", ".blend"], kinds)
check("polish: all in one LOKI scene, files named by out_names", len({c["params"].get("scene") for c in seen["cmds"]}) == 1
      and seen["cmds"][0]["params"]["scene"].startswith("LOKI ") and Path(res["files"]["render"]).name.startswith("character-polished_"),
      (seen["cmds"][0]["params"], res["files"]))
check("polish via the agents' tool: a missing model says so",
      "no model" in blender_link.tool({"action": "polish", "path": "models/nope.glb"}, TMP / "ws")["error"])

check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
