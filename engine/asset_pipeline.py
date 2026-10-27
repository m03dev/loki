"""LOKI's asset pipeline: concept -> turnaround -> model -> finish -> render, run like a studio (owner 2026-10-26:
"technical agent skills ... like an industry pipeline where they pass on work to each other and can improve").

Ideas taken (docs/PIPELINE_RESEARCH_2026-10-26.md, "Agent pipeline"): OpenCue's stage DAG, Kitsu's task statuses,
ShotGrid's review notes as their own records, Pyblish's collect -> validate -> integrate (nothing is handed on that
failed a check), CrewAI's guardrail + 3 retries, ChatDev's "only the agreed result goes forward", LangGraph's
checkpoint after every step, OpenAssetIO-style references (loki://<asset>/<stage>@approved), Reflexion / ExpeL / ACE
lessons with helpful / harmful votes, Voyager's "promote what verified work proved" into a skill. No code vendored.

    a stage      STAGES: who does it (role + skills), what it needs (an approved upstream stage), the tool it runs,
                 the checks its output must pass, how a retry changes its settings
    an asset     <workspace>/pipeline/<asset>/pipeline.json - the checkpoint: each stage's status, tries, versions,
                 approved version; notes.jsonl - review notes (owner, agent or a check), open until addressed
    a hand-off   <asset>/<stage>/v001/record.json (+ handoff.md): inputs (the upstream records), outputs with sha256,
                 settings, the checks and their verdict, lessons used, notes addressed. The next stage gets THIS -
                 never a chat log
    lessons      <data>/pipeline/lessons.jsonl - one line per lesson {stage, kind, text, helpful, harmful}; written
                 when a check fails and when a changed setting fixed it; voted up when a stage that used it passes,
                 down when it fails; gone at score 0; promoted into a learned skill (skills/learned/pipeline-<stage>)
                 once it has helped 5 times and never hurt
    settings     <data>/pipeline/params.jsonl - what each try ran with and whether it passed; the next asset of the
                 same kind starts from the last settings that passed

Statuses: waiting (an upstream stage is not approved) -> ready -> wip -> approved | retake (3 tries failed: it waits
for the owner or an agent with notes) ; omitted. A retake note on an earlier stage reopens it and sends everything
after it back to waiting (their versions are kept).

    python engine/asset_pipeline.py start "a moss golem guardian" [--kind creature] [--concept images/x.png]
    python engine/asset_pipeline.py status [asset]      advance <asset>      note <asset> <stage> "text" [--retake]
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

STATUSES = ("waiting", "ready", "wip", "approved", "retake", "omitted")
MAX_TRIES = 3
FRESH_WIP_S = 3 * 3600          # a wip older than this is a crashed run: it may start again
KINDS = ("character", "creature", "prop", "vehicle")
QUADS = {"prop": 3000, "vehicle": 6000, "character": 8000, "creature": 8000}
# retries walk through these; without an NVIDIA card (the Mac) the ComfyUI ones cannot run, so online comes first
BACKENDS = (("auto", "online", "triposr", "pixal3d", "trellis2") if sys.platform == "darwin"
            else ("auto", "pixal3d", "trellis2", "online", "triposr"))
LIKENESS = float(os.environ.get("LOKI_PIPELINE_LIKENESS", "0.6"))
VIEW_MATCH = float(os.environ.get("LOKI_PIPELINE_VIEW_MATCH", "0.45"))   # turnaround view vs concept colours
LOCK = threading.RLock()       # re-entrant: settling a stage also writes lessons


# ----------------------------------------------------------------------------- small helpers
def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:n].rstrip("-") or "asset"


def _now() -> float:
    return time.time()


def _read(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _jsonl(path: Path) -> list:
    out = []
    try:
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _jsonl_write(path: Path, rows: list) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def data_dir() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data"))


# ----------------------------------------------------------------------------- checks (Pyblish "validate")
# Each check: (ctx) -> (ok, detail, hint). `hint` says what to change - it becomes the lesson and the retry's note.
def _image_ok(path: Path, min_side: int = 512) -> tuple:
    try:
        head = path.read_bytes()[:12]
    except OSError:
        return False, "missing: %s" % path.name
    if not (head.startswith(b"\x89PNG") or head[:3] == b"\xff\xd8\xff" or head[8:12] == b"WEBP"):
        return False, "%s is not a picture" % path.name
    try:
        from PIL import Image, ImageStat  # pylint: disable=import-outside-toplevel
        with Image.open(path) as im:
            if min(im.size) < min_side:
                return False, "%s is only %dx%d" % (path.name, im.size[0], im.size[1])
            spread = max(ImageStat.Stat(im.convert("L").resize((64, 64))).stddev)
            if spread < 6:
                return False, "%s is blank (one flat colour)" % path.name
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return False, "%s does not open: %s" % (path.name, exc)
    return True, path.name


def glb_triangles(path: Path) -> int:
    """Triangles in a .glb from its JSON chunk (indices / 3, else positions / 3) - no 3D library needed."""
    import struct  # pylint: disable=import-outside-toplevel
    try:
        b = Path(path).read_bytes()
        if b[:4] != b"glTF":
            return -1
        n = struct.unpack("<I", b[12:16])[0]
        j = json.loads(b[20:20 + n])
    except (OSError, ValueError, struct.error):
        return -1
    acc = j.get("accessors") or []
    tris = 0
    for m in j.get("meshes") or []:
        for p in m.get("primitives") or []:
            if p.get("mode", 4) != 4:
                continue
            i = p.get("indices")
            cnt = acc[i]["count"] if i is not None and i < len(acc) else acc[p.get("attributes", {}).get("POSITION", 0)]["count"]
            tris += cnt // 3
    return tris


def check_files(ctx) -> tuple:
    files = [Path(f) for f in ctx["outputs"]]
    missing = [f.name for f in files if not f.is_file()]
    if not files:
        return False, "the tool made no files", "run the stage's tool again; read its error"
    return (not missing), ("all %d files are there" % len(files) if not missing else "missing: " + ", ".join(missing)), \
        "the tool said ok but wrote nothing - check its folder"


def check_pictures(ctx) -> tuple:
    pics = [Path(f) for f in ctx["outputs"] if Path(f).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if not pics:
        return False, "no picture among the outputs", "the stage must hand on a picture"
    bad = [d for ok, d in (_image_ok(p, ctx["stage"].get("min_side", 512)) for p in pics) if not ok]
    return (not bad), ("%d good pictures" % len(pics) if not bad else "; ".join(bad)), \
        "redraw with another seed; keep one subject on a plain background"


def check_views(ctx) -> tuple:
    rep = ctx["report"]
    views = rep.get("views") or {}
    need = [v for v in ("front", "side", "back") if v not in views]
    if need or rep.get("missing"):
        return False, "views missing: %s" % ", ".join(need or [str(m)[:60] for m in rep["missing"]]), \
            "draw the missing views on the same seed; a creature needs front, side and back for 3D"
    sil = rep.get("silhouette") or {}
    front_h = (sil.get("front") or [0, 0])[0]
    if front_h:
        bad = {v: hc for v, hc in sil.items() if v in ("side", "back") and hc[0] and abs(hc[0] - front_h) / front_h > 0.12}
        off = {v: hc for v, hc in sil.items() if v in ("front", "side", "back") and abs(hc[1]) > 0.08}
        if bad or off:
            return False, "views do not line up: %s" % ", ".join(
                ["%s height %.0f%% of front" % (v, 100 * hc[0] / front_h) for v, hc in bad.items()] +
                ["%s off-centre %.0f%%" % (v, 100 * hc[1]) for v, hc in off.items()]), \
                "same scale and centred in every view: full body in frame, same margin, feet on one line"
    concept = ""
    con = (ctx.get("inputs") or {}).get("concept")
    if con:
        concept = next((o for o in con.get("outputs") or [] if Path(o).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                        and Path(o).is_file()), "")
    modes = rep.get("mode") or {}
    if concept and modes and all(str(m).startswith("text") for m in modes.values()):
        return False, "the views were drawn from text, not from the concept picture (mode %s)" % ", ".join(
            sorted(set(map(str, modes.values())))), "make them FROM the concept: a model that takes a reference picture"
    match = dict(rep.get("colour_match") or {})
    if concept and not match:   # an older turnaround (no scores): score it now
        try:
            import turnaround as _ta  # pylint: disable=import-outside-toplevel
            for v in ("front", "side", "back"):
                f = next((o for o in ctx["outputs"] if Path(o).stem == v and Path(o).is_file()), "")
                if f:
                    match[v] = _ta.colour_match(concept, f)
        except Exception:  # noqa: BLE001
            pass
    off = {v: m for v, m in match.items() if m < VIEW_MATCH}
    if off:
        return False, "views do not match the concept's colours: %s (mode %s)" % (
            ", ".join("%s %.2f" % kv for kv in off.items()), rep.get("mode") or "?"), \
            "draw the views FROM the concept (an edit-capable model: FLUX.2 klein on NVIDIA), not from text"
    return True, "front, side, back (+%d)%s" % (len(views) - 3, "; colour match " + ", ".join(
        "%s %.2f" % kv for kv in match.items()) if match else ""), ""


def check_model(ctx) -> tuple:
    glbs = [Path(f) for f in ctx["outputs"] if Path(f).suffix.lower() == ".glb"]
    if not glbs:
        return False, "no .glb", "make_3d must hand on a .glb"
    tris = glb_triangles(glbs[0])
    backend = str(ctx["report"].get("backend") or "")
    if backend == "lift":
        return False, "made by 'lift' (a puffy silhouette, not a model)", \
            "ComfyUI was not reachable: start it or use another backend (pixal3d, trellis2, online)"
    if tris < ctx["stage"].get("min_tris", 1000):
        return False, "only %d triangles" % tris, "the model came out empty or broken: try another backend"
    return True, "%d triangles (%s)" % (tris, backend or "?"), ""


def check_likeness(ctx) -> tuple:
    """Does the model look like its picture? forge_judge renders it from four sides and asks a vision model
    (owner 2026-10-26: "looks nothing like images they are making"). Under LIKENESS fails; a judge that could not
    look passes but says so in the record (a missing vision model must not stop every asset)."""
    j = ctx["report"].get("judge") or {}
    if j.get("score") is None:
        return True, "not judged: %s" % (j.get("error") or "no vision model answered"), ""
    score = float(j["score"])
    if score < LIKENESS:
        missing = ", ".join(j.get("missing") or [])
        return False, "looks %d%% like the picture (shape %s, colour %s)%s - %s" % (
            score * 100, j.get("shape"), j.get("colour"), ("; missing " + missing) if missing else "",
            j.get("note") or ""), "another backend, or a cleaner front view (one subject, plain background)"
    return True, "looks %d%% like the picture" % (score * 100), ""


def check_topology(ctx) -> tuple:
    topo = ctx["report"].get("topology") or {}
    if not topo:
        return False, "no topology report", "polish with retopo so the mesh is measured"
    probs = []
    if topo.get("verdict") != "quads":
        probs.append("verdict %s" % topo.get("verdict"))
    if float(topo.get("quad_pct") or 0) < 95:
        probs.append("quads %s%%" % topo.get("quad_pct"))
    if float(topo.get("pole_pct") or 100) > 8:
        probs.append("poles %s%%" % topo.get("pole_pct"))
    if probs:
        return False, ", ".join(probs), "raise the quad count (faces) or rebuild finer; thin parts need more faces"
    return True, "%s faces, %s%% quads, %s%% poles (%s)" % (topo.get("faces"), topo.get("quad_pct"),
                                                           topo.get("pole_pct"), topo.get("retopo", "?")), ""


def check_quality(ctx) -> tuple:
    q = ctx["report"].get("quality") or {}
    if q.get("verdict") == "garbage":
        return False, "repair says garbage: %s" % ", ".join(q.get("problems") or []), \
            "the model itself is broken - send the model stage back (retake) instead of polishing it"
    return True, "repair: %s" % (q.get("verdict") or "not run"), ""


def check_formats(ctx) -> tuple:
    have = {Path(f).suffix.lower() for f in ctx["outputs"]}
    need = [x for x in (".glb", ".fbx") if x not in have]
    return (not need), ("formats: " + ", ".join(sorted(have)) if not need else "missing " + ", ".join(need)), \
        "export again; FBX needs Blender's FBX exporter"


CHECKS = {"files": check_files, "pictures": check_pictures, "views": check_views, "model": check_model,
          "likeness": check_likeness,
          "topology": check_topology, "quality": check_quality, "formats": check_formats}


# ----------------------------------------------------------------------------- the stages
def _first(outputs, exts):
    return next((o for o in outputs if Path(o).suffix.lower() in exts), "")


def _files(rec: dict) -> list:
    """A hand-off's outputs as the tools want them: relative to the workspace when inside it."""
    return rec.get("outputs_rel") or rec.get("outputs") or []


