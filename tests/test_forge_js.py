"""Forge's kernel tests written in JavaScript (tests/js/*.js: flatten, soft selection, multi-object edit, Edit Mesh,
UVs, levels, bake ...), run with node so tools/ship.py checks them too. Skips when node is not installed. Under a minute.

    python tests/test_forge_js.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
t0 = time.time()
node = shutil.which("node")
if not node:
    print("SKIP: no node here\n\n0 passed, 0 failed")
    sys.exit(0)
passed, failed = [], []
for f in sorted((REPO / "tests" / "js").glob("test_*.js")):
    r = subprocess.run([node, str(f)], cwd=str(REPO), capture_output=True, text=True, timeout=50)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    ok = r.returncode == 0
    (passed if ok else failed).append(f.name)
    print(("  PASS " if ok else "  FAIL ") + f.name + "  " + tail[0] + ("" if ok else "\n" + (r.stdout + r.stderr)[-800:]))
ok_time = time.time() - t0 < 60
print("  %s this suite stays under 60 s (%.1f s)" % ("PASS" if ok_time else "FAIL", time.time() - t0))
print("\n%d passed, %d failed" % (len(passed) + ok_time, len(failed) + (not ok_time)))
sys.exit(1 if failed or not ok_time else 0)
