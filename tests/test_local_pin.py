"""The local model the owner picks is kept in LOKI's .env (survives restarts, reaches background jobs) - the PC,
2026-10-26. Runs without LOKI's venv: the function is taken out of engine/loki.py and run on its own.

    python tests/test_local_pin.py
"""
from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-pin-"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "write_env_setting")
ns = {"re": re, "os": os, "env_file_path": lambda: TMP / ".env"}
exec(compile(ast.Module([fn], []), "loki.py", "exec"), ns)  # noqa: S102 - LOKI's own code
w = ns["write_env_setting"]
(TMP / ".env").write_text("NVIDIA_API_KEY=x\nLOKI_LOCAL_MODEL=old\n", encoding="utf-8")
check("the pick is written", w("LOKI_LOCAL_MODEL", "loki-huihui_ai-qwen3-abliterated-8b:latest"))
text = (TMP / ".env").read_text(encoding="utf-8")
check("one line, the new value, keys untouched", text.count("LOKI_LOCAL_MODEL=") == 1 and "abliterated" in text
      and "NVIDIA_API_KEY=x" in text, text)
check("live in this process too", os.environ.get("LOKI_LOCAL_MODEL", "").startswith("loki-huihui_ai"))
w("LOKI_LOCAL_MODEL", "")
check("an empty pick removes it", "LOKI_LOCAL_MODEL" not in (TMP / ".env").read_text() and "LOKI_LOCAL_MODEL" not in os.environ)
check("a bad name is refused", not w("bad name", "x"))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
