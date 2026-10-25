"""Forge's Pixal3D / TRELLIS.2 backends (engine/forge_trellis.py, engine/comfy_workflow.py), offline, under a minute.

A fake ComfyUI (a real HTTP server on 127.0.0.1) serves /object_info from a fixture written from ComfyUI's node sources
(tests/fixtures/comfy_trellis_object_info.json), takes the upload and the prompt, checks the graph it gets the way
ComfyUI would (known classes, every link to a real output, every required input there, loaders naming files it lists),
and "finishes" with a .glb. Checked: the UI -> API converter (widget counts, seeds' extra slot, upload slot, dynamic
combos), the vendored graph equals a fresh conversion of Comfy Org's template, switches resolve per mode and the unused
branch is pruned, missing models / too-old ComfyUI are reported, a whole Forge run picks Pixal3D and saves the model,
the installer downloads into models/<folder>/ and resumes a cut download, and the Forge window has the controls.

    python tests/test_forge_trellis.py
"""
from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-trellis-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_TRIPOSR_DIR"] = str(TMP / "no-triposr")
os.environ["LOKI_FORGE_ONLINE"] = "0"
os.environ["LOKI_FORGE_JUDGE"] = "0"
os.environ["LOKI_COMFY_DIR"] = str(TMP / "nowhere")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import comfy_workflow as cw  # noqa: E402
import forge3d  # noqa: E402
import forge_trellis as ft  # noqa: E402

INFO = json.loads((REPO / "tests" / "fixtures" / "comfy_trellis_object_info.json").read_text())
UI = json.loads((REPO / "engine" / "forge_workflows" / "ui" / "3d_pixal3d_trellis2_image_to_model.json").read_text())
WF = ft.workflow()

# ------------------------------------------------------------------ the converter
api = cw.ui_to_api(UI, INFO)
check("the whole template converts: every node's widget values match its inputs", len(api) > 50, len(api))
check("a KSampler's seed slot ('fixed') is skipped", api["12"]["inputs"]["seed"] == 43 and api["12"]["inputs"]["steps"] == 12
      and api["12"]["inputs"]["sampler_name"] == "euler", api["12"]["inputs"])
check("LoadImage's upload slot is skipped", api["122"]["inputs"] == {"image": "viking_wolf_rune_axe.png"}, api["122"])
check("a dynamic combo sends its option's widgets as name.sub", api["241"]["inputs"].get("sign_mode") == "solid"
      and api["241"]["inputs"].get("sign_mode.fill") == 20 and api["241"]["inputs"].get("band") == 1, api["241"]["inputs"])
check("a linked widget sends the link", api["196"]["inputs"]["resolution"] == ["288", 0], api["196"]["inputs"])
bad = copy.deepcopy(UI)
next(n for n in bad["nodes"] if n["id"] == 3)["widgets_values"].append(99)
try:
    cw.ui_to_api(bad, INFO)
    check("a node with too many widget values is an error, never a guess", False)
except cw.WorkflowError as exc:
    check("a node with too many widget values is an error, never a guess", "node 3" in str(exc), exc)
sys.path.insert(0, str(REPO / "tools"))
import build_forge_workflows as bfw  # noqa: E402
fresh = bfw.single(INFO)
check("the vendored graph is exactly a fresh conversion of the template (+ SaveGLB)", fresh == WF["api"],
      sorted(set(fresh) ^ set(WF["api"])))
VWF = ft.workflow("pixal3d-views")
check("the 4-view graph too (its fixed-pixel crops swapped for one LoadImage per view)", bfw.views(INFO) == VWF["api"]
      and all(VWF["api"][nid]["class_type"] == "LoadImage" for nid in VWF["nodes"]["views"].values()))
check("the template and its MIT licence are vendored", (REPO / "engine" / "licenses" / "comfy-workflow-templates-MIT.txt").is_file())


# ------------------------------------------------------------------ build per mode
def links_ok(graph):
    probs = []
    for nid, node in graph.items():
        cls = node["class_type"]
        spec = INFO[cls]["input"]
        for k in spec.get("required") or {}:
            if k not in node["inputs"] and not (isinstance(spec["required"][k][0], str)
                                                and spec["required"][k][0] == "COMFY_DYNAMICCOMBO_V3" and k in node["inputs"]):
                probs.append("%s.%s missing" % (nid, k))
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                src = graph.get(v[0])
                if src is None:
                    probs.append("%s.%s -> missing %s" % (nid, k, v[0]))
                elif v[1] >= max(1, len(INFO[src["class_type"]]["output"])):
                    probs.append("%s.%s -> %s slot %s" % (nid, k, v[0], v[1]))
    return probs