def _args_concept(asset, inputs, params):
    tall = asset["kind"] in ("character", "creature")
    return "make_image", {"prompt": asset["brief"], "style": params.get("style", "game-concept"), "folder": "images",
                          "width": 768 if tall else 1024, "height": 1024, **({"seed": params["seed"]} if params.get("seed") else {})}


def _args_turnaround(asset, inputs, params):
    concept = _first(_files(inputs["concept"]), (".png", ".jpg", ".jpeg", ".webp"))
    return "make_turnaround", {"concept": concept, "subject": asset["brief"], "kind": asset["kind"],
                               **({"seed": params["seed"]} if params.get("seed") else {})}


def _args_model(asset, inputs, params):
    views = inputs["turnaround"]["report"].get("views") or {}
    front = views.get("front") or _first(_files(inputs["turnaround"]), (".png",))
    return "make_3d", {"image": front, "prompt": asset["brief"], "backend": params.get("backend", "auto"),
                       "judge": os.environ.get("LOKI_PIPELINE_JUDGE", "on") != "off",
                       **({"seed": params["seed"]} if params.get("seed") else {})}


def _args_finish(asset, inputs, params):
    glb = _first(_files(inputs["model"]), (".glb",))
    return "blender", {"action": "polish", "path": glb, "name": asset["name"],
                       "retopo": int(params.get("faces") or QUADS.get(asset["kind"], 8000)),
                       "symmetric": bool(params.get("symmetric", False))}


