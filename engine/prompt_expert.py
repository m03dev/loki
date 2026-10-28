"""The Prompt Expert: every prompt an agent writes for a picture is rewritten by an art director before the owner sees it
(owner 2026-10-27: "every prompt should go through a prompt expert agent that improves the prompt ... in the background
... the current prompts suck").

It runs in the engine, in the background, when a prompt card appears in Home > For you (engine/owner_review.py): the
card shows "Prompt Expert is improving this..." and then the better prompt, with the agent's own words kept underneath.
The owner still approves or edits it - nothing is drawn before that.

What it knows (and what the agent usually ignores):
  - what the picture is FOR: who asks and what the stage must deliver (a concept, a T-pose turnaround, a sprite...)
  - the owner's taste, the prompts of pictures they gave a thumbs-up, the reasons they gave for thumbs-down
    (engine/image_feedback.py), their note on a retake
  - real reference prompts that made great pictures in real models, picked for THIS card (engine/specialist_library.py:
    the YouMind galleries, f/awesome-chatgpt-prompts); the card shows their pictures so the owner sees the reference;
    a video card also gets the Wan2.2 makers' own prompt rules
  - how the image models LOKI draws with read prompts (FLUX, Z-Image: plain descriptive sentences, subject first, no
    keyword soup, no weights, nothing to "avoid" written as a positive word); the style finish (art_direction.STYLES)
    is added later by make_image, so it is not repeated here

The model: the strongest one set up first (EXPERT_MODELS: GLM-5.3 on the free NVIDIA key, ...), this computer's
local model last; with neither the card
keeps the agent's words and says the expert could not run. (Laya, LOKI's first layer, is a decision model - it
answers choices and scores, it does not write - so it is not the writer here.)

    improve(card, ask, ws=None) -> {"prompt", "why", "by"} | raises      ask(system, user) -> text
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

SYSTEM = """You are the Prompt Expert of a small game studio: an art director who rewrites the prompts other agents
write for an image model (FLUX / Z-Image class). Make the picture the owner will love.
Rules:
- Plain, vivid, specific English sentences, 60-140 words. Subject first: what it is, its build, materials, colours,
  pose and expression; then composition and camera (framing, angle, lens), light (direction, quality, time of day),
  palette and mood, medium and finish.
- One clear subject unless the brief needs more. Concrete nouns and adjectives, never vague praise ("beautiful",
  "masterpiece", "8k", "trending") and never keyword soup, weights or parentheses.
- Never put words in the picture, and never name what to avoid as a positive (write "an empty sky", not "no text").
- Keep everything the original asked for (subject, style, view, pose, background). Fix what is vague or missing.
- If the picture is FOR a 3D model, a turnaround or a sprite: full body, whole subject in frame, neutral pose (T-pose
  for characters on a turnaround), plain flat light background, even soft light, no cast shadow, no scenery.
- The style's finishing words are added afterwards automatically - do not repeat a style list.
Answer with JSON only: {"prompt": "...", "why": "one short line: what you changed"}"""

TASTE = ("painterly fantasy game concept art; the owner loved a red baby dragon guarding its gold and a fox chasing a "
         "rabbit through glowing grass")


def _feedback(ws) -> tuple:
    """(liked prompts, disliked reasons) from the owner's thumbs (engine/image_feedback.py)."""
    liked, reasons = [], []
    if ws is None:
        return liked, reasons
    try:
        import image_feedback  # pylint: disable=import-outside-toplevel
        rows = image_feedback.ratings(Path(ws)) or {}
        for rel, r in rows.items():
            if int(r.get("rating") or 0) > 0:
                meta = image_feedback._meta(Path(ws), rel) or {}  # pylint: disable=protected-access
                words = str(meta.get("idea") or meta.get("prompt") or "").strip()
                if words:
                    liked.append(words[:300])
            elif int(r.get("rating") or 0) < 0:
                reasons += [image_feedback.REASONS.get(x, x) for x in r.get("reasons") or []]
                if r.get("note"):
                    reasons.append(str(r["note"])[:160])
    except Exception:  # noqa: BLE001 - feedback is a help, never a blocker
        pass
    seen, out = set(), []
    for x in reasons:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return liked[-3:], out[:8]


def brief(card: dict, ws=None) -> str:
    """What the expert is told about one card."""
    args = card.get("args") or {}
    words = str(args.get("prompt") or args.get("subject") or "")
    liked, disliked = _feedback(ws)
    lines = ["The agent's prompt: %s" % words,
             "Who asks: %s%s" % (card.get("who") or "an agent",
                                ("; asset %s, stage %s" % (card["asset"], card.get("stage"))) if card.get("asset") else ""),
             "Tool: %s%s" % (card.get("tool"), ("; style %s" % args["style"]) if args.get("style") else "")]
    if card.get("handoff"):
        lines.append("What it is for:\n%s" % str(card["handoff"])[:900])
    if card.get("tool") == "make_turnaround":
        lines.append("This is a TURNAROUND: describe the subject itself (it will be drawn front / side / back in a T-pose "
                     "on a plain background) - its exact shapes, proportions, materials and colours, so every view matches.")
    if card.get("note"):
        lines.append("The owner's note (must be addressed): %s" % card["note"])
    lines.append("The owner's taste: %s" % TASTE)
    refs = references(card)
    if refs:
        lines.append("Real prompts that made great pictures in real image models (from open prompt galleries). Match "
                     "their level of detail and how they are built - subject, materials, camera, light, finish - but "
                     "keep YOUR subject; never copy theirs:")
        for i, r in enumerate(refs, 1):
            lines.append("%d. \"%s\": %s" % (i, r["title"], r["prompt"][:700]))
    if liked:
        lines.append("Prompts of pictures the owner gave a thumbs-up:\n- " + "\n- ".join(liked))
    if disliked:
        lines.append("What the owner disliked before: " + "; ".join(disliked))
    return "\n".join(lines)


