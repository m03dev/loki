"""LOKI for anyone (session 29): the help center, first-run onboarding state and the language
settings. Kept out of loki_bridge.py, which only routes here (like portal_api / self_api):

  GET  /help                    every help article: {slug, title, tags, summary, text} (for search)
  GET  /help/<slug>?lang=xx     one article (docs/help/<lang>/<slug>.md first, else docs/help/<slug>.md)
  GET  /onboarding              {done, step, interests, language, reply_language, ...}
  POST /onboarding              {done?, step?, interests?, model_choice?}   (saved per computer)
  GET  /prefs/language          {ui, reply, languages}
  POST /prefs/language          {ui?, reply?}   saved in harness_data/.env, live at once

Help articles are plain Markdown in docs/help/ (first "# " line = the title; an optional
"<!-- tags: a, b -->" line). The window renders them with its own escaping Markdown renderer.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
HELP_DIR = REPO / "docs" / "help"

# The UI languages (app/ui/i18n/<code>.json). Names are in their own language.
LANGUAGES = {
    "en": {"name": "English", "english": "English", "dir": "ltr"},
    "es": {"name": "Español", "english": "Spanish", "dir": "ltr"},
    "fr": {"name": "Français", "english": "French", "dir": "ltr"},
    "de": {"name": "Deutsch", "english": "German", "dir": "ltr"},
    "ar": {"name": "العربية", "english": "Arabic", "dir": "rtl"},
    "hi": {"name": "हिन्दी", "english": "Hindi", "dir": "ltr"},
    "zh": {"name": "中文", "english": "Chinese (Simplified)", "dir": "ltr"},
    "ja": {"name": "日本語", "english": "Japanese", "dir": "ltr"},
}
UI_CHOICES = ("auto",) + tuple(LANGUAGES)
# match = answer in the language the user writes in; ui = always the UI language; en = English only.
REPLY_CHOICES = ("match", "ui", "en")
INTERESTS = ("everyday", "work", "study", "creative", "home", "money", "health", "business")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


# ------------------------------------------------------------------ help center
def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    title, tags, summary = path.stem.replace("-", " ").capitalize(), [], ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# ") and title == path.stem.replace("-", " ").capitalize():
            title = s[2:].strip()
        elif s.startswith("<!--") and "tags:" in s:
            tags = [t.strip() for t in s.split("tags:", 1)[1].replace("-->", "").split(",") if t.strip()]
        elif s and not s.startswith(("#", "<!--", ">", "|", "-", "*", "`")) and not summary:
            summary = s[:220]
    # what the window renders: without the tags comment, and the title as its own block
    body = "\n".join(l for l in text.splitlines() if not (l.strip().startswith("<!--") and l.strip().endswith("-->")))
    body = body.replace("# " + title + "\n", "# " + title + "\n\n", 1) if body.startswith("# ") else body
    return {"slug": path.stem, "title": title, "tags": tags, "summary": summary, "text": text, "body": body}


def help_articles(lang: str = "", root: Path | None = None) -> list:
    """Every article, in the user's language where a translation exists, ordered by 'order' in
    docs/help/index.json (then by title)."""
    root = root or HELP_DIR
    order: list = []
    try:
        order = json.loads((root / "index.json").read_text(encoding="utf-8")).get("order", [])
    except (OSError, ValueError, AttributeError):
        order = []
    out = []
    for path in sorted(root.glob("*.md")):
        if not SLUG.match(path.stem):
            continue
        local = root / lang / path.name if lang in LANGUAGES and lang != "en" else None
        art = _parse(local if local is not None and local.is_file() else path)
        art["translated"] = bool(local is not None and local.is_file())
        out.append(art)
    rank = {s: i for i, s in enumerate(order)}
    out.sort(key=lambda a: (rank.get(a["slug"], 999), a["title"].lower()))
    return out


def help_article(slug: str, lang: str = "", root: Path | None = None) -> dict | None:
    root = root or HELP_DIR
    if not SLUG.match(slug or ""):
        return None
    for path in ((root / lang / (slug + ".md")) if lang in LANGUAGES and lang != "en" else None, root / (slug + ".md")):
        if path is not None and path.is_file():
            art = _parse(path)
            art["translated"] = path.parent != root
            return art
    return None


# ------------------------------------------------------------------ onboarding
def _state_file(agent: Any) -> Path:
    data = Path(getattr(agent, "DATA_DIR", "") or os.environ.get("LOKI_DATA") or (REPO / "harness_data"))
    return data / "app" / "onboarding.json"


def onboarding_state(agent: Any) -> dict:
    try:
        value = json.loads(_state_file(agent).read_text(encoding="utf-8"))
        value = value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        value = {}
    value.setdefault("done", False)
    value.setdefault("step", 0)
    value.setdefault("interests", [])
    return value


def save_onboarding(agent: Any, data: dict) -> dict:
    state = onboarding_state(agent)
    if "done" in data:
        state["done"] = bool(data["done"])
        if state["done"]:
            state["done_at"] = time.time()
    if "step" in data:
        try:
            state["step"] = max(0, min(10, int(data["step"])))
        except (TypeError, ValueError):
            pass
    if "interests" in data and isinstance(data["interests"], list):
        state["interests"] = [i for i in data["interests"] if i in INTERESTS][:len(INTERESTS)]
        _write_env(agent, {"LOKI_INTERESTS": ",".join(state["interests"])})
    if "model_choice" in data:
        state["model_choice"] = str(data["model_choice"])[:40]
    path = _state_file(agent)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": "could not save the setup progress (%s) - check that LOKI's data folder is writable" % exc}
    return {"ok": True, **state}


# ------------------------------------------------------------------ language
def language_prefs() -> dict:
    ui = os.environ.get("LOKI_LANGUAGE", "auto") or "auto"
    reply = os.environ.get("LOKI_REPLY_LANGUAGE", "match") or "match"
    return {"ui": ui if ui in UI_CHOICES else "auto", "reply": reply if reply in REPLY_CHOICES else "match",
            "languages": LANGUAGES, "reply_choices": list(REPLY_CHOICES)}


def _write_env(agent: Any, updates: dict) -> None:
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        peer_link.write_env(Path(agent.env_file_path()), updates)
    except Exception:  # noqa: BLE001 - a read-only data folder: still live for this run
        os.environ.update({k: v for k, v in updates.items() if v is not None})


def save_language(agent: Any, data: dict) -> tuple:
    updates = {}
    if "ui" in data:
        ui = str(data["ui"]).strip().lower()
        if ui not in UI_CHOICES:
            return 400, {"ok": False, "error": "unknown language %r - pick one of %s" % (ui, ", ".join(UI_CHOICES))}
        updates["LOKI_LANGUAGE"] = ui
    if "reply" in data:
        reply = str(data["reply"]).strip().lower()
        if reply not in REPLY_CHOICES:
            return 400, {"ok": False, "error": "reply language must be one of %s" % ", ".join(REPLY_CHOICES)}
        updates["LOKI_REPLY_LANGUAGE"] = reply
    if "browser" in data:   # what the window's system says (navigator.language), for "auto"
        code = str(data["browser"]).split("-")[0].lower()[:5]
        if code.isalpha():
            os.environ["LOKI_BROWSER_LANGUAGE"] = code
    if updates:
        _write_env(agent, updates)
    try:
        agent.refresh_system_prompt()   # LOKI's next answer follows the new setting
    except Exception:  # noqa: BLE001
        pass
    return 200, {"ok": True, **language_prefs()}


# ------------------------------------------------------------------ routing
def handles(method: str, route: str) -> bool:
    if method == "GET":
        return route == "/help" or route.startswith("/help/") or route in ("/onboarding", "/prefs/language")
    return route in ("/onboarding", "/prefs/language")


def route(state: Any, method: str, path: str, data: dict | None = None) -> tuple:
    agent = state.agent
    parsed = urlparse(path)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    r = parsed.path
    lang = q.get("lang", "")
    if method == "GET":
        if r == "/help":
            return 200, {"ok": True, "articles": help_articles(lang)}
        if r.startswith("/help/"):
            art = help_article(r[len("/help/"):], lang)
            if art is None:
                return 404, {"ok": False, "error": "No help article with that name. Open the help center (?) and search."}
            return 200, {"ok": True, **art}
        if r == "/onboarding":
            return 200, {"ok": True, **onboarding_state(agent), **language_prefs()}
        if r == "/prefs/language":
            return 200, {"ok": True, **language_prefs()}
    else:
        data = data or {}
        if r == "/onboarding":
            result = save_onboarding(agent, data)
            return (200 if result.get("ok") else 500), result
        if r == "/prefs/language":
            return save_language(agent, data)
    return 404, {"ok": False, "error": "not found"}
