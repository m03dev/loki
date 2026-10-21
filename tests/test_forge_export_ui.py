"""Forge's Export dialog in headless Chromium: glTF (.glb), OBJ, STL (binary + ASCII) and PLY are real files,
the unit scale multiplies the geometry, and the name/extension land in the save request. We intercept the
POST the app makes to /forge/save and inspect the bytes. Under a minute.

    python tests/test_forge_export_ui.py
"""
from __future__ import annotations

import asyncio
import os
import struct
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
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        captured: list = []

        async def route(r):
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        async def save_route(r):
            captured.append({"url": r.request.url, "body": r.request.post_data_buffer or b""})
            name = r.request.url.split("name=")[1].split("&")[0]
            await r.fulfill(json={"ok": True, "path": "models/" + name, "name": name})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.route("**/forge/save**", save_route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-hotkeys')")
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm", timeout=10000)
        E = page.evaluate

        has_btn = await E("!!document.querySelector('#forge-exportbar [data-icon=\"export\"]')")
        await E("forgeExportDialog()")
        await page.wait_for_timeout(60)
        dlg = await E("[!document.getElementById('forge-exportdlg').hidden, document.querySelectorAll('#forge-export-fmts [data-fmt]').length]")
        check("the export bar has an Export button that opens a dialog with the 4 formats",
              has_btn and dlg == [True, 4], [has_btn, dlg])

        async def export(fmt, **opts):
            captured.clear()
            await E("forgeExport.fmt = %r; forgeExport.stlAscii = %s; forgeExport.scale = %r; forgeExport.name = %r"
                    % (fmt, "true" if opts.get("ascii") else "false", str(opts.get("scale", "1")), opts.get("name", "shot")))
            await E("document.getElementById('forge-export-go').click()")
            for _ in range(60):
                if captured:
                    break
                await page.wait_for_timeout(50)
            return captured[-1] if captured else None

        glb = await export("glb")
        check("glTF binary export is a real .glb (glTF magic + the .glb name)",
              glb is not None and glb["body"][:4] == b"glTF" and glb["url"].endswith("shot.glb"), glb and glb["url"])

        obj = await export("obj")
        text = obj["body"].decode("utf-8", "replace") if obj else ""
        check("OBJ export has vertices and faces and the .obj name",
              obj is not None and "\nv " in text and "\nf " in text and obj["url"].endswith("shot.obj"), text[:60])

        stl = await export("stl")
        tris = struct.unpack_from("<I", stl["body"], 80)[0] if stl and len(stl["body"]) >= 84 else -1
        check("binary STL: 80-byte header, triangle count, 50 bytes a triangle",
              stl is not None and tris > 0 and len(stl["body"]) == 84 + tris * 50 and stl["url"].endswith("shot.stl"),
              [tris, len(stl["body"]) if stl else 0])

        ascii_stl = await export("stl", ascii=True)
        atext = ascii_stl["body"].decode("utf-8", "replace") if ascii_stl else ""
        check("ASCII STL is the readable 'solid ... facet normal ... vertex' form",
              ascii_stl is not None and atext.startswith("solid ") and "facet normal" in atext and atext.rstrip().endswith("endsolid shot"), atext[:40])

        ply = await export("ply")
        ptext = ply["body"][:420].decode("utf-8", "replace") if ply else ""
        check("PLY export is a binary_little_endian .ply with a vertex + face element",
              ply is not None and ply["body"][:3] == b"ply" and "format binary_little_endian" in ptext and "element vertex" in ptext and "element face" in ptext,
              [len(ply["body"]) if ply else 0, repr(ply["body"][:40]) if ply else ""])

        one = await export("stl", scale="1")
        two = await export("stl", scale="2")
        def first_vertex(b):
            return struct.unpack_from("<3f", b, 84 + 12) if b and len(b) >= 96 else (0, 0, 0)
        v1, v2 = first_vertex(one["body"]) if one else (0, 0, 0), first_vertex(two["body"]) if two else (0, 0, 0)
        ratio = abs(v2[0]) / abs(v1[0]) if v1[0] else 0
        check("the unit scale multiplies the geometry (scale 2 doubles the coordinates)",
              abs(ratio - 2) < 0.01 and one["url"].endswith("shot.stl"), [v1, v2, ratio])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
