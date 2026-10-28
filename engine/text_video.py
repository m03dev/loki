"""Type a line, get a video (owner 2026-10-27: "i have still to receive a render ... there needs to be a way where I can
just type something and it renders a video").

    make(prompt, seconds=3, size="640x368", seed=0, ws=<workspace>) -> {"ok", "file", "engine", "seconds_taken", ...}

Where it runs:
  * the PC (or any machine whose own ComfyUI has the Wan VACE files): ComfyUI's text-to-video graph
    (engine/forge_workflows/wan_t2v.json - the model files Render Studio already uses), ComfyUI started if needed;
  * the Mac: handed to the PC over the link (offload kind "video", engine/offload.py); the video comes back into the
    Mac's own Home library. The Mac never loads the 14B model itself.
The video lands in <workspace>/videos/ with a .meta sidecar (prompt, engine), so Home shows and plays it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

FPS = 16
SIZES = {"640x368": (640, 368), "832x480": (832, 480), "480x832": (480, 832), "512x512": (512, 512)}
# Wan prompts read best as one concrete shot description; these keep the motion clean on a small model.
SHOT = ("single continuous shot, smooth natural motion, stable camera, consistent subject and lighting, sharp detail, "
        "cinematic")


def frames_for(seconds: float) -> int:
    """Wan wants 4n+1 frames; 1-8 s at 16 fps (an 8 GB GPU is happy up to ~5 s at 640x368)."""
    n = int(round(max(1.0, min(8.0, float(seconds or 3))) * FPS))
    return (n // 4) * 4 + 1


def full_prompt(prompt: str) -> str:
    p = re.sub(r"\s+", " ", str(prompt or "")).strip().rstrip(".")
    return "%s. %s" % (p, SHOT) if p else ""


def _slug(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:6]
    return "-".join(words) or "video"


MODEL_FILES = (("unet", "wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf"),
               ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"), ("vae", "wan_2.1_vae.safetensors"))


def files_here() -> tuple:
    """Without starting anything: are ComfyUI and the three Wan files on this machine's disk? (ok, why)"""
    if os.getenv("LOKI_VIDEO_SERVE", "").lower() == "on":     # models kept elsewhere (extra_model_paths)
        return True, ""
    try:
        import comfy_autostart  # pylint: disable=import-outside-toplevel
        root = comfy_autostart.comfy_root() / "ComfyUI"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:120]
    if not (root / "main.py").is_file():
        return False, "no ComfyUI on this machine"
    gone = [name for folder, name in MODEL_FILES
            if not any((root / "models" / d / name).is_file() for d in (folder, "diffusion_models", "clip"))]
    return (not gone), ("missing " + ", ".join(gone)) if gone else ""


def _local_ready() -> tuple:
    try:
        import comfy_jobs  # pylint: disable=import-outside-toplevel
        import forge_trellis  # pylint: disable=import-outside-toplevel
        url = forge_trellis.comfy_url()
        host = re.sub(r"^https?://", "", url).split(":")[0]
        if host in ("127.0.0.1", "localhost"):
            import comfy_autostart  # pylint: disable=import-outside-toplevel
            if not (comfy_autostart.comfy_root() / "ComfyUI" / "main.py").is_file():
                return False, "no ComfyUI on this machine"
            comfy_autostart.ensure(url)
        st = comfy_jobs.status("video")
        if st.get("ready"):
            return True, ""
        return False, st.get("error") or ("missing " + ", ".join(st.get("missing") or st.get("missing_nodes") or ["?"]))
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]


def status() -> dict:
    """Where a video would be made right now, and why not when it can't."""
    try:
        import offload  # pylint: disable=import-outside-toplevel
        peer = offload.target("video")
        if peer:
            return {"ready": True, "where": peer["name"], "engine": "Wan VACE text-to-video on %s" % peer["name"]}
    except Exception:  # noqa: BLE001
        pass
    ok, why = _local_ready()
    if ok:
        return {"ready": True, "where": "here", "engine": "Wan VACE text-to-video (this machine's ComfyUI)"}
    return {"ready": False, "where": "", "why": why or "no machine with the video model is linked"}


def run_here(params: dict, out: Path) -> dict:
    """On the machine with the GPU: ComfyUI's graph -> files in `out`."""
    import comfy_jobs  # pylint: disable=import-outside-toplevel
    ok, why = _local_ready()
    if not ok:
        raise RuntimeError("text to video cannot run here: " + why)
    res = comfy_jobs.run("video", {k: params.get(k) for k in ("prompt", "negative", "width", "height", "frames",
                                                               "seed", "steps")}, out, timeout=3600)
    return {"files": res["files"], "seconds": res.get("seconds"), "engine": "Wan VACE (ComfyUI)"}


