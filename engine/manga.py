"""Manga Studio: from one idea to finished, lettered manga pages - characters that stay the same on every page (owner
2026-10-28: "focus oniichan-ai and later nano-banana-pro, add it to loki ... in the forge tab ... i want my agents able
to do that stuff ... as detailed as that if not more").

What it does (the feature set of Oniichan - oniichan.app - and the method of FURU's AI 4-koma system
github.com/FURUYAN1234/nano-banana-pro, re-built for LOKI; no code is copied from either - Oniichan publishes none, and
FURU's terms keep its code out of an AGPL program, so only the published ideas and methods are used):

    project     a premise, a format (4-koma strip, 5-8 panel page, webtoon), colour or monochrome, a language, an
                ending type, how many pages
    outline     a logline and a page-by-page breakdown (each page one beat of the story, the last page its ending)
    cast        characters with a LOCKED look (face, hair, eyes, build, outfit, colours, props) - carried into every
                panel prompt, so the same person looks the same everywhere (wardrobe continuity); a reference sheet
                per character, several variants to pick from, a library reused across projects
    script      per page, per panel: shot, camera angle, action, emotion, setting, who is in it, a panel style
                (normal / pop / watercolor / gekiga / sketch / chibi), and dialogue kept APART from the drawing:
                speaker, kind (speech, thought, shout, whisper, narration, sfx), placement
    layout      8 page layouts (full, vertical split, horizontal split, top focus, bottom focus, three rows, four
                grid, focus + detail), the 4-koma strip, 5-8 panel grids and the webtoon column; the panel count of
                the script is never changed to fit a layout - the layout is chosen to fit the script
    draw        each panel drawn on its own, at its panel's shape, with no text in the picture; LOKI letters it
    letter      real typeset lettering: speech balloons with tails toward the speaker, thought clouds, shout bursts,
                narration boxes, sound effects - so every word is spelled exactly as written (image models misspell)
    edit        redraw one panel with a note, change the dialogue (re-lettered without redrawing), move a balloon
    review      checks the page against the script: every panel drawn, every line lettered, the cast present
    export      PNG pages, a PDF, a CBZ for comic readers; a reading view in the window

Agents use it through the `manga` tool (engine/make_mcp.py); the window is Forge > Manga (app/ui/forge_manga.js).
Every picture an agent asks for waits for the owner's OK in Home > For you - one card per page or character sheet.

Storage: <workspace>/manga/<slug>/project.json, panels/, pages/, characters/, exports/.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable

FONTS = Path(__file__).resolve().parent / "data" / "fonts"
FORMATS = ("4koma", "page", "webtoon")
STYLES = {   # per-panel drawing recipes (what each style means for faces, lines, colour) - never identity or acting
    "normal": "clean manga linework, confident G-pen contours, balanced detail, readable shapes",
    "pop": "pop-art manga: extra-bold black contours, flat vivid opaque colours, large clearly separated halftone dots, "
           "graphic shapes on faces, hair and clothes",
    "watercolor": "watercolour manga: transparent pigment washes layered over fine ink lines, soft paper texture, "
                  "colour blooms at edges, light airy values on skin and hair",
    "gekiga": "gekiga style: dense multidirectional fine pen hatching that carves deep eye sockets, the nose and the "
              "cheek and jaw planes, serious adult proportions, shadows built from line density, sparse solid black",
    "sketch": "loose pencil sketch manga: rough construction lines left visible, light graphite shading, unfinished edges",
    "chibi": "chibi gag style: 2-3 heads tall, oversized head and eyes, tiny limbs, simplified hands, exaggerated "
             "comic expressions, playful motion lines",
}
COLOUR = {"color": "full colour, cel-shaded colour with soft gradients, consistent palette per character",
          "mono": "black and white manga ink, screentone halftone shading, no colour, pure black and white"}
SHOTS = ("establishing", "wide", "full", "medium", "medium close-up", "close-up", "extreme close-up", "over-the-shoulder",
         "insert")
ANGLES = ("eye level", "low angle", "high angle", "bird's-eye", "worm's-eye", "dutch angle", "profile", "from behind")
KINDS = ("speech", "thought", "shout", "whisper", "narration", "sfx")
ENDINGS = {
    "serious": ("resolution", "bittersweet", "twist", "open question", "sacrifice", "reunion", "quiet aftermath", "cliffhanger"),
    "gag": ("punchline reversal", "deadpan", "escalation", "callback", "fourth-wall", "misunderstanding", "slapstick",
            "role swap", "anticlimax", "absurd logic", "tables turned", "running gag"),
}
PAGE_W, PAGE_H = 1240, 1754           # A4 portrait at 150 dpi
MARGIN, GUTTER = 48, 22
STRIP_W = 760                          # the 4-koma strip column
LAYOUTS = {   # name -> panel rectangles in page units (0..1), reading order (right to left is a setting, not a layout)
    "full": [(0, 0, 1, 1)],
    "vsplit": [(0, 0, .5, 1), (.5, 0, .5, 1)],
    "hsplit": [(0, 0, 1, .5), (0, .5, 1, .5)],
    "top-focus": [(0, 0, 1, .6), (0, .6, .5, .4), (.5, .6, .5, .4)],
    "bottom-focus": [(0, 0, .5, .4), (.5, 0, .5, .4), (0, .4, 1, .6)],
    "three-row": [(0, 0, 1, 1 / 3), (0, 1 / 3, 1, 1 / 3), (0, 2 / 3, 1, 1 / 3)],
    "four-grid": [(0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5), (.5, .5, .5, .5)],
    "focus-detail": [(0, 0, .65, 1), (.65, 0, .35, .5), (.65, .5, .35, .5)],
}


# ----------------------------------------------------------------------------- project files
def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (s[:40] or "manga").strip("-")


def root(ws: Path | str) -> Path:
    d = Path(ws) / "manga"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdir(ws: Path | str, pid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,60}", str(pid or "")):
        raise ValueError("unknown manga project")
    return root(ws) / pid


def save(ws: Path | str, proj: dict) -> dict:
    proj["updated"] = time.time()
    d = pdir(ws, proj["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ("project.json.tmp%d" % os.getpid())
    tmp.write_text(json.dumps(proj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / "project.json")
    return proj


def load(ws: Path | str, pid: str) -> dict:
    return json.loads((pdir(ws, pid) / "project.json").read_text(encoding="utf-8"))


def projects(ws: Path | str) -> list:
    out = []
    for p in sorted(root(ws).glob("*/project.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": d["id"], "title": d.get("title"), "format": d.get("format"), "pages": len(d.get("pages") or []),
                    "drawn": sum(1 for pg in d.get("pages") or [] if pg.get("file")), "cover": _cover(d),
                    "updated": d.get("updated")})
    return out


def _cover(proj: dict) -> str:
    for pg in proj.get("pages") or []:
        if pg.get("file"):
            return pg["file"]
    for c in proj.get("characters") or []:
        if c.get("sheet"):
            return c["sheet"]
    return ""


def create(ws: Path | str, premise: str, title: str = "", fmt: str = "page", colour: str = "mono",
           language: str = "English", pages: int = 4, tone: str = "auto", ending: str = "auto",
           style: str = "normal", reading: str = "ltr") -> dict:
    premise = " ".join(str(premise or "").split())
    if not premise:
        raise ValueError("a premise is needed - what is the story about?")
    fmt = fmt if fmt in FORMATS else "page"
    pid = _slug(title or premise)
    while (root(ws) / pid).exists():
        pid = "%s-%s" % (_slug(title or premise)[:32], uuid.uuid4().hex[:4])
    proj = {"id": pid, "title": title or _title_from(premise), "premise": premise, "format": fmt,
            "colour": colour if colour in COLOUR else "mono", "language": language or "English",
            "pages_target": max(1, min(int(pages or 4), 40 if fmt != "4koma" else 12)), "tone": tone, "ending": ending,
            "style": style if style in STYLES else "normal", "reading": reading if reading in ("ltr", "rtl") else "ltr",
            "outline": {}, "characters": [], "pages": [], "history": [], "created": time.time()}
    return save(ws, proj)


def _title_from(premise: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", premise)[:5]
    return " ".join(w.capitalize() for w in words) or "Untitled manga"


def _log(proj: dict, what: str) -> None:
    proj.setdefault("history", []).append({"t": time.time(), "what": what[:300]})
    proj["history"] = proj["history"][-200:]


def _warn(proj: dict, what: str, exc: Exception) -> None:
    """The model could not write `what`: a placeholder stands in, and the review says so (not a quiet success)."""
    proj.setdefault("warnings", {})[what] = ("the model could not write it, a placeholder stands in: %s" % exc)[:400]
    _log(proj, "%s: placeholder (%s)" % (what, exc))


def _wrote(proj: dict, what: str) -> None:
    (proj.get("warnings") or {}).pop(what, None)


# ----------------------------------------------------------------------------- writing: outline, cast, script
def _json(raw: str):
    """The JSON object in a model's answer. Small models drop a colon or a comma in long answers (the PC's model on
    page 2's script, 2026-10-28: "Expecting ':' delimiter ... char 1550"): LOKI's own repair (structured.parse), then
    json_repair (github mangiucugna/json_repair, MIT) before the answer counts as unusable."""
    raw = re.sub(r"<think>.*?</think>", "", str(raw or ""), flags=re.S)
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("no JSON in the answer")
    try:
        return json.loads(raw[s:e + 1])
    except ValueError as first:
        try:
            import structured  # pylint: disable=import-outside-toplevel
            fixed = structured.parse(raw[s:e + 1])
        except Exception:  # noqa: BLE001
            fixed = None
        if not isinstance(fixed, dict):
            try:
                import json_repair  # pylint: disable=import-outside-toplevel
                fixed = json_repair.loads(raw[s:e + 1])
            except Exception:  # noqa: BLE001 - not installed yet, or past repair
                fixed = None
        if isinstance(fixed, dict) and fixed:
            return fixed
        raise first


OUTLINE_PROMPT = """You are a manga story editor. Plan this manga.
Premise: %(premise)s
Format: %(format_note)s
Pages: %(pages)d. Tone: %(tone)s. Ending: %(ending)s. Language of the dialogue: %(language)s.

