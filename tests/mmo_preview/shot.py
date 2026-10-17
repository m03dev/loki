"""Screenshots of LOKI World's MMO mode in headless Chromium (Playwright, SwiftShader WebGL).

    python tests/mmo_preview/shot.py [out_dir]

Starts serve.py on a free port, opens the preview, walks the character with real key presses
and saves PNGs. Prints console errors. Needs Playwright + Chromium (not part of the suites).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import serve  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    srv = serve.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/preview/preview.html" % srv.server_address[1]
    errors: list = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for engine in ("babylon", "classic"):
            page = browser.new_page(viewport={"width": 1100, "height": 680})
            page.on("console", lambda m: m.type == "error" and errors.append("%s: %s" % (engine, m.text)))
            page.on("pageerror", lambda e: errors.append("%s: %s" % (engine, e)))
            page.goto(url + "?engine=" + engine)
            page.wait_for_function("window.previewReady === true", timeout=60000)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(out / ("mmo_%s_start.png" % engine)))
            page.click("#world-panel-canvas", position={"x": 550, "y": 600})
            page.keyboard.down("w")
            page.wait_for_timeout(1400)
            page.keyboard.up("w")
            page.keyboard.down("d")
            page.wait_for_timeout(500)
            page.keyboard.up("d")
            page.keyboard.press(" ")
            page.wait_for_timeout(150)
            page.screenshot(path=str(out / ("mmo_%s_walked.png" % engine)))
            pos = page.evaluate("[MMO.player.x, MMO.player.z, MMO.player.zone, MMO.active, World.views.panel.perf.engine || 'classic']")
            print(engine, "player after walking:", pos)
            page.click(".mmo-toggle")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(out / ("mmo_%s_spectate.png" % engine)))
            page.close()
        browser.close()
    srv.shutdown()
    for e in errors:
        print("CONSOLE ERROR", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("mmo_shots")))
