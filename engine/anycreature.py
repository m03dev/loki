"""anyCreature (contrib/anycreature/, MIT) behind LOKI: make a creature from a few controls, compile an
ACS spec into a .glb, and draw the front / side / top / hero views the gates judge.

    anycreature.available()                    Node + the vendored engine present?
    anycreature.schema()                       the FORM the UI draws: presets, sliders, colours
    anycreature.build_spec(controls)           controls -> an ACS spec (the details live here)
    anycreature.make_from_controls(c, out)     build + compile (with auto-fix) + render the views
    anycreature.compile_spec(spec, out_glb)    spec (a dict, JSON text, or a .json path) -> out_glb
    anycreature.render_views(glb, out_dir)     -> {"front": png, "side": png, "top": png, "hero": png}

The engine is zero-dependency Node (`node contrib/anycreature/engine/cli.js spec.json out.glb`); the
views are pure Python (numpy + pillow). "Handle the details in the backend": the engine names its own
fixes (a joint limit, the true standing height), so compile_spec applies them and retries - the user
only ever sees what cannot be repaired. The vendored code is unchanged (contrib/anycreature/NOTICE.md).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "contrib" / "anycreature"
ENGINE = VENDOR / "engine" / "cli.js"
OUTLINE = VENDOR / "harness" / "outline.py"
PRESETS_DIR = VENDOR / "presets"
VIEWS = ("front", "side", "top", "hero")
TIMEOUT = 300
LEG_JOINTS = {"LFrontRoot", "LFrontElbow", "LFrontWrist", "LFrontToe",
              "LBackRoot", "LBackKnee", "LBackHock", "LBackToe"}

# A starter creature is a whole skeleton, not a name: these are authored variants of the vendored
# example (different proportions and palettes, each compiled once to confirm it stands).
PRESETS = [
    {"id": "hound", "label": "Hound", "icon": "models", "what": "A steady, medium-legged quadruped."},
    {"id": "tall", "label": "Long-shanks", "icon": "layers", "what": "Long legs, compact body - a runner."},
    {"id": "low", "label": "Courser", "icon": "grid", "what": "Low and long, close to the ground."},
]
SLIDERS = [
    {"id": "size", "label": "Size", "min": 0.6, "max": 1.6, "step": 0.05, "value": 1.0,
     "what": "How big it stands - scales the whole creature, so its proportions and its walk stay right."},
    {"id": "smooth", "label": "Smooth", "min": 10, "max": 70, "step": 1, "value": 50,
     "what": "Higher = smoother body, lower = more facets."},
]
COLORS = [
    {"id": "body", "label": "Body colour", "value": "#6f6a5c"},
    {"id": "ear", "label": "Ear / accent", "value": "#8a3d14"},
]


class AnyCreatureError(RuntimeError):
    """The build was refused (a BLOCK: floor we could not repair), the engine is missing, or a view failed."""


def available() -> dict:
    node = shutil.which("node")
    return {"engine": ENGINE.is_file(), "outline": OUTLINE.is_file(), "node": bool(node),
            "ok": bool(node) and ENGINE.is_file() and OUTLINE.is_file()}


def schema() -> dict:
    """The form the UI draws - presets (icons), sliders and colour pickers - so the window needs no
    anyCreature knowledge of its own."""
    return {"presets": PRESETS, "sliders": SLIDERS, "colors": COLORS, "views": list(VIEWS)}


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise AnyCreatureError("Node is not installed (the anyCreature engine is Node)")
    return node


def _num(value, default, lo, hi) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def _hexcol(value) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else ""


def _safe_name(value) -> str:
    return "".join(c for c in str(value or "") if c.isalnum() or c in "-_")[:40]


def _load_preset(pid: str) -> dict:
    ids = {p["id"] for p in PRESETS}
    if pid not in ids:
        pid = PRESETS[0]["id"]
    path = PRESETS_DIR / (pid + ".json")
    if not path.is_file():
        raise AnyCreatureError("the starter %r is missing (%s)" % (pid, path))
    return json.loads(path.read_text(encoding="utf-8"))


def _scale_spec(spec: dict, k: float) -> None:
    """Scale every LENGTH in a spec by k - joint positions, profile radii, part sizes and thicknesses -
    and leave the unit-less numbers alone (profile t, anchors, angles, colours). Uniform, so the
    proportions and the tuned walk stay correct: only the creature's real-world size changes."""
    if k == 1.0:
        return
    sc = lambda v: round(float(v) * k, 4)   # noqa: E731
    scal = lambda v: [sc(x) if isinstance(x, (int, float)) else x for x in v]   # noqa: E731
    spec["height"] = round(float(spec.get("height") or 0) * k, 3)
    for name, joint in list((spec.get("joints") or {}).items()):
        if isinstance(joint, list):
            spec["joints"][name] = scal(joint)
        elif isinstance(joint, dict):
            spec["joints"][name] = {kk: (sc(vv) if kk in ("up", "fwd", "side", "ground")
                                         and isinstance(vv, (int, float)) else vv) for kk, vv in joint.items()}
    for vol in spec.get("volumes") or []:
        vol["profile"] = [([e[0], sc(e[1]), sc(e[2])] + list(e[3:]))
                          if isinstance(e, list) and len(e) >= 3 else e for e in vol.get("profile") or []]
        if isinstance(vol.get("ring_step"), (int, float)):
            vol["ring_step"] = sc(vol["ring_step"])
    for part in spec.get("parts") or []:
        if isinstance(part.get("thickness"), (int, float)):
            part["thickness"] = sc(part["thickness"])
        if isinstance(part.get("size"), (int, float)):
            part["size"] = sc(part["size"])
        elif isinstance(part.get("size"), list):
            part["size"] = scal(part["size"])
        if isinstance(part.get("offset"), list):
            part["offset"] = scal(part["offset"])
        for seg in part.get("segments") or []:
            for key in ("len", "r", "radius"):
                if isinstance(seg.get(key), (int, float)):
                    seg[key] = sc(seg[key])
        if isinstance(part.get("points"), list):
            part["points"] = [scal(p) if isinstance(p, list) else p for p in part["points"]]


