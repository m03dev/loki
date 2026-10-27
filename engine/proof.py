"""Proof, not claims: a task is done only when what it was asked to make really exists and is real (owner 2026-10-27:
"i dont like these fake results i want things done right").

Seen on the PC (2026-10-27): the "music loop" standing goal reported DONE 21 times overnight and music/ stayed EMPTY;
the sprite goal said DONE 25 times and made one sprite. A team's verdict was the agent's own word. Research on agent
verification says the same thing: an agent's self-report is not evidence - check the outcome (the artifact), and add
negative invariants (every file it CLAIMS must exist). This module does that, from the outside, with no model:

  expect(text)          what the request asks to be made: image / sprite / 3d / audio / video / render / doc / named
                        files ("write qa/x.md", "into sprites/") - from its words, no guessing beyond them
  check(text, files, answer, workspace)
                        {ok, kinds, problems, evidence}: for each expected kind, at least one NEW file of that kind in
                        the run window that passes its real-file check; every path the answer names exists; a named
                        file exists; "DONE" with nothing made is not done
  real-file checks      picture: decodes, at least 32x32, not one flat colour, not a "-weak-draft"; sprite: some opaque
                        pixels; 3D: a glTF/GLB that parses with at least one mesh and 12+ vertices (OBJ/FBX: size and
                        vertex lines); audio: WAV with 2+ s of samples, other formats 20 KB+; video: 50 KB+; text: 120+
                        characters that are not only the request repeated

Used by the autopilot when a team finishes (task_board): an unproven "done" is a failure with the reason, so a request
is tried again and a standing goal that keeps faking rests. Standard library + Pillow (already a requirement).
"""
from __future__ import annotations

import json
import re
import struct
import wave
from pathlib import Path

IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MODEL = {".glb", ".gltf", ".obj", ".fbx", ".blend"}
AUDIO = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
VIDEO = {".mp4", ".webm", ".mov", ".gif"}
TEXT = {".md", ".txt", ".json", ".html", ".csv"}

# what words in a request mean it must make that kind of thing (order: the most specific first)
WANTS = [
    ("sprite", re.compile(r"\b(sprite|pixel[- ]?art|pixelize|make_sprite)\b", re.I)),
    ("3d", re.compile(r"\b(3d model|3d prop|3d asset|make_3d|\.glb|glb\b|mesh|retopo\w*|lods?\b|hunyuan|trellis|"
                      r"pixal3d|triposr|blender tool|textured 3d|creature as)", re.I)),
    ("audio", re.compile(r"\b(music|loop|song|soundtrack|sound effect|sfx|voice line|read [\w ]{0,24}aloud|voice tool|tts|"
                         r"make_music)\b", re.I)),
    ("video", re.compile(r"\b(video|turntable\.mp4|trailer|clip|animation file|mp4)\b(?![- ]?(scripts?|ideas?|concepts?))", re.I)),
    ("render", re.compile(r"\b(render(s|ed)?|render_scene|beauty pass|turntable)\b", re.I)),
    ("image", re.compile(r"\b(picture|image|concept art|painting|illustration|logo|make_image|turnaround|drawing|art\b)", re.I)),
    ("doc", re.compile(r"\b(write|draft|post|devlog|caption|report|summary|plan|ad (copy|draft)|names?)\b", re.I)),
]
# requests that only check or install something make nothing we can look at: their proof is their named qa file
CHECK_ONLY = re.compile(r"^\s*(\[\w+\]\s*)*(do first\s*-\s*)?(check|startup time|local model check|install|update|"
                        r"setup|set up|prove|proof|test)\b", re.I)
# a named file is something to MAKE only when the request says so ("write qa/x.md", "save it into sprites/a.png");
# qa/ files are always the task's own report. Other named files are inputs ("from images/...", "rows of docs/...").
OUTPUT_VERB = re.compile(r"\b(write|writes|save|saved|into|to|as|create|export|copy|put|paste|report)\b[^.\n]{0,40}$", re.I)
WRITE_FIRST = re.compile(r"^(write|draft|research|summari[sz]e|list|outline|plan)\b", re.I)
NAMED = re.compile(r"(?<![\w./-])((?:qa|images|sprites|models|renders|music|audio|video|videos|turnarounds|brand|scenes|"
                   r"docs)/[\w.\-/<>*]+\.(?:md|png|jpg|glb|gltf|wav|mp3|ogg|mp4|json|txt|fbx|blend))", re.I)
CLAIMED = re.compile(r"(?<![\w-])((?:[\w.\-]+/)+[\w.\-]+\.(?:png|jpe?g|webp|gif|glb|gltf|obj|fbx|blend|wav|mp3|ogg|flac|"
                     r"mp4|webm|mov|md|txt|json))\b", re.I)