def _args_render(asset, inputs, params):
    glb = _first(_files(inputs["finish"]), (".glb",))
    return "render_scene", {"model": glb, **({"prompt": params["prompt"]} if params.get("prompt") else {})}


def _retry_concept(params, failed, tries, kind=""):
    return dict(params, seed=int(params.get("seed") or 1000) + 7919 * tries)


def _retry_model(params, failed, tries, kind=""):
    cur = params.get("backend", "auto")
    nxt = BACKENDS[(BACKENDS.index(cur) + 1) % len(BACKENDS)] if cur in BACKENDS else "pixal3d"
    return dict(params, backend=nxt, seed=int(params.get("seed") or 7) + 7919 * int(tries or 1))


def _retry_finish(params, failed, tries, kind="creature"):
    if "topology" in failed or str(failed).startswith("retake"):
        return dict(params, faces=min(15000, int((params.get("faces") or QUADS.get(kind, 8000)) * 1.5)))
    return dict(params)


STAGES = [
    {"name": "concept", "needs": [], "role": "Concept Artist", "lane": "gpu", "args": _args_concept,
     "checks": ["files", "pictures"], "retry": _retry_concept,
     "expected": "one picture of the subject: full body, one subject, plain background, readable silhouette"},
    {"name": "turnaround", "needs": ["concept"], "role": "Technical Artist", "lane": "gpu", "args": _args_turnaround,
     "checks": ["files", "pictures", "views"], "retry": _retry_concept,
     "expected": "orthographic front / side / back (+ top) views of the SAME design, T-pose for characters"},
    {"name": "model", "needs": ["turnaround"], "role": "3D Artist", "lane": "gpu", "args": _args_model,
     "checks": ["files", "model", "likeness"], "retry": _retry_model, "min_tris": 1000,
     "expected": "a textured .glb from the front view that matches the side and back views"},
    {"name": "finish", "needs": ["model"], "role": "3D Finisher", "lane": "cpu", "args": _args_finish,
     "skills": ["blender-gameready", "gameready-retopo", "gameready-uv-bake", "gameready-qa"],
     "checks": ["files", "quality", "topology", "formats"], "retry": _retry_finish,
     "expected": "clean quads (>=95%, poles <=8%), colour + normal map baked, .glb .gltf .fbx .blend + LODs, a render"},
    {"name": "render", "needs": ["finish"], "role": "Lighting / Render", "lane": "gpu", "args": _args_render,
     "checks": ["files", "pictures"], "retry": lambda p, f, t, k="": dict(p), "min_side": 256,
     "expected": "render passes of the finished model (and an AI still when a prompt is given)"},
]
BY_NAME = {s["name"]: s for s in STAGES}
ORDER = [s["name"] for s in STAGES]


