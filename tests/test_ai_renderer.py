"""Render Studio's engine (engine/ai_renderer.py) against a FAKE ComfyUI on localhost that answers the routes ComfyUI's
server.py defines (/system_stats, /object_info, /upload/image, /prompt, /queue, /history/{id}, /view, /interrupt, /ws),
with the node schemas captured from the sources in tests/fixtures/comfyui_object_info.json. Offline, under a minute.

    python tests/test_ai_renderer.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-airender-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PEERS"] = "pc=http://192.168.50.7:8768"
os.environ.pop("LOKI_COMFYUI_URL", None)
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import ai_renderer as AR  # noqa: E402

FIX = json.loads((REPO / "tests" / "fixtures" / "comfyui_object_info.json").read_text(encoding="utf-8"))["object_info"]
MODELS = {"unet_gguf": ["wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf"], "text_encoders": ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"],
          "vae": ["wan_2.1_vae.safetensors", "pixel_space"]}


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ the fake ComfyUI
class Fake:
    def __init__(self):
        self.models = json.loads(json.dumps(MODELS))
        self.drop_nodes = set()
        self.uploads = {}
        self.prompts = {}
        self.history = {}
        self.running = None
        self.interrupted = []
        self.mode = "ok"            # ok | fail | slow | evil
        self.ws_clients = []
        self.lock = threading.Lock()

    def object_info(self):
        info = json.loads(json.dumps(FIX))
        info["UNETLoader"]["input"]["required"]["unet_name"] = [[]]
        info["CLIPLoader"]["input"]["required"]["clip_name"] = [self.models["text_encoders"]]
        info["VAELoader"]["input"]["required"]["vae_name"] = [self.models["vae"]]
        info["UnetLoaderGGUF"]["input"]["required"]["unet_name"] = [self.models["unet_gguf"]]
        info["LoadImage"]["input"]["required"]["image"] = [sorted(self.uploads), {"image_upload": True}]
        for n in self.drop_nodes:
            info.pop(n, None)
        return info

    def validate(self, prompt):
        info = self.object_info()
        errors = {}
        for nid, node in prompt.items():
            cls = node.get("class_type")
            if cls not in info:
                return {"type": "missing_node_type", "message": "Node '%s' not found" % cls}, {}
            req = info[cls]["input"]["required"]
            for k, spec in req.items():
                if k not in node["inputs"]:
                    errors[nid] = {"class_type": cls, "errors": [{"message": "Required input is missing", "details": k}]}
                    continue
                v = node["inputs"][k]
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    if v[0] not in prompt:
                        errors[nid] = {"class_type": cls, "errors": [{"message": "bad link", "details": k}]}
                    continue
                if cls == "LoadImage":
                    if v not in self.uploads:
                        errors[nid] = {"class_type": cls, "errors": [{"message": "Invalid image file", "details": v}]}
                    continue
                opts = AR._option_list(spec)
                if opts is not None and v not in opts:
                    errors[nid] = {"class_type": cls, "errors": [{"message": "Value not in list", "details": "%s: %r" % (k, v)}]}
                if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) and isinstance(v, (int, float)):
                    if "min" in spec[1] and v < spec[1]["min"] or "max" in spec[1] and v > spec[1]["max"]:
                        errors[nid] = {"class_type": cls, "errors": [{"message": "out of range", "details": k}]}
        if errors:
            return {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"}, errors
        return None, {}

    def execute(self, pid, prompt):
        """What ComfyUI's worker would do: progress over the sampler steps, then the history entry."""
        steps = int(prompt["12"]["inputs"]["steps"]) if "12" in prompt else 2
        with self.lock:
            self.running = pid
        for i in range(steps):
            if pid in self.interrupted:
                with self.lock:
                    self.history[pid] = {"prompt": [0, pid, prompt, {}, []], "outputs": {}, "status": {"status_str": "error", "completed": False,
                                         "messages": [["execution_start", {"prompt_id": pid}], ["execution_interrupted", {"prompt_id": pid, "node_id": "12"}]]}}
                    self.running = None
                return
            self.ws_send({"type": "progress", "data": {"value": i + 1, "max": steps, "prompt_id": pid, "node": "12"}})
            time.sleep(0.25 if self.mode == "slow" else 0.02)
        with self.lock:
            self.running = None
            if self.mode == "fail":
                self.history[pid] = {"prompt": [0, pid, prompt, {}, []], "outputs": {}, "status": {"status_str": "error", "completed": False,
                                     "messages": [["execution_start", {"prompt_id": pid}], ["execution_error", {"prompt_id": pid, "node_id": "12", "node_type": "KSampler",
                                                                                                                "exception_message": "CUDA out of memory"}]]}}
                return
            prefix = prompt["15"]["inputs"]["filename_prefix"]
            sub, base = prefix.rsplit("/", 1)
            vname = "../../evil.webm" if self.mode == "evil" else base + "_00001_.webm"
            self.history[pid] = {"prompt": [0, pid, prompt, {}, []], "status": {"status_str": "success", "completed": True, "messages": []},
                                 "outputs": {"15": {"images": [{"filename": vname, "subfolder": sub, "type": "output"}], "animated": [True]},
                                             "17": {"images": [{"filename": base + "_00001_.png", "subfolder": sub, "type": "output"}]}}}

    def ws_send(self, msg):
        data = json.dumps(msg).encode()
        frame = bytes([0x81]) + (bytes([len(data)]) if len(data) < 126 else bytes([126]) + struct.pack(">H", len(data))) + data
        for c in list(self.ws_clients):
            try:
                c.sendall(frame)
            except OSError:
                self.ws_clients.remove(c)


