"""Forge's File menu rows (app/ui/forge_file.js): New Scene (one undo brings the old scene back), Import (.obj / .stl
/ .glb as NEW objects beside what is there), Open Scene and Save Scene As in Maya's places. Under a minute.

    python tests/test_forge_file_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
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
        F = "forge.view.tree.api.worldPolys ? (() => { const t = forge.view.tree.api; return forge.view.poly ? forge.view.poly.f.length : -1; })() : -1"

        T = "forge.view.tree.api"
        await E("(async () => { await forgeProRun(forge.view, 'cube'); await forgeProRun(forge.view, 'sphere'); })()")
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'File') || [0, []])[1])")
        check("File: New Scene, Open Scene..., Save, Save Scene As..., Import... in Maya's order",
              [x for x in menu if x in ("newScene", "openScene", "save", "saveAs", "importFile")] == ["newScene", "openScene", "save", "saveAs", "importFile"], menu)
        r = await E("""(async () => { const t = forge.view.tree.api;
          const obj = "v 0 0 0\\nv 1 0 0\\nv 1 1 0\\nv 0 1 0\\nv 0 0 1\\nf 1 2 3 4\\nf 1 2 5\\n";
          const msg = await ForgeFile.importFile(new File([obj], "plate.obj"));
          return { msg, names: t.list().filter((n) => n.kind === 'mesh').map((n) => n.name), faces: forge.view.poly.f.length }; })()""")
        check("Import .obj: a NEW object beside the cube and the sphere, with its faces", r["names"] == ["pCube1", "pSphere1", "plate1"]
              and r["faces"] == 2 and "Imported" in r["msg"], r)
        r = await E("""(async () => { const t = forge.view.tree.api, n = 1, buf = new ArrayBuffer(84 + 50 * n), dv = new DataView(buf);
          dv.setUint32(80, n, true); const pts = [0, 0, 0, 1, 0, 0, 0, 1, 0]; pts.forEach((x, k) => dv.setFloat32(84 + 12 + k * 4, x, true));
          const msg = await ForgeFile.importFile(new File([buf], "tri.stl"));
          return { msg, names: t.list().filter((x) => x.kind === 'mesh').map((x) => x.name), faces: forge.view.poly.f.length }; })()""")
        check("Import binary .stl: a new object with its triangle", r["names"][-1] == "tri1" and r["faces"] == 1, r)
        bad = await E("ForgeFile.importFile(new File(['x'], 'notes.txt'))")
        check("an unknown file type says which ones work", ".obj" in bad and ".stl" in bad, bad)
        await E("ForgeFile.newScene()")
        st = await E("[forge.view.tree.api.list().filter((n) => n.kind === 'mesh' && (!n.root || (forge.view.poly && forge.view.poly.f.length))).length, document.querySelectorAll('#forge-out-list .forge-out-row').length]")
        check("New Scene: nothing left (the Outliner is empty)", st == [0, 0], st)
        await E("forge.view.undo()"); await page.wait_for_timeout(150)
        back = await E("forge.view.tree.api.list().filter((n) => n.kind === 'mesh').map((n) => n.name)")
        check("one undo brings the whole old scene back", back == ["pCube1", "pSphere1", "plate1", "tri1"], back)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
