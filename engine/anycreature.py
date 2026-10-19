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
# example. The three shipped skeletons differ in scale only, so a body plan is the skeleton PLUS a set
# of proportions (SHAPE below) and a coat - which is what makes a deer read differently from a bear.
PRESETS = [
    {"id": "hound", "label": "Hound", "icon": "models", "what": "A steady, medium-legged quadruped.",
     "base": "hound", "shape": {}, "coat": "wolf"},
    {"id": "tall", "label": "Long-shanks", "icon": "layers", "what": "Long legs, compact body - a runner.",
     "base": "tall", "shape": {"legs": 1.22, "body": 0.92, "neck": 1.12, "girth": 0.92}, "coat": "dusk"},
    {"id": "low", "label": "Courser", "icon": "grid", "what": "Low and long, close to the ground.",
     "base": "low", "shape": {"legs": 0.8, "body": 1.2, "tail": 1.15}, "coat": "sand"},
    {"id": "fox", "label": "Fox", "icon": "sparkle", "what": "Small and quick: big ears, a long snout and a brush of a tail.",
     "base": "hound", "size": 0.8, "shape": {"ears": 1.8, "snout": 1.2, "tail": 1.4, "legthick": 0.88, "girth": 0.92},
     "coat": "fox"},
    {"id": "deer", "label": "Deer", "icon": "layers", "what": "Tall and slender: long legs and neck, a short tail.",
     "base": "tall", "shape": {"legs": 1.3, "neck": 1.6, "tail": 0.5, "legthick": 0.82, "snout": 1.1, "ears": 1.4},
     "coat": "deer"},
    {"id": "bear", "label": "Brute", "icon": "cube", "what": "Heavy and broad: a big head, thick legs, almost no tail.",
     "base": "low", "shape": {"girth": 1.2, "legs": 0.85, "head": 1.15, "snout": 0.8, "tail": 0.5, "legthick": 1.22,
                              "ears": 0.75, "neck": 0.8}, "coat": "bear"},
]
SLIDERS = [
    {"id": "size", "label": "Size", "min": 0.6, "max": 1.6, "step": 0.05, "value": 1.0, "group": "Build",
     "what": "How big it stands - scales the whole creature, so its proportions and its walk stay right."},
    {"id": "smooth", "label": "Smooth", "min": 10, "max": 70, "step": 1, "value": 50, "group": "Build",
     "what": "Higher = smoother body, lower = more facets."},
]
# Proportions: each one scales a named part of the skeleton (and the flesh on it) and is 1.0 at the
# starter's own build. The ranges are the ones that compiled clean on every starter; anything between
# is landed by make_from_controls (it eases the extreme sliders back toward 1.0 until the build stands).
SHAPE = [
    {"id": "legs", "label": "Legs", "min": 0.75, "max": 1.35, "group": "Body",
     "what": "Leg length. The body is lifted with them, so the feet stay on the ground."},
    {"id": "legthick", "label": "Leg thickness", "min": 0.8, "max": 1.3, "group": "Body",
     "what": "How heavy the legs and paws are."},
    {"id": "body", "label": "Body length", "min": 0.8, "max": 1.3, "group": "Body",
     "what": "From the hips to the chest: short and compact, or long."},
    {"id": "girth", "label": "Girth", "min": 0.82, "max": 1.25, "group": "Body",
     "what": "How deep and wide the body is; the legs move out with it."},
    {"id": "neck", "label": "Neck", "min": 0.7, "max": 1.7, "group": "Head",
     "what": "Neck length."},
    {"id": "head", "label": "Head", "min": 0.8, "max": 1.3, "group": "Head",
     "what": "Head size: skull, eyes, ears and nose together."},
    {"id": "snout", "label": "Snout", "min": 0.7, "max": 1.35, "group": "Head",
     "what": "Muzzle length: a flat face or a long nose."},
    {"id": "ears", "label": "Ears", "min": 0.6, "max": 2.0, "group": "Head",
     "what": "Ear size."},
    {"id": "tail", "label": "Tail", "min": 0.4, "max": 1.6, "group": "Tail",
     "what": "Tail length (it thickens a little as it grows)."},
]
SHAPE_IDS = [s["id"] for s in SHAPE]
for _s in SHAPE:
    _s.update({"step": 0.01, "value": 1.0})