pix = ft.build("pixal3d", "loki/in.png", {"seed": 7, "texture_size": 2048, "faces": 50000, "detail": 512})
tre = ft.build("trellis2", "loki/in.png")
check("Pixal3D: no switch nodes left, its own model and MoGe in, TRELLIS.2's model out",
      not any(n["class_type"] == "ComfySwitchNode" for n in pix.values()) and "319" in pix and "55" in pix and "40" not in pix,
      sorted(pix, key=int))
check("TRELLIS.2: its model in, Pixal3D's model and MoGe out", "40" in tre and "319" not in tre and "55" not in tre,
      sorted(tre, key=int))
check("both graphs are whole (every link to a real output, every required input there)",
      not links_ok(pix) and not links_ok(tre), links_ok(pix) + links_ok(tre))
check("options reach the graph (picture, seeds, texture, triangles, detail)",
      pix["122"]["inputs"]["image"] == "loki/in.png" and pix["3"]["inputs"]["seed"] == 7 and pix["12"]["inputs"]["seed"] == 8
      and pix["288"]["inputs"]["value"] == 2048 and pix["186"]["inputs"]["target_face_count"] == 50000
      and pix["241"]["inputs"]["resolution"] == 512)
check("the background is removed by BiRefNet (the switch picked its mask)", pix["312"]["inputs"]["masks"] == ["303", 0]
      and pix["303"]["inputs"]["mask"] == ["192", 0], (pix["312"]["inputs"], pix.get("303")))
vw = ft.build("pixal3d-views", {"front": "f.png", "left": "l.png", "back": "b.png", "right": "r.png"}, {"faces": 30000})
check("the 4-view graph is whole, each view its own picture, one multi-view model",
      not links_ok(vw) and {vw[n]["inputs"]["image"] for n in VWF["nodes"]["views"].values()} == {"f.png", "l.png", "b.png", "r.png"}
      and {f[3] for f in cw.loaders(vw) if f[1] == "UNETLoader"} == {"pixal3d_multiview_int8_convrot.safetensors"}
      and vw["186"]["inputs"]["target_face_count"] == 30000, links_ok(vw))
need_p = {f[3] for f in cw.loaders(pix)}
check("Pixal3D needs exactly its 6 model files", need_p == {m["file"] for m in ft.models_for("pixal3d")}
      and len(need_p) == 6, need_p)
need_t = {f[3] for f in cw.loaders(tre)}
check("TRELLIS.2 needs 5 (no Pixal3D model, no MoGe)", need_t == {m["file"] for m in ft.models_for("trellis2")}
      and len(need_t) == 5, need_t)
check("every model has a Hugging Face URL in the folder its loader reads",
      all(m["url"].startswith("https://huggingface.co/Comfy-Org/") and m["url"].endswith("/" + m["folder"] + "/" + m["file"])
          for m in WF["models"]))

# ------------------------------------------------------------------ a fake ComfyUI
GLB = io.BytesIO()
mesh = {"positions": [(0, 0, 0), (1, 0, 0), (0, 1, 0)], "normals": [(0, 0, 1)] * 3, "colors": [(1, 1, 1)] * 3,
        "indices": [0, 1, 2]}