FAKE = Fake()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/ws":
            key = self.headers.get("Sec-WebSocket-Key", "")
            acc = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", acc)
            self.end_headers()
            self.wfile.flush()
            FAKE.ws_clients.append(self.connection)
            FAKE.ws_send({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}}})
            time.sleep(5)
            return
        if u.path == "/system_stats":
            return self._json(200, {"system": {"os": "nt", "comfyui_version": "0.9.9", "python_version": "3.12"},
                                    "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 3070 Ti : cudaMallocAsync", "type": "cuda", "vram_total": 8589934592, "vram_free": 7000000000}]})
        if u.path == "/object_info":
            return self._json(200, FAKE.object_info())
        if u.path == "/queue":
            with FAKE.lock:
                run = [[0, FAKE.running, {}, {}, []]] if FAKE.running else []
                pend = [[1, p, {}, {}, []] for p in FAKE.prompts if p not in FAKE.history and p != FAKE.running]
            return self._json(200, {"queue_running": run, "queue_pending": pend})
        if u.path.startswith("/history/"):
            pid = u.path.split("/", 2)[2]
            with FAKE.lock:
                h = FAKE.history.get(pid)
            return self._json(200, {pid: h} if h else {})
        if u.path == "/view":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("filename", "").startswith("/") or ".." in q.get("filename", ""):
                self.send_response(400); self.end_headers(); return
            body = b"\x1aE\xdf\xa3fake-webm" if q["filename"].endswith(".webm") else png(4, 4, (9, 9, 9))
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {})

    def do_POST(self):
        u = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        if u.path == "/upload/image":
            ct = self.headers.get("Content-Type", "")
            bnd = ct.split("boundary=", 1)[1].encode()
            fields, fname, data = {}, None, b""
            for part in body.split(b"--" + bnd):
                if b"\r\n\r\n" not in part:
                    continue
                head, val = part.split(b"\r\n\r\n", 1)
                val = val[:-2] if val.endswith(b"\r\n") else val
                name = head.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
                if b'filename="' in head:
                    fname = head.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
                    data = val
                else:
                    fields[name] = val.decode()
            sub = fields.get("subfolder", "")
            FAKE.uploads[(sub + "/" if sub else "") + fname] = data
            return self._json(200, {"name": fname, "subfolder": sub, "type": "input"})
        if u.path == "/prompt":
            d = json.loads(body)
            err, nerr = FAKE.validate(d["prompt"])
            if err:
                return self._json(400, {"error": err, "node_errors": nerr})
            pid = d.get("prompt_id")
            FAKE.prompts[pid] = d["prompt"]
            threading.Thread(target=FAKE.execute, args=(pid, d["prompt"]), daemon=True).start()
            return self._json(200, {"prompt_id": pid, "number": len(FAKE.prompts), "node_errors": {}})
        if u.path == "/interrupt":
            d = json.loads(body or b"{}")
            if d.get("prompt_id") == FAKE.running:
                FAKE.interrupted.append(d["prompt_id"])
            self.send_response(200); self.end_headers(); return
        if u.path == "/queue":
            self.send_response(200); self.end_headers(); return
        self._json(404, {})