def build_spec(controls: dict) -> dict:
    """Turn the form's values into a whole ACS spec. The scaffolding the user never sees is here."""
    c = controls if isinstance(controls, dict) else {}
    base = _load_preset(str(c.get("preset") or PRESETS[0]["id"]))
    spec = json.loads(json.dumps(base))
    _scale_spec(spec, _num(c.get("size"), 1.0, 0.6, 1.6))
    spec["smooth_angle"] = int(_num(c.get("smooth"), base.get("smooth_angle", 50), 10, 70))
    colours = c.get("colors") if isinstance(c.get("colors"), dict) else {}
    for part, key in (("fur_body", "body"), ("ear", "ear")):
        col = _hexcol(colours.get(key))
        if col:
            spec["palette"][part]["color"] = col
    spec["name"] = _safe_name(c.get("name")) or spec.get("name") or "creature"
    return spec


def _run_engine(src: Path, out_glb: Path) -> tuple:
    proc = subprocess.run([_node(), str(ENGINE), str(src), str(out_glb)], capture_output=True, text=True, timeout=TIMEOUT)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fix_joint_range(spec: dict, out: str) -> bool:
    m = re.search(r'BLOCK: joint_range: (\S+?)\.(\w+) is declared to [\d.]+.*?set the limit to ([\d.]+)', out, re.S)
    if not m:
        return False
    joint, axis, val = m.group(1).strip('"'), m.group(2), float(m.group(3))
    ranges = spec.setdefault("joint_range", {})
    if joint not in ranges:                       # the engine names a mirrored joint: copy the other side
        other = ("L" + joint[1:]) if joint.startswith("R") else ("R" + joint[1:])
        ranges[joint] = dict(ranges.get(other, {}))
    cur = ranges[joint].get(axis)
    ranges[joint][axis] = [cur[0], val] if isinstance(cur, list) and len(cur) == 2 else [-val, val]
    return True


def _fix_size(spec: dict, out: str) -> bool:
    m = re.search(r'BLOCK: size: spec declares height [\d.]+ m but the build stands ([\d.]+) m', out)
    if not m:
        return False
    spec["height"] = round(float(m.group(1)), 3)   # the engine measured it: trust the measurement
    return True


def _apply_fix(spec: dict, out: str) -> bool:
    for fix in (_fix_joint_range, _fix_size):
        if fix(spec, out):
            return True
    return False


def _block_message(out: str) -> str:
    """The engine's own BLOCK lines, without the ascii rulers - what the user is told when we cannot fix it."""
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("BLOCK:")]
    return " ".join(lines)[:600] or " ".join(out.split())[-400:]