# where each colour lands: a palette material, or a marking (the arcs a volume paints on its ring:
# 0-52 degrees is the top of the ring, 128-180 the underside)
COLORS = [
    {"id": "body", "label": "Body", "value": "#6f6a5c", "palette": ["fur_body"]},
    {"id": "back", "label": "Back", "value": "#3d382d", "arc": [("body", 0)]},
    {"id": "belly", "label": "Belly", "value": "#c9c1ae", "arc": [("body", 128)]},
    {"id": "head", "label": "Head", "value": "#b5561f", "palette": ["fur_head"]},
    {"id": "mask", "label": "Brow", "value": "#8a3d14", "arc": [("head", 0)]},
    {"id": "muzzle", "label": "Chin", "value": "#e08a3c", "arc": [("head", 128)]},
    {"id": "legs", "label": "Legs", "value": "#5f594b", "palette": ["fur_leg"]},
    {"id": "paws", "label": "Paws", "value": "#6b6455", "palette": ["fur_paw"]},
    {"id": "tail", "label": "Tail", "value": "#b5561f", "palette": ["fur_tail"], "arc": [("tail", 0)]},
    {"id": "ear", "label": "Ears", "value": "#8a3d14", "palette": ["ear"]},
    {"id": "eye", "label": "Eyes", "value": "#f0a51e", "palette": ["eye"]},
    {"id": "nose", "label": "Nose", "value": "#191a1d", "palette": ["nose"]},
    {"id": "shadow", "label": "Shadow", "value": "#001370", "ramp": "bottom"},
]
# Coats: a whole palette in one click (the swatch grid above still edits any one of them).
COATS = [
    {"id": "wolf", "label": "Wolf", "colors": {"body": "#6f6a5c", "back": "#3d382d", "belly": "#c9c1ae", "head": "#b5561f",
     "mask": "#8a3d14", "muzzle": "#e08a3c", "legs": "#5f594b", "paws": "#6b6455", "tail": "#b5561f", "ear": "#8a3d14",
     "eye": "#f0a51e", "nose": "#191a1d", "shadow": "#001370"}},
    {"id": "fox", "label": "Fox", "colors": {"body": "#c8571d", "back": "#9c3d10", "belly": "#f1e6d4", "head": "#d0601f",
     "mask": "#a3430f", "muzzle": "#f4ece0", "legs": "#2b2420", "paws": "#1d1915", "tail": "#c8571d", "ear": "#2b2420",
     "eye": "#e9b83a", "nose": "#141414", "shadow": "#3a1206"}},
    {"id": "arctic", "label": "Arctic", "colors": {"body": "#e8ebee", "back": "#c9d0d8", "belly": "#f7f8f9", "head": "#eef0f2",
     "mask": "#cfd6de", "muzzle": "#ffffff", "legs": "#dde2e7", "paws": "#cbd2d9", "tail": "#e8ebee", "ear": "#b9c2cc",
     "eye": "#5aa9e6", "nose": "#202326", "shadow": "#33465e"}},
    {"id": "panther", "label": "Panther", "colors": {"body": "#26262b", "back": "#18181c", "belly": "#33333a", "head": "#2a2a30",
     "mask": "#1b1b1f", "muzzle": "#3a3a42", "legs": "#222227", "paws": "#1a1a1e", "tail": "#26262b", "ear": "#1d1d21",
     "eye": "#d8e04a", "nose": "#0d0d0f", "shadow": "#05050a"}},
    {"id": "deer", "label": "Fawn", "colors": {"body": "#a8743f", "back": "#7c5228", "belly": "#efe2cc", "head": "#a8743f",
     "mask": "#6e4824", "muzzle": "#f2e7d6", "legs": "#946535", "paws": "#2e2117", "tail": "#f2e7d6", "ear": "#8a5e33",
     "eye": "#2a1c12", "nose": "#151010", "shadow": "#2a1608"}},
    {"id": "bear", "label": "Bear", "colors": {"body": "#4e3524", "back": "#3a271a", "belly": "#5e432f", "head": "#55392a",
     "mask": "#3e2a1d", "muzzle": "#8a6a4e", "legs": "#3f2b1e", "paws": "#2a1d14", "tail": "#4e3524", "ear": "#3a271a",
     "eye": "#1a120c", "nose": "#100c0a", "shadow": "#120a05"}},
    {"id": "dusk", "label": "Dusk", "colors": {"body": "#7a6a63", "back": "#4a3e3a", "belly": "#cbbfb6", "head": "#8c5a3c",
     "mask": "#5b2f0f", "muzzle": "#d9a87a", "legs": "#5f594b", "paws": "#4b463c", "tail": "#8c5a3c", "ear": "#5b2f0f",
     "eye": "#f0a51e", "nose": "#191a1d", "shadow": "#1d1440"}},
    {"id": "sand", "label": "Sand", "colors": {"body": "#c2a878", "back": "#8f7650", "belly": "#efe4cc", "head": "#c9a46a",
     "mask": "#8c6a3a", "muzzle": "#f2e6cf", "legs": "#ad9466", "paws": "#7c6845", "tail": "#c9a46a", "ear": "#3c2a1a",
     "eye": "#3b2a16", "nose": "#1a1612", "shadow": "#3d2a12"}},
    {"id": "moss", "label": "Moss", "colors": {"body": "#56653a", "back": "#38431f", "belly": "#a9b27a", "head": "#647443",
     "mask": "#3c4722", "muzzle": "#b8c08a", "legs": "#4b5732", "paws": "#2f3620", "tail": "#647443", "ear": "#7a3b1d",
     "eye": "#f2c230", "nose": "#18190f", "shadow": "#0f1a08"}},
    {"id": "ember", "label": "Ember", "colors": {"body": "#7a1f17", "back": "#4a0f0b", "belly": "#e0703a", "head": "#8f2a1a",
     "mask": "#3d0c08", "muzzle": "#f09a4a", "legs": "#3a1410", "paws": "#1f0b08", "tail": "#d0501e", "ear": "#2a0a07",
     "eye": "#ffd54a", "nose": "#120606", "shadow": "#2a0303"}},
]


