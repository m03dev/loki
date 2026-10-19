"""anyCreature (Ariescar/anyCreature, MIT) in LOKI: the ACS text->creature engine and the
front/side/top/hero view renderer, vendored under contrib/anycreature/.

    python tests/test_anycreature.py      (< 60 s, offline: compiles the bundled example spec)

The engine is zero-dependency Node (`node contrib/anycreature/engine/cli.js spec.json out.glb`);
`harness/outline.py` is a pure-Python software rasteriser that draws the silhouettes the quality
gates judge - the FRONT/SIDE/TOP/hero views Forge shows. Both are MIT - see
contrib/anycreature/LICENSE and docs/THIRD_PARTY.md.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AC = REPO / "contrib" / "anycreature"
TMP = Path(tempfile.mkdtemp(prefix="loki-anycreature-"))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("OK  " if ok else "FAIL", name, "" if ok else "  -> %s" % str(detail)[-400:]))


def read(rel):
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- vendored, licensed, no drift
check("the ACS engine is vendored under contrib/anycreature", (AC / "engine" / "cli.js").is_file())
check("the front/side/top view renderer is vendored", (AC / "harness" / "outline.py").is_file())
check("the bundled example spec is present", (AC / "example" / "wolf.json").is_file())
check("the upstream MIT licence is kept beside it",
      (AC / "LICENSE").is_file() and "MIT License" in (AC / "LICENSE").read_text(encoding="utf-8"))
check("a NOTICE records provenance",
      (AC / "NOTICE.md").is_file() and "Ariescar/anyCreature" in (AC / "NOTICE.md").read_text(encoding="utf-8"))
check("THIRD_PARTY.md lists anyCreature", "anyCreature" in read("docs/THIRD_PARTY.md"))
check("the engine carries no npm dependencies (no package.json / node_modules)",
      not (AC / "engine" / "package.json").exists() and not (AC / "engine" / "node_modules").exists())

# --------------------------------------------------------------- the engine compiles the example
node = shutil.which("node")
check("node is available (the engine is Node)", bool(node))
glb = TMP / "wolf.glb"
if node:
    r = subprocess.run([node, str(AC / "engine" / "cli.js"), str(AC / "example" / "wolf.json"), str(glb)],
                       capture_output=True, text=True, timeout=180)
    out = (r.stdout or "") + (r.stderr or "")
    check("the engine compiles example/wolf.json to a GLB (exit 0)", r.returncode == 0, out[-300:])
    check("the result is real glTF binary (magic 'glTF')",
          glb.is_file() and glb.read_bytes()[:4] == b"glTF", glb if glb.exists() else "no file")
    check("the compiler reports a skinned, animated creature (joints + anims)",
          '"joints"' in out and '"anims"' in out, out[-200:])

# --------------------------------------------------------------- the four orthographic views
if node and glb.is_file():
    views = TMP / "views"
    r2 = subprocess.run([sys.executable, str(AC / "harness" / "outline.py"), str(glb), str(views),
                         "--views", "front,side,top,hero"], capture_output=True, text=True, timeout=240)
    out2 = (r2.stdout or "") + (r2.stderr or "")
    check("outline renders the silhouettes (exit 0)", r2.returncode == 0, out2[-300:])
    made = [v for v in ("front", "side", "top", "hero") if (views / ("sil_%s.png" % v)).is_file()]
    check("FRONT, SIDE, TOP and HERO silhouettes are all written", len(made) == 4, "made: %s" % made)
    blobs = [(views / ("sil_%s.png" % v)).read_bytes() for v in made]
    check("they are four distinct views, not the same image four times", len(set(blobs)) == len(blobs))
    check("outline also writes a metrics report",
          (views / "metrics.json").is_file() and "views" in json.loads((views / "metrics.json").read_text()))

# --------------------------------------------------------------- LOKI's glue (engine/anycreature.py)
sys.path.insert(0, str(REPO / "engine"))
import anycreature  # noqa: E402

avail = anycreature.available()
check("engine/anycreature.py finds the vendored engine, the renderer and node", avail["ok"], avail)


def _refuses(fn, *a, **k):
    try:
        fn(*a, **k)
        return False
    except anycreature.AnyCreatureError:
        return True


check("a spec that is not JSON is refused with AnyCreatureError (nothing half-written)",
      _refuses(anycreature.make, "{not json", TMP / "bad", "bad"))
if node:
    gres = anycreature.make(AC / "example" / "wolf.json", TMP / "glue", "wolf")
    check("the glue compiles a spec and renders the four views",
          (TMP / "glue" / "wolf.glb").is_file()
          and all((TMP / "glue" / "wolf.views" / ("sil_%s.png" % v)).is_file() for v in ("front", "side", "top", "hero")),
          gres)
    check("a copied example is a hard floor (example_copy), surfaced as AnyCreatureError",
          _refuses(anycreature.make, (AC / "example" / "wolf.json").read_text(encoding="utf-8"), TMP / "copy", "copy"))

# --------------------------------------------------------------- the Forge routes (engine/forge_api.py)
import forge_api  # noqa: E402
import forge3d  # noqa: E402


class _State:                     # the routes only read state.agent.WORKSPACE
    class agent:                  # noqa: N801
        WORKSPACE = TMP


st = _State()
code, body = forge_api.handle_get(st, "/forge/creature")
check("GET /forge/creature reports the vendored engine", code == 200 and body.get("ok"), body)
code, body = forge_api.handle_get(st, "/forge/creature/view?name=x&view=nope")
check("GET /forge/creature/view refuses a view that is not one of the four", code == 400, body)

if node:
    spec_text = (AC / "example" / "wolf.json").read_text(encoding="utf-8")
    code, job = forge_api.handle_post(st, "/forge/creature", json.dumps({"spec": spec_text, "name": "viaapi"}).encode(), thread=False)
    result = (forge3d.job(job.get("id", "")) or {}).get("result", {}) if code == 200 else {}
    check("POST /forge/creature runs the job and surfaces the engine's BLOCK when a spec is refused",
          code == 200 and result.get("ok") is False and "example_copy" in str(result.get("error", "")), result)
    anycreature.make(AC / "example" / "wolf.json", forge_api.models_dir(st), "viaapi")   # a real model + views
    res2 = forge_api.handle_get(st, "/forge/creature/view?name=viaapi&view=front")
    body2 = res2[1] if len(res2) > 1 else b""
    check("GET /forge/creature/view serves the PNG the UI draws",
          res2[0] == 200 and isinstance(body2, (bytes, bytearray)) and bytes(body2[:4]) == b"\x89PNG", res2[0])

tools_src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8", errors="replace")
check("make_creature is an agent tool (registration + schema + creative category)",
      'LOCAL_TOOLS["make_creature"]' in tools_src and 'TOOL_CATEGORIES["creative"] += ["make_creature"]' in tools_src
      and 'MODEL_TOOL_NAMES.add("make_creature")' in tools_src and '_CREATURE_SCHEMA' in tools_src)

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