def kind_of(path: str) -> str:
    p = str(path).lower()
    ext = Path(p).suffix
    if ext in MODEL:
        return "3d"
    if ext in AUDIO:
        return "audio"
    if ext in {".mp4", ".webm", ".mov"}:
        return "video"
    if ext in IMG:
        if "sprite" in p or p.startswith("sprites/"):
            return "sprite"
        if p.startswith("renders/"):
            return "render"
        return "image"
    if ext in TEXT:
        return "doc"
    return ""


def expect(text: str) -> dict:
    """{"kinds": [...], "named": [...], "check_only": bool} for a request or goal."""
    t = str(text or "")
    t = re.split(r"\n\n\(Try \d+ of \d+\.", t)[0]   # retry notes are not part of what was asked
    named = set()
    for m in NAMED.finditer(t):
        rel = m.group(1)
        if "<" in rel or "*" in rel:
            continue
        if rel.lower().startswith("qa/") or OUTPUT_VERB.search(t[max(0, m.start() - 60):m.start()]):
            named.add(rel)
    named = sorted(named)
    # what to make is in the request's own words - not in its (parenthetical notes) or quotes of the owner
    core = re.sub(r"\([^()]*\)", " ", re.sub(r"\([^()]*\)", " ", t))
    core = re.sub(r'"[^"]{0,200}"', " ", core)
    head = re.sub(r"^\s*(\[\w+\]\s*)*(do first\s*-\s*)?([A-Z0-9 ]{3,30}:\s*)?", "", core).strip()
    kinds = []
    if WRITE_FIRST.search(head) or re.match(r"^[\w ]{2,30}:\s*(write|draft|research)\b", core.strip(), re.I):
        kinds = ["doc"]                  # "Write a devlog ...", "Brand name: research 20 names" - the text is the result
    else:
        # the deliverable is named in the first sentence ("Make one textured 3D prop ...", "3D ARTIST: take the newest
        # turnaround ... and make its model"); the rest is how - tools, notes, what to compare
        first = re.split(r"(?<=[a-z0-9)])\.\s|;\s|\n", head, maxsplit=1)[0][:260]
        lead = re.match(r"^\s*(\[\w+\]\s*)*(do first\s*-\s*)?([A-Z0-9 ]{3,30}):", core)
        scope = (lead.group(3) + " " if lead else "") + first
        for kind, rx in WANTS:
            if rx.search(scope):
                kinds.append(kind)
        if not kinds:
            for kind, rx in WANTS:
                if rx.search(core):
                    kinds.append(kind)
    if "3d" in kinds and "image" in kinds:
        kinds.remove("image")            # the picture is the model's input; the model is the deliverable
    if not kinds and not named and not CHECK_ONLY.search(t):
        kinds = ["doc"]                  # a kit, personas, a plan ... : something written must exist
    if "sprite" in kinds and "image" in kinds:
        kinds.remove("image")            # a sprite IS the picture
    if "render" in kinds and "3d" in kinds and not re.search(r"\brender\b.*\b(png|still|frame|pass)", t, re.I):
        kinds.remove("render")           # "3D model ... with a turntable" - the model is the proof
    if "doc" in kinds and len(kinds) > 1:
        kinds.remove("doc")              # "write" next to "make a picture" means the caption, not the deliverable
    check_only = bool(CHECK_ONLY.search(t))
    if check_only:
        kinds = [k for k in kinds if k == "doc"] if named else []
    return {"kinds": kinds, "named": named, "check_only": check_only}


