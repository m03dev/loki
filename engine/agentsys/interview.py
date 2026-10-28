"""The interview: before work starts, LOKI asks the owner 1-4 short questions with options - "is this what you want?"
(owner 2026-10-28: "interview like always asks me if this is what i want with options").

The shape is Claude's AskUserQuestion (1-4 questions; each a short header of at most 12 characters, 2-4 options with
a label and a one-line description, multi-select when the options are not exclusive, and "Other" is always free
text), with ChatGPT deep research's order (ask -> rewrite the request into a brief -> do the work) and A2A's
`input-required` task state for work nobody is watching (the question waits in Home > For you; the job waits).

Why it is fast this time (options.py was switched off on 2026-10-25 because asking a model first held the message up
for 54 s on the Mac's local model):
  - the questions come from templates per kind of work (no model) and drop what the request already says;
  - a model may only sharpen them, inside LOKI_INTERVIEW_MODEL_S (4 s), and is never needed;
  - the owner's message shows at once; the card follows it. "Go as written" always skips.

LOKI_INTERVIEW: "always" (default - every request that makes or changes something), "big" (only goals that are
long or start a team / pipeline), "off". Plain questions ("what is ...?", thanks, yes/no) are never interviewed.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Callable

from . import playbook, trace

MAX_Q = 4
HEADER_MAX = 12
ANSWERS_MARK = "Owner's choices (from the interview):"

# kind -> questions. Each: (header, question, multi, [(label, description)], skip_if regex - the request already says)
TEMPLATES = {
    "image": [
        ("Style", "Which look should it have?", False,
         [("Painterly concept art", "Like the red baby dragon you liked: painted, game concept art"),
          ("Stylized 3D render", "Clean shapes and materials, like a game asset render"),
          ("Pixel art", "Crisp pixels, a limited palette"),
          ("Photoreal", "Looks like a photograph")],
         r"\b(painterly|painted|concept art|pixel|photo ?real\w*|realistic|stylized|cel|anime|watercolou?r|3d render)\b"),
        ("Framing", "How should it be framed?", False,
         [("Full body", "The whole subject, plain background - best for turnarounds and 3D"),
          ("In a scene", "The subject in its world, wide shot"),
          ("Close-up", "Head and shoulders / the detail")],
         r"\b(full[- ]body|close[- ]?up|portrait|wide shot|scene|landscape|environment|headshot)\b"),
        ("Shape", "Which picture shape?", False,
         [("16:9", "Wide - concept art, thumbnails"), ("1:1", "Square - icons, sprites, posts"),
          ("9:16", "Tall - phone, TikTok, Reels")],
         r"\b(\d{1,2}:\d{1,2}|square|vertical|portrait orientation|widescreen)\b"),
    ],
    "turnaround": [
        ("Views", "Which views do you need?", False,
         [("Front, side, back", "The standard model sheet"), ("Plus top", "Adds a top view for 3D")],
         r"\b(top view|front.{0,12}side.{0,12}back)\b"),
        ("Pose", "Which pose?", False,
         [("T-pose", "Arms straight out - best for rigging"), ("A-pose", "Arms down at 45 degrees - better shoulders")],
         r"\b([ta]-?pose)\b"),
    ],
    "3d": [
        ("Use", "What is the model for?", False,
         [("Game asset", "Low-poly, clean topology, baked textures"),
          ("Hero detail", "High detail for renders and close shots"),
          ("Blockout", "Quick shapes to judge the idea")],
         r"\b(low.?poly|game.?ready|game asset|hero|high.?poly|blockout|print)\b"),
        ("Start from", "What should the model be made from?", False,
         [("Newest concept", "The newest picture in your library"),
          ("New concept first", "The Concept Artist draws one first - you OK it in For you"),
          ("Build in Blender", "Modelled from scratch with Blender, no picture")],
         r"\b(from (?:the|this|my) (?:picture|image|concept)|images/|\.png|\.jpe?g|blender)\b"),
    ],
    "video": [
        ("Length", "How long?", False, [("5 seconds", "One shot"), ("10 seconds", "Two shots or a longer move")],
         r"\b\d+\s*(?:s|sec|secs|seconds)\b"),
        ("Shape", "Which shape?", False, [("16:9", "Wide - YouTube, trailers"), ("9:16", "Tall - TikTok, Reels, Shorts")],
         r"\b(\d{1,2}:\d{1,2}|vertical|tiktok|reels|shorts|widescreen)\b"),
        ("Look", "Which look?", False,
         [("Cinematic", "Film lighting, slow camera"), ("Game trailer", "Energetic, the game's style"),
          ("Stylized", "Painterly / animated")],
         r"\b(cinematic|trailer|stylized|anime|painterly|realistic)\b"),
    ],
    "code": [
        ("Scope", "How far should it go?", False,
         [("Root-cause fix", "Find why it breaks and fix that, with a test"),
          ("Smallest change", "Just make this work, nothing else touched"),
          ("Rework it", "Redesign this part properly")],
         r"\b(refactor|rework|redesign|rewrite|minimal|smallest|quick fix)\b"),
        ("When done", "When it works, then what?", False,
         [("Ship to master", "Tests, commit, push - both machines update"),
          ("Commit only", "Commit here, don't push"), ("Leave it", "Show me the change, no commit")],
         r"\b(ship|push|commit|don'?t (?:push|commit))\b"),
    ],
    "marketing": [
        ("Platform", "Where is it going?", True,
         [("TikTok / Reels", "Vertical video, 15-45 s"), ("X", "Short posts and threads"),
          ("YouTube", "Shorts or a video"), ("Reddit", "Following each subreddit's rules")],
         r"\b(tiktok|reels|instagram|youtube|twitter|x\.com|reddit|linkedin)\b"),
        ("Goal", "What should it do?", False,
         [("Show the app", "What LOKI can make"), ("Get sign-ups", "A clear call to action"),
          ("Devlog", "What changed and why it matters")],
         r"\b(sign.?ups?|launch|devlog|awareness|download)\b"),
    ],
    "research": [
        ("Depth", "How deep?", False,
         [("Thorough report", "Many sources, compared, with links"), ("Quick answer", "The short version, a few sources")],
         r"\b(quick|briefly|short|deep|thorough|in.?depth|report)\b"),
        ("Then", "And after the research?", False,
         [("Build it into LOKI", "Turn the findings into code and ship it"), ("Just the report", "Findings only")],
         r"\b(implement|build it|add it|just (?:tell|research))\b"),
    ],
    "writing": [
        ("Length", "How long?", False, [("Short", "A few lines"), ("Medium", "A page"), ("Long", "As long as it needs")],
         r"\b(short|brief|long|\d+\s*words|one.?pager|page)\b"),
        ("Tone", "Which tone?", False, [("Plain", "Direct and clear"), ("Friendly", "Warm, casual"), ("Formal", "Professional")],
         r"\b(formal|casual|friendly|professional|funny|plain)\b"),
    ],
    "general": [
        ("Scope", "How much should this cover?", False,
         [("Exactly this", "Only what you wrote"), ("This and around it", "Also fix what it touches"),
          ("Plan first", "Show me a plan before doing anything")],
         r"\b(only|just|everything|whole|all of)\b"),
        ("Result", "What should you get back?", False,
         [("The finished thing", "Made, checked and shown"), ("A plan to approve", "Steps first, then I build"),
          ("Options to pick from", "A few directions to choose between")],
         r"\b(plan|options|ideas|show me)\b"),
    ],
}

_PLAIN_QUESTION = re.compile(r"^(what|when|who|where|why|how (?:many|much|do|does|is|are)|is|are|does|do|did|can you tell|"
                             r"which)\b[^.!]*\?\s*$", re.I)
_SMALL_TALK = re.compile(r"^(hi|hey|hello|thanks|thank you|ok|okay|yes|no|yep|nope|cool|nice|great|good|lol|sure|"
                         r"go|go ahead|do it|stop|continue)\b[\s!.]*$", re.I)
_BIG = re.compile(r"\b(team|pipeline|everything|whole|rework|redesign|from scratch|game|campaign|research|series|"
                  r"all of|full|complete)\b", re.I)


def mode() -> str:
    m = str(os.environ.get("LOKI_INTERVIEW", "always")).strip().lower()
    return m if m in ("always", "big", "off") else "always"


def needed(text: str, force: bool = False) -> bool:
    t = " ".join(str(text or "").split())
    if not t or ANSWERS_MARK in str(text):
        return False
    if force:
        return True
    m = mode()
    if m == "off" or t.startswith("/") or _SMALL_TALK.match(t) or len(t.split()) < 3:
        return False
    if _PLAIN_QUESTION.match(t) and len(t.split()) <= 25:
        return False
    if m == "big":
        return bool(_BIG.search(t)) or len(t.split()) > 40
    return True


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


WHO = ("Who", "Who should do it?", False,
       [("Specialist team", "LOKI plans it, hands each step to a specialist and checks every result"),
        ("One agent", "One agent does it start to finish")], r"\b(one agent|alone|team of)\b")


def is_big(text: str) -> bool:
    return bool(_BIG.search(text or "")) or len(str(text or "").split()) > 30


def template_questions(text: str, kind: str = "") -> list:
    kind = kind or playbook.kind_of(text)
    out = []
    if is_big(text) and not re.search(WHO[4], text or "", re.I):     # big work: team or one agent?
        out.append({"id": "q1", "header": WHO[0], "question": WHO[1], "multi": False,
                    "options": [{"label": a, "description": b} for a, b in WHO[3]]})
    for header, q, multi, options, skip in TEMPLATES.get(kind, []) + (TEMPLATES["general"] if kind != "general" else []):
        if skip and re.search(skip, text or "", re.I):
            continue          # the request already says it - never ask what was said
        if any(x["header"] == header for x in out):
            continue
        out.append({"id": "q%d" % (len(out) + 1), "header": _clip(header, HEADER_MAX), "question": q, "multi": multi,
                    "options": [{"label": _clip(lab, 40), "description": _clip(desc, 120)} for lab, desc in options][:4]})
        if len(out) >= MAX_Q - (1 if kind != "general" else 0):
            break
    return out[:MAX_Q]


MODEL_PROMPT = """The owner asked LOKI (a desktop 3D/AI studio with agents) for this:
<<<
%(text)s
>>>
Kind of work: %(kind)s. Draft questions LOKI would ask him before starting:
%(draft)s
Improve them for THIS request: drop any question the request already answers, make the options concrete for his
subject (his words, his thing), most likely option first. At most 4 questions, each with a header of at most 12
characters and 2-4 options (label + one-line description). Also give a one-sentence plan of what LOKI will do.
Answer with JSON only: {"plan": "...", "questions": [{"header": "...", "question": "...", "multi": false,
"options": [{"label": "...", "description": "..."}]}]}"""


def validate(qs) -> list:
    out = []
    for q in qs or []:
        if not isinstance(q, dict):
            continue
        opts = [o for o in (q.get("options") or []) if isinstance(o, dict) and str(o.get("label") or "").strip()]
        if not str(q.get("question") or "").strip() or len(opts) < 2:
            continue
        out.append({"id": "q%d" % (len(out) + 1), "header": _clip(q.get("header") or "Choice", HEADER_MAX),
                    "question": _clip(q["question"], 200), "multi": bool(q.get("multi")),
                    "options": [{"label": _clip(o["label"], 40), "description": _clip(o.get("description") or "", 120)}
                                for o in opts[:4]]})
        if len(out) == MAX_Q:
            break
    return out


def plan_line(text: str, kind: str = "") -> str:
    """What LOKI will do, in one line - the "is this what you want?" part."""
    kind = kind or playbook.kind_of(text)
    return {
        "image": "The Concept Artist writes a technical prompt; you OK it in For you; the PC draws it and shows you.",
        "turnaround": "The Technical Artist draws front / side / back together from the concept; you check it off.",
        "3d": "Concept -> turnaround -> 3D model on the PC -> clean-up in Blender -> render; you check each hand-off.",
        "video": "The Video Director writes the shot; the PC renders it with Wan; it plays on Home.",
        "code": "LOKI reads the code, finds the root cause, changes it with a test, runs the suites and reports.",
        "marketing": "Drafts only - copy, scripts and pictures made from your real renders. Nothing is posted.",
        "research": "Several searches in parallel, primary sources first, one report with links.",
        "writing": "One draft in the length and tone you pick; you can send it back with a note.",
    }.get(kind, "LOKI plans the steps, hands each to the right specialist, checks the result and shows you.")


def make(text: str, ask: Callable[[str], str] | None = None, timeout_s: float | None = None, force: bool = False) -> dict:
    """{"ask": bool, "id", "kind", "plan", "questions": [...], "by": "templates"|"<model>"}. Never raises."""
    if not needed(text, force=force):
        return {"ask": False}
    kind = playbook.kind_of(text)
    qs = template_questions(text, kind)
    out = {"ask": bool(qs), "id": uuid.uuid4().hex[:12], "kind": kind, "plan": plan_line(text, kind),
           "questions": qs, "by": "templates", "text": str(text)[:4000], "t": time.time()}
    budget = float(timeout_s if timeout_s is not None else os.environ.get("LOKI_INTERVIEW_MODEL_S", "4") or 4)
    if ask is not None and budget > 0:
        import concurrent.futures as cf  # pylint: disable=import-outside-toplevel
        prompt = MODEL_PROMPT % {"text": str(text)[:2000], "kind": kind,
                                 "draft": json.dumps(qs, ensure_ascii=False)[:3000]}
        pool = cf.ThreadPoolExecutor(max_workers=1)
        try:
            raw = pool.submit(ask, prompt).result(timeout=budget) or ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            better = validate(data.get("questions"))
            if better:
                out["questions"], out["by"] = better, "model"
                out["ask"] = True
            if str(data.get("plan") or "").strip():
                out["plan"] = _clip(data["plan"], 240)
        except Exception:  # noqa: BLE001 - too slow or a bad answer: the templates stand
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    if is_big(text) and not any(q["header"] == WHO[0] for q in out["questions"]) and \
            not re.search(WHO[4], text or "", re.I):   # the model may not drop "team or one agent"
        out["questions"] = [{"id": "q0", "header": WHO[0], "question": WHO[1], "multi": False,
                             "options": [{"label": a, "description": b} for a, b in WHO[3]]}] + out["questions"][:MAX_Q - 1]
    if not out["questions"]:
        out["ask"] = False
    trace.event("interview", "interview", **{"loki.kind": kind, "loki.questions": len(out["questions"]),
                                              "loki.by": out["by"]})
    return out


def brief(text: str, answers: dict | None, questions: list | None = None, note: str = "") -> str:
    """The request with the owner's choices on it - what the agent actually gets."""
    answers = answers or {}
    if not answers and not str(note or "").strip():
        return text
    lines = []
    by_id = {q.get("id"): q for q in questions or []}
    for key, value in answers.items():
        q = by_id.get(key) or next((x for x in questions or [] if x.get("question") == key or x.get("header") == key), None)
        label = (q or {}).get("header") or key
        val = ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
        if val.strip():
            lines.append("- %s: %s" % (label, _clip(val, 300)))
    if str(note or "").strip():
        lines.append("- Also: %s" % _clip(note, 600))
    return "%s\n\n%s\n%s" % (str(text).rstrip(), ANSWERS_MARK, "\n".join(lines))


def card(text: str, who: str = "", cwd: str = "", job: str = "") -> dict | None:
    """For work nobody is watching (a background job, the autopilot): the questions wait in Home > For you as a
    "question" card and the work is parked (A2A input-required). Returns the card, or None when nothing to ask."""
    iv = make(text)
    if not iv.get("ask"):
        return None
    try:
        import owner_review  # pylint: disable=import-outside-toplevel
        return owner_review.queue("question", "interview", {"text": iv["text"], "questions": iv["questions"],
                                                            "plan": iv["plan"], "kind": iv["kind"], "job": job},
                                  cwd or ".", who=who or "LOKI")
    except Exception:  # noqa: BLE001
        return None