def make(prompt: str, seconds: float = 3, size: str = "640x368", seed: int = 0, ws: Path | None = None,
         steps: int = 20) -> dict:
    words = full_prompt(prompt)
    if not words:
        return {"ok": False, "error": "say what the video shows"}
    w, h = SIZES.get(size, SIZES["640x368"])
    params = {"prompt": words, "width": w, "height": h, "frames": frames_for(seconds), "seed": int(seed or 0) or
              int(time.time()) % 2_000_000_000, "steps": int(steps or 20)}
    ws = Path(ws or os.getenv("LOKI_WORKSPACE") or ".")
    videos = ws / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="loki-t2v-"))
    try:
        where = "here"
        try:
            import offload  # pylint: disable=import-outside-toplevel
            peer = offload.target("video")
        except Exception:  # noqa: BLE001
            peer = None
        if peer:
            got = offload.run("video", params, {}, tmp, peer=peer)
            files = [str(f) for f in got.get("files") or []]
            where = peer["name"]
        else:
            files = run_here(params, tmp)["files"]
        vids = [Path(f) for f in files if Path(f).suffix.lower() in (".webm", ".mp4")]
        if not vids:
            return {"ok": False, "error": "the video model finished but no video came back"}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = videos / ("%s-%s%s" % (stamp, _slug(prompt), vids[0].suffix.lower()))
        shutil.move(str(vids[0]), dest)
        meta = {"prompt": words, "idea": str(prompt)[:600], "engine": "Wan VACE text-to-video", "machine": where,
                "size": "%dx%d" % (w, h), "frames": params["frames"], "fps": FPS, "seed": params["seed"],
                "seconds_taken": round(time.time() - started, 1), "t": time.time()}
        try:
            import creations  # pylint: disable=import-outside-toplevel
            rel = dest.relative_to(ws).as_posix()
            if creations.meta_path(ws, rel) is not None:
                creations.write_meta(ws, rel, **{k: v for k, v in meta.items() if k in ("prompt", "idea")})
        except Exception:  # noqa: BLE001 - a sidecar of our own below
            pass
        side = videos / ".meta"
        side.mkdir(exist_ok=True)
        side_file = side / (dest.name + ".json")
        old = json.loads(side_file.read_text()) if side_file.is_file() else {}
        side_file.write_text(json.dumps({**old, **meta}, indent=1))
        return {"ok": True, "file": str(dest), "rel": dest.relative_to(ws).as_posix(), **meta}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400], "machine": locals().get("where", "")}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the window: /video/make, /video/jobs, /video/status
import threading  # noqa: E402
import uuid  # noqa: E402

JOBS: dict = {}


def start(prompt: str, seconds: float, size: str, ws: Path) -> dict:
    jid = uuid.uuid4().hex[:10]
    rec = {"id": jid, "prompt": str(prompt)[:600], "status": "working", "t": time.time(), "seconds": seconds}
    JOBS[jid] = rec

    def work():
        res = make(prompt, seconds=seconds, size=size, ws=ws)
        rec.update(res, status="done" if res.get("ok") else "failed", ended=time.time())
    threading.Thread(target=work, daemon=True, name="loki-text-video").start()
    for old in sorted(JOBS.values(), key=lambda r: r["t"])[:-30]:
        JOBS.pop(old["id"], None)
    return rec


def route(state, method: str, route_: str, data: dict) -> tuple:
    ws = Path(getattr(getattr(state, "agent", None), "WORKSPACE", "") or os.getenv("LOKI_WORKSPACE") or ".")
    if (method, route_) == ("GET", "/video/status"):
        return 200, {"ok": True, **status()}
    if (method, route_) == ("GET", "/video/jobs"):
        return 200, {"ok": True, "jobs": sorted(JOBS.values(), key=lambda r: -r["t"])}
    if (method, route_) == ("POST", "/video/make"):
        prompt = str((data or {}).get("prompt") or "").strip()
        if not prompt:
            return 400, {"ok": False, "error": "say what the video shows"}
        st = status()
        if not st.get("ready"):
            return 200, {"ok": False, "error": "no machine can make video right now: " + st.get("why", "")}
        rec = start(prompt, float((data or {}).get("seconds") or 3), str((data or {}).get("size") or "640x368"), ws)
        return 200, {"ok": True, "job": rec, "where": st.get("where"), "engine": st.get("engine")}
    return 404, {"ok": False, "error": "unknown video route"}
