"""Professional pictures for the art team (owner 2026-10-25: "this poli img gen is bad... it should be professional").

engine/runners/imagegen.py: FLUX on NVIDIA's hosted API (the NVIDIA key LOKI already has: FLUX.2 [klein] first, the
next model on a 404, FLUX.1 sizes snapped) and on Hugging Face (HF_TOKEN) come before Pollinations, which is now the
last resort. engine/art_direction.py: style presets (an art director's finish + negative prompt) and Real-ESRGAN
upscaling. make_image says when Pollinations made it. Faked network, under a minute.

    python tests/test_image_pro.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "engine" / "runners"))
TMP = Path(tempfile.mkdtemp(prefix="loki-imgpro-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
for k in ("NVIDIA_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY", "MODELSCOPE_API_KEY", "LOKI_IMAGE_BACKEND"):
    os.environ.pop(k, None)
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import art_direction  # noqa: E402
import imagegen  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
imagegen.local_status = lambda: ("sdcpp", False, "not installed")
imagegen.zimage_status = lambda: (False, "not installed")
check("no keys: Pollinations only (and why the others are skipped)", imagegen.plan_order()["order"] == ["pollinations"]
      and "nvidia" in imagegen.plan_order()["skipped"])
os.environ["NVIDIA_API_KEY"] = "nvapi-test"
os.environ["HF_TOKEN"] = "hf_test"
order = imagegen.plan_order()["order"]
check("with the NVIDIA key and HF_TOKEN: nvidia, huggingface, then Pollinations last", order == ["nvidia", "huggingface", "pollinations"], order)

asked = []


def fake_request(url, key, body=None, headers=None, timeout=60):
    asked.append((url, body))
    if "flux.2-klein" in url:
        raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
    return {"artifacts": [{"base64": base64.b64encode(PNG).decode(), "finishReason": "SUCCESS", "seed": 7}]}


r = imagegen.nvidia("a lighthouse in a storm", 1280, 720, str(TMP / "out"), 7, request=fake_request)
check("NVIDIA: FLUX.2 [klein] tried first, a 404 -> FLUX.1 [dev], the picture saved", [u.rsplit("/", 2)[-2] + "/" + u.rsplit("/", 1)[-1] for u, _ in asked]
      == ["black-forest-labs/flux.2-klein-4b", "black-forest-labs/flux.1-dev"] and Path(r["file"]).read_bytes() == PNG
      and r["model"] == "black-forest-labs/flux.1-dev", (asked, r))
check("... FLUX.1 gets the nearest size it takes (16:9 -> 1344x768) and dev settings", asked[1][1]["width"] == 1344 and asked[1][1]["height"] == 768
      and asked[1][1]["cfg_scale"] == 3.5 and asked[1][1]["steps"] == 30, asked[1][1])
check("... the key goes as a Bearer token to ai.api.nvidia.com", asked[0][0].startswith("https://ai.api.nvidia.com/v1/genai/"))


def filtered(url, key, body=None, headers=None, timeout=60):
    return {"artifacts": [{"base64": "", "finishReason": "CONTENT_FILTERED"}]}


try:
    imagegen.nvidia("x", 1024, 1024, str(TMP / "out"), 1, request=filtered)
    check("a filtered picture is an error, not an empty file", False)
except RuntimeError as exc:
    check("a filtered picture is an error, not an empty file", "filter" in str(exc), exc)


class Resp(io.BytesIO):
    def __init__(self, data, kind):
        super().__init__(data)
        self.headers = {"Content-Type": kind}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


hf_asked = []


def hf_open(req, timeout=0):
    hf_asked.append((req.full_url, json.loads(req.data), req.headers.get("Authorization")))
    return Resp(PNG, "image/png")


r = imagegen.huggingface("a red fox, watercolor", 1024, 768, str(TMP / "out"), 3, opener=hf_open)
check("Hugging Face: FLUX.1 [dev] through the router, the picture saved", hf_asked[0][0].endswith("/hf-inference/models/black-forest-labs/FLUX.1-dev")
      and hf_asked[0][1]["parameters"]["width"] == 1024 and hf_asked[0][2] == "Bearer hf_test" and Path(r["file"]).read_bytes() == PNG, hf_asked)

p, neg = art_direction.direct("a knight at the gate", "oil-painting")
check("style oil-painting: the brief kept, a painter's finish added, a negative prompt", p.startswith("a knight at the gate.")
      and "brushstrokes" in p and "blurry" in neg and "photo" in neg, (p, neg))
check("no style: the prompt as written", art_direction.direct("a knight", "") == ("a knight", ""))
check("presets for comics, novels' covers, concept art, product shots, textures ...",
      all(k in art_direction.STYLES for k in ("comic", "book-cover", "concept-art", "product", "texture", "photo")))

# upscale with a stand-in Real-ESRGAN that writes the output file
src = TMP / "out" / "fox.png"; src.write_bytes(PNG)
art_direction.find_upscaler = lambda: "/fake/realesrgan-ncnn-vulkan"
runs = []


def fake_run(cmd, **kw):
    runs.append(cmd)
    Path(cmd[cmd.index("-o") + 1]).write_bytes(PNG)
    return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()


r = art_direction.upscale(str(src), 4, anime=True, run=fake_run)
check("upscale 4x: Real-ESRGAN with the anime model for drawn art, fox-4x.png beside it", r["ok"] and r["file"].endswith("fox-4x.png")
      and "realesrgan-x4plus-anime" in runs[0] and runs[0][runs[0].index("-i") + 1] == str(src), (r, runs))

# make_image: style and the Pollinations note
import make_mcp  # noqa: E402
jobs = []


def fake_imagegen(job, runner=None):
    jobs.append(job)
    f = Path(job["out_dir"]) / "a.png"; f.write_bytes(PNG)
    return {"ok": True, "file": str(f), "files": [str(f)], "backend": "pollinations", "seed": 1}


make_mcp.run_imagegen = fake_imagegen
ws = TMP / "ws"; ws.mkdir()
r = make_mcp.make_image({"prompt": "a dragon over a city", "style": "comic"}, ws)
check("make_image style=comic: the prompt gets the comic finish and its negative", "bold clean inks" in jobs[0]["prompt"]
      and "blurry lines" in jobs[0]["negative"], jobs[0])
check("... and says plainly when Pollinations (the weak fallback) made it", "Pollinations" in r.get("note", ""), r)
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
