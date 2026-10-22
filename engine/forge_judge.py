"""E19 - LOKI judges its own 3D.

After Forge makes a model (engine/forge3d.py), this draws the model from four angles, shows those
renders PLUS the source picture to a vision model, and gets back a score for how well they match -
shape, colour, missing parts. When the score is low the caller retries once with a better backend
or a better prompt. Every score is kept in harness_data/forge_scores.jsonl so speed_watch and
self_review can see which backend works best on this machine.

    judge.match(glb, source_png, ask=..., views=None)   -> a verdict dict
    judge.history(path=None)                            -> the kept rows, oldest first
    judge.best_backend(path=None)                       -> {"backend": mean score}, the winner
    judge.LOW                                              the score under which a retry is worth it

`ask(png_bytes, prompt) -> str` is the only outside call (the vision model). Tests pass a fake.
`views` is an injected renderer `(glb, out_dir) -> {"front": png, ...}` (engine/anycreature.render_views
by default), so the whole thing can be exercised offline.

Pure standard library - no new dependency, nothing runs on startup, nothing slows the window.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOW = 0.6                       # below this, a retry with another backend / a sharper prompt
VIEWS = ("front", "side", "top", "hero")

PROMPT = (
    "You are judging a 3D model against the picture it was made from.\n"
    "Picture 1 is the source. Pictures 2..%d are the model rendered from %s.\n"
    "Score how well the model matches the source, from 0.0 (nothing alike) to 1.0 (a perfect match):\n"
    "- shape: does the silhouette and the proportions match?\n"
    "- colour: are the colours right?\n"
    "- parts: is anything missing, extra or in the wrong place?\n"
    "Reward what is there; do NOT punish the plain background or the flat lighting.\n"
    "Reply with ONLY a JSON object, no prose:\n"
    '{"score": <0..1>, "shape": <0..1>, "colour": <0..1>, "missing": ["<part>", ...], '
    '"note": "<one short sentence>"}'
)


class JudgeError(Exception):
    pass


def _clamp(v, default=0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return round(max(0.0, min(1.0, f)), 3)


def parse_verdict(text: str) -> dict:
    """Read the vision model's answer. Plain JSON is best; a fenced block or a sentence with a JSON
    object in it are read too. A number with no JSON at all is still a score. Raises JudgeError."""
    raw = (text or "").strip()
    if not raw:
        raise JudgeError("the vision model answered nothing")
    body = raw
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        body = fence.group(1).strip()
    obj = None
    try:
        obj = json.loads(body)
    except Exception:  # noqa: BLE001 - a sentence around the object, or a bare number
        brace = re.search(r"\{.*\}", body, re.S)
        if brace:
            try:
                obj = json.loads(brace.group(0))
            except Exception:  # noqa: BLE001
                obj = None
    if isinstance(obj, dict):
        score = obj.get("score")
        if score is None:                         # no overall score: average what it did give
            parts = [_clamp(obj[k], None) for k in ("shape", "colour") if obj.get(k) is not None]
            score = sum(parts) / len(parts) if parts else None
        if score is None:
            raise JudgeError("the vision model gave no score")
        out = {"score": _clamp(score)}
        for k in ("shape", "colour"):
            if obj.get(k) is not None:
                out[k] = _clamp(obj[k])
        missing = obj.get("missing")
        if isinstance(missing, str):
            missing = [missing] if missing.strip() else []
        elif isinstance(missing, list):
            missing = [str(m) for m in missing if str(m).strip()]
        else:
            missing = []
        out["missing"] = missing
        out["note"] = str(obj.get("note") or "").strip()[:240]
        out["parsed"] = True
        return out
    num = re.search(r"(?<![\d.])(\d(?:\.\d+)?|\.\d+)", body)   # a bare 0.8 / 1.0 / 0.35
    if num:
        return {"score": _clamp(num.group(1)), "missing": [], "note": body[:240], "parsed": False}
    raise JudgeError("could not read a score out of: " + raw[:160])


def _png_bytes(path) -> bytes:
    p = Path(path)
    if not p.is_file():
        raise JudgeError("no picture at %s" % p)
    return p.read_bytes()


OUTLINE = ROOT / "contrib" / "anycreature" / "harness" / "outline.py"


def _default_views(glb, out_dir) -> dict:
    """Draw the four angles with the vendored software rasteriser (contrib/anycreature/harness/
    outline.py, MIT) - pure Python, no browser, no Node, so it works for any Forge model. Falls back
    to anyCreature's own renderer (which needs Node) only if the rasteriser is not there."""
    if OUTLINE.is_file():
        import subprocess  # noqa: PLC0415
        import sys  # noqa: PLC0415
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run([sys.executable, str(OUTLINE), str(glb), str(out_dir),
                                   "--views", ",".join(VIEWS)],
                                  capture_output=True, text=True, timeout=300, shell=False)
        except OSError as exc:
            raise JudgeError("could not render the model: %s" % exc) from exc
        made = {v: str(out_dir / ("sil_%s.png" % v)) for v in VIEWS if (out_dir / ("sil_%s.png" % v)).is_file()}
        if made:
            return {"ok": True, "views": made}
        tail = " ".join(((proc.stdout or "") + (proc.stderr or "")).split())[-300:]
        raise JudgeError("the model did not render: " + (tail or "exit %d" % proc.returncode))
    import anycreature  # noqa: PLC0415 - the Node path; only when the rasteriser is missing
    return anycreature.render_views(glb, out_dir)


