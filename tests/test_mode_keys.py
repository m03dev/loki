"""The mode bar's keys never take Forge's (owner 2026-10-21: "control 1 ... takes me to home").

    python tests/test_mode_keys.py      (< 20 s; skips without Playwright + Chromium)

In Forge, Ctrl/Cmd+1 is Isolate Select and stays in Forge; Godot's own mode keys (Option+1..4 on a Mac, Ctrl+F1..F4)
switch from anywhere; outside Forge Ctrl/Cmd+1..4 still switch; the chat's Alt+Up / Mod+B leave Forge's keys alone.
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
            await pg.keyboard.press(mod + "+Digit2")
            check(plat + ": Ctrl/Cmd+2 opens Forge from Home", await mode() == "forge", await mode())
            await pg.keyboard.press(mod + "+Digit1")
            check(plat + ": in Forge Ctrl/Cmd+1 stays in Forge", await mode() == "forge", await mode())
            check(plat + ": ...and reaches Forge (Isolate Select)", await pg.evaluate("window.isolated") == 1)
            if plat == "MacIntel":
                await pg.keyboard.press("Alt+Digit1")
                check("Mac: Option+1 goes Home (Godot's key)", await mode() == "loki", await mode())
                await pg.keyboard.press("Alt+Digit4")
                check("Mac: Option+4 opens Godot", await mode() == "godot", await mode())
            await pg.keyboard.press(mod + "+Digit2")
            await pg.keyboard.press("Control+F1")
            check(plat + ": Ctrl+F1 goes Home from Forge", await mode() == "loki", await mode())
            await pg.keyboard.press("Control+F4")
            check(plat + ": Ctrl+F4 opens Godot", await mode() == "godot", await mode())
            await pg.keyboard.press(mod + "+Digit1")
            check(plat + ": outside Forge Ctrl/Cmd+1 still goes Home", await mode() == "loki", await mode())
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
