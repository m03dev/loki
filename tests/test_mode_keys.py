"""The mode bar's keys never take Forge's (owner 2026-10-21: "control 1 ... takes me to home").

    python tests/test_mode_keys.py      (< 20 s; skips without Playwright + Chromium)

One key per mode: Option+1..4 on a Mac, Ctrl+F1..F4 on Windows (Godot's own), from anywhere; Ctrl/Cmd+1 is always
Forge's Isolate Select, never a second mode key.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % detail))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright\n\n0 passed, 0 failed")
    sys.exit(0)

PAGE = """<!doctype html><html><body><div id="forge" hidden></div><script>
window.forgeOpen = () => { document.getElementById('forge').hidden = false; };
window.forgeClose = () => { document.getElementById('forge').hidden = true; };
window.api = () => Promise.resolve({ok: true, projects: [], projects_dir: '~/LOKI Projects', editors: []});
window.isolated = 0;
document.addEventListener('keydown', (e) => {   // stands in for forge_pro.js (bubble phase, like the real one)
  if (!document.getElementById('forge').hidden && (e.ctrlKey || e.metaKey) && e.code === 'Digit1') window.isolated++;
});
</script><script>%s</script><script>%s</script></body></html>"""


async def main():
    keys = (UI / "forge_keys.js").read_text(encoding="utf-8")
    bar = (UI / "modebar.js").read_text(encoding="utf-8")
    async with async_playwright() as pw:
        try:
            br = await pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)\n\n0 passed, 0 failed" % exc)
            return
        for plat in ("MacIntel", "Win32"):
            ctx = await br.new_context()
            await ctx.add_init_script("Object.defineProperty(navigator, 'platform', {get: () => '%s'})" % plat)
            pg = await ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.set_content(PAGE % (keys, bar))
            await pg.evaluate("LokiModeBar.init()")
            mode = lambda: pg.evaluate("LokiModeBar.active()")  # noqa: E731
            mod = "Meta" if plat == "MacIntel" else "Control"
            # ONE key per mode (owner 2026-10-25: nothing duplicated): Option+1..4 on a Mac, Ctrl+F1..F4 on Windows
            if plat == "MacIntel":
                await pg.keyboard.press("Alt+Digit2")
                check("Mac: Option+2 opens Forge", await mode() == "forge", await mode())
                await pg.keyboard.press("Meta+Digit1")
                check("Mac: in Forge Cmd+1 stays in Forge", await mode() == "forge", await mode())
                check("Mac: ...and reaches Forge (Isolate Select)", await pg.evaluate("window.isolated") == 1)
                await pg.keyboard.press("Alt+Digit1")
                check("Mac: Option+1 goes Home", await mode() == "loki", await mode())
                await pg.keyboard.press("Alt+Digit4")
                check("Mac: Option+4 opens Engine", await mode() == "godot", await mode())
                await pg.keyboard.press("Control+F1")
                check("Mac: Ctrl+F1 is not a second key for Home", await mode() == "godot", await mode())
            else:
                await pg.keyboard.press("Control+F2")
                check("Win: Ctrl+F2 opens Forge", await mode() == "forge", await mode())
                await pg.keyboard.press("Control+Digit1")
                check("Win: in Forge Ctrl+1 stays in Forge", await mode() == "forge", await mode())
                check("Win: ...and reaches Forge (Isolate Select)", await pg.evaluate("window.isolated") == 1)
                await pg.keyboard.press("Control+F1")
                check("Win: Ctrl+F1 goes Home", await mode() == "loki", await mode())
                await pg.keyboard.press("Control+F4")
                check("Win: Ctrl+F4 opens Engine", await mode() == "godot", await mode())
            await pg.keyboard.press(mod + "+Digit1")
            check(plat + ": Ctrl/Cmd+1 is no longer a second key for Home", await mode() == "godot", await mode())
            names = await pg.evaluate("[...document.querySelectorAll('.modebar-tab span')].map(s => s.textContent)")
            check(plat + ": the tabs are Home, Forge, Studio, Engine", names == ["Home", "Forge", "Studio", "Engine"], names)
            tip = await pg.get_attribute("#mode-forge", "title")
            check(plat + ": the tab shows Godot's key", ("⌥2" if plat == "MacIntel" else "Ctrl+F2") in tip, tip)
            check(plat + ": no page errors", not errs, errs)
            await ctx.close()
        await br.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + "; ".join(FAIL))
    sys.exit(1)
