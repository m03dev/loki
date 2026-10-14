"""Loki's local context store, addressed with viking:// URIs.

OpenViking (volcengine/OpenViking) organises an agent's context as a filesystem behind
`viking://` URIs. Loki adopts the same addressing over plain local folders, so the memory
layer has one shape now and an OpenViking server can be dropped in later behind the same
`MemoryProvider` protocol (interfaces.py) without touching callers:

    viking://memory/...      harness_data/memory/      (lasting facts, notes)
    viking://skills/...      <repo>/skills/ + vendored skill libraries (read-only)
    viking://project/...     <workspace>/docs/         (the project's own docs, read-only)
    viking://state/...       harness_data/state/       (resumable task state)

Every URI is resolved inside its root; anything that escapes is refused. Writes are only
allowed under memory/ and state/. Standard library only.

Graphiti (a temporal knowledge graph) is deliberately not wired in: add it behind the same
protocol only when Loki needs "what was true before decision X" questions.
"""
from __future__ import annotations

import os
from pathlib import Path

SCHEME = "viking://"
WRITABLE = {"memory", "state"}
MAX_READ = 200_000


class KnowledgeError(ValueError):
    pass


class LocalViking:
    """MemoryProvider over local folders."""

    name = "local-viking"

    def __init__(self, roots: dict[str, list[Path]]) -> None:
        self.roots = {k: [Path(p) for p in v] for k, v in roots.items()}

    def _parse(self, uri: str) -> tuple[str, str]:
        uri = str(uri or "").strip()
        if not uri.startswith(SCHEME):
            raise KnowledgeError("not a viking:// URI: %r" % uri)
        rest = uri[len(SCHEME):].strip("/")
        space, _, path = rest.partition("/")
        if space not in self.roots:
            raise KnowledgeError("unknown namespace %r (have %s)" % (space, ", ".join(sorted(self.roots))))
        return space, path

    def _resolve(self, space: str, path: str, must_exist: bool) -> Path:
        for root in self.roots[space]:
            root = root.resolve()
            target = (root / path).resolve() if path else root
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise KnowledgeError("%r escapes viking://%s" % (path, space)) from exc
            if not must_exist or target.exists():
                return target
        if must_exist:
            raise KnowledgeError("not found: viking://%s/%s" % (space, path))
        return (self.roots[space][0].resolve() / path).resolve()

    def read(self, uri: str) -> str:
        space, path = self._parse(uri)
        target = self._resolve(space, path, must_exist=True)
        if target.is_dir():
            return "\n".join(self.list(uri))
        return target.read_text(encoding="utf-8", errors="replace")[:MAX_READ]

    def write(self, uri: str, text: str) -> None:
        space, path = self._parse(uri)
        if space not in WRITABLE:
            raise KnowledgeError("viking://%s is read-only" % space)
        if not path:
            raise KnowledgeError("a file path is required")
        target = self._resolve(space, path, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(str(text), encoding="utf-8")
        os.replace(tmp, target)

    def list(self, uri: str) -> list[str]:
        space, path = self._parse(uri)
        seen: dict[str, None] = {}
        for root in self.roots[space]:
            root = root.resolve()
            folder = (root / path).resolve() if path else root
            try:
                folder.relative_to(root)
            except ValueError:
                raise KnowledgeError("%r escapes viking://%s" % (path, space)) from None
            if folder.is_dir():
                for child in sorted(folder.iterdir()):
                    if child.name.startswith("."):
                        continue
                    rel = child.relative_to(root).as_posix() + ("/" if child.is_dir() else "")
                    seen[SCHEME + space + "/" + rel] = None
        return list(seen)


def default_store(repo: Path, data_dir: Path, workspace: Path) -> LocalViking:
    data_dir = Path(data_dir)
    return LocalViking({
        "memory": [data_dir / "memory"],
        "state": [data_dir / "state"],
        "skills": [Path(repo) / "skills", data_dir / "vendor"],
        "project": [Path(workspace) / "docs"],
    })