Story method (follow it): normalise the facts of the premise first; decide the tone ONCE; build the spine
(%(spine)s); give every page exactly one story job (setup, development, turn, payoff ...) and the last page the ending;
pick visual evidence (props, places, gestures) that SHOW the story; give each main character a want and a contrast with
the others. No filler pages.
Answer with JSON only:
{"title": "...", "logline": "one sentence", "tone": "serious|gag|...", "ending": "<ending type>",
 "pages": [{"n": 1, "beat": "setup|development|turn|payoff|...", "summary": "what happens on this page, 1-3 sentences",
            "panels": <panel count this page needs>}]}"""

CAST_PROMPT = """List the cast of this manga and LOCK each character's look so every artist draws them the same.
Title: %(title)s. Premise: %(premise)s
Outline: %(outline)s
Answer with JSON only:
{"characters": [{"name": "...", "species": "what they are, plainly (a human teenage boy, a small white fox spirit in
  animal form, a vending machine with a face ...)", "role": "protagonist|deuteragonist|rival|mentor|side|extra", "age": "...",
  "look": {"face": "shape, eye shape and colour, distinguishing marks", "hair": "style, length, colour",
           "build": "height, body type, posture", "outfit": "every garment and its colour, shoes, accessories",
           "colours": ["3-5 colours that belong to this character"], "props": "what they carry"},
  "personality": "3-6 words", "voice": "how they talk"}]}
Keep it to the characters the outline needs (1-6). A character who is not a human must say so in "species" - an
artist who reads only the look draws a person."""

SCRIPT_PROMPT = """Write the panel script for page %(n)d of the manga "%(title)s".
Premise: %(premise)s
This page's job: %(beat)s - %(summary)s
Previous page: %(prev)s
Cast (locked looks - refer to them by name): %(cast)s
Format: %(format_note)s
Panel count: %(count_note)s
Dialogue language: %(language)s. Overall style: %(style)s.

