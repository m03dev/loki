"""Workbench - the Claude Code habits, for LOKI's own window.

  * Checkpoints: before every request that may change files, the workspace is snapshotted
    into a PRIVATE shadow git store (<state>/checkpoints.git, --work-tree=<workspace>). It
    never touches the project's own .git, branches or index. You can see what a request
    changed (a unified diff) and rewind the files to any checkpoint; rewinding first takes a
    checkpoint of "now", so a rewind can itself be undone.
  * @file mentions: "@src/app.py" in a message attaches that file's text (bounded), the way
    Claude Code does, so the model reads exactly what you pointed at.
  * File search for the @ picker in the composer.

Everything here is bounded (size caps, timeouts) and never raises into the request path:
a checkpoint that cannot be taken is reported, the request still runs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "harness_data", ".loki", ".godot",
             "dist", "build", ".next", ".cache", "target", ".idea", ".vscode"}
BIG_SUFFIXES = (".gguf", ".safetensors", ".bin", ".pt", ".onnx", ".zip", ".7z", ".tar", ".gz", ".mp4", ".mov",
                ".psd", ".blend", ".fbx", ".exr", ".dmg", ".exe", ".iso")
MAX_FILE_BYTES = 2 * 1024 * 1024          # bigger files are not snapshotted
MENTION_MAX = 20000                        # characters attached per @file
MENTION_TOTAL = 60000
KEEP = 50                                  # checkpoints kept


def _git_exe() -> str:
    return shutil.which("git") or ""


class Checkpoints:
    def __init__(self, workspace: Path, store: Path) -> None:
        self.workspace = Path(workspace)
        self.store = Path(store)
        self.index_file = self.store.parent / "checkpoints.json"

    # -- plumbing
    def _git(self, *args: str, timeout: float = 60.0, input_text: str | None = None) -> tuple:
        exe = _git_exe()
        if not exe:
            return 127, "git is not installed"
        env = dict(os.environ, GIT_DIR=str(self.store), GIT_WORK_TREE=str(self.workspace), GIT_TERMINAL_PROMPT="0",
                   GIT_AUTHOR_NAME="LOKI", GIT_AUTHOR_EMAIL="loki@localhost", GIT_COMMITTER_NAME="LOKI",
                   GIT_COMMITTER_EMAIL="loki@localhost", LC_ALL="C")
        try:
            proc = subprocess.run([exe, "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args],
                                  cwd=str(self.workspace), env=env, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, input=input_text, stdin=None if input_text else subprocess.DEVNULL)
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, "git timed out"
        except OSError as exc:
            return 126, str(exc)

    def _ensure(self) -> str:
        if (self.store / "HEAD").is_file():
            return ""
        self.store.parent.mkdir(parents=True, exist_ok=True)
        code, out = self._git("init", "-q")
        if code != 0:
            return out.strip()[:300]
        exclude = self.store / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(["%s/" % d for d in sorted(SKIP_DIRS)] + ["*%s" % s for s in BIG_SUFFIXES]) + "\n",
                           encoding="utf-8")
        return ""

    def _index(self) -> list:
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save_index(self, items: list) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(json.dumps(items[-KEEP:], indent=1), encoding="utf-8")

    def _stage_all(self) -> None:
        self._git("add", "-A", "--", ".", timeout=120)
        # drop anything too large that slipped past the patterns
        code, out = self._git("diff", "--cached", "--name-only", "-z")
        for name in out.split("\0"):
            if not name:
                continue
            try:
                if (self.workspace / name).stat().st_size > MAX_FILE_BYTES:
                    self._git("rm", "--cached", "-q", "--", name)
            except OSError:
                pass

    # -- the API
    def take(self, label: str, kind: str = "auto") -> dict:
        """Snapshot the workspace now. Returns the checkpoint, or {"error": ...}."""
        if not self.workspace.is_dir():
            return {"error": "the workspace folder does not exist"}
        problem = self._ensure()
        if problem:
            return {"error": "could not start checkpoints: " + problem}
        self._stage_all()
        code, tree = self._git("write-tree")
        if code != 0:
            return {"error": "could not snapshot: " + tree.strip()[:200]}
        tree = tree.strip()
        items = self._index()
        if items and items[-1].get("tree") == tree and kind == "auto":
            return items[-1]                         # nothing changed since the last one
        parent = ["-p", items[-1]["commit"]] if items and items[-1].get("commit") else []
        code, commit = self._git("commit-tree", tree, *parent, "-m", (label or "checkpoint")[:200])
        if code != 0:
            return {"error": "could not snapshot: " + commit.strip()[:200]}
        commit = commit.strip()
        self._git("update-ref", "refs/loki/latest", commit)
        item = {"id": commit[:12], "commit": commit, "tree": tree, "t": time.time(), "label": (label or "")[:200], "kind": kind}
        items.append(item)
        self._save_index(items)
        return item

    def list(self) -> list:
        items = self._index()[::-1]
        return [{k: it.get(k) for k in ("id", "t", "label", "kind")} for it in items]

    def _find(self, cid: str) -> dict | None:
        for it in self._index():
            if it.get("id") == cid or it.get("commit") == cid:
                return it
        return None

    def changes(self, cid: str = "") -> dict:
        """What changed in the workspace since checkpoint `cid` (default: the latest)."""
        items = self._index()
        it = self._find(cid) if cid else (items[-1] if items else None)
        if it is None:
            return {"ok": False, "error": "no such checkpoint"}
        self._stage_all()
        code, stat = self._git("diff", "--cached", "--numstat", it["tree"])
        files = []
        for line in stat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                add, rem, name = parts
                files.append({"path": name, "added": int(add) if add.isdigit() else 0,
                              "removed": int(rem) if rem.isdigit() else 0, "binary": add == "-"})
        code, patch = self._git("diff", "--cached", "--no-color", "-U3", it["tree"])
        if len(patch) > 200000:
            patch = patch[:200000] + "\n... (diff cut at 200 KB)"
        return {"ok": True, "since": it["id"], "label": it.get("label", ""), "files": files, "diff": patch}

    def rewind(self, cid: str) -> dict:
        """Put the workspace files back as they were at checkpoint `cid`. A checkpoint of the
        current state is taken first, so this can be undone. Files created after `cid` are
        removed only if they are not ignored and the snapshot tracked their folder."""
        it = self._find(cid)
        if it is None:
            return {"ok": False, "error": "no such checkpoint"}
        safety = self.take("before rewinding to %s" % it["id"], kind="safety")
        if safety.get("error"):
            return {"ok": False, "error": safety["error"]}
        code, out = self._git("diff", "--name-only", "--diff-filter=A", it["tree"], safety["tree"])
        added = [n for n in out.splitlines() if n]
        code, out = self._git("read-tree", it["tree"])
        if code != 0:
            return {"ok": False, "error": out.strip()[:300]}
        code, out = self._git("checkout-index", "-a", "-f")
        if code != 0:
            return {"ok": False, "error": out.strip()[:300]}
        removed = []
        for name in added:
            target = (self.workspace / name)
            try:
                target.resolve().relative_to(self.workspace.resolve())
                if target.is_file():
                    target.unlink()
                    removed.append(name)
            except (OSError, ValueError):
                pass
        return {"ok": True, "rewound_to": it["id"], "undo": safety["id"], "removed": removed}


# --- @file mentions ------------------------------------------------------------------

_MENTION = re.compile(r"(?<![\w@])@([\w./\\-]+\.[A-Za-z0-9]{1,8}|[\w./\\-]+/)(?=[\s,;:!?)]|$)")


def expand_mentions(text: str, workspace: Path) -> tuple[str, list]:
    """Attach the files a message names with @path. Returns (new text, [paths attached]).
    Only files inside the workspace; folders get a listing; everything is size-capped."""
    root = Path(workspace).resolve()
    attached, blocks, total = [], [], 0
    for match in _MENTION.finditer(text or ""):
        rel = match.group(1).replace("\\", "/")
        if rel in attached:
            continue
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            continue
        if target.is_dir():
            names = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir()
                           if p.name not in SKIP_DIRS)[:200]
            body = "\n".join(names)
        elif target.is_file() and not target.name.endswith(BIG_SUFFIXES):
            try:
                body = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(body) > MENTION_MAX:
                body = body[:MENTION_MAX] + "\n... (cut: %d more characters)" % (len(body) - MENTION_MAX)
        else:
            continue
        if total + len(body) > MENTION_TOTAL:
            break
        total += len(body)
        attached.append(rel)
        blocks.append("--- @%s ---\n%s" % (rel, body))
    if not blocks:
        return text, []
    return (text + "\n\n[Files the user attached with @ - read them, they are the current contents]\n" +
            "\n\n".join(blocks)), attached


def search_files(workspace: Path, query: str = "", limit: int = 40) -> list:
    """Paths in the workspace matching `query` (all of its letters, in order), best first."""
    root = Path(workspace)
    q = (query or "").lower().replace("\\", "/")
    found = []
    start = time.monotonic()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        for name in filenames:
            rel = name if rel_dir == "." else rel_dir + "/" + name
            score = _fuzzy(q, rel.lower())
            if score is not None:
                found.append((score, rel))
        if time.monotonic() - start > 1.5 or len(found) > 5000:
            break
    found.sort(key=lambda x: (x[0], len(x[1])))
    return [rel for _, rel in found[:limit]]


def _fuzzy(q: str, text: str):
    if not q:
        return 0
    if q in text:
        return text.index(q) - 1000 + (0 if text.endswith(q) else 50)
    pos = 0
    gaps = 0
    for ch in q:
        nxt = text.find(ch, pos)
        if nxt < 0:
            return None
        gaps += nxt - pos
        pos = nxt + 1
    return gaps