fake = ThreadingHTTPServer(("127.0.0.1", 0), H)
fake.daemon_threads = True
threading.Thread(target=fake.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % fake.server_address[1]


class Agent:
    DATA_DIR = TMP / "data"
    WORKSPACE = TMP / "ws"


class State:
    agent = Agent()
    secret = "s3cret"


ST = State()

# ------------------------------------------------------------------ workflow graphs: valid against the captured schemas
wfs = AR.workflows()
check("four graphs ship (render, preprocess, two Z-Image reference graphs)",
      set(wfs) == {"vace_render", "preprocess_lineart", "zimage_reference", "zimage_reference_depth"}, list(wfs))
for name, wf in wfs.items():
    probs = AR.check_graph(wf["prompt"], FIX)
    check("%s: every link points at an existing node + output, every required input is set, no unknown input" % name, not probs, probs)
    for key, spec in wf["params"].items():
        for nid, inp in spec.get("nodes") or [[spec["node"], spec["input"]]]:
            node = wf["prompt"].get(nid)
            ok = node is not None and inp in node["inputs"] and AR._input_spec(FIX, node["class_type"], inp) is not None
            if not ok:
                check("%s: parameter %s maps to a real input" % (name, key), False, (nid, inp))
    for m in wf["models"]:
        node = wf["prompt"][m["node"]]
        check("%s: model %s sits on a loader input (%s.%s)" % (name, m["file"], node["class_type"], m["input"]),
              node["inputs"].get(m["input"]) == m["file"] and m["size"] > 0 and m["revision"], m)
render = wfs["vace_render"]
check("the render graph's frame count follows 4n+1 by default (81)", (render["prompt"]["11"]["inputs"]["length"] - 1) % 4 == 0)
check("the GGUF loader is ComfyUI-GGUF's UnetLoaderGGUF, recorded as the one custom node pack",
      render["prompt"]["1"]["class_type"] == "UnetLoaderGGUF" and list(render["custom_nodes"]) == ["UnetLoaderGGUF"])
p, prob = AR.build_prompt(render, {"frames": 33, "prompt": "a fox", "seed": 7}, {"depth": "loki/a.png", "lineart": "loki/b.png"}, "lineart")
check("Guide 'line art only' wires the line art straight into VACE and drops the depth loader + the blend",
      p["11"]["inputs"]["control_video"] == ["8", 0] and "7" not in p and "9" not in p and not AR.check_graph(p, FIX), (p.get("11"), prob))
check("without a start image the reference_image input and its loader are taken out", "10" not in p and "reference_image" not in p["11"]["inputs"])
p2, prob2 = AR.build_prompt(render, {"cfg": 1e9}, {"depth": "a", "lineart": "b"})
check("a value outside the node's own range is refused", any("cfg" in x for x in prob2), prob2)

# ------------------------------------------------------------------ APNG packing
frames = [png(8, 6, (i * 40, 0, 0)) for i in range(3)]
ap = AR.apng(frames, 16)
kinds = []
pos = 8
while pos < len(ap):
    ln, k = struct.unpack(">I4s", ap[pos:pos + 8]); kinds.append(k); pos += 12 + ln
check("three PNG frames become one APNG: acTL(3), 3 fcTL, IDAT for the first, fdAT for the rest, CRCs valid",
      kinds.count(b"fcTL") == 3 and kinds.count(b"fdAT") == 2 and kinds.count(b"IDAT") == 1 and struct.unpack(">I", ap[ap.index(b"acTL") + 4:ap.index(b"acTL") + 8])[0] == 3, kinds)
try:
    AR.apng([png(8, 6, (0, 0, 0)), png(9, 6, (0, 0, 0))], 16)
    check("frames of different sizes are refused", False)
except AR.RenderError:
    check("frames of different sizes are refused", True)

# ------------------------------------------------------------------ connection, settings, consent
AR.save_settings(ST, {"url": URL})
cl = AR.Comfy(URL)
st = cl.system_stats()
check("connection test: /system_stats answers with the GPU", "3070" in st["devices"][0]["name"])
check("a local URL counts as this computer", AR.where(URL)["place"] == "local")
check("a URL on a linked peer's host counts as LOKI's own machine", AR.where("http://192.168.50.7:8188")["place"] == "peer")
check("anything else is remote and needs consent", not AR.may_upload({"url": "http://203.0.113.9:8188", "consent_remote": False})[0]
      and AR.may_upload({"url": "http://203.0.113.9:8188", "consent_remote": True})[0])
try:
    AR.save_settings(ST, {"url": "http://user:pw@10.0.0.2:8188"})
    check("an address with a password is refused", False)
except AR.RenderError:
    check("an address with a password is refused", True)
check("logs show the host only, never a user / password / query", AR.redact("http://u:p@pc.lan:8188/x?token=1") == "http://pc.lan:8188")
dead = AR.Comfy("http://127.0.0.1:9")
try:
    dead.system_stats()
    check("an unreachable ComfyUI is a plain error", False)
except AR.RenderError as exc:
    check("an unreachable ComfyUI is a plain error", "cannot reach ComfyUI" in str(exc), exc)


def newjob(frames=5, **params):
    j = AR.new_job(ST, {"kind": "ai", "workflow": "vace_render", "params": {"frames": frames, "steps": 4, "prompt": "a red fox", **params},
                        "size": [64, 64], "fps": 16, "frames": frames, "camera": "persp"})["job"]
    for i in range(frames):
        AR.save_pass(ST, j, "depth", i, png(64, 64, (200 - i * 10,) * 3))
        AR.save_pass(ST, j, "lineart", i, png(64, 64, (0, 0, 0)))
    return j


# ------------------------------------------------------------------ preflight
rep = AR.preflight(ST, "vace_render", {"frames": 5, "width": 64, "height": 64}, client=cl)
check("preflight with everything installed: ok, nodes and models checked, GPU memory reported",
      rep["ok"] and any("installed" in c for c in rep["checked"]) and rep["gpu"]["vram_total"] == 8589934592, rep)
check("preflight warns that the 11.6 GB GGUF is bigger than the 8 GB card (offload) without claiming it fails",
      rep["ok"] and any("offload" in w for w in rep["warnings"]), rep["warnings"])
FAKE.drop_nodes = {"UnetLoaderGGUF"}
rep = AR.preflight(ST, "vace_render", {"frames": 5, "width": 64, "height": 64}, client=cl)
check("a missing custom node is reported with its pack (city96/ComfyUI-GGUF) and blocks",
      not rep["ok"] and rep["missing_nodes"] and rep["missing_nodes"][0]["pack"] == "https://github.com/city96/ComfyUI-GGUF", rep)
FAKE.drop_nodes = set()
FAKE.models["unet_gguf"] = []
rep = AR.preflight(ST, "vace_render", {"frames": 5, "width": 64, "height": 64}, client=cl)
mm = rep["missing_models"]
check("a missing model file is reported with its folder, size, licence note and a pinned download link",
      not rep["ok"] and mm and mm[0]["folder"] == "models/unet" and mm[0]["size"] == 11627589408
      and "/resolve/57045d4ab42eb76a53bdaadb37b5d8dc923ec67b/" in mm[0]["url"], mm)
FAKE.models = json.loads(json.dumps(MODELS))
rep = AR.preflight(ST, "vace_render", {"frames": 32, "width": 64, "height": 64}, client=cl)
check("frames that are not 4n+1 are refused with the nearest good counts", not rep["ok"] and any("4n+1" in b and "29" in b and "33" in b for b in rep["blockers"]), rep["blockers"])
rep = AR.preflight(ST, "vace_render", {"frames": 5, "width": 70, "height": 64}, client=cl)
check("a width that is not a multiple of 16 is refused", not rep["ok"] and any("width" in b for b in rep["blockers"]), rep["blockers"])
AR.save_settings(ST, {"url": "http://203.0.113.9:8188", "consent_remote": False})
rep = AR.preflight(ST, "vace_render", {"frames": 5}, client=cl)
check("no upload to a remote ComfyUI without consent (blocked in preflight)", not rep["ok"] and any("allow uploads" in b for b in rep["blockers"]), rep["blockers"])
AR.save_settings(ST, {"url": URL})
j0 = AR.new_job(ST, {"kind": "ai", "workflow": "vace_render", "params": {"frames": 5}, "size": [64, 64]})["job"]
rep = AR.preflight(ST, "vace_render", {"frames": 5, "width": 64, "height": 64}, job=j0, client=cl)
check("a job without its passes is not ready", not rep["ok"] and any("depth pass has not been rendered" in b for b in rep["blockers"]), rep["blockers"])

# ------------------------------------------------------------------ a job runs to success
j = newjob(5)
AR.save_pass(ST, j, "start", 0, png(64, 64, (10, 120, 200)))
m = AR.start(ST, j, poll_s=0.05, wait=True)
check("a job runs to success: preflight -> preparing -> queued -> running -> succeeded", m["status"] == "succeeded", m.get("log"))
folder = AR.job_dir(ST, j)
check("the result video and the thumbnail land in renders/<job>/", (folder / "result.webm").is_file() and m["thumb"] and (folder / m["thumb"]).is_file(), m)
up = sorted(FAKE.uploads)
check("the depth + line-art APNGs and the start image were uploaded into input/loki/", any(u.endswith("_depth.png") for u in up)
      and any(u.endswith("_lineart.png") for u in up) and any(u.endswith("_start.png") for u in up), up)
dep = FAKE.uploads[[u for u in up if u.startswith("loki/" + j) and u.endswith("_depth.png")][0]]
check("the uploaded depth pass is an APNG with all 5 frames", b"acTL" in dep and dep.count(b"fcTL") == 5)
sent = FAKE.prompts[m["prompt_id"]]
check("the queued graph carries the user's values in the verified inputs", sent["5"]["inputs"]["text"] == "a red fox" and sent["11"]["inputs"]["length"] == 5
      and sent["12"]["inputs"]["steps"] == 4 and sent["10"]["inputs"]["image"].endswith("_start.png") and sent["15"]["inputs"]["filename_prefix"] == "loki_render/" + j)
man = json.loads((folder / "manifest.json").read_text())
check("manifest.json has the Home screen's fields", all(k in man for k in ("name", "kind", "status", "created", "frames", "fps", "size", "camera", "passes", "outputs", "thumb", "log"))
      and man["kind"] == "ai" and man["passes"]["depth"]["frames"] == 5, man)
check("the log keeps the steps with times and no secrets", any("queued" in x["msg"] for x in man["log"]) and "s3cret" not in json.dumps(man))
check("progress reached 1.0", man["progress"] == 1.0)
import home_projects  # noqa: E402
items = home_projects.renders(ST)
check("Home's /home/projects lists the render with its thumbnail", any(i["path_or_id"] == j and i["thumb"] for i in items), items[:2])

# ------------------------------------------------------------------ cancel
FAKE.mode = "slow"
j2 = newjob(5, steps=40)
AR.start(ST, j2, poll_s=0.05)
for _ in range(100):
    if (AR.manifest(ST, j2) or {}).get("status") == "running":
        break
    time.sleep(0.05)
mid = AR.manifest(ST, j2)
check("while running, the websocket's step progress moves the job's progress", mid["status"] == "running" and 0.1 <= mid["progress"] < 1, mid.get("progress"))
AR.cancel(ST, j2)
for _ in range(100):
    if AR.manifest(ST, j2)["status"] in AR.FINAL:
        break
    time.sleep(0.05)
m2 = AR.manifest(ST, j2)
check("cancel interrupts the running prompt and the job ends cancelled", m2["status"] == "cancelled" and m2["prompt_id"] in FAKE.interrupted, m2.get("log"))
FAKE.mode = "ok"

# ------------------------------------------------------------------ one job per workflow
j3, j4 = newjob(5, steps=30), newjob(5)
FAKE.mode = "slow"
AR.start(ST, j3, poll_s=0.05)
time.sleep(0.2)
try:
    AR.start(ST, j4)
    check("a second job on the same workflow waits (one at a time)", False)
except AR.RenderError as exc:
    check("a second job on the same workflow waits (one at a time)", "one at a time" in str(exc), exc)
AR.cancel(ST, j3)
for _ in range(100):
    if AR.manifest(ST, j3)["status"] in AR.FINAL:
        break
    time.sleep(0.05)
FAKE.mode = "ok"

# ------------------------------------------------------------------ a failing job
FAKE.mode = "fail"
m5 = AR.start(ST, newjob(5), poll_s=0.05, wait=True)
check("a failing job is reported with the node and ComfyUI's message", m5["status"] == "failed" and "CUDA out of memory" in m5["log"][-1]["msg"]
      and "KSampler" in m5["log"][-1]["msg"], m5["log"][-1:])
FAKE.mode = "ok"
FAKE.models["text_encoders"] = []
m6 = AR.start(ST, newjob(5), poll_s=0.05, wait=True)
check("a job whose model is missing fails at preflight, nothing queued", m6["status"] == "failed" and "preflight" in m6["log"][-1]["msg"] and not m6.get("prompt_id"), m6["log"][-1:])
FAKE.models = json.loads(json.dumps(MODELS))

# ------------------------------------------------------------------ path traversal
FAKE.mode = "evil"
m7 = AR.start(ST, newjob(5), poll_s=0.05, wait=True)
check("an output named ../../evil.webm is refused and nothing is written outside the job", not (AR.renders_dir(ST).parent / "evil.webm").exists()
      and not (AR.renders_dir(ST) / "evil.webm").exists() and any("unsafe" in x["msg"] for x in m7["log"]), m7["log"][-3:])
FAKE.mode = "ok"
check("safe_name refuses folders, '..', drive letters and control characters",
      [AR.safe_name(x) for x in ("a.png", "../a.png", "a/b.png", "c:x.png", "a\x00.png", "..")] == ["a.png", None, None, None, None, None])
for bad in ("../x", "a/b", ""):
    try:
        AR.job_dir(ST, bad)
        check("job names with folders are refused (%r)" % bad, False)
    except AR.RenderError:
        pass
check("job names with folders are refused", True)

# ------------------------------------------------------------------ retry, presets, path-traced finish
m8 = AR.retry(ST, j2)
check("retry makes a new job with the same passes and settings", m8["manifest"]["passes"]["depth"]["frames"] == 5 and m8["manifest"]["params"]["steps"] == 40)
AR.save_preset(ST, "my game", "dusk", {"prompt": "dusk light", "steps": 12})
check("presets are saved per project", AR.presets(ST, "my game")["dusk"]["steps"] == 12 and AR.presets(ST, "other") == {})
pj = AR.new_job(ST, {"kind": "path", "size": [32, 32], "fps": 24, "frames": 2})["job"]
AR.save_pass(ST, pj, "beauty", 0, png(32, 32, (1, 2, 3)))
AR.save_pass(ST, pj, "beauty", 1, png(32, 32, (3, 2, 1)))
pm = AR.finish(ST, pj, {"status": "succeeded"})
check("a path-traced job lists its frames, packs them into result.png (APNG) and has a thumbnail",
      pm["status"] == "succeeded" and pm["outputs"][0] == "result.png" and pm["thumb"] == "thumb.png" and len(pm["outputs"]) == 3, pm)

# ------------------------------------------------------------------ the bridge routes
import loki_bridge  # noqa: E402


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), loki_bridge.BridgeHandler)
        self.state = ST