def downstream(stage: str) -> list:
    """Every stage that depends on `stage`, directly or not, in pipeline order."""
    out, frontier = [], {stage}
    for s in STAGES:
        if frontier & set(s["needs"]):
            out.append(s["name"])
            frontier.add(s["name"])
    return out


# ----------------------------------------------------------------------------- lessons (Reflexion / ExpeL / ACE)
def lessons_path() -> Path:
    return data_dir() / "pipeline" / "lessons.jsonl"


def _score(lesson: dict) -> int:
    return 2 + int(lesson.get("helpful", 0)) - int(lesson.get("harmful", 0))


def add_lesson(stage: str, kind: str, text: str, source: str = "") -> dict:
    """ADD - or UPVOTE the lesson that already says this (similarity > 0.9): no duplicates, no rewrite of the list."""
    text = " ".join(str(text).split())[:400]
    with LOCK:
        rows = _jsonl(lessons_path())
        for r in rows:
            if r["stage"] == stage and r.get("kind") in (kind, "any") and \
                    difflib.SequenceMatcher(None, r["text"].lower(), text.lower()).ratio() > 0.9:
                r["helpful"] = int(r.get("helpful", 0)) + 1
                r["t"] = _now()
                _jsonl_write(lessons_path(), rows)
                return r
        lesson = {"id": "L" + hashlib.sha1((stage + kind + text).encode()).hexdigest()[:8], "stage": stage,
                  "kind": kind, "text": text, "helpful": 0, "harmful": 0, "approved_uses": 0, "source": source,
                  "t": _now()}
        rows.append(lesson)
        _jsonl_write(lessons_path(), rows)
        return lesson


def vote(ids: list, good: bool) -> None:
    """After a stage that used these lessons: passed -> helpful+1 (and an approved use), failed -> harmful+1.
    A lesson whose score falls to 0 is deleted (ExpeL)."""
    if not ids:
        return
    with LOCK:
        rows = _jsonl(lessons_path())
        keep = []
        for r in rows:
            if r["id"] in ids:
                if good:
                    r["helpful"] = int(r.get("helpful", 0)) + 1
                    r["approved_uses"] = int(r.get("approved_uses", 0)) + 1
                else:
                    r["harmful"] = int(r.get("harmful", 0)) + 1
            if _score(r) > 0:
                keep.append(r)
        _jsonl_write(lessons_path(), keep)


def recall(stage: str, kind: str, brief: str = "", k: int = 6) -> list:
    """The lessons for this stage and kind, best first: score, then words shared with the brief."""
    words = set(re.findall(r"[a-z]{4,}", brief.lower()))
    rows = [r for r in _jsonl(lessons_path()) if r["stage"] == stage and r.get("kind") in (kind, "any")]
    rows.sort(key=lambda r: (_score(r), len(words & set(re.findall(r"[a-z]{4,}", r["text"].lower())))), reverse=True)
    return rows[:k]


def promote(stage: str, min_helpful: int = 5, min_uses: int = 3) -> Path | None:
    """Voyager: what proved itself (helped >= 5 times, never hurt, used in >= 3 approved runs) becomes the learned
    skill skills/learned/pipeline-<stage>/SKILL.md - the agents' skill catalog picks it up (engine/agents.py)."""
    proven = [r for r in _jsonl(lessons_path()) if r["stage"] == stage and int(r.get("helpful", 0)) >= min_helpful
              and not int(r.get("harmful", 0)) and int(r.get("approved_uses", 0)) >= min_uses]
    if not proven:
        return None
    proven.sort(key=_score, reverse=True)
    body = "\n".join("- (%s, helped %d) %s" % (r.get("kind", "any"), r["helpful"], r["text"]) for r in proven)[:3200]
    st = BY_NAME[stage]
    text = ("---\nname: pipeline-%s\ndescription: What LOKI's %s stage learned from its own checked work - read before "
            "doing the %s stage of an asset.\n---\n\n# %s: proven lessons\n\nExpected output: %s\n\n%s\n"
            % (stage, st["role"], stage, st["role"], st["expected"], body))
    path = data_dir() / "skills" / "learned" / ("pipeline-" + stage) / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- settings memory
def params_path() -> Path:
    return data_dir() / "pipeline" / "params.jsonl"


def remember_params(stage: str, kind: str, params: dict, ok: bool) -> None:
    rows = _jsonl(params_path())[-400:]
    rows.append({"stage": stage, "kind": kind, "params": {k: v for k, v in params.items() if k != "seed"},
                 "ok": bool(ok), "t": _now()})
    _jsonl_write(params_path(), rows)


def best_params(stage: str, kind: str) -> dict:
    """The settings of the last try that passed for this stage and kind (a new asset starts from what worked)."""
    for r in reversed(_jsonl(params_path())):
        if r["stage"] == stage and r["kind"] == kind and r["ok"]:
            return dict(r["params"])
    return {}


# ----------------------------------------------------------------------------- assets
def root(ws: Path) -> Path:
    return Path(ws) / "pipeline"


def asset_dir(ws: Path, asset_id: str) -> Path:
    return root(ws) / slug(asset_id, 60)


def load(ws: Path, asset_id: str) -> dict:
    a = _read(asset_dir(ws, asset_id) / "pipeline.json", None)
    if a is None:
        raise KeyError("no asset %s in %s" % (asset_id, root(ws)))
    return a


def save(ws: Path, asset: dict) -> None:
    asset["updated"] = _now()
    _write(asset_dir(ws, asset["id"]) / "pipeline.json", asset)


def assets(ws: Path) -> list:
    out = []
    if root(ws).is_dir():
        for p in sorted(root(ws).glob("*/pipeline.json")):
            a = _read(p, None)
            if a:
                out.append(a)
    return out


