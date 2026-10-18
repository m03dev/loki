"""LOKI installs what it needs by itself (engine/auto_setup.py).

    python tests/test_auto_setup.py      (< 5 s, nothing is installed for real)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import auto_setup  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


TMP = Path(tempfile.mkdtemp(prefix="loki-autosetup-"))
check("the default is 'recommended'", auto_setup.level({}) == "recommended")
check("an unknown value falls back to recommended", auto_setup.level({"LOKI_AUTO_SETUP": "lots"}) == "recommended")
check("off installs nothing", auto_setup.wanted("off") == [])
light = auto_setup.wanted("recommended", apple_silicon=False, nvidia=True)
check("recommended = the light add-ons + CADCraft, no big model downloads",
      "documents" in light and "cadcraft" in light and "local-image" not in light and "local-video" not in light, light)
check("an Apple-silicon Mac also gets MLX", "mlx" in auto_setup.wanted("recommended", apple_silicon=True, nvidia=False))
check("everything on the NVIDIA PC adds the local picture and video makers",
      {"local-image", "local-video"} <= set(auto_setup.wanted("everything", apple_silicon=False, nvidia=True)))
check("no NVIDIA GPU: no local video maker", "local-video" not in auto_setup.wanted("everything", apple_silicon=True, nvidia=False))

done, clock = [], [1000.0]
present = {"documents", "ocr"}
results = {"media": {"ok": False, "error": "pip failed: no network"}}
state = auto_setup.run(TMP, "recommended", install=lambda n: (done.append(n), results.get(n, {"ok": True}))[1],
                       installed=lambda n: n in present, sleep=lambda s: None, now=lambda: clock[0])
check("only what is missing is installed, one at a time, in order",
      done == [n for n in auto_setup.wanted("recommended") if n not in present], done)
check("a failure is reported with its reason", state["failed"].get("media", "").startswith("pip failed"), state["failed"])
check("it is not running any more", not state["running"] and state["current"] == "")
record = json.loads((TMP / "auto_setup.json").read_text())
check("the failure is remembered", "media" in record["failed"])

done.clear()
clock[0] += 60
state = auto_setup.run(TMP, "recommended", install=lambda n: (done.append(n), {"ok": True})[1],
                       installed=lambda n: n in present, sleep=lambda s: None, now=lambda: clock[0])
check("a recent failure is not retried in a loop", "media" not in done and "media" in state["skipped"], (done, state["skipped"]))
clock[0] += auto_setup.RETRY_AFTER_S + 1
done.clear()
auto_setup.run(TMP, "recommended", install=lambda n: (done.append(n), {"ok": True})[1],
               installed=lambda n: n in present, sleep=lambda s: None, now=lambda: clock[0])
check("it is tried again on a later start", "media" in done, done)

waits = []
busy = iter([True, True, False] + [False] * 50)
auto_setup.run(TMP, "recommended", install=lambda n: {"ok": True}, installed=lambda n: n != "documents",
               busy=lambda: next(busy), sleep=lambda s: waits.append(s), now=lambda: clock[0])
check("it waits while LOKI is answering a request", len(waits) == 2, waits)

bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine starts it after the window is ready, and the window can start it",
      "auto_setup.start(" in bridge and '"/autosetup/start"' in bridge and '"/autosetup/status"' in bridge)
js = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
check("Settings > Add-ons shows its progress and the two buttons", "autoSetupBox" in js and "Install what LOKI needs now" in js)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
