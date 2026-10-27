"""The technical artist: a concept picture -> a turnaround sheet a 3D artist (or LOKI's own 3D makers) can build from.

Owner 2026-10-26: "we should also make a technical artist for concept art but should make tpose and perspective top
side and front drawings from the concepts we get - all the agents should be harmonious, same with the 3d".

    make_turnaround(args, cwd, image_maker)   agent tool (loki-make): concept= a picture here and/or subject= what it
                                              is; kind= character | creature | prop | vehicle; views= front,side,back,top
                                              (default; add three-quarter for a perspective view)

Each view is drawn on its own with the SAME seed and the same fixed description, as a flat orthographic view in a
neutral pose (T-pose for characters) on a plain light grey background - one subject, nothing else - so the views
match each other and cut out cleanly. Saved in turnarounds/:

    turnarounds/<subject>_<stamp>-sheet.png      all views side by side, labelled (shows on Home)
    turnarounds/<subject>_<stamp>/<view>.png     each view alone - the input for multi-view / image-to-3D
    turnarounds/<subject>_<stamp>/turnaround.json  the lineage: which concept, subject, kind, seed, backend, views

so the 3D step (make_3d image=<front view>) and the render step always know where a model came from.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

KINDS = ("character", "creature", "prop", "vehicle")
VIEWS = ("front", "side", "back", "top", "three-quarter")
DEFAULT_VIEWS = ("front", "side", "back", "top")
POSE = {
    "character": "standing in a T-pose, arms straight out to the sides at shoulder height, palms down, legs straight "
                 "and slightly apart, feet flat, neutral face, looking straight ahead",
    "creature": "standing in a neutral reference pose, legs straight and evenly spaced, tail and wings extended and "
                "straight, mouth closed, looking straight ahead",
    "prop": "upright in its rest position, nothing attached, nothing held",
    "vehicle": "parked on flat ground, wheels straight, doors and hatches closed",
}
VIEW_WORDS = {
    "front": "orthographic FRONT view, facing the camera straight on, perfectly symmetrical",
    "side": "orthographic SIDE view, exact left profile, facing left",
    "back": "orthographic BACK view, seen straight from behind",
    "top": "orthographic TOP view, seen straight down from directly above",
    "three-quarter": "three-quarter perspective view from slightly above, 45 degrees to the front left",
}
# Owner 2026-10-26: "the perspective technical images ... are awful, not really making sense". What was wrong (seen on
# the Mac): each view was drawn from TEXT only, so a red pixel-art dragon came back as a grey realistic one; words like
# "model sheet" made the model write fake labels on the picture; scenes (a library interior) were "turned around".
# Now: the concept picture is the REFERENCE for every view (FLUX.2 klein edits on NVIDIA, the Mac's hosted model),
# the front view joins it as a second reference for the rest, the wording never asks for a sheet or labels, a scene is
# refused, and every view is scored against the concept's colours.
VIEW_STYLE = ("orthographic projection, no perspective distortion, the whole subject in frame with a margin, alone on a "
              "plain flat light grey background, even flat studio lighting, no cast shadow, no ground, no scenery, no "
              "text, no letters, no labels, no border, crisp clean edges")
SHEET_STYLE = VIEW_STYLE          # older callers
SHEET_NEG = ("perspective distortion, dramatic lighting, background scenery, ground, multiple subjects, extra limbs, "
             "cropped, cut off, text, letters, labels, caption, watermark, logo, border, frame, blurry, dynamic pose")
SCENE_WORDS = ("interior", "landscape", "fortress", "castle", "city", "village", "forest clearing", "scene",
               "environment", "skyline", "panorama", "widescreen", "16:9", "room", "library", "glacier", "valley",
               "battlefield", "street", "temple interior", "cave interior", "establishing shot")
ROOT = "turnarounds"


def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    if len(slug) > limit:
        cut = slug[:limit + 1]
        slug = cut[:cut.rfind("-")] if "-" in cut[1:] else slug[:limit]
    return slug.strip("-") or "subject"


def subject_of(cwd: Path, concept: str) -> str:
    """What the concept shows, from its sidecar (the prompt it was drawn from) or its file name."""
    try:
        import creations  # pylint: disable=import-outside-toplevel
        meta = creations.read_meta(cwd, concept)
        text = str(meta.get("idea") or meta.get("prompt") or "").strip()
        if text:
            return text.split(". ")[0][:300]
        return creations.title_of(Path(concept).name)
    except Exception:  # noqa: BLE001
        return re.sub(r"[-_]+", " ", Path(concept).stem)


def view_prompt(subject: str, kind: str, view: str, reference: bool = False) -> str:
    """The words for one view. With a reference picture: keep ITS design, only turn it and set the pose."""
    pose = POSE.get(kind, POSE["prop"])
    if reference:
        return ("The same %s as in the reference picture (%s): keep its exact design, shapes, proportions, colours, "
                "materials, markings and art style. Show it %s, %s. %s." % (kind, subject.rstrip(". ")[:300],
                                                                          VIEW_WORDS[view], pose, VIEW_STYLE))
    return "%s, %s, %s. %s." % (subject.rstrip(". "), pose, VIEW_WORDS[view], VIEW_STYLE)


def is_scene(subject: str, concept_size: tuple | None = None) -> str:
    """Why this is a scene, not one subject a turnaround can show ("" when it is fine)."""
    low = " %s " % str(subject or "").lower()
    hit = next((w for w in SCENE_WORDS if (" %s" % w) in low), "")
    if hit:
        return "the concept is a scene (%r) - a turnaround needs ONE character, creature, prop or vehicle" % hit
    if concept_size and concept_size[1] and concept_size[0] / float(concept_size[1]) > 1.6:
        return "the concept is a wide %dx%d picture (a scene) - a turnaround needs one subject" % concept_size
    return ""


def silhouette_box(path) -> tuple:
    """(height share, centre offset) of the subject on its plain background: pixels that differ from the corner
    colour. A turnaround's front / side / back must stand the same height and in the middle (research, 2026-10-26)."""
    from PIL import Image, ImageChops  # pylint: disable=import-outside-toplevel
    with Image.open(path) as im:
        rgb = im.convert("RGB").resize((128, 128))
    bg = Image.new("RGB", rgb.size, rgb.getpixel((2, 2)))
    diff = ImageChops.difference(rgb, bg).convert("L").point(lambda v: 255 if v > 28 else 0)
    box = diff.getbbox()
    if not box:
        return 0.0, 0.0
    x0, y0, x1, y1 = box
    return round((y1 - y0) / 128.0, 3), round(((x0 + x1) / 2.0 - 64) / 128.0, 3)