def _refresh(asset: dict) -> None:
    """waiting <-> ready from the upstream approvals."""
    for s in STAGES:
        st = asset["stages"][s["name"]]
        if st["status"] in ("waiting", "ready"):
            ok = all(asset["stages"][n]["status"] == "approved" for n in s["needs"])
            st["status"] = "ready" if ok else "waiting"


def start(ws: Path, brief: str, kind: str = "creature", name: str = "", concept: str = "", skip=()) -> dict:
    """A new asset. `concept`: a picture already in the workspace becomes the approved concept (after its checks)."""
    brief = " ".join(str(brief or "").split())
    if not brief:
        raise ValueError("describe the asset (brief)")
    kind = kind if kind in KINDS else "creature"
    name = slug(name or brief, 32)
    aid = name
    n = 2
    while (asset_dir(ws, aid) / "pipeline.json").is_file():
        aid = "%s-%d" % (name, n)
        n += 1
    asset = {"id": aid, "name": name, "brief": brief, "kind": kind, "created": _now(), "log": [],
             "stages": {s["name"]: {"status": "waiting", "tries": 0, "versions": [], "approved": None, "params": {}}
                        for s in STAGES}}
    for s in skip:
        if s in asset["stages"]:
            asset["stages"][s]["status"] = "omitted"
    _refresh(asset)
    save(ws, asset)
    if concept:
        submit(ws, aid, "concept", [concept], {"note": "the owner's picture"}, author="owner")
        asset = load(ws, aid)
    return asset


def _log(asset: dict, text: str) -> None:
    asset["log"] = (asset.get("log", []) + [{"t": _now(), "text": text[:300]}])[-80:]


def ref(asset_id: str, stage: str, which: str = "approved") -> str:
    return "loki://%s/%s@%s" % (asset_id, stage, which)


def resolve(ws: Path, reference: str) -> dict | None:
    """loki://<asset>/<stage>@approved|latest|v002 -> that version's record."""
    m = re.match(r"^loki://([^/]+)/([^@]+)@(\w+)$", str(reference))
    if not m:
        return None
    asset = load(ws, m.group(1))
    st = asset["stages"].get(m.group(2)) or {}
    v = st.get("approved") if m.group(3) == "approved" else (st["versions"][-1] if m.group(3) == "latest" and
                                                                st.get("versions") else m.group(3))
    return _read(asset_dir(ws, m.group(1)) / m.group(2) / str(v) / "record.json", None) if v else None


# ----------------------------------------------------------------------------- notes (ShotGrid-style review notes)
def notes(ws: Path, asset_id: str, stage: str = "", open_only: bool = False) -> list:
    rows = _jsonl(asset_dir(ws, asset_id) / "notes.jsonl")
    return [n for n in rows if (not stage or n["stage"] == stage) and (not open_only or n["status"] == "open")]


def note(ws: Path, asset_id: str, stage: str, text: str, author: str = "owner", retake: bool = False) -> dict:
    """A review note on a stage. retake=True reopens that stage (3 fresh tries) and sends every stage after it back
    to waiting - their versions stay on disk, the next run replaces them."""
    if stage not in BY_NAME:
        raise ValueError("stage is one of %s" % ", ".join(ORDER))
    load(ws, asset_id)                                   # KeyError for an asset that does not exist
    path = asset_dir(ws, asset_id) / "notes.jsonl"
    rows = _jsonl(path)
    n = {"id": "N%03d" % (len(rows) + 1), "stage": stage, "text": " ".join(str(text).split())[:800], "author": author,
         "status": "open", "t": _now()}
    rows.append(n)
    _jsonl_write(path, rows)
    if retake:
        with LOCK:
            asset = load(ws, asset_id)
            st = asset["stages"][stage]
            if st["status"] != "omitted":
                rejected = st.get("rejected") or []
                if st.get("approved"):     # its files must never come back unchanged (the Mac 2026-10-26: the
                    rec = _read(asset_dir(ws, asset_id) / stage / st["approved"] / "record.json", {})   # same model
                    rejected += [f.get("sha256") for f in rec.get("files") or [] if f.get("sha256")]   # 3 times)
                st.update(status="ready", tries=0, approved=None, retakes=int(st.get("retakes") or 0) + 1,
                          rejected=rejected[-60:], retake_note=n["text"][:300])
            for d in downstream(stage):
                if asset["stages"][d]["status"] != "omitted":
                    asset["stages"][d].update(status="waiting", tries=0, approved=None)
            _refresh(asset)
            _log(asset, "retake %s by %s: %s" % (stage, author, n["text"][:120]))
            save(ws, asset)
    return n


def _close_notes(ws: Path, asset_id: str, stage: str, version: str) -> list:
    path = asset_dir(ws, asset_id) / "notes.jsonl"
    rows, closed = _jsonl(path), []
    for n in rows:
        if n["stage"] == stage and n["status"] == "open":
            n.update(status="addressed", by=version)
            closed.append(n["id"])
    if closed:
        _jsonl_write(path, rows)
    return closed


# ----------------------------------------------------------------------------- the hand-off
def _inputs(ws: Path, asset: dict, stage: dict) -> dict:
    out = {}
    for n in stage["needs"]:
        v = asset["stages"][n]["approved"]
        rec = _read(asset_dir(ws, asset["id"]) / n / str(v) / "record.json", None) if v else None
        if rec is None:
            raise RuntimeError("%s needs an approved %s" % (stage["name"], n))
        out[n] = rec
    return out


