"""Render Studio against a REAL ComfyUI - the checks a fake server cannot make (docs/AI_RENDERER.md, Blocker 3):
the live node schemas against the ones LOKI's graphs assume, and ComfyUI actually READING the multi-frame APNG the
passes are sent as. Skips (0 passed) when no server answers, so it is harmless in CI.

    python tools/setup_comfyui.py --install --start && python tests/test_comfyui_live.py
    LOKI_COMFYUI_URL=http://<pc>:8188 python tests/test_comfyui_live.py
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
import urllib.error
import uuid
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


import ai_renderer as AR  # noqa: E402

FIX = json.loads((REPO / "tests" / "fixtures" / "comfyui_object_info.json").read_text(encoding="utf-8"))["object_info"]


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def live_inputs(schema, cls):
    """Every input name the live server accepts for a class, required and optional."""
    ins = schema.get(cls, {}).get("input", {}) or {}
    return set((ins.get("required") or {}).keys()) | set((ins.get("optional") or {}).keys())


def post_prompt(cl, prompt):
    """POST /prompt keeping the server's own 400 body (the engine turns it into a RenderError with the text in it)."""
    body = json.dumps({"prompt": prompt, "client_id": "loki-live-test", "prompt_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(cl.url + "/prompt", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as exc:
        try:
            return None, json.loads(exc.read().decode("utf-8", "replace"))
        except ValueError:
            return None, {"error": {"message": str(exc)}}


def queue_and_wait(cl, prompt, budget=120.0):
    """Queue a graph and wait for its outputs. Returns (outputs, status_str, node_errors)."""
    pid = str(uuid.uuid4())
    try:
        cl.queue_prompt(prompt, "loki-live-test", pid)
    except AR.RenderError as exc:                 # the engine raises this for the server's 400
        return None, str(exc), {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            err = json.loads(body)
        except ValueError:
            err = {"raw": body[:400]}
        return None, err.get("error", {}).get("message", str(exc)), err.get("node_errors") or {}
    end = time.time() + budget
    while time.time() < end:
        h = cl.history(pid)
        if pid in h:
            ent = h[pid]
            status = (ent.get("status") or {})
            return ent.get("outputs") or {}, status.get("status_str") or "", status.get("messages") or []
        time.sleep(1.0)
    return None, "timeout after %.0fs" % budget, []


def main() -> int:
    url = os.environ.get("LOKI_COMFYUI_URL") or AR.default_url()
    cl = AR.Comfy(url, timeout=20.0)
    try:
        stats = cl.system_stats()
    except Exception as exc:  # noqa: BLE001
        print("SKIP: no ComfyUI at %s (%s)" % (url, str(exc)[:120]))
        print("\n0 passed, 0 failed")
        return 0
    ver = (stats.get("system") or {}).get("comfyui_version") or "?"
    dev = (stats.get("devices") or [{}])[0]
    vram = (dev.get("vram_total") or 0) / (1 << 30)
    print("  ComfyUI %s at %s - %s (%.1f GB VRAM)" % (ver, url, dev.get("name") or "?", vram))
    check("ComfyUI answers /system_stats with a version", bool(ver and ver != "?"))

    try:
        schema = cl.object_info()
    except Exception as exc:  # noqa: BLE001
        check("ComfyUI answers /object_info", False, exc)
        return 1

    # ---- every class and every input LOKI's graphs use must exist on the live server
    missing_cls, missing_in, drift = [], [], []
    for name, wf in AR.workflows().items():
        for nid, node in (wf.get("prompt") or {}).items():
            cls = node.get("class_type")
            if cls not in schema:
                missing_cls.append("%s: %s" % (name, cls))
                continue
            live = live_inputs(schema, cls)
            for k in (node.get("inputs") or {}):
                if k not in live:
                    missing_in.append("%s node %s %s.%s" % (name, nid, cls, k))
            for k, spec in ((schema.get(cls, {}).get("input", {}) or {}).get("required") or {}).items():
                if k not in (node.get("inputs") or {}) and not (isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict) and spec[1].get("default") is not None):
                    drift.append("%s node %s %s: required input %r is not set" % (name, nid, cls, k))
    check("every node class in LOKI's graphs exists on the live server", not missing_cls, missing_cls[:6])
    check("every input LOKI sets exists on the live server (no schema drift)", not missing_in, missing_in[:8])
    check("every input the live server requires is set by LOKI's graphs", not drift, drift[:6])

    # ---- the fixture against the live server: the same required inputs, for the classes LOKI uses
    used = {n.get("class_type") for wf in AR.workflows().values() for n in (wf.get("prompt") or {}).values()}
    diffs = []
    for cls in sorted(used):
        if cls not in schema or cls not in FIX:
            diffs.append("%s: fixture=%s live=%s" % (cls, cls in FIX, cls in schema))
            continue
        fr = set(((FIX[cls].get("input") or {}).get("required") or {}).keys())
        lr = set(((schema[cls].get("input") or {}).get("required") or {}).keys())
        if fr != lr:
            diffs.append("%s: only in fixture %s / only live %s" % (cls, sorted(fr - lr), sorted(lr - fr)))
    check("tests/fixtures/comfyui_object_info.json still matches the live schemas", not diffs, diffs[:6])

    # ---- the model files the graphs name, if they are installed (informational)
    have, want = [], []
    for name, wf in AR.workflows().items():
        for m in (wf.get("models") or []):
            want.append(m.get("file"))
            # the graphs store the folder as "models/unet"; the map keys and ComfyUI's loader classes use the bare name
            bare = (m.get("folder") or "").rstrip("/").split("/")[-1]
            folder = {"unet": "unet_gguf", "unet_gguf": "unet_gguf", "diffusion_models": "UNETLoader", "text_encoders": "CLIPLoader", "vae": "VAELoader",
                      "model_patches": "ModelPatchLoader"}.get(bare, bare)
            cls = {"unet_gguf": "UnetLoaderGGUF", "UNETLoader": "UNETLoader", "CLIPLoader": "CLIPLoader", "VAELoader": "VAELoader",
                   "ModelPatchLoader": "ModelPatchLoader"}.get(folder)
            if cls and cls in schema:
                opts = ((schema[cls].get("input") or {}).get("required") or {})
                key = {"UnetLoaderGGUF": "unet_name", "UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name",
                       "ModelPatchLoader": "name"}.get(cls)
                if key and isinstance(opts.get(key), list) and len(opts[key]) and isinstance(opts[key][0], list) and m.get("file") in opts[key][0]:
                    have.append(m.get("file"))
    print("  models installed: %d of %d named by the graphs%s" % (len(set(have)), len(set(want)),
          (" - e.g. " + ", ".join(sorted(set(have))[:2])) if have else " (Render Studio will still preflight-fail)"))

    # ---- ComfyUI READING the multi-frame APNG (the control-video path; Blocker 3)
    frames = [png(64, 48, (i * 60 % 255, 40, 200 - i * 30)) for i in range(3)]
    anim = AR.apng(frames, 24.0)
    sub = "loki-live-" + uuid.uuid4().hex[:8]
    up = cl.upload_image("check_%d.png" % len(frames), anim, subfolder=sub)
    ref = (up.get("subfolder") + "/" if up.get("subfolder") else "") + up.get("name")
    print("  uploaded a 3-frame APNG as %s (%d bytes)" % (ref, len(anim)))
    pref = "loki_live_" + uuid.uuid4().hex[:8]
    outs, status, msgs = queue_and_wait(cl, {
        "1": {"class_type": "LoadImage", "inputs": {"image": ref, "upload": "image"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": pref}},
    })
    got = len(((outs or {}).get("2") or {}).get("images") or [])
    check("LoadImage on the live server reads EVERY frame of the APNG the passes are sent as", got == len(frames),
          {"frames_out": got, "status": status, "messages": str(msgs)[:300]})

    # ---- Canny (the node preprocess_lineart.json depends on) and ImageBlend (the guide mix)
    outs, status, msgs = queue_and_wait(cl, {
        "1": {"class_type": "LoadImage", "inputs": {"image": ref, "upload": "image"}},
        "2": {"class_type": "Canny", "inputs": {"image": ["1", 0], "low_threshold": 0.4, "high_threshold": 0.8}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": pref + "_canny"}},
    })
    cans = ((outs or {}).get("3") or {}).get("images") or []
    check("Canny runs on the live server (the line-art preprocess graph)", len(cans) == len(frames), {"out": len(cans), "status": status})
    outs, status, msgs = queue_and_wait(cl, {
        "1": {"class_type": "LoadImage", "inputs": {"image": ref, "upload": "image"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": ref, "upload": "image"}},
        "3": {"class_type": "ImageBlend", "inputs": {"image1": ["1", 0], "image2": ["2", 0], "blend_factor": 0.2, "blend_mode": "normal"}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": pref + "_blend"}},
    })
    bl = ((outs or {}).get("4") or {}).get("images") or []
    check("ImageBlend runs on the live server (the line art + depth guide)", len(bl) == len(frames), {"out": len(bl), "status": status})

    # ---- the real vace_render graph: the server's own validation of all 17 nodes. Model files may be missing (that is
    #      expected on a fresh install) - a STRUCTURAL error is not.
    wf = AR.workflow("vace_render")
    prompt, problems = AR.build_prompt(wf, {"frames": 33, "prompt": "a fox in a forest", "seed": 7},
                                       {"depth": ref, "lineart": ref, "start": ref}, "both")
    check("build_prompt fills the whole graph with no problems", not problems, problems)
    ok, err = post_prompt(cl, prompt)
    errs = (err or {}).get("node_errors") or {}
    missing, structural = [], []
    for nid, node in errs.items():
        for e in (node.get("errors") or []):
            msg = str(e.get("message") or "")
            det = str(e.get("details") or "")
            (missing if "not in list" in msg or "not found" in msg.lower() else structural).append("%s %s: %s %s" % (nid, node.get("class_type"), msg, det))
    check("the live server accepts LOKI's 17-node graph as valid (only missing model files, if any)",
          bool(ok) or not structural, {"structural": structural[:4], "accepted": bool(ok)})
    if ok:
        print("  the live server QUEUED the full 17-node graph (every model file present)")
    else:
        print("  the server's validation named %d node(s); every one a model file that is not installed here:" % len(errs))
        for line in missing[:6]:
            print("    " + line[:170])

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
