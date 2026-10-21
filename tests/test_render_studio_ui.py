"""Render Studio (app/ui/render_studio.js, app/ui/forge_passes.js) in headless Chromium against a stubbed /render API:
the Render tab opens with its three panes and icon tooltips, Forge's passes render a 64x64 depth + line art for 3 frames
of an animated cube from a chosen camera (depth white = near, line art white on black, the cube moving between frames)
and the scene, camera, Time Slider and renderer are exactly as before, the preflight button shows the report (missing
model with its folder and link), and a job's frames are posted to /render/upload-pass. Skips without Playwright + Chromium.
Under a minute.

    python tests/test_render_studio_ui.py
"""
from __future__ import annotations

import asyncio
import json
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


html = (UI / "index.html").read_text(encoding="utf-8")
check("index.html loads render_studio.css, forge_passes.js and render_studio.js after forge_render.js",
      html.find("/ui/render_studio.js") > html.find("/ui/forge_passes.js") > html.find("/ui/forge_render.js") > 0 and "/ui/render_studio.css" in html)

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)

WF = json.loads((REPO / "engine" / "ai_renderer_workflows" / "vace_render.json").read_text(encoding="utf-8"))
STATUS = {"ok": True, "settings": {"url": "http://192.168.1.50:8188", "consent_remote": False, "timeout_s": 3600, "url_shown": "http://192.168.1.50:8188",
          "where": {"place": "peer", "own": True, "note": "LOKI's linked machine 'pc'"}},
          "workflows": [{k: WF.get(k) for k in ("name", "label", "params", "uploads", "constraints", "custom_nodes")} | {"models": WF["models"]}],
          "jobs": [{"job": "ai-20261021-1-ab", "name": "Shot 1", "kind": "ai", "status": "running", "progress": 0.4, "last": "running on pc"}], "active": []}
