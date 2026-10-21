"""Forge's automatic seams (app/ui/forge_uvgami.js, ported from UVgami - GPL-3.0): runs the node suite
tests/js/test_forge_uvgami.js (hard-surface seams make disk shells that flatten without overlap, a cylinder opens
into disks, symmetric seams, rectify, reroute, similar islands, the flatten hook, inputs never changed). Skips
without node. Under 10 seconds.

    python tests/test_forge_uvgami.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


node = shutil.which("node")
if node:
    r = subprocess.run([node, str(REPO / "tests" / "js" / "test_forge_uvgami.js")], capture_output=True, text=True, timeout=40)
    print(r.stdout.strip())
    check("the automatic seams (forge_uvgami.js) pass their node suite (test_forge_uvgami.js)", r.returncode == 0, (r.stdout + r.stderr)[-400:])
else:
    print("SKIP: no node here")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