def _view_list(views) -> list:
    if isinstance(views, dict):
        got = views.get("views") if "views" in views else views
        if isinstance(got, dict):
            return [(k, got[k]) for k in VIEWS if got.get(k)] or [(k, v) for k, v in got.items()]
    return []


def ask_prompt(n_views: int) -> str:
    return PROMPT % (n_views + 1, "/".join(VIEWS[:n_views]))


def match(glb, source, *, ask, views=None, out_dir=None, backend: str = "") -> dict:
    """Render `glb` from four angles, ask the vision model to compare it with `source`, and return
    {"score", "shape", "colour", "missing", "note", "views", "backend"}. `ask(png, prompt) -> str`;
    `views(glb, out_dir) -> {...}` (engine/anycreature.render_views by default)."""
    if ask is None:
        raise JudgeError("no vision model to ask")
    glb = Path(glb)
    if not glb.is_file():
        raise JudgeError("no model at %s" % glb)
    folder = Path(out_dir) if out_dir else (glb.parent / (glb.stem + ".views"))
    renderer = views or _default_views
    got = renderer(str(glb), str(folder))
    rendered = _view_list(got)
    files = [p for _, p in rendered]
    if not files:
        raise JudgeError("the model was not rendered from any angle")
    try:
        imgs = [_png_bytes(source)]                # the source picture goes first
    except JudgeError:
        imgs = []                                  # no source picture: the renders must speak alone
    imgs += [_png_bytes(p) for p in files]
    text = ask(imgs, ask_prompt(len(files)))
    out = parse_verdict(text)
    out["views"] = [str(p) for p in files]
    out["backend"] = backend
    out["t"] = time.time()
    out["glb"] = str(glb)
    return out


def scores_path(path=None) -> Path:
    if path:
        return Path(path)
    import os  # noqa: PLC0415
    data = os.environ.get("LOKI_DATA") or (ROOT / "harness_data")
    return Path(data) / "forge_scores.jsonl"


def record(verdict: dict, *, backend: str = "", path=None, attempt: int = 0, ok: bool = True) -> dict:
    """Append one verdict to the scores file (JSON lines). Never raises - a judge that cannot write
    its note must not break the build it just made."""
    row = {"kind": "forge_judge", "t": time.time(), "backend": backend or verdict.get("backend") or "",
           "score": verdict.get("score"), "shape": verdict.get("shape"), "colour": verdict.get("colour"),
           "missing": verdict.get("missing") or [], "note": verdict.get("note") or "",
           "attempt": attempt, "ok": bool(ok), "glb": verdict.get("glb") or ""}
    try:
        p = scores_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - a note that cannot be kept is not a reason to fail a build
        pass
    return row