class AnyCreatureError(RuntimeError):
    """The build was refused (a BLOCK: floor we could not repair), the engine is missing, or a view failed."""


def available() -> dict:
    node = shutil.which("node")
    return {"engine": ENGINE.is_file(), "outline": OUTLINE.is_file(), "node": bool(node),
            "ok": bool(node) and ENGINE.is_file() and OUTLINE.is_file()}


def schema() -> dict:
    """The form the UI draws - presets (icons), sliders and colour pickers - so the window needs no
    anyCreature knowledge of its own. Each preset carries the control values it starts from."""
    def defaults(p):
        coat = next((c for c in COATS if c["id"] == p.get("coat")), COATS[0])
        return {"size": p.get("size", 1.0), "shape": {k: p["shape"].get(k, 1.0) for k in SHAPE_IDS},
                "coat": coat["id"], "colors": dict(coat["colors"])}
    presets = [{**{k: v for k, v in p.items() if k not in ("base", "shape", "size")}, "start": defaults(p)}
               for p in PRESETS]
    colors = [{k: c[k] for k in ("id", "label", "value")} for c in COLORS]
    return {"presets": presets, "sliders": SLIDERS, "shape": SHAPE, "colors": colors, "coats": COATS,
            "views": list(VIEWS)}


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


def _preset(pid: str) -> dict:
    return next((p for p in PRESETS if p["id"] == pid), PRESETS[0])


def _load_preset(pid: str) -> dict:
    base = _preset(pid).get("base") or PRESETS[0]["id"]
    path = PRESETS_DIR / (base + ".json")
    if not path.is_file():
        raise AnyCreatureError("the starter %r is missing (%s)" % (pid, path))
    return json.loads(path.read_text(encoding="utf-8"))


def _scale_joint(spec: dict, name: str, k: float, keys=("up", "fwd", "side")) -> None:
    """Scale a RELATIVE joint's offset from its parent (the length of that bone)."""
    j = (spec.get("joints") or {}).get(name)
    if isinstance(j, dict) and k != 1.0:
        for key in keys:
            if isinstance(j.get(key), (int, float)):
                j[key] = round(float(j[key]) * k, 4)


def _volume(spec: dict, chain: str):
    return next((v for v in spec.get("volumes") or [] if v.get("chain") == chain), None)


def _scale_profile(spec: dict, chain: str, kw: float, kh: float = None) -> None:
    vol = _volume(spec, chain)
    kh = kw if kh is None else kh
    if vol and (kw != 1.0 or kh != 1.0):
        vol["profile"] = [([e[0], round(e[1] * kw, 4), round(e[2] * kh, 4)] + list(e[3:]))
                          if isinstance(e, list) and len(e) >= 3 else e for e in vol.get("profile") or []]


def _part(spec: dict, name: str):
    return next((p for p in spec.get("parts") or [] if p.get("name") == name), None)