def stage_brief(ws: Path, asset_id: str, stage_name: str) -> str:
    """What an agent doing this stage is given: the asset, the approved upstream hand-offs (files + what was
    checked), what to deliver, the checks it must pass, the lessons for this stage, the open notes."""
    asset, stage = load(ws, asset_id), BY_NAME[stage_name]
    lines = ["# %s - %s stage (%s)" % (asset["name"], stage_name, stage["role"]), "",
             "Asset: %s (%s). Brief: %s" % (asset["id"], asset["kind"], asset["brief"]),
             "Deliver: %s" % stage["expected"],
             "Checks it must pass before it is handed on: %s" % ", ".join(stage["checks"])]
    try:
        for n, rec in _inputs(ws, asset, stage).items():
            lines.append("From %s (%s, %s): %s" % (n, rec["version"], rec["verdict"], ", ".join(rec["outputs_rel"][:6])))
            lines += ["  checked: %s - %s" % (c["check"], c["detail"]) for c in rec["validation"]]
    except RuntimeError as exc:
        lines.append("Not ready: %s" % exc)
    lessons = recall(stage_name, asset["kind"], asset["brief"])
    if lessons:
        lines += ["", "Lessons from earlier %s work:" % stage_name] + ["- %s" % r["text"] for r in lessons]
    open_notes = notes(ws, asset_id, stage_name, open_only=True)
    if open_notes:
        lines += ["", "Open notes to address (say which in your report):"] + \
                 ["- %s (%s): %s" % (n["id"], n["author"], n["text"]) for n in open_notes]
    lines += ["", "When done: asset_pipeline action=submit asset=%s stage=%s files=[...] - or let LOKI run it: "
              "action=advance." % (asset_id, stage_name)]
    return "\n".join(lines)


def _record(ws: Path, asset: dict, stage: dict, version: str, inputs: dict, outputs: list, report: dict,
            params: dict, validation: list, lessons_used: list, author: str, seconds: float) -> dict:
    folder = asset_dir(ws, asset["id"]) / stage["name"] / version
    outs = []
    for f in outputs:
        p = Path(f)
        outs.append({"path": str(p), "bytes": p.stat().st_size if p.is_file() else 0,
                     "sha256": sha256(p) if p.is_file() and p.stat().st_size < 512 << 20 else ""})
    rel = []
    for f in outputs:
        try:
            rel.append(Path(f).resolve().relative_to(Path(ws).resolve()).as_posix())
        except ValueError:
            rel.append(str(f))
    ok = all(c["ok"] for c in validation)
    rec = {"id": ref(asset["id"], stage["name"], version), "asset": asset["id"], "stage": stage["name"],
           "version": version, "role": stage["role"], "author": author, "brief": asset["brief"], "kind": asset["kind"],
           "expected": stage["expected"], "inputs": {n: r["id"] for n, r in inputs.items()},
           "outputs": [o["path"] for o in outs], "outputs_rel": rel, "files": outs, "params": params,
           "report": {k: v for k, v in (report or {}).items() if isinstance(v, (str, int, float, bool, list, dict))
                      and len(json.dumps(v)) < 4000},
           "validation": validation, "verdict": "pass" if ok else "fail", "lessons_used": lessons_used,
           "seconds": round(seconds, 1), "created": _now()}
    _write(folder / "record.json", rec)
    md = ["# %s %s %s - %s" % (asset["name"], stage["name"], version, rec["verdict"].upper()), "",
          "By: %s (%s) in %.0f s" % (stage["role"], author, seconds), "Settings: %s" % json.dumps(params), "",
          "## Files"] + ["- %s" % r for r in rel] + ["", "## Checks"] + \
         ["- %s %s: %s" % ("PASS" if c["ok"] else "FAIL", c["check"], c["detail"]) for c in validation]
    (folder / "handoff.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return rec


def _validate(stage: dict, outputs: list, report: dict, inputs: dict | None = None, rejected=None) -> list:
    ctx = {"stage": stage, "outputs": outputs, "report": report or {}, "inputs": inputs or {}}
    out = []
    if rejected:          # a retake that made the very same files again is not a retake
        same = [Path(o).name for o in outputs if Path(o).is_file() and sha256(Path(o)) in set(rejected)]
        if same:
            return [{"check": "new", "ok": False, "detail": "the same files as the version that was sent back: %s"
                     % ", ".join(same[:3]), "hint": "change the input or the settings - a rejected result must not "
                     "come back unchanged"}]
    for name in stage["checks"]:
        try:
            ok, detail, hint = CHECKS[name](ctx)
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed check, never a pass
            ok, detail, hint = False, "check crashed: %s: %s" % (type(exc).__name__, exc), "fix the check"
        out.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300], "hint": "" if ok else hint})
        if not ok and name == "files":
            break
    return out


def _outputs(ws: Path, result: dict) -> list:
    """The files a tool says it made, as absolute paths. Tools answer {"files": [..]} (make_image, make_3d,
    make_turnaround, render_scene), {"files": {"models": [..], "render": ..}} (blender polish) or a single "file"."""
    f = result.get("files")
    if isinstance(f, dict):
        files = list(f.get("models") or []) + ([f["render"]] if f.get("render") else [])
    elif isinstance(f, str):
        files = [f]
    else:
        files = list(f or [])
    if isinstance(result.get("file"), str):
        files.append(result["file"])
    out = []
    for x in files:
        p = Path(str(x))
        out.append(str(p if p.is_absolute() else Path(ws) / p))
    return list(dict.fromkeys(out))