def _as_dict(spec) -> dict:
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, (str, Path)):
        path = Path(spec)
        try:
            is_path = path.is_file()
        except OSError:
            is_path = False
        text = path.read_text(encoding="utf-8") if is_path else str(spec)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise AnyCreatureError("the spec is not valid JSON: %s" % exc) from exc
        if not isinstance(data, dict):
            raise AnyCreatureError("the spec must be a JSON object")
        return data
    raise AnyCreatureError("give the spec as an object, JSON text, or a .json path")


def compile_spec(spec, out_glb, *, autofix: bool = False, max_fixes: int = 16) -> dict:
    """Compile an ACS spec into out_glb. An existing .json PATH goes straight to the engine (so the
    vendored example keeps its exemption); a dict or JSON text is written to a temp file and, when
    autofix is on, the engine's own fixes are applied and the build retried."""
    out_glb = Path(out_glb)
    if not ENGINE.is_file():
        raise AnyCreatureError("the vendored engine is missing (%s)" % ENGINE)
    direct = None
    if isinstance(spec, (str, Path)):
        path = Path(spec)
        try:
            direct = path if path.is_file() else None
        except OSError:
            direct = None
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    if direct is not None:                                   # a file the engine may already know
        code, out = _run_engine(direct, out_glb)
        if code != 0 or not out_glb.is_file():
            raise AnyCreatureError(_block_message(out))
        return {"ok": True, "glb": str(out_glb), "bytes": out_glb.stat().st_size, "fixes": 0}

    data = _as_dict(spec)
    tmp = out_glb.with_name(out_glb.stem + ".spec.json")
    fixes = 0
    try:
        for attempt in range((max_fixes + 1) if autofix else 1):
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            code, out = _run_engine(tmp, out_glb)
            if code == 0 and out_glb.is_file():
                return {"ok": True, "glb": str(out_glb), "bytes": out_glb.stat().st_size, "fixes": fixes}
            if not (autofix and _apply_fix(data, out)):
                raise AnyCreatureError(_block_message(out))
            fixes += 1
    finally:
        tmp.unlink(missing_ok=True)
    raise AnyCreatureError("the build still would not stand after %d fixes" % max_fixes)


def render_views(glb, out_dir) -> dict:
    """Draw the front / side / top / hero silhouettes of a GLB into out_dir."""
    out_dir = Path(out_dir)
    if not OUTLINE.is_file():
        raise AnyCreatureError("the view renderer is missing (%s)" % OUTLINE)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run([sys.executable, str(OUTLINE), str(glb), str(out_dir), "--views", ",".join(VIEWS)],
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise AnyCreatureError("the views did not finish in %ds" % TIMEOUT) from exc
    made = {v: str(out_dir / ("sil_%s.png" % v)) for v in VIEWS if (out_dir / ("sil_%s.png" % v)).is_file()}
    if proc.returncode != 0 or not made:
        tail = " ".join(((proc.stdout or "") + (proc.stderr or "")).split())[-400:]
        raise AnyCreatureError("the views did not render: " + (tail or "exit %d" % proc.returncode))
    return {"ok": True, "views": made}


def make(spec, out_dir, name: str = "creature", *, autofix: bool = True, render: bool = True) -> dict:
    """Compile + (optionally) render: <out_dir>/<name>.glb plus <out_dir>/<name>.views/*.png."""
    out_dir = Path(out_dir)
    safe = _safe_name(name) or "creature"
    glb = out_dir / (safe + ".glb")
    res = compile_spec(spec, glb, autofix=autofix)
    out = {**res, "name": glb.name, "stem": safe, "dir": str(out_dir)}
    if render:
        out.update(render_views(glb, out_dir / (safe + ".views")))
    return out


def make_from_controls(controls: dict, out_dir, name: str = "") -> dict:
    """The window's whole path: a few controls in, a .glb and its four views out.

    The engine's floors are measured in absolute metres, so a handful of exact sizes are refused
    (a fold appears at one scale and not its neighbours). The user asked for "about this big", so the
    backend lands on the nearest size that stands and says which one it used."""
    c = dict(controls or {})
    asked = _num(c.get("size"), 1.0, 0.6, 1.6)
    last = None
    for delta in (0, 0.03, -0.03, 0.06, -0.06, 0.09, -0.09, 0.12, -0.12):
        size = round(min(1.6, max(0.6, asked + delta)), 3)
        try:
            spec = build_spec({**c, "size": size})
            res = make(spec, out_dir, name or c.get("name") or spec.get("name") or "creature")
            res["size"] = size
            res["asked_size"] = asked
            res["size_moved"] = abs(size - asked) > 1e-6
            return res
        except AnyCreatureError as exc:
            last = exc
    raise last