def _scale_part(spec: dict, name: str, k: float) -> None:
    pt = _part(spec, name)
    if not pt or k == 1.0:
        return
    if isinstance(pt.get("size"), (int, float)):
        pt["size"] = round(pt["size"] * k, 4)
    elif isinstance(pt.get("size"), list):
        pt["size"] = [round(x * k, 4) for x in pt["size"]]
    if isinstance(pt.get("points"), list):
        pt["points"] = [[round(x * k, 4) for x in q] if isinstance(q, list) else q for q in pt["points"]]
    for seg in pt.get("segments") or []:
        for key in ("len", "r", "radius"):
            if isinstance(seg.get(key), (int, float)):
                seg[key] = round(seg[key] * k, 4)


def _chain(spec: dict, name: str) -> list:
    return list((spec.get("chains") or {}).get(name) or [])


def _drop(spec: dict, names) -> float:
    """How far a run of relative joints goes DOWN (the leg's height above its toe)."""
    out = 0.0
    for n in names:
        j = (spec.get("joints") or {}).get(n)
        if isinstance(j, dict) and isinstance(j.get("up"), (int, float)):
            out -= float(j["up"])
    return out


def _positions(spec: dict) -> dict:
    """Every joint's world position, resolving the relative ones the way engine/core/relative.js does."""
    raw, out = spec.get("joints") or {}, {}
    for name, j in raw.items():
        if isinstance(j, list) and len(j) == 3:
            out[name] = [float(x) for x in j]
    for _ in range(len(raw) + 1):
        moved = False
        for name, d in raw.items():
            if name in out or not isinstance(d, dict) or d.get("from") not in out:
                continue
            b = out[d["from"]]
            if d.get("dir") and d.get("len") is not None:
                v = [float(x) for x in d["dir"]]
                n = sum(x * x for x in v) ** 0.5 or 1.0
                p = [b[i] + v[i] / n * float(d["len"]) for i in range(3)]
            else:
                p = [b[0] + float(d.get("side") or 0), b[1] + float(d.get("up") or 0), b[2] + float(d.get("fwd") or 0)]
            if d.get("ground") is not None:
                p[1] = float(d["ground"])
            out[name] = p
            moved = True
        if not moved:
            break
    return out


def _arc(spec: dict, chain: str) -> list:
    """Cumulative arc length at each joint of a chain - what a volume's profile t is a fraction of."""
    pos, names, cum = _positions(spec), _chain(spec, chain), [0.0]
    for a, b in zip(names, names[1:]):
        if a not in pos or b not in pos:
            return []
        cum.append(cum[-1] + sum((pos[b][i] - pos[a][i]) ** 2 for i in range(3)) ** 0.5)
    return cum


def _remap_t(t: float, old: list, new: list) -> float:
    """The same place on the skeleton (which bone, how far along it) as a fraction of the new chain."""
    if len(old) < 2 or len(old) != len(new) or not old[-1] or not new[-1]:
        return t
    s = max(0.0, min(1.0, float(t))) * old[-1]
    i = 0
    while i < len(old) - 2 and s > old[i + 1]:
        i += 1
    span = old[i + 1] - old[i]
    f = (s - old[i]) / span if span > 1e-9 else 0.0
    return round(max(0.0, min(1.0, (new[i] + f * (new[i + 1] - new[i])) / new[-1])), 4)


def _keep_on_bones(spec: dict, arcs: dict) -> None:
    """After the bones changed length, put every profile ring and every part anchor back on the same
    bone it was on - so a longer neck is a longer NECK, not the barrel stretched up into it."""
    for chain, old in arcs.items():
        new = _arc(spec, chain)
        vol = _volume(spec, chain)
        if vol:
            for e in vol.get("profile") or []:
                if isinstance(e, list) and e and isinstance(e[0], (int, float)) and 0 < e[0] < 1:
                    e[0] = _remap_t(e[0], old, new)
        for pt in spec.get("parts") or []:
            a = pt.get("anchor")
            if isinstance(a, dict) and a.get("chain") == chain and isinstance(a.get("t"), (int, float)):
                a["t"] = _remap_t(a["t"], old, new)


