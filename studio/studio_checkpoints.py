"""Checkpoints: every turn of a Studio session can be undone.

A checkpoint is the state of the files at the START of a turn (one owner message and everything
the agent did for it). "Undo turn N" puts the files back exactly as they were before turn N
(turns N, N+1, ... are all undone), and the editor-side changes of those turns are undone with
the editor's own UndoRedo (the plugin does that part).

Two kinds of store, picked by the session:
  git    LOKI's code (a session worktree): a snapshot COMMIT of the whole worktree - tracked,
         changed and new files, .gitignore respected - made with a throwaway index, so the
         branch, the real index and the working tree are never touched; kept under
         refs/studio-checkpoints/<session>/<turn>. Restoring writes that tree back and removes
         files the turn created. Catches every change, including ones made by the test runs.
  files  a Godot project (often not a git repo, or the owner's own repo we must not write refs
         into): before the agent's first write to a file in a turn, that file's bytes (or
         "it did not exist") are saved under harness_data/studio/sessions/<id>/checkpoints/.
         Restoring writes the saved bytes back / deletes the files that turn created.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def _git(cwd: Path, *args: str, env_extra: dict | None = None, timeout: float = 120.0) -> tuple:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    env.update(env_extra or {})
    try:
        p = subprocess.run(["git", "-c", "user.email=studio@loki", "-c", "user.name=LOKI Studio", *args], cwd=str(cwd),
                           capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def is_git_tree(root: Path) -> bool:
    return _git(Path(root), "rev-parse", "--is-inside-work-tree")[1] == "true"


class Checkpoints:
    def __init__(self, store: Path, root: Path, kind: str = "", session_id: str = "s"):
        self.store = Path(store)
        self.root = Path(root).resolve()
        self.kind = kind or ("git" if is_git_tree(self.root) else "files")
        self.sid = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        self.store.mkdir(parents=True, exist_ok=True)
        self.index_file = self.store / "checkpoints.json"

    # ------------------------------------------------------------- the list
    def list(self) -> list:
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, rows: list) -> None:
        tmp = self.index_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        os.replace(tmp, self.index_file)

    def current(self) -> dict | None:
        rows = self.list()
        return rows[-1] if rows else None

    # ------------------------------------------------------------- git snapshots
    def _snapshot_tree(self) -> tuple:
        """(commit, error) of the worktree as it is now, without touching its index or branch."""
        with tempfile.TemporaryDirectory(prefix="loki-cp-") as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            head = _git(self.root, "rev-parse", "--verify", "-q", "HEAD")[1]
            if head:
                _git(self.root, "read-tree", head, env_extra=env)
            code, _, err = _git(self.root, "add", "-A", ".", env_extra=env)
            if code != 0:
                return "", err
            code, tree, err = _git(self.root, "write-tree", env_extra=env)
            if code != 0:
                return "", err
        args = ["commit-tree", tree, "-m", "LOKI Studio checkpoint"]
        if head:
            args[2:2] = ["-p", head]
        code, commit, err = _git(self.root, *args)
        return (commit, "") if code == 0 else ("", err)

    def _files_now(self) -> set:
        with tempfile.TemporaryDirectory(prefix="loki-cp-") as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            _git(self.root, "add", "-A", ".", env_extra=env)
            return set(_git(self.root, "ls-files", env_extra=env)[1].splitlines())

    def _restore_git(self, commit: str) -> list:
        before = self._files_now()
        target = set(_git(self.root, "ls-tree", "-r", "--name-only", commit)[1].splitlines())
        changed = []
        for rel in sorted(before - target):
            p = self.root / rel
            try:
                p.unlink()
                changed.append(rel)
            except OSError:
                pass
        with tempfile.TemporaryDirectory(prefix="loki-cp-") as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            _git(self.root, "read-tree", commit, env_extra=env)
            diff = _git(self.root, "diff", "--name-only", env_extra=env)[1].splitlines()
            _git(self.root, "checkout-index", "-a", "-f", env_extra=env)
        return sorted(set(changed) | set(diff))

    # ------------------------------------------------------------- the API
    def begin(self, turn: int, label: str = "") -> dict:
        """The checkpoint for the start of `turn`."""
        rows = [r for r in self.list() if r["turn"] < turn]
        row = {"turn": int(turn), "t": time.time(), "label": str(label)[:120], "kind": self.kind, "files": {}}
        if self.kind == "git":
            commit, err = self._snapshot_tree()
            row["commit"] = commit
            if commit:
                _git(self.root, "update-ref", "refs/studio-checkpoints/%s/%d" % (self.sid, turn), commit)
            else:
                row["error"] = err[-300:]
        else:
            (self.store / ("turn-%d" % turn)).mkdir(parents=True, exist_ok=True)
        rows.append(row)
        self._save(rows)
        return row

    def before_write(self, path: Path) -> None:
        """Files mode: remember `path` as it was before this turn first changed it."""
        if self.kind != "files":
            return
        rows = self.list()
        if not rows:
            return
        row = rows[-1]
        try:
            rel = Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return
        if rel in row["files"]:
            return
        folder = self.store / ("turn-%d" % row["turn"])
        folder.mkdir(parents=True, exist_ok=True)
        src = self.root / rel
        if src.is_file():
            name = "%04d.bin" % len(row["files"])
            shutil.copyfile(src, folder / name)
            row["files"][rel] = name
        else:
            row["files"][rel] = None          # it did not exist: undo deletes it
        self._save(rows)

    def changed_in(self, turn: int) -> list:
        row = next((r for r in self.list() if r["turn"] == turn), None)
        return sorted((row or {}).get("files", {}))

    def undo(self, turn: int) -> dict:
        """Put the files back as they were at the start of `turn`; forget that turn and later ones."""
        rows = self.list()
        keep = [r for r in rows if r["turn"] < turn]
        undo = [r for r in rows if r["turn"] >= turn]
        if not undo:
            return {"ok": False, "error": "no checkpoint for turn %d" % turn}
        changed: list = []
        if self.kind == "git":
            first = undo[0]
            if not first.get("commit"):
                return {"ok": False, "error": "that checkpoint has no snapshot (%s)" % first.get("error", "")}
            changed = self._restore_git(first["commit"])
            for r in undo:
                _git(self.root, "update-ref", "-d", "refs/studio-checkpoints/%s/%d" % (self.sid, r["turn"]))
        else:
            for r in reversed(undo):
                folder = self.store / ("turn-%d" % r["turn"])
                for rel, name in r["files"].items():
                    target = self.root / rel
                    try:
                        if name is None:
                            if target.exists():
                                target.unlink()
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(folder / name, target)
                        changed.append(rel)
                    except OSError:
                        pass
                shutil.rmtree(folder, ignore_errors=True)
        self._save(keep)
        return {"ok": True, "turn": turn, "undone_turns": [r["turn"] for r in undo], "files": sorted(set(changed))}
