"""Background removal never uses rembg's default model (bria-rmbg / RMBG-2.0, non-commercial) - 2026-10-26 licence
review. A fake rembg records which model was asked for. Seconds.

    python tests/test_cutout.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


from PIL import Image  # noqa: E402

asked, removed = [], []


def new_session(name):
    asked.append(name)
    if name == "birefnet-general-lite":
        raise RuntimeError("no download here")
    return types.SimpleNamespace(name=name)


def remove(img, session=None):
    removed.append(getattr(session, "name", None))
    return img.convert("RGBA")


sys.modules["rembg"] = types.SimpleNamespace(new_session=new_session, remove=remove)
import cutout  # noqa: E402

out = cutout.remove(Image.new("RGB", (8, 8)))
check("a cut-out always names an allowed model (BiRefNet, then the next licence-safe one)",
      out is not None and removed == ["birefnet-general"] and asked[:2] == ["birefnet-general-lite", "birefnet-general"], (asked, removed))
check("never without a model (rembg's default is bria-rmbg)", None not in removed and "bria-rmbg" not in asked)
check("bria-rmbg is forbidden even when asked for", "bria-rmbg" in cutout.FORBIDDEN and "bria-rmbg" not in cutout.ALLOWED)
bare = []
for f in (REPO / "engine").rglob("*.py"):
    text = f.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "rembg.remove(" in line and "session=session" not in line:
            bare.append("%s: %s" % (f.name, line.strip()[:90]))
check("no code calls rembg.remove without a named session", not bare, bare)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
