"""Updates straight from the other machine when GitHub is not reachable (engine/peer_update.py; owner 2026-10-27:
"could we not use github for updates could we have alternatives" -> "both for now").

Real git repos, no network: a "PC" checkout one commit ahead serves a bundle; a "Mac" checkout whose GitHub remote is
gone fetches it into origin/master; a bundle from an unrelated history is refused (fast-forward only); asking with the
same commit gets "nothing newer"; and updater.check() falls back to a linked machine when the GitHub fetch fails.

    python tests/test_peer_update.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import peer_update  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def sh(cwd, *args):
    return subprocess.run(list(args), cwd=str(cwd), env=ENV, capture_output=True, text=True, check=True).stdout.strip()


T = Path(tempfile.mkdtemp(prefix="loki-peerupd-"))
origin = T / "origin.git"
sh(T, "git", "init", "-q", "--bare", "-b", "master", str(origin))
seed = T / "seed"
sh(T, "git", "clone", "-q", str(origin), str(seed))
(seed / "a.txt").write_text("1")
sh(seed, "git", "add", "-A")
sh(seed, "git", "commit", "-qm", "one")
sh(seed, "git", "push", "-q", "origin", "HEAD:master")
pc, mac = T / "pc", T / "mac"
sh(T, "git", "clone", "-q", str(origin), str(pc))
sh(T, "git", "clone", "-q", str(origin), str(mac))
(pc / "a.txt").write_text("2")
sh(pc, "git", "commit", "-qam", "two (shipped from the PC)")
pc_head = sh(pc, "git", "rev-parse", "HEAD")
mac_have = sh(mac, "git", "rev-parse", "origin/master")

b = peer_update.make_bundle(pc, mac_have)
check("the PC serves only what the Mac lacks", b["ok"] and b["head"] == pc_head and b["bundle"], b.get("error"))
ok, msg = peer_update.apply_bundle(mac, b["bundle"])
check("the Mac fetches it into origin/master", ok and sh(mac, "git", "rev-parse", "origin/master") == pc_head, msg)
check("... and its own work and branch are untouched", sh(mac, "git", "rev-parse", "HEAD") == mac_have)
check("asking again with the same commit: nothing newer", peer_update.make_bundle(pc, pc_head)["bundle"] == "")

other = T / "other"
sh(T, "git", "init", "-q", "-b", "master", str(other))
(other / "x.txt").write_text("evil")
sh(other, "git", "add", "-A")
sh(other, "git", "commit", "-qm", "unrelated")
bad = peer_update.make_bundle(other)
ok, msg = peer_update.apply_bundle(mac, bad["bundle"])
check("a bundle from another history is refused (fast-forward only)", not ok and sh(mac, "git", "rev-parse", "origin/master") == pc_head, msg)

# updater.check(): GitHub gone -> a linked machine
(pc / "a.txt").write_text("3")
sh(pc, "git", "commit", "-qam", "three")
sh(mac, "git", "remote", "set-url", "origin", str(T / "gone.git"))
import updater  # noqa: E402
import peers  # noqa: E402
real_peers, real_call = peers.peers, peers.call
peers.peers = lambda env=None: [{"name": "pc", "url": "http://127.0.0.1:1"}]
peers.call = lambda peer, method, path, payload=None, **k: peer_update.make_bundle(pc, (payload or {}).get("have", ""))
try:
    t0 = time.time()
    st = updater.check(mac, timeout=20)
    check("updater.check(): GitHub unreachable -> takes the update from the PC", st.get("ok") and st.get("behind") == 2, st)
    os.environ["LOKI_PEER_UPDATES"] = "off"
    st = updater.check(mac, timeout=20)
    check("... LOKI_PEER_UPDATES=off: the plain GitHub error", not st.get("ok"), st)
finally:
    peers.peers, peers.call = real_peers, real_call
    os.environ.pop("LOKI_PEER_UPDATES", None)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
