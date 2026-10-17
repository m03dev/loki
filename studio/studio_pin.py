"""LOKI Studio's pinned, known-good copy of LOKI.

Studio is the tool that repairs LOKI, so a bad LOKI commit must not break Studio. Studio runs
its own code AND the engine modules it uses (loki_mcp, ratelimit, updater, policy) from a
separate git worktree of the checkout, detached at a commit known to be good:

    harness_data/studio/pinned       the pinned copy (git worktree --detach)
    harness_data/studio/pin.json     {commit, at, tried: {commit: why it was refused}}

Which commit: the updater's last good version on this machine (engine/updater.py health
"last_good" - the commit whose engine AND window came up), else the checkout's HEAD the very
first time. The pin moves forward only when the candidate passes Studio's own checks in a
throwaway worktree (`studio/studio_app.py --self-test` and `tools/ship.py --check --only
test_studio`); a candidate that fails is remembered and not tried again. The move happens in
the background and takes effect on Studio's next start. A candidate without studio/ in it
(older than Studio) is never pinned; Studio then runs straight from the checkout.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import studio_paths
import updater


def pin_dir(data: Path | None = None) -> Path:
    return Path(data or studio_paths.data()) / "studio" / "pinned"


def _record_file(data: Path | None = None) -> Path:
    return Path(data or studio_paths.data()) / "studio" / "pin.json"


def record(data: Path | None = None) -> dict:
    try:
        value = json.loads(_record_file(data).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(rec: dict, data: Path | None = None) -> None:
    path = _record_file(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1), encoding="utf-8")


def candidate(repo: Path) -> str:
    """The commit Studio should run on: the last good one here, else HEAD."""
    good = str(updater.health(repo).get("last_good") or "").strip()
    if good:
        code, out = updater.git(repo, "rev-parse", "--verify", "--quiet", good + "^{commit}")
        if code == 0 and out.strip():
            return out.strip()
    code, out = updater.git(repo, "rev-parse", "HEAD")
    return out.strip() if code == 0 else ""


def _has_studio(repo: Path, commit: str) -> bool:
    code, _ = updater.git(repo, "cat-file", "-e", "%s:studio/studio_app.py" % commit)
    return code == 0


def pinned_commit(data: Path | None = None) -> str:
    tree = pin_dir(data)
    if not (tree / ".git").exists():
        return ""
    code, out = updater.git(tree, "rev-parse", "HEAD")
    return out.strip() if code == 0 else ""


def usable(data: Path | None = None) -> Path | None:
    """The pinned copy's studio_app.py when there is a pinned copy that has Studio in it."""
    app = pin_dir(data) / "studio" / "studio_app.py"
    return app if app.is_file() and (pin_dir(data) / "engine" / "loki_mcp.py").is_file() else None


def ensure(repo: Path, data: Path | None = None) -> dict:
    """Make the pinned copy if there is none yet (at the candidate commit, when it has Studio)."""
    tree = pin_dir(data)
    if (tree / ".git").exists():
        rec = record(data)
        nxt, have = str(rec.get("next") or ""), pinned_commit(data)
        if nxt and nxt != have:   # a move refresh() checked last time: apply it now, before the copy runs
            code, out = updater.git(tree, "checkout", "--detach", "--force", nxt)
            if code == 0:
                rec.update(commit=nxt, previous=have, at=time.time())
                rec.pop("next", None)
                _save(rec, data)
                return {"ok": True, "commit": nxt, "note": "pin moved %s -> %s" % (have[:12], nxt[:12])}
            rec.pop("next", None)
            _save(rec, data)
        return {"ok": True, "commit": pinned_commit(data), "note": "pinned copy present"}
    want = candidate(repo)
    if not want or not _has_studio(repo, want):
        return {"ok": False, "note": "no good commit with Studio in it yet; Studio runs from the checkout"}
    tree.parent.mkdir(parents=True, exist_ok=True)
    if tree.exists():
        shutil.rmtree(tree, ignore_errors=True)
    updater.git(repo, "worktree", "prune")
    code, out = updater.git(repo, "worktree", "add", "--detach", "--force", str(tree), want, timeout=120)
    if code != 0:
        return {"ok": False, "note": "could not make the pinned copy: " + out[-200:]}
    rec = record(data)
    rec.update(commit=want, at=time.time())
    _save(rec, data)
    return {"ok": True, "commit": want, "note": "pinned %s" % want[:12]}


def check_candidate(repo: Path, commit: str, python: str = "", timeout: float = 900.0) -> tuple:
    """(ok, why): does `commit`'s Studio pass its own checks? Run in a throwaway worktree."""
    tmp = Path(tempfile.mkdtemp(prefix="loki-studio-pin-"))
    tree = tmp / "tree"
    python = python or sys.executable
    try:
        code, out = updater.git(repo, "worktree", "add", "--detach", "--force", str(tree), commit, timeout=120)
        if code != 0:
            return False, "could not check it out: " + out[-160:]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LOKI_", "HARNESS_"))}
        env.update(LOKI_DATA=str(tmp / "data"), LOKI_STUDIO_NO_PIN="1", PYTHONDONTWRITEBYTECODE="1")
        steps = [[python, str(tree / "studio" / "studio_app.py"), "--self-test"]]
        if (tree / "tests" / "test_studio.py").is_file():
            steps.append([python, str(tree / "tools" / "ship.py"), "--check", "--only", "test_studio", "--repo", str(tree)])
        for argv in steps:
            try:
                proc = subprocess.run(argv, cwd=str(tree), env=env, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return False, "%s did not finish in %ds" % (Path(argv[1]).name, timeout)
            text = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if proc.returncode != 0:
                return False, "%s failed: %s" % (Path(argv[1]).name, " ".join(text.split())[-300:])
        return True, "passed"
    finally:
        updater.git(repo, "worktree", "remove", "--force", str(tree))
        updater.git(repo, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)


def refresh(repo: Path, data: Path | None = None, checker=None, python: str = "") -> dict:
    """Move the pin to the newest good commit when it passes Studio's checks. Takes effect next start."""
    checker = checker or (lambda r, c: check_candidate(r, c, python))
    ensured = ensure(repo, data)
    if not ensured.get("ok"):
        return ensured
    want = candidate(repo)
    have = pinned_commit(data)
    rec = record(data)
    if not want or want == have:
        return {"ok": True, "commit": have, "note": "the pin is current"}
    if rec.get("next") == want:
        return {"ok": True, "commit": have, "next": want, "note": "the pin moves to %s on Studio's next start" % want[:12]}
    if want in (rec.get("tried") or {}):
        return {"ok": True, "commit": have, "note": "%s was refused before: %s" % (want[:12], rec["tried"][want])}
    if not _has_studio(repo, want):
        return {"ok": True, "commit": have, "note": "%s has no Studio in it; staying on %s" % (want[:12], have[:12])}
    ok, why = checker(repo, want)
    if not ok:
        tried = dict(rec.get("tried") or {})
        tried[want] = why[:300]
        rec["tried"] = dict(list(tried.items())[-20:])
        _save(rec, data)
        return {"ok": False, "commit": have, "note": "kept %s: %s failed Studio's checks (%s)" % (have[:12], want[:12], why)}
    # Not moved under the running Studio: ensure() applies it at the next start.
    rec["next"] = want
    _save(rec, data)
    return {"ok": True, "commit": have, "next": want,
            "note": "%s passed Studio's checks; the pin moves to it on Studio's next start" % want[:12]}
