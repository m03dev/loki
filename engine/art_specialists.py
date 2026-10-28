"""The art pipeline's specialists (owner 2026-10-27: "the builder is too vague. They need specialized agents. That's why
we have over 500 skills and loads of 3-D modelling art skills ... the prompts should be very technical").

Each role has its own SKILL.md (skills/art-pipeline/<role>/) - a technical checklist, not mood words - plus the
best-matching skills from the downloaded libraries (harness_data/vendor: ECC, GodotPrompter, awesome-gamedev ...,
~1,300 SKILL.md, mostly game programming; the few art/3D ones are found by keyword).

    for_card(card)        -> the specialist key for a For you card (by stage, else by tool), or ""
    for_goal(goal)        -> the specialist keys an art goal needs, in pipeline order ([] for non-art goals)
    system(key)           -> the Prompt Expert's system prompt, written as that specialist
    skills_text(key, n)   -> that role's SKILL.md + up to n library skill excerpts (for prompts)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWN = ROOT / "skills" / "art-pipeline"
# LOKI_DATA is what the app sets (engine/loki.py); this file used to read only LOKI_DATA_DIR, so a build with its data
# elsewhere (a packaged build, the external drive) never found the downloaded skills.
VENDOR = Path(os.getenv("LOKI_DATA") or os.getenv("LOKI_DATA_DIR") or ROOT / "harness_data") / "vendor"
LOCAL_SKILLS = ROOT / "skills"

SPECIALISTS = {
    "concept": {"name": "Concept Artist", "skill": "concept-artist", "tool": "make_image",
                "keys": ("create-game-assets", "character-design", "concept", "assets-pipeline"),
                "does": "a model-reference concept picture of the subject"},
    "turnaround": {"name": "Technical Artist", "skill": "technical-artist", "tool": "make_turnaround",
                   "keys": ("character-design", "create-game-assets", "3d-essentials"),
                   "does": "orthographic front / side / back views of the approved concept"},
    "model": {"name": "3D Artist", "skill": "3d-artist", "tool": "make_3d",
              "keys": ("3d-essentials", "assets-pipeline", "create-game-assets"),
              "does": "a textured .glb from the front view, checked against side and back"},
    "finish": {"name": "3D Finisher", "skill": "3d-finisher", "tool": "blender",
               "keys": ("blender-gameready", "gameready-retopo", "gameready-uv-bake", "gameready-qa"),
               "does": "a game-ready model: retopology, UVs, baked maps, LODs, exports"},
    "render": {"name": "Lighting / Render", "skill": "lighting-render", "tool": "render_scene",
               "keys": ("camera-system", "shader-basics", "3d-essentials"),
               "does": "a lit turntable and stills of the finished model"},
    "video": {"name": "Video Director", "skill": "video-director", "tool": "make_video",
              "keys": ("camera-system", "camera-systems"),
              "does": "one shot of text-to-video"},
    # Manga Studio (engine/manga.py): the writer plans, the artist draws, the editor letters, checks and exports
    "manga_writer": {"name": "Manga Writer", "skill": "manga-writer", "tool": "manga",
                     "keys": ("manga", "comic", "storyboard", "story"),
                     "does": "the outline, the cast with locked looks and every page's panel script (manga actions "
                             "outline, characters, script - written as JSON in data)"},
    "manga_artist": {"name": "Manga Artist", "skill": "manga-artist", "tool": "manga",
                     "keys": ("manga", "comic", "character-design"),
                     "does": "the character reference sheets and the drawn pages (manga actions sheet, pick, draw_page, "
                             "edit_panel)"},
    "manga_editor": {"name": "Manga Editor", "skill": "manga-editor", "tool": "manga",
                     "keys": ("manga", "comic"),
                     "does": "the lettering, the review against the script and the export (manga actions letter, "
                             "layout, review, export)"},
}
ORDER = ("concept", "turnaround", "model", "finish", "render")
TOOL_TO = {v["tool"]: k for k, v in SPECIALISTS.items()}
TOOL_TO["manga"] = "manga_artist"       # a manga For you card is a drawing step
MANGA = ("manga_writer", "manga_artist", "manga_editor")

ART_GOAL = re.compile(r"\b(manga|comic|4-koma|4koma|yonkoma|webtoon|concept art|character|creature|prop|vehicle|3d model|model of|turnaround|sprite|sculpt|"
                      r"render|lighting|turntable|texture|asset|video|animation|shot)\b", re.I)


def for_card(card: dict) -> str:
    stage = str(card.get("stage") or "")
    if stage in SPECIALISTS:
        return stage
    return TOOL_TO.get(str(card.get("tool") or ""), "")


def for_goal(goal: str) -> list:
    text = str(goal or "")
    if not ART_GOAL.search(text):
        return []
    low = text.lower()
    if re.search(r"\b(manga|comic|4-?koma|yonkoma|webtoon)\b", low):
        return list(MANGA)
    if re.search(r"\b(video|shot|clip|animation)\b", low) and not re.search(r"\b3d model|turnaround\b", low):
        return ["video"]
    if re.search(r"\brender|turntable|lighting\b", low) and not re.search(r"\bconcept|turnaround|model\b", low):
        return ["render"]
    if re.search(r"\b(concept art|picture|image|illustration)\b", low) and not re.search(r"\b3d|model|turnaround\b", low):
        return ["concept"]
    return list(ORDER)


def _read(path: Path, limit: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()
    return text[:limit]


_INDEX: dict = {}


def _library() -> list:
    """[(name, path)] of every downloaded / bundled SKILL.md, once."""
    if "all" in _INDEX:
        return _INDEX["all"]
    found = []
    for base in (VENDOR, LOCAL_SKILLS):
        if base.is_dir():
            for p in base.rglob("SKILL.md"):
                if OWN in p.parents:
                    continue
                found.append((p.parent.name.lower(), p))
    _INDEX["all"] = found
    return found


def library_matches(key: str, n: int = 2) -> list:
    """The library skills for this role: its own named ones first, then the best search matches of every premade
    library (engine/specialist_library.py: wshobson, VoltAgent, ECC ...) for what the role does."""
    spec = SPECIALISTS.get(key) or {}
    out = _named_matches(spec, n)
    if len(out) < n:
        try:
            import specialist_library  # pylint: disable=import-outside-toplevel
            for d in specialist_library.best_specialists("%s %s %s" % (spec.get("name", ""), spec.get("does", ""),
                                                                    " ".join(spec.get("keys", ()))), n * 2, "skill"):
                p = Path(d["path"])
                if OWN not in p.parents and p not in out:
                    out.append(p)
                if len(out) >= n:
                    break
        except Exception:  # noqa: BLE001 - the named matches stand
            pass
    return out


def _named_matches(spec: dict, n: int) -> list:
    out = []
    for want in spec.get("keys", ()):
        for name, path in _library():
            if want in name and path not in out:
                out.append(path)
                break
        if len(out) >= n:
            break
    return out


def skills_text(key: str, n: int = 2, each: int = 1400) -> str:
    spec = SPECIALISTS.get(key)
    if not spec:
        return ""
    parts = [_read(OWN / spec["skill"] / "SKILL.md", 3000)]
    for p in library_matches(key, n):
        body = _read(p, each)
        if body:
            parts.append("From the skill library (%s):\n%s" % (p.parent.name, body))
    return "\n\n".join(x for x in parts if x)


def system(key: str) -> str:
    spec = SPECIALISTS.get(key)
    if not spec:
        return ""
    return ("You are the %s of a small game studio. You write the exact words an image / 3D / video model gets for %s. "
            "Be technical and specific: follow your skill's checklist line by line and fill every line with concrete "
            "values (proportions, part shapes, materials and finish, named colours, pose, camera and lens, light "
            "direction, background). Plain sentences for FLUX / Z-Image / Wan class models - no keyword soup, no "
            "weights, no praise words ('masterpiece', '8k'). Never put words in the picture, and never name what to avoid as a "
            "positive (write 'a plain grey background', not 'no scenery'). Keep everything the original "
            "asked for and fix what is vague or missing.\n\nYour skill:\n%s\n\nAnswer with JSON only: "
            '{"prompt": "...", "why": "one short line: what you changed"}' % (spec["name"], spec["does"],
                                                                                 skills_text(key)))
