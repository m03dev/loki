"""Thumbs up / down on anything LOKI made (owner 2026-10-26: "give me a way to tell them the images are bad with a
thumbs down or something next to the image if i like it or not").

    rate(ws, rel, rating, reasons, note)   +1 / -1 / 0 (clear) on a picture; kept in <data>/feedback/ratings.jsonl
                                           (one line per rating, newest wins) and in the picture's sidecar
    rating_of(ws, rel) / ratings(ws)       what the owner said
    preferences(ws)                        liked vs disliked per style, model, backend, folder + the top reasons
    hints(ws, folder)                      short "avoid ..." lines from the owner's reasons - added to the prompt of
                                           the next picture made for that folder (images, turnarounds, sprites...)

What a thumbs down does beyond being remembered:
  - the picture belongs to an asset in the pipeline (engine/asset_pipeline.py) -> a retake note on its stage, so
    that stage is redone with the owner's reasons and everything after it follows
  - a lesson for that stage (concept / turnaround / render): the agents read it in their brief next time
A thumbs up stars the picture too (the daily creation and "more like this" learn from stars).

Ideas: Midjourney's rating parties, Krea / Draw Things likes; no aesthetic model is downloaded (LAION aesthetic /
PickScore / ImageReward are possible later - licences in docs/PIPELINE_RESEARCH_2026-10-26.md).
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

REASONS = {
    "match": "does not match the concept / design",
    "perspective": "wrong view or perspective (not flat orthographic)",
    "text": "text, letters or labels in the picture",
    "anatomy": "bad anatomy, extra or missing limbs",
    "detail": "blurry or low detail",
    "style": "wrong art style",
    "colour": "wrong colours",
    "background": "background not plain / scenery",
    "cropped": "cut off or not all in frame",
    "pose": "wrong pose (not a T-pose / neutral pose)",
    "boring": "boring composition",
}
AVOID = {   # what the next prompt says when the owner keeps giving this reason
    "text": "absolutely no text, letters, numbers, labels or captions anywhere",
    "perspective": "strictly flat orthographic projection, camera exactly level with the subject",
    "anatomy": "anatomically correct, the right number of limbs, fingers and toes",
    "detail": "sharp focus, crisp fine detail",
    "background": "alone on a plain flat background, no scenery, no ground",
    "cropped": "the whole subject in frame with a clear margin around it",
    "pose": "standing still in a neutral reference pose, limbs straight and symmetrical",
    "match": "follow the reference design exactly: same shapes, proportions and colours",
    "colour": "keep the colours of the reference exactly",
}


def _data(data_dir: Path | None = None) -> Path:
    return Path(data_dir or os.environ.get("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data"))


def log_path(data_dir: Path | None = None) -> Path:
    return _data(data_dir) / "feedback" / "ratings.jsonl"


def _rows(data_dir=None) -> list:
    out = []
    try:
        for ln in log_path(data_dir).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _safe_rel(ws: Path, rel: str) -> str:
    rel = str(rel or "").replace("\\", "/").strip("/")
    if rel.startswith("creations/"):
        rel = rel[len("creations/"):]
    p = (Path(ws) / rel).resolve()
    if Path(ws).resolve() not in p.parents or not p.is_file():
        return ""
    return rel


def _meta(ws: Path, rel: str) -> dict:
    try:
        import creations  # pylint: disable=import-outside-toplevel
        return creations.read_meta(ws, rel)
    except Exception:  # noqa: BLE001
        return {}


def rate(ws: Path, rel: str, rating: int, reasons=None, note: str = "", data_dir=None, pipeline=True) -> dict:
    ws = Path(ws)
    rel = _safe_rel(ws, rel)
    if not rel:
        return {"ok": False, "error": "no such picture in this workspace"}
    rating = 1 if int(rating or 0) > 0 else (-1 if int(rating or 0) < 0 else 0)
    reasons = [r for r in (reasons or []) if r in REASONS][:6]
    note = " ".join(str(note or "").split())[:400]
    meta = _meta(ws, rel)
    row = {"path": rel, "rating": rating, "reasons": reasons, "note": note, "t": time.time(),
           "folder": rel.split("/")[0], "style": meta.get("style", ""), "backend": meta.get("backend", ""),
           "model": meta.get("model", ""), "prompt": str(meta.get("prompt") or "")[:300]}
    path = log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    try:   # the picture's own sidecar (creations/.meta) - the Home wall and "more like this" read it
        import creations  # pylint: disable=import-outside-toplevel
        if creations.meta_path(ws, rel) is not None:
            creations.write_meta(ws, rel, rating=rating, reasons=reasons, note=note,
                                 **({"liked": True} if rating > 0 else {"liked": False} if rating < 0 else {}))
    except Exception:  # noqa: BLE001
        pass
    out = {"ok": True, "path": rel, "rating": rating, "reasons": reasons}
    if rating < 0 and pipeline:
        out.update(_to_pipeline(ws, rel, reasons, note))
    return out


def _to_pipeline(ws: Path, rel: str, reasons: list, note: str) -> dict:
    """A thumbs down on a pipeline output: a retake note on that stage + a lesson for it."""
    try:
        import asset_pipeline as ap  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        return {}
    why = "; ".join([REASONS[r] for r in reasons] + ([note] if note else [])) or "the owner did not like it"
    for asset in ap.assets(ws):
        for stage in ap.ORDER:
            v = asset["stages"][stage].get("approved")
            if not v:
                continue
            rec = ap.resolve(ws, ap.ref(asset["id"], stage, v)) or {}
            if rel in (rec.get("outputs_rel") or []):
                n = ap.note(ws, asset["id"], stage, "Owner thumbs down on %s: %s" % (Path(rel).name, why),
                            author="owner", retake=True)
                ap.add_lesson(stage, asset["kind"], "The owner rejected a %s: %s." % (stage, why), source=n["id"])
                return {"retake": {"asset": asset["id"], "stage": stage, "note": n["id"]}}
    stage = {"images": "concept", "turnarounds": "turnaround", "renders": "render"}.get(rel.split("/")[0])
    if stage and reasons:
        ap.add_lesson(stage, "any", "The owner rejected a %s: %s." % (stage, why), source="feedback:" + rel)
        return {"lesson": stage}
    return {}


def ratings(ws: Path, data_dir=None) -> dict:
    """{path: the latest row} - a later rating replaces an earlier one; 0 clears."""
    last = {}
    for r in _rows(data_dir):
        last[r["path"]] = r
    return {p: r for p, r in last.items() if r.get("rating")}


def rating_of(ws: Path, rel: str, data_dir=None) -> int:
    return int((ratings(ws, data_dir).get(str(rel)) or {}).get("rating") or 0)


def preferences(ws: Path, data_dir=None) -> dict:
    rows = list(ratings(ws, data_dir).values())
    out = {"liked": sum(1 for r in rows if r["rating"] > 0), "disliked": sum(1 for r in rows if r["rating"] < 0)}
    for key in ("style", "model", "backend", "folder"):
        c = Counter()
        for r in rows:
            if r.get(key):
                c[(r[key], "up" if r["rating"] > 0 else "down")] += 1
        out[key] = {k: {"up": c[(k, "up")], "down": c[(k, "down")]} for k in {k for k, _ in c}}
    out["reasons"] = Counter(x for r in rows if r["rating"] < 0 for x in r.get("reasons") or []).most_common(8)
    return out


def hints(ws: Path, folder: str = "images", data_dir=None, min_count: int = 1) -> str:
    """The owner's repeated complaints for a folder, as prompt words for the next picture made there."""
    c = Counter(x for r in ratings(ws, data_dir).values() if r["rating"] < 0 and r.get("folder") == folder
                for x in r.get("reasons") or [])
    return ", ".join(AVOID[k] for k, n in c.most_common() if n >= min_count and k in AVOID)
