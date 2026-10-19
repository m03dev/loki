"""anyCreature (contrib/anycreature/, MIT) behind LOKI: an ACS spec -> a creature .glb, plus the
front / side / top / hero views the quality gates judge.

    anycreature.available()                   Node + the vendored engine present?
    anycreature.compile_spec(spec, out_glb)   spec (a dict, JSON text, or a .json path) -> out_glb
    anycreature.render_views(glb, out_dir)    -> {"front": png, "side": png, "top": png, "hero": png}
    anycreature.make(spec, out_dir, name)     compile + render: <out_dir>/<name>.glb and <name>.views/

The engine is zero-dependency Node (`node contrib/anycreature/engine/cli.js spec.json out.glb`);
the views are pure Python (contrib/anycreature/harness/outline.py, numpy + pillow - no browser, no
GPU, no download). LOKI's own glue; the vendored code is unchanged (see contrib/anycreature/NOTICE.md).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "contrib" / "anycreature"
ENGINE = VENDOR / "engine" / "cli.js"
OUTLINE = VENDOR / "harness" / "outline.py"
VIEWS = ("front", "side", "top", "hero")
TIMEOUT = 240


class AnyCreatureError(RuntimeError):
    """The spec was refused, the engine is missing, or a view did not render."""


def available() -> dict:
    """What of the vendored engine is usable here (the UI hides the feature when this is not ok)."""
    node = shutil.which("node")
    return {"engine": ENGINE.is_file(), "outline": OUTLINE.is_file(), "node": bool(node),
            "ok": bool(node) and ENGINE.is_file() and OUTLINE.is_file()}


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise AnyCreatureError("Node is not installed (the anyCreature engine is Node)")
    return node


def compile_spec(spec, out_glb) -> dict:
    """Compile an ACS spec into out_glb (a skinned, animated GLB). Raises AnyCreatureError.

    spec may be an existing .json path (passed straight to the engine, so the vendored example keeps
    its exemption), or a dict / JSON text (written to a temp file the engine never saw before).
    """
    out_glb = Path(out_glb)
    src, tmp, text = None, None, ""
    if isinstance(spec, (str, Path)):
        path = Path(spec)
        try:
            is_path = path.is_file()
        except OSError:              # a long JSON string is not a path (a huge "filename")
            is_path = False
        if is_path:
            src = path
        else:
            text = str(spec)
    else:
        text = json.dumps(spec)
    if not ENGINE.is_file():
        raise AnyCreatureError("the vendored engine is missing (%s)" % ENGINE)
    if src is None:
        try:
            json.loads(text)
        except ValueError as exc:
            raise AnyCreatureError("the spec is not valid JSON: %s" % exc) from exc
        out_glb.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_glb.with_name(out_glb.stem + ".spec.json")
        tmp.write_text(text, encoding="utf-8")
        src = tmp
    try:
        proc = subprocess.run([_node(), str(ENGINE), str(src), str(out_glb)],
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise AnyCreatureError("the engine did not finish in %ds" % TIMEOUT) from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    if proc.returncode != 0 or not out_glb.is_file():
        tail = " ".join((proc.stdout + proc.stderr).split())[-500:]
        raise AnyCreatureError("the creature did not compile: " + (tail or "exit %d" % proc.returncode))
    return {"ok": True, "glb": str(out_glb), "bytes": out_glb.stat().st_size}


def render_views(glb, out_dir) -> dict:
    """Draw the front / side / top / hero silhouettes of a GLB into out_dir. Raises AnyCreatureError."""
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
        tail = " ".join((proc.stdout + proc.stderr).split())[-400:]
        raise AnyCreatureError("the views did not render: " + (tail or "exit %d" % proc.returncode))
    return {"ok": True, "views": made}


def make(spec, out_dir, name: str = "creature") -> dict:
    """Compile + render in one call: <out_dir>/<name>.glb plus <out_dir>/<name>.views/*.png."""
    out_dir = Path(out_dir)
    safe = "".join(c for c in str(name) if c.isalnum() or c in "-_") or "creature"
    glb = out_dir / (safe + ".glb")
    res = compile_spec(spec, glb)
    views = render_views(glb, out_dir / (safe + ".views"))
    return {**res, **views, "name": glb.name, "stem": safe, "dir": str(out_dir)}
