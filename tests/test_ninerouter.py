"""9Router as a LOKI provider (engine/ninerouter.py; owner 2026-10-18: "get 9router repo").

    python tests/test_ninerouter.py      (< 5 s, no network, no Node)

LOKI pins a 9Router past CVE-2026-62328 (<= 0.4.41 leaked every key to anyone who reached its port), installs it into
its own data folder, starts it on 127.0.0.1 only with no self-update, and routes to it like any OpenAI provider.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "tools"))
TMP = Path(tempfile.mkdtemp(prefix="loki-9r-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["NINEROUTER_PORT"] = "1"           # nothing ever answers on port 1: "not running"
import ninerouter  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


ver = tuple(int(x) for x in ninerouter.PACKAGE.split("@")[1].split("."))
check("the pinned 9Router is past CVE-2026-62328 (<= 0.4.41)", ver > (0, 4, 41), ninerouter.PACKAGE)
a = ninerouter.argv("9router")
check("started on loopback only, no browser, no self-update",
      a[a.index("--host") + 1] == "127.0.0.1" and "--no-browser" in a and "--skip-update" in a, a)
check("not installed: says how to install", "setup_extras.py 9router" in ninerouter.start()["why"])
bin_dir = ninerouter.prefix() / "node_modules" / ".bin"
bin_dir.mkdir(parents=True)
(bin_dir / ("9router.cmd" if sys.platform == "win32" else "9router")).write_text("", encoding="utf-8")
seen = []
out = ninerouter.start(popen=lambda argv, **kw: seen.append((argv, kw)))
check("installed and not running: LOKI starts it", out["started"] and seen and seen[0][0][0].endswith(("9router", "9router.cmd")), out)
check("detached from LOKI (its own session / no console)", "start_new_session" in seen[0][1] or "creationflags" in seen[0][1])
os.environ["LOKI_9ROUTER"] = "off"
check("LOKI_9ROUTER=off never starts it", not ninerouter.start(popen=lambda *a, **k: seen.append(1))["started"])
os.environ.pop("LOKI_9ROUTER")

import setup_extras  # noqa: E402
argv = setup_extras.ninerouter_argv("npm", ninerouter.prefix())
check("installed into LOKI's data folder at the pin (never global)", "--prefix" in argv and "-g" not in argv
      and ninerouter.PACKAGE in argv, argv)
check("installed only when named (not part of `all`)", "9router" in setup_extras.OPT_IN and "9router" not in setup_extras.STEPS)

src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("a model provider (OpenAI API, key from its dashboard)", '"9router": ModelConfig(' in src and '"9router": "NINEROUTER_API_KEY"' in src)
check("in smart routing", '"9router"' in src.split("SMART_ORDER = (", 1)[1].split(")", 1)[0])
import providers_catalog  # noqa: E402
card = providers_catalog.get("9router")
check("a card in Settings > Connections with https links", card and card["env"] == "NINEROUTER_API_KEY"
      and all(card[k].startswith("https://") for k in ("signup", "docs")), card)
import provider_health  # noqa: E402
check("without a 'loki' combo LOKI takes the first model 9Router lists",
      provider_health.replacement("9router", "loki", ["cc/claude-sonnet", "glm/glm-4.7"]) == "cc/claude-sonnet")
check("the engine starts it at boot", "ninerouter.start_background()" in (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8"))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
