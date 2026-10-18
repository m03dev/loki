"""Forge (engine/forge3d.py, engine/forge_api.py, app/ui/forge.js), offline and under a minute:
the lift turns a red circle on white into a closed, valid .glb (header, JSON chunk, accessor counts),
backend selection falls through when TripoSR / gradio_client are missing, the API routes work through
the real bridge handler (and refuse path traversal), the make_3d tool is registered, and - when
Playwright + Chromium are here - the window opens Forge, shows the model, sculpts it and saves it.

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
res2 = forge3d.make_3d(url, WS / "models")
check("a canvas drawing (data URL) becomes a model", res2.get("ok") and res2["meta"]["source"] == "drawing", res2)
check("a bad data URL is refused cleanly", not forge3d.make_3d("data:text/plain,hi", WS / "models")["ok"])
check("nothing to make from is refused", not forge3d.make_3d("", WS / "models")["ok"])

# ------------------------------------------------------------------ backend selection
check("auto with neither TripoSR nor gradio_client -> the lift", forge3d.plan("auto") == ["lift"], forge3d.plan("auto"))
check("asking for triposr still ends with the lift", forge3d.plan("triposr") == ["triposr", "lift"])
res3 = forge3d.make_3d(str(circle), WS / "models", backend="triposr")
check("TripoSR missing -> falls through to the lift, says why", res3["ok"] and res3["backend"] == "lift"
      and res3["meta"]["fallbacks"] and res3["meta"]["fallbacks"][0].startswith("triposr"), res3)
res4 = forge3d.make_3d(str(circle), WS / "models", backend="online")
check("gradio_client missing -> falls through to the lift", res4["ok"] and res4["backend"] == "lift"
      and "gradio_client" in res4["meta"]["fallbacks"][0], res4["meta"])
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
      and 'TOOL_CATEGORIES["creative"] += ["make_3d"]' in loki_src)
import manifests  # noqa: E402
mf = json.loads((REPO / "capabilities" / "forge-3d" / "manifest.json").read_text(encoding="utf-8"))
check("capabilities/forge-3d manifest is valid, MIT, says the Space is a third party",
      manifests.validate(mf) == [] and mf["license"].startswith("MIT") and "third party" in mf["description"])
html = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
js = (REPO / "app" / "ui" / "forge.js").read_text(encoding="utf-8")
check("index.html loads forge.js and forge.css, with a sidebar icon", '<script src="/ui/forge.js" defer></script>' in html
      and 'href="/ui/forge.css"' in html and 'id="open-forge"' in html and 'data-icon="cube"' in html)
check("forge.js has the sculpt brushes, symmetry, undo/redo, subdivide",
      all(('["%s",' % b) in js for b in ("draw", "inflate", "smooth", "flatten", "grab", "pinch"))
      and "symmetry" in js and "view.undo" in js and "view.redo" in js and "forgeSubdivide" in js)
check("forge.js has the three ways in", all(w in js for w in ('"Draw"', '"Add an image"', '"Describe it"')))
third = (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
check("docs/THIRD_PARTY.md has a Forge row", "forge3d" in third and "TripoSR" in third)
ship = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("the suite is in ship.py's SUITES", '"test_forge3d"' in ship)

# ------------------------------------------------------------------ the window, headless (skips without Playwright)
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


async def browser_check():
    UI = REPO / "app" / "ui"
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP window: no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            path = r.request.url.split("8898", 1)[1].split("#")[0]
            bare = path.split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare.startswith("/forge/"):   # straight to the real bridge above
                st, out, kind = call(path, raw_body=r.request.post_data_buffer) if r.request.method == "POST" else call(path)
                return await r.fulfill(status=st, body=out, content_type=kind or "application/json")
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8898/**", route)
        await page.goto("http://127.0.0.1:8898/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        check("the sidebar's cube opens Forge", await page.is_visible("#forge-canvas"))
        box = await page.query_selector("#forge-canvas")
        bb = await box.bounding_box()
        await page.mouse.move(bb["x"] + bb["width"] * 0.3, bb["y"] + bb["height"] * 0.5)
        await page.mouse.down()
        for i in range(12):
            await page.mouse.move(bb["x"] + bb["width"] * (0.3 + i * 0.03), bb["y"] + bb["height"] * (0.5 - 0.01 * i))
        await page.mouse.up()
        await page.select_option("#forge-backend", "lift")
        await page.click("#forge-make")
        await page.wait_for_function("document.getElementById('forge-empty').hidden === true && forge.view && forge.view.sm", timeout=20000)
        check("a drawing becomes a model in the viewer", True)
        before = await page.evaluate("forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)")
        await page.evaluate("forge.view.dab('inflate', 0, 0, 0.1, 1); forge.view.dab('draw', 0.2, 0, 0.1, 1)")
        after = await page.evaluate("forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)")
        check("sculpting moves the vertices", abs(after - before) > 1e-4, (before, after))
        await page.evaluate("forge.view.undo(); forge.view.undo()")
        undone = await page.evaluate("forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)")
        check("undo puts them back", abs(undone - before) < 1e-3, (before, undone))
        tris = await page.evaluate("forge.view.sm.idx.length / 3")
        await page.evaluate("forge.view.subdivide()")
        check("subdivide makes four times the triangles", await page.evaluate("forge.view.sm.idx.length / 3") == tris * 4)
        await page.click("#forge-mode")
        check("Sculpt mode shows the brushes", await page.is_visible("#forge-sculpt [data-brush='pinch']"))
        await page.evaluate("forgeSave('glb')")
        await page.wait_for_function("/Saved models/.test(document.getElementById('forge-status').textContent)", timeout=10000)
        sculpted = sorted((WS / "models").glob("*-sculpt*.glb"))
        check("Save .glb writes a valid sculpted model into models/", bool(sculpted)
              and forge3d.glb_counts(sculpted[-1])["triangles"] == tris * 4)
        check("no script errors in Forge", not errors, errors[:3])
        await browser.close()


if async_playwright is None:
    print("SKIP window: no Playwright")
else:
    try:
        asyncio.run(asyncio.wait_for(browser_check(), 45))
    except asyncio.TimeoutError:
        check("the Forge window check finishes in time", False)

srv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