def shape_spec(spec: dict, shape: dict) -> dict:
    """Apply the proportion sliders (SHAPE) to a spec, in place. 1.0 everywhere = the starter as built.

    Legs scale every bone below the hip/shoulder and LIFT the hips by what they gained, so the toes
    (which carry an absolute "ground") stay planted; girth widens the body and moves the leg roots out
    with it; head scales the skull bones, its flesh and the eyes / ears / nose on it."""
    sh = {k: _num((shape or {}).get(k), 1.0, s["min"], s["max"]) for k, s in zip(SHAPE_IDS, SHAPE)}
    joints = spec.get("joints") or {}
    arcs = {c: _arc(spec, c) for c in ("body", "head") if _chain(spec, c)}
    legs, before = sh["legs"], 0.0
    leg_chains = [c for c in ("LFront", "LBack") if _chain(spec, c)]
    if legs != 1.0 and leg_chains:
        seg = [_chain(spec, c)[1:-1] for c in leg_chains]          # elbow/wrist, knee/hock: not the toe
        before = sum(_drop(spec, s) for s in seg) / len(seg)
        for c in leg_chains:
            for n in _chain(spec, c)[1:]:
                _scale_joint(spec, n, legs)
        lift = sum(_drop(spec, s) for s in seg) / len(seg) - before
        hips = joints.get("Hips")
        if isinstance(hips, list) and len(hips) == 3:
            hips[1] = round(hips[1] + lift, 4)
        spec["height"] = round(float(spec.get("height") or 0) + lift, 3)
    for n in ("Rump", "Spine", "Chest"):
        _scale_joint(spec, n, sh["body"])
    if sh["girth"] != 1.0:   # the barrel, not the ends: the neck end carries the head, the rump the tail
        g = sh["girth"]
        vol = _volume(spec, "body")
        if vol:
            def w(t):
                return max(0.0, min(1.0, t / 0.12, (1.0 - t) / 0.3))
            vol["profile"] = [([e[0], round(e[1] * (1 + (g - 1) * w(e[0])), 4), round(e[2] * (1 + (g - 1) * w(e[0])), 4)]
                               + list(e[3:])) if isinstance(e, list) and len(e) >= 3 else e for e in vol.get("profile") or []]
        if g > 1.0:              # a wider barrel carries its legs out with it (a narrower one keeps them clear)
            for c in leg_chains:
                _scale_joint(spec, _chain(spec, c)[0], g, keys=("side",))
    for n in ("NeckB", "Neck2"):
        _scale_joint(spec, n, sh["neck"])
    head = sh["head"]
    if head != 1.0:
        for n in _chain(spec, "head")[1:]:
            _scale_joint(spec, n, head)
        vol = _volume(spec, "head")   # not the root ring: it has to stay seated in the neck
        if vol:
            def w(t):
                return max(0.0, min(1.0, t / 0.16))
            vol["profile"] = [([e[0], round(e[1] * (1 + (head - 1) * w(e[0])), 4), round(e[2] * (1 + (head - 1) * w(e[0])), 4)]
                               + list(e[3:])) if isinstance(e, list) and len(e) >= 3 else e for e in vol.get("profile") or []]
        for p in spec.get("parts") or []:
            if p.get("type") == "eye" or p.get("host") in ("Nose",):
                _scale_part(spec, p.get("name"), head)
    for n in ("Muzzle", "Nose"):
        _scale_joint(spec, n, sh["snout"])
    ears = min(2.0, sh["ears"] * head)   # big ears on a big head stop where they would come loose
    for p in spec.get("parts") or []:
        if p.get("type") == "fin" and p.get("host") in _chain(spec, "head"):
            _scale_part(spec, p.get("name"), ears)
    tail = sh["tail"]
    if tail != 1.0:
        for n in _chain(spec, "tail")[1:]:
            _scale_joint(spec, n, tail)
        _scale_profile(spec, "tail", 0.7 + 0.3 * tail)
    lt = sh["legthick"]
    if lt != 1.0:
        for c in leg_chains:
            _scale_profile(spec, c, lt)
        for p in spec.get("parts") or []:
            if p.get("type") == "paw":
                _scale_part(spec, p.get("name"), lt)
    _keep_on_bones(spec, arcs)
    # the walk: a longer leg on a shorter body takes a longer stride into a shorter gap, so the
    # front and back paws would meet - keep the stride in proportion to the body it walks under
    stride = min(1.0, (sh["body"] / legs) ** 0.9)
    if stride < 0.995:
        _ease_clip(spec, "move", stride)
    return spec


def _paint(spec: dict, colours: dict) -> None:
    """The colour pickers onto the spec: palette materials and the volumes' markings (arcs)."""
    pal = spec.setdefault("palette", {})
    for c in COLORS:
        col = _hexcol((colours or {}).get(c["id"]))
        if not col:
            continue
        for mat in c.get("palette") or []:
            if mat in pal:
                pal[mat]["color"] = col
        if c.get("ramp"):     # the engine's top-to-bottom shading ramp (engine/core/shade.js L3)
            sh = spec.setdefault("shading", {})
            ramp = sh.get("ramp") if isinstance(sh.get("ramp"), dict) else {}
            ramp[c["ramp"]] = col
            sh["ramp"] = ramp
        for chain, start in c.get("arc") or []:
            vol = _volume(spec, chain)
            for arc in ((vol or {}).get("colors") or {}).get("arcs") or []:
                if arc.get("from") == start:
                    arc["color"] = col


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


