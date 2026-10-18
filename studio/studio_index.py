"""Project awareness for LOKI Studio's agent: what is in the project, and how it hangs together.

Godot projects: project.godot (name, main scene, autoloads, input actions), every scene (nodes,
types, scripts, instanced scenes, signal connections), every script (class_name, extends,
signals, exported vars, functions, preload/load references) and resources - as one graph the
agent can query (`project_index`) or draw (`project_graph` -> a mermaid diagram).

Code (LOKI's own Python/JS, or any repo): a repo map - per file its top-level classes and
functions, like aider's map - so the agent knows where things are before it reads.

Pure standard library, read-only, cached by file mtimes.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

SKIP_DIRS = {".git", ".godot", ".import", "node_modules", "__pycache__", "harness_data", ".venv", "venv", "build", "dist",
             ".mono", ".claude"}
GODOT_EXT = {".tscn", ".gd", ".tres", ".gdshader", ".cs", ".godot"}
CODE_EXT = {".py", ".js", ".ts", ".mjs", ".gd", ".cs", ".sh"}
MAX_FILES = 6000
_CACHE: dict = {}


def _walk(root: Path, exts: set):
    root = Path(root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() in exts or name == "project.godot":
                count += 1
                if count > MAX_FILES:
                    return
                yield p


def res_path(root: Path, path: Path) -> str:
    return "res://" + Path(path).relative_to(root).as_posix()


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ------------------------------------------------------------------ Godot
def parse_project(text: str) -> dict:
    out = {"name": "", "main_scene": "", "autoloads": {}, "inputs": [], "features": ""}
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
            continue
        if "=" not in s or s.startswith(";"):
            continue
        key, _, value = s.partition("=")
        value = value.strip()
        if section == "application" and key == "config/name":
            out["name"] = value.strip('"')
        elif section == "application" and key == "run/main_scene":
            out["main_scene"] = value.strip('"')
        elif section == "application" and key == "config/features":
            out["features"] = ",".join(re.findall(r'"([^"]+)"', value))
        elif section == "autoload":
            out["autoloads"][key.strip('"')] = value.strip('"').lstrip("*")
        elif section == "input" and re.match(r"^[A-Za-z0-9_]+$", key):
            out["inputs"].append(key)
    return out


def parse_scene(text: str) -> dict:
    ext = {}
    for m in re.finditer(r'\[ext_resource ([^\]]*)\]', text):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if attrs.get("id"):
            ext[attrs["id"]] = {"type": attrs.get("type", ""), "path": attrs.get("path", "")}
    nodes, connections = [], []
    for chunk in re.split(r"^\[", text, flags=re.M)[1:]:
        head, _, body = chunk.partition("]")
        if head.startswith("node "):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', head))
            inst = re.search(r'instance=ExtResource\("([^"]+)"\)', head)
            script = re.search(r'^script = ExtResource\("([^"]+)"\)', body, re.M)
            parent = attrs.get("parent")
            name = attrs.get("name", "?")
            path = name if parent is None else (name if parent == "." else parent + "/" + name)
            nodes.append({"name": name, "path": "." if parent is None else path, "type": attrs.get("type", ""),
                          "instance": ext.get(inst.group(1), {}).get("path", "") if inst else "",
                          "script": ext.get(script.group(1), {}).get("path", "") if script else "",
                          "groups": re.findall(r'"([^"]+)"', attrs.get("groups", "")) if "groups" in head else []})
        elif head.startswith("connection "):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', head))
            connections.append({"signal": attrs.get("signal", ""), "from": attrs.get("from", ""), "to": attrs.get("to", ""),
                                "method": attrs.get("method", "")})
    return {"nodes": nodes, "connections": connections,
            "resources": sorted({v["path"] for v in ext.values() if v["path"]})}


def parse_gdscript(text: str) -> dict:
    out = {"class_name": "", "extends": "", "signals": [], "exports": [], "funcs": [], "refs": [], "tool": False,
           "connects": []}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("@tool"):
            out["tool"] = True
        m = re.match(r"^class_name\s+(\w+)", s)
        if m:
            out["class_name"] = m.group(1)
        m = re.match(r"^extends\s+([\w.\"/:]+)", s)
        if m and not out["extends"] and not line.startswith((" ", "\t")):
            out["extends"] = m.group(1).strip('"')
        m = re.match(r"^signal\s+(\w+)", s)
        if m and not line.startswith((" ", "\t")):
            out["signals"].append(m.group(1))
        m = re.match(r"^@export\w*(?:\([^)]*\))?\s+var\s+(\w+)", s)
        if m:
            out["exports"].append(m.group(1))
        m = re.match(r"^(?:static\s+)?func\s+(\w+)\s*\(", s)
        if m and not line.startswith((" ", "\t")):
            out["funcs"].append(m.group(1))
        for r in re.findall(r'(?:preload|load)\(\s*"(res://[^"]+)"', s):
            out["refs"].append(r)
        m = re.search(r"(\w+)\.connect\(\s*([\w.]+)", s)
        if m:
            out["connects"].append("%s -> %s" % (m.group(1), m.group(2)))
    out["refs"] = sorted(set(out["refs"]))
    return out


def godot_index(root: Path, force: bool = False) -> dict:
    """The whole project as a dict (cached by the newest mtime)."""
    root = Path(root).resolve()
    files = list(_walk(root, GODOT_EXT))
    stamp = (len(files), max((f.stat().st_mtime for f in files), default=0))
    key = ("godot", str(root))
    if not force and _CACHE.get(key, {}).get("stamp") == stamp:
        return _CACHE[key]["index"]
    project = parse_project(_read(root / "project.godot"))
    scenes, scripts, resources, shaders = {}, {}, [], []
    for f in files:
        rp = res_path(root, f)
        if f.suffix == ".tscn":
            scenes[rp] = parse_scene(_read(f))
        elif f.suffix == ".gd":
            scripts[rp] = parse_gdscript(_read(f))
        elif f.suffix == ".cs":
            text = _read(f)
            scripts[rp] = {"class_name": (re.findall(r"class\s+(\w+)", text) or [""])[0], "extends": "", "signals":
                           re.findall(r"\[Signal\]\s*public\s+delegate\s+void\s+(\w+?)EventHandler", text), "exports": [],
                           "funcs": re.findall(r"public\s+(?:override\s+)?\w+\s+(\w+)\s*\(", text)[:40], "refs": [], "tool": False,
                           "connects": []}
        elif f.suffix == ".tres":
            resources.append(rp)
        elif f.suffix == ".gdshader":
            shaders.append(rp)
    index = {"root": str(root), "project": project, "scenes": scenes, "scripts": scripts, "resources": resources,
             "shaders": shaders, "built": time.time()}
    _CACHE[key] = {"stamp": stamp, "index": index}
    return index


def godot_summary(index: dict, limit: int = 3500) -> str:
    """A compact text for the system prompt: what the project is and where things are."""
    p = index["project"]
    lines = ["Godot project %r (main scene %s; features %s)" % (p.get("name") or "?", p.get("main_scene") or "none", p.get("features") or "?")]
    if p["autoloads"]:
        lines.append("autoloads: " + ", ".join("%s=%s" % kv for kv in p["autoloads"].items()))
    if p["inputs"]:
        lines.append("input actions: " + ", ".join(p["inputs"][:40]))
    lines.append("%d scenes, %d scripts, %d resources, %d shaders" % (len(index["scenes"]), len(index["scripts"]),
                                                                      len(index["resources"]), len(index["shaders"])))
    for path, sc in list(index["scenes"].items())[:60]:
        root = sc["nodes"][0] if sc["nodes"] else {}
        lines.append("  %s: %s [%s] %d nodes%s%s" % (path, root.get("name", "?"), root.get("type") or "instance", len(sc["nodes"]),
                                                    (" script " + root["script"]) if root.get("script") else "",
                                                    (", %d signal links" % len(sc["connections"])) if sc["connections"] else ""))
    for path, s in list(index["scripts"].items())[:80]:
        lines.append("  %s: %sextends %s%s; funcs %s" % (path, (s["class_name"] + " ") if s["class_name"] else "", s["extends"] or "?",
                                                       ("; signals " + ",".join(s["signals"])) if s["signals"] else "",
                                                       ",".join(s["funcs"][:12])))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n... (project_index for the rest)"


def godot_query(index: dict, query: str = "") -> str:
    """What the index knows about a file, a node type, a script class, a signal or a word."""
    q = str(query or "").strip()
    if not q:
        return godot_summary(index, 12000)
    ql = q.lower()
    out = []
    for path, sc in index["scenes"].items():
        if ql in path.lower():
            out.append("scene %s:\n%s" % (path, "\n".join("  %s [%s]%s%s" % (n["path"], n["type"] or "instance",
                                                                         (" script=" + n["script"]) if n["script"] else "",
                                                                         (" instance=" + n["instance"]) if n["instance"] else "")
                                                         for n in sc["nodes"][:120])))
            out += ["  signal %s: %s -> %s.%s" % (c["signal"], c["from"], c["to"], c["method"]) for c in sc["connections"][:60]]
            continue
        for n in sc["nodes"]:
            if ql in (n["type"] or "").lower() or ql == n["name"].lower() or (n["script"] and ql in n["script"].lower()):
                out.append("%s: node %s [%s]%s" % (path, n["path"], n["type"] or "instance", (" script=" + n["script"]) if n["script"] else ""))
        for c in sc["connections"]:
            if ql in c["signal"].lower() or ql in c["method"].lower():
                out.append("%s: signal %s from %s -> %s.%s" % (path, c["signal"], c["from"], c["to"], c["method"]))
    for path, s in index["scripts"].items():
        if ql in path.lower() or ql == s["class_name"].lower():
            out.append("script %s: class_name %s extends %s\n  signals: %s\n  exports: %s\n  funcs: %s\n  refs: %s\n  connects: %s" % (
                path, s["class_name"] or "-", s["extends"] or "?", ", ".join(s["signals"]) or "-", ", ".join(s["exports"]) or "-",
                ", ".join(s["funcs"]) or "-", ", ".join(s["refs"]) or "-", "; ".join(s["connects"][:20]) or "-"))
            used = [sp for sp, sc in index["scenes"].items() if any(n["script"] == path for n in sc["nodes"])]
            if used:
                out.append("  used by scenes: " + ", ".join(used))
            continue
        if ql in [x.lower() for x in s["signals"] + s["funcs"] + s["exports"]] or ql == s["extends"].lower():
            out.append("%s: has %s (extends %s)" % (path, q, s["extends"]))
    for kind in ("resources", "shaders"):
        out += ["%s %s" % (kind[:-1], r) for r in index[kind] if ql in r.lower()]
    p = index["project"]
    if ql in [a.lower() for a in p["autoloads"]]:
        out.append("autoload %s" % q)
    if ql in [i.lower() for i in p["inputs"]]:
        out.append("input action %s (project.godot [input])" % q)
    return "\n".join(out[:300]) or "nothing in the project index matches %r" % q


def _mid(text: str) -> str:
    return "n" + re.sub(r"[^A-Za-z0-9]", "_", text)[-48:]


def godot_mermaid(index: dict, kind: str = "scenes", focus: str = "") -> str:
    """A mermaid flowchart: scenes (instancing + scripts), or signals (who connects to whom)."""
    lines = ["graph LR"]
    seen = set()

    def node(label: str, shape: str = "box") -> str:
        nid = _mid(label)
        if nid not in seen:
            seen.add(nid)
            short = label.replace("res://", "").replace('"', "'")
            lines.append('  %s%s' % (nid, ('(["%s"])' % short) if shape == "round" else ('["%s"]' % short)))
        return nid

    if kind == "signals":
        for path, sc in index["scenes"].items():
            if focus and focus.lower() not in path.lower():
                continue
            for c in sc["connections"][:80]:
                a = node("%s:%s" % (path.split("/")[-1], c["from"]))
                b = node("%s:%s" % (path.split("/")[-1], c["to"]))
                lines.append("  %s -- %s -> %s" % (a, re.sub(r"[^\w]", "", c["signal"]), b))
        for path, s in index["scripts"].items():
            if focus and focus.lower() not in path.lower():
                continue
            for link in s["connects"][:20]:
                sig, _, target = link.partition(" -> ")
                lines.append("  %s -- %s -> %s" % (node(path, "round"), re.sub(r"[^\w]", "", sig), node(target)))
    else:
        for path, sc in index["scenes"].items():
            if focus and focus.lower() not in path.lower():
                continue
            a = node(path)
            for n in sc["nodes"]:
                if n["instance"]:
                    lines.append("  %s -->|%s| %s" % (a, re.sub(r"[^\w]", "", n["name"]) or "instance", node(n["instance"])))
                if n["script"]:
                    lines.append("  %s -.-> %s" % (a, node(n["script"], "round")))
    if len(lines) == 1:
        lines.append('  empty["nothing to draw"]')
    return "\n".join(lines[:400])


# ------------------------------------------------------------------ code (repo map)
_PY = re.compile(r"^(class|def|async def)\s+(\w+)", re.M)
_JS = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|class\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?\()", re.M)


def repo_map(root: Path, prefix: str = "", limit: int = 6000) -> str:
    """Per file its top-level definitions: `path: name, name, ...`, under `prefix` when given."""
    root = Path(root).resolve()
    key = ("map", str(root), prefix)
    files = [f for f in _walk(root / prefix if prefix else root, CODE_EXT)]
    stamp = (len(files), max((f.stat().st_mtime for f in files), default=0))
    if _CACHE.get(key, {}).get("stamp") != stamp:
        rows = []
        for f in files:
            text = _read(f)
            if f.suffix == ".py":
                names = [m.group(2) for m in _PY.finditer(text)]
            elif f.suffix == ".gd":
                names = parse_gdscript(text)["funcs"]
            elif f.suffix in (".js", ".ts", ".mjs"):
                names = [next(g for g in m.groups() if g) for m in _JS.finditer(text)]
            else:
                names = []
            rel = f.relative_to(root).as_posix()
            rows.append("%s (%d lines): %s" % (rel, text.count("\n") + 1, ", ".join(names[:40]) + (" ..." if len(names) > 40 else "")))
        _CACHE[key] = {"stamp": stamp, "text": "\n".join(rows)}
    text = _CACHE[key]["text"]
    return text if len(text) <= limit else text[:limit] + "\n... (narrow with a folder prefix)"


def is_godot(root: Path) -> bool:
    return (Path(root) / "project.godot").is_file()
