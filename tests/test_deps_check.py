"""engine/deps_check.py: a required package that is missing (a failed pip run during an update) is installed at the
next start, only the missing ones, never a loop. No network: the installer is faked.

    python tests/test_deps_check.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
import deps_check  # noqa: E402

PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


tmp = Path(tempfile.mkdtemp(prefix="loki-deps-"))
(tmp / "engine").mkdir()
(tmp / "app").mkdir()
(tmp / "engine" / "requirements.txt").write_text("# LOKI\npip>=1.0\nno-such-package-loki-test>=1.0\nextras-pkg-loki[default]>=2\n", encoding="utf-8")
(tmp / "app" / "requirements.txt").write_text("pip>=999.0\n", encoding="utf-8")
reqs = deps_check.requirements(tmp)
check("reads both files, skips comments", [r[1] for r in reqs] == ["pip", "no-such-package-loki-test", "extras-pkg-loki", "pip"], reqs)
need = deps_check.missing(tmp)
check("an installed package is not missing", "pip>=1.0" not in need, need)
check("a package that is not installed is missing", "no-such-package-loki-test>=1.0" in need)
check("... with its extras kept", "extras-pkg-loki[default]>=2" in need)
check("an installed package older than >= is missing", "pip>=999.0" in need)
asked = []
result = deps_check.check_and_install(tmp, run=lambda lines: (asked.append(list(lines)) or (False, "offline")))
check("only the missing lines go to pip", asked == [need], asked)
check("a failure is reported, not hidden", result["failed"] == "offline" and not result["ok"], result)
check("the real repo's requirement files parse", len(deps_check.requirements()) >= 5)
check("this suite stays under 60 s", time.time() - T0 < 60)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