def _effective(controls: dict) -> dict:
    """The controls with the starter's own build filled in for anything not given: a Deer asked for
    with no sliders is the deer, not the skeleton it is built on."""
    c = dict(controls) if isinstance(controls, dict) else {}
    pre = _preset(str(c.get("preset") or PRESETS[0]["id"]))
    shape = dict(pre.get("shape") or {})
    given = c.get("shape") if isinstance(c.get("shape"), dict) else {}
    shape.update({k: v for k, v in given.items() if k in SHAPE_IDS})
    shape.update({k: c[k] for k in SHAPE_IDS if k in c and k not in given})
    c["shape"] = {k: _num(shape.get(k), 1.0, s["min"], s["max"]) for k, s in zip(SHAPE_IDS, SHAPE)}
    if c.get("size") in (None, ""):
        c["size"] = pre.get("size", 1.0)
    if not c.get("coat") and not any(_hexcol(v) for v in (c.get("colors") or {}).values()):
        c["coat"] = pre.get("coat")
    return c


def build_spec(controls: dict) -> dict:
    """Turn the form's values into a whole ACS spec. The scaffolding the user never sees is here.

    controls: preset, size, smooth, shape {legs, body, ...} (or the same keys at the top level),
    coat (a COATS id: the whole palette) and colors {id: #hex} (each one over the coat)."""
    c = _effective(controls)
    pid = str(c.get("preset") or PRESETS[0]["id"])
    base = _load_preset(pid)
    spec = json.loads(json.dumps(base))
    shape_spec(spec, c["shape"])
    _scale_spec(spec, _num(c.get("size"), 1.0, 0.6, 1.6))
    spec["smooth_angle"] = int(_num(c.get("smooth"), base.get("smooth_angle", 50), 10, 70))
    coat = next((x for x in COATS if x["id"] == c.get("coat")), None)
    if coat:
        _paint(spec, coat["colors"])
    _paint(spec, c.get("colors") if isinstance(c.get("colors"), dict) else {})
    spec["name"] = _safe_name(c.get("name")) or spec.get("name") or "creature"
    return spec


def _run_engine(src: Path, out_glb: Path) -> tuple:
    proc = subprocess.run([_node(), str(ENGINE), str(src), str(out_glb)], capture_output=True, text=True, timeout=TIMEOUT)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fix_joint_range(spec: dict, out: str) -> bool:
    m = re.search(r'BLOCK: joint_range: (\S+?)\.(\w+) is declared to -?[\d.]+.*?set the limit to (-?[\d.]+)', out, re.S)
    if not m:
        return False
    joint, axis, val = m.group(1).strip('"'), m.group(2), float(m.group(3))
    ranges = spec.setdefault("joint_range", {})
    if joint not in ranges:                       # the engine names a mirrored joint: copy the other side
        other = ("L" + joint[1:]) if joint.startswith("R") else ("R" + joint[1:])
        ranges[joint] = dict(ranges.get(other, {}))
    cur = ranges[joint].get(axis)
    if isinstance(cur, list) and len(cur) == 2:
        ranges[joint][axis] = [val, cur[1]] if val < 0 else [cur[0], val]   # the bound the engine names
    else:
        ranges[joint][axis] = [-abs(val), abs(val)]
    return True


def _fix_size(spec: dict, out: str) -> bool:
    m = re.search(r'BLOCK: size: spec declares height [\d.]+ m but the build stands ([\d.]+) m', out)
    if not m:
        return False
    spec["height"] = round(float(m.group(1)), 3)   # the engine measured it: trust the measurement
    return True


def _bone(spec: dict, name: str):
    """The offset vector [side, up, fwd] of a relative joint (None for an absolute one)."""
    j = (spec.get("joints") or {}).get(name)
    if isinstance(j, dict):
        return [float(j.get("side") or 0), float(j.get("up") or 0), float(j.get("fwd") or 0)]
    return None


def _fix_proportion(spec: dict, out: str) -> bool:
    """A 50:50 'dead rhythm' between two bones: make the second one clearly longer (or shorter)."""
    done = False
    for m in re.finditer(r'BLOCK: proportion: chain "[^"]+" segments (\w+)→(\w+)→(\w+) are 50:50', out):
        a, b = _bone(spec, m.group(2)), _bone(spec, m.group(3))
        if a is None or b is None:
            continue
        la, lb = (sum(x * x for x in a) ** 0.5), (sum(x * x for x in b) ** 0.5)
        if not la or not lb:
            continue
        target = la / 0.82 if lb >= la else la * 0.8     # out of the 0.92+ band, into the ~0.8 rhythm
        _scale_joint(spec, m.group(3), target / lb)
        done = True
    return done