def _task_text(card: dict) -> str:
    args = card.get("args") or {}
    return " ".join(str(x) for x in (args.get("prompt") or args.get("subject") or "", card.get("stage") or "",
                                     card.get("tool") or "", args.get("style") or "") if x)


def _card_kind(card: dict) -> str:
    stage, tool = str(card.get("stage") or ""), str(card.get("tool") or "")
    if stage == "turnaround" or tool == "make_turnaround":
        return "turnaround"
    if stage == "video" or tool == "make_video":
        return "video"
    if stage in ("model", "finish", "render") or tool in ("make_3d", "blender", "render_scene"):
        return "3d"
    return "image"


def references(card: dict, n: int = 3) -> list:
    """Real reference prompts (with the pictures they made) for this card (engine/specialist_library.py)."""
    try:
        import specialist_library  # pylint: disable=import-outside-toplevel
        return specialist_library.image_refs(_task_text(card), n, _card_kind(card))
    except Exception:  # noqa: BLE001 - the expert still writes without references
        return []


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        raise ValueError("the expert gave no JSON: %s" % str(text or "")[:160])
    d = json.loads(m.group(0))
    prompt = " ".join(str(d.get("prompt") or "").split())
    if len(prompt) < 20:
        raise ValueError("the expert's prompt is too short")
    return {"prompt": prompt[:1800], "why": " ".join(str(d.get("why") or "").split())[:200]}


def system_for(card: dict) -> str:
    """The specialist for this card writes it (engine/art_specialists.py; owner 2026-10-27: "they need specialized
    agents ... the prompts should be very technical"); the general art director only when no specialist fits."""
    base = SYSTEM
    try:
        import art_specialists  # pylint: disable=import-outside-toplevel
        key = art_specialists.for_card(card)
        if key:
            base = art_specialists.system(key)
    except Exception:  # noqa: BLE001 - the general expert still runs
        pass
    if _card_kind(card) == "video":   # the video model's makers know best how it reads prompts
        try:
            import specialist_library  # pylint: disable=import-outside-toplevel
            rules = specialist_library.video_rules(bool((card.get("args") or {}).get("image")))
        except Exception:  # noqa: BLE001
            rules = ""
        if rules:
            base += ("\n\nHow the Wan video model's own makers (Alibaba, Wan2.2) say its prompts are written - follow "
                     "these for the prompt text, but still answer with the JSON above:\n" + rules[:4000])
    return base


def improve(card: dict, ask: Callable[[str, str], tuple], ws=None) -> dict:
    """One rewrite. `ask(system, user)` -> (text, model name)."""
    text, by = ask(system_for(card), brief(card, ws))
    out = parse(text)
    out["by"] = by
    out["refs"] = [{"title": r["title"], "image": (r.get("images") or [""])[0], "author": r.get("author", ""),
                    "source": r.get("source", ""), "lib": r.get("lib", "")} for r in references(card)]
    return out


# ----------------------------------------------------------------------------- the engine's model call
def _heavy_busy() -> bool:
    try:
        import heavy  # pylint: disable=import-outside-toplevel
        return bool(heavy.busy())
    except Exception:  # noqa: BLE001 - unknown: assume busy, stay safe
        return True


# The writer, strongest first (owner 2026-10-28: "the prompt agent is bad"): the strongest free model on the NVIDIA key
# (GLM-5.3), the free NVIDIA driver, the paid keys when the owner has them, this computer's model last.
EXPERT_MODELS = ("nvidia-pro", "nvidia", "deepseek", "claude", "gpt", "local")


def asker(agent) -> Callable[[str, str], tuple]:
    """ask(system, user) for the engine: the first model in EXPERT_MODELS that is set up and answers."""
    def ask(system: str, user: str) -> tuple:
        import asyncio  # pylint: disable=import-outside-toplevel
        errors = []
        order = os.environ.get("LOKI_PROMPT_EXPERT_MODELS", ",".join(EXPERT_MODELS)).split(",")
        for name in [x.strip() for x in order if x.strip()]:
            try:
                if name not in agent.MODELS or not agent.provider_configured(name):
                    continue
                if name == "local" and _heavy_busy():   # never load a local model beside Blender / ComfyUI / a
                    errors.append("local: skipped - heavy work is running")   # local job (the Mac crashed, 2026-10-26)
                    continue
                cfg = agent.MODELS[name]
                client = agent.make_client(name)
                model = cfg.model

                async def go():
                    r = await asyncio.wait_for(client.chat.completions.create(
                        model=model, max_tokens=2000, temperature=0.5,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]),
                        float(os.environ.get("LOKI_PROMPT_EXPERT_TIMEOUT_S", "120")))
                    return str(r.choices[0].message.content or "")
                text = asyncio.run(go())
                if text.strip():
                    return text, "%s (%s)" % (name, model)
            except Exception as exc:  # noqa: BLE001 - the next model
                errors.append("%s: %s" % (name, str(exc)[:120]))
        raise RuntimeError("no model answered (%s)" % ("; ".join(errors) or "no model is set up"))
    return ask