forge3d.write_glb(TMP / "fake.glb", mesh)
GLB_BYTES = (TMP / "fake.glb").read_bytes()
STATE = {"info": copy.deepcopy(INFO), "prompts": [], "uploads": [], "problems": []}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/object_info":
            return self._send(STATE["info"])
        if self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[1]
            if not STATE["prompts"] or STATE["prompts"][-1][0] != pid:
                return self._send({})
            return self._send({pid: {"status": {"status_str": "success", "completed": True, "messages": []},
                                     "outputs": {"322": {"3d": [{"filename": "forge_00001_.glb", "subfolder": "loki",
                                                                 "type": "output"}]}}}})
        if self.path.startswith("/view?"):
            return self._send(None, raw=GLB_BYTES)
        if self.path == "/system_stats":
            return self._send({"system": {}})
        return self._send({"error": "no"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if self.path == "/upload/image":
            STATE["uploads"].append(len(body))
            return self._send({"name": "loki-up.png", "subfolder": "loki", "type": "input"})
        if self.path == "/prompt":
            got = json.loads(body)
            graph = got["prompt"]
            probs = links_ok(graph) + ["unknown " + c for c in cw.missing_nodes(graph, STATE["info"])]
            probs += ["model " + m["file"] for m in cw.check_models(graph, STATE["info"])]
            STATE["problems"] = probs
            STATE["prompts"].append((got["prompt_id"], graph))
            if probs:
                return self._send({"error": {"message": "bad graph"}, "node_errors": {"x": {"errors": probs}}}, 400)
            return self._send({"prompt_id": got["prompt_id"], "number": 1, "node_errors": {}})
        return self._send({"error": "no"}, 404)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["LOKI_COMFYUI_URL"] = "http://127.0.0.1:%d" % srv.server_address[1]
ft.forget_cache()

st = ft.status()
check("status: reachable, new enough, both modes ready", st["reachable"] and st["nodes_ok"]
      and st["modes"]["pixal3d"]["ready"] and st["modes"]["trellis2"]["ready"], st)
check("the 4-view sheet mode is ready too", st["modes"]["pixal3d-views"]["ready"], st["modes"].get("pixal3d-views"))
check("Forge's best-available order starts with Pixal3D (one ComfyUI mode, then the rest)",
      forge3d.plan("auto")[:1] == ["pixal3d"] and "trellis2" not in forge3d.plan("auto"), forge3d.plan("auto"))

from PIL import Image, ImageDraw  # noqa: E402
pic = TMP / "axe.png"
im = Image.new("RGB", (256, 256), (250, 250, 250))
ImageDraw.Draw(im).rectangle((100, 40, 150, 220), fill=(120, 80, 40))
im.save(pic)
out = forge3d.make_3d(str(pic), TMP / "ws" / "models", prompt="axe", backend="auto", options={"faces": 40000})
check("a whole Forge run on ComfyUI: Pixal3D made it, the .glb is saved and valid",
      out.get("ok") and out["backend"] == "pixal3d" and Path(out["glb"]).read_bytes() == GLB_BYTES, out)
check("the picture was uploaded and the graph ComfyUI got was whole", STATE["uploads"] and not STATE["problems"],
      STATE["problems"])
sent = STATE["prompts"][-1][1]
check("the queued graph uses the uploaded picture and Forge's triangle count",
      sent["122"]["inputs"]["image"] == "loki/loki-up.png" and sent["186"]["inputs"]["target_face_count"] == 40000)
check("the model's note says who made it", "Pixal3D" in (out.get("meta") or {}).get("note", ""), out.get("meta"))
sheet = TMP / "sheet.png"
im = Image.new("RGB", (800, 200), (250, 250, 250))
for i, c in enumerate([(200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 0)]):
    ImageDraw.Draw(im).rectangle((i * 200 + 70, 30, i * 200 + 130, 180), fill=c)
im.save(sheet)
parts = ft.split_sheet(sheet)
first = Image.open(io.BytesIO(parts["front"])).convert("RGB")
check("a sheet splits into front, left, back, right (four equal columns, left to right)",
      list(parts) == ["front", "left", "back", "right"] and first.size == (200, 200) and first.getpixel((100, 100)) == (200, 0, 0)
      and Image.open(io.BytesIO(parts["right"])).convert("RGB").getpixel((100, 100)) == (200, 200, 0))
before = len(STATE["uploads"])
out = forge3d.make_3d(str(sheet), TMP / "ws" / "models", prompt="hero", backend="pixal3d", options={"views": True})
sent = STATE["prompts"][-1][1]
check("Forge's 4-view sheet option: four pictures uploaded, the multi-view graph queued, the model saved",
      out.get("ok") and len(STATE["uploads"]) - before == 4 and any(n["class_type"] == "Pixal3DMultiViewConditioning"
                                                                    for n in sent.values()) and not STATE["problems"],
      (out, STATE["problems"]))
try:
    ft.split_sheet(pic)
    check("a square picture is not a sheet (said plainly)", False)
except ft.TrellisError as exc:
    check("a square picture is not a sheet (said plainly)", "four views" in str(exc), exc)

# models missing -> not ready, the reason names the files, auto falls back
STATE["info"]["UNETLoader"]["input"]["required"]["unet_name"] = [["trellis_2_int8_convrot.safetensors"]]
ft.forget_cache()
st = ft.status()
check("a missing Pixal3D model: Pixal3D not ready (named), TRELLIS.2 still ready",
      not st["modes"]["pixal3d"]["ready"] and st["modes"]["pixal3d"]["missing"] == ["pixal3d_int8_convrot.safetensors"]
      and st["modes"]["trellis2"]["ready"], st["modes"])
check("then auto uses TRELLIS.2", forge3d.plan("auto")[:1] == ["trellis2"], forge3d.plan("auto"))
try:
    ft.run(pic, TMP / "x", "pixal3d")
    check("running Pixal3D without its model says which file is missing", False)
except ft.TrellisError as exc:
    check("running Pixal3D without its model says which file is missing", "pixal3d_int8_convrot" in str(exc), exc)
del STATE["info"]["Trellis2ShapeStage"]
ft.forget_cache()
st = ft.status()
check("an old ComfyUI (no TRELLIS.2 nodes): not ready, 'update it'", not st["nodes_ok"] and "Update" in st.get("error", "")
      and not any(m["ready"] for m in st["modes"].values()), st.get("error"))
STATE["info"] = copy.deepcopy(INFO)
srv.shutdown()
srv.server_close()
ft.forget_cache()
st = ft.status()
check("ComfyUI off: not reachable, and Forge falls back without it", not st["reachable"]
      and forge3d.plan("auto") == ["lift"], (st.get("error"), forge3d.plan("auto")))

# ------------------------------------------------------------------ installing the models
comfy = TMP / "ComfyUI"
(comfy / "models").mkdir(parents=True)
(comfy / "models" / "vae").mkdir()
(comfy / "models" / "vae" / "trellis_2_shape_vae_bf16.safetensors").write_bytes(b"done")
part = comfy / "models" / "clip_vision" / "dino_v3_L_naf_fp32.safetensors.part"
part.parent.mkdir()
part.write_bytes(b"ABC")
asked = []


class Resp:
    def __init__(self, data, code=200):
        self._b = io.BytesIO(data)
        self.status = code
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(req, timeout=0):
    asked.append((req.full_url, req.headers.get("Range")))
    if req.headers.get("Range"):
        return Resp(b"DEF", 206)
    return Resp(b"weights-" + req.full_url.rsplit("/", 1)[1].encode())


res = ft.install(mode="trellis2", comfy_dir=str(comfy), opener=opener)
check("install downloads what TRELLIS.2 needs into models/<folder>/ (skipping what is there)",
      res["ok"] and "trellis_2_shape_vae_bf16.safetensors" in res["already"]
      and (comfy / "models" / "diffusion_models" / "trellis_2_int8_convrot.safetensors").read_bytes().startswith(b"weights-")
      and (comfy / "models" / "background_removal" / "birefnet.safetensors").is_file()
      and not (comfy / "models" / "diffusion_models" / "pixal3d_int8_convrot.safetensors").exists(), res)
check("a cut download resumes from its .part (Range)",
      (comfy / "models" / "clip_vision" / "dino_v3_L_naf_fp32.safetensors").read_bytes() == b"ABCDEF"
      and any(r == "bytes=3-" for _, r in asked) and not part.exists())
try:
    ft.install(comfy_dir=str(TMP / "not-comfy"), opener=opener)
    check("install with no ComfyUI here says where to do it instead", False)
except ft.TrellisError as exc:
    check("install with no ComfyUI here says where to do it instead", "computer ComfyUI runs on" in str(exc), exc)

# ------------------------------------------------------------------ the window, the API, the tools
js = (REPO / "app" / "ui" / "forge.js").read_text()
check("Forge's backend menu offers Pixal3D and TRELLIS.2", '"pixal3d", "Pixal3D' in js and '"trellis2", "TRELLIS.2' in js)
check("Forge's Output shows the ComfyUI 3D line with Install / Folder / Check again",
      "forgeComfyCheck" in js and "/forge/trellis/install" in js and "/forge/trellis/dir" in js)
check("the output options include Triangles and Detail for the ComfyUI backends",
      {o["id"] for o in forge3d.OPTIONS if "pixal3d" in o["applies_to"]} >= {"faces", "detail", "texture_size", "seed"})
import forge_api  # noqa: E402
code, got = forge_api.handle_get(None, "/forge/trellis")
check("GET /forge/trellis answers (ComfyUI off: not reachable, the model list)", code == 200 and got["ok"]
      and not got["reachable"] and len(got["models"]) == 8, got)
code, got = forge_api.handle_post(None, "/forge/trellis/dir", json.dumps({"comfy_dir": str(comfy)}).encode())
check("POST /forge/trellis/dir remembers this computer's ComfyUI folder", code == 200 and got["comfy_dir"] == str(comfy), got)
os.environ.pop("LOKI_COMFY_DIR")
check("and LOKI finds it from then on", ft.find_comfy_dir() == comfy, ft.find_comfy_dir())
mk = (REPO / "engine" / "make_mcp.py").read_text()
lk = (REPO / "engine" / "loki.py").read_text()
check("the agents' make_3d tools can ask for pixal3d / trellis2", '"pixal3d", "trellis2"' in mk and '"pixal3d", "trellis2"' in lk)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
