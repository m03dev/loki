"""Forge's Level workspace (app/ui/forge_level.js + forge_level_core.js): the engine's node suite
(tests/js/test_forge_level.js), the /forge level routes (engine/forge_api.py: .level save, /forge/levels), then in
headless Chromium: Workspace > Level, Place Actors into the Outliner, undo a placement, a Content Browser model
placed as an actor, a script on a Forge cube, Play (W walks, the script spins the cube, Esc stops and restores
everything), a broken script reported in Output without a page error, Alt+P, Save Level, Open Level.
Skips the browser part without node / Playwright. Under a minute.

    python tests/test_forge_level_ui.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


# ---------------------------------------------------------------- 1. the engine in node
node = shutil.which("node")
if node:
    r = subprocess.run([node, str(REPO / "tests" / "js" / "test_forge_level.js")], capture_output=True, text=True, timeout=30)
    print(r.stdout.strip())
    check("the Level engine passes its node suite", r.returncode == 0, (r.stdout + r.stderr)[-400:])

# ---------------------------------------------------------------- 2. the server routes
import forge_api  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    forge_api.models_dir = lambda state: Path(tmp)          # the suite's own models/ folder
    st = types.SimpleNamespace()
    level = {"format": "loki-level", "version": 1, "actors": [{"id": 1, "type": "empty"}]}
    code, out = forge_api.save(st, "my level.level", json.dumps(level).encode())
    check("POST /forge/save takes a .level", code == 200 and out.get("ok") and (Path(tmp) / "my level.level").is_file(), out)
    code2, _ = forge_api.save(st, "my level.level", json.dumps(level).encode())
    check("a second save never overwrites (my level-2.level)", code2 == 200 and (Path(tmp) / "my level-2.level").is_file())
    bad, out3 = forge_api.save(st, "x.level", b'{"format": "something"}')
    check("a .level that is not a LOKI level is refused", bad == 400 and "level" in out3.get("error", ""), out3)
    c, listed = forge_api.handle_get(st, "/forge/levels")
    check("GET /forge/levels lists them with their actor counts",
          c == 200 and {i["name"] for i in listed["items"]} == {"my level.level", "my level-2.level"} and listed["items"][0]["actors"] == 1, listed)
    got = forge_api.handle_get(st, "/forge/file/my%20level.level")
    check("GET /forge/file serves a .level as JSON", got[0] == 200 and got[2] == "application/json", got[:1] + got[2:])


# ---------------------------------------------------------------- 3. the workspace in the window
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
        page = await browser.new_page(viewport={"width": 1500, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        files = {}          # what the fake server holds: name -> (bytes, type)
        saved = []

        async def route(r):
            bare = r.request.url.split("8894", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/forge/list":
                return await r.fulfill(json={"ok": True, "items": [{"name": n} for n in files if n.endswith(".glb")]})
            if bare == "/forge/levels":
                return await r.fulfill(json={"ok": True, "items": [{"name": n, "actors": len(json.loads(b)["actors"])}
                                                                   for n, (b, _) in files.items() if n.endswith(".level")]})
            if bare.startswith("/forge/file/"):
                name = bare[len("/forge/file/"):].replace("%20", " ")
                if name in files:
                    return await r.fulfill(body=files[name][0], content_type=files[name][1])
                return await r.fulfill(status=404, json={"ok": False})
            if bare == "/forge/save" and r.request.method == "POST":
                name = r.request.url.split("name=", 1)[1].split("&")[0]
                body = r.request.post_data_buffer
                saved.append((name, body))
                files[name] = (body, "application/json")
                return await r.fulfill(json={"ok": True, "name": name})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("['loki-forge-workspace'].forEach((k) => localStorage.removeItem(k))")
        await E("document.getElementById('open-forge').click()")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree && document.getElementById('forge-workspace')", timeout=15000)

        # a model for the Content Browser, exported by three.js itself
        glb = await E("""(async () => {
          const T = forge.view.THREE, { GLTFExporter } = await import('/ui/vendor/three/addons/exporters/GLTFExporter.js');
          const m = new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial()); m.name = 'crate';
          const buf = await new GLTFExporter().parseAsync(m, { binary: true });
          let s = ''; new Uint8Array(buf).forEach((b) => s += String.fromCharCode(b)); return btoa(s); })()""")
        files["20261024-120000-crate.glb"] = (base64.b64decode(glb), "model/gltf-binary")

        await page.select_option("#forge-workspace", "level")
        await page.wait_for_timeout(300)
        shown = await E("[!document.getElementById('forge-levelpanel').hidden, document.querySelectorAll('#forge-levelpanel [data-lv^=place-]').length,"
                        " document.querySelector('#forge .forge-body').classList.contains('ws-level')]")
        check("Workspace > Level shows the Level panel with all 7 actor types", shown == [True, 7, True], shown)
        menus = await E("FORGE_PRO_SETS.level && FORGE_PRO_SETS.level.menus.includes('Level') && FORGE_PRO_MENUS.Level.length > 5")
        check("the Level menu set has a Level menu (Play, Simulate, Stop, Place Actors, Save)", menus)

        count0 = await E("forge.view.tree.api.sceneNodes().length")
        for t in ("playerStart", "triggerBox", "pointLight"):
            await E("document.querySelector('#forge-levelpanel [data-lv=place-%s]').click()" % t)
            await page.wait_for_timeout(80)
        placed = await E("forge.view.tree.api.sceneNodes().filter((n) => n.kind === 'actor').map((n) => [n.name, n.actor])")
        check("Place Actors puts Outliner nodes in the scene", [a for _, a in placed] == ["playerStart", "triggerBox", "pointLight"]
              and await E("forge.view.tree.api.sceneNodes().length") == count0 + 3, placed)
        await E("forge.view.tree.api.node(forge.view.tree.api.sceneNodes().find((n) => n.actor === 'triggerBox').id).grp.position.set(0, 0, -3)")
        await E("document.querySelector('#forge-levelpanel [data-lv=place-empty]').click()")
        await page.wait_for_timeout(80)
        n1 = await E("forge.view.tree.api.sceneNodes().length")
        await E("forgeProRun(forge.view, 'undo')")
        n2 = await E("forge.view.tree.api.sceneNodes().length")
        await E("forgeProRun(forge.view, 'redo')")
        n3 = await E("forge.view.tree.api.sceneNodes().length")
        check("placing an actor is one undo step (undo removes it, redo brings it back)", n2 == n1 - 1 and n3 == n1, [n1, n2, n3])

        await E("ForgeLevelUI.refresh()")
        await page.wait_for_selector("#forge-levelpanel [data-asset='20261024-120000-crate.glb']", timeout=5000)
        await E("document.querySelector(\"#forge-levelpanel [data-asset='20261024-120000-crate.glb']\").click()")
        await page.wait_for_function("forge.view.tree.api.sceneNodes().some((n) => n.actor === 'mesh')", timeout=5000)
        asset = await E("(() => { const n = forge.view.tree.api.sceneNodes().find((n) => n.actor === 'mesh'); return [n.name, ForgeLevel.actorOf(n.grp).asset, !!n.grp.getObjectByName('asset')]; })()")
        check("Content Browser: a models/ .glb is placed as a mesh actor that remembers its file", asset[1] == "20261024-120000-crate.glb" and asset[2], asset)

        # a Forge cube with the starter script (it spins while playing)
        await E("forgeProRun(forge.view, 'cube')")
        await page.wait_for_timeout(250)
        await E("ForgeLevelUI.details()")
        await E("document.querySelector('#forge-levelpanel [data-lv=addscript]').click()")
        cube = await E("(() => { const n = forge.view.tree.api.active(); return [n.name, ForgeLevel.actorOf(n.grp).scripts.length, !!document.querySelector('#forge-levelpanel .flv-code')]; })()")
        check("Details > Add Script makes a Forge object an actor with a script editor", cube[1] == 1 and cube[2], cube)
        await E("window.__cubeId = forge.view.tree.api.active().id")

        # Play: possess the Player Start, walk with W, the script spins the cube; Esc stops and restores
        before = await E("(() => { const g = forge.view.tree.api.node(__cubeId).grp; return [g.rotation.y, forge.view.scene.children.length]; })()")
        await E("document.querySelector('#forge-levelpanel [data-lv=play]').click()")
        await page.wait_for_timeout(200)
        playing = await E("[!!forge.view.playing, !forge.view.transform.object, ForgeLevelUI.state.session && !!ForgeLevelUI.state.session.player]")
        check("Play: the view plays, the manipulator is away, the player is possessed", playing == [True, True, True], playing)
        z0 = await E("ForgeLevelUI.state.session.player.position.z")
        await page.keyboard.down("w")
        await page.wait_for_timeout(700)
        await page.keyboard.up("w")
        mid = await E("[ForgeLevelUI.state.session.player.position.z, forge.view.tree.api.node(__cubeId).grp.rotation.y]")
        check("W walks the player forward and the cube's script runs every frame", mid[0] < z0 - 0.5 and mid[1] > 0.1, [z0, mid])
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
        after = await E("(() => { const g = forge.view.tree.api.node(__cubeId).grp; return [g.rotation.y, forge.view.scene.children.length, !!forge.view.playing, !forge.view.scene.getObjectByName('Player')]; })()")
        check("Esc stops: the cube is back, the player is gone, the scene is as before", after == [before[0], before[1], False, True], [before, after])

        # a broken script: reported in Output, Play goes on, no page error
        await E("ForgeLevel.actorOf(forge.view.tree.api.node(__cubeId).grp).scripts.push({ name: 'broken', source: 'function update(dt) { nope(); }' })")
        await E("ForgeLevelUI.play(false)")
        await page.wait_for_timeout(300)
        out = await E("[!!forge.view.playing, document.querySelector('#forge-levelpanel .flv-log').textContent]")
        await E("ForgeLevelUI.stop()")
        check("a script that throws is reported in Output and Simulate keeps running", out[0] and "nope" in out[1] and "broken" in out[1], out)
        await E("ForgeLevel.actorOf(forge.view.tree.api.node(__cubeId).grp).scripts.pop()")

        # Alt+P: Unreal's Play key (Forge's hotkey table)
        await E("document.activeElement && document.activeElement.blur()")
        await page.mouse.move(500, 400)
        await page.keyboard.press("Alt+p")
        await page.wait_for_timeout(200)
        hot = await E("!!forge.view.playing")
        await E("ForgeLevelUI.stop()")
        check("Alt+P plays", hot, hot)

        # Save Level, then Open it (adds its actors again)
        await E("ForgeLevelUI.save('testlevel')")
        await page.wait_for_timeout(200)
        doc = json.loads(saved[-1][1]) if saved else {}
        types_saved = sorted(a["type"] for a in doc.get("actors", []))
        check("Save Level posts a loki-level with every actor and its scripts",
              saved and saved[-1][0] == "testlevel.level" and doc.get("format") == "loki-level"
              and types_saved == ["empty", "mesh", "mesh", "playerStart", "pointLight", "triggerBox"]
              and any(a["scripts"] for a in doc["actors"]), types_saved)
        k0 = await E("forge.view.tree.api.sceneNodes().filter((n) => n.kind === 'actor').length")
        await E("ForgeLevelUI.refresh()")
        await page.wait_for_selector("#forge-levelpanel [data-level='testlevel.level']", timeout=5000)
        await E("document.querySelector(\"#forge-levelpanel [data-level='testlevel.level']\").click()")
        await page.wait_for_function("document.querySelector('#forge-levelpanel .flv-status').textContent.startsWith('Opened')", timeout=8000)
        k1 = await E("forge.view.tree.api.sceneNodes().filter((n) => n.kind === 'actor').length")
        trig = await E("(() => { const t = forge.view.tree.api.sceneNodes().filter((n) => n.actor === 'triggerBox').pop(); return t.grp.position.z; })()")
        check("Open Level brings its actors back (the modeled cube without a file is skipped), transforms included",
              k1 == k0 + 5 and abs(trig + 3) < 1e-6, [k0, k1, trig])

        await page.select_option("#forge-workspace", "model")
        hid = await E("document.getElementById('forge-levelpanel').hidden")
        check("back to Modeling hides the Level panel", hid, hid)
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(ui(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