def _settle(ws: Path, asset_id: str, stage: dict, outputs: list, report: dict, params: dict, lessons: list,
            author: str, seconds: float) -> dict:
    """Validate, record a version, approve or count the failed try (and learn from it either way)."""
    with LOCK:
        asset = load(ws, asset_id)
        st = asset["stages"][stage["name"]]
        try:
            inputs = _inputs(ws, asset, stage)
        except RuntimeError:
            inputs = {}
        validation = _validate(stage, outputs, report, inputs, st.get("rejected"))
        version = "v%03d" % (len(st["versions"]) + 1)
        rec = _record(ws, asset, stage, version, inputs, outputs, report, params, validation,
                      [r["id"] for r in lessons], author, seconds)
        st["versions"].append(version)
        failed = [c for c in validation if not c["ok"]]
        remember_params(stage["name"], asset["kind"], params, not failed)
        if not failed:
            st.update(status="approved", approved=version, params=params)
            rec["notes_addressed"] = _close_notes(ws, asset_id, stage["name"], version)
            _write(asset_dir(ws, asset_id) / stage["name"] / version / "record.json", rec)
            _log(asset, "%s %s approved (%s)" % (stage["name"], version, "; ".join(c["detail"] for c in validation)[:160]))
            if st["tries"] > 0 and st.get("last_failed"):     # it failed before and a changed setting fixed it
                changed = {k: v for k, v in params.items() if st.get("last_params", {}).get(k) != v and k != "seed"}
                if changed:
                    add_lesson(stage["name"], asset["kind"], "When %s fails, %s fixed it (%s)."
                               % (st["last_failed"], ", ".join("%s=%s" % kv for kv in changed.items()),
                                  asset["brief"][:60]), source=rec["id"])
        else:
            st["tries"] += 1
            st["last_failed"] = ", ".join(c["check"] for c in failed)
            st["last_params"] = params
            for c in failed:
                add_lesson(stage["name"], asset["kind"], "%s check failed: %s. %s" % (c["check"], c["detail"], c["hint"]),
                           source=rec["id"])
            if st["tries"] >= MAX_TRIES:
                st["status"] = "retake"
                _log(asset, "%s needs you: %d tries failed (%s)" % (stage["name"], st["tries"], st["last_failed"]))
            else:
                st["status"] = "ready"
                _log(asset, "%s %s failed (%s) - try %d of %d next" % (stage["name"], version, st["last_failed"],
                                                                     st["tries"] + 1, MAX_TRIES))
        vote([r["id"] for r in lessons], not failed)
        _refresh(asset)
        save(ws, asset)
    if not failed:
        promote(stage["name"])
    return rec


def submit(ws: Path, asset_id: str, stage_name: str, files: list, report: dict | None = None,
           author: str = "agent") -> dict:
    """An agent (or the owner) hands in a stage's work: it goes through the same checks as LOKI's own run."""
    stage = BY_NAME[stage_name]
    asset = load(ws, asset_id)
    if asset["stages"][stage_name]["status"] in ("waiting", "omitted"):
        raise RuntimeError("%s is %s" % (stage_name, asset["stages"][stage_name]["status"]))
    outs = [str(Path(f) if Path(f).is_absolute() else Path(ws) / f) for f in files]
    rep = dict(report or {})
    if stage_name == "turnaround" and "views" not in rep:      # read the turnaround's own record
        tj = next((Path(o).parent / "turnaround.json" for o in outs if (Path(o).parent / "turnaround.json").is_file()), None)
        if tj:
            info = _read(tj, {})
            rep.update(views=info.get("views") or {}, missing=info.get("missing") or [])
    return _settle(ws, asset_id, stage, outs, rep, {}, recall(stage_name, asset["kind"], asset["brief"]), author, 0.0)


def next_stage(asset: dict) -> str:
    _refresh(asset)
    return next((n for n in ORDER if asset["stages"][n]["status"] == "ready"), "")


def advance(ws: Path, asset_id: str, call=None, stage_name: str = "") -> dict:
    """Run the next ready stage with its tool (make_mcp.call), check it, hand it on. One stage per call."""
    if call is None:
        import make_mcp  # pylint: disable=import-outside-toplevel
        call = make_mcp.call
    with LOCK:
        asset = load(ws, asset_id)
        name = stage_name or next_stage(asset)
        if not name:
            return {"ok": True, "asset": asset_id, "idle": True, "status": summary(asset)}
        stage, st = BY_NAME[name], asset["stages"][name]
        if st["status"] != "ready":
            return {"ok": False, "error": "%s is %s" % (name, st["status"])}
        inputs = _inputs(ws, asset, stage)
        params = dict(best_params(name, asset["kind"]))
        params.update(st.get("params") or {})
        if st["tries"]:                       # a retry changes what the failed check points at (CrewAI guardrail)
            params = stage["retry"](st.get("last_params") or params, st.get("last_failed", ""), st["tries"],
                                    asset["kind"])
        elif st.get("retakes"):               # sent back by a review note: never the same run again - new seed and
            n = int(st["retakes"])            # the stage's own "try something else" (another backend, more quads...)
            params = stage["retry"](dict(params, **(st.get("params") or {})), "retake " + str(st.get("retake_note", "")),
                                    n, asset["kind"])
            params["seed"] = int(params.get("seed") or 1000) + 104729 * n
        tool, args = stage["args"](asset, inputs, params)
        st.update(status="wip", started=_now())
        _log(asset, "%s started by %s (%s, try %d)" % (name, stage["role"], tool, st["tries"] + 1))
        save(ws, asset)
    lessons = recall(name, asset["kind"], asset["brief"])
    t0 = _now()
    try:
        result = call(tool, args, Path(ws)) or {}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    report = dict(result)
    if not result.get("ok"):
        report["error"] = str(result.get("error") or "the tool failed")[:400]
    outputs = _outputs(ws, result) if result.get("ok") else []
    rec = _settle(ws, asset_id, stage, outputs, report, params, lessons, "loki", _now() - t0)
    if not result.get("ok"):
        rec["error"] = report["error"]
    return {"ok": rec["verdict"] == "pass", "stage": name, "version": rec["version"], "record": rec["id"],
            "checks": rec["validation"], "error": rec.get("error", ""), "status": summary(load(ws, asset_id))}


def summary(asset: dict) -> dict:
    return {n: "%s%s" % (asset["stages"][n]["status"], (" " + asset["stages"][n]["approved"])
                         if asset["stages"][n].get("approved") else "") for n in ORDER}


