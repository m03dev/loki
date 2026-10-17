"""A prompt library (research round 3; Open WebUI "Prompts" with /commands, LibreChat presets, Lobe
Chat's assistant market, Cherry Studio's agents): reusable prompts with {{variables}}.

  - a prompt = {name (a short slug, used as "/p name"), title, text, tags, uses, builtin};
  - variables are written {{like this}} or {{name|default}}; filling asks for each one once;
    {{date}}, {{time}}, {{weekday}} and {{clipboard}} (given by the window) fill themselves;
  - LOKI ships starter prompts for everyday jobs (an email reply, a summary, explain simply,
    translate, a meal plan, a trip plan, a cover letter, fix grammar ...); the owner's own prompts
    and edits live in DATA_DIR/prompts.json; a built-in that is edited becomes the owner's copy,
    a deleted built-in stays hidden.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

VAR = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9 _-]{0,40}?)\s*(?:\|([^}]*))?\}\}")
AUTO_VARS = ("date", "time", "weekday", "clipboard")
_LOCK = threading.Lock()

STARTERS = [
    ("reply", "Reply to an email", "Write a reply to this email. Tone: {{tone|friendly and clear}}. "
     "Keep it short and answer every question it asks.\n\nThe email:\n{{email}}", ["writing", "email"]),
    ("summary", "Summarise", "Summarise this in {{length|5 bullet points}} for someone with no background. "
     "Put the most important point first.\n\n{{text}}", ["reading"]),
    ("explain", "Explain simply", "Explain {{topic}} as if I were {{audience|12 years old}}. Use one everyday "
     "example and no jargon. End with one question I could ask next.", ["learning"]),
    ("translate", "Translate", "Translate this into {{language}}. Keep the meaning and the tone; for anything "
     "that has no direct translation, add a short note.\n\n{{text}}", ["language"]),
    ("grammar", "Fix grammar and spelling", "Correct the grammar, spelling and punctuation of this text. Keep my "
     "words and style; list the 3 biggest changes after it.\n\n{{text}}", ["writing"]),
    ("meals", "Plan meals for the week", "Plan {{days|7}} days of dinners for {{people|2}} people. Diet: "
     "{{diet|no restrictions}}. Budget: {{budget|low}}. Give a shopping list grouped by aisle at the end.", ["home"]),
    ("trip", "Plan a trip", "Plan a {{days|3}}-day trip to {{place}} in {{month|the next month}} for "
     "{{who|two adults}}. Day by day, with one rainy-day option and rough costs.", ["travel"]),
    ("cover", "Cover letter", "Write a one-page cover letter for this job, using my background. Specific, "
     "no clichés.\n\nThe job:\n{{job}}\n\nMy background:\n{{background}}", ["work", "writing"]),
    ("decide", "Help me decide", "I am deciding: {{decision}}. Ask me up to 3 questions first, then compare "
     "the options in a table (cost, effort, risk, upside) and say which you would pick and why.", ["thinking"]),
    ("code-review", "Review this code", "Review this code for bugs, security problems and unclear parts. "
     "Most important first, each with the fix.\n\n```\n{{code}}\n```", ["code"]),
    ("message", "Write a message", "Write a {{kind|text message}} to {{who}} about {{about}}. Tone: "
     "{{tone|warm}}. Give two versions: short and a bit longer.", ["writing"]),
    ("today", "Plan my day", "Today is {{weekday}} {{date}}. Here is what I have to do:\n{{tasks}}\n\nMake a "
     "realistic schedule with breaks, hardest work first, and say what to move to tomorrow.", ["planning"]),
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(name or "").strip().lower()).strip("-")[:32]


def variables(text: str) -> list:
    """[{name, default}] in order of first use; the self-filling ones are left out."""
    out, seen = [], set()
    for m in VAR.finditer(str(text or "")):
        name = m.group(1).strip()
        key = name.lower()
        if key in seen or key in AUTO_VARS:
            continue
        seen.add(key)
        out.append({"name": name, "default": (m.group(2) or "").strip()})
    return out


def fill(text: str, values: dict | None = None, now: float | None = None, clipboard: str = "") -> dict:
    """{ok, text, missing}: every {{var}} replaced by its value, else its default; `missing` lists
    the ones with neither (the text keeps them, so nothing is silently dropped)."""
    values = {str(k).strip().lower(): str(v) for k, v in (values or {}).items()}
    stamp = time.localtime(now if now is not None else time.time())
    auto = {"date": time.strftime("%Y-%m-%d", stamp), "time": time.strftime("%H:%M", stamp),
            "weekday": time.strftime("%A", stamp), "clipboard": clipboard}
    missing: list = []

    def sub(m):
        key = m.group(1).strip().lower()
        if values.get(key, "").strip():
            return values[key]
        if key in auto and auto[key]:
            return auto[key]
        if (m.group(2) or "").strip():
            return m.group(2).strip()
        if m.group(1).strip() not in missing:
            missing.append(m.group(1).strip())
        return m.group(0)

    filled = VAR.sub(sub, str(text or ""))
    return {"ok": not missing, "text": filled, "missing": missing}


class Library:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list:
        data = self._load()
        own = {p["name"]: p for p in data.get("prompts", []) if isinstance(p, dict) and p.get("name")}
        hidden = set(data.get("hidden", []))
        uses = data.get("uses", {})
        out = []
        for name, title, text, tags in STARTERS:
            if name in own or name in hidden:
                continue
            out.append({"name": name, "title": title, "text": text, "tags": tags, "builtin": True})
        out += [dict(p, builtin=False) for p in own.values()]
        for p in out:
            p["uses"] = int(uses.get(p["name"], 0))
            p["variables"] = variables(p["text"])
        out.sort(key=lambda p: (-p["uses"], p["builtin"], p["title"].lower()))
        return out

    def get(self, name: str) -> dict | None:
        key = _slug(name)
        return next((p for p in self.all() if p["name"] == key), None)

    def save(self, name: str, text: str, title: str = "", tags=None) -> dict:
        key = _slug(name or title)
        if not key:
            return {"ok": False, "error": "give the prompt a short name (letters, numbers, dashes)"}
        if not str(text or "").strip():
            return {"ok": False, "error": "the prompt is empty"}
        tags = [str(t).strip()[:20] for t in (tags if isinstance(tags, list) else str(tags or "").split(",")) if str(t).strip()][:6]
        with _LOCK:
            data = self._load()
            prompts = [p for p in data.get("prompts", []) if isinstance(p, dict) and p.get("name") != key]
            prompts.append({"name": key, "title": (str(title or "").strip() or key)[:60],
                            "text": str(text)[:8000], "tags": tags, "updated": time.time()})
            data["prompts"] = prompts[-300:]
            data["hidden"] = [h for h in data.get("hidden", []) if h != key]
            self._save(data)
        return {"ok": True, "prompt": self.get(key)}

    def delete(self, name: str) -> dict:
        key = _slug(name)
        with _LOCK:
            data = self._load()
            before = len(data.get("prompts", []))
            data["prompts"] = [p for p in data.get("prompts", []) if p.get("name") != key]
            builtin = any(s[0] == key for s in STARTERS)
            if builtin and key not in data.get("hidden", []):
                data.setdefault("hidden", []).append(key)
            if len(data["prompts"]) == before and not builtin:
                return {"ok": False, "error": "no prompt called %s" % key}
            self._save(data)
        return {"ok": True}

    def used(self, name: str) -> None:
        key = _slug(name)
        with _LOCK:
            data = self._load()
            uses = data.setdefault("uses", {})
            uses[key] = int(uses.get(key, 0)) + 1
            self._save(data)

    def search(self, query: str, limit: int = 8) -> list:
        words = [w for w in re.findall(r"[a-z0-9]+", str(query or "").lower()) if len(w) > 1]
        items = self.all()
        if not words:
            return items[:limit]
        scored = []
        for p in items:
            hay = " ".join([p["name"], p["title"], " ".join(p.get("tags", [])), p["text"][:300]]).lower()
            score = sum(3 if w in p["name"] or w in p["title"].lower() else 1 for w in words if w in hay)
            if score:
                scored.append((score, p))
        scored.sort(key=lambda s: -s[0])
        return [p for _, p in scored[:limit]]
