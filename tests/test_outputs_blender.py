"""Output names, Blender MCP and Home's scroll bar (owner 2026-10-26: "get blender mcp going on both ...
orangize output files names better ... mac scroll bar at home doesnt work but windows works"). Offline: Blender
and uvx are faked, nothing is installed or started.

    python tests/test_outputs_blender.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-outnames-"))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import out_names  # noqa: E402

AT = 1793037600.0
n = out_names.name("knight with sword and shield, professional concept art", "png", at=AT)
check("subject words first, filler and style words dropped", n.startswith("knight-sword-shield_"), n)
check("date stays in the name (YYYYMMDD-HHMM)", n.endswith(".png") and len(n.split("_")[1].split(".")[0]) == 13, n)
long = out_names.subject("painterly fantasy game concept art, wide cinematic shot of an ancient mountain shrine")
check("never cut mid-word ('cinemati')", long == "ancient-mountain-shrine", long)
check("all-filler prompt keeps its own words", out_names.subject("a beautiful concept art") != "untitled")
check("empty prompt -> fallback", out_names.subject("", "image") == "image")
check("a tag names the variant", out_names.name("fox", "png", tag="sprite64", at=AT).endswith("_sprite64.png"))
p1 = out_names.path(TMP / "images", "red fox", "png", at=AT)
p1.write_bytes(b"x")
p2 = out_names.path(TMP / "images", "red fox", "png", at=AT)
check("a taken name gets _2", p2.name == p1.stem + "_2.png", p2.name)
for fname, want in (("knight-sword-shield_20261026-1021_sprite64-x8.png", "knight sword shield"),
                    ("20261026-022217-red-fox-cub.jpg", "red fox cub"),
                    ("fox_20261026-1021_2.glb", "fox")):
    check("display name of %s" % fname, out_names.display_name(fname) == want, out_names.display_name(fname))
import creations  # noqa: E402
check("Home titles read new names", creations.title_of("knight-sword-shield_20261026-1021.png") == "Knight sword shield",
      creations.title_of("knight-sword-shield_20261026-1021.png"))

# every maker uses the one rule (no hand-rolled "%Y%m%d-%H%M%S-<slug>" names left in the makers)
makers = ["creative.py", "forge3d.py", "turnaround.py", "voice.py", "runners/imagegen.py"]
old = [m for m in makers if 'strftime("%Y%m%d-%H%M%S")' in (REPO / "engine" / m).read_text(encoding="utf-8")
       and "out_names" not in (REPO / "engine" / m).read_text(encoding="utf-8")]
check("makers name files through out_names", not old, old)

# ---- Blender MCP
import blender_link  # noqa: E402

cfg = json.loads((REPO / "engine" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
b = cfg.get("blender") or {}
check("blender MCP server registered, pinned to the add-on's commit (same protocol)", b.get("command") == "uvx"
      and b.get("args") == ["--from", "git+https://github.com/ahujasid/mcp-for-blender@febcd90", "mcp-for-blender"], b)
proto = [ln for ln in (REPO / "contrib/blender_mcp/addon.py").read_text(encoding="utf-8").splitlines()
         if ln.startswith("ADDON_PROTOCOL_VERSION")]
check("vendored add-on speaks protocol 15 (the pinned server's EXPECTED_ADDON_PROTOCOL_VERSION)",
      proto == ["ADDON_PROTOCOL_VERSION = 15"], proto)
import ast  # noqa: E402
# the Blender bridge itself (loader, core, setup, run, proof): tests/test_blender_bridge.py

try:
    import loki  # noqa: E402  pylint: disable=wrong-import-position
except ImportError as exc:     # a cloud session without LOKI's venv: the machines run this part
    print("SKIP the MCP gate check (%s)" % exc)
    loki = None
if loki:
    blender_link.find_blender = lambda: ""
    check("MCP gate skips blender when it is not installed",
          "found nothing" in loki._server_skip_reason({"requires_check": "blender_link.find_blender"}, "blender"))
    blender_link.find_blender = lambda: "/x/blender"
    check("MCP gate passes when Blender is there",
          loki._server_skip_reason({"requires_check": "blender_link.find_blender"}, "blender") == "")


# ---- Home's scroll bar on the Mac (WebKit)
css = (REPO / "app/ui/home_layout.css").read_text(encoding="utf-8")
check("Home pane has a WebKit scroll bar you can grab", ".home-hub::-webkit-scrollbar {" in css
      and ".home-hub::-webkit-scrollbar-thumb {" in css)
check("the split's row is the window's height (WebKit sized it to content)", "grid-template-rows: minmax(0, 1fr); }" in css)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
