"""Forge's best 3D: Pixal3D and TRELLIS.2 through ComfyUI's own native nodes (owner 2026-10-25: "focus trellis and pixel3d
forge stuff i want that all working and flushed out").

The graph is Comfy Org's official template (MIT), converted once to the API format by tools/comfy_convert.py and kept in
engine/forge_workflows/trellis2_pixal3d.json (the original UI file sits beside it in ui/). One picture -> BiRefNet cut-out
-> crop -> sparse structure -> shape -> 1536 upsample -> texture -> remesh, decimate, UV unwrap -> PBR bake (base colour,
metallic, roughness, normal, AO) -> one textured .glb.

    pixal3d   Pixal3D (TencentARC, MIT): pixel-aligned - MoGe estimates the camera's field of view, so the model's
              front matches the picture. The default.
    trellis2  TRELLIS.2 (Microsoft, MIT): the same pipeline without the camera step; a little faster, one model less.

It runs where ComfyUI runs - the PC (RTX 3070 Ti, 8 GB: the int8 models fit; start ComfyUI with --lowvram if it runs
out) - and LOKI on the Mac reaches it over the LAN like Render Studio does (ai_renderer settings: the same ComfyUI
address, the same rule that pictures only go to this computer or LOKI's own linked machines unless the owner allowed
another server).

    pixal3d-views  Pixal3D's multi-view model: a turnaround sheet (front, left, back, right side by side; Forge's
              "4-view sheet" option) -> one model whose sides and back match the sheet (engine/forge_workflows/
              pixal3d_views.json - LOKI splits the sheet into its four columns).

    status(url=None)               {reachable, nodes_ok, missing_nodes, modes: {pixal3d: {ready, missing}}, comfy_dir}
    ready(mode)                    cached for a minute (Forge's "Best available" order asks this)
    build(mode, image, opts)       the API prompt for one run (switches resolved, unused branch pruned)
    run(cutout_png, out_base, mode, opts)  upload, queue, wait, download -> {"glb", "mode", "seconds"}
    install(names=None, comfy_dir=None)    download the missing model files into that ComfyUI's models/ folders
                                   (only on the computer ComfyUI is installed on; resumable, a .part file until done)
Standard library only; the ComfyUI client is ai_renderer.Comfy.
"""
from __future__ import annotations

import copy
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import comfy_workflow

FLOWS = Path(__file__).resolve().parent / "forge_workflows"
WORKFLOW = FLOWS / "trellis2_pixal3d.json"
VIEWS_WORKFLOW = FLOWS / "pixal3d_views.json"
MODES = ("pixal3d", "trellis2")                    # one picture
ALL_MODES = MODES + ("pixal3d-views",)              # + a 4-view turnaround sheet (front, left, back, right)
VIEWS = ("front", "left", "back", "right")
LABELS = {"pixal3d": "Pixal3D (best match to the picture)", "trellis2": "TRELLIS.2",
          "pixal3d-views": "Pixal3D multi-view (a 4-view sheet)"}
_CACHE: dict = {}
CACHE_S = 60.0


class TrellisError(RuntimeError):
    pass


def workflow(mode: str = "pixal3d") -> dict:
    return json.loads((VIEWS_WORKFLOW if mode == "pixal3d-views" else WORKFLOW).read_text(encoding="utf-8"))


def all_models() -> list:
    """Every model file any mode needs, once, with the modes that need it."""
    seen: dict = {}
    for wf in (workflow(), workflow("pixal3d-views")):
        for m in wf["models"]:
            seen.setdefault(m["file"], dict(m, **{"for": []}))["for"] += [x for x in m["for"] if x not in seen[m["file"]]["for"]]
    return list(seen.values())


def comfy_url() -> str:
    import ai_renderer  # pylint: disable=import-outside-toplevel
    return ai_renderer.settings().get("url") or ai_renderer.default_url()


def client(url: str | None = None, timeout: float = 20.0):
    import ai_renderer  # pylint: disable=import-outside-toplevel
    return ai_renderer.Comfy(url or comfy_url(), timeout=timeout)


