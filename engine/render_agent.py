"""Renders for agents: a 3D model in, a rendered picture or turntable out, with no window open.

engine/scene_passes.py makes Forge's control passes (depth, line art, normals, a shaded beauty) from a .glb, and the
AI Renderer's own graphs on ComfyUI (engine/ai_renderer.py) turn them into the finished look:

    passes only (no prompt)      the passes into renders/<model>-<time>/, plus a 2x2 contact sheet - seconds, no GPU
    prompt, frames = 1           a still: Z-Image Turbo steered by the depth (zimage_reference_depth), waited for
    prompt, frames > 1           a turntable video: Wan VACE driven by depth + line art (vace_render), frames rounded
                                 up to 4n+1; its start image is `start=` or a still made first. It runs in the
                                 background - action=status job=<id> brings the video into renders/ when it is done

The jobs are ordinary AI Renderer jobs, so they also show in the Render tab, with their log and Retry.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import scene_passes

TOOL = {"name": "render_scene",
        "description": "Render a 3D model (.glb in this folder, e.g. from make_3d) with no window open. Without prompt: "
                       "depth / lineart / normal / beauty passes and a contact sheet, in seconds; frames=48 adds a "
                       "turntable video (turntable.mp4). With prompt: the AI "
                       "Renderer on the owner's ComfyUI - frames=1 a finished still (waits for it), frames>1 a "
                       "turntable video (runs in the background; action=status job=<id> to collect it). Options: "
                       "size='832x480', azimuth (degrees, default 30), elevation (15), orbit (degrees turned over the "
                       "frames, 360), start= a picture for the video's look, seed=, strength= (depth's pull, 0-1).",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["render", "status"]},
            "model": {"type": "string"}, "prompt": {"type": "string"}, "frames": {"type": "integer"},
            "size": {"type": "string"}, "azimuth": {"type": "number"}, "elevation": {"type": "number"},
            "orbit": {"type": "number"}, "start": {"type": "string"}, "seed": {"type": "integer"},
            "strength": {"type": "number"}, "job": {"type": "string"},
            "passes": {"type": "string", "description": "comma list of depth,lineart,normal,beauty"}}}}

STILL, VIDEO = "zimage_reference_depth", "vace_render"


def _size(text) -> tuple:
    try:
        w, h = (int(x) for x in str(text or "832x480").lower().replace(" ", "").split("x"))
    except ValueError:
        w, h = 832, 480
    snap = lambda v: max(64, min(2048, int(round(v / 16.0)) * 16))  # noqa: E731 - the graphs want multiples of 16
    return snap(w), snap(h)


def _find(ws: Path, name: str) -> Path | None:
    if not name:
        return None
    p = Path(name).expanduser()
    for c in ([p] if p.is_absolute() else [ws / p, ws / "models" / p, ws / "models" / p.name]):
        if c.is_file():
            return c.resolve()
    return None


def contact_sheet(made: dict, out: Path, index: int = 0) -> str:
    from PIL import Image  # pylint: disable=import-outside-toplevel
    ims = [Image.open(made[p][index]).convert("RGB") for p in ("beauty", "depth", "lineart", "normal") if made.get(p)]
    if not ims:
        return ""
    w, h = ims[0].size
    cols = 2 if len(ims) > 1 else 1
    rows = (len(ims) + 1) // 2
    sheet = Image.new("RGB", (w * cols, h * rows))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet.save(out)
    return str(out)


def turntable_video(frames: list, target: Path, fps: int = 24) -> str:
    """The beauty frames as an H.264 MP4 (ffmpeg, if this computer has it) - a turntable with no GPU at all."""
    import shutil as _sh  # pylint: disable=import-outside-toplevel
    import subprocess  # pylint: disable=import-outside-toplevel
    exe = _sh.which("ffmpeg")
    if not exe or len(frames) < 2:
        return ""
    pattern = str(Path(frames[0]).parent / "%04d.png")
    try:
        subprocess.run([exe, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pattern, "-c:v", "libx264",
                        "-preset", "veryfast", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                        "-movflags", "+faststart", str(target)], check=True, timeout=300, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        return ""
    return str(target) if target.is_file() else ""


def _bring(state, job: str, ws: Path, stem: str) -> list:
    import ai_renderer  # pylint: disable=import-outside-toplevel
    m = ai_renderer.manifest(state, job) or {}
    dest = ws / "renders"
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    for name in m.get("outputs") or []:
        src = ai_renderer.job_dir(state, job) / name
        if src.is_file():
            target = dest / ("%s-%s%s" % (stem, job[-4:], src.suffix) if len(m["outputs"]) == 1
                             else "%s-%s-%s" % (stem, job[-4:], name))
            shutil.copy2(src, target)
            got.append(str(target))
    return got


def _png_bytes(path) -> bytes:
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    import io  # pylint: disable=import-outside-toplevel
    from PIL import Image  # pylint: disable=import-outside-toplevel
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def _job(state, wf: str, name: str, params: dict, passes: dict, frames: int, size: tuple) -> str:
    import ai_renderer  # pylint: disable=import-outside-toplevel
    made = ai_renderer.new_job(state, {"kind": "ai", "workflow": wf, "name": name, "params": params, "frames": frames,
                                       "size": list(size), "camera": "orbit", "project": "agents"})
    job = made["job"]
    for pname, paths in passes.items():
        for i, p in enumerate(paths):
            ai_renderer.save_pass(state, job, pname, i, _png_bytes(p))
    return job


def status(args: dict, ws: Path, state=None) -> dict:
    import ai_renderer  # pylint: disable=import-outside-toplevel
    job = str(args.get("job") or "")
    m = ai_renderer.manifest(state, job) if job else None
    if not m:
        return {"ok": False, "error": "no render job %r" % job}
    out = {"ok": m["status"] != "failed", "job": job, "status": m["status"], "progress": m.get("progress"),
           "last": (m.get("log") or [{}])[-1].get("msg", "")}
    if m["status"] == "succeeded":
        out["files"] = _bring(state, job, ws, (m.get("name") or "render").split()[0][:40])
    return out


def render(args: dict, ws, state=None, wait_s: float = 900, starter=None) -> dict:
    """The tool. `starter(state, job, wait)` is ai_renderer.start (tests pass their own)."""
    ws = Path(ws)
    if str(args.get("action") or "render") == "status":
        return status(args, ws, state)
    model = _find(ws, str(args.get("model") or ""))
    if model is None:
        return {"ok": False, "error": "no model %r here - give the .glb's path (make_3d saves them in models/)"
                                      % args.get("model")}
    w, h = _size(args.get("size"))
    prompt = str(args.get("prompt") or "").strip()
    frames = max(1, min(int(args.get("frames") or 1), 241))
    if prompt and frames > 1:
        frames = (frames - 1 + 3) // 4 * 4 + 1                 # Wan: 4n+1
    want = [p.strip() for p in str(args.get("passes") or "").split(",") if p.strip()] or (
        list(scene_passes.PASSES) if not prompt else ["depth", "lineart"] if frames > 1 else ["depth"])
    if not prompt and frames > 1 and "beauty" not in want:
        want.append("beauty")                     # the turntable video is made from it
    stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in model.stem)[:40] or "model"
    out = ws / "renders" / ("%s-%s" % (stem, time.strftime("%Y%m%d-%H%M%S")))
    try:
        res = scene_passes.render(model, out, frames=frames, passes=want, width=w, height=h,
                                  azimuth=float(args.get("azimuth", 30)), elevation=float(args.get("elevation", 15)),
                                  orbit=float(args.get("orbit", 360)))
    except (scene_passes.PassError, OSError, KeyError, ValueError) as exc:
        return {"ok": False, "error": "could not read %s: %s" % (model.name, exc)}
    sheet = contact_sheet(res["passes"], out / "sheet.png")
    if not prompt:
        files = [sheet] if sheet else []
        video = turntable_video(res["passes"].get("beauty") or [], out / "turntable.mp4") if frames > 1 else ""
        if video:
            files.insert(0, video)
        return {"ok": True, "folder": str(out), "sheet": sheet, "frames": frames, "seconds": res["seconds"],
                "files": files, "video": video, "passes": {k: len(v) for k, v in res["passes"].items()}}

    import ai_renderer  # pylint: disable=import-outside-toplevel
    start = starter or (lambda st, job, wait: ai_renderer.start(st, job, wait=wait))
    seed = int(args["seed"]) if args.get("seed") not in (None, "") else int(time.time()) % 2**31
    try:
        if frames == 1 or not _find(ws, str(args.get("start") or "")):
            params = {"prompt": prompt, "width": w, "height": h, "seed": seed,
                      "control_strength": float(args.get("strength") or 0.8)}
            sjob = _job(state, STILL, "%s still" % stem, params, {"depth": res["passes"]["depth"][:1]}, 1, (w, h))
            m = start(state, sjob, True)
            t0 = time.time()
            while m and m.get("status") not in ("succeeded", "failed", "cancelled") and time.time() - t0 < wait_s:
                time.sleep(2)
                m = ai_renderer.manifest(state, sjob)
            if not m or m.get("status") != "succeeded":
                return {"ok": False, "job": sjob, "error": "the still did not render: %s"
                        % ((m or {}).get("log") or [{}])[-1].get("msg", "no answer"), "passes_folder": str(out)}
            still = _bring(state, sjob, ws, stem)
            if frames == 1:
                return {"ok": True, "files": still, "job": sjob, "passes_folder": str(out), "sheet": sheet}
            start_img = Path(still[0])
        else:
            start_img = _find(ws, str(args.get("start")))
        params = {"prompt": prompt, "width": w, "height": h, "frames": frames, "seed": seed}
        if args.get("strength") not in (None, ""):
            params["strength"] = float(args["strength"])
        vjob = _job(state, VIDEO, "%s turntable" % stem, params,
                    {"depth": res["passes"]["depth"], "lineart": res["passes"]["lineart"], "start": [str(start_img)]},
                    frames, (w, h))
        m = start(state, vjob, False)
    except ai_renderer.RenderError as exc:
        return {"ok": False, "error": str(exc), "passes_folder": str(out)}
    return {"ok": True, "job": vjob, "status": (m or {}).get("status"), "start_image": str(start_img),
            "frames": frames, "passes_folder": str(out),
            "next": "it renders in the background (Render tab); call render_scene action=status job=%s to collect it" % vjob}
