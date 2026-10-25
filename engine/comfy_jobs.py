"""Run one of LOKI's ComfyUI graphs (engine/forge_workflows/<name>.json) with plain parameters and bring the files back:
the same pipe Forge's Pixal3D / TRELLIS.2 use (engine/forge_trellis.py), for every other ComfyUI-native maker.

A graph file: {"api": <API prompt>, "params": {name: [[node, input], ...]}, "save": <node id>, "models": [...],
"uploads": {name: [node, input]} (pictures sent first)}. Graphs come from Comfy Org's MIT templates through
engine/comfy_workflow.py, checked widget by widget.

    GRAPHS               music (ACE-Step 1.5: songs with lyrics, or instrumentals)
    status(name)         ComfyUI reachable, nodes there, model files there (which are missing)
    run(name, params, out_dir)   -> {"ok", "files": [...]}
    install(name)        the missing model files into ComfyUI's models/ (on the computer ComfyUI runs on)
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Callable

import comfy_workflow

FLOWS = Path(__file__).resolve().parent / "forge_workflows"
GRAPHS = {"music": "ace_step_music.json"}
LABELS = {"music": "Music (ACE-Step 1.5)"}


class JobError(RuntimeError):
    pass


def graph(name: str) -> dict:
    if name not in GRAPHS:
        raise JobError("no ComfyUI graph called %r (%s)" % (name, ", ".join(GRAPHS)))
    return json.loads((FLOWS / GRAPHS[name]).read_text(encoding="utf-8"))


def build(name: str, params: dict | None = None, wf: dict | None = None) -> dict:
    wf = wf or graph(name)
    api = copy.deepcopy(wf["api"])
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        for nid, inp in wf.get("params", {}).get(key) or []:
            if nid in api:
                old = api[nid]["inputs"].get(inp)
                api[nid]["inputs"][inp] = (type(old)(value) if isinstance(old, (int, float)) and not isinstance(old, bool)
                                           else value)
    return api


def status(name: str, cl=None) -> dict:
    import forge_trellis  # pylint: disable=import-outside-toplevel - the same ComfyUI, client and cache
    url = forge_trellis.comfy_url()
    out = {"name": name, "label": LABELS.get(name, name), "url": url, "reachable": False, "ready": False,
           "missing_nodes": [], "missing": []}
    try:
        cl = cl or forge_trellis.client(url, timeout=4.0)
        info = forge_trellis._object_info(cl, url)  # pylint: disable=protected-access
    except Exception as exc:  # noqa: BLE001
        out["error"] = "ComfyUI is not reachable at %s (%s)" % (url, str(exc)[:160])
        return out
    api = build(name)
    out.update(reachable=True, missing_nodes=comfy_workflow.missing_nodes(api, info),
               missing=[m["file"] for m in comfy_workflow.check_models(api, info)])
    out["ready"] = not out["missing_nodes"] and not out["missing"]
    if out["missing_nodes"]:
        out["error"] = "ComfyUI is too old for %s (missing %s) - update it" % (name, ", ".join(out["missing_nodes"][:4]))
    return out


def run(name: str, params: dict, out_dir: str | Path, cl=None, sleep: Callable = time.sleep, timeout: float = 3600,
        progress: Callable | None = None) -> dict:
    import ai_renderer  # pylint: disable=import-outside-toplevel
    import forge_trellis  # pylint: disable=import-outside-toplevel
    say = progress or (lambda msg: None)
    wf = graph(name)
    url = forge_trellis.comfy_url()
    if cl is None:
        ok, note = ai_renderer.may_upload(ai_renderer.settings())
        if not ok:
            raise JobError(note)
        cl = forge_trellis.client(url)
    st = status(name, cl)
    if not st["reachable"]:
        raise JobError(st.get("error", "ComfyUI is not reachable"))
    if st["missing_nodes"]:
        raise JobError(st["error"])
    if st["missing"]:
        raise JobError("ComfyUI is missing %s - install them (toolshelf / Settings, on the computer ComfyUI runs on)"
                       % ", ".join(st["missing"]))
    params = dict(params or {})
    for key, (nid, inp) in (wf.get("uploads") or {}).items():
        src = params.pop(key, None)
        if src:
            p = Path(src)
            up = cl.upload_image("loki-%s%s" % (uuid.uuid4().hex[:10], p.suffix or ".png"), p.read_bytes(), subfolder="loki")
            params.setdefault("_uploaded", {})[(nid, inp)] = "%s/%s" % (up.get("subfolder"), up.get("name"))
    uploaded = params.pop("_uploaded", {})
    api = build(name, params, wf)
    for (nid, inp), value in uploaded.items():
        api[nid]["inputs"][inp] = value
    pid = uuid.uuid4().hex
    started = time.time()
    got = cl.queue_prompt(api, "loki-jobs", pid)
    if got.get("node_errors"):
        raise JobError("ComfyUI refused the graph: %s" % json.dumps(got["node_errors"])[:300])
    entry = {}
    while True:
        try:
            entry = (cl.history(pid) or {}).get(pid) or {}
        except Exception:  # noqa: BLE001
            entry = {}
        state = entry.get("status") or {}
        if state.get("completed") or state.get("status_str") in ("success", "error"):
            break
        if time.time() - started > timeout:
            try:
                cl.interrupt(pid)
            except Exception:  # noqa: BLE001
                pass
            raise JobError("%s took longer than %d minutes" % (name, timeout // 60))
        say("working on ComfyUI (%ds)" % int(time.time() - started))
        sleep(3.0)
    state = entry.get("status") or {}
    if state.get("status_str") == "error":
        msg = ""
        for kind, data in state.get("messages") or []:
            if kind == "execution_error":
                msg = "%s: %s" % (data.get("node_type", "?"), str(data.get("exception_message", ""))[:300])
        raise JobError("ComfyUI failed: %s" % (msg or "see its console"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for item_list in (entry.get("outputs") or {}).get(wf["save"], {}).values():
        for item in item_list if isinstance(item_list, list) else []:
            if not isinstance(item, dict) or not item.get("filename"):
                continue
            fname = ai_renderer.safe_name(item["filename"])
            if not fname:
                continue
            data = cl.view(item["filename"], item.get("subfolder", ""), item.get("type", "output"))
            target = out / fname
            n = 2
            while target.exists():
                target = out / ("%s-%d%s" % (Path(fname).stem, n, Path(fname).suffix))
                n += 1
            target.write_bytes(data)
            files.append(str(target))
    if not files:
        raise JobError("ComfyUI finished but saved nothing")
    return {"ok": True, "files": files, "seconds": round(time.time() - started, 1), "graph": name}


def install(name: str, comfy_dir: str | None = None, progress: Callable | None = None, opener=None) -> dict:
    import forge_trellis  # pylint: disable=import-outside-toplevel
    wf = graph(name)
    kw = {"opener": opener} if opener else {}
    return forge_trellis.install(None, comfy_dir, None, progress=progress, wf=wf, **kw)


MUSIC_TOOL = {"name": "make_music",
              "description": "Make music with ACE-Step 1.5 on the owner's ComfyUI (the PC): tags= genre, instruments, mood "
                             "(e.g. 'epic orchestral battle theme, taiko drums, choir, 140 bpm'), lyrics= with [Verse] / "
                             "[Chorus] lines, or leave it out for an instrumental; seconds= 10-240 (default 60); bpm=; "
                             "key= e.g. 'E minor'; language= (default en); seed=. Saves an MP3 in audio/.",
              "inputSchema": {"type": "object", "properties": {
                  "tags": {"type": "string"}, "lyrics": {"type": "string"}, "seconds": {"type": "number"},
                  "bpm": {"type": "integer"}, "key": {"type": "string"}, "language": {"type": "string"},
                  "seed": {"type": "integer"}}, "required": ["tags"]}}


def make_music(args: dict, out_dir: str | Path, cl=None, sleep: Callable = time.sleep) -> dict:
    tags = str(args.get("tags") or args.get("prompt") or "").strip()
    if not tags:
        return {"ok": False, "error": "describe the music (tags=)"}
    lyrics = str(args.get("lyrics") or "").strip() or "[Instrumental]"
    params = {"tags": tags, "lyrics": lyrics, "seconds": max(10.0, min(240.0, float(args.get("seconds") or 60))),
              "bpm": int(args["bpm"]) if args.get("bpm") else None, "key": args.get("key") or None,
              "language": args.get("language") or None,
              "seed": int(args["seed"]) if args.get("seed") not in (None, "") else int(time.time()) % 2**31}
    try:
        return run("music", params, out_dir, cl=cl, sleep=sleep)
    except JobError as exc:
        return {"ok": False, "error": str(exc)}