def vision_ready() -> bool:
    """Cheap, no network: is there a vision model the judge can ask? LOKI_VISION_MODEL when set,
    else LOKI's active model if it is a real chat model (not a CLI agent). Never raises."""
    import os  # noqa: PLC0415
    want = str(os.getenv("LOKI_VISION_MODEL", "") or "").strip()
    if want:
        return True
    try:
        import loki  # noqa: PLC0415
        cfg = loki.MODELS[loki.active_model_name()]
        return not str(cfg.base_url).startswith(loki.CLI_AGENT_PREFIX)
    except Exception:  # noqa: BLE001 - no loki, no models, a broken config: no judge then
        return False


def judge_one(glb, source, backend="", *, ask=None, views=None, out_dir=None, path=None, attempt=0) -> dict:
    """The one call forge3d.make_3d needs: judge a model and keep the score.

    `ask(png_list, prompt) -> str` is the vision model (engine/loki._vision_ask adapted by the
    caller); when it is not given, LOKI's own vision tool is used - one question, then it is gone."""
    own = ask is None
    if own:
        ask = vision_ask
    verdict = match(glb, source, ask=ask, views=views, out_dir=out_dir, backend=backend)
    record(verdict, backend=backend, path=path, attempt=attempt, ok=True)
    return verdict


def vision_ask(images, prompt: str) -> str:
    """LOKI's own vision model (LOKI_VISION_MODEL, else the active one), asked about several pictures.
    Runs a private event loop so it works from Forge's job thread, exactly as read_document does."""
    import asyncio  # noqa: PLC0415
    import base64  # noqa: PLC0415
    import os  # noqa: PLC0415

    import loki  # noqa: PLC0415 - the agent core is a heavy import; only the real judge pays for it
    want = str(os.getenv("LOKI_VISION_MODEL", "") or "").strip()
    if want and want in loki.MODELS:
        cfg = loki.MODELS[want]
        base, key, model = cfg.base_url, cfg.api_key, cfg.model
    elif want:
        base, key, model = "http://localhost:11434/v1", "ollama", want
    else:
        cfg = loki.MODELS[loki.active_model_name()]
        base, key, model = cfg.base_url, cfg.api_key, cfg.model
    if str(base).startswith(loki.CLI_AGENT_PREFIX):
        raise JudgeError("the active model is a CLI agent; set LOKI_VISION_MODEL to a vision model")
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}
                for png in images]
    # A judge must never hold up a build: its own timeout, and no retries of its own.
    timeout = float(os.getenv("LOKI_FORGE_JUDGE_TIMEOUT", "90") or 90)
    client = loki.AsyncOpenAI(base_url=base, api_key=key or "none", timeout=timeout, max_retries=0)

    async def _go():
        r = await client.chat.completions.create(model=model, max_tokens=600,
                                                 messages=[{"role": "user", "content": content}])
        return str(r.choices[0].message.content or "")

    return asyncio.run(_go())


def history(path=None, limit: int = 0) -> list:
    """Every kept verdict, oldest first (the last `limit` when limit > 0). Bad lines are skipped."""
    p = scores_path(path)
    if not p.is_file():
        return []
    rows = []
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows[-limit:] if limit and limit > 0 else rows


def best_backend(path=None) -> dict:
    """Which backend the vision model likes most on this machine: {"backend": mean score, ...}.
    Looks at the models that were actually shipped (ok rows only)."""
    per: dict = {}
    for row in history(path):
        if row.get("ok") is False:
            continue
        b, s = row.get("backend") or "", row.get("score")
        if not b or not isinstance(s, (int, float)):
            continue
        per.setdefault(b, []).append(float(s))
    means = {b: round(sum(v) / len(v), 3) for b, v in per.items() if v}
    rank = sorted(means.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"scores": means, "ranked": [b for b, _ in rank],
            "backend": rank[0][0] if rank else "", "score": rank[0][1] if rank else None,
            "counts": {b: len(v) for b, v in per.items()}}


def summary(path=None) -> str:
    """One line for speed_watch / self_review / a reply."""
    best = best_backend(path)
    rows = history(path)
    if not rows:
        return "no 3D judged yet"
    if not best["backend"]:
        return "%d judged, no score recorded" % len(rows)
    lead = ", ".join("%s %.2f (%d)" % (b, best["scores"][b], best["counts"][b]) for b in best["ranked"][:4])
    return "%d judged - best backend here: %s - %s" % (len(rows), best["backend"], lead)
