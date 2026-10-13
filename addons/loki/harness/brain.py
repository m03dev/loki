"""Loki's brain map - an Obsidian-style graph of everything Loki knows.

`build()` returns {nodes, edges, groups} for the app's Brain view:

    Loki (the conductor) -> its specialist roles -> the capabilities behind them
    Memory               -> facts in memory.md and files in viking://memory
    Skills               -> each skill library -> its skills
    Jobs                 -> recent background jobs -> the backend that ran them
    Docs                 -> the workspace's docs/*.md, linked by [[wikilinks]] and md links
    Vault                -> your Obsidian vault (read-only): every note, linked by
                            [[wikilinks]], plus #tags

Only Markdown is read; nothing is executed or written. Notes are addressed by opaque ids,
and `note_text(id)` only ever returns a file that `build()` itself listed, so the UI can
never ask for an arbitrary path. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_VAULT_NOTES = 1500
MAX_SKILLS_PER_LIBRARY = 60
MAX_MEMORY_FACTS = 150
MAX_NOTE_BYTES = 400_000
WIKILINK = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
MDLINK = re.compile(r"\]\(([^)\s]+\.md)(?:#[^)]*)?\)")
TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{1,40})")
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules", ".venv", "__pycache__"}

GROUPS = {
    "loki": "Loki", "role": "Specialist roles", "capability": "Capabilities", "memory": "Memory",
    "skill": "Skills", "job": "Jobs", "doc": "Project docs", "vault": "Your vault", "tag": "Tags",
}


def _id(kind: str, key: str) -> str:
    return kind + ":" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:12]


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: set[tuple[str, str]] = set()
        self.files: dict[str, Path] = {}

    def node(self, nid: str, label: str, group: str, detail: str = "", path: Path | None = None) -> str:
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "label": label[:80], "group": group, "detail": detail[:400],
                               "note": path is not None}
            if path is not None:
                self.files[nid] = path
        return nid

    def edge(self, a: str, b: str) -> None:
        if a != b and a in self.nodes and b in self.nodes:
            self.edges.add((a, b) if a < b else (b, a))

    def out(self) -> dict:
        degree: dict[str, int] = {}
        for a, b in self.edges:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        nodes = [{**n, "degree": degree.get(n["id"], 0)} for n in self.nodes.values()]
        used = sorted({n["group"] for n in nodes})
        return {"nodes": nodes, "edges": [list(e) for e in sorted(self.edges)],
                "groups": {g: GROUPS.get(g, g) for g in used}}


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_NOTE_BYTES:
            return path.read_bytes()[:MAX_NOTE_BYTES].decode("utf-8", "replace")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _markdown_folder(graph: Graph, root: Path, group: str, hub: str, limit: int, tags: bool) -> None:
    """Every .md under root as a node; [[wikilinks]], relative md links and #tags as edges."""
    root = root.resolve()
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
        if len(files) >= limit:
            break
    by_name: dict[str, str] = {}
    for path in files:
        nid = graph.node(_id(group, str(path)), path.stem, group, str(path.relative_to(root)), path)
        by_name.setdefault(path.stem.lower(), nid)
        by_name.setdefault(path.relative_to(root).with_suffix("").as_posix().lower(), nid)
    for path in files:
        nid = _id(group, str(path))
        text = _read(path)
        linked = False
        for target in WIKILINK.findall(text):
            key = target.strip().lower()
            other = by_name.get(key) or by_name.get(key.split("/")[-1])
            if other:
                graph.edge(nid, other)
                linked = True
        for target in MDLINK.findall(text):
            if "://" in target:
                continue
            candidate = (path.parent / target).resolve()
            other = _id(group, str(candidate))
            if other in graph.nodes:
                graph.edge(nid, other)
                linked = True
        if tags:
            for tag in set(TAG.findall(text)):
                tid = graph.node(_id("tag", tag.lower()), "#" + tag, "tag")
                graph.edge(nid, tid)
        if not linked:
            graph.edge(nid, hub)