def _fix_containment(spec: dict, out: str) -> bool:
    """A root ring outside its host: move the chain's root joint by what the engine measured."""
    done = False
    for m in re.finditer(r'root_containment: chain "[^"]+" root ring.*?Move joint "(\w+)" about ([\d.]+)m'
                         r'(?: toward \[([-\d., ]+)\])?', out):
        name, dist = m.group(1), float(m.group(2)) * 1.25 + 0.002
        if not m.group(3):
            continue
        d = [float(x) for x in m.group(3).split(",")]
        if not re.match(r"[LR][A-Z]", name):
            # an axis chain's root (the head on the neck) stays on the centre line: widen the host's end
            # under it instead - the engine offers that fix too, and moving the joint just orbits it
            host = re.search(r'outside its host "(\w+)"', m.group(0))
            vol = _volume(spec, host.group(1)) if host else None
            if vol:
                prof = vol.get("profile") or []
                for e in prof:
                    if isinstance(e, list) and len(e) >= 3 and e[0] >= 0.85:
                        e[1] = round(e[1] + dist, 4)
                        e[2] = round(e[2] + dist, 4)
                done = True
            continue
        j = (spec.get("joints") or {}).get(name)
        if isinstance(j, dict):
            for key, comp in (("side", d[0]), ("up", d[1]), ("fwd", d[2])):
                j[key] = round(float(j.get(key) or 0) + comp * dist, 4)
            done = True
        elif isinstance(j, list) and len(j) == 3:
            spec["joints"][name] = [round(j[i] + d[i] * dist, 4) for i in range(3)]
            done = True
    return done


def _fix_clearance(spec: dict, out: str) -> bool:
    """Two mirrored legs too close at the centre line: move the leg's root out by what was measured."""
    done = False
    for m in re.finditer(r'BLOCK: limb_clearance: "(\w+)" and its mirror .*? Move "\w+" ([\d.]+) further out in x', out):
        root = (_chain(spec, m.group(1)) or [None])[0]
        j = (spec.get("joints") or {}).get(root)
        if isinstance(j, dict):
            j["side"] = round(float(j.get("side") or 0) + float(m.group(2)) * 1.3 + 0.002, 4)
            done = True
    return done


def _leg_tracks(spec: dict, clip: str):
    legs = set()
    for c in ("LFront", "LBack"):
        legs.update(_chain(spec, c))
    anim = (spec.get("animations") or {}).get(clip) or {}
    return [(jn, tr) for jn, tr in (anim.get("tracks") or {}).items() if jn in legs]


def _ease_clip(spec: dict, clip: str, k: float, joints=None) -> bool:
    """Scale the rotation keys of a clip's leg tracks (or the named joints) by k: a smaller stride."""
    done = False
    for jn, tr in _leg_tracks(spec, clip):
        if joints and jn not in joints:
            continue
        for axis, keys in tr.items():
            if axis.startswith("r") and isinstance(keys, list):
                tr[axis] = [[kk[0], round(kk[1] * k, 2)] + list(kk[2:]) if isinstance(kk, list) and len(kk) >= 2 else kk
                            for kk in keys]
                done = True
    return done


def _fix_clip(spec: dict, out: str) -> bool:
    """A paw swept through the other paw (self_clip) or a leg folded by its bend (anim_integrity):
    the same walk, a little less far - or, for a crowded bend, fewer rings through it."""
    done = False
    for m in re.finditer(r'BLOCK: self_clip: in "(\w+)"', out):
        done = _ease_clip(spec, m.group(1), 0.85) or done
    for m in re.finditer(r'BLOCK: anim_integrity: "(\w+)" @[\d.]+ folds mesh .*? worst in "([^"]+)"', out):
        chain = re.sub(r"^R", "L", m.group(2).split("@")[0])
        vol = _volume(spec, chain)
        if vol is not None and float(vol.get("ring_step") or 0) < 0.085:
            vol["ring_step"] = round(max(float(vol.get("ring_step") or 0.05), 0.04) * 1.25, 4)
            done = True
        elif _ease_clip(spec, m.group(1), 0.85, set(_chain(spec, chain))):
            done = True
        elif vol is not None and vol.get("_slim", 0) < 4:
            # a fold in a pose that does not move this chain is the shape itself: a bend the tube is
            # too thick to make - slim the tube a little (at most four times)
            vol["_slim"] = vol.get("_slim", 0) + 1
            _scale_profile(spec, chain, 0.94)
            done = True
    for m in re.finditer(r'BLOCK: anim_integrity: "(\w+)" @[\d.]+ stretches an edge .*? pulled by joint "(\w+)"', out):
        done = _ease_clip(spec, m.group(1), 0.85, {re.sub(r"^R", "L", m.group(2))}) or done
    return done