Rules: every panel moves the story (an action, a reaction, a reveal or a needed pause - a silent panel is fine when it
carries a feeling); vary the shots (establishing / wide / medium / close-up / extreme close-up / over-the-shoulder /
insert) and the angles (eye level / low / high / bird's-eye / dutch / profile / from behind); the most important panel
gets the biggest moment; dialogue is short (max ~18 words per balloon, max 3 balloons per panel); spoken names stay in
the dialogue; the art description NEVER contains the dialogue words; a panel's style is one of normal, pop,
watercolor, gekiga, sketch, chibi (keep the overall style unless a moment needs another).
Answer with JSON only:
{"panels": [{"n": 1, "shot": "...", "angle": "...", "setting": "where, time of day, light",
  "characters": ["names in the panel"], "action": "what we SEE (pose, gesture, expression, props) - no dialogue words",
  "emotion": "the feeling of the moment", "style": "normal",
  "dialogue": [{"speaker": "name or NARRATOR or SFX", "kind": "speech|thought|shout|whisper|narration|sfx",
                "text": "exact words to letter", "place": "top-left|top-right|top|bottom-left|bottom-right|bottom|middle"}]}]}"""


def _format_note(proj: dict) -> str:
    return {"4koma": "4-koma: a vertical strip of exactly four panels - setup (ki), development (sho), turn (ten), "
                     "conclusion (ketsu); the turn panel changes the situation, the last panel lands the ending",
            "page": "a manga page of 5 to 8 panels - plan intermediate actions, the other person's reaction, scene "
                    "changes and needed pauses; use the smallest count that keeps every needed beat",
            "webtoon": "a vertical webtoon scroll - 4 to 7 tall panels, generous space between beats, one big reveal "
                       "panel"}.get(proj.get("format"), "a manga page")


def _spine(proj: dict) -> str:
    return ("ki-sho-ten-ketsu: setup, development, the turn, the conclusion" if proj.get("format") == "4koma"
            else "setup, rising development, the turn, the climax, the ending")


def outline(ws, pid: str, ask: Callable[[str], str] | None = None, data: dict | None = None) -> dict:
    """The page-by-page plan: from `data` (an agent wrote it) or `ask` (LOKI writes it), else a plain spine."""
    proj = load(ws, pid)
    o = None
    if data:
        o = data
    elif ask is not None:
        try:
            o = _json(ask(OUTLINE_PROMPT % {"premise": proj["premise"], "format_note": _format_note(proj),
                                            "pages": proj["pages_target"], "tone": proj["tone"],
                                            "ending": proj["ending"], "language": proj["language"],
                                            "spine": _spine(proj)}))
        except Exception as exc:  # noqa: BLE001 - the plain spine below, and the window is told
            o = None
            _warn(proj, "outline", exc)
    if not o or not o.get("pages"):
        beats = (["setup", "development", "turn", "conclusion"] if proj["format"] == "4koma"
                 else ["setup", "development", "turn", "climax", "ending"])
        n = proj["pages_target"]
        o = {"logline": proj["premise"], "pages": [{"n": i + 1, "beat": beats[min(len(beats) - 1, int(i * len(beats) / max(1, n)))],
                                                     "summary": "%s (page %d of %d)" % (proj["premise"], i + 1, n),
                                                     "panels": 4 if proj["format"] == "4koma" else 6} for i in range(n)]}
    pages = []
    for i, pg in enumerate(o.get("pages") or []):
        pages.append({"n": i + 1, "beat": str(pg.get("beat") or "")[:40], "summary": str(pg.get("summary") or "")[:800],
                      "panels_target": _panel_count(proj, pg.get("panels"))})
    proj["outline"] = {"logline": str(o.get("logline") or proj["premise"])[:400], "tone": str(o.get("tone") or proj["tone"]),
                       "ending": str(o.get("ending") or proj["ending"]), "pages": pages}
    if o.get("title") and not proj.get("title_fixed"):
        proj["title"] = str(o["title"])[:80]
    old = {p["n"]: p for p in proj.get("pages") or []}
    proj["pages"] = [dict(old.get(p["n"], {}), n=p["n"], beat=p["beat"], summary=p["summary"],
                          panels_target=p["panels_target"]) for p in pages]
    if o is data or (o and "(page 1 of" not in str((o.get("pages") or [{}])[0].get("summary", ""))):
        _wrote(proj, "outline")
    _log(proj, "outline: %d pages" % len(pages))
    return save(ws, proj)


def _panel_count(proj: dict, n) -> int:
    if proj.get("format") == "4koma":
        return 4
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 6
    return max(4, min(n, 7)) if proj.get("format") == "webtoon" else max(5, min(n, 8))


def cast(ws, pid: str, ask: Callable[[str], str] | None = None, data: dict | None = None, library: bool = True) -> dict:
    """The characters with their locked looks (from `data`, `ask`, or the library)."""
    proj = load(ws, pid)
    c = data or None
    if c is None and ask is not None:
        try:
            c = _json(ask(CAST_PROMPT % {"title": proj["title"], "premise": proj["premise"],
                                         "outline": json.dumps(proj.get("outline", {}).get("pages", []))[:3000]}))
        except Exception as exc:  # noqa: BLE001
            c = None
            _warn(proj, "characters", exc)
        else:
            _wrote(proj, "characters")
    chars = []
    for ch in (c or {}).get("characters") or []:
        name = " ".join(str(ch.get("name") or "").split())[:40]
        if not name:
            continue
        lib = _library_get(ws, name) if library else None
        look = ch.get("look") if isinstance(ch.get("look"), dict) else {"description": str(ch.get("look") or "")}
        entry = {"id": _slug(name), "name": name, "species": " ".join(str(ch.get("species") or "").split())[:80],
                 "role": str(ch.get("role") or "")[:30], "age": str(ch.get("age") or "")[:20],
                 "look": {k: (v if isinstance(v, list) else str(v)[:300]) for k, v in look.items()},
                 "personality": str(ch.get("personality") or "")[:120], "voice": str(ch.get("voice") or "")[:120],
                 "sheet": "", "variants": []}
        if lib:                                   # the same character from an earlier project: same look, same sheet
            entry.update({k: lib[k] for k in ("look", "sheet", "variants") if lib.get(k)})
            entry["from_library"] = True
        chars.append(entry)
    keep = {x["id"]: x for x in proj.get("characters") or []}
    for e in chars:                               # what the owner already picked stays
        if e["id"] in keep and keep[e["id"]].get("sheet"):
            e["sheet"], e["variants"] = keep[e["id"]]["sheet"], keep[e["id"]].get("variants", [])
    proj["characters"] = chars
    _log(proj, "cast: %s" % ", ".join(x["name"] for x in chars))
    return save(ws, proj)


def look_text(ch: dict) -> str:
    """One character's locked look, as a drawing instruction (the same words in every panel)."""
    lk = ch.get("look") or {}
    # what the character IS comes first (2026-10-28: "Kitsune ... tiny, cherubic face, shrine uniform" with no word
    # saying fox was drawn as a little girl and NVIDIA's filter refused the sheet)
    bits = ["%s (%s)" % (ch["name"], ch["species"]) if ch.get("species") else ch["name"]]
    for k in ("age",):
        if ch.get(k):
            bits.append(str(ch[k]))
    for k in ("face", "hair", "build", "outfit", "props", "description"):
        if lk.get(k):
            bits.append("%s: %s" % (k, lk[k]))
    if lk.get("colours"):
        bits.append("colours: " + ", ".join(lk["colours"]) if isinstance(lk["colours"], list) else str(lk["colours"]))
    return "; ".join(bits)


def draw_text(ch: dict) -> str:
    """What a character LOOKS like, for the picture model: what they are, then face, hair, build, outfit, props,
    colours - no name or age label (2026-10-28: FLUX painted "OTeu-Vending Mahne" and "5 years" onto the sheet)."""
    lk = ch.get("look") or {}
    bits = [ch["species"]] if ch.get("species") else []
    for k in ("face", "hair", "build", "outfit", "props", "description"):
        if lk.get(k):
            bits.append(str(lk[k]))
    if lk.get("colours") and isinstance(lk["colours"], list):
        bits.append("colours " + ", ".join(lk["colours"]))
    return "; ".join(bits)


PROMPT_BUDGET = 780   # the strictest picture model here takes 800 characters (NVIDIA flux.2-klein)


def budget(head: str, middle: list, tail: str, limit: int = PROMPT_BUDGET) -> str:
    """head + as much of `middle` as fits + tail, never over `limit`: the instructions that make the picture right
    (layout, style, black and white, no text) are the tail and are never the part that is cut."""
    room = limit - len(head) - len(tail) - 2
    kept = []
    for part in middle:
        part = " ".join(str(part or "").split())
        if not part:
            continue
        if len(part) + 1 > room:
            cut = part[:max(0, room - 1)].rsplit(" ", 1)[0].rstrip(" ,.;")
            if len(cut) > 20:
                kept.append(cut)
            break
        kept.append(part)
        room -= len(part) + 1
    return " ".join(x for x in [head] + kept + [tail] if x)[:limit]


def script(ws, pid: str, n: int, ask: Callable[[str], str] | None = None, data: dict | None = None) -> dict:
    """One page's panels (from `data`, `ask`, or a plain fallback), checked and stored."""
    proj = load(ws, pid)
    page = _page(proj, n)
    want = page.get("panels_target") or _panel_count(proj, None)
    raw = data
    if raw is None and ask is not None:
        prev = _page(proj, n - 1, create=False) if n > 1 else None
        count_note = ("exactly 4" if proj["format"] == "4koma" else "%d (the outline planned it; use 5-8)" % want
                      if proj["format"] == "page" else "%d (4-7)" % want)
        try:
            raw = _json(ask(SCRIPT_PROMPT % {
                "n": n, "title": proj["title"], "premise": proj["premise"], "beat": page.get("beat", ""),
                "summary": page.get("summary", ""), "prev": (prev or {}).get("summary", "this is the first page"),
                "cast": "; ".join(look_text(c) for c in proj.get("characters") or [])[:3000] or "invent at most 2",
                "format_note": _format_note(proj), "count_note": count_note, "language": proj["language"],
                "style": proj["style"]}))
        except Exception as exc:  # noqa: BLE001
            raw = None
            _warn(proj, "script page %d" % n, exc)
        else:
            _wrote(proj, "script page %d" % n)
    panels = normalize_panels(proj, (raw or {}).get("panels") or [], want)
    if not panels:
        panels = [{"n": i + 1, "shot": SHOTS[min(i, len(SHOTS) - 1)], "angle": "eye level", "setting": "",
                   "characters": [c["name"] for c in (proj.get("characters") or [])[:2]],
                   "action": page.get("summary", proj["premise"]), "emotion": "", "style": proj["style"],
                   "dialogue": []} for i in range(want)]
    old = {p["n"]: p for p in page.get("panels") or []}
    for p in panels:                           # a panel already drawn keeps its picture unless the action changed
        o = old.get(p["n"])
        if o and o.get("image") and o.get("action") == p["action"] and o.get("style") == p["style"]:
            p["image"], p["prompt"] = o["image"], o.get("prompt", "")
    page["panels"] = panels
    page["layout"] = choose_layout(proj, panels)
    page.pop("file", None)
    _log(proj, "script: page %d, %d panels" % (n, len(panels)))
    return save(ws, proj)


def normalize_panels(proj: dict, panels: list, want: int) -> list:
    out = []
    names = {c["name"].lower(): c["name"] for c in proj.get("characters") or []}
    for i, p in enumerate(panels or []):
        if not isinstance(p, dict):
            continue
        dl = []
        for d in (p.get("dialogue") or [])[:4]:
            if not isinstance(d, dict) or not str(d.get("text") or "").strip():
                continue
            kind = str(d.get("kind") or "speech").lower()
            dl.append({"speaker": str(d.get("speaker") or "")[:40], "kind": kind if kind in KINDS else "speech",
                       "text": " ".join(str(d["text"]).split())[:240],
                       "place": str(d.get("place") or "")[:20].lower()})
        style = str(p.get("style") or proj.get("style") or "normal").lower()
        out.append({"n": len(out) + 1, "shot": str(p.get("shot") or "medium")[:40], "angle": str(p.get("angle") or "eye level")[:40],
                    "setting": str(p.get("setting") or "")[:300],
                    "characters": [names.get(str(x).lower(), str(x))[:40] for x in (p.get("characters") or [])][:6],
                    "action": " ".join(str(p.get("action") or "").split())[:600],
                    "emotion": str(p.get("emotion") or "")[:120], "style": style if style in STYLES else "normal",
                    "dialogue": dl})
    if proj.get("format") == "4koma":
        out = out[:4]
        while out and len(out) < 4:            # a 4-koma has four panels - a missing beat is a quiet panel
            out.append(dict(out[-1], n=len(out) + 1, dialogue=[], action=out[-1]["action"] + " (a quiet beat)"))
    return out[:8]


def _page(proj: dict, n: int, create: bool = True) -> dict | None:
    for pg in proj.get("pages") or []:
        if pg.get("n") == n:
            return pg
    if not create:
        return None
    pg = {"n": n, "beat": "", "summary": "", "panels_target": _panel_count(proj, None)}
    proj.setdefault("pages", []).append(pg)
    proj["pages"].sort(key=lambda x: x["n"])
    return pg


# ----------------------------------------------------------------------------- layout
def grid(count: int) -> list:
    """A 5-8 panel page as rows (2-4 rows; the biggest moments get a full row)."""
    rows = {5: [2, 1, 2], 6: [2, 2, 2], 7: [2, 1, 2, 2], 8: [2, 2, 2, 2]}.get(count) or [2] * math.ceil(count / 2)
    rects, y, h = [], 0.0, 1.0 / len(rows)
    for r in rows:
        for c in range(r):
            rects.append((c / r, y, 1 / r, h))
        y += h
    return rects[:count]


def choose_layout(proj: dict, panels: list) -> str:
    """The layout that fits the script (never the other way round)."""
    n = len(panels)
    if proj.get("format") == "4koma":
        return "strip"
    if proj.get("format") == "webtoon":
        return "column"
    if n == 1:
        return "full"
    if n == 2:
        return "hsplit"
    if n == 3:
        big = max(range(3), key=lambda i: _weight(panels[i]))
        return "top-focus" if big == 0 else "bottom-focus" if big == 2 else "three-row"
    if n == 4:
        return "four-grid"
    return "grid%d" % n


def _weight(p: dict) -> int:
    shot = p.get("shot", "")
    return (3 if shot in ("establishing", "wide") else 2 if shot in ("full", "medium") else 1) + len(p.get("dialogue") or [])


def rects(proj: dict, page: dict) -> tuple:
    """(page width, page height, [panel boxes in pixels]) for the page's layout."""
    panels = page.get("panels") or []
    lay = page.get("layout") or choose_layout(proj, panels)
    n = len(panels)
    if lay == "strip":
        w, ph = STRIP_W, 300
        h = MARGIN * 2 + n * ph + (n - 1) * GUTTER
        return w, h, [(MARGIN, MARGIN + i * (ph + GUTTER), w - 2 * MARGIN, ph) for i in range(n)]
    if lay == "column":
        w, ph = 800, 900
        h = MARGIN * 2 + n * ph + (n - 1) * 140
        return w, h, [(MARGIN, MARGIN + i * (ph + 140), w - 2 * MARGIN, ph) for i in range(n)]
    units = LAYOUTS.get(lay) or grid(n)
    units = units[:n] if len(units) >= n else grid(n)
    iw, ih = PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN
    boxes = []
    for (x, y, bw, bh) in units:
        x0 = MARGIN + x * iw + (GUTTER / 2 if x > 0 else 0)
        y0 = MARGIN + y * ih + (GUTTER / 2 if y > 0 else 0)
        x1 = MARGIN + (x + bw) * iw - (GUTTER / 2 if x + bw < 0.999 else 0)
        y1 = MARGIN + (y + bh) * ih - (GUTTER / 2 if y + bh < 0.999 else 0)
        boxes.append((int(x0), int(y0), int(x1 - x0), int(y1 - y0)))
    if proj.get("reading") == "rtl":           # right-to-left manga: mirror the columns, keep the reading order
        boxes = [(PAGE_W - x - w, y, w, h) for (x, y, w, h) in boxes]
    return PAGE_W, PAGE_H, boxes


# ----------------------------------------------------------------------------- the panel prompt
def panel_prompt(proj: dict, page: dict, panel: dict) -> dict:
    """What one panel's picture is asked for: the drawing only - the words are lettered by LOKI afterwards."""
    by = {c["name"].lower(): c for c in proj.get("characters") or []}
    cast_bits = ["%s: %s" % (n, draw_text(by[n.lower()])) for n in panel.get("characters") or [] if n.lower() in by]
    style = STYLES.get(panel.get("style") or proj.get("style") or "normal", STYLES["normal"])
    parts = ["Manga panel, %s shot, %s." % (panel.get("shot") or "medium", panel.get("angle") or "eye level"),
             panel.get("action") or "",
             ("Setting: " + panel["setting"]) if panel.get("setting") else "",
             ("Mood: " + panel["emotion"]) if panel.get("emotion") else "",
             ("Characters (draw exactly these, same face, hair and outfit as described): " + " | ".join(cast_bits))
             if cast_bits else "",
             "Style: " + style + ".", COLOUR.get(proj.get("colour") or "mono", COLOUR["mono"]) + ".",
             "Leave clear empty space near the %s for speech balloons." % _space_hint(panel) if panel.get("dialogue") else "",
             "No text, no letters, no speech bubbles, no captions, no watermark, no panel borders."]
    style_bits = [x for x in parts if x.startswith(("Style: ", "Leave clear", "No text"))] + \
        [x for x in parts if x in COLOUR.values() or x.rstrip(".") in COLOUR.values()]
    body = [x for x in parts[1:] if x and x not in style_bits]
    prompt = budget(parts[0], body, " ".join(x for x in style_bits if x))
    refs = [by[n.lower()]["sheet"] for n in panel.get("characters") or [] if n.lower() in by and by[n.lower()].get("sheet")]
    return {"prompt": prompt, "reference": refs[:3],
            "negative": "text, letters, words, speech bubble, caption, watermark, signature, extra fingers, deformed hands, "
                        "duplicate character, frame border"}


def _space_hint(panel: dict) -> str:
    places = [d.get("place") or "" for d in panel.get("dialogue") or []]
    return places[0].replace("-", " ") if places and places[0] else "top"


def _size_for(box: tuple) -> tuple:
    """A picture size near the panel's shape, in multiples of 64, ~1 megapixel."""
    _, _, w, h = box
    ar = max(0.3, min(3.5, w / float(max(1, h))))
    area = 1024 * 1024
    W = int(round(math.sqrt(area * ar) / 64)) * 64
    H = int(round(math.sqrt(area / ar) / 64)) * 64
    return max(512, min(W, 1536)), max(512, min(H, 1536))


# ----------------------------------------------------------------------------- drawing (the makers do the pictures)
def character_sheet_args(proj: dict, ch: dict) -> dict:
    prompt = budget("Manga character model sheet:", [draw_text(ch) + "."],
                    "Front, side and back full-body views side by side, three head close-ups (neutral, happy, angry), "
                    "same character in every view, plain white background. %s. %s. No text, no labels, no letters."
                    % (STYLES.get(proj.get("style") or "normal"), COLOUR.get(proj.get("colour") or "mono", COLOUR["mono"])))
    return {"prompt": prompt, "width": 1536, "height": 1024,
            "negative": "text, letters, labels, watermark, different characters, inconsistent outfit",
            "folder": "manga/%s/characters" % proj["id"], "style": ""}


def draw_character(ws, pid: str, char_id: str, make: Callable[[dict], dict], variants: int = 1) -> dict:
    """The reference sheet (and variants to pick from). `make(args) -> {"ok", "files"}` (make_mcp.make_image)."""
    proj = load(ws, pid)
    ch = next((c for c in proj.get("characters") or [] if c["id"] == char_id), None)
    if ch is None:
        return {"ok": False, "error": "no character %r" % char_id}
    res = make(dict(character_sheet_args(proj, ch), count=max(1, min(int(variants or 1), 4))))
    if not res.get("ok"):
        return res
    files = [str(f).replace("\\", "/") for f in res.get("files") or []]
    ch["variants"] = (ch.get("variants") or []) + files
    if not ch.get("sheet") and files:
        ch["sheet"] = files[0]
    _log(proj, "character sheet: %s (%d)" % (ch["name"], len(files)))
    save(ws, proj)
    _library_put(ws, ch)
    return {"ok": True, "files": files, "character": ch}


def pick_variant(ws, pid: str, char_id: str, file: str) -> dict:
    proj = load(ws, pid)
    ch = next((c for c in proj.get("characters") or [] if c["id"] == char_id), None)
    if ch is None or file not in (ch.get("variants") or []):
        raise ValueError("that variant is not one of this character's")
    ch["sheet"] = file
    save(ws, proj)
    _library_put(ws, ch)
    return ch


def draw_page(ws, pid: str, n: int, make: Callable[[dict], dict], only: list | None = None, note: str = "") -> dict:
    """Draw the page's panels (all, or `only` these numbers) and letter the page. Returns the page."""
    proj = load(ws, pid)
    page = _page(proj, n, create=False)
    if not page or not page.get("panels"):
        return {"ok": False, "error": "page %d has no script yet - write the script first" % n}
    W, H, boxes = rects(proj, page)
    made, errors = [], []
    for panel, box in zip(page["panels"], boxes):
        if only and panel["n"] not in only:
            continue
        if not only and panel.get("image") and (Path(ws) / panel["image"]).is_file():
            continue                            # already drawn (a redraw asks for it by number)
        args = panel_prompt(proj, page, panel)
        if note:
            args["prompt"] = ("%s Owner's note: %s" % (args["prompt"], note))[:1800]
        w, h = _size_for(box)
        args.update(width=w, height=h, folder="manga/%s/panels" % proj["id"], reference_optional=True)
        res = make(args)
        if not res.get("ok") or not res.get("files"):
            errors.append("panel %d: %s" % (panel["n"], res.get("error") or "nothing was drawn"))
            if res.get("waiting_for_owner"):
                return {"ok": False, "waiting_for_owner": True, "error": res.get("error"), "review": res.get("review")}
            continue
        panel["image"] = str(res["files"][0]).replace("\\", "/")
        panel["prompt"] = args["prompt"]
        made.append(panel["image"])
        # the page grows panel by panel in the window (owner 2026-10-28: "make sure they show preview" - before this the
        # page stayed empty until every panel of a several-minute draw was done)
        save(ws, proj)
        try:
            compose(ws, pid, n)
            done = _page(load(ws, pid), n, create=False) or {}
            page["file"] = done.get("file") or page.get("file")
        except Exception:  # noqa: BLE001 - the final compose below reports it
            pass
    save(ws, proj)
    out = compose(ws, pid, n)
    out.update(drawn=made, errors=errors, ok=bool(out.get("ok")) and not (errors and not made))
    return out


# ----------------------------------------------------------------------------- lettering and composing
def _font(size: int, kind: str = "speech"):
    from PIL import ImageFont  # pylint: disable=import-outside-toplevel
    name = {"sfx": "Bangers-Regular.ttf", "shout": "Bangers-Regular.ttf"}.get(kind, "ComicNeue-Bold.ttf")
    for p in (FONTS / name, FONTS / "ComicNeue-Bold.ttf"):
        try:
            return ImageFont.truetype(str(p), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _anchor(box: tuple, place: str, bw: int, bh: int, i: int) -> tuple:
    x, y, w, h = box
    pad = 14
    place = place or ("top-left" if i % 2 == 0 else "top-right")
    cx = x + pad if "left" in place else x + w - bw - pad if "right" in place else x + (w - bw) // 2
    cy = (y + h - bh - pad) if "bottom" in place else (y + (h - bh) // 2) if place == "middle" else y + pad
    cy += 0 if "bottom" in place else i * 0  # stacking is handled by the caller
    return int(max(x + 4, min(cx, x + w - bw - 4))), int(max(y + 4, min(cy, y + h - bh - 4)))


def letter_panel(img, draw, box: tuple, dialogue: list, scale: float = 1.0) -> list:
    """Draw every balloon of one panel into `img`; returns their boxes (for the review)."""
    out = []
    x, y, w, h = box
    taken: list = []
    for i, d in enumerate(dialogue):
        kind = d.get("kind") or "speech"
        size = int((44 if kind in ("sfx",) else 30 if kind == "shout" else 24) * scale)
        font = _font(size, kind)
        text = d["text"].upper() if kind in ("shout", "sfx") else d["text"]
        max_tw = int(w * (0.55 if kind != "narration" else 0.8))
        lines = _wrap(draw, text, font, max_tw)
        lh = int(size * 1.18)
        tw = int(max(draw.textlength(l, font=font) for l in lines)) if lines else 0
        th = lh * len(lines)
        if kind in ("narration", "sfx"):
            padx, pady = int(size * 0.5), int(size * 0.4)
        else:                                  # text in an oval: the oval is ~1.42x the text box (it must not touch)
            grow = 1.8 if kind == "shout" else 1.42
            padx = int((tw * grow - tw) / 2 + size * 0.5)
            pady = int((th * grow - th) / 2 + size * 0.45)
        bw, bh = tw + 2 * padx, th + 2 * pady
        bx, by = _anchor(box, d.get("place") or "", bw, bh, i)
        for (tx, ty, tw2, th2) in taken:      # never on top of another balloon: move down
            if bx < tx + tw2 and tx < bx + bw and by < ty + th2 and ty < by + bh:
                by = ty + th2 + 8
        by = min(by, y + h - bh - 4)
        rect = (bx, by, bx + bw, by + bh)
        if kind == "narration":
            draw.rectangle(rect, fill="#fffbe8", outline="black", width=max(2, int(3 * scale)))
        elif kind == "sfx":
            pass
        elif kind == "thought":
            draw.ellipse(rect, fill="white", outline="black", width=max(2, int(3 * scale)))
            for k in range(3):                 # the little thought bubbles
                r = int((10 - 3 * k) * scale)
                up = by + bh + 50 * scale > y + h      # no room below: the bubbles go up toward the thinker
                off = int((8 + 16 * k) * scale)
                cx, cy = bx + bw // 3 - k * int(14 * scale), (by - off) if up else (by + bh + off)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white", outline="black", width=2)
        elif kind == "shout":
            cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
            rx, ry = bw / 2, bh / 2               # the spikes reach the box edge, never past the panel
            pts = []
            for k in range(28):
                a = 2 * math.pi * k / 28
                f = 1.0 if k % 2 == 0 else 0.8
                pts.append((cx + math.cos(a) * rx * f, cy + math.sin(a) * ry * f))
            draw.polygon(pts, fill="white", outline="black")
        else:                                  # speech / whisper: an oval with a tail toward the speaker
            tail_x = bx + bw // 3 if (d.get("place") or "").endswith("left") or i % 2 == 0 else bx + 2 * bw // 3
            up = by + bh + 40 * scale > y + h          # no room below: the tail points up
            ty0 = by + 4 if up else by + bh - 4
            ty1 = max(y + 6, by - int(36 * scale)) if up else min(y + h - 6, by + bh + int(36 * scale))
            draw.polygon([(tail_x - int(12 * scale), ty0), (tail_x + int(12 * scale), ty0), (tail_x + int(4 * scale), ty1)],
                         fill="white", outline="black")
            dash = kind == "whisper"
            draw.ellipse(rect, fill="white", outline="black", width=max(1 if dash else 2, int((2 if dash else 3) * scale)))
            draw.line([(tail_x - int(10 * scale), ty0 + (-1 if up else 1)), (tail_x + int(10 * scale), ty0 + (-1 if up else 1))],
                      fill="white", width=4)
        ty = by + pady
        for line in lines:
            lw = draw.textlength(line, font=font)
            tx = bx + (bw - lw) / 2 if kind != "narration" else bx + padx
            if kind == "sfx":
                draw.text((tx, ty), line, font=font, fill="black", stroke_width=max(3, int(4 * scale)), stroke_fill="white")
            else:
                draw.text((tx, ty), line, font=font, fill="black")
            ty += lh
        taken.append((bx, by, bw, bh))
        out.append({"speaker": d.get("speaker"), "kind": kind, "box": [bx, by, bw, bh]})
    return out


def compose(ws, pid: str, n: int) -> dict:
    """Put the page together: panels cut to their frames, borders, every balloon lettered. Missing art is a grey
    placeholder with the panel's action (so the page can be read before it is drawn)."""
    from PIL import Image, ImageDraw, ImageOps  # pylint: disable=import-outside-toplevel
    proj = load(ws, pid)
    page = _page(proj, n, create=False)
    if not page or not page.get("panels"):
        return {"ok": False, "error": "page %d has no script yet" % n}
    W, H, boxes = rects(proj, page)
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    missing, lettered = [], []
    for panel, box in zip(page["panels"], boxes):
        x, y, w, h = box
        src = Path(ws) / panel["image"] if panel.get("image") else None
        if src is not None and src.is_file():
            try:
                pic = Image.open(src).convert("RGB")
                pic = ImageOps.fit(pic, (w, h), method=Image.LANCZOS, centering=(0.5, 0.4))
                if proj.get("colour") == "mono":
                    pic = ImageOps.grayscale(pic).convert("RGB")
                img.paste(pic, (x, y))
            except OSError:
                src = None
        if src is None or not src.is_file():
            missing.append(panel["n"])
            draw.rectangle((x, y, x + w, y + h), fill="#e9e9ee")
            note = "%d. %s" % (panel["n"], panel.get("action") or "")
            f = _font(18)
            for k, line in enumerate(_wrap(draw, note, f, w - 30)[:8]):
                draw.text((x + 15, y + 15 + k * 22), line, font=f, fill="#777")
        draw.rectangle((x, y, x + w, y + h), outline="black", width=5)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # lettering is clipped to its own panel
        lettered += letter_panel(layer, ImageDraw.Draw(layer), box, panel.get("dialogue") or [],
                                 scale=1.0 if W >= 1000 else 0.85)
        part = layer.crop((x, y, x + w, y + h))
        img.paste(part, (x, y), part)
        draw.rectangle((x, y, x + w, y + h), outline="black", width=5)
    out_dir = pdir(ws, pid) / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / ("page-%02d.png" % n)
    tmp = out_dir / ("page-%02d.part%d.png" % (n, os.getpid()))
    img.save(tmp, optimize=True)
    os.replace(tmp, f)        # never a half-written page in the window (it would show blank)
    rel = os.path.relpath(f, ws).replace("\\", "/")
    page["file"] = rel
    page["missing"] = missing
    page["balloons"] = len(lettered)
    _log(proj, "page %d composed%s" % (n, (" (%d panels not drawn yet)" % len(missing)) if missing else ""))
    save(ws, proj)
    return {"ok": True, "file": rel, "missing": missing, "balloons": len(lettered), "size": [W, H]}


# ----------------------------------------------------------------------------- edits
def edit_dialogue(ws, pid: str, n: int, panel_n: int, dialogue: list) -> dict:
    """New words for one panel: re-lettered, the picture is not redrawn."""
    proj = load(ws, pid)
    page = _page(proj, n, create=False)
    panel = next((p for p in (page or {}).get("panels") or [] if p["n"] == panel_n), None)
    if panel is None:
        return {"ok": False, "error": "no panel %d on page %d" % (panel_n, n)}
    panel["dialogue"] = normalize_panels(proj, [dict(panel, dialogue=dialogue)], 1)[0]["dialogue"]
    save(ws, proj)
    return compose(ws, pid, n)


def edit_panel(ws, pid: str, n: int, panel_n: int, note: str = "", action: str = "", style: str = "",
               make: Callable[[dict], dict] | None = None) -> dict:
    """Change one panel (its action / style) and redraw only it, with the owner's note."""
    proj = load(ws, pid)
    page = _page(proj, n, create=False)
    panel = next((p for p in (page or {}).get("panels") or [] if p["n"] == panel_n), None)
    if panel is None:
        return {"ok": False, "error": "no panel %d on page %d" % (panel_n, n)}
    if action:
        panel["action"] = " ".join(action.split())[:600]
    if style and style in STYLES:
        panel["style"] = style
    panel.setdefault("notes", []).append(note[:300]) if note else None
    save(ws, proj)
    if make is None:
        return compose(ws, pid, n)
    return draw_page(ws, pid, n, make, only=[panel_n], note=note)


# ----------------------------------------------------------------------------- review and export
def review(ws, pid: str) -> dict:
    """The page against the script: drawn, lettered, the cast where the script put them, the format kept."""
    proj = load(ws, pid)
    issues = ["%s: %s" % (k, v) for k, v in (proj.get("warnings") or {}).items()]
    for page in proj.get("pages") or []:
        panels = page.get("panels") or []
        if not panels:
            issues.append("page %d has no script" % page["n"])
            continue
        if proj["format"] == "4koma" and len(panels) != 4:
            issues.append("page %d: a 4-koma needs exactly 4 panels (has %d)" % (page["n"], len(panels)))
        if proj["format"] == "page" and not 5 <= len(panels) <= 8:
            issues.append("page %d: a page has 5-8 panels (has %d)" % (page["n"], len(panels)))
        for p in panels:
            if not p.get("image"):
                issues.append("page %d panel %d is not drawn" % (page["n"], p["n"]))
            for d in p.get("dialogue") or []:
                if len(d["text"].split()) > 25:
                    issues.append("page %d panel %d: a balloon of %d words - split it" % (page["n"], p["n"], len(d["text"].split())))
            known = {c["name"].lower() for c in proj.get("characters") or []}
            for nm in p.get("characters") or []:
                if known and nm.lower() not in known:
                    issues.append("page %d panel %d: %s is not in the cast" % (page["n"], p["n"], nm))
        if not page.get("file"):
            issues.append("page %d is not composed" % page["n"])
    for c in proj.get("characters") or []:
        if not c.get("sheet"):
            issues.append("%s has no reference sheet (the panels will drift)" % c["name"])
    return {"ok": not issues, "issues": issues[:80], "pages": len(proj.get("pages") or []),
            "drawn_panels": sum(1 for pg in proj.get("pages") or [] for p in pg.get("panels") or [] if p.get("image"))}


def export(ws, pid: str, fmt: str = "pdf") -> dict:
    from PIL import Image  # pylint: disable=import-outside-toplevel
    proj = load(ws, pid)
    files = [Path(ws) / pg["file"] for pg in sorted(proj.get("pages") or [], key=lambda x: x["n"]) if pg.get("file")
             and (Path(ws) / pg["file"]).is_file()]
    if not files:
        return {"ok": False, "error": "no composed pages yet"}
    out = pdir(ws, pid) / "exports"
    out.mkdir(parents=True, exist_ok=True)
    base = out / _slug(proj["title"])
    if fmt == "cbz":
        target = base.with_suffix(".cbz")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as z:
            for i, f in enumerate(files):
                z.write(f, "%03d.png" % (i + 1))
    elif fmt == "png":
        return {"ok": True, "files": [os.path.relpath(f, ws).replace("\\", "/") for f in files]}
    else:
        target = base.with_suffix(".pdf")
        imgs = [Image.open(f).convert("RGB") for f in files]
        imgs[0].save(target, save_all=True, append_images=imgs[1:], resolution=150)
    return {"ok": True, "file": os.path.relpath(target, ws).replace("\\", "/"), "pages": len(files)}


# ----------------------------------------------------------------------------- the character library
def _lib_path(ws) -> Path:
    return root(ws) / "characters.json"


def library(ws) -> list:
    try:
        return json.loads(_lib_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _library_get(ws, name: str) -> dict | None:
    return next((c for c in library(ws) if c["name"].lower() == str(name).lower()), None)


def _library_put(ws, ch: dict) -> None:
    lib = [c for c in library(ws) if c["name"].lower() != ch["name"].lower()]
    lib.append({k: ch.get(k) for k in ("id", "name", "role", "age", "look", "personality", "voice", "sheet", "variants")})
    _lib_path(ws).write_text(json.dumps(lib[-200:], indent=1, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------------------- one tool for the agents
GATED = ("sheet", "draw_page", "draw", "edit_panel")   # the steps that draw: an agent's call waits for the owner


def card_text(args: dict, ws) -> str:
    """What the owner reads on the For you card before an agent's drawing step runs ("" = nothing is drawn)."""
    a = args or {}
    act = str(a.get("action") or "").lower()
    if act not in GATED:
        return ""
    proj = load(ws, str(a.get("project") or ""))
    if act == "sheet":
        ch = next((c for c in proj.get("characters") or [] if c["id"] == str(a.get("character") or "")), None)
        return ("Manga '%s' - character sheet: %s" % (proj["title"], look_text(ch))) if ch else ""
    n = int(a.get("page") or 1)
    page = _page(proj, n, create=False) or {}
    only = [int(x) for x in (a.get("panels") or ([a["panel"]] if a.get("panel") else []))]
    lines = ["Manga '%s' - page %d (%s, %s, %s):" % (proj["title"], n, proj["format"], proj["colour"], proj["style"])]
    for p in page.get("panels") or []:
        if only and p["n"] not in only:
            continue
        said = " / ".join('%s: "%s"' % (d["speaker"], d["text"]) for d in p.get("dialogue") or [])
        lines.append("%d. %s, %s - %s%s" % (p["n"], p["shot"], p["angle"], p["action"], (" [%s]" % said) if said else ""))
    if a.get("note"):
        lines.append("Note: %s" % a["note"])
    return "\n".join(lines)[:1800]


WRITE_FORMAT = {"outline": OUTLINE_PROMPT, "characters": CAST_PROMPT, "script": SCRIPT_PROMPT}

# One lock per project around every step that changes it. Each step loads project.json, works for minutes (a model
# call, a picture) and saves the whole file: on 2026-10-28 three page scripts ran at once and page 1's new script (with
# the renamed cast) was overwritten by another job's stale copy. Steps on one project now take turns; reads do not wait
# (save() replaces the file in one move) and other projects run alongside.
READ_ONLY = ("list", "status", "review")
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def project_lock(pid: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(pid or ""), threading.RLock())


def tool(args: dict, ws: Path, make: Callable[[dict], dict] | None = None, ask: Callable[[str], str] | None = None) -> dict:
    """The `manga` tool (each changing step holds its project's lock - see project_lock)."""
    a = dict(args or {})
    act = str(a.get("action") or "status").lower()
    pid = str(a.get("project") or a.get("id") or "")
    if act in READ_ONLY or act == "project" or not pid:
        return _tool(a, ws, make, ask)
    with project_lock(pid):
        return _tool(a, ws, make, ask)


def _tool(args: dict, ws: Path, make: Callable[[dict], dict] | None = None, ask: Callable[[str], str] | None = None) -> dict:
    """The `manga` tool. action: project | outline | characters | sheet | pick | script | layout | draw_page |
    letter | edit_panel | review | export | status | list. Agents write the outline / cast / script themselves (pass
    them as JSON in `data`) or leave it to LOKI's model (`ask`)."""
    a = dict(args or {})
    act = str(a.get("action") or "status").lower()
    ws = Path(ws)
    if a.get("_card") and a.get("prompt") and " ".join(str(a["prompt"]).split()) != " ".join(str(a["_card"]).split()):
        a["note"] = ("%s %s" % (a.get("note") or "", "The owner changed the plan to: " + str(a["prompt"]))).strip()
    pid = str(a.get("project") or a.get("id") or "")
    data = a.get("data")
    if isinstance(data, str) and data.strip():
        try:
            data = json.loads(data)
        except ValueError:
            return {"ok": False, "error": "data must be JSON"}
    try:
        if act == "list":
            return {"ok": True, "projects": projects(ws), "library": [c["name"] for c in library(ws)]}
        if act == "project":
            p = create(ws, a.get("premise") or a.get("prompt") or "", a.get("title", ""), a.get("format", "page"),
                       a.get("colour") or a.get("color") or "mono", a.get("language", "English"), int(a.get("pages") or 4),
                       a.get("tone", "auto"), a.get("ending", "auto"), a.get("style", "normal"), a.get("reading", "ltr"))
            return {"ok": True, "project": p["id"], "next": "outline"}
        if not pid:
            return {"ok": False, "error": "say which project (project=<id>) - action=list shows them"}
        if act == "status":
            p = load(ws, pid)
            return {"ok": True, "project": p, "review": review(ws, pid)}
        if act in WRITE_FORMAT and ask is None and not isinstance(data, dict):
            return {"ok": False, "error": "write the %s yourself and pass it as data= (JSON in the format below), "
                    "then call again" % act, "format": WRITE_FORMAT[act].split("Answer with JSON only:", 1)[-1].strip()}
        if act == "outline":
            p = outline(ws, pid, ask=ask, data=data if isinstance(data, dict) else None)
            return {"ok": True, "outline": p["outline"], "next": "characters", "warnings": p.get("warnings") or {}}
        if act == "characters":
            p = cast(ws, pid, ask=ask, data=data if isinstance(data, dict) else None)
            return {"ok": True, "characters": p["characters"], "next": "sheet for each character",
                    "warnings": p.get("warnings") or {}}
        if act == "sheet":
            if make is None:
                return {"ok": False, "error": "no image maker here"}
            return draw_character(ws, pid, str(a.get("character") or ""), make, int(a.get("variants") or 1))
        if act == "pick":
            return {"ok": True, "character": pick_variant(ws, pid, str(a.get("character") or ""), str(a.get("file") or ""))}
        if act == "script":
            n = int(a.get("page") or 1)
            p = script(ws, pid, n, ask=ask, data=data if isinstance(data, dict) else None)
            pg = _page(p, n, create=False)
            return {"ok": True, "page": pg, "next": "draw_page", "warnings": p.get("warnings") or {}}
        if act == "layout":
            p = load(ws, pid)
            pg = _page(p, int(a.get("page") or 1), create=False)
            if not pg:
                return {"ok": False, "error": "no such page"}
            lay = str(a.get("layout") or "")
            if lay and (lay in LAYOUTS or lay in ("strip", "column") or re.fullmatch(r"grid[5-8]", lay)):
                if lay in LAYOUTS and len(LAYOUTS[lay]) != len(pg.get("panels") or []):
                    return {"ok": False, "error": "%s has %d panels, the page has %d - the script's count stays"
                            % (lay, len(LAYOUTS[lay]), len(pg.get("panels") or []))}
                pg["layout"] = lay
                save(ws, p)
            return compose(ws, pid, pg["n"])
        if act in ("draw_page", "draw"):
            if make is None:
                return {"ok": False, "error": "no image maker here"}
            only = [int(x) for x in (a.get("panels") or [])] if a.get("panels") else None
            return draw_page(ws, pid, int(a.get("page") or 1), make, only=only, note=str(a.get("note") or ""))
        if act == "letter":
            if a.get("panel") and isinstance(data, (list, dict)):
                dl = data if isinstance(data, list) else data.get("dialogue") or []
                return edit_dialogue(ws, pid, int(a.get("page") or 1), int(a["panel"]), dl)
            return compose(ws, pid, int(a.get("page") or 1))
        if act == "edit_panel":
            return edit_panel(ws, pid, int(a.get("page") or 1), int(a.get("panel") or 1), str(a.get("note") or ""),
                              str(a.get("action_text") or a.get("panel_action") or ""), str(a.get("style") or ""), make)
        if act == "review":
            return review(ws, pid)
        if act == "export":
            return export(ws, pid, str(a.get("format") or "pdf"))
    except (ValueError, OSError, KeyError) as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": False, "error": "unknown manga action %r" % act}


TOOL_SCHEMA = {
    "name": "manga",
    "description": ("Manga Studio: make a manga from an idea - project, outline, characters (locked looks + reference "
                    "sheets), per-page panel script (shot, angle, action, emotion, style, dialogue apart from the art), "
                    "draw_page (each panel drawn without text, LOKI letters every balloon), edit_panel, letter, review, "
                    "export (pdf/cbz/png). Order: project -> outline -> characters -> sheet (each) -> script (each page) "
                    "-> draw_page (each page) -> review -> export. Pass your own outline/cast/script as JSON in data. "
                    "Pictures wait for the owner's OK in Home > For you."),
    "inputSchema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["list", "project", "outline", "characters", "sheet", "pick", "script", "layout",
                                              "draw_page", "letter", "edit_panel", "review", "export", "status"]},
        "project": {"type": "string", "description": "the project id (from action=project or list)"},
        "premise": {"type": "string"}, "title": {"type": "string"},
        "format": {"type": "string", "enum": list(FORMATS)}, "colour": {"type": "string", "enum": ["mono", "color"]},
        "language": {"type": "string"}, "pages": {"type": "integer"}, "style": {"type": "string", "enum": list(STYLES)},
        "page": {"type": "integer"}, "panel": {"type": "integer"}, "panels": {"type": "array", "items": {"type": "integer"}},
        "character": {"type": "string"}, "variants": {"type": "integer"}, "file": {"type": "string"},
        "layout": {"type": "string"}, "note": {"type": "string"}, "data": {"type": "object"}},
        "required": ["action"]},
}