def colour_match(a_path, b_path) -> float:
    """How alike the subject's colours are (0-1): hue histograms of the saturated pixels (the plain background drops
    out). Cheap and dependency-free beyond Pillow - it catches a red dragon coming back grey."""
    from PIL import Image  # pylint: disable=import-outside-toplevel

    def hist(p):
        with Image.open(p) as im:
            hsv = im.convert("RGB").resize((96, 96)).convert("HSV")
        h = [0.0] * 18
        sat = 0
        for hh, ss, vv in hsv.getdata():
            if ss > 60 and 40 < vv < 250:
                h[hh * 18 // 256] += 1
                sat += 1
        grey = 96 * 96 - sat
        return h + [grey * 0.15], sat
    (ha, sa), (hb, sb) = hist(a_path), hist(b_path)
    dot = sum(x * y for x, y in zip(ha, hb))
    na, nb = sum(x * x for x in ha) ** 0.5, sum(x * x for x in hb) ** 0.5
    return round(dot / (na * nb), 3) if na and nb else 0.0


def stitch(files: list, labels: list, out: Path, height: int = 768) -> Path:
    """All views side by side on one light grey sheet, each labelled under it."""
    from PIL import Image, ImageDraw  # pylint: disable=import-outside-toplevel
    tiles = []
    for f in files:
        im = Image.open(f).convert("RGB")
        w = max(1, round(im.width * height / im.height))
        tiles.append(im.resize((w, height)))
    pad, label_h = 24, 40
    W = sum(t.width for t in tiles) + pad * (len(tiles) + 1)
    sheet = Image.new("RGB", (W, height + pad * 2 + label_h), (214, 214, 214))
    draw = ImageDraw.Draw(sheet)
    x = pad
    for tile, label in zip(tiles, labels):
        sheet.paste(tile, (x, pad))
        draw.text((x + tile.width // 2 - 4 * len(label), pad + height + 10), label.upper(), fill=(40, 40, 40))
        x += tile.width + pad
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def make_turnaround(args: dict, cwd: Path, image_maker: Callable[[dict, Path], dict],
                    clock: Callable[[], float] = time.time) -> dict:
    a = dict(args or {})
    cwd = Path(cwd)
    concept = str(a.get("concept") or a.get("image") or "").strip().replace("\\", "/")
    if concept:
        p = (cwd / concept).resolve()
        if cwd.resolve() not in p.parents or not p.is_file():
            return {"ok": False, "error": "no such concept picture in this folder: %s" % concept}
        concept = p.relative_to(cwd.resolve()).as_posix()
    subject = str(a.get("subject") or a.get("prompt") or "").strip() or (subject_of(cwd, concept) if concept else "")
    if not subject:
        return {"ok": False, "error": "say what the subject is (subject=) or give a concept picture (concept=)"}
    kind = str(a.get("kind") or "character").strip().lower()
    if kind not in KINDS:
        return {"ok": False, "error": "kind must be one of %s" % ", ".join(KINDS)}
    raw = a.get("views") or DEFAULT_VIEWS
    views = [v.strip().lower() for v in (raw.split(",") if isinstance(raw, str) else raw) if str(v).strip()]
    bad = [v for v in views if v not in VIEWS]
    if bad or not views:
        return {"ok": False, "error": "views are %s (not %s)" % (", ".join(VIEWS), ", ".join(bad) or "none")}
    if not a.get("allow_scene"):
        size = None
        if concept:
            try:
                from PIL import Image  # pylint: disable=import-outside-toplevel
                with Image.open(cwd / concept) as im:
                    size = im.size
            except Exception:  # noqa: BLE001
                size = None
        why = is_scene(subject, size)
        if why:
            return {"ok": False, "error": why + " (allow_scene=true to try anyway)"}
    seed = int(a.get("seed") or (int(clock()) % 2**31))
    import out_names  # pylint: disable=import-outside-toplevel
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    name = out_names.name(subject, fallback="subject", at=clock())
    folder = cwd / ROOT / name
    folder.mkdir(parents=True, exist_ok=True)
    tall = kind in ("character", "creature")
    made, labels, backend, model, errors, modes, match, shape = [], [], "", "", [], {}, {}, {}
    use_ref = bool(concept) and str(a.get("reference", "on")).lower() not in ("off", "0", "false", "no")
    for view in views:
        w, h = (768, 1024) if tall and view not in ("top",) else (1024, 1024)
        job = {"prompt": view_prompt(subject, kind, view), "negative": SHEET_NEG, "width": w, "height": h,
               "seed": seed, "folder": "%s/%s" % (ROOT, name)}
        res = {"ok": False}
        if use_ref:     # the concept (+ the front view once made) as the reference: the design stays the same
            refs = [concept] + ([made[labels.index("front")].relative_to(cwd.resolve()).as_posix()]
                                if "front" in labels else [])
            res = image_maker(dict(job, prompt=view_prompt(subject, kind, view, reference=True), reference=refs,
                                   need_edit=True), cwd)
            modes[view] = "reference" if res.get("ok") else "text"
            if not res.get("ok"):
                errors.append("%s: no reference edit (%s) - drawn from text" % (view, str(res.get("error") or "")[:120]))
        if not res.get("ok"):
            res = image_maker(job, cwd)
            modes.setdefault(view, "text")
        if not res.get("ok"):
            errors.append("%s: %s" % (view, str(res.get("error") or "not made")[:200]))
            continue
        src = (cwd / res["files"][0]).resolve()
        dest = folder / ("%s%s" % (view, src.suffix.lower() or ".png"))
        try:
            os.replace(src, dest)
        except OSError as exc:
            errors.append("%s: %s" % (view, exc))
            continue
        made.append(dest.resolve())
        labels.append(view)
        if concept:
            try:
                match[view] = colour_match(cwd / concept, dest)
            except Exception:  # noqa: BLE001
                pass
        try:
            shape[view] = silhouette_box(dest)
        except Exception:  # noqa: BLE001
            pass
        backend, model = res.get("backend", backend), res.get("model", model)
    if not made:
        return {"ok": False, "error": "no view was drawn: " + "; ".join(errors)}
    sheet = stitch(made, labels, cwd / ROOT / (name + "-sheet.png"))
    rel = lambda p: Path(p).resolve().relative_to(cwd.resolve()).as_posix()  # noqa: E731
    info = {"concept": concept, "subject": subject, "kind": kind, "seed": seed, "backend": backend, "model": model,
            "views": {v: rel(f) for v, f in zip(labels, made)}, "sheet": rel(sheet), "made": stamp,
            "missing": [e for e in errors if "drawn from text" not in e], "notes": [e for e in errors if "drawn from text" in e],
            "mode": modes, "colour_match": match, "silhouette": shape}
    (folder / "turnaround.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    front = info["views"].get("front") or next(iter(info["views"].values()))
    return {"ok": True, "files": [info["sheet"]] + list(info["views"].values()), "sheet": info["sheet"],
            "views": info["views"], "concept": concept, "backend": backend, "model": model, "missing": info["missing"],
            "mode": modes, "colour_match": match, "notes": info["notes"], "silhouette": shape,
            "next": "make_3d image=%s (the front view; the other views are beside it for multi-view 3D)" % front}


TOOL = {"name": "make_turnaround",
        "description": "TECHNICAL ARTIST: turn a concept picture into a turnaround sheet for 3D - flat orthographic "
                       "views in a neutral pose (T-pose for characters) on a plain grey background: front, side, "
                       "back and top by default (views= add three-quarter for a perspective one). concept= a picture "
                       "here (its prompt is reused so the design stays the same) and/or subject= a precise description "
                       "(materials, colours, shapes); kind= character | creature | prop | vehicle. Saves "
                       "turnarounds/<name>-sheet.png and each view in turnarounds/<name>/ with turnaround.json (which "
                       "concept it came from). Then make_3d image= the front view.",
        "inputSchema": {"type": "object", "properties": {
            "concept": {"type": "string"}, "subject": {"type": "string"},
            "kind": {"type": "string", "enum": list(KINDS)}, "views": {"type": "string"},
            "seed": {"type": "integer"}}}}