def active(ws: Path) -> list:
    """Assets with work to do (a ready stage), oldest first."""
    return [a for a in sorted(assets(ws), key=lambda a: a.get("created", 0)) if next_stage(a)]


def busy(ws: Path) -> str:
    for a in assets(ws):
        for n in ORDER:
            st = a["stages"][n]
            if st["status"] == "wip" and _now() - float(st.get("started") or 0) < FRESH_WIP_S:
                return "%s/%s" % (a["id"], n)
    return ""


def recover(ws: Path) -> int:
    """A wip left by a crash (older than FRESH_WIP_S) goes back to ready."""
    n = 0
    for a in assets(ws):
        changed = False
        for name in ORDER:
            st = a["stages"][name]
            if st["status"] == "wip" and _now() - float(st.get("started") or 0) >= FRESH_WIP_S:
                st["status"] = "ready"
                changed = True
                n += 1
        if changed:
            save(ws, a)
    return n


def tick(ws: Path, call=None, thread: bool = True) -> str:
    """The autopilot's duty: when no stage is running, start the next ready stage of the oldest asset (in a
    background thread - a 3D stage takes minutes). Returns what it started, or ""."""
    recover(ws)
    if busy(ws):
        return ""
    try:   # another heavy job (Blender, a local model) is running on this computer: wait for it (engine/heavy.py)
        import heavy  # pylint: disable=import-outside-toplevel
        if heavy.busy():
            return ""
    except ImportError:
        pass
    todo = active(ws)
    if not todo:
        return ""
    a = todo[0]
    name = next_stage(a)
    if thread:
        threading.Thread(target=advance, args=(ws, a["id"], call), daemon=True, name="pipeline-" + a["id"]).start()
    else:
        advance(ws, a["id"], call)
    return "pipeline: %s -> %s (%s)" % (a["id"], name, BY_NAME[name]["role"])


# ----------------------------------------------------------------------------- the agents' tool
TOOL = {"name": "asset_pipeline",
        "description": "LOKI's studio pipeline for one asset: concept -> turnaround -> model -> finish (Blender "
                       "retopo, bake, FBX/GLB) -> render. Each stage's work is checked before it is handed on; "
                       "3 failed tries -> it waits with notes. action=start {brief, kind character|creature|prop|"
                       "vehicle, concept=<a picture here, optional>}; status {asset?}; brief {asset, stage} = what "
                       "the stage is given (upstream files + checks, lessons, open notes); advance {asset} = LOKI "
                       "runs the next ready stage; submit {asset, stage, files[]} = hand in work you made yourself; "
                       "note {asset, stage, text, retake=true reopens it and everything after}; lessons {stage}.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["start", "status", "brief", "advance", "submit", "note", "lessons"]},
            "asset": {"type": "string"}, "stage": {"type": "string", "enum": ORDER}, "brief": {"type": "string"},
            "kind": {"type": "string", "enum": list(KINDS)}, "concept": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}}, "text": {"type": "string"},
            "retake": {"type": "boolean"}}, "required": ["action"]}}


def tool(args: dict, cwd: Path, call=None) -> dict:
    a = args or {}
    act = str(a.get("action") or "status")
    try:
        if act == "start":
            asset = start(cwd, str(a.get("brief") or ""), str(a.get("kind") or "creature"), concept=str(a.get("concept") or ""))
            return {"ok": True, "asset": asset["id"], "status": summary(asset), "next": next_stage(asset)}
        if act == "status":
            if a.get("asset"):
                asset = load(cwd, str(a["asset"]))
                return {"ok": True, "asset": asset["id"], "status": summary(asset), "log": asset["log"][-8:],
                        "notes": notes(cwd, asset["id"], open_only=True)}
            return {"ok": True, "assets": {x["id"]: summary(x) for x in assets(cwd)}}
        if act == "brief":
            return {"ok": True, "brief": stage_brief(cwd, str(a["asset"]), str(a.get("stage") or next_stage(load(cwd, str(a["asset"]))) or "concept"))}
        if act == "advance":
            return advance(cwd, str(a["asset"]), call, str(a.get("stage") or ""))
        if act == "submit":
            rec = submit(cwd, str(a["asset"]), str(a["stage"]), list(a.get("files") or []), author="agent")
            return {"ok": rec["verdict"] == "pass", "record": rec["id"], "checks": rec["validation"]}
        if act == "note":
            return {"ok": True, "note": note(cwd, str(a["asset"]), str(a["stage"]), str(a.get("text") or ""),
                                             "agent", bool(a.get("retake")))}
        if act == "lessons":
            return {"ok": True, "lessons": recall(str(a.get("stage") or "finish"), str(a.get("kind") or "creature"), k=20)}
    except (KeyError, ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "unknown action %s" % act}


def main(argv: list) -> int:
    ws = Path(os.environ.get("LOKI_WORKSPACE") or (Path.home() / "LOKI Projects" / "Home"))
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    def opt(name, default=""):
        return rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else default
    if cmd == "start":
        print(json.dumps(tool({"action": "start", "brief": rest[0] if rest else "", "kind": opt("--kind", "creature"),
                               "concept": opt("--concept")}, ws), indent=1))
    elif cmd == "status":
        print(json.dumps(tool({"action": "status", "asset": rest[0] if rest else ""}, ws), indent=1))
    elif cmd == "advance":
        print(json.dumps(tool({"action": "advance", "asset": rest[0]}, ws), indent=1, default=str))
    elif cmd == "brief":
        print(stage_brief(ws, rest[0], rest[1] if len(rest) > 1 else next_stage(load(ws, rest[0]))))
    elif cmd == "note":
        print(json.dumps(tool({"action": "note", "asset": rest[0], "stage": rest[1], "text": rest[2],
                               "retake": "--retake" in rest}, ws), indent=1))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(sys.argv[1:]))
