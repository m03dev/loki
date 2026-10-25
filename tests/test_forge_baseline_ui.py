"""Forge primitives: the baseline (owner 2026-10-25: "when I press t I should be able to adjust baseline height negative
or positive so it goes on the grid. Right now it's .5, I should be able to get 0-1").

  * a new cube / sphere / torus ... sits ON the grid (its lowest point at y = 0, its pivot at its base);
  * t on the new object opens its In-View Editor with a Baseline row (-1..1, step 0.05); changing it moves the mesh,
    in object mode too, and the scene's world mesh follows;
  * Settings > Create > Baseline sets where new objects start (-0.5 = the old centred cube);
  * the kernel's own callers (no baseline given) still get the unit box centred on the origin.
Under a minute.

    python tests/test_forge_baseline_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)

LOW = "(() => Math.round(Math.min(...forge.view.poly.v.map((q) => q[1])) * 1000) / 1000)()"
WORLD = "forge.view.tree.api.worldPolys().map((p) => Math.round(Math.min(...p.poly.v.map((q) => q[1])) * 1000) / 1000)"


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8892", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8892/**", route)
        await page.goto("http://127.0.0.1:8892/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=15000)
        E = page.evaluate
        wait = page.wait_for_timeout

        kern = await E("""(() => { const P = window.ForgePoly, out = {};
          for (const k of Object.keys(P.PRIMITIVES)) { const c = P.primitive(k), b = P.primitive(k, { baseline: 0.25 });
            const lo = (m) => Math.min(...m.v.map((q) => q[1])), hi = (m) => Math.max(...m.v.map((q) => q[1]));
            out[k] = [Math.abs(lo(c) + hi(c)) < 1e-9, Math.abs(lo(b) - 0.25) < 1e-9, c.f.length === b.f.length]; }
          return out; })()""")
        check("kernel: no baseline -> centred on the origin as before; a baseline puts the lowest point there",
              all(all(x) for x in kern.values()), kern)

        await E("forgeProRun(forge.view, 'cube')"); await wait(250)
        check("a new cube sits on the grid (lowest point y = 0)", await E(LOW) == 0, await E(LOW))
        check("... and the scene's world mesh agrees", await E(WORLD) == [0], await E(WORLD))
        await E("forge.view.canvas.focus && forge.view.canvas.focus()")
        await page.keyboard.press("t"); await wait(250)
        ive = await E("(() => { const b = document.getElementById('forge-ive'), r = b && b.querySelector('.forge-ive-row[data-k=baseline] input'); return b && !b.hidden && r ? { min: r.min, max: r.max, step: r.step, v: r.value } : null; })()")
        check("t opens the new cube's editor with a Baseline row, -1..1 in 0.05 steps", ive == {"min": "-1", "max": "1", "step": "0.05", "v": "0"}, ive)
        for val, want in (("-0.5", -0.5), ("0.75", 0.75), ("-1", -1), ("3", 1)):
            await E("(() => { const n = document.querySelector('#forge-ive .forge-ive-row[data-k=baseline] input'); n.value = '%s'; n.dispatchEvent(new Event('change')); })()" % val)
            await wait(120)
            got = [await E(LOW), await E(WORLD)]
            check("Baseline %s -> its base at %s (object mode, world mesh too)" % (val, want), got == [want, [want]], got)
        side = await E("forge.view.mode")
        check("still in object mode after the change", side == "view", side)
        await E("(() => { const n = document.querySelector('#forge-ive .forge-ive-row[data-k=baseline] input'); n.value = '0.3'; n.dispatchEvent(new Event('change')); })()")
        await E("(async () => { await forgeModelMode(true); await forgeModelMode(false); })()"); await wait(200)
        check("the baseline survives going into components and back", await E(WORLD) == [0.3], await E(WORLD))
        await E("ForgeSettings.set('createBaseline', -0.5)")
        await E("forgeProRun(forge.view, 'sphere')"); await wait(250)
        check("Settings > Create > Baseline -0.5: a new sphere is centred on the grid (the old way)", await E(LOW) == -0.5, await E(LOW))
        await E("ForgeSettings.set('createBaseline', 0)")
        await E("forgeProRun(forge.view, 'torus')"); await wait(250)
        check("a torus (not a unit-tall shape) also lands with its lowest point on the grid", await E(LOW) == 0, await E(LOW))
        await E("forgeModelMode(true)"); await wait(200)
        sl = await E("[...document.querySelectorAll('#forge-model-params .forge-hslider, #forge-model-params label, #forge-model-params *')].some((n) => /Baseline/.test(n.textContent || ''))")
        check("the INPUTS panel in component mode has the Baseline slider too", sl)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    import time
    t0 = time.time()
    asyncio.run(main())
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        sys.exit(1)
