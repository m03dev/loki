"""Better image prompts: Fooocus' style presets and prompt expansion, for any image backend.

Ported from Fooocus (lllyasviel/Fooocus, GPL-3.0 - see engine/licenses/Fooocus-GPL-3.0.txt):
  * the style presets of sdxl_styles/sdxl_styles_fooocus.json and sdxl_styles_sai.json (Stability
    AI's SDXL styles as shipped in Fooocus) -> engine/data/image_styles.json
  * modules/sdxl_styles.py apply_style: the user's prompt goes into the style's "{prompt}" slot and
    the style's negative prompt is added
  * extras/expansion.py: Fooocus V2 expands a short prompt with words from a vocabulary of positive,
    descriptive words (positive.txt), seeded so the same seed gives the same expansion, cleaned with
    safe_str. Fooocus does it with a fine-tuned GPT-2 whose logits are masked to that vocabulary;
    LOKI asks its own model (any size) with an instruction in the same spirit and, when no model
    answers, falls back to a seeded pick from words that are in Fooocus' positive.txt.

The owner loved a fox picture LOKI made; this makes "a fox" into a prompt a free backend
(Pollinations, FLUX, SDXL) turns into a much better picture, in a named style
("pixel art", "cinematic", "anime", ...). It does not call an image backend itself - the caller
passes the result to generate_media / the image specialist. Pure functions + one async call.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

STYLES_FILE = Path(__file__).resolve().parent / "data" / "image_styles.json"
# Visual words that are in Fooocus' positive.txt (checked when ported).
POSITIVE_WORDS = ["intricate", "elegant", "highly detailed", "sharp focus", "dramatic light", "vibrant colors",
                  "cinematic", "atmosphere", "ambient light", "beautiful", "glowing", "rich", "illuminated",
                  "composition", "vivid", "striking", "stunning", "crisp", "delicate", "magical", "cozy", "epic"]
ENHANCE_INSTRUCTION = (
    "You write prompts for an image generator. Rewrite the user's idea as ONE prompt of 25 to 60 words: keep "
    "every subject and detail the user gave, then add what makes a striking picture - the subject's look, "
    "setting, lighting, camera or art medium, colours, mood and composition. Use concrete, positive, "
    "descriptive words; no negatives, no instructions to the reader, no quotes, no lists. If a style is "
    "named, write the prompt in that style. Reply with the prompt only.\n\nIdea: {idea}\nStyle: {style}\n")
_cache: dict = {}


def safe_str(x) -> str:
    """Fooocus' safe_str: collapse double spaces, trim stray punctuation at the ends."""
    x = str(x)
    for _ in range(16):
        x = x.replace("  ", " ")
    return x.strip(",. \r\n")


def styles(path: Path = STYLES_FILE) -> dict:
    key = str(path)
    if key not in _cache:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            _cache[key] = {s["name"]: s for s in data.get("styles", [])}
        except (OSError, ValueError, KeyError):
            _cache[key] = {}
    return _cache[key]


def find_style(name: str, path: Path = STYLES_FILE):
    name = " ".join(str(name or "").lower().replace("_", " ").replace("-", " ").split())
    if not name or name == "none":
        return None
    table = styles(path)
    for key, style in table.items():
        if key.replace("-", " ") == name:
            return style
    for key, style in table.items():
        if name in key.replace("-", " ") or key.replace("-", " ") in name:
            return style
    return None


def apply_style(prompt: str, style_name: str, path: Path = STYLES_FILE) -> tuple:
    """(positive, negative) - Fooocus' apply_style."""
    style = find_style(style_name, path)
    prompt = safe_str(prompt)
    if not style:
        return prompt, ""
    template = style.get("prompt") or "{prompt}"
    positive = template.replace("{prompt}", prompt) if "{prompt}" in template else (prompt + ", " + template)
    return safe_str(positive), safe_str(style.get("negative_prompt", ""))


def expand_offline(prompt: str, seed: int = 0, count: int = 6) -> str:
    """Seeded expansion from the positive vocabulary (Fooocus' fallback spirit: same seed, same words)."""
    rng = random.Random(int(seed) & 0xFFFFFFFF)
    have = str(prompt).lower()
    words = [w for w in POSITIVE_WORDS if w not in have]
    rng.shuffle(words)
    return safe_str(prompt + ", " + ", ".join(words[:count]))


def clean_model_prompt(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S | re.I).strip()
    text = text.strip().strip('"').strip("'")
    for prefix in ("prompt:", "image prompt:", "here is the prompt:", "here's the prompt:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
    text = " ".join(text.split())
    return safe_str(text)[:900]


async def enhance(idea: str, style: str = "", ask=None, seed: int = 0) -> dict:
    """{"prompt", "negative", "style", "source": "model"|"offline"} for one idea."""
    idea = safe_str(idea)
    if not idea:
        return {"ok": False, "error": "give the idea for the picture"}
    found = find_style(style)
    expanded, source = "", "offline"
    if ask is not None:
        try:
            expanded = clean_model_prompt(await ask(ENHANCE_INSTRUCTION.format(idea=idea, style=found["name"] if found
                                                                               else (style or "any"))))
        except Exception:  # noqa: BLE001 - no model: the offline expansion still helps
            expanded = ""
        # a reply that lost the idea (too short, or an apology) is not used
        if len(expanded.split()) >= 6 and not expanded.lower().startswith(("i can't", "i cannot", "sorry")):
            source = "model"
        else:
            expanded = ""
    if not expanded:
        expanded = expand_offline(idea, seed)
    positive, negative = apply_style(expanded, found["name"] if found else "")
    return {"ok": True, "prompt": positive, "negative": negative, "style": found["name"] if found else "",
            "source": source}
