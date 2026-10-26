"""One way to name what LOKI makes (owner 2026-10-26: "organize output files names better").

Before: every maker built its own name - "20261026-022217-painterly-fantasy-game-concept-art-wide-cinemati.jpg":
timestamp first, the raw prompt cut mid-word at 48 characters, style words ("painterly", "concept art", "wide
cinematic") crowding out what the picture actually shows.

Now:   <subject>_<YYYYMMDD-HHMM>[_<tag>][_<n>].<ext>      e.g.  knight-sword-shield_20261026-1021.png
       - subject: up to 4 words that say WHAT it is, filler and style words dropped, never cut mid-word;
       - the date stays in the name (sortable, and two makes of the same thing never collide);
       - tag: what kind of variant it is (sprite64, x8, front, draft ...);
       - _2, _3 ... only when the name is taken.
Files go into their kind's folder (images/, sprites/, models/, videos/, audio/, turnarounds/) - never loose.

`display_name()` turns both the new and the old names back into a readable title for the UI.
Standard library only; no other module is needed to use it.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

MAX_WORDS = 4
MAX_CHARS = 36

# words that describe HOW it looks or are grammar, not WHAT it is
FILLER = frozenset("""
a an the of with and or in on at to for from by into onto over under its his her their this that these those
is are be being very some one single full body centered centred isolated standing alert front view side
photo photograph photography photorealistic realistic hyperrealistic render rendered rendering 3d 2d
painterly painting painted illustration illustrated drawing drawn sketch sketched digital art artwork artstation
concept fantasy game asset assets style styled stylized stylised cinematic wide shot closeup close up portrait
professional detailed highly high quality ultra hd 4k 8k sharp focus lighting lit dramatic soft studio
background plain white simple clean flat vector minimal minimalist modern logo icon mark emblem
beautiful epic ethereal cute small tiny big large sleek young old craft play doh clay
""".split())

_STAMP_NEW = re.compile(r"_\d{8}-\d{4}(?:_[a-z0-9]+)*(?:_\d+)?$")
_STAMP_OLD = re.compile(r"^(?:sketch-|higgsfield-|browser-|computer-)?\d{8}-\d{6}-?")


def subject(text: str, fallback: str = "untitled", words: int = MAX_WORDS, limit: int = MAX_CHARS) -> str:
    """The few words that say what a thing is, as a file-safe slug: "a knight with sword and shield, professional
    concept art" -> "knight-sword-shield". Falls back to the plain slug when every word is filler."""
    raw = re.findall(r"[a-z0-9]+", str(text or "").lower())
    keep = [w for w in raw if w not in FILLER and not w.isdigit()]
    seen, picked = set(), []
    for w in keep or raw:
        if w in seen:
            continue
        seen.add(w)
        picked.append(w)
        if len(picked) >= words:
            break
    out = ""
    for w in picked:                       # whole words only, never "cinemati"
        nxt = (out + "-" + w) if out else w
        if len(nxt) > limit:
            break
        out = nxt
    return out or (picked[0][:limit] if picked else fallback)


def stamp(at: float | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M", time.localtime(at if at is not None else time.time()))


def name(text: str, ext: str = "", tag: str = "", fallback: str = "untitled", at: float | None = None) -> str:
    """The file name (no folder): knight-sword-shield_20261026-1021[_tag][.ext]."""
    tag = re.sub(r"[^a-z0-9]+", "", str(tag or "").lower())
    ext = str(ext or "").lstrip(".")
    base = "%s_%s%s" % (subject(text, fallback), stamp(at), ("_" + tag) if tag else "")
    return base + ("." + ext if ext else "")


def path(folder, text: str, ext: str = "", tag: str = "", fallback: str = "untitled", at: float | None = None) -> Path:
    """A free path in `folder` (made if missing): adds _2, _3 ... when the name is taken (with or without ext)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    first = folder / name(text, ext, tag, fallback, at)
    stem, suf = (first.stem, first.suffix) if ext else (first.name, "")
    cand, n = first, 2
    while cand.exists() or (not ext and any(folder.glob(cand.name + ".*"))):
        cand = folder / ("%s_%d%s" % (stem, n, suf))
        n += 1
    return cand


def display_name(file_name: str) -> str:
    """A readable title from a file name, old or new style: "knight-sword-shield_20261026-1021_sprite64.png" ->
    "knight sword shield"; "20261026-022217-red-fox-cub.jpg" -> "red fox cub"."""
    stem = Path(str(file_name or "")).name
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", stem)
    stem = re.sub(r"-x\d+$", "", stem)        # pixel_art's enlarged preview
    stem = _STAMP_OLD.sub("", stem)
    stem = _STAMP_NEW.sub("", stem)
    return stem.replace("-", " ").replace("_", " ").strip() or str(file_name or "")