def build(data_dir: Path, workspace: Path, registry: Any = None, roster: list[dict] | None = None,
          skill_entries: list | None = None, vault: str = "") -> dict:
    g = Graph()
    loki = g.node("loki", "Loki", "loki", "The conductor: plans, keeps the conversation, calls specialists.")

    # conductor -> roles -> capabilities
    caps: dict[str, str] = {}
    if registry is not None:
        try:
            for row in registry.present():
                cid = g.node("cap:" + row["name"], row["name"], "capability",
                             "%s - %s" % (row["status"], row["description"]))
                caps[row["name"]] = cid
                g.edge(loki, cid)
        except Exception:
            pass
    for role in roster or []:
        rid = g.node("role:" + role["role"], role["role"], "role",
                     ("ready via %s" % role["via"]) if role.get("ready") else ("not ready: %s" % role.get("why", "")))
        g.edge(loki, rid)
        try:
            import conductor  # local import keeps brain.py importable on its own
            for name in conductor.ROLES.get(role["role"], {}).get("capabilities", ()):
                if name in caps:
                    g.edge(rid, caps[name])
        except Exception:
            pass

    # memory
    memory_hub = g.node("hub:memory", "Memory", "memory", "What Loki keeps about you and your work.")
    g.edge(loki, memory_hub)
    facts = [l.strip("-* \t") for l in _read(Path(data_dir) / "memory.md").splitlines() if l.strip("-* \t#")]
    for fact in facts[:MAX_MEMORY_FACTS]:
        g.edge(memory_hub, g.node(_id("memory", fact), fact[:48], "memory", fact))
    memory_dir = Path(data_dir) / "memory"
    if memory_dir.is_dir():
        _markdown_folder(g, memory_dir, "memory", memory_hub, 300, tags=True)

    # skills
    skills_hub = g.node("hub:skills", "Skills", "skill", "Instructions Loki can load.")
    g.edge(loki, skills_hub)
    per_library: dict[str, int] = {}
    for library, name, path in skill_entries or []:
        lib = g.node("lib:" + library, library, "skill", "skill library")
        g.edge(skills_hub, lib)
        if per_library.get(library, 0) >= MAX_SKILLS_PER_LIBRARY:
            continue
        per_library[library] = per_library.get(library, 0) + 1
        g.edge(lib, g.node(_id("skill", str(path)), name, "skill", library, Path(path)))

    # jobs
    try:
        jobs = json.loads(_read(Path(data_dir) / "jobs.json") or "{}").get("jobs", [])
    except ValueError:
        jobs = []
    if jobs:
        jobs_hub = g.node("hub:jobs", "Background jobs", "job", "Work handed to agents.")
        g.edge(loki, jobs_hub)
        for job in sorted(jobs, key=lambda j: j.get("created", 0), reverse=True)[:40]:
            jid = g.node("job:" + str(job.get("id")), str(job.get("title", ""))[:40], "job",
                         "%s on %s" % (job.get("status", ""), job.get("backend", "")))
            g.edge(jobs_hub, jid)
            backend = {"herdr": "herdr", "cua": "cua"}.get(job.get("backend", ""))
            if backend and backend in caps:
                g.edge(jid, caps[backend])

    # project docs
    docs = Path(workspace) / "docs"
    if docs.is_dir():
        docs_hub = g.node("hub:docs", "Project docs", "doc", str(docs))
        g.edge(loki, docs_hub)
        _markdown_folder(g, docs, "doc", docs_hub, 400, tags=False)

    # the user's Obsidian vault
    if vault:
        root = Path(vault).expanduser()
        if root.is_dir():
            vault_hub = g.node("hub:vault", root.name or "Vault", "vault", "Obsidian vault (read-only): %s" % root)
            g.edge(loki, vault_hub)
            _markdown_folder(g, root, "vault", vault_hub, MAX_VAULT_NOTES, tags=True)

    out = g.out()
    out["_files"] = g.files  # stripped by the caller before it is sent
    return out


def note_text(graph: dict, node_id: str) -> str | None:
    """Text of a note that build() listed - never any other file."""
    path = (graph.get("_files") or {}).get(node_id)
    return _read(path) if path is not None else None


def public(graph: dict) -> dict:
    return {k: v for k, v in graph.items() if not k.startswith("_")}


def load_settings(data_dir: Path) -> dict:
    try:
        value = json.loads((Path(data_dir) / "brain.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_vault(data_dir: Path, vault: str) -> str:
    """Remember the vault folder (must exist, or "" to forget it)."""
    vault = str(vault or "").strip()
    if vault:
        root = Path(vault).expanduser()
        if not root.is_dir():
            raise ValueError("no such folder: %s" % vault)
        vault = str(root.resolve())
    settings = load_settings(data_dir)
    settings["vault"] = vault
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    (Path(data_dir) / "brain.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return vault