def _apply_fix(spec: dict, out: str) -> bool:
    """Apply every fix the engine's BLOCK lines name (several can be wrong at once)."""
    done = False
    for fix in (_fix_joint_range, _fix_size, _fix_proportion, _fix_containment, _fix_clearance, _fix_clip):
        done = fix(spec, out) or done
    return done


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
    fixes, seen = 0, {}
    try:
        for attempt in range((max_fixes + 1) if autofix else 1):
            tmp.write_text(json.dumps(_clean(data), indent=1), encoding="utf-8")
            if out_glb.is_file():
                out_glb.unlink()                             # a refused build must not leave the last one
            code, out = _run_engine(tmp, out_glb)
            if code == 0 and out_glb.is_file():
                return {"ok": True, "glb": str(out_glb), "bytes": out_glb.stat().st_size, "fixes": fixes}
            msg = _block_message(out)
            key = re.sub(r"[\d.]+", "#", msg)[:200]             # the same refusal, numbers aside
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 3 or not (autofix and _apply_fix(data, out)):
                raise AnyCreatureError(msg)                  # not converging: say what the engine said
            fixes += 1
    finally:
        tmp.unlink(missing_ok=True)
    raise AnyCreatureError("the build still would not stand after %d fixes" % max_fixes)


def _clean(spec: dict) -> dict:
    """The spec without LOKI's own bookkeeping keys (they start with _ and live on volumes)."""
    out = dict(spec)
    out["volumes"] = [{k: v for k, v in vol.items() if not (k.startswith("_") and k != "_template")}
                      if isinstance(vol, dict) else vol for vol in spec.get("volumes") or []]
    return out


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


def make_from_controls(controls: dict, out_dir, name: str = "", progress=None) -> dict:
    """The window's whole path: a few controls in, a .glb and its four views out.

    The engine's floors are measured in absolute metres, so a handful of exact sizes are refused
    (a fold appears at one scale and not its neighbours). The user asked for "about this big", so the
    backend lands on the nearest size that stands and says which one it used. The same for the
    proportion sliders: when a combination will not stand even with the engine's own fixes applied,
    the sliders are eased back toward the starter's build (which is known to stand) until it does -
    and the result says how far ("eased"), so the window can show the values that were used."""
    c = _effective(controls or {})
    asked = _num(c.get("size"), 1.0, 0.6, 1.6)
    shape = c["shape"]
    stem = name or c.get("name") or "creature"
    last = None
    plan = [(1.0, d) for d in (0, 0.03, -0.03, 0.06, -0.06, 0.09, -0.09)]
    if any(abs(v - 1.0) > 1e-6 for v in shape.values()):
        plan += [(f, d) for f in (0.7, 0.4, 0.0) for d in (0, 0.04, -0.04)]
    for i, (f, delta) in enumerate(plan):
        size = round(min(1.6, max(0.6, asked + delta)), 3)
        used = {k: round(1.0 + (v - 1.0) * f, 3) for k, v in shape.items()}
        if progress and i:
            progress("easing it until it stands" if f < 1 else "trying a size that stands", min(0.85, 0.2 + 0.06 * i))
        try:
            spec = build_spec({**c, "size": size, "shape": used})
            glb = Path(out_dir) / ((_safe_name(stem) or "creature") + ".glb")
            res = compile_spec(spec, glb, autofix=True, max_fixes=10)
        except AnyCreatureError as exc:
            last = exc
            continue
        safe = _safe_name(stem) or "creature"
        out = {**res, "name": glb.name, "stem": safe, "dir": str(out_dir)}
        if progress:
            progress("drawing the four views", 0.9)
        out.update(render_views(glb, Path(out_dir) / (safe + ".views")))
        out.update({"size": size, "asked_size": asked, "size_moved": abs(size - asked) > 1e-6,
                    "shape": used, "asked_shape": shape, "eased": f < 1.0, "ease": round(1.0 - f, 2)})
        return out
    raise last or AnyCreatureError("nothing was built")
