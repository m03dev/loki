"""The Godot class reference, offline: built once from Godot's own doc XML, then searched locally.

In-editor agents search the Godot docs online. Studio keeps the whole class reference (every class, method,
property, signal and constant WITH its description) in one cached file, so the agent can look up
the real API with no network and for the exact Godot version the owner runs.

Where the XML comes from (the first that works):
  1. a folder of class XML files: LOKI_GODOT_DOCS=<dir>, or a Godot source checkout
     (<src>/doc/classes + <src>/modules/*/doc_classes; LOKI_GODOT_SRC=<src>)
  2. the owner's Godot itself: `godot --doctool <tmp> --headless` dumps the reference of THAT build
     (GODOT_BIN, or godot / godot4 on PATH)
  3. git: a shallow sparse clone of github.com/godotengine/godot (doc/classes only, ~10 MB),
     at <version>-stable when a version is given

The cache is harness_data/studio/godot_docs/classes.json.gz (never committed).

    python studio/godot_docs.py build [--from <dir>] [--godot <bin>] [--git [--version 4.7]]
    python studio/godot_docs.py search "move and slide"
    python studio/godot_docs.py show CharacterBody3D.move_and_slide
"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

GIT_URL = "https://github.com/godotengine/godot.git"
_CACHE: dict = {}


def cache_path(data: Path | None = None) -> Path:
    base = Path(data or os.getenv("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data"))
    return base / "studio" / "godot_docs" / "classes.json.gz"


def _clean(text: str | None, limit: int = 0) -> str:
    """Godot's BBCode-ish doc markup -> plain text."""
    t = str(text or "")
    t = re.sub(r"\[codeblocks?\].*?\[/codeblocks?\]", lambda m: _first_block(m.group(0)), t, flags=re.S)
    t = re.sub(r"\[(method|member|signal|constant|enum|annotation|theme_item|param|operator|constructor) ([^\]]+)\]", r"\2", t)
    t = re.sub(r"\[url=([^\]]+)\]([^\[]*)\[/url\]", r"\2 (\1)", t)
    t = re.sub(r"\[/?(b|i|u|code|kbd|br|center|lb|rb|gdscript|csharp|codeblock)\]", "", t)
    t = re.sub(r"\[([A-Z][A-Za-z0-9_]*)\]", r"\1", t)
    t = "\n".join(line.strip() for line in t.strip().splitlines())
    t = re.sub(r"\n{3,}", "\n\n", t)
    return (t[:limit].rstrip() + "...") if limit and len(t) > limit else t


def _first_block(block: str) -> str:
    m = re.search(r"\[gdscript\](.*?)\[/gdscript\]", block, re.S) or re.search(r"\[codeblock\](.*?)\[/codeblock\]", block, re.S)
    return ("\n" + m.group(1).strip() + "\n") if m else ""


def _params(node) -> str:
    out = []
    for p in sorted(node.findall("param"), key=lambda p: int(p.get("index", "0") or 0)):
        s = "%s: %s" % (p.get("name"), p.get("type"))
        if p.get("default") is not None:
            s += " = " + p.get("default")
        out.append(s)
    return ", ".join(out)


def parse_class(path: Path) -> dict | None:
    try:
        root = ET.parse(str(path)).getroot()
    except (ET.ParseError, OSError):
        return None
    if root.tag != "class" or not root.get("name"):
        return None
    cls = {"name": root.get("name"), "inherits": root.get("inherits", ""), "brief": _clean(root.findtext("brief_description"), 400),
           "desc": _clean(root.findtext("description"), 2400), "methods": [], "members": [], "signals": [], "constants": []}
    for group in ("methods", "constructors", "operators"):
        for m in root.findall("%s/*" % group):
            ret = m.find("return")
            sig = "%s(%s) -> %s" % (m.get("name"), _params(m), ret.get("type") if ret is not None else "void")
            if m.get("qualifiers"):
                sig += "  [%s]" % m.get("qualifiers")
            cls["methods"].append([m.get("name"), sig, _clean(m.findtext("description"), 500)])
    for m in root.findall("members/member"):
        cls["members"].append([m.get("name"), m.get("type", ""), m.get("default", ""), _clean(m.text, 400)])
    for s in root.findall("signals/signal"):
        cls["signals"].append([s.get("name"), "%s(%s)" % (s.get("name"), _params(s)), _clean(s.findtext("description"), 300)])
    for c in root.findall("constants/constant"):
        cls["constants"].append([c.get("name"), c.get("value", ""), c.get("enum", ""), _clean(c.text, 200)])
    return cls


def xml_files(folder: Path) -> list:
    folder = Path(folder)
    found = []
    for sub in (folder, folder / "doc" / "classes"):
        if sub.is_dir():
            found += sorted(sub.glob("*.xml"))
    mods = folder / "modules"
    if mods.is_dir():
        found += sorted(mods.glob("*/doc_classes/*.xml"))
    return found