# ----------------------------------------------------------------------------- the graph
def build(mode: str, image, opts: dict | None = None, wf: dict | None = None) -> dict:
    """The API prompt: `image` an uploaded picture's name (pixal3d | trellis2) or {front, left, back, right: name}
    (pixal3d-views); Forge's output options."""
    if mode not in ALL_MODES:
        raise TrellisError("mode is pixal3d, trellis2 or pixal3d-views")
    wf = wf or workflow(mode)
    n = wf["nodes"]
    o = opts or {}
    api = copy.deepcopy(wf["api"])
    if mode == "pixal3d-views":
        names = image if isinstance(image, dict) else {v: image for v in VIEWS}
        for view, nid in n["views"].items():
            api[nid]["inputs"]["image"] = names[view]
    else:
        api[n["image"]]["inputs"]["image"] = image
        api[n["mode"]]["inputs"]["value"] = mode == "trellis2"
    seed = int(o.get("seed") or 0)
    for i, sid in enumerate(n["seeds"]):
        if seed:
            api[sid]["inputs"]["seed"] = seed + i
    tex = int(o.get("texture_size") or 0)
    if tex:
        api[n["texture"]]["inputs"]["value"] = max(512, min(4096, tex // 512 * 512))
    faces = int(o.get("faces") or 0)
    if faces:
        api[n["faces"]]["inputs"]["target_face_count"] = max(2000, min(2_000_000, faces))
    detail = int(o.get("detail") or 0)
    if detail:
        api[n["remesh"]]["inputs"]["resolution"] = max(256, min(1024, detail // 64 * 64))
    prefix = str(o.get("prefix") or "loki/forge")
    api[n["save"]]["inputs"]["filename_prefix"] = prefix
    api = comfy_workflow.resolve_switches(api)
    return comfy_workflow.prune(api, [n["save"]])


def models_for(mode: str, wf: dict | None = None) -> list:
    wf = wf or workflow(mode)
    return [m for m in wf["models"] if mode in m["for"]]


# ----------------------------------------------------------------------------- is it ready
def _object_info(cl, url: str) -> dict:
    hit = _CACHE.get(("info", url))
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    cl.system_stats()            # quick: a sleeping PC fails here in seconds, not in object_info's minute
    info = cl.object_info()
    _CACHE[("info", url)] = (time.time(), info)
    return info


def status(url: str | None = None, cl=None) -> dict:
    url = url or comfy_url()
    out = {"url": url, "reachable": False, "nodes_ok": False, "missing_nodes": [], "modes": {},
           "comfy_dir": str(find_comfy_dir() or "")}
    try:
        cl = cl or client(url, timeout=4.0)
        info = _object_info(cl, url)
    except Exception as exc:  # noqa: BLE001
        out["error"] = "ComfyUI is not reachable at %s (%s)" % (url, str(exc)[:160])
        for m in ALL_MODES:
            out["modes"][m] = {"ready": False, "label": LABELS[m], "missing": []}
        return out
    out["reachable"] = True
    for m in ALL_MODES:
        api = build(m, "x.png")
        nodes = comfy_workflow.missing_nodes(api, info)
        files = comfy_workflow.check_models(api, info)
        if m in MODES:                             # the sheet's extra nodes never make the one-picture modes "old"
            out["missing_nodes"] = sorted(set(out["missing_nodes"]) | set(nodes))
        out["modes"][m] = {"ready": not nodes and not files, "label": LABELS[m],
                           "missing": [f["file"] for f in files], "missing_nodes": nodes}
    out["nodes_ok"] = not out["missing_nodes"]
    if out["missing_nodes"]:
        out["error"] = ("This ComfyUI is too old for TRELLIS.2 / Pixal3D (missing %s). Update it (git pull, or the "
                        "desktop app's update) and restart it." % ", ".join(out["missing_nodes"][:4]))
    return out


def ready(mode: str) -> bool:
    if os.environ.get("LOKI_FORGE_TRELLIS", "1") == "0":
        return False
    hit = _CACHE.get("status")
    if not hit or time.time() - hit[0] >= CACHE_S:
        try:
            st = status()
        except Exception:  # noqa: BLE001
            st = {"modes": {}}
        hit = _CACHE["status"] = (time.time(), st)
    return bool(((hit[1].get("modes") or {}).get(mode) or {}).get("ready"))


def forget_cache() -> None:
    _CACHE.clear()


# ----------------------------------------------------------------------------- one run
def run(cutout_png: Path, out_base: Path, mode: str = "pixal3d", opts: dict | None = None, cl=None,
        sleep: Callable = time.sleep, timeout: float = 3600.0, progress: Callable | None = None) -> dict:
    """The picture -> a textured .glb at out_base.glb. Raises TrellisError with the reason."""
    import ai_renderer  # pylint: disable=import-outside-toplevel
    say = progress or (lambda msg: None)
    url = comfy_url()
    if cl is None:
        ok, note = ai_renderer.may_upload(ai_renderer.settings())
        if not ok:
            raise TrellisError(note)
        cl = client(url)
    try:
        info = _object_info(cl, url)
    except Exception as exc:  # noqa: BLE001
        raise TrellisError("ComfyUI is not reachable at %s: %s" % (url, str(exc)[:200])) from None
    views = mode == "pixal3d" and bool((opts or {}).get("views"))
    if views:
        mode = "pixal3d-views"
    probe = build(mode, "x.png", opts)
    nodes = comfy_workflow.missing_nodes(probe, info)
    if nodes:
        raise TrellisError("ComfyUI is too old for %s (missing %s) - update it" % (mode, ", ".join(nodes[:4])))
    files = comfy_workflow.check_models(probe, info)
    if files:
        raise TrellisError("ComfyUI is missing %s - Forge > Output > Install models (on the computer ComfyUI runs on)"
                           % ", ".join(f["file"] for f in files))
    def upload(data: bytes, tag: str) -> str:
        name = "loki-forge-%s%s.png" % (uuid.uuid4().hex[:10], tag)
        up = cl.upload_image(name, data, subfolder="loki")
        return ("%s/%s" % (up["subfolder"], up.get("name") or name)) if up.get("subfolder") else (up.get("name") or name)

    if mode == "pixal3d-views":
        image = {v: upload(data, "-" + v) for v, data in split_sheet(Path(cutout_png)).items()}
    else:
        image = upload(Path(cutout_png).read_bytes(), "")
    prompt = build(mode, image, opts)
    pid = uuid.uuid4().hex
    started = time.time()
    say("queued on ComfyUI (%s)" % mode)
    got = cl.queue_prompt(prompt, "loki-forge", pid)
    if got.get("node_errors"):
        raise TrellisError("ComfyUI refused the graph: %s" % json.dumps(got["node_errors"])[:300])
    entry = {}
    while True:
        try:
            entry = (cl.history(pid) or {}).get(pid) or {}
        except Exception:  # noqa: BLE001 - a busy server misses a poll now and then
            entry = {}
        st = entry.get("status") or {}
        if st.get("completed") or st.get("status_str") in ("success", "error"):
            break
        if time.time() - started > timeout:
            try:
                cl.interrupt(pid)
            except Exception:  # noqa: BLE001
                pass
            raise TrellisError("%s took longer than %d minutes" % (mode, timeout // 60))
        say("working on ComfyUI (%ds)" % int(time.time() - started))
        sleep(3.0)
    st = entry.get("status") or {}
    if st.get("status_str") == "error":
        msg = ""
        for kind, data in st.get("messages") or []:
            if kind == "execution_error":
                msg = "%s: %s" % (data.get("node_type", "?"), str(data.get("exception_message", ""))[:300])
        if "out of memory" in msg.lower() or "allocation" in msg.lower():
            msg += " - the GPU ran out of memory: start ComfyUI with --lowvram, or lower Detail / Texture size"
        raise TrellisError("ComfyUI failed: %s" % (msg or "see its console"))
    found = None
    for out in (entry.get("outputs") or {}).values():
        for item in out.get("3d") or []:
            found = item
    if not found:
        raise TrellisError("ComfyUI finished but saved no model")
    data = cl.view(found["filename"], found.get("subfolder", ""), found.get("type", "output"))
    if data[:4] != b"glTF":
        raise TrellisError("ComfyUI sent something that is not a .glb")
    glb = Path(out_base).with_suffix(".glb")
    glb.write_bytes(data)
    return {"glb": str(glb), "mode": mode, "seconds": round(time.time() - started, 1),
            "note": "made by %s on ComfyUI (%s)" % (LABELS[mode], ai_renderer.redact(url))}


def split_sheet(path: Path) -> dict:
    """A turnaround sheet -> {front, left, back, right: PNG bytes}: four equal columns, left to right (the order
    Comfy Org's multi-view template reads them in)."""
    import io  # pylint: disable=import-outside-toplevel
    from PIL import Image  # pylint: disable=import-outside-toplevel
    with Image.open(path) as im:
        im = im.convert("RGBA")
        w, h = im.size
        if w < h * 1.5:
            raise TrellisError("a turnaround sheet has four views side by side (front, left, back, right) - "
                               "this picture is %dx%d" % (w, h))
        out = {}
        for i, view in enumerate(VIEWS):
            buf = io.BytesIO()
            im.crop((w * i // 4, 0, w * (i + 1) // 4, h)).save(buf, "PNG")
            out[view] = buf.getvalue()
    return out


# ----------------------------------------------------------------------------- installing the models
def find_comfy_dir() -> Path | None:
    """The ComfyUI on THIS computer: LOKI_COMFY_DIR, the forge setting, or the usual places (git clone, the desktop
    app's Documents/ComfyUI, the portable build)."""
    import ai_renderer  # pylint: disable=import-outside-toplevel
    s = ai_renderer._read_json(ai_renderer._settings_file(), {}) or {}  # pylint: disable=protected-access
    home = Path.home()
    cands = [os.environ.get("LOKI_COMFY_DIR"), s.get("comfy_dir"), home / "ComfyUI", home / "Documents" / "ComfyUI",
             home / "ComfyUI_windows_portable" / "ComfyUI", home / "Desktop" / "ComfyUI",
             home / "Desktop" / "ComfyUI_windows_portable" / "ComfyUI", Path("C:/ComfyUI"),
             Path("C:/ComfyUI_windows_portable/ComfyUI")]
    for c in cands:
        if c and (Path(c) / "models").is_dir():
            return Path(c)
    return None


def install(names: list | None = None, comfy_dir: str | None = None, mode: str | None = None,
            opener=urllib.request.urlopen, progress: Callable | None = None, wf: dict | None = None) -> dict:
    """Download model files into <ComfyUI>/models/<folder>/. names=None: every file `mode` (or both modes) needs that is
    not there yet. Already-complete files are skipped; a cut download resumes from its .part."""
    base = Path(comfy_dir) if comfy_dir else find_comfy_dir()
    if base is None or not (base / "models").is_dir():
        raise TrellisError("No ComfyUI on this computer (set its folder in Forge > Output, or LOKI_COMFY_DIR). Install "
                           "the models on the computer ComfyUI runs on - from LOKI there, or: python tools/setup_trellis.py")
    say = progress or (lambda msg, frac=None: None)
    models = wf["models"] if wf else all_models()
    want = [m for m in models if (names is None and (mode is None or mode in m["for"]))
            or (names is not None and m["file"] in names)]
    done, skipped = [], []
    for m in want:
        target = base / "models" / m["folder"] / m["file"]
        if target.is_file() and target.stat().st_size > 0:
            skipped.append(m["file"])
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        have = part.stat().st_size if part.is_file() else 0
        headers = {"User-Agent": "Loki/1.0"}
        if have:
            headers["Range"] = "bytes=%d-" % have
        token = os.environ.get("HF_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        with opener(urllib.request.Request(m["url"], headers=headers), timeout=120) as resp:
            code = getattr(resp, "status", 200)
            if have and code != 206:          # the server ignored the range: start over
                have = 0
            total = have + int(resp.headers.get("Content-Length") or 0) if hasattr(resp, "headers") else 0
            with open(part, "ab" if have else "wb") as fh:
                got = have
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    say("downloading %s" % m["file"], (got / total) if total else None)
        os.replace(part, target)
        done.append(m["file"])
    forget_cache()
    return {"ok": True, "installed": done, "already": skipped, "comfy_dir": str(base)}
