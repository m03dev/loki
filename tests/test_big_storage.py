"""Everything big goes on Xero or LOKI's own drive, never the Mac's internal one (engine/big_storage.py). Owner
2026-10-26: "u crashed my mac with ur voice studio install ... everything should be in xero we dont have room".

    python tests/test_big_storage.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-big-"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


import big_storage  # noqa: E402

env = {"LOKI_DATA": str(TMP / "data")}
check("no Xero mounted: big things go to LOKI's data folder (its own drive)", big_storage.big_dir(env) == TMP / "data" / "big")
check("LOKI_BIG_DIR wins", big_storage.big_dir({"LOKI_BIG_DIR": str(TMP / "x")}) == TMP / "x")
done = big_storage.apply(env)
check("model, package and tool caches all point there", all(Path(env[k]).is_relative_to(TMP / "data" / "big") for k in
      ("HF_HOME", "TORCH_HOME", "PIP_CACHE_DIR", "UV_CACHE_DIR", "npm_config_cache", "LOKI_TOOLS_DIR")), env)
env2 = {"LOKI_DATA": str(TMP / "data"), "HF_HOME": "/mine"}
big_storage.apply(env2)
check("a location the owner set himself is kept", env2["HF_HOME"] == "/mine")
os.environ["LOKI_MIN_FREE_GB"] = "100000"
check("an installer refuses when the internal drive is low, and says where big things go",
      big_storage.low_space() and "not installing" in big_storage.install_note("VoiceStudio"))
import voice_studio  # noqa: E402
ran = []
r = voice_studio.tool({"action": "install"}, TMP, ask=lambda *a: True, run=lambda *a, **k: ran.append(a))
check("VoiceStudio is not installed onto a nearly full drive", not r["ok"] and not ran and "not installing" in r["error"], r)
os.environ["LOKI_MIN_FREE_GB"] = "0"
seen = {}


class P:
    returncode, stdout, stderr = 0, "ok", ""


voice_studio.tool({"action": "install"}, TMP, ask=lambda *a: True, run=lambda cmd, **k: (seen.update(k), P())[1])
check("when it is installed, its downloads are pointed at the big drive (HF_HOME)",
      "big" in str((seen.get("env") or {}).get("HF_HOME", "")) or "Xero" in str((seen.get("env") or {}).get("HF_HOME", "")),
      (seen.get("env") or {}).get("HF_HOME"))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
