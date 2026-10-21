"""Forge's C++ geometry (owner 2026-10-21: "improve it with c++"): the native engine's cage subdivision
(native/sculpt/core/src/cage_subdiv.cpp, in app/ui/vendor/sculpt/sculpt.wasm) gives the same smooth preview as
the JS ForgePoly.smooth, faster, and Forge uses it - in its own worker - for big cages. Part 1 runs the engine
test in node (skips without node); part 2 checks the window in headless Chromium (skips without Playwright).
Under a minute.

    python tests/test_forge_native_geom.py
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
    r = subprocess.run([node, str(REPO / "native" / "sculpt" / "wasm" / "test" / "test_cage.js")], capture_output=True, text=True, timeout=40)
    print(r.stdout.strip())
    check("the engine's cage subdivision matches the JS on every test cage (test_cage.js)", r.returncode == 0, (r.stdout + r.stderr)[-400:])
else:
    print("SKIP part 1: no node here")


async def ui():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("SKIP part 2: no Playwright here")
        return
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP part 2: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 860})
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
        await page.click("#open-forge")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree", timeout=15000)
        await E("forgeAddPrimitive('sphere')")
        await page.wait_for_timeout(200)
        await E("forgeProRun(forge.view, 'smooth')")          # 288 -> 1 104 faces: over the native threshold
        await page.wait_for_timeout(200)
        await E("fmySmoothPreview(3)")
        await page.wait_for_function("forge.view.smoothPrev && forge.view.smoothPrev.mesh && !forge.view.smoothPrev.pending", timeout=10000)
        got = await E("""(() => { const st = forge.view.smoothPrev, P = ForgePoly; let m = forge.view.poly;
          for (let k = 0; k < 2 && m.f.length * 4 <= 60000; k++) m = P.smooth(m);
          const j = P.triangulate(m), a = st.mesh.geometry.attributes.position.array; let d = 0;
          for (let i = 0; i < j.pos.length; i++) d = Math.max(d, Math.abs(j.pos[i] - a[i]));
          return { native: st.native, state: ForgeGeom.state, n: a.length, jn: j.pos.length, d, tris: st.mesh.geometry.index.count, jt: j.idx.length }; })()""")
        check("a 1 104-face cage's smooth preview (3) comes from the C++ engine, the same mesh the JS makes",
              got["native"] is True and got["state"] == "on" and got["n"] == got["jn"] and got["tris"] == got["jt"] and got["d"] < 1e-4, got)
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(200)
        await E("fmySmoothPreview(3)")
        small = await E("[forge.view.smoothPrev.native, forge.view.smoothPrev.mesh.geometry.attributes.position.count]")
        check("a small cage (a cube) stays on the instant JS path", small == [False, 98], small)
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(ui(), timeout=45))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
