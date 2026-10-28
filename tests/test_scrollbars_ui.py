"""LOKI's own scroll bars must actually be drawn on the Mac (owner 2026-10-27: "the middle scroll bar doesnt show right
can't scroll down"; 2026-10-26: "mac scroll bar at home doesnt work but windows works").

Root cause: the Mac window is Apple's WebKit (pywebview). Once an element has the standard `scrollbar-width` or
`scrollbar-color`, WebKit - and Chromium 121+, which is why this can be checked headless here - ignores every
::-webkit-scrollbar rule and falls back to the platform bar: on macOS an overlay that hides until you scroll. glass.css set
`scrollbar-width: thin` on every element, so Home's 12px always-there bar was never drawn on the Mac.

Checks:
  * static: no scrollbar-width / scrollbar-color outside `@supports not selector(::-webkit-scrollbar)` in LOKI's UI css
    (Forge's deliberate hover-only bars and `scrollbar-width: none` excepted);
  * live (headless Chromium, the real index.html, engine stubbed): Home's column, the chat transcript - computed
    scrollbar-width/-color are `auto`, the bar is LOKI's 12px (not the 15px native one), and Home scrolls to its last card
    on a vertical screen, stacked, in a chat.

    python tests/test_scrollbars_ui.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def strip_supports(css: str) -> str:
    """css with every `@supports not selector(::-webkit-scrollbar) { ... }` block (balanced braces) removed."""
    out, i = [], 0
    for m in re.finditer(r"@supports\s+not\s+selector\(::-webkit-scrollbar\)\s*\{", css):
        if m.start() < i:
            continue
        out.append(css[i:m.start()])
        depth, j = 1, m.end()
        while j < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        i = j
    out.append(css[i:])
    return re.sub(r"/\*.*?\*/", "", "".join(out), flags=re.S)


bad = []
for f in sorted(UI.glob("*.css")):
    if f.name.startswith("forge"):
        continue   # Forge's bars are hidden until hover on purpose (Maya-clean viewport)
    for n, line in enumerate(strip_supports(f.read_text(encoding="utf-8")).splitlines(), 1):
        if re.search(r"scrollbar-(width|color)\s*:", line) and not re.search(r"scrollbar-width\s*:\s*none", line):
            bad.append("%s: %s" % (f.name, line.strip()[:120]))
check("static: no scrollbar-width / scrollbar-color outside the Firefox-only @supports (they switch WebKit's bars off)",
      not bad, bad[:5])

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP live: no Playwright\n\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
from PIL import Image  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki-bars-"))
Image.new("RGB", (64, 40), (200, 60, 40)).save(TMP / "p.png")
ITEMS = [{"kind": "image", "name": "pic %d" % i, "path_or_id": "images/p.png", "updated": time.time() - i * 3600,
          "thumb": "/creations/images/p.png", "status": "", "detail": "", "open": {"mode": "image", "path": "p.png"}}
         for i in range(40)]
BAR = """(s => { const e = document.querySelector(s); if (!e) return null; const c = getComputedStyle(e);
  return {w: c.scrollbarWidth || 'auto', c: c.scrollbarColor || 'auto', bar: e.offsetWidth - e.clientWidth,
          scrolls: e.scrollHeight > e.clientHeight + 2}; })"""


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP live: no Chromium (%s)" % str(exc)[:100])
            return
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                ct = "text/javascript" if bare.endswith(".js") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ct} if ct else {}))
            if bare == "/home/projects":
                return await r.fulfill(json={"ok": True, "items": ITEMS, "errors": {}, "counts": {"image": len(ITEMS)}})
            if bare.startswith("/creations/"):
                return await r.fulfill(path=str(TMP / "p.png"), content_type="image/png")
            return await r.fulfill(json={"ok": True})
        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("LokiHome.refresh && LokiHome.refresh()")
        await page.wait_for_selector(".home-card", timeout=8000)
        await page.evaluate("document.getElementById('main').classList.remove('home')")   # in a chat, stacked
        await page.wait_for_timeout(500)

        hub = await page.evaluate(BAR + "('#home-hub')")
        check("Home's column: standard scrollbar props stay auto (so LOKI's bar is drawn)", hub and hub["w"] == "auto" and hub["c"] == "auto", hub)
        check("... the bar is LOKI's 12px one, not the platform's (15px here, a hidden overlay on the Mac)", hub and hub["bar"] == 12, hub)
        check("... and there is something to scroll", hub and hub["scrolls"], hub)
        end = await page.evaluate("""(() => { const h = document.getElementById('home-hub'); h.scrollTop = h.scrollHeight;
          const c = h.querySelectorAll('.home-card'), last = c[c.length - 1].getBoundingClientRect(), r = h.getBoundingClientRect();
          return {top: h.scrollTop, bottom: Math.round(last.bottom), hub: Math.round(r.bottom)}; })()""")
        check("... it scrolls down to the last card", end["top"] > 0 and end["bottom"] <= end["hub"] + 1, end)
        tr = await page.evaluate(BAR + "('#chat-col .transcript')")
        check("chat transcript: LOKI's 12px bar too", tr and tr["w"] == "auto" and tr["c"] == "auto" and tr["bar"] == 12, tr)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 50))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
