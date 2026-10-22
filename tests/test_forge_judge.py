"""E19 - LOKI judges its own 3D (engine/forge_judge.py + the judge step in engine/forge3d.make_3d).

Offline and under a minute: the four view renders of two fixture meshes (a good closed ball and a
broken one), a FAKE vision model (no network), the score it gets back (plain JSON, a fenced block, a
bare number, a bad answer), the retry-once-and-keep-the-better rule, and the scores kept for
speed_watch / self_review (history / best_backend / summary).

    python tests/test_forge_judge.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-forge-judge-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_TRIPOSR_DIR"] = str(TMP / "no-triposr")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import forge3d  # noqa: E402
import forge_judge  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def ball(scale, colour=(1.0, 0.2, 0.2), rings=10):
    """A closed sphere as a forge3d mesh dict: the GOOD fixture. A tiny scale is the BROKEN one."""
    pos, nrm, col, idx = [], [], [], []
    sides = rings * 2
    for i in range(rings + 1):
        v = i / rings
        for j in range(sides):
            th, ph = v * math.pi, (j / sides) * 2 * math.pi
            x, y, z = (math.sin(th) * math.cos(ph) * scale, math.cos(th) * scale,
                       math.sin(th) * math.sin(ph) * scale)
            pos.append([x, y, z])
            nrm.append([x, y, z])
            col.append(list(colour))
    for i in range(rings):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c, d = (i + 1) * sides + j, (i + 1) * sides + (j + 1) % sides
            idx += [a, c, b, b, c, d]
    return {"positions": pos, "normals": nrm, "colors": col, "indices": idx}


GOOD = TMP / "good.glb"
BROKEN = TMP / "broken.glb"
forge3d.write_glb(GOOD, ball(1.0), name="good")
forge3d.write_glb(BROKEN, ball(0.02), name="broken")
SRC = TMP / "source.png"
im = Image.new("RGB", (160, 160), "white")
ImageDraw.Draw(im).ellipse((40, 40, 120, 120), fill=(220, 40, 40))
im.save(SRC)

# ------------------------------------------------------------------ the scores the vision model sends back
check("plain JSON is read", forge_judge.parse_verdict(
    '{"score": 0.8, "shape": 0.7, "colour": 0.9, "missing": [], "note": "close"}')["score"] == 0.8)
fenced = forge_judge.parse_verdict('```json\n{"score": 0.2, "missing": ["tail"], "note": "flat"}\n```')
check("a fenced block is read, and the missing parts with it",
      fenced["score"] == 0.2 and fenced["missing"] == ["tail"], fenced)
check("a bare number in a sentence is still a score", forge_judge.parse_verdict("I would say 0.55 overall")["score"] == 0.55)
check("a score is clamped into 0..1", forge_judge.parse_verdict('{"score": 1.7}')["score"] == 1.0)
check("no overall score averages shape + colour", forge_judge.parse_verdict('{"shape": 0.4, "colour": 0.6}')["score"] == 0.5)
for bad in ("", "no idea at all", "the model is a nice shape I think"):
    try:
        forge_judge.parse_verdict(bad)
        check("a bad answer raises JudgeError (%r)" % bad[:20], False, "no error")
    except forge_judge.JudgeError:
        check("a bad answer raises JudgeError (%r)" % bad[:20], True)
check("the low-score line matches forge3d", forge_judge.LOW == forge3d.JUDGE_LOW)

# ------------------------------------------------------------------ four renders of a real Forge .glb
views = forge_judge._default_views(str(GOOD), str(TMP / "good.views"))
names = set(views.get("views", {}))
check("the judge renders all four angles (front/side/top/hero)",
      names == set(forge_judge.VIEWS), names)
check("every rendered view is a real PNG",
      all(Path(p).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for p in views["views"].values()))
broken_views = forge_judge._default_views(str(BROKEN), str(TMP / "broken.views"))
check("a broken mesh still renders four views (a tiny blob)", len(broken_views["views"]) == 4)

# ------------------------------------------------------------------ match(): the fake vision model
shots = []


def fake_vision(images, prompt):
    shots.append((len(images), prompt))
    return '{"score": 0.9, "shape": 0.9, "colour": 0.85, "missing": [], "note": "matches the picture"}'


verdict = forge_judge.match(str(GOOD), str(SRC), ask=fake_vision, out_dir=TMP / "j1")
check("match asks the vision model with the source + the four views (5 pictures)",
      shots and shots[-1][0] == 5, shots)
check("the prompt names shape, colour and missing parts",
      all(w in shots[-1][1] for w in ("shape", "colour", "missing")) and "JSON" in shots[-1][1])
check("the verdict carries the score, the parts and the backend slot",
      verdict["score"] == 0.9 and verdict["shape"] == 0.9 and verdict["colour"] == 0.85
      and verdict["missing"] == [] and len(verdict["views"]) == 4, verdict)

# a fake model that plays along with the fixture: good = high, broken = low
def scoring_vision(images, prompt):
    return '{"score": 0.95, "missing": [], "note": "good"}'


def scoring_broken(images, prompt):
    return '{"score": 0.15, "missing": ["legs", "head"], "note": "a blob"}'


good_v = forge_judge.match(str(GOOD), str(SRC), ask=scoring_vision, out_dir=TMP / "j2")
broken_v = forge_judge.match(str(BROKEN), str(SRC), ask=scoring_broken, out_dir=TMP / "j3")
check("the good fixture scores high and the broken one low",
      good_v["score"] >= 0.9 and broken_v["score"] < forge_judge.LOW, (good_v["score"], broken_v["score"]))
check("the broken one says what is missing", broken_v["missing"] == ["legs", "head"])

# a bad vision answer must not crash the verdict - it becomes a JudgeError
try:
    forge_judge.match(str(GOOD), str(SRC), ask=lambda i, p: "cannot tell", out_dir=TMP / "j4")
    check("a vision answer with no score raises JudgeError", False, "no error")
except forge_judge.JudgeError:
    check("a vision answer with no score raises JudgeError", True)

# ------------------------------------------------------------------ the score is kept (speed_watch / self_review)
hist_path = TMP / "data" / "forge_scores.jsonl"
forge_judge.judge_one(str(GOOD), str(SRC), "lift", ask=scoring_vision, out_dir=TMP / "h1", path=hist_path)
forge_judge.judge_one(str(BROKEN), str(SRC), "lift", ask=scoring_broken, out_dir=TMP / "h2", path=hist_path)
forge_judge.judge_one(str(GOOD), str(SRC), "triposr", ask=scoring_vision, out_dir=TMP / "h3", path=hist_path)
hist = forge_judge.history(hist_path)
check("every verdict is kept as JSON lines", hist_path.is_file() and len(hist) == 3, len(hist))
check("a kept row has the backend, the score and the missing parts",
      hist[0]["backend"] == "lift" and hist[0]["score"] == 0.95 and hist[1]["missing"] == ["legs", "head"], hist[0])
best = forge_judge.best_backend(hist_path)
check("best_backend ranks the backend the vision model liked most",
      best["backend"] == "triposr" and best["scores"]["triposr"] == 0.95 and best["counts"]["lift"] == 2, best)
check("the summary line names the best backend here", "triposr" in forge_judge.summary(hist_path), forge_judge.summary(hist_path))
check("history(limit=1) returns just the newest", len(forge_judge.history(hist_path, limit=1)) == 1)
check("a missing scores file reads as empty, not an error", forge_judge.history(TMP / "none.jsonl") == [])
check("no rows at all summarises as 'no 3D judged yet'", forge_judge.summary(TMP / "none.jsonl") == "no 3D judged yet")

# ------------------------------------------------------------------ the retry in make_3d (two backends)
forge3d.triposr_ready = lambda: True          # pretend two backends exist so a retry has somewhere to go
made: list = []


def fake_triposr(cut_png, base, runner=None, timeout=1800, opts=None):
    out = Path(str(base) + "-tri.glb")
    forge3d.write_glb(out, ball(1.0), name="tri")     # a real, renderable mesh
    made.append(out)
    return {"glb": str(out), "obj": ""}


forge3d.run_triposr = fake_triposr
check("with triposr 'installed' the plan offers two backends", forge3d.plan("auto") == ["triposr", "lift"])

seen: list = []


def first_low(glb, source, backend):
    """The first backend (triposr) scores low, the retry (lift) scores high."""
    seen.append(backend)
    return {"score": 0.2 if backend == "triposr" else 0.9, "missing": [], "backend": backend}


res = forge3d.make_3d(str(SRC), TMP / "m1", prompt="red ball", backend="auto", judge=first_low)
check("a low score retries once with the other backend", res.get("ok") and seen == ["triposr", "lift"], seen)
check("the retry that scored better is the one kept",
      res.get("backend") == "lift" and res.get("judge", {}).get("score") == 0.9 and res.get("judged") is True, res.get("backend"))
check("the model that lost is removed (one .glb left)",
      len(list((TMP / "m1").glob("*.glb"))) == 1, [p.name for p in (TMP / "m1").glob("*.glb")])
check("the kept .glb is a real model", Path(res["glb"]).is_file() and Path(res["glb"]).read_bytes()[:4] == b"glTF")

seen2: list = []


def retry_worse(glb, source, backend):
    """The first backend scores low so a retry fires, but the retry (lift) scores even worse."""
    seen2.append(backend)
    return {"score": 0.55 if backend == "triposr" else 0.1, "backend": backend}


res2 = forge3d.make_3d(str(SRC), TMP / "m2", prompt="red ball 2", backend="auto", judge=retry_worse)
check("a retry that scores worse is thrown away",
      res2.get("backend") == "triposr" and res2.get("judge", {}).get("score") == 0.55 and seen2 == ["triposr", "lift"], seen2)
check("only one model is left after a losing retry", len(list((TMP / "m2").glob("*.glb"))) == 1)

# a high first score needs no retry, and no judge at all is the old behaviour
seen3: list = []


def always_good(glb, source, backend):
    seen3.append(backend)
    return {"score": 0.99, "backend": backend}


res3 = forge3d.make_3d(str(SRC), TMP / "m3", prompt="red ball 3", backend="auto", judge=always_good)
check("a high score does not retry", seen3 == ["triposr"] and res3.get("judged") is False, seen3)
res4 = forge3d.make_3d(str(SRC), TMP / "m4", prompt="red ball 4", backend="lift")
check("without a judge make_3d is unchanged (no judge keys)", res4.get("ok") and "judge" not in res4 and "judged" not in res4)
check("the sidecar keeps the verdict for the window",
      "judge" in res3["meta"] and res3["meta"]["judge"]["score"] == 0.99, res3.get("meta", {}).get("judge"))
check("a judge that cannot look does not undo the model (None score, no retry)",
      forge3d.make_3d(str(SRC), TMP / "m5", prompt="red ball 5", backend="lift",
                      judge=lambda g, s, b: {"score": None, "error": "no vision"}).get("ok") is True)

# ------------------------------------------------------------------ the API hands the build a judge
import forge_api  # noqa: E402


class _Agent:
    WORKSPACE = str(TMP / "ws")


class _State:
    agent = _Agent()


(TMP / "ws" / "models").mkdir(parents=True, exist_ok=True)
os.environ.pop("LOKI_FORGE_JUDGE", None)
os.environ["LOKI_VISION_MODEL"] = "test-vision"        # a vision model is configured: judge on
check("the Forge API points the build at the judge when a vision model exists", callable(forge_api._judge(_State())))
os.environ["LOKI_FORGE_JUDGE"] = "0"
check("LOKI_FORGE_JUDGE=0 turns judging off", forge_api._judge(_State()) is None)
os.environ.pop("LOKI_FORGE_JUDGE", None)
os.environ.pop("LOKI_VISION_MODEL", None)
_real = forge_judge.vision_ready
forge_judge.vision_ready = lambda: False           # pretend no vision model is reachable
check("with no vision model the API hands over no judge (a build never waits to find out)",
      forge_api._judge(_State()) is None)
forge_judge.vision_ready = _real
check("vision_ready() is a plain bool (never raises)", isinstance(_real(), bool))
os.environ["LOKI_FORGE_JUDGE"] = "0"
check("with LOKI_FORGE_JUDGE=0 the API hands over no judge, vision model or not", forge_api._judge(_State()) is None)
os.environ.pop("LOKI_FORGE_JUDGE", None)


class _AgentWithJudge(_Agent):
    forge_judge = staticmethod(lambda glb, src, backend: {"score": 1.0})   # a window/test can inject one


class _StateWithJudge:
    agent = _AgentWithJudge()


check("an injected judge is used as it is", forge_api._judge(_StateWithJudge()) is _AgentWithJudge.forge_judge)

# ------------------------------------------------------------------ documented, in ship's suites, one code path
check("E19 is ticked in docs/EVOLVE.md", "- [x] E19" in (REPO / "docs" / "EVOLVE.md").read_text(encoding="utf-8"))
check("the new suite is in ship.py's SUITES", '"test_forge_judge"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
src = (REPO / "engine" / "forge_judge.py").read_text(encoding="utf-8")
check("forge_judge adds no heavy dependency (standard library only)",
      "import numpy" not in src and "import torch" not in src and "import requests" not in src)
check("the module never imports loki or any engine at module level (only inside a function)",
      not any(ln.startswith(("import loki", "import forge3d", "import anycreature"))
              for ln in src.splitlines()) and "import loki  # noqa" in src)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
