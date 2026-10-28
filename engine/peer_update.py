"""Updates straight from the other machine, GitHub as the backup (owner 2026-10-27: "could we not use github for
updates could we have alternatives" -> "both for now").

When a machine cannot get master from GitHub (down, signed out, blocked), it asks its linked machines for theirs:
  POST /peer/update/bundle {"have": <my commit>}  ->  {"ok", "head", "bundle": base64 git bundle of HEAD}
The asking machine verifies the bundle and fetches it into origin/master FAST-FORWARD ONLY, so a peer can never move
it backwards or onto another history, and the usual update path (pre-flight, trial start, restart) does the rest.
Requests and answers are signed by peers.py, so only our own machines can serve an update.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from pathlib import Path

MAX_BUNDLE = 48 * 1024 * 1024


def _git(repo: Path, *args, timeout: float = 120.0) -> tuple:
    try:
        p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def make_bundle(repo: Path, have: str = "") -> dict:
    """What this machine runs (HEAD), as a bundle; only the commits `have` lacks when we know `have`."""
    code, head = _git(repo, "rev-parse", "HEAD")
    if code:
        return {"ok": False, "error": "not a git checkout"}
    head = head.strip()
    if have and head.startswith(have.strip()):
        return {"ok": True, "head": head, "bundle": ""}         # nothing newer here
    fd, path = tempfile.mkstemp(suffix=".bundle")
    os.close(fd)
    try:
        args = ["bundle", "create", path, "HEAD"]
        if have and _git(repo, "cat-file", "-e", have.strip() + "^{commit}")[0] == 0 \
                and _git(repo, "merge-base", "--is-ancestor", have.strip(), "HEAD")[0] == 0:
            args.append("^" + have.strip())
        code, out = _git(repo, *args)
        if code:
            return {"ok": False, "error": "bundle failed: " + out[-200:]}
        size = Path(path).stat().st_size
        if size > MAX_BUNDLE:
            return {"ok": False, "error": "update too big to send directly (%d MB)" % (size >> 20)}
        return {"ok": True, "head": head, "bundle": base64.b64encode(Path(path).read_bytes()).decode("ascii")}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def apply_bundle(repo: Path, data: str, branch: str = "master") -> tuple:
    """Fetch a received bundle into origin/<branch>, fast-forward only. (ok, message)."""
    fd, path = tempfile.mkstemp(suffix=".bundle")
    os.close(fd)
    try:
        Path(path).write_bytes(base64.b64decode(data))
        code, out = _git(repo, "bundle", "verify", path)
        if code:
            return False, "the bundle does not fit this checkout: " + out[-200:]
        # no "+": git refuses to move origin/master unless it is a fast-forward
        code, out = _git(repo, "fetch", "--quiet", path, "HEAD:refs/remotes/origin/" + branch)
        if code:
            return False, "not a fast-forward of origin/%s - refused (%s)" % (branch, out[-160:])
        return True, "fetched from a linked machine"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def fetch_from_peers(repo: Path, branch: str = "master", env: dict | None = None) -> tuple:
    """Try every linked machine; (ok, message). Used when fetching from GitHub failed."""
    import peers  # pylint: disable=import-outside-toplevel
    _, have = _git(repo, "rev-parse", "refs/remotes/origin/" + branch)
    reasons = []
    for peer in peers.peers(env):
        try:
            got = peers.call(peer, "POST", "/peer/update/bundle", {"have": have.strip()}, env=env, timeout=90.0)
        except peers.PeerError as exc:
            reasons.append(str(exc))
            continue
        if not got.get("ok"):
            reasons.append("%s: %s" % (peer["name"], got.get("error", "no update")))
            continue
        if not got.get("bundle"):
            reasons.append("%s has nothing newer" % peer["name"])
            continue
        ok, msg = apply_bundle(repo, got["bundle"], branch)
        if ok:
            return True, "%s (%s)" % (msg, peer["name"])
        reasons.append("%s: %s" % (peer["name"], msg))
    return False, "; ".join(reasons) or "no linked machine"
