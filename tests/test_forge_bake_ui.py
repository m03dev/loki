"""Forge's Baking workspace (app/ui/forge_bake.js): the node suite for the baker (tests/js/test_forge_bake.js), then
in headless Chromium: a high sphere and a low cube with UVs in one scene, Workspace > Baking, pick the high, Bake ->
map previews, the normal + AO maps on the low's material, settings remembered. Skips without node / Playwright.
Under a minute.

    python tests/test_forge_bake_ui.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


node = shutil.which("node")
if node:
    r = subprocess.run([node, str(REPO / "tests" / "js" / "test_forge_bake.js")], capture_output=True, text=True, timeout=30)
    print(r.stdout.strip())
    check("the baker passes its node suite", r.returncode == 0, (r.stdout + r.stderr)[-400:])


async def ui():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("SKIP: no Playwright here")
        return
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8894", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("['loki-forge-bake', 'loki-forge-workspace'].forEach((k) => localStorage.removeItem(k))")
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree && document.getElementById('forge-workspace')", timeout=15000)
        # the high: a sphere; the low: a cube with automatic UVs, made after it (the edited one)
        await E("forgeProRun(forge.view, 'sphere')")
        await page.wait_for_timeout(250)
        await E("forgeProRun(forge.view, 'cube')")
        await page.wait_for_timeout(250)
        await E("ForgeUVEditor.OPS.automatic()")
        await page.wait_for_timeout(400)
        names = await E("forge.view.tree.api.sceneNodes().map((n) => [n.name, !!n.root])")
        await E("(() => { const s = JSON.parse(localStorage.getItem('loki-forge-bake') || '{}'); s.res = 128; s.aoSamples = 4; s.maxDist = 0.6; localStorage.setItem('loki-forge-bake', JSON.stringify(s)); })()")
        await page.select_option("#forge-workspace", "bake")
        await page.wait_for_timeout(200)
        pan = await E("[!document.getElementById('forge-bakepanel').hidden, [...document.querySelectorAll('#forge-bakepanel .fbk-high option')].map((o) => o.textContent)]")
        check("Workspace > Baking: the Baking panel, with the other object offered as High", pan[0] and len(pan[1]) == 1 and pan[1][0].startswith("pSphere"), [names, pan])
        await E("document.querySelector('#forge-bakepanel [data-bk=bake]').click()")
        await page.wait_for_function("/Baked|missed|needs|no UVs|Pick/.test(document.querySelector('#forge-bakepanel .fbk-status').textContent)", timeout=30000)
        out = await E("""[document.querySelector('#forge-bakepanel .fbk-status').textContent, [...document.querySelectorAll('#forge-bakepanel .fbk-thumb')].map((c) => c.dataset.map),
          !!(forge.view.material.normalMap && forge.view.material.aoMap)]""")
        check("Bake: the checked maps (normal, AO, curvature) are previewed and put on the low's material", out[0].startswith("Baked") and out[1] == ["normal", "ao", "curvature"] and out[2], out)
        await E("document.querySelector('#forge-bakepanel [data-bk=preview]').click()")
        off = await E("!forge.view.material.normalMap")
        check("Preview toggles the maps off the model again", off, off)
        none = await E("(async () => { forgeProRun(forge.view, 'torus'); await new Promise((r) => setTimeout(r, 300)); await ForgeBake.bake(); return document.querySelector('#forge-bakepanel .fbk-status').textContent; })()")
        check("a low without UVs is refused with what to do", "UV" in none, none)
        await page.select_option("#forge-workspace", "model")
        hid = await E("document.getElementById('forge-bakepanel').hidden")
        check("back to Modeling hides the Baking panel", hid, hid)
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(ui(), timeout=50))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