def source_version(folder: Path) -> str:
    """4.7.2-stable from a Godot source checkout's version.py, else ""."""
    try:
        text = (Path(folder) / "version.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    parts = dict(re.findall(r'^(major|minor|patch|status)\s*=\s*"?([\w.]+)"?', text, re.M))
    if "major" not in parts:
        return ""
    v = "%s.%s" % (parts["major"], parts.get("minor", "0"))
    if parts.get("patch", "0") not in ("0", ""):
        v += "." + parts["patch"]
    return v + ("-" + parts["status"] if parts.get("status") else "")


def binary_version(binary: str) -> str:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.match(r"(\d+\.\d+(?:\.\d+)?)\.(\w+)", out)
    return (m.group(1) + "-" + m.group(2)) if m else out[:20]


def build_from(folder: Path, source: str = "", version: str = "") -> dict:
    classes = {}
    for f in xml_files(folder):
        c = parse_class(f)
        if c:
            classes[c["name"]] = c
    if not classes:
        raise RuntimeError("no Godot class XML found in %s" % folder)
    version = version or source_version(folder)
    return {"format": 1, "version": version, "source": source or str(folder), "classes": classes}


def godot_binary() -> str:
    for cand in (os.getenv("GODOT_BIN", ""), shutil.which("godot") or "", shutil.which("godot4") or ""):
        if cand and Path(cand).is_file():
            return cand
    return ""


def dump_with_godot(binary: str, timeout: float = 120) -> Path:
    out = Path(tempfile.mkdtemp(prefix="loki-godot-doctool-"))
    subprocess.run([binary, "--headless", "--doctool", str(out)], capture_output=True, timeout=timeout, cwd=str(out))
    return out


def clone_docs(version: str = "", timeout: float = 300) -> Path:
    out = Path(tempfile.mkdtemp(prefix="loki-godot-docs-git-"))
    argv = ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse"]
    if version:
        argv += ["--branch", version if version.endswith("-stable") else version + "-stable"]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    subprocess.run(argv + [GIT_URL, str(out / "godot")], capture_output=True, timeout=timeout, env=env, check=True)
    subprocess.run(["git", "sparse-checkout", "set", "doc/classes"], cwd=str(out / "godot"), capture_output=True,
                   timeout=timeout, env=env, check=True)
    return out / "godot"


def save(doc: dict, data: Path | None = None) -> Path:
    path = cache_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    os.replace(tmp, path)
    _CACHE.pop(str(path), None)
    return path


def build(data: Path | None = None, folder: str = "", godot: str = "", use_git: bool = False, version: str = "") -> dict:
    """Make the cache. Returns {"ok", "classes", "version", "source", "path"} or {"ok": False, "why"}."""
    tried = []
    candidates = []
    if folder:
        candidates.append(("folder", Path(folder)))
    for env_name in ("LOKI_GODOT_DOCS", "LOKI_GODOT_SRC"):
        if os.getenv(env_name):
            candidates.append((env_name, Path(os.environ[env_name])))
    for kind, path in candidates:
        try:
            doc = build_from(path, "%s %s" % (kind, path))
            return {"ok": True, "classes": len(doc["classes"]), "version": doc["version"], "source": doc["source"],
                    "path": str(save(doc, data))}
        except RuntimeError as exc:
            tried.append(str(exc))
    binary = godot or godot_binary()
    if binary and not use_git:
        try:
            out = dump_with_godot(binary)
            doc = build_from(out, "godot --doctool (%s)" % binary, binary_version(binary))
            shutil.rmtree(out, ignore_errors=True)
            return {"ok": True, "classes": len(doc["classes"]), "version": doc["version"], "source": doc["source"],
                    "path": str(save(doc, data))}
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            tried.append("godot --doctool: %s" % exc)
    try:
        src = clone_docs(version)
        doc = build_from(src, "git %s %s" % (GIT_URL, version or "master"), version or "master")
        shutil.rmtree(src.parent, ignore_errors=True)
        return {"ok": True, "classes": len(doc["classes"]), "version": doc["version"], "source": doc["source"],
                "path": str(save(doc, data))}
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        tried.append("git: %s" % exc)
    return {"ok": False, "why": "; ".join(tried) or "no source"}


def load(data: Path | None = None) -> dict:
    path = cache_path(data)
    key = str(path)
    if key not in _CACHE:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                _CACHE[key] = json.load(fh)
        except (OSError, ValueError):
            return {}
    return _CACHE[key]


def status(data: Path | None = None) -> dict:
    doc = load(data)
    if not doc:
        return {"ready": False, "why": "the Godot docs are not cached yet (python studio/godot_docs.py build)"}
    return {"ready": True, "classes": len(doc.get("classes", {})), "version": doc.get("version", ""), "source": doc.get("source", "")}


def _words(text: str) -> list:
    return [w for w in re.split(r"[^a-z0-9]+", str(text).lower().replace("_", " ")) if len(w) > 1]


def search(query: str, data: Path | None = None, limit: int = 12) -> list:
    """[(score, "Class" | "Class.member", kind, one line)] best first."""
    doc = load(data)
    q = str(query or "").strip()
    if not doc or not q:
        return []
    ql = q.lower().replace(" ", "_")
    qw = set(_words(q))
    hits = []
    for name, c in doc["classes"].items():
        nl = name.lower()
        s = 0.0
        if nl == ql.replace("_", ""):
            s += 100
        elif ql.replace("_", "") in nl:
            s += 30
        s += 4 * len(qw & set(_words(c.get("brief", ""))))
        if s:
            hits.append((s, name, "class", c.get("brief", "")[:160]))
        for kind, rows in (("method", c["methods"]), ("property", c["members"]), ("signal", c["signals"]), ("constant", c["constants"])):
            for row in rows:
                mn = str(row[0]).lower()
                ms = 0.0
                if mn == ql:
                    ms += 60
                elif ql in mn:
                    ms += 25
                overlap = qw & set(_words(mn))
                ms += 10 * len(overlap)
                if ms and len(qw) > 1:
                    ms += 2 * len(qw & set(_words(row[-1])))
                if ms:
                    if nl in ("object", "node"):
                        ms += 1
                    line = row[1] if kind in ("method", "signal") else ("%s: %s" % (row[0], row[1]))
                    hits.append((ms, "%s.%s" % (name, row[0]), kind, (line + " - " + str(row[-1]).split("\n")[0])[:200]))
    hits.sort(key=lambda h: (-h[0], len(h[1])))
    return hits[:limit]


def show(name: str, data: Path | None = None) -> str:
    """The reference text of a class, or of Class.member."""
    doc = load(data)
    if not doc:
        return "error: " + status(data)["why"]
    target = str(name or "").strip()
    member = ""
    if "." in target:
        target, member = target.split(".", 1)
    cls = doc["classes"].get(target) or next((c for n, c in doc["classes"].items() if n.lower() == target.lower()), None)
    if cls is None:
        near = [h[1] for h in search(target, data, 8)]
        return "error: no Godot class %r. Closest: %s" % (target, ", ".join(near) or "none")
    if member:
        out = []
        for kind, rows in (("method", cls["methods"]), ("property", cls["members"]), ("signal", cls["signals"]), ("constant", cls["constants"])):
            for row in rows:
                if str(row[0]).lower() == member.lower():
                    if kind == "property":
                        out.append("%s.%s: %s = %s\n%s" % (cls["name"], row[0], row[1], row[2] or "(no default)", row[3]))
                    elif kind == "constant":
                        out.append("%s.%s = %s%s\n%s" % (cls["name"], row[0], row[1], (" (enum %s)" % row[2]) if row[2] else "", row[3]))
                    else:
                        out.append("%s %s.%s\n%s" % (kind, cls["name"], row[1], row[2]))
        if out:
            return "\n\n".join(out)
        return "error: %s has no member %r. Methods: %s" % (cls["name"], member, ", ".join(r[0] for r in cls["methods"][:60]))
    chain, parent = [], cls.get("inherits")
    while parent and len(chain) < 12:
        chain.append(parent)
        parent = (doc["classes"].get(parent) or {}).get("inherits")
    lines = ["%s%s  (Godot %s)" % (cls["name"], (" < " + " < ".join(chain)) if chain else "", doc.get("version", "?")), cls["brief"], "", cls["desc"][:1500]]
    if cls["members"]:
        lines.append("\nproperties: " + ", ".join("%s: %s" % (m[0], m[1]) for m in cls["members"][:50]))
    if cls["methods"]:
        lines.append("\nmethods:\n" + "\n".join("  " + m[1] for m in cls["methods"][:70]))
    if cls["signals"]:
        lines.append("\nsignals: " + ", ".join(s[1] for s in cls["signals"][:30]))
    enums = sorted({c[2] for c in cls["constants"] if c[2]})
    if enums:
        lines.append("\nenums: " + ", ".join(enums[:30]))
    return "\n".join(lines).strip()


def answer(query: str, data: Path | None = None) -> str:
    """One tool: an exact name shows its reference; anything else searches."""
    q = str(query or "").strip()
    st = status(data)
    if not st["ready"]:
        return "error: " + st["why"]
    if re.fullmatch(r"[A-Z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)?", q):
        text = show(q, data)
        if not text.startswith("error"):
            return text
    hits = search(q, data)
    if not hits:
        return "nothing in the Godot %s reference matches %r" % (st.get("version", ""), q)
    return "Godot %s reference, best matches for %r (show one with its full name):\n%s" % (
        st.get("version", ""), q, "\n".join("- %s [%s] %s" % (h[1], h[2], h[3]) for h in hits))


def main(argv: list | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Godot's class reference, cached offline for LOKI Studio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--from", dest="folder", default="")
    b.add_argument("--godot", default="")
    b.add_argument("--git", action="store_true")
    b.add_argument("--version", default="")
    s = sub.add_parser("search")
    s.add_argument("query")
    sh = sub.add_parser("show")
    sh.add_argument("name")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        r = build(folder=args.folder, godot=args.godot, use_git=args.git, version=args.version)
        print(json.dumps(r, indent=1))
        return 0 if r.get("ok") else 1
    print(answer(args.query) if args.cmd == "search" else show(args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
