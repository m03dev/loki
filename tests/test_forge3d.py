"""Forge (engine/forge3d.py, engine/forge_api.py, app/ui/forge.js), offline and under a minute:
the lift turns a red circle on white into a closed, valid .glb (header, JSON chunk, accessor counts),
backend selection falls through when TripoSR / gradio_client are missing, the API routes work through
the real bridge handler (and refuse path traversal), the make_3d tool is registered, the Output options reach every
backend (fakes), every Pollinations request asks for no watermark, and Material Maker is found / opened / saved for.
The window itself (three.js add-ons, sculpting, materials, layout) is tests/test_forge_ui.py.

    python tests/test_forge3d.py
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-forge-"))
WS = TMP / "ws"
WS.mkdir()
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_TRIPOSR_DIR"] = str(TMP / "no-triposr")
os.environ["LOKI_FORGE_JUDGE"] = "0"    # E19 judging is tested on its own in tests/test_forge_judge.py
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import forge3d  # noqa: E402
import forge_api  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

# ------------------------------------------------------------------ the lift
circle = TMP / "circle.png"
im = Image.new("RGB", (256, 256), "white")
ImageDraw.Draw(im).ellipse((48, 48, 208, 208), fill=(220, 20, 20))
im.save(circle)
t0 = time.time()
res = forge3d.make_3d(str(circle), WS / "models", prompt="red ball", backend="lift")
check("the lift makes a model from a red circle", res.get("ok") and res["backend"] == "lift", res)
glb = Path(res["glb"])
raw = glb.read_bytes()
magic, version, length = struct.unpack_from("<III", raw, 0)
check("glb header: magic glTF, version 2, length = file size", magic == 0x46546C67 and version == 2 and length == len(raw))
jlen, jtype = struct.unpack_from("<II", raw, 12)
doc = json.loads(raw[20:20 + jlen])
check("first chunk is JSON with asset version 2.0", jtype == 0x4E4F534A and doc["asset"]["version"] == "2.0")
blen, btype = struct.unpack_from("<II", raw, 20 + jlen)
check("second chunk is BIN and fills the buffer", btype == 0x004E4942 and blen == doc["buffers"][0]["byteLength"])
prim = doc["meshes"][0]["primitives"][0]
acc = doc["accessors"]
nv = acc[prim["attributes"]["POSITION"]]["count"]
check("POSITION, NORMAL, COLOR_0 have the same count", all(acc[prim["attributes"][k]]["count"] == nv
                                                         for k in ("POSITION", "NORMAL", "COLOR_0")))
ni = acc[prim["indices"]]["count"]
check("indices are triangles", ni % 3 == 0 and ni > 300, ni)
for a in acc:
    v = doc["bufferViews"][a["bufferView"]]
    size = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]] * 4
    if v["byteLength"] != a["count"] * size or v["byteOffset"] % 4:
        check("accessor byte lengths match", False, a)
        break
else:
    check("accessor byte lengths match", True)
binary = raw[20 + jlen + 8:]
iv = doc["bufferViews"][acc[prim["indices"]]["bufferView"]]
idx = struct.unpack_from("<%dI" % ni, binary, iv["byteOffset"])
check("every index points at a vertex", max(idx) < nv)
edges = Counter()
for i in range(0, ni, 3):
    a, b, c = idx[i:i + 3]
    edges.update([(a, b), (b, c), (c, a)])
check("the mesh is closed and consistently wound (every edge once each way)",
      all(n == 1 and edges.get((e[1], e[0])) == 1 for e, n in edges.items()))
pmin, pmax = acc[prim["attributes"]["POSITION"]]["min"], acc[prim["attributes"]["POSITION"]]["max"]
check("it is round: as deep as about half its width", 0.3 < (pmax[2] - pmin[2]) / (pmax[0] - pmin[0]) < 1.2, (pmin, pmax))
cv = doc["bufferViews"][acc[prim["attributes"]["COLOR_0"]]["bufferView"]]
r, g, b = struct.unpack_from("<3f", binary, cv["byteOffset"] + 12 * (nv // 2))
check("vertex colours come from the picture (red)", r > 0.5 and g < 0.1 and b < 0.1, (r, g, b))
check("an .obj is written too", Path(res["obj"]).read_text().startswith("# LOKI Forge"))
side = WS / "models" / ".meta" / (glb.name + ".json")
meta = json.loads(side.read_text())
check("sidecar: prompt, source, backend, time, counts", meta["prompt"] == "red ball" and meta["backend"] == "lift"
      and meta["t"] and meta["triangles"] == ni // 3)
check("read_glb / glb_counts agree", forge3d.glb_counts(glb) == {"vertices": nv, "triangles": ni // 3})
check("the lift is fast (< 10 s)", time.time() - t0 < 10, time.time() - t0)

# a drawing as a data URL, transparent background (alpha used), and a drawing with a hole kept
buf = io.BytesIO()
dr = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
ImageDraw.Draw(dr).rectangle((20, 30, 180, 90), fill=(30, 120, 240, 255))
dr.save(buf, "PNG")
url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
res2 = forge3d.make_3d(url, WS / "models", backend="lift")   # auto no longer ends in a lift blob (owner 2026-10-26)
check("a canvas drawing (data URL) becomes a model", res2.get("ok") and res2["meta"]["source"] == "drawing", res2)
res_auto = forge3d.make_3d(url, WS / "models")
check("auto never hands over a silhouette blob as a finished model - it says what to start instead",
      res_auto.get("ok") is False and "ComfyUI" in res_auto.get("error", ""), res_auto)
res_draft = forge3d.make_3d(url, WS / "models", options={"allow_draft": True})
check("... unless a draft is asked for", res_draft.get("ok") and res_draft.get("backend") == "lift", res_draft.get("error"))
check("a bad data URL is refused cleanly", not forge3d.make_3d("data:text/plain,hi", WS / "models")["ok"])
check("nothing to make from is refused", not forge3d.make_3d("", WS / "models")["ok"])

# ------------------------------------------------------------------ backend selection
check("auto with neither TripoSR nor gradio_client -> the lift", forge3d.plan("auto") == ["lift"], forge3d.plan("auto"))
check("asking for triposr still ends with the lift", forge3d.plan("triposr") == ["triposr", "lift"])
res3 = forge3d.make_3d(str(circle), WS / "models", backend="triposr")
check("TripoSR missing -> an error that says why, never a silent lift blob (owner 2026-10-26: 'its just a blob')",
      res3["ok"] is False and "triposr" in res3["error"] and "lift" in res3["error"], res3)
res3b = forge3d.make_3d(str(circle), WS / "models", backend="triposr", options={"allow_draft": True})
check("... a draft asked for on purpose still falls through to the lift and says why", res3b["ok"]
      and res3b["backend"] == "lift" and res3b["meta"]["fallbacks"][0].startswith("triposr"), res3b)
res4 = forge3d.make_3d(str(circle), WS / "models", backend="online")
check("gradio_client missing -> an error naming it, not a lift", res4["ok"] is False and "gradio_client" in res4["error"], res4)
os.environ["LOKI_FORGE_SPACES"] = "a/one, b/two"
check("online Spaces are tried in turn (LOKI_FORGE_SPACES)", forge3d.online_spaces() == ["a/one", "b/two"])
os.environ.pop("LOKI_FORGE_SPACES")
check("... by default TRELLIS then TRELLIS.2", forge3d.online_spaces()[:2] == ["trellis-community/TRELLIS", "microsoft/TRELLIS.2"])
os.environ["LOKI_LOCAL_ONLY"] = "1"
check("local-only never uses the online Space", not forge3d.online_ready())
os.environ.pop("LOKI_LOCAL_ONLY")


class FakeProc:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, "", 0


def fake_triposr(argv, input, **kw):  # noqa: A002 - subprocess.run's own name
    job = json.loads(input)
    forge3d.write_glb(Path(job["out"] + ".glb"), forge3d.lift_mesh([[True, True], [True, True]], [[(9, 9, 9)] * 2] * 2, 2, 2))
    return FakeProc(json.dumps({"ok": True, "glb": job["out"] + ".glb", "obj": "", "device": "cuda:0"}))


res5 = forge3d.make_3d(str(circle), WS / "models", backend="triposr", triposr_runner=fake_triposr)
check("a working TripoSR runner is used (its own process, JSON in/out)", res5["ok"] and res5["backend"] == "triposr", res5)
made = []
res6 = forge3d.make_3d("", WS / "models", prompt="a mushroom", backend="lift",
                       image_maker=lambda p: (made.append(p), str(circle))[1])
check("text -> picture -> 3D uses the image maker first", res6["ok"] and made == ["a mushroom"] and res6["image"] == str(circle))
check("models are listed newest first with their sidecar", forge3d.list_models(WS / "models")[0]["name"] == res6["name"]
      and forge3d.list_models(WS / "models")[0]["prompt"] == "a mushroom")

# ------------------------------------------------------------------ the API through the real bridge handler
import loki_bridge  # noqa: E402


class Agent:
    WORKSPACE = WS

    @staticmethod
    def forge_image_maker(prompt):
        target = WS / "images" / "made.png"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(circle.read_bytes())
        return str(target)


class State:
    agent = Agent()
    secret = "s3cret"


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), loki_bridge.BridgeHandler)
        self.state = State()


srv = Server()
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None, raw_body=None, token="s3cret"):
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=20) as resp:
            out = resp.read()
            return resp.status, out, resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def wait(job_id):
    for _ in range(200):
        st, out, _ = call("/forge/status?id=" + job_id)
        j = json.loads(out)
        if j.get("done"):
            return j
        time.sleep(0.05)
    return {}


st, out, _ = call("/forge/status")
check("GET /forge/status lists the backends and the order", st == 200 and json.loads(out)["order"] == ["lift"], out[:200])
check("the token is required", call("/forge/list", token="wrong")[0] == 401)
st, out, _ = call("/forge/make", {"drawing": url, "backend": "lift"})
job = wait(json.loads(out)["id"])
check("POST /forge/make {drawing} runs as a job with progress to done", job.get("done") and job["result"]["ok"]
      and job["progress"] == 1.0, job)
name = job["result"]["name"]
check("the job's result names the file, not a local path", "glb" not in job["result"] and name.endswith(".glb"))
st, out, _ = call("/forge/make", {"image": "../circle.png"})
check("POST /forge/make refuses a picture outside the workspace", st == 400, out)
(WS / "images").mkdir(exist_ok=True)
(WS / "images" / "c.png").write_bytes(circle.read_bytes())
st, out, _ = call("/forge/make", {"image": "images/c.png", "prompt": "ball", "backend": "lift"})
check("POST /forge/make {image} works", wait(json.loads(out)["id"])["result"]["ok"])
st, out, _ = call("/forge/image", {"prompt": "a fox"})
j = wait(json.loads(out)["id"])
check("POST /forge/image -> a picture in the workspace, shown before 3D", j["result"].get("image") == "images/made.png", j)
st, out, _ = call("/forge/make", {"prompt": "a fox", "backend": "lift"})
j = wait(json.loads(out)["id"])
check("POST /forge/make {prompt} draws first, then lifts", j["result"]["ok"] and j["result"]["image"] == "images/made.png", j)
st, out, _ = call("/forge/list")
items = json.loads(out)["items"]
check("GET /forge/list shows the models", st == 200 and len(items) >= 6 and items[0]["name"].endswith(".glb"))
st, out, kind = call("/forge/file/" + name)
check("GET /forge/file/<name> serves the .glb", st == 200 and out[:4] == b"glTF" and kind == "model/gltf-binary")
(TMP / "secret.glb").write_bytes(b"glTF-secret")
for bad in ("../secret.glb", "..%2Fsecret.glb", "%2E%2E%2Fsecret.glb", "..%5Csecret.glb", ".meta%2Fx.json",
            "notes.txt", "%2Fetc%2Fpasswd", "..", ""):
    st, out, _ = call("/forge/file/" + bad)
    if st != 404 or b"secret" in out:
        check("path traversal on the file route is refused", False, (bad, st, out[:60]))
        break
else:
    check("path traversal on the file route is refused", True)
st, out, _ = call("/forge/save?name=..%2F..%2Fevil.glb", raw_body=raw)
saved = json.loads(out)
check("POST /forge/save keeps the file inside models/", st == 200 and saved["path"] == "models/evil.glb"
      and (WS / "models" / "evil.glb").is_file() and not (TMP / "evil.glb").exists(), saved)
st, out, _ = call("/forge/save?name=evil.glb", raw_body=raw)
check("POST /forge/save never overwrites", json.loads(out)["name"] == "evil-2.glb")
check("POST /forge/save refuses other types and broken glb",
      call("/forge/save?name=x.exe", raw_body=b"MZ")[0] == 400 and call("/forge/save?name=x.glb", raw_body=b"glTFjunk")[0] == 400)

# ------------------------------------------------------------------ registration + window (static)
loki_src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("make_3d is an agent tool (schema + dispatch + creative category)",
      'LOCAL_TOOLS["make_3d"] = make_3d_tool' in loki_src and '"make_3d", "Make a 3D model' in loki_src
      and 'TOOL_CATEGORIES["creative"] += ["make_3d"' in loki_src)
import manifests  # noqa: E402
mf = json.loads((REPO / "capabilities" / "forge-3d" / "manifest.json").read_text(encoding="utf-8"))
check("capabilities/forge-3d manifest is valid, MIT, says the Space is a third party",
      manifests.validate(mf) == [] and mf["license"].startswith("MIT") and "third party" in mf["description"])
html = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
js = (REPO / "app" / "ui" / "forge.js").read_text(encoding="utf-8")
check("index.html loads forge.js and forge.css, with a sidebar icon", '<script src="/ui/forge.js" defer></script>' in html
      and 'href="/ui/forge.css"' in html and 'id="open-forge"' in html and 'data-icon="cube"' in html)
check("forge.js has the sculpt brushes (SculptGL's), symmetry, undo/redo, subdivide",
      all(('["%s",' % b) in js for b in ("draw", "inflate", "smooth", "flatten", "grab", "pinch", "crease"))
      and "SculptGL" in js
      and "symmetry" in js and "view.undo" in js and "view.redo" in js and "forgeSubdivide" in js)
check("forge.js has the three ways in", all(w in js for w in ('"Draw"', '"Add an image"', '"Describe it"')))
third = (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
check("docs/THIRD_PARTY.md has a Forge row", "forge3d" in third and "TripoSR" in third)
ship = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("the suite is in ship.py's SUITES", '"test_forge3d"' in ship)

# ------------------------------------------------------------------ output options reach the backends (fakes)
opts = forge3d.clean_options({"resolution": 9999, "keep": 50, "thickness": 1.5, "smooth": 0, "image_size": 777, "seed": 42,
                              "foreground": 0.7, "symmetry": "on", "bogus": 1})
check("options are clamped to their range, unknown ones dropped", opts["resolution"] == 512 and "bogus" not in opts
      and opts["symmetry"] is True and opts["thickness"] == 1.5, opts)
check("every option is one module entry {id, label, min, max, step, default, applies_to}",
      all({"id", "label", "default", "applies_to", "kind"} <= set(o) for o in forge3d.OPTIONS)
      and {o["id"] for o in forge3d.OPTIONS} >= {"resolution", "keep", "thickness", "smooth", "texture_size", "image_size",
                                                   "foreground", "cutout", "symmetry", "seed"})
seen = {}


def fake_triposr2(argv, input, **kw):  # noqa: A002
    seen["triposr"] = json.loads(input)
    return fake_triposr(argv, input, **kw)


forge3d.make_3d(str(circle), WS / "models", backend="triposr", triposr_runner=fake_triposr2, options={"resolution": 384, "foreground": 0.7, "keep": 40})
check("TripoSR gets mc resolution, foreground ratio and keep %", seen["triposr"]["resolution"] == 384
      and seen["triposr"]["foreground_ratio"] == 0.7 and seen["triposr"]["keep"] == 40, seen.get("triposr"))


class FakeClient:
    def __init__(self):
        self.calls = []

    def predict(self, **kw):
        self.calls.append(kw)
        if kw.get("api_name") == "/extract_glb":
            g = TMP / "space.glb"
            forge3d.write_glb(g, forge3d.lift_mesh([[True]], [[(1, 2, 3)]], 1, 1))
            return [None, str(g)]
        return None


fc = FakeClient()
r_on = forge3d.make_3d(str(circle), WS / "models", backend="online", online_factory=lambda space: (fc, lambda f: f),
                       options={"texture_size": 2048, "keep": 5, "seed": 7})
check("the online Space gets texture size, simplify and seed", r_on["ok"] and r_on["backend"] == "online"
      and [c for c in fc.calls if c.get("api_name") == "/extract_glb"][0]["texture_size"] == 2048
      and [c for c in fc.calls if c.get("api_name") == "/extract_glb"][0]["mesh_simplify"] == 0.98
      and [c for c in fc.calls if c.get("api_name") == "/image_to_3d"][0]["seed"] == 7, fc.calls)
coarse = forge3d.make_3d(str(circle), WS / "models", backend="lift", options={"resolution": 64, "smooth": 0})
fine = forge3d.make_3d(str(circle), WS / "models", backend="lift", options={"resolution": 512})
check("the lift's grid follows Mesh resolution", coarse["meta"]["triangles"] * 8 < fine["meta"]["triangles"],
      (coarse["meta"]["triangles"], fine["meta"]["triangles"]))
thin = forge3d.make_3d(str(circle), WS / "models", backend="lift", options={"thickness": 0.2})
fat = forge3d.make_3d(str(circle), WS / "models", backend="lift", options={"thickness": 2.0})
depth = lambda r: (lambda d: d["accessors"][d["meshes"][0]["primitives"][0]["attributes"]["POSITION"]])(forge3d.read_glb(Path(r["glb"]))[0])  # noqa: E731
check("the lift's thickness follows Thickness", depth(fat)["max"][2] > 4 * depth(thin)["max"][2])
asked = []
forge3d.make_3d("", WS / "models", prompt="a vase", backend="lift", options={"image_size": 1536, "seed": 9},
                image_maker=lambda p, o: (asked.append(o), str(circle))[1])
check("text -> picture gets the picture size and seed", asked == [{"width": 1536, "height": 1536, "seed": 9}], asked)
check("an old-style image maker (prompt only) still works", forge3d.make_3d("", WS / "models", prompt="x", backend="lift",
                                                                              image_maker=lambda p: str(circle))["ok"])
check("the options are kept in the sidecar", fine["meta"]["options"]["resolution"] == 512)
st, out, _ = call("/forge/make", {"drawing": url, "backend": "lift", "options": {"resolution": 64, "thickness": 0.3}})
j = wait(json.loads(out)["id"])
side2 = json.loads((WS / "models" / ".meta" / (j["result"]["name"] + ".json")).read_text())
check("POST /forge/make passes the options through the API", side2["options"]["resolution"] == 64 and side2["options"]["thickness"] == 0.3)
st, out, _ = call("/forge/status")
check("GET /forge/status serves the option modules for the window", [o["id"] for o in json.loads(out)["backends"]["options"]]
      == [o["id"] for o in forge3d.OPTIONS])

# ------------------------------------------------------------------ watermark: every Pollinations request asks for none
sys.path.insert(0, str(REPO / "engine" / "runners"))
import imagegen  # noqa: E402
check("Pollinations is gone from the image runner (owner 2026-10-26: 'giving awful results')",
      not hasattr(imagegen, "pollinations") and "pollinations" not in imagegen.plan_order("auto")["order"])

# ------------------------------------------------------------------ Material Maker: find it, open files in it, save .ptex/.png
import forge_mm  # noqa: E402
os.environ["LOKI_MATERIAL_MAKER"] = ""
mm_dir = TMP / "data" / "tools" / "material_maker_1_5"
mm_dir.mkdir(parents=True)
exe = mm_dir / ("material_maker.exe" if sys.platform == "win32" else "material_maker")
exe.write_text("")
exe.chmod(0o755)
check("Material Maker is found in harness_data/tools", forge_mm.find() == str(exe) or sys.platform == "darwin", forge_mm.find())
started = []
forge_mm.RUN = lambda argv, **kw: started.append(argv)
ptex = json.dumps({"type": "graph", "nodes": [], "connections": []}).encode()
st, out, _ = call("/forge/save?name=wood.ptex", raw_body=ptex)
check("a .ptex project saves into models/", st == 200 and json.loads(out)["name"] == "wood.ptex")
check("a broken .ptex is refused", call("/forge/save?name=x.ptex", raw_body=b"nope")[0] == 400)
png = io.BytesIO(); Image.new("RGB", (4, 4)).save(png, "PNG")
check("a material map .png saves; a fake one is refused", call("/forge/save?name=m_albedo.png", raw_body=png.getvalue())[0] == 200
      and call("/forge/save?name=x.png", raw_body=b"GIF89a")[0] == 400)
if sys.platform != "darwin":
    st, out, _ = call("/forge/mm/open", {"name": "wood.ptex"})
    check("Open in Material Maker starts it with the .ptex", json.loads(out).get("ok") and started and started[-1][-1].endswith("wood.ptex"), (out, started))
st, out, _ = call("/forge/mm/open", {"name": "../secret.glb"})
check("Open in Material Maker only opens files from models/", st == 404)
st, out, _ = call("/forge/mm")
check("GET /forge/mm reports it with the download link", json.loads(out)["download"].startswith("https://github.com/RodZill4/material-maker"))
nodes = json.loads((REPO / "app" / "ui" / "vendor" / "material_maker" / "nodes.json").read_text(encoding="utf-8"))
check("Material Maker's own node files are bundled (noise, voronoi, gradients, shapes, blend, colorize, tiling, transform)",
      {"perlin", "fbm2", "voronoi", "gradient", "shape", "blend", "colorize", "tile2x2", "transform2"} <= set(nodes["nodes"])
      and nodes["_meta"]["licence"] == "MIT" and "float rand(vec2" in nodes["_shader_functions"])
check("their licence is next to them", "Rodolphe Suescun" in (REPO / "app" / "ui" / "vendor" / "material_maker" / "LICENSE").read_text())
third = (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
check("THIRD_PARTY: SculptGL, Material Maker, the three.js add-ons", "SculptGL" in third and "Material Maker" in third
      and "GLTFLoader" in third and (REPO / "app" / "ui" / "licenses" / "SculptGL-LICENSE.txt").is_file())
for addon in ("loaders/GLTFLoader.js", "exporters/GLTFExporter.js", "exporters/OBJExporter.js", "controls/OrbitControls.js",
              "controls/TransformControls.js", "utils/BufferGeometryUtils.js"):
    text = (REPO / "app" / "ui" / "vendor" / "three" / "addons" / addon).read_text(encoding="utf-8")
    if "from 'three'" in text:
        check("vendored add-ons import the local three.js (no import map)", False, addon)
        break
else:
    check("vendored add-ons import the local three.js (no import map)", True)
check("ship.py runs the Forge window suite too", '"test_forge_ui"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))

srv.shutdown()
# ------------------------------------------------------------------ the online Space across versions
class _NewClient:
    def __init__(self, space, token=None):
        self.kw = ("token", token)


class _OldClient:
    def __init__(self, space, hf_token=None):
        self.kw = ("hf_token", hf_token)


check("gradio_client: token= on new versions, hf_token= on old ones (the Mac's 'unexpected keyword hf_token')",
      forge3d.gradio_client_for(_NewClient, "s", "t").kw == ("token", "t")
      and forge3d.gradio_client_for(_OldClient, "s", "t").kw == ("hf_token", "t"))
_glb = TMP / "space_out.glb"
forge3d.write_glb(_glb, forge3d.lift_mesh([[True]], [[(1, 2, 3)]], 1, 1))
_calls = []


class _OldSpace:
    """The older TRELLIS app: /image_to_3d takes only the image; /extract_glb the two settings (state is kept by
    the client's session) - as its view_api says."""
    def view_api(self, return_format="dict", print_info=False):
        return {"named_endpoints": {
            "/preprocess_image": {"parameters": [{"parameter_name": "image", "parameter_has_default": False}]},
            "/image_to_3d": {"parameters": [{"parameter_name": "image", "parameter_has_default": False}]},
            "/extract_glb": {"parameters": [{"parameter_name": "mesh_simplify", "parameter_has_default": True},
                                            {"parameter_name": "texture_size", "parameter_has_default": True}]}}}

    def predict(self, *args, api_name="", **kw):
        _calls.append((api_name, sorted(kw)))
        if api_name == "/start_session":
            raise ValueError("no such endpoint")
        if api_name == "/image_to_3d":
            return "video.mp4"
        if api_name == "/extract_glb":
            return str(_glb), str(_glb)


class _OneShotSpace:
    def view_api(self, return_format="dict", print_info=False):
        return {"named_endpoints": {"/generate_and_extract_glb": {"parameters": [
            {"parameter_name": "image", "parameter_has_default": False},
            {"parameter_name": "seed", "parameter_has_default": True},
            {"parameter_name": "style_strength", "parameter_has_default": True}]}}}

    def predict(self, *args, api_name="", **kw):
        _calls.append((api_name, sorted(kw)))
        if api_name == "/generate_and_extract_glb":
            return {"video": "v.mp4", "model": {"path": str(_glb)}}


_png = TMP / "cut.png"
__import__("PIL.Image", fromlist=["Image"]).new("RGBA", (8, 8), (200, 0, 0, 255)).save(_png)
_r = forge3d.run_online(_png, TMP / "online_model", client_factory=lambda space: (_OldSpace(), lambda p: p))
check("the Space's own endpoint list is used: the older TRELLIS (image only, then extract) works",
      Path(_r["glb"]).is_file() and ("/image_to_3d", ["image"]) in _calls
      and ("/extract_glb", ["mesh_simplify", "texture_size"]) in _calls, _calls)
_calls.clear()
_r = forge3d.run_online(_png, TMP / "online_model2", client_factory=lambda space: (_OneShotSpace(), lambda p: p))
check("a one-step generate-and-extract endpoint is used as is, unknown optional settings left at their defaults",
      Path(_r["glb"]).is_file() and _calls == [("/generate_and_extract_glb", ["image", "seed"])], _calls)


class _StrangeSpace:
    def view_api(self, return_format="dict", print_info=False):
        return {"named_endpoints": {"/chat": {"parameters": []}}}

    def predict(self, *a, **k):
        return None


try:
    forge3d.run_online(_png, TMP / "x", client_factory=lambda space: (_StrangeSpace(), lambda p: p))
    check("a Space with no 3D endpoint says what it has instead", False)
except forge3d.ForgeError as exc:
    check("a Space with no 3D endpoint says what it has instead", "/chat" in str(exc), exc)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
