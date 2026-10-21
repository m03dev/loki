"""Forge's path-traced Render (docs/FORGE_RENDER.md): the vendored three-gpu-pathtracer + three-mesh-bvh load under the
page's CSP, the Renderer menu has Path Traced Preview and Render..., the Render window renders a cube at 64x64 with the
samples climbing, Stop stops it, Save PNG hands over a PNG data URL, window.ForgeRender.render() returns a job whose
picture is not blank, renderSequence() puts the Time Slider back, and the preview refines the viewport. Headless
Chromium with SwiftShader. Skips without Playwright + Chromium, and says so (and skips) if SwiftShader has no WebGL2
float render targets. Under a minute.

    python tests/test_forge_render_ui.py
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


import time as _t
_T0 = _t.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + ("[%4.1fs] " % (_t.time() - _T0)) + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


# ---- offline checks (no browser): the vendored code is complete, licensed, and has no bare imports left
import re  # noqa: E402

VEND = UI / "vendor"
bare = []
for d in ("pathtracer", "three-mesh-bvh"):
    for p in (VEND / d).rglob("*.js"):
        for line in p.read_text(encoding="utf-8").split("\n"):
            s = line.lstrip()
            if s.startswith("//") or s.startswith("*"):
                continue
            for m in re.finditer(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)['"]([^'"]+)['"]""", line):
                if not m.group(1).startswith("."):
                    bare.append("%s: %s" % (p.relative_to(VEND), m.group(1)))
check("the vendored path tracer and BVH have no bare imports left (the CSP allows no import map)", not bare, bare[:5])
check("each vendored library keeps its MIT LICENSE next to it",
      all("MIT License" in (VEND / d / "LICENSE").read_text(encoding="utf-8") for d in ("pathtracer", "three-mesh-bvh")))