REPORT = {"ok": True, "report": {"ok": False, "url": "http://192.168.1.50:8188", "blockers": ["model file wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf is not in ComfyUI/models/unet"],
          "warnings": ["the largest model file (11.6 GB) is bigger than the GPU's 8.6 GB"], "checked": ["connected to ComfyUI 0.9.9"],
          "missing_nodes": [], "missing_models": [{"file": "wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf", "folder": "models/unet", "size": 11627589408,
          "license": "see docs", "url": "https://huggingface.co/mickmumpitz/VACE_Skyreels_V3_R2V_Merge-GGUF/resolve/57045d4ab42eb76a53bdaadb37b5d8dc923ec67b/wan-14B_vace_skyreels_v3_R2V_e4m3fn_v1-Q4_K_M.gguf"}],
          "gpu": {"name": "NVIDIA GeForce RTX 3070 Ti", "vram_total": 8589934592}}}


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
        errors, posted = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        async def route(r):
            bare = r.request.url.split("8894", 1)[1].split("#")[0]
            path = bare.split("?")[0]
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/") and (UI / path[4:]).is_file():
                return await r.fulfill(path=str(UI / path[4:]))
            if path == "/render/status":
                return await r.fulfill(json=STATUS)
            if path == "/render/preflight":
                posted.append(("preflight", json.loads(r.request.post_data or "{}")))
                return await r.fulfill(json=REPORT)
            if path == "/render/presets":
                return await r.fulfill(json={"ok": True, "presets": {}})
            if path == "/render/upload-pass":
                body = r.request.post_data_buffer or b""
                posted.append(("pass", bare.split("?", 1)[1], body[:8]))
                return await r.fulfill(json={"ok": True, "passes": {}})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("localStorage.removeItem('loki-render-studio')")

        # ---- the Render tab
        tabs = await E("[...document.querySelectorAll('.modebar-tab')].map((b) => b.dataset.mode)")
        check("the title bar has Home / Forge / Render / Godot", tabs == ["loki", "forge", "render", "godot"], tabs)
        await page.click("#mode-render")
        await page.wait_for_selector("#render-studio", timeout=8000)
        panes = await E("['rs-jobs', 'rs-centre', 'rs-settings'].map((id) => { const b = document.getElementById(id).getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; })")
        check("Render Studio: jobs left, preview centre (the widest), settings right", all(w > 100 and h > 300 for w, h in panes) and panes[1][0] > panes[0][0], panes)
        await page.wait_for_selector("#rs-joblist .rs-job", timeout=5000)
        job = await E("document.querySelector('#rs-joblist .rs-job').textContent")
        check("the job list shows the jobs the engine reports, with their status", "Shot 1" in job and "running" in job, job)
        tips = await E("[...document.querySelectorAll('#render-studio button.rs-btn')].map((b) => [b.dataset.tipName, b.dataset.tipWhat, !!b.querySelector('svg')])")
        check("every Render Studio button is an icon with a tooltip (name + what it does)", tips and all(n and w and s for n, w, s in tips), [t for t in tips if not all(t)][:4])
        await page.hover("#rs-preflight")
        await page.wait_for_timeout(500)
        tip = await E("(() => { const t = document.querySelector('.icon-tip'); return t && !t.hidden ? t.textContent : ''; })()")
        check("hovering an icon shows its tooltip", "Preflight" in tip, tip)
        url = await E("document.getElementById('rs-url').value")
        check("the ComfyUI address comes from the engine's settings (the PC)", url == "http://192.168.1.50:8188", url)
        opts = await E("[...document.getElementById('rs-model').options].map((o) => o.value)")
        check("the model choice lists the GGUF files the workflow names (Q4_K_M + the other sizes)", opts and opts[0].endswith("Q4_K_M.gguf") and len(opts) == 4, opts)

        # ---- Forge: an animated cube, 3 frames
        await E("LokiModeBar.go('forge')")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree", timeout=15000)
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(150)
        await E("forgeModelMode(false)")
        T = "forge.view.tree.api"
        await E("""(() => { const a = %s, id = a.sceneNodes()[0].id; a.setKey(id, 1, 'translate', 0, -0.6); a.setKey(id, 3, 'translate', 0, 0.6);
                a.setRange(1, 3); a.setFrame(2); })()""" % T)
        before = await E("""(() => { const v = forge.view, n = %s.sceneNodes()[0], t = v.tree.time;
          return { cam: v.camera.position.toArray().map((x) => +x.toFixed(6)), q: v.camera.quaternion.toArray().map((x) => +x.toFixed(6)),
            fov: v.camera.fov, camName: v.cam, frame: t.frame, start: t.start, end: t.end, pos: n.grp.position.toArray().map((x) => +x.toFixed(6)),
            mat: n.grp.children.map((c) => c.material && c.material.uuid).join(), over: v.scene.overrideMaterial, bg: v.scene.background ? v.scene.background.getHexString ? v.scene.background.getHexString() : 'tex' : null,
            target: v.renderer.getRenderTarget(), size: [v.canvas.width, v.canvas.height],
            vis: (() => { const out = []; v.scene.traverse((o) => out.push(o.visible ? 1 : 0)); return out.join(''); })() }; })()""" % T)
        res = await E("""ForgePasses.render({ camera: 'front', passes: ['depth', 'lineart'], width: 64, height: 64, start: 1, end: 3, step: 1 }).then((r) => {
            const px = (c) => { const g = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; return g; };
            const stat = (c) => { const g = px(c); let white = 0, black = 0, sum = 0, cx = 0, n = 0;
              for (let i = 0; i < g.length; i += 4) { const v = g[i]; sum += v; if (v > 200) white++; if (v < 30) black++; if (v > 0) { cx += (i / 4) % c.width; n++; } }
              return { white, black, mean: sum / (g.length / 4), cx: n ? cx / n : -1, w: c.width, h: c.height, grey: [...g.slice(0, 64 * 4)].every((x, i) => i % 4 === 3 || x === g[i - (i % 4)]) }; };
            return { n: r.frames.length, frames: r.frames.map((f) => f.frame), cam: r.camera, near: r.near, far: r.far,
                     depth: r.frames.map((f) => stat(f.depth)), line: r.frames.map((f) => stat(f.lineart)),
                     center: (() => { const g = px(r.frames[1].depth); return g[(32 * 64 + 32) * 4]; })() }; })""")
        check("3 frames of depth + line art at 64x64 from the front camera", res["n"] == 3 and res["frames"] == [1, 2, 3] and res["cam"] == "front"
              and all(d["w"] == 64 and d["h"] == 64 for d in res["depth"] + res["line"]), res)
        check("depth: the cube is bright (near = white) on a black background", res["center"] > 100 and all(d["black"] > 500 for d in res["depth"]), [res["center"], res["depth"]])
        check("line art: white lines on black, a thin outline (far fewer white than black pixels)",
              all(0 < l["white"] < l["black"] for l in res["line"]), res["line"])
        xs = [d["cx"] for d in res["depth"]]
        check("the cube moves across the frames (the Time Slider keys are evaluated per frame)", xs[0] < xs[1] < xs[2], xs)
        after = await E("""(() => { const v = forge.view, n = %s.sceneNodes()[0], t = v.tree.time;
          return { cam: v.camera.position.toArray().map((x) => +x.toFixed(6)), q: v.camera.quaternion.toArray().map((x) => +x.toFixed(6)),
            fov: v.camera.fov, camName: v.cam, frame: t.frame, start: t.start, end: t.end, pos: n.grp.position.toArray().map((x) => +x.toFixed(6)),
            mat: n.grp.children.map((c) => c.material && c.material.uuid).join(), over: v.scene.overrideMaterial, bg: v.scene.background ? v.scene.background.getHexString ? v.scene.background.getHexString() : 'tex' : null,
            target: v.renderer.getRenderTarget(), size: [v.canvas.width, v.canvas.height],
            vis: (() => { const out = []; v.scene.traverse((o) => out.push(o.visible ? 1 : 0)); return out.join(''); })() }; })()""" % T)
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        check("the scene is unchanged after: camera, view, frame + range, object position, materials, visibility, renderer target, canvas size",
              not diff, diff)

        # ---- the Render tab: render the passes, preview, preflight, a job
        await E("LokiModeBar.go('render')")
        await E("""(() => { const s = (id, v) => { document.getElementById(id).value = String(v); };
           s('rs-camera', 'front'); s('rs-start', 1); s('rs-end', 3); s('rs-width', 64); s('rs-height', 64); s('rs-frames', 5); })()""")
        await page.click("#rs-passes-go")
        await page.wait_for_function("LokiRenderStudio.state.passes && LokiRenderStudio.state.passes.frames.length === 3", timeout=15000)
        prev = await E("[...document.querySelectorAll('#rs-ptabs .rs-ptab')].map((b) => b.dataset.kind).concat([!document.getElementById('rs-canvas').hidden, document.getElementById('rs-frame').max])")
        check("the passes show in the preview with a tab per pass and a frame scrubber", prev[:2] == ["depth", "lineart"] and prev[2] is True and prev[3] == "2", prev)
        await page.click("#rs-preflight")
        await page.wait_for_selector("#rs-report h4", timeout=5000)
        rep = await E("document.getElementById('rs-report').innerText")
        link = await E("(document.querySelector('#rs-report .rs-missing a') || {}).href || ''")
        check("Preflight shows the report: not ready, the missing model with its ComfyUI folder and a download link, the GPU",
              "Not ready" in rep and "models/unet" in rep and "RTX 3070 Ti" in rep and link.startswith("https://huggingface.co/mickmumpitz/"), rep[:300])
        sent = [x[1] for x in posted if x[0] == "preflight"][-1]
        check("preflight sends only the graph's verified parameters", set(sent["params"]) <= set(WF["params"]) and sent["params"]["frames"] == 5, sent)
        await E("document.getElementById('rs-pass-normal').checked = false; document.getElementById('rs-pass-beauty').checked = false")
        await E("window.confirm = () => true")
        # a job: new -> passes uploaded -> preflight (stub says not ready) -> the job waits
        await page.click("#rs-render")
        await page.wait_for_function("document.getElementById('rs-info').textContent.includes('Preflight found problems')", timeout=15000)
        ups = [x for x in posted if x[0] == "pass"]
        kinds = sorted({q.split("pass=")[1].split("&")[0] for q, _b in [(u[1], u[2]) for u in ups]})
        check("Render sends every pass frame as a PNG to /render/upload-pass (depth + line art, 3 frames each)",
              len(ups) == 6 and kinds == ["depth", "lineart"] and all(u[2][:4] == b"\x89PNG" for u in ups), [u[1] for u in ups])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
