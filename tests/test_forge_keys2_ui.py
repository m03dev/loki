"""Key and Playback rows (Maya): Set Key on Translate / Rotate / Scale key just those channels; Cut Keys takes them
off and Paste Keys puts them back; Next / Prev Frame step by one; Backward plays the other way; Playback Looping
once stops at the end, oscillate turns round, continuous wraps. Under a minute.

    python tests/test_forge_keys2_ui.py
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

        await E("forgeProRun(forge.view, 'cube')"); await page.wait_for_timeout(150)
        K = "Object.keys(forge.view.tree.api.active().keys || {}).sort()"
        await E("forgeProRun(forge.view, 'keyTranslate')")
        check("Set Key on Translate: the three translate channels only", await E(K) == ["translate0", "translate1", "translate2"], await E(K))
        await E("forgeProRun(forge.view, 'keyRotate')")
        await E("forgeProRun(forge.view, 'keyScale')")
        check("... then Rotate and Scale: nine channels", len(await E(K)) == 9, await E(K))
        await E("forge.view.undo()")
        check("one undo takes back only the Scale keys", len(await E(K)) == 6, await E(K))
        await E("forgeProRun(forge.view, 'keyAnimated')")
        check("Set Key on Animated: keys only the six channels already animated (no scale)", len(await E(K)) == 6 and not any(k.startswith("scale") for k in await E(K)), await E(K))
        await E("forgeProRun(forge.view, 'cutKeys')")
        check("Cut Keys: no keys left", await E(K) == [])
        await E("forgeProRun(forge.view, 'pasteAnim')")
        check("Paste Keys puts them back", len(await E(K)) == 6, await E(K))
        F = "forge.view.tree.time.frame"
        await E("forge.view.tree.api.setRange(1, 10); forge.view.tree.api.setFrame(5)")
        await E("forgeProRun(forge.view, 'nextFrame')"); f1 = await E(F)
        await E("forgeProRun(forge.view, 'prevFrame'); forgeProRun(forge.view, 'prevFrame')"); f2 = await E(F)
        check("Next Frame / Prev Frame step one frame", f1 == 6 and f2 == 4, (f1, f2))
        # drive the clock by hand: tickTime reads the real time, so wait between ticks
        async def run_for(ms):          # the Time Slider's clock, ticked by hand every 40 ms (no render loop here)
            await E("forge.view.tickTime()")
            for _ in range(ms // 40):
                await page.wait_for_timeout(40)
                await E("forge.view.tickTime()")
            return await E("[+forge.view.tree.time.frame.toFixed(2), forge.view.tree.time.playing, forge.view.tree.time.dir || 1]")
        await E("forgeProRun(forge.view, 'playStop'); forge.view.tree.api.setFrame(8); forgeProRun(forge.view, 'playBack')")
        st = await run_for(150)
        check("Backward: the frame goes down", st[1] and st[0] < 8, st)
        await E("forgeProRun(forge.view, 'playStop'); forgeProRun(forge.view, 'loopOnce'); forge.view.tree.api.setFrame(9); forgeProRun(forge.view, 'playPause')")
        st = await run_for(700)
        check("Looping Once: it stops at the end (frame 10)", st[0] == 10 and not st[1], st)
        await E("forgeProRun(forge.view, 'loopOscillate'); forge.view.tree.api.setFrame(9.5); forgeProRun(forge.view, 'playPause')")
        st = await run_for(700)
        check("Looping Oscillate: at the end it turns round and plays backward", st[1] and st[2] == -1 and st[0] < 10, st)
        await E("forgeProRun(forge.view, 'playStop'); forgeProRun(forge.view, 'loopContinuous'); forge.view.tree.api.setFrame(9.5); forgeProRun(forge.view, 'playPause')")
        st = await run_for(700)
        check("Looping Continuous: past the end it wraps to the start", st[1] and st[0] < 9, st)
        await E("forgeProRun(forge.view, 'playStop')")
        ids = ("keyTranslate", "keyRotate", "keyScale", "keyAnimated", "cutKeys", "playBack", "playStop", "nextFrame", "prevFrame", "loopOnce", "loopOscillate", "loopContinuous")
        miss = await E("(ids) => ids.filter((id) => !JSON.stringify(FORGE_MAYA).includes('\"' + id + '\"'))", list(ids))
        check("the Animation menu set's Key and Playback menus list the new rows", miss == [], miss)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
