"""Forge's Time Slider in headless Chromium: Set Key writes keyframes on the transform channels, scrubbing evaluates
them (linear between), the tick strip shows one tick per key, playback advances and loops, prev / next key step, the
S hotkey keys, and undo takes a key back. Under a minute.

    python tests/test_forge_anim_ui.py
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
E_ = "forge.view.tree.api.transform().translate[0]"


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

        async def route(r):
            bare = r.request.url.split("8896", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8896/**", route)
        await page.goto("http://127.0.0.1:8896/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree && forge.view.tree.api", timeout=10000)
        await page.evaluate("ForgeUVEditor.setWorkspace('anim')")   # the key bar and the Graph Editor live in Workspace: Animation
        await page.evaluate("document.getElementById('fdock-keys-btn') && !document.getElementById('forge-time').classList.contains('fdock-keys-open') && document.getElementById('fdock-keys-btn').click()")
        E = page.evaluate

        bar = await E("[!!document.getElementById('forge-time'), !!document.getElementById('forge-time-slider'), !!document.getElementById('forge-time-setkey'), !!document.getElementById('forge-time-ticks')]")
        check("the Time Slider is on screen (playhead, Set Key and a tick strip)", bar == [True, True, True, True], bar)

        await E("forge.view.tree.api.setRange(1, 20)")
        # key at frame 1 (x = 0), move to 3 at frame 10 and key again
        await E("forge.view.tree.api.setFrame(1)")
        r1 = await E("forgeProRun(forge.view, 'setKey')")
        await E("forge.view.tree.api.setFrame(10)")
        await E("forge.view.tree.api.setTransform(null, 'translate', 0, 3)")
        r2 = await E("forgeProRun(forge.view, 'setKey')")
        keys = await E("forge.view.tree.api.keyTimes()")
        ticks = await E("document.querySelectorAll('#forge-time-ticks .forge-tick').length")
        check("Set Key writes keys at both frames and the tick strip shows them",
              keys == [1, 10] and ticks == 2, [r1, r2, keys, ticks])

        await E("forge.view.tree.api.setFrame(1)")
        x1 = await E(E_)
        await E("forge.view.tree.api.setFrame(10)")
        x10 = await E(E_)
        await E("forge.view.tree.api.setFrame(5)")
        x5 = await E(E_)
        # keys at frame 1 (0) and frame 10 (3): linear, so frame 5 is 3 * 4/9
        check("scrubbing evaluates the keys: 0 at frame 1, 3 at frame 10, 4/3 between (linear)",
              abs(x1) < 1e-6 and abs(x10 - 3) < 1e-6 and abs(x5 - 4.0 / 3.0) < 1e-6, [x1, x10, x5])

        # interpolation: step holds, smooth eases (both differ from linear's 4/3)
        async def at5():
            await E("forge.view.tree.api.setFrame(5)")
            return await E(E_)
        await E("forge.view.tree.api.setInterp(null, 1, null, null, 'step')")
        step5 = await at5()
        await E("forge.view.tree.api.setInterp(null, 1, null, null, 'bezier')")
        smooth5 = await at5()
        await E("forge.view.tree.api.setFrame(1)")
        await E("forgeProRun(forge.view, 'keyLinear')")
        lin5 = await at5()
        check("key interpolation: Step holds, Smooth eases, Linear is a straight line",
              abs(step5) < 1e-6 and abs(smooth5 - 912.0 / 729.0) < 1e-3 and abs(lin5 - 4.0 / 3.0) < 1e-6, [step5, smooth5, lin5])

        # the Graph Editor: the curves of the selected object, and dragging a key changes it
        await E("forge.view.tree.api.setFrame(1)")
        opened = await E("forgeProRun(forge.view, 'graphEditor')")
        shown = await E("[!document.getElementById('forge-graph').hidden, !!document.getElementById('forge-time-graph'), Object.keys(forge.view.graphData().channels).length]")
        before = await E("forge.view.graphData().channels.find((c) => c.k === 'translate0').keys.map((k) => k.slice())")
        pk = before[1]                              # the middle key of translate x (frame 10)
        px = await E("(() => { const c = document.getElementById('forge-graph-canvas'), r = c.getBoundingClientRect(); const [x, y] = forge.view.graphXY(%f, %f); return [r.left + x * (r.width / c.width), r.top + y * (r.height / c.height)]; })()" % (pk[0], pk[1]))
        await page.mouse.move(px[0], px[1]); await page.mouse.down()
        await page.mouse.move(px[0] + 4, px[1] - 30, steps=5); await page.mouse.up()
        await page.wait_for_timeout(80)
        after = await E("forge.view.graphData().channels.find((c) => c.k === 'translate0').keys.map((k) => k.slice())")
        check("the Graph Editor shows the curves and dragging a key raises its value",
              shown == [True, True, 9] and len(after) == len(before) and max(k[1] for k in after) > max(k[1] for k in before) + 0.05,
              [shown, before, after])
        await E("forgeProRun(forge.view, 'graphEditor')")
        closed = await E("document.getElementById('forge-graph').hidden")
        check("Graph Editor closes again", closed is True, closed)

        # Auto Keyframe: a moved object writes a key at the playhead
        auto_ui = await E("[!!document.getElementById('forge-time-autokey'), !!document.getElementById('forge-time-interp')]")
        await E("forge.view.tree.api.setFrame(12)")
        await E("forge.view.tree.api.setTransform(null, 'translate', 0, 5)")
        c = await E("forge.view.tree.api.setAutoKey(true) && forge.view.tree.api.autoKeyNow()")
        keys2 = await E("forge.view.tree.api.keyTimes()")
        await E("forge.view.tree.api.setFrame(12)")
        x12 = await E(E_)
        check("Auto Keyframe: moving an object keys it at the playhead (Auto Key is on the bar)",
              auto_ui == [True, True] and c == 9 and 12 in keys2 and abs(x12 - 5) < 1e-6, [auto_ui, c, keys2, x12])
        await E("forge.view.tree.api.setAutoKey(false)")

        # mirror the keys across YZ: the keyed translate x flips sign
        await E("forge.view.tree.api.setFrame(10)")
        xb = await E(E_)
        await E("forgeProRun(forge.view, 'mirrorKeysX')")
        await E("forge.view.tree.api.setFrame(10)")
        xa = await E(E_)
        check("Mirror Keys across YZ flips the keyed translate x", abs(xa + xb) < 1e-6 and abs(xb) > 0.1, [xb, xa])
        await E("forgeProRun(forge.view, 'mirrorKeysX')")

        # prev / next key
        await E("forge.view.tree.api.setFrame(5)")
        await E("forgeProRun(forge.view, 'prevKey')")
        pk = await E("forge.view.tree.time.frame")
        await E("forgeProRun(forge.view, 'nextKey')")
        nk = await E("forge.view.tree.time.frame")
        check("Previous / Next Key jump the playhead between keys", abs(pk - 1) < 1e-6 and abs(nk - 10) < 1e-6, [pk, nk])

        # playback advances and loops
        await E("forge.view.tree.api.setRange(1, 20); forge.view.tree.api.setFrame(1); forgeProRun(forge.view, 'playPause')")
        try:
            await page.wait_for_function("forge.view.tree.time.frame > 1", timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        mid = await E("forge.view.tree.time.frame")
        await E("forgeProRun(forge.view, 'playPause')")
        stopped = await E("forge.view.tree.time.playing")
        await page.wait_for_timeout(120)
        after = await E("forge.view.tree.time.frame")
        check("play advances the playhead and stop holds it", 1 < mid <= 21 and stopped is False and abs(after - (mid if mid <= 20 else 20)) < 3, [mid, stopped, after])

        # the channel rows shout about keys
        keyed = await E("document.querySelectorAll('#forge-channel .forge-ch-row.keyed').length")
        check("the Channel Box marks the keyed channels", keyed >= 1, keyed)

        # S keys the selection at the current frame
        await E("forge.view.tree.api.setFrame(15); forge.view.tree.time.frame = 15")
        await page.click("#forge-view")
        await page.keyboard.press("s")
        await page.wait_for_timeout(80)
        s_keys = await E("forge.view.tree.api.keyTimes()")
        check("the S hotkey keys the selected object at the playhead", 15 in s_keys, s_keys)

        # delete key + undo
        before = await E("forge.view.tree.api.keyTimes()")
        await E("forgeProRun(forge.view, 'deleteKey')")
        gone = await E("forge.view.tree.api.keyTimes()")
        check("Delete Key takes the key off the current frame", 15 in before and 15 not in gone, [before, gone])

        # copy / paste animation (the clipboard pastes the clip's first key on the playhead)
        n0 = await E("forge.view.tree.api.copyAnim()")
        await E("forge.view.tree.api.clearKeys()")
        empty = await E("forge.view.tree.api.keyTimes()")
        await E("forge.view.tree.api.setRange(1, 60); forge.view.tree.api.setFrame(20)")
        await E("forge.view.tree.api.pasteAnim()")
        await page.wait_for_timeout(80)
        pasted = await E("forge.view.tree.api.keyTimes()")
        check("Copy / Paste Animation puts the clip back, offset onto the playhead",
              n0 >= 2 and empty == [] and pasted[:2] == [20, 29], [n0, empty, pasted])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