tp = (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
check("docs/THIRD_PARTY.md has a row for each", "app/ui/vendor/pathtracer/" in tp and "app/ui/vendor/three-mesh-bvh/" in tp)
html = (UI / "index.html").read_text(encoding="utf-8")
check("index.html loads forge_render.js after the other Forge scripts",
      html.find("/ui/forge_render.js") > html.find("/ui/forge_sculpt.js") > 0)
src = (UI / "forge_render.js").read_text(encoding="utf-8")
check("no product names in the Render UI text", not re.search(r"\b(Maya|Blender|ZBrush|Cycles|Arnold|V-Ray|Redshift|Octane)\b", src))

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 860}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        async def route(r):
            bare_url = r.request.url.split("8894", 1)[1].split("#")[0].split("?")[0]
            if bare_url == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare_url.startswith("/ui/") and (UI / bare_url[4:]).is_file():
                return await r.fulfill(path=str(UI / bare_url[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        # Light sampling (MIS) off: its full shader takes SwiftShader ~25 s to compile; the smaller one ~4 s (a real GPU: ~1 s)
        await E("localStorage.setItem('loki-forge-render', JSON.stringify({ mis: false }))")

        check("window.ForgeRender and the renderPreview / renderDialog commands exist",
              await E("!!(window.ForgeRender && FORGE_PRO_CMDS.renderPreview && FORGE_PRO_CMDS.renderDialog)"))
        if not await E("ForgeRender.isAvailable()"):
            print("SKIP: this browser's WebGL (SwiftShader) has no WebGL2 float render targets - the path tracer cannot run here")
            await browser.close()
            return

        await page.click("#open-forge")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree", timeout=15000)
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(150)
        await E("forgeModelMode(false)")

        # ---- the Renderer menu
        await page.click("#fmy-panelbar .fmy-mb[data-menu='Renderer']")
        items = await E("[...document.querySelectorAll('.fmy-drop .fmy-ditem')].map((b) => b.textContent)")
        check("Renderer menu: Viewport 2.0, Path Traced Preview, Render...",
              any("Viewport 2.0" in t for t in items) and any("Path Traced Preview" in t for t in items) and any("Render..." in t for t in items), items)
        await page.click(".fmy-drop .fmy-ditem[data-pro-id='renderDialog']")
        check("Render... opens the Render window", await E("!!document.getElementById('forge-render') && !document.getElementById('forge-render').hidden"))
        check("the window reads the saved settings (Light sampling off here)", await E("document.getElementById('fr-mis').checked") is False)
        check("the scene's visible meshes are what renders (one cube)", await E("ForgeRender.meshes().length") == 1)

        # ---- render 64 x 64 from the window
        await page.select_option("#fr-res", "custom")
        await page.fill("#fr-w", "64")
        await page.fill("#fr-h", "64")
        await page.fill("#fr-samples", "400")
        await page.dispatch_event("#fr-samples", "input")
        await page.click("#fr-render")
        await page.wait_for_function("(() => { const j = ForgeRender.dialogJob(); return j && j.samples >= 2; })()", timeout=40000)
        s1 = await E("ForgeRender.dialogJob().samples")
        await page.wait_for_function("ForgeRender.dialogJob().samples > %d" % s1, timeout=15000)
        s2 = await E("ForgeRender.dialogJob().samples")
        check("the samples climb while it renders", s2 > s1, [s1, s2])
        await page.click("#fr-stop")
        res = await E("ForgeRender.dialogJob().done.then((r) => ({ s: r.samples, w: r.width, h: r.height, stopped: r.stopped, url: r.dataURL.slice(0, 22) }))")
        check("Stop ends the render early and keeps what was there", res["stopped"] and res["s"] < 400 and res["w"] == 64 and res["h"] == 64, res)
        info = await E("document.getElementById('fr-info').textContent")
        check("the window says how many samples and how long", "Stopped at" in info and "samples" in info, info)
        blank = await E("""(() => { const c = document.getElementById('fr-canvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          const seen = new Set(); let a = 0; for (let i = 0; i < d.length; i += 4) { seen.add((d[i] >> 3) + ',' + (d[i + 1] >> 3) + ',' + (d[i + 2] >> 3)); a += d[i + 3]; }
          return [seen.size, a / (d.length / 4)]; })()""")
        check("the rendered picture is not blank (many colours, opaque)", blank[0] > 8 and blank[1] > 200, blank)
        url = await E("ForgeRender.savePNG()")
        check("Save PNG hands over a PNG data URL", isinstance(url, str) and url.startswith("data:image/png;base64,") and len(url) > 200, (url or "")[:40])

        # ---- the API Render Studio uses: render(opts) -> job
        r = await E("""(async () => { const job = ForgeRender.render({ width: 48, height: 32, samples: 3, bounces: 3, environment: { type: 'sky', intensity: 1.2 },
            background: '#203040', exposure: 1.1, toneMapping: 'ACES', camera: 'current' });
          const keys = ['progress', 'samples', 'stop', 'done'].every((k) => k in job);
          const out = await job.done; const d = out.canvas.getContext('2d').getImageData(0, 0, out.width, out.height).data;
          let lit = 0; for (let i = 0; i < d.length; i += 4) if (d[i] + d[i + 1] + d[i + 2] > 30) lit++;
          return { keys, p: job.progress, s: out.samples, w: out.width, h: out.height, lit, url: out.dataURL.slice(0, 22), blob: !!out.blob, ms: out.ms }; })()""")
        check("ForgeRender.render(opts): a job with progress / samples / stop / done; done gives the canvas, a PNG, samples and time",
              r["keys"] and r["p"] == 1 and r["s"] == 3 and r["w"] == 48 and r["h"] == 32 and r["lit"] > 100
              and r["url"] == "data:image/png;base64," and r["blob"] and r["ms"] >= 0, r)

        # ---- an animation: the Time Slider is put back afterwards
        seq = await E("""(async () => { const T = forge.view.tree; T.time.frame = 5; const before = [T.time.frame, T.time.start, T.time.end];
          const s = ForgeRender.renderSequence({ width: 16, height: 16, samples: 1, start: 1, end: 3, step: 1 });
          const out = await s.done; return { n: out.frames.length, f: out.frames.map((x) => x.frame), before, after: [T.time.frame, T.time.start, T.time.end] }; })()""")
        check("renderSequence renders each frame and restores the Time Slider", seq["n"] == 3 and seq["f"] == [1, 2, 3] and seq["before"] == seq["after"], seq)

        # ---- Path Traced Preview: the viewport refines while still, raster again on any change
        await page.click("#forge-render .forge-rw-x")
        check("the window's x closes it", await E("document.getElementById('forge-render').hidden"))
        await page.click("#fmy-panelbar .fmy-mb[data-menu='Renderer']")
        await page.click(".fmy-drop .fmy-ditem[data-pro-id='renderPreview']")
        await page.wait_for_function("ForgeRender.previewSamples() >= 2", timeout=15000)
        on = await E("[ForgeRender.previewOn(), ForgeRender.previewSamples()]")
        # orbit a little (what a camera move does): the raster frame shows it and the trace starts over
        await E("(() => { const v = forge.view; v.camera.position.applyAxisAngle(new v.THREE.Vector3(0, 1, 0), 0.2); v.controls.update(); v.dirty = true; })()")
        await page.wait_for_function("ForgeRender.previewSamples() < %d" % on[1], timeout=8000)
        reset = await E("ForgeRender.previewSamples()")
        check("Path Traced Preview converges in the viewport and starts over when the view changes", on[0] and on[1] >= 2 and reset < on[1], [on, reset])
        await page.click("#fmy-panelbar .fmy-mb[data-menu='Renderer']")
        ticked = await E("document.querySelector(\".fmy-drop .fmy-ditem[data-pro-id='renderPreview'] .fmy-tick\").textContent")
        await page.click(".fmy-drop .fmy-ditem[data-pro-id='renderPreview']")
        check("the menu ticks the preview while it is on, and a second click turns it off", ticked == "✓" and not await E("ForgeRender.previewOn()"), ticked)

        errs = [e for e in errors if "deprecated" not in e.lower()]
        check("no page errors", not errs, errs[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
