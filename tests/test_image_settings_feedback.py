"""Picture settings + thumbs up / down (owner 2026-10-26: "give me a way to tell them the images are bad with a thumbs
down ... images should be very technical lots of settings to adjust what size and pixel we want ... everything should be
modular"). Offline: the image maker is faked; real files, real sidecars, real pipeline.

    python tests/test_image_settings_feedback.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-imgset-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
WS = TMP / "ws"
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


from PIL import Image  # noqa: E402

import image_settings as st  # noqa: E402
import image_feedback as fb  # noqa: E402
import image_api  # noqa: E402
import creations  # noqa: E402

# ---- settings: one list, clamped, model-aware
keys = [s["key"] for s in st.schema()]
check("one settings list: size, quality, variation, look, output, engine", {"aspect", "megapixels", "width", "height", "steps",
      "guidance", "sampler", "seed", "count", "strength", "from_picture", "style", "negative", "upscale", "pixel_size",
      "palette", "backend"} <= set(keys), keys)
check("every setting says what it does and which models honour it", all(s.get("what") and s.get("honoured") for s in st.schema()))
check("the style list is filled from art_direction", "game-concept" in next(s for s in st.schema() if s["key"] == "style")["options"])
check("16:9 at 1 MP -> 1360x768 (multiples of 16)", st.size_for("16:9", 1.0) == (1360, 768), st.size_for("16:9", 1.0))
check("2:3 at 0.5 MP", st.size_for("2:3", 0.5) == (592, 880) or all(v % 16 == 0 for v in st.size_for("2:3", 0.5)))
job, notes = st.normalize({"width": 5000, "height": 333, "steps": 200, "seed": 42, "sampler": "dpm++2m", "backend": "sdcpp"})
check("numbers are clamped and said so; exact pixels win", job["width"] == 2048 and job["height"] == 336 and job["steps"] == 60
      and job["sampler"] == "dpm++2m" and any("lowered" in n for n in notes), (job, notes))
job, notes = st.normalize({"aspect": "3:4", "megapixels": 1, "sampler": "euler", "guidance": 4, "negative": "text",
                           "backend": "nvidia"})
check("a hosted model: settings it ignores are left out and named (sampler, guidance, negative)",
      "sampler" not in job and "guidance" not in job and "negative" not in job and any("nvidia ignores" in n for n in notes),
      (job, notes))
check("a bad option is refused with the choices", any("not one of" in n for n in st.normalize({"palette": "neon"})[1]))

# ---- the runner gets them (engine/runners/imagegen.py, engine/creative.py)
import creative  # noqa: E402
argv = creative.sdcpp_argv("sd", "zimage-q4", "a fox", "", 1024, 1024, 7, Path("o.png"), steps=20, cfg=3.5,
                           sampler="dpm++2m", init_image="in.png", strength=0.4)
check("sd.cpp gets steps, CFG, sampler and image-to-image", argv[argv.index("--steps") + 1] == "20"
      and argv[argv.index("--cfg-scale") + 1] == "3.5" and argv[argv.index("--sampling-method") + 1] == "dpm++2m"
      and argv[argv.index("-i") + 1] == "in.png" and argv[argv.index("--strength") + 1] == "0.40", argv)
argv = creative.mflux_argv("mflux", "m", "a fox", 768, 1024, 7, Path("o.png"), steps=12, guidance=2.5, init_image="in.png",
                           strength=0.3)
check("mflux gets steps, guidance and a starting picture (keep = 1 - change)", argv[argv.index("--steps") + 1] == "12"
      and argv[argv.index("--guidance") + 1] == "2.50" and argv[argv.index("--image-strength") + 1] == "0.70", argv)
argv = creative.mflux_edit_argv("mflux-generate-flux2-edit", ["c.png", "f.png"], "side view", 768, 1024, 9, Path("o.png"))
check("a turnaround view on the Mac: FLUX.2 klein 4B edit (Apache-2.0) with the concept + front as references, -q 8",
      argv[argv.index("--model") + 1] == "flux2-klein-4b" and argv[argv.index("-q") + 1] == "8"
      and argv[argv.index("--image-paths") + 1:argv.index("--image-paths") + 3] == ["c.png", "f.png"] and "--low-ram" in argv, argv)
sys.path.insert(0, str(REPO / "engine" / "runners"))
import imagegen  # noqa: E402
pic = WS / "images" / "fox_20261026-1900.png"
pic.parent.mkdir(parents=True)
from PIL import ImageDraw  # noqa: E402
im = Image.new("RGB", (1600, 1200), (210, 210, 210))
ImageDraw.Draw(im).ellipse((400, 200, 1200, 1100), fill=(180, 90, 40))
im.save(pic)
urls = imagegen.reference_data_urls([pic])
check("a reference goes to the hosted model as a small JPEG data URL", urls[0].startswith("data:image/jpeg;base64,")
      and len(urls[0]) < 200_000, len(urls[0]))
sent = {}


def fake_request(url, key, body, headers, timeout):
    sent.update(body=body, url=url)
    import base64
    return {"artifacts": [{"base64": base64.b64encode(pic.read_bytes()).decode(), "finishReason": "SUCCESS"}]}


os.environ["NVIDIA_API_KEY"] = "test"
imagegen.NVIDIA_IMAGE_MODELS[:] = ["black-forest-labs/flux.2-klein-4b"]
r = imagegen.nvidia("side view", 768, 1024, str(TMP / "out"), 5, request=fake_request,
                    extra={"reference": [str(pic)], "steps": 6})
check("FLUX.2 klein on NVIDIA edits with the reference ('image' list) and the asked steps",
      sent["body"]["image"][0].startswith("data:image/jpeg") and sent["body"]["steps"] == 6 and r["reference"], sent.get("body", {}).keys())
os.environ.pop("NVIDIA_API_KEY")

# ---- thumbs up / down
creations.write_meta(WS, "images/fox_20261026-1900.png", prompt="a red fox", style="game-concept", backend="nvidia",
                     model="flux.2-klein-4b")
r = fb.rate(WS, "images/fox_20261026-1900.png", -1, ["text", "perspective", "nonsense"], "letters on the side")
meta = creations.read_meta(WS, "images/fox_20261026-1900.png")
check("thumbs down: kept with the known reasons (unknown ones dropped) and in the picture's sidecar",
      r["ok"] and r["reasons"] == ["text", "perspective"] and meta.get("rating") == -1 and meta.get("liked") is False, (r, meta))
check("... and it is remembered", fb.rating_of(WS, "images/fox_20261026-1900.png") == -1)
check("the reasons become words in the next prompt for that folder", "no text" in fb.hints(WS, "images")
      and "orthographic" in fb.hints(WS, "images"), fb.hints(WS, "images"))
fb.rate(WS, "images/fox_20261026-1900.png", 1)
check("a later thumbs up replaces it and stars the picture", fb.rating_of(WS, "images/fox_20261026-1900.png") == 1
      and creations.read_meta(WS, "images/fox_20261026-1900.png").get("liked") is True)
p = fb.preferences(WS)
check("preferences: liked / disliked per style and model", p["liked"] == 1 and p["style"]["game-concept"]["up"] == 1, p)
check("a picture outside the workspace cannot be rated", not fb.rate(WS, "../etc/passwd", -1)["ok"])
check("thumbs-down hints reach make_image (engine/make_mcp.py)",
      "image_feedback.hints" in (REPO / "engine" / "make_mcp.py").read_text())

# a thumbs down on a pipeline output sends that stage back
import asset_pipeline as ap  # noqa: E402
a = ap.start(WS, "a red fox", kind="creature", concept="images/fox_20261026-1900.png")
out = fb.rate(WS, "images/fox_20261026-1900.png", -1, ["match"])
s = ap.summary(ap.load(WS, a["id"]))
check("thumbs down on an approved pipeline concept -> a retake note: the concept is redone with the reason",
      out.get("retake", {}).get("stage") == "concept" and s["concept"] == "ready" and s["turnaround"] == "waiting"
      and "does not match" in ap.notes(WS, a["id"], "concept")[0]["text"], (out, s))
check("... and the concept stage gets a lesson", any("rejected" in x["text"] for x in ap.recall("concept", "creature")))

# ---- routes
state = types.SimpleNamespace(agent=types.SimpleNamespace(WORKSPACE=str(WS)))
code, out = image_api.route(state, "GET", "/image/settings", {}, {})
check("GET /image/settings: the list the viewer draws itself from", code == 200 and len(out["settings"]) >= 15)
code, out = image_api.route(state, "GET", "/image/info", {"path": "images/fox_20261026-1900.png"}, {})
check("GET /image/info: size, prompt, rating", code == 200 and out["size"] == [1600, 1200] and out["meta"]["prompt"] == "a red fox"
      and out["rating"] == -1, out)
code, out = image_api.route(state, "POST", "/image/rate", {}, {"path": "images/fox_20261026-1900.png", "rating": 1})
check("POST /image/rate", code == 200 and out["rating"] == 1)
made = {}


def fake_maker(args, cwd):
    made.update(args)
    f = Path(cwd) / "images" / "fox_20261026-1901.png"
    Image.new("RGB", (args["width"], args["height"]), (1, 2, 3)).save(f)
    return {"ok": True, "files": ["images/fox_20261026-1901.png"], "backend": "mflux", "seed": args.get("seed")}


r = image_api.remake(WS, "images/fox_20261026-1900.png", {"aspect": "9:16", "megapixels": 0.5, "steps": 12, "seed": 99,
                                                          "from_picture": True, "strength": 0.3}, maker=fake_maker, thread=False)
j = image_api.JOBS[r["job"]]
check("remake: this picture's own prompt + the settings (size from aspect, steps, seed, start from the picture)",
      j["status"] == "done" and made["prompt"] == "a red fox" and made["width"] < made["height"] and made["steps"] == 12
      and made["seed"] == 99 and made["reference"] == ["images/fox_20261026-1900.png"], (j, made))
check("... the new picture remembers its parent and settings", creations.read_meta(WS, "images/fox_20261026-1901.png").get("parent")
      == "images/fox_20261026-1900.png" and creations.read_meta(WS, "images/fox_20261026-1901.png")["settings"]["steps"] == 12)
check("unknown picture -> 404", image_api.route(state, "POST", "/image/remake", {}, {"path": "images/nope.png"})[0] == 404)
bridge = (REPO / "engine" / "loki_bridge.py").read_text()
check("the bridge serves them", '"/image/remake", "/image/rate"' in bridge and '"/image/settings", "/image/info"' in bridge)

# ---- the turnaround check now also wants the views to line up
ctx = {"stage": ap.BY_NAME["turnaround"], "outputs": [], "report": {"views": {"front": 1, "side": 1, "back": 1},
       "silhouette": {"front": [0.8, 0.0], "side": [0.55, 0.01], "back": [0.79, 0.0]}}}
ok, detail, _ = ap.check_views(ctx)
check("a side view at 69% of the front's height fails (views must line up for 3D)", not ok and "side height" in detail, detail)
ctx["report"]["silhouette"]["side"] = [0.78, 0.0]
ctx["report"]["colour_match"] = {"front": 0.9, "side": 0.2}
ok, detail, _ = ap.check_views(ctx)
check("a view whose colours do not match the concept fails (red dragon -> grey)", not ok and "colours" in detail, detail)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
