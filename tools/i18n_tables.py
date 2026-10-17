"""LOKI's UI string tables (app/ui/i18n/<lang>.json): extract the English, check the others.

    python tools/i18n_tables.py --check        every table has every key, same {placeholders}
    python tools/i18n_tables.py --write-en     refresh en.json from the code (keeps hand-written keys)
    python tools/i18n_tables.py --missing es   the keys es.json still lacks, with their English

Where the English comes from (the code is the source of truth, so a new string needs no
separate edit to en.json):
  - tr("key", "English") / keyed(node, "key", "English") / button(cls, "key", "English", ...)
    / choiceRow("key", "English", ...) / ["value", "key", "English"] option lists, in app/ui/*.js
  - gallery.js CATEGORIES and TASKS (cat.<id>, task.<id>.title, task.<id>.prompt)
  - "phrases": icon names and tooltips (icons.js ICON_BUTTONS and TAB_ICONS, the Settings tab
    names from index.html, and literal dataset.tipName / tipWhat strings), keyed by their English
  - keys only written by hand in en.json (index.html's static words, i18n.js STATIC) are kept

A table's "_meta" says its language, direction and whether it still needs a native review.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
TABLES = UI / "i18n"
LANGS = ("en", "es", "fr", "de", "ar", "hi", "zh", "ja")
STR = r'"((?:[^"\\]|\\.)*)"'
KEY = r'"([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)"'
PATTERNS = [
    re.compile(r"\b(?:tr|uiText|t)\(\s*" + KEY + r"\s*,\s*" + STR),
    re.compile(r"\bkeyed\(\s*[^,()]+(?:\([^()]*\))?\s*,\s*" + KEY + r"\s*,\s*" + STR),
    re.compile(r"\bbutton\(\s*" + STR + r"\s*,\s*" + KEY + r"\s*,\s*" + STR),
    re.compile(r"\bchoiceRow\(\s*" + KEY + r"\s*,\s*" + STR + r"(?:\s*,\s*" + KEY + r"\s*,\s*" + STR + r")?"),
    re.compile(r"\[\s*" + STR + r"\s*,\s*" + KEY + r"\s*,\s*" + STR + r"\s*\]"),
    re.compile(r"\b(?:LokiDialog\(\s*" + STR + r"\s*,|nav\()\s*" + KEY + r"\s*,\s*" + STR),
    re.compile(r"\[\s*" + KEY + r"\s*,\s*" + STR + r"\s*\]"),
]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _unescape(s: str) -> str:
    return json.loads('"' + s + '"')


def extract() -> tuple[dict, dict]:
    """(keys, phrases) - every English string the UI code asks the tables for."""
    keys: dict = {}
    phrases: dict = {}
    for path in sorted(UI.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for pat in PATTERNS:
            for m in pat.finditer(text):
                g = m.groups()
                if pat is PATTERNS[2]:
                    keys.setdefault(g[1], _unescape(g[2]))
                elif pat is PATTERNS[3]:
                    keys.setdefault(g[0], _unescape(g[1]))
                    if g[2]:
                        keys.setdefault(g[2], _unescape(g[3]))
                elif pat is PATTERNS[4]:
                    if path.name != "i18n.js":   # its STATIC list is [selector, key, attribute]
                        keys.setdefault(g[1], _unescape(g[2]))
                elif pat is PATTERNS[5]:
                    keys.setdefault(g[-2], _unescape(g[-1]))
                else:
                    keys.setdefault(g[0], _unescape(g[1]))
        for m in re.finditer(r"dataset\.tip(?:Name|What)\s*=\s*" + STR, text):
            phrases.setdefault(_unescape(m.group(1)), "")
    gallery = (UI / "gallery.js").read_text(encoding="utf-8")
    for m in re.finditer(r'\[\s*"([a-z]+)"\s*,\s*' + STR + r'\s*\]', gallery[gallery.index("CATEGORIES"):gallery.index("TASKS")]):
        keys["cat." + m.group(1)] = _unescape(m.group(2))
    keys.setdefault("cat.all", "All")
    block = gallery[gallery.index("const TASKS"):gallery.index("SAFETY_EN")]
    for m in re.finditer(r'\[\s*"([a-z_]+)"\s*,\s*"([a-z]+)"\s*,\s*' + STR + r"\s*,\s*" + STR + r"\s*\]", block):
        keys["task.%s.title" % m.group(1)] = _unescape(m.group(3))
        keys["task.%s.prompt" % m.group(1)] = _unescape(m.group(4))
    icons = (UI / "icons.js").read_text(encoding="utf-8")
    for m in re.finditer(r'\[\s*' + STR + r'\s*,\s*"\w+"\s*,\s*' + STR + r"\s*,\s*" + STR + r"\s*\]", icons):
        phrases.setdefault(_unescape(m.group(2)), "")
        phrases.setdefault(_unescape(m.group(3)), "")
    for m in re.finditer(r'^\s*\w+: \["\w+", ' + STR + r"\]", icons, re.M):
        phrases.setdefault(_unescape(m.group(1)), "")
    index = (UI / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r'role="tab" data-tab="\w+"[^>]*>(?:<span[^>]*>[^<]*</span>)?([^<]+)<', index):
        phrases.setdefault(m.group(1).replace("&amp;", "&").strip(), "")
    phrases.pop("", None)
    return keys, phrases


def load(lang: str) -> dict:
    try:
        return json.loads((TABLES / (lang + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_en() -> dict:
    keys, phrases = extract()
    en = load("en")
    meta = en.get("_meta", {"language": "English", "code": "en", "dir": "ltr", "review": False})
    out = {"_meta": meta}
    hand = {k: v for k, v in en.items() if k not in ("_meta", "phrases")}
    merged = dict(hand)
    merged.update(keys)
    for k in sorted(merged):
        out[k] = merged[k]
    out["phrases"] = {p: p for p in sorted(set(phrases) | set((en.get("phrases") or {}).keys()))}
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / "en.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def problems(lang: str, en: dict | None = None) -> list:
    """What is wrong with one table compared to English."""
    en = en if en is not None else load("en")
    table = load(lang)
    out = []
    if not table:
        return ["%s.json is missing or not valid JSON" % lang]
    meta = table.get("_meta") or {}
    if meta.get("code") != lang:
        out.append("%s: _meta.code is %r" % (lang, meta.get("code")))
    for key, value in en.items():
        if key in ("_meta", "phrases"):
            continue
        got = table.get(key)
        if not isinstance(got, str) or not got.strip():
            out.append("%s: missing %s" % (lang, key))
        elif sorted(PLACEHOLDER.findall(got)) != sorted(PLACEHOLDER.findall(value)):
            out.append("%s: %s has placeholders %s, English has %s" % (lang, key, PLACEHOLDER.findall(got), PLACEHOLDER.findall(value)))
    for key in table:
        if key not in en and key not in ("_meta", "phrases"):
            out.append("%s: %s is not an English key (typo or removed?)" % (lang, key))
    tp = table.get("phrases") or {}
    for phrase in (en.get("phrases") or {}):
        if not isinstance(tp.get(phrase), str) or not tp.get(phrase).strip():
            out.append("%s: missing phrase %r" % (lang, phrase))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-en", action="store_true")
    ap.add_argument("--missing", default="")
    args = ap.parse_args()
    if args.write_en:
        out = write_en()
        print("en.json: %d keys, %d phrases" % (len(out) - 2, len(out["phrases"])))
    if args.missing:
        en, table = load("en"), load(args.missing)
        miss = {k: v for k, v in en.items() if k not in ("_meta", "phrases") and not table.get(k)}
        miss["phrases"] = {p: p for p in en.get("phrases", {}) if not (table.get("phrases") or {}).get(p)}
        print(json.dumps(miss, ensure_ascii=False, indent=1))
    if args.check or not (args.write_en or args.missing):
        keys, phrases = extract()
        en = load("en")
        bad = ["en: missing %s (run --write-en)" % k for k in keys if k not in en]
        bad += ["en: missing phrase %r (run --write-en)" % p for p in phrases if p not in (en.get("phrases") or {})]
        for lang in LANGS[1:]:
            bad += problems(lang, en)
        for line in bad[:80]:
            print("  " + line)
        print("%d problems in %d tables" % (len(bad), len(LANGS)))
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