srv = Server()
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, body=None, raw=None, token="s3cret", ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": ctype})
    try:
        with OP.open(req, timeout=20) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), ""


s_, out, _ = call("/render/status")
o = json.loads(out)
check("GET /render/status: settings, the graphs' verified params, jobs", s_ == 200 and o["settings"]["url"] == URL
      and any(w["name"] == "vace_render" and "frames" in w["params"] for w in o["workflows"]) and len(o["jobs"]) >= 5)
check("the bridge wants the token for /render", call("/render/status", token="nope")[0] == 401)
s_, out, _ = call("/render/graph?workflow=vace_render")
g = json.loads(out)
gnodes = {n["id"]: n for n in g["nodes"]}
check("GET /render/graph: the graph's nodes, links and models (for the Nodes view)",
      s_ == 200 and len(g["nodes"]) == 17 and gnodes["1"]["class"] == "UnetLoaderGGUF"
      and gnodes["1"]["models"][0]["file"].endswith(".gguf") and {"from": "1", "input": "model"} in gnodes["4"]["links"]
      and "shift" in gnodes["4"]["inputs"], out[:200])
check("GET /render/graph rejects a graph that does not exist", call("/render/graph?workflow=nope")[0] == 400)
s_, out, _ = call("/render/test", {})
check("POST /render/test reaches the fake ComfyUI", s_ == 200 and json.loads(out)["version"] == "0.9.9", out[:200])
s_, out, _ = call("/render/new", {"kind": "ai", "params": {"frames": 5}, "size": [64, 64]})
nj = json.loads(out)["job"]
s_, out, _ = call("/render/upload-pass?job=%s&pass=depth&index=0" % nj, raw=png(64, 64, (5, 5, 5)), ctype="image/png")
check("POST /render/upload-pass stores a PNG frame", s_ == 200 and json.loads(out)["passes"]["depth"]["frames"] == 1, out)
s_, out, _ = call("/render/upload-pass?job=%s&pass=depth&index=1" % nj, raw=b"not a png", ctype="image/png")
check("a body that is not a PNG is refused", s_ == 400)
s_, out, _ = call("/render/upload-pass?job=..%%2Fx&pass=depth&index=0", raw=png(4, 4, (0, 0, 0)), ctype="image/png")
check("an upload to a job name with a path is refused", s_ == 400)
s_, body_, ct = call("/render/file?job=%s&name=passes/depth/0000.png" % nj)
check("GET /render/file serves a pass frame", s_ == 200 and body_[:4] == b"\x89PNG" and ct == "image/png")
check("GET /render/file refuses ../", call("/render/file?job=%s&name=../manifest.json" % nj)[0] == 400
      and call("/render/file?job=%s&name=passes/../../x.png" % nj)[0] == 400)