# ------------------------------------------------------------------ real-file checks
def check_image(path: Path, sprite: bool = False) -> str:
    """"" when it is a real picture, else what is wrong."""
    if "weak-draft" in path.name:
        return "a weak draft (the fallback maker), not a real picture"
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            if w < 16 or h < 16 or (not sprite and (w < 32 or h < 32)):
                return "too small to be a picture (%dx%d)" % (w, h)
            rgba = im.convert("RGBA")
            small = rgba.resize((min(64, w), min(64, h)))
            px = list(small.getdata())
            opaque = [p for p in px if p[3] > 20]
            if sprite and len(opaque) < max(8, len(px) // 50):
                return "the sprite is (almost) all transparent"
            if not opaque:
                return "fully transparent"
            lo = [min(p[i] for p in opaque) for i in range(3)]
            hi = [max(p[i] for p in opaque) for i in range(3)]
            if max(h_ - l_ for h_, l_ in zip(hi, lo)) < 8:
                return "one flat colour - nothing drawn"
    except Exception as exc:  # noqa: BLE001
        return "does not open as a picture (%s)" % type(exc).__name__
    return ""


def _glb_json(path: Path) -> dict:
    data = path.read_bytes()
    if path.suffix.lower() == ".gltf":
        return json.loads(data.decode("utf-8"))
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file")
    length = struct.unpack_from("<I", data, 12)[0]
    if data[16:20] != b"JSON":
        raise ValueError("no JSON chunk")
    return json.loads(data[20:20 + length].decode("utf-8"))


def check_model(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        size = path.stat().st_size
    except OSError:
        return "missing"
    if ext in (".glb", ".gltf"):
        try:
            doc = _glb_json(path)
        except Exception as exc:  # noqa: BLE001
            return "not a valid glTF (%s)" % str(exc)[:60]
        meshes = doc.get("meshes") or []
        if not meshes:
            return "the file has no mesh"
        acc = doc.get("accessors") or []
        verts = 0
        for m in meshes:
            for prim in m.get("primitives") or []:
                i = (prim.get("attributes") or {}).get("POSITION")
                if isinstance(i, int) and i < len(acc):
                    verts += int(acc[i].get("count") or 0)
        if verts < 12:
            return "the mesh has only %d vertices" % verts
        return ""
    if ext == ".obj":
        try:
            n = sum(1 for line in path.open("r", encoding="utf-8", errors="replace") if line.startswith("v "))
        except OSError:
            return "cannot be read"
        return "" if n >= 12 else "the OBJ has only %d vertices" % n
    return "" if size >= 2000 else "too small to hold a model (%d bytes)" % size


def check_audio(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "missing"
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                secs = w.getnframes() / float(w.getframerate() or 1)
        except Exception as exc:  # noqa: BLE001
            return "not a valid WAV (%s)" % type(exc).__name__
        return "" if secs >= 2.0 else "only %.1f s of sound" % secs
    return "" if size >= 20_000 else "too small to be audio (%d bytes)" % size


def check_text(path: Path, request: str = "") -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "cannot be read"
    if len(text) < 120:
        return "almost empty (%d characters)" % len(text)
    if request and len(text) < 2 * len(request) and request.strip()[:200] in text:
        return "only repeats the request"
    return ""


def check_file(path: Path, kind: str, request: str = "") -> str:
    if not path.is_file():
        return "missing"
    if kind in ("image", "render"):
        return check_image(path)
    if kind == "sprite":
        return check_image(path, sprite=True)
    if kind == "3d":
        return check_model(path)
    if kind == "audio":
        return check_audio(path)
    if kind == "video":
        return "" if path.stat().st_size >= 50_000 else "too small to be a video"
    if kind == "doc":
        return check_text(path, request)
    return ""


def claimed(answer: str) -> list:
    """Paths the agent's answer says it made (relative, as written)."""
    out = []
    for m in CLAIMED.finditer(str(answer or "")):
        p = m.group(1).strip("./").replace("\\", "/")
        if p not in out and not p.startswith(("http", "www.")):
            out.append(p)
    return out[:30]


def check(text: str, files: list, answer: str, workspace) -> dict:
    """Is this finished task proven? files = what appeared in the workspace during the run (relative paths)."""
    ws = Path(workspace) if workspace else None
    want = expect(text)
    problems, evidence = [], []
    by_kind: dict = {}
    for rel in files or []:
        by_kind.setdefault(kind_of(rel), []).append(rel)
    for kind in want["kinds"]:
        cands = list(by_kind.get(kind, []))
        if kind == "image":
            cands += by_kind.get("render", [])
        if kind == "render":
            cands += by_kind.get("image", [])
        if not cands:
            problems.append("no %s was made" % {"3d": "3D model", "audio": "sound file", "doc": "written file"}.get(kind, kind))
            continue
        bad = []
        for rel in cands:
            why = check_file(ws / rel, kind, text) if ws else ""
            if not why:
                evidence.append(rel)
                break
            bad.append("%s: %s" % (rel, why))
        else:
            problems.append("the %s it made is not real - %s" % (kind, "; ".join(bad[:2])))
    for rel in want["named"]:
        if ws and not (ws / rel).is_file() and not any(f.endswith(rel) for f in files or []):
            problems.append("%s was asked for and does not exist" % rel)
        elif ws:
            evidence.append(rel)
    for rel in claimed(answer):
        if ws and not (ws / rel).exists() and not (Path(rel).is_absolute() and Path(rel).exists()):
            if kind_of(rel):
                problems.append("it says it made %s, which does not exist" % rel)
    if not want["kinds"] and not want["named"] and not files and not want["check_only"]:
        txt = str(answer or "").strip()
        if len(txt) < 40:
            problems.append("it made nothing and said almost nothing")
    return {"ok": not problems, "kinds": want["kinds"], "named": want["named"], "problems": problems[:6],
            "evidence": evidence[:8], "check_only": want["check_only"]}
