"""LOKI's ComfyUI-native makers (engine/comfy_jobs.py): music with ACE-Step 1.5 from Comfy Org's MIT template, against
a fake ComfyUI over HTTP that checks the graph like ComfyUI does. Offline, a few seconds.

    python tests/test_comfy_jobs.py
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-cjobs-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import comfy_jobs as cj  # noqa: E402
import comfy_workflow as cw  # noqa: E402

INFO = json.loads((REPO / "tests" / "fixtures" / "comfy_audio_object_info.json").read_text())
UI = json.loads((REPO / "engine" / "forge_workflows" / "ui" / "audio_ace_step_1_5_split.json").read_text())
WF = cj.graph("music")
fresh = cw.prune(cw.ui_to_api(UI, INFO), ["107"])
check("the music graph converts from Comfy Org's template, every widget accounted for", len(fresh) == 10)
check("a UI-only Primitive feeding a widget keeps the widget's value (seconds, seed)",
      fresh["98"]["inputs"]["seconds"] == 120 and fresh["94"]["inputs"]["duration"] == 120 and fresh["3"]["inputs"]["seed"] == 31)
check("a dynamic combo (mp3 + quality) and both text encoders come through",
      fresh["107"]["inputs"]["format"] == "mp3" and fresh["107"]["inputs"]["format.quality"] == "V0"
      and {f[3] for f in cw.loaders(fresh) if f[1] == "DualCLIPLoader"} == {"qwen_0.6b_ace15.safetensors", "qwen_1.7b_ace15.safetensors"})
g = cj.build("music", {"tags": "chiptune boss fight", "seconds": 45, "seed": 7, "bpm": 150, "key": "A minor"})
check("parameters land on every node they belong to", g["94"]["inputs"]["tags"] == "chiptune boss fight"
      and g["98"]["inputs"]["seconds"] == 45 and g["94"]["inputs"]["duration"] == 45 and g["3"]["inputs"]["seed"] == 7
      and g["94"]["inputs"]["seed"] == 7 and g["94"]["inputs"]["bpm"] == 150 and g["94"]["inputs"]["keyscale"] == "A minor")
check("the model files come with their Hugging Face URLs and folders", len(WF["models"]) == 4
      and all(m["url"].startswith("https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/") for m in WF["models"]))
STATE = {"info": copy.deepcopy(INFO), "prompt": None}
MP3 = b"ID3\x04fake-mp3"


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj=None, raw=None, code=200):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/system_stats":
            return self._send({})
        if self.path == "/object_info":
            return self._send(STATE["info"])
        if self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[1]
            if not STATE["prompt"]:
                return self._send({})
            return self._send({pid: {"status": {"status_str": "success", "completed": True},
                                     "outputs": {"107": {"audio": [{"filename": "music_00001_.mp3", "subfolder": "loki", "type": "output"}]}}}})
        if self.path.startswith("/view?"):
            return self._send(raw=MP3)
        return self._send({}, code=404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["prompt"] = body["prompt"]
        probs = cw.missing_nodes(body["prompt"], STATE["info"]) + [m["file"] for m in cw.check_models(body["prompt"], STATE["info"])]
        if probs:
            return self._send({"error": "bad", "node_errors": {"x": probs}}, code=400)
        return self._send({"prompt_id": body["prompt_id"], "node_errors": {}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["LOKI_COMFYUI_URL"] = "http://127.0.0.1:%d" % srv.server_address[1]
import forge_trellis  # noqa: E402
forge_trellis.forget_cache()
st = cj.status("music")
check("status: reachable and ready", st["reachable"] and st["ready"], st)
ws = TMP / "ws"
res = cj.make_music({"tags": "cozy farming game theme, acoustic guitar, flute", "seconds": 30}, ws / "audio", sleep=lambda s: None)
check("make_music: an instrumental MP3 lands in audio/", res.get("ok") and Path(res["files"][0]).read_bytes() == MP3
      and STATE["prompt"]["94"]["inputs"]["lyrics"] == "[Instrumental]" and STATE["prompt"]["98"]["inputs"]["seconds"] == 30, res)
res = cj.make_music({"tags": "pop", "lyrics": "[Chorus]\nla la", "seconds": 999}, ws / "audio", sleep=lambda s: None)
check("lyrics are sung; the length is kept to 240 s", res["ok"] and STATE["prompt"]["94"]["inputs"]["lyrics"].startswith("[Chorus]")
      and STATE["prompt"]["98"]["inputs"]["seconds"] == 240 and Path(res["files"][0]).name.endswith("-2.mp3"), res)
STATE["info"]["UNETLoader"]["input"]["required"]["unet_name"] = [["other.safetensors"]]
forge_trellis.forget_cache()
res = cj.make_music({"tags": "x"}, ws / "audio", sleep=lambda s: None)
check("a missing model is named, nothing is queued for nothing", not res["ok"] and "acestep_v1.5_turbo" in res["error"], res)
check("no tags: says what it needs", not cj.make_music({}, ws)["ok"])
import make_mcp  # noqa: E402
check("the agents get make_music and loki-make music", any(t["name"] == "make_music" for t in make_mcp.TOOLS)
      and make_mcp.CLI["music"] == "make_music")
srv.shutdown()
srv.server_close()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