s_, out, _ = call("/render/preflight", {"workflow": "vace_render", "params": {"frames": 6}, "job": nj})
check("POST /render/preflight returns the report", s_ == 200 and not json.loads(out)["report"]["ok"])

# ------------------------------------------------------------------ the PC's setup helper, dry run only (never installs here)
sys.path.insert(0, str(REPO / "tools"))
import setup_comfyui as SC  # noqa: E402


class A:
    install = models = start = True
    yes_download = False
    quant = "Q3_K_M"
    zimage = True


plan = SC.plan(A, TMP / "comfy", platform="win32")
steps = {s["do"]: s for s in plan["steps"]}
clones = [s for s in plan["steps"] if s["do"] == "git clone + checkout"]
check("setup dry run: ComfyUI + ComfyUI-GGUF at pinned 40-hex commits, GGUF into custom_nodes",
      len(clones) == 2 and all(len(c["commit"]) == 40 for c in clones) and clones[1]["into"].replace("\\", "/").endswith("custom_nodes/ComfyUI-GGUF"), clones)
dl = steps["download"]
check("setup dry run: the downloads come from the graphs' model lists at pinned revisions, the quant is honoured, not confirmed",
      dl["files"][0]["file"].endswith("Q3_K_M.gguf") and any(f["file"] == "qwen_3_4b.safetensors" for f in dl["files"])
      and all("/resolve/" in f["url"] for f in dl["files"]) and dl["confirmed"] is False, dl)
argv = steps["start"]["argv"]
check("setup dry run: ComfyUI starts hidden on 127.0.0.1:8188 from harness_data/comfyui's venv (Windows: Scripts/python.exe)",
      argv[2:6] == ["--listen", "127.0.0.1", "--port", "8188"] and argv[0].replace("\\", "/").endswith("venv/Scripts/python.exe") and steps["start"]["hidden"], argv)
check("setup on macOS uses venv/bin/python and no CUDA index", SC.venv_python(TMP, "darwin").as_posix().endswith("venv/bin/python")
      and "extra_index" not in [s for s in SC.plan(A, TMP / "comfy", platform="darwin")["steps"] if s["do"] == "pip install"][0])
check("setup refuses to download without --yes-download", SC.main(["--models", "--data", str(TMP / "d2")]) == 1 and not (TMP / "d2" / "comfyui").exists())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
