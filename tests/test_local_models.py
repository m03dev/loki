"""Settings > Local models lists every model downloaded on this computer and removes one (engine/local_models.py,
app/ui/local_models.js; owner 2026-10-25: "i should be able to see what models i have downloaded and i can uninstall
them from my system from loki in that local tab").

Engine: a fake Ollama (its /api/tags, /api/ps, /api/delete) with the owner's two models and LOKI's long-context copy;
a Hugging Face cache and LOKI's image-model folder in a temp dir. Remove deletes the Ollama model AND LOKI's copy of it
(same files), a cache folder for real, and nothing outside those folders. Window: the list, "in use", Remove asks in
the row, then the list refreshes. Under a minute.

    python tests/test_local_models.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-localmodels-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["HF_HUB_CACHE"] = str(TMP / "hf")
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


MODELS = {"huihui_ai/qwen3.5-abliterated:9b": 6.6, "huihui_ai/qwen3-vl-abliterated:8b": 6.1,
          "loki-huihui_ai-qwen3.5-abliterated-9b:latest": 6.6}
DELETED: list = []


class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/tags":
            return self._send({"models": [{"name": n, "size": int(g * 2**30), "details": {"parameter_size": "9B" if "9b" in n else "8B",
                                                                                         "quantization_level": "Q4_K_M"}} for n, g in MODELS.items()]})
        if self.path == "/api/ps":
            return self._send({"models": [{"name": "loki-huihui_ai-qwen3.5-abliterated-9b:latest"}]})
        self._send({})

    def do_DELETE(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        DELETED.append(body["model"]); MODELS.pop(body["model"], None)
        self._send({})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST_URL"] = "http://127.0.0.1:%d" % srv.server_address[1]

import local_models  # noqa: E402

hub = TMP / "hf" / "models--filipstrand--Z-Image-Turbo-mflux-4bit" / "blobs"; hub.mkdir(parents=True)
(hub / "w.safetensors").write_bytes(b"x" * 2048)
img = local_models.image_dir(); img.mkdir(parents=True, exist_ok=True)
(img / "z_image_turbo-Q4_K.gguf").write_bytes(b"y" * 4096)
outside = TMP / "keep.txt"; outside.write_text("mine")

d = local_models.listing()
names = {m["name"]: m for m in d["models"]}
check("the owner's two Ollama models are listed with size, parameters, quantization", "huihui_ai/qwen3.5-abliterated:9b" in names
      and names["huihui_ai/qwen3.5-abliterated:9b"]["size_gb"] == 6.6 and names["huihui_ai/qwen3.5-abliterated:9b"]["params"] == "9B", names)
check("LOKI's long-context copy is tied to its model (and 'in use')", names["loki-huihui_ai-qwen3.5-abliterated-9b:latest"]["copy_of"]
      == "huihui_ai/qwen3.5-abliterated:9b" and names["loki-huihui_ai-qwen3.5-abliterated-9b:latest"]["loaded"], names)
check("the image model file and the Hugging Face download are listed too", "z_image_turbo-Q4_K.gguf" in names
      and "filipstrand/Z-Image-Turbo-mflux-4bit" in names, list(names))
check("total counts the copy once (it shares the files)", d["total_gb"] == round(6.6 + 6.1 + 4096 / 2**30 + 2048 / 2**30, 1), d["total_gb"])

r = local_models.remove("ollama:huihui_ai/qwen3.5-abliterated:9b")
check("Remove a model: Ollama deletes it AND LOKI's copy of it", sorted(r["removed"]) == sorted(["huihui_ai/qwen3.5-abliterated:9b",
      "loki-huihui_ai-qwen3.5-abliterated-9b:latest"]) and DELETED == r["removed"], (r, DELETED))
r = local_models.remove("hf:models--filipstrand--Z-Image-Turbo-mflux-4bit")
check("Remove a Hugging Face download: its folder is gone", r["ok"] and not hub.parent.exists(), r)
r = local_models.remove("image:z_image_turbo-Q4_K.gguf")
check("Remove an image model file: gone", r["ok"] and not (img / "z_image_turbo-Q4_K.gguf").exists(), r)
for bad in ("hf:../../keep.txt", "image:../../../keep.txt", "ollama:nope"):
    code, r = local_models.route(None, "POST", "/local/models/remove", {}, {"id": bad})
    check("refused, nothing outside the model folders touched: %s" % bad, code == 400 and outside.read_text() == "mine", r)

# ---- the window
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


async def ui():
    state = {"models": [{"id": "ollama:qwen3.5:9b", "kind": "ollama", "name": "qwen3.5:9b", "size_gb": 6.6, "params": "9B", "quant": "Q4_K_M", "loaded": False},
                        {"id": "ollama:loki-qwen3.5-9b", "kind": "ollama", "name": "loki-qwen3.5-9b:latest", "size_gb": 6.6, "copy_of": "qwen3.5:9b", "loaded": True},
                        {"id": "hf:models--a--b", "kind": "hf", "name": "a/b", "size_gb": 2.0}]}
    posts = []
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            print("SKIP window part (%s)" % str(exc)[:80]); return
        page = await b.new_page(viewport={"width": 1300, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8896", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/local/models":
                return await r.fulfill(json={"ok": True, "models": state["models"], "total_gb": 8.6, "free_gb": 40.2})
            if bare == "/local/models/remove":
                posts.append(json.loads(r.request.post_data))
                state["models"] = [m for m in state["models"] if m["id"] == "hf:models--a--b"]
                return await r.fulfill(json={"ok": True, "removed": ["qwen3.5:9b", "loki-qwen3.5-9b:latest"]})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8896/**", route)
        await page.goto("http://127.0.0.1:8896/#token=s")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("openSettings(); showTab('models')")
        await page.wait_for_selector("#lm-downloaded .lm-row", timeout=8000)
        rows = await page.evaluate("[...document.querySelectorAll('#lm-downloaded .lm-row')].map((r) => r.textContent)")
        check("Settings > Local models: a row per downloaded model (LOKI's copy folded into its model's row)", len(rows) == 2
              and "qwen3.5:9b" in rows[0] and "in use" in rows[0] and "long-context copy" in rows[0] and "a/b" in rows[1], rows)
        check("... the total and the free disk space", "40.2 GB free" in await page.inner_text("#lm-downloaded .lm-head"))
        await page.click("#lm-downloaded .lm-row:first-child .lm-remove")
        ask = await page.inner_text("#lm-downloaded .lm-row:first-child .lm-acts")
        check("Remove asks in the row first (size, and LOKI's copy too) - nothing removed yet", "6.6 GB" in ask and "LOKI's copy" in ask and not posts, ask)
        await page.click("#lm-downloaded .lm-row:first-child .lm-acts .danger")
        await page.wait_for_function("document.querySelectorAll('#lm-downloaded .lm-row').length === 1", timeout=5000)
        check("... confirmed: it posts the model and the list refreshes", posts == [{"id": "ollama:qwen3.5:9b"}], posts)
        check("no page errors", not errors, errors)
        await b.close()

if async_playwright:
    asyncio.run(asyncio.wait_for(ui(), 45))
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
