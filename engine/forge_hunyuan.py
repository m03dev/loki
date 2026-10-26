"""Hunyuan3D-2.1 as a Forge backend - OWNER-INSTALLED ONLY (owner 2026-10-26: "lets add this").

Two ways to run it (LOKI_HUNYUAN_MODE, default "comfy"):
  comfy   ComfyUI's own native Hunyuan3D 2.1 nodes (engine/forge_workflows/hunyuan3d21.json - the official template:
          30 steps, cfg 5, euler, surface net). ComfyUI's memory management fits the 3.3B shape model on the PC's 8 GB
          card; the weights (Comfy-Org/hunyuan3D_2.1_repackaged) go into ComfyUI's checkpoints/. Shape only.
  server  Tencent's own api_server.py from the owner's clone (shape ~10 GB VRAM official; texture ~21 GB).

Hunyuan3D-2.1 (github.com/Tencent-Hunyuan/Hunyuan3D-2.1) is NOT open source: the Tencent Hunyuan 3D 2.1 Community
License excludes the EU, the UK and South Korea, needs Tencent's permission above 1M monthly users, forbids using its
output to improve any other AI model (5.b) and any use outside its Territory (5.c). So none of its code or weights
are in LOKI (AGPL-3.0): the owner installs it on their own machine (tools/setup_hunyuan3d.py, with the licence shown
and accepted), runs its own api_server.py, and LOKI only talks to that server over HTTP:

    POST {url}/generate   {"image": <base64 PNG>, "remove_background", "texture", "seed", "octree_resolution",
                           "num_inference_steps", "guidance_scale", "num_chunks", "face_count"}  ->  the .glb bytes
    GET  {url}/health     {"status": "healthy", ...}
(/send + /status/{uid} are not used: upstream /status only completes once a TEXTURED file exists.)

ready() needs all of: LOKI_HUNYUAN_ACCEPTED=1 (written by the setup after the owner accepted the licence), a
server answering /health at LOKI_HUNYUAN_URL (default http://127.0.0.1:8081 - on the Mac it can point at the PC).
Everything it makes is marked in the sidecar: licence, "no_training": true (5.b) - LOKI's training/self-improvement
must skip it (engine/training_guard.py).
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8081"
LICENCE = "Tencent Hunyuan 3D 2.1 Community License (not open source; EU/UK/KR excluded; no training other models)"
LICENCE_URL = "https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE"


class HunyuanError(Exception):
    pass


FLOW = Path(__file__).resolve().parent / "forge_workflows" / "hunyuan3d21.json"


def mode() -> str:
    m = str(os.environ.get("LOKI_HUNYUAN_MODE") or "comfy").lower()
    return m if m in ("comfy", "server") else "comfy"


def workflow() -> dict:
    return json.loads(FLOW.read_text(encoding="utf-8"))


def build(image: str, opts: dict | None = None, wf: dict | None = None) -> dict:
    """The ComfyUI API prompt for one cut-out picture already uploaded as `image`."""
    import copy  # pylint: disable=import-outside-toplevel
    wf = wf or workflow()
    n, api, o = wf["nodes"], copy.deepcopy(wf["api"]), options_for(opts)
    api[n["image"]]["inputs"]["image"] = image
    api[n["sampler"]]["inputs"]["seed"] = o["seed"]
    api[n["sampler"]]["inputs"]["steps"] = max(10, min(50, int((opts or {}).get("steps") or 30)))
    api[n["sampler"]]["inputs"]["cfg"] = o["guidance_scale"]
    api[n["decode"]]["inputs"]["octree_resolution"] = o["octree_resolution"]
    api[n["decode"]]["inputs"]["num_chunks"] = o["num_chunks"]
    api[n["save"]]["inputs"]["filename_prefix"] = str((opts or {}).get("prefix") or "loki/hunyuan")
    return api


def comfy_status(cl=None) -> dict:
    """{reachable, ready, missing, missing_nodes} for the ComfyUI route."""
    import comfy_workflow  # pylint: disable=import-outside-toplevel
    import forge_trellis  # pylint: disable=import-outside-toplevel
    url_ = forge_trellis.comfy_url()
    try:
        cl = cl or forge_trellis.client(url_, timeout=4.0)
        info = forge_trellis._object_info(cl, url_)  # pylint: disable=protected-access
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "ready": False, "error": "ComfyUI not reachable at %s (%s)" % (url_, str(exc)[:120])}
    api = build("x.png")
    nodes = comfy_workflow.missing_nodes(api, info)
    files = comfy_workflow.check_models(api, info)
    return {"reachable": True, "ready": not nodes and not files, "missing": [f["file"] for f in files],
            "missing_nodes": nodes, "url": url_}


def install_models(comfy_dir: str | None = None, progress=None) -> dict:
    """Download the repackaged 2.1 checkpoint into <ComfyUI>/models/checkpoints/ (only after the owner accepted)."""
    if not accepted():
        raise HunyuanError("accept the licence first: python tools/setup_hunyuan3d.py")
    import forge_trellis  # pylint: disable=import-outside-toplevel
    return forge_trellis.install(None, comfy_dir, "hunyuan", progress=progress, wf=workflow())


def url() -> str:
    return str(os.environ.get("LOKI_HUNYUAN_URL") or DEFAULT_URL).rstrip("/")


def accepted() -> bool:
    return str(os.environ.get("LOKI_HUNYUAN_ACCEPTED", "")).strip() == "1"


def health(timeout: float = 1.5, opener=urllib.request.urlopen) -> dict:
    try:
        with opener(url() + "/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except (OSError, ValueError, urllib.error.URLError):
        return {}


_READY = {}


def ready(opener=urllib.request.urlopen) -> bool:
    if not accepted():
        return False
    hit = _READY.get(mode())
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    ok = (comfy_status().get("ready") if mode() == "comfy" else health(opener=opener).get("status") == "healthy")
    _READY[mode()] = (time.time(), bool(ok))
    return bool(ok)


def why_not(opener=urllib.request.urlopen) -> str:
    if not accepted():
        return "not installed by the owner (python tools/setup_hunyuan3d.py - shows the licence first)"
    if mode() == "comfy":
        st = comfy_status()
        if not st.get("reachable"):
            return st.get("error") or "ComfyUI not reachable"
        if st.get("missing_nodes"):
            return "this ComfyUI is too old for Hunyuan3D 2.1 (missing %s) - update it" % ", ".join(st["missing_nodes"][:3])
        if st.get("missing"):
            return "ComfyUI is missing %s - python tools/setup_hunyuan3d.py models" % ", ".join(st["missing"])
        return ""
    if health(opener=opener).get("status") != "healthy":
        return "no Hunyuan3D server answering at %s (start it: python tools/setup_hunyuan3d.py start)" % url()
    return ""


def options_for(opts: dict | None) -> dict:
    """Forge's output options (engine/forge3d.py OPTIONS) -> the server's request fields, inside its limits."""
    o = opts or {}
    res = int(o.get("remesh") or o.get("resolution") or 256)
    return {"octree_resolution": max(64, min(512, res if res <= 512 else 384)),
            "face_count": max(1000, min(100000, int(o.get("triangles") or o.get("faces") or 40000))),
            "texture": bool(o.get("texture", False)),
            "seed": int(o.get("seed") or 0) or int(time.time()) % 2 ** 31,
            "num_inference_steps": max(1, min(20, int(o.get("steps") or 5))),
            "guidance_scale": max(0.1, min(20.0, float(o.get("guidance") or 5.0))),
            "num_chunks": 8000}


def run(cut_png: Path, base: Path, opts: dict | None = None, opener=urllib.request.urlopen,
        timeout: float = 1800) -> dict:
    """The cut-out picture -> <base>.glb through the owner's Hunyuan3D server. The picture is already cut out
    (engine/cutout.py, BiRefNet), so the server's own background remover is off."""
    reason = why_not(opener=opener)
    if reason:
        raise HunyuanError(reason)
    if mode() == "comfy":
        return run_comfy(cut_png, base, opts)
    body = {"image": base64.b64encode(Path(cut_png).read_bytes()).decode("ascii"), "remove_background": False}
    body.update(options_for(opts))
    req = urllib.request.Request(url() + "/generate", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with opener(req, timeout=timeout) as r:
            data = r.read()
            ctype = r.headers.get("Content-Type", "") if getattr(r, "headers", None) else ""
    except urllib.error.HTTPError as exc:
        raise HunyuanError("Hunyuan3D server said %s: %s" % (exc.code, exc.read()[:300])) from None
    except (OSError, urllib.error.URLError) as exc:
        raise HunyuanError("Hunyuan3D server unreachable: %s" % exc) from None
    if not data.startswith(b"glTF"):
        msg = data[:300].decode("utf-8", "replace")
        raise HunyuanError("Hunyuan3D gave no model (%s): %s" % (ctype or "?", msg))
    glb = Path(base).with_suffix(".glb")
    glb.write_bytes(data)
    return {"glb": str(glb), "backend": "hunyuan", "seconds": round(time.time() - t0, 1),
            "texture": body["texture"], "licence": LICENCE, "licence_url": LICENCE_URL, "no_training": True}


def run_comfy(cut_png: Path, base: Path, opts: dict | None = None, cl=None, sleep=time.sleep, timeout: float = 1800,
              progress=None) -> dict:
    """The cut-out -> <base>.glb on ComfyUI with the native 2.1 nodes (shape only)."""
    import uuid  # pylint: disable=import-outside-toplevel
    import forge_trellis  # pylint: disable=import-outside-toplevel
    say = progress or (lambda msg: None)
    url_ = forge_trellis.comfy_url()
    cl = cl or forge_trellis.client(url_)
    name = "loki-hunyuan-%s.png" % uuid.uuid4().hex[:10]
    up = cl.upload_image(name, Path(cut_png).read_bytes(), subfolder="loki")
    image = ("%s/%s" % (up["subfolder"], up.get("name") or name)) if up.get("subfolder") else (up.get("name") or name)
    pid, t0 = str(uuid.uuid4()), time.time()   # ComfyUI wants a real UUID
    got = cl.queue_prompt(build(image, opts), "loki-forge", pid)
    if got.get("node_errors"):
        raise HunyuanError("ComfyUI refused the graph: %s" % json.dumps(got["node_errors"])[:300])
    while True:
        try:
            entry = (cl.history(pid) or {}).get(pid) or {}
        except Exception:  # noqa: BLE001
            entry = {}
        st = entry.get("status") or {}
        if st.get("completed") or st.get("status_str") in ("success", "error"):
            break
        if time.time() - t0 > timeout:
            raise HunyuanError("Hunyuan3D on ComfyUI took longer than %d minutes" % (timeout // 60))
        say("Hunyuan3D 2.1 on ComfyUI (%ds)" % int(time.time() - t0))
        sleep(3.0)
    if st.get("status_str") == "error":
        msg = next(("%s: %s" % (d.get("node_type", "?"), str(d.get("exception_message", ""))[:300])
                    for k, d in st.get("messages") or [] if k == "execution_error"), "see ComfyUI's console")
        if "out of memory" in msg.lower():
            msg += " - start ComfyUI with --lowvram, or lower Detail (octree resolution)"
        raise HunyuanError("ComfyUI failed: " + msg)
    found = None
    for out in (entry.get("outputs") or {}).values():
        for item in out.get("3d") or []:
            found = item
    if not found:
        raise HunyuanError("ComfyUI finished but saved no model")
    data = cl.view(found["filename"], found.get("subfolder", ""), found.get("type", "output"))
    if data[:4] != b"glTF":
        raise HunyuanError("ComfyUI sent something that is not a .glb")
    glb = Path(base).with_suffix(".glb")
    glb.write_bytes(data)
    return {"glb": str(glb), "backend": "hunyuan", "route": "comfy", "seconds": round(time.time() - t0, 1),
            "texture": False, "licence": LICENCE, "licence_url": LICENCE_URL, "no_training": True}
