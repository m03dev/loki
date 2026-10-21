"""Forge's pro Channel Box in headless Chromium: a Rotate Order channel that keeps the orientation, per-channel
lock / hide driven from the row's right-click menu, custom attributes added from the Edit menu, and Tab moving
to the next value field. Under a minute.

    python tests/test_forge_channel_ui.py
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
T = "forge.view.tree.api"


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
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-hotkeys')")
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree", timeout=10000)
        E = page.evaluate

        async def menu_on(sel):
            await E("document.querySelector(%r).dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}))" % sel)
            await page.wait_for_timeout(60)
            return await E("[...document.querySelectorAll('.forge-pm-pop .forge-pm-item')].map((b) => b.textContent.trim())")

        async def click_menu(text):
            return await E("[...document.querySelectorAll('.forge-pm-pop .forge-pm-item')].find((b) => b.textContent.includes(%r))?.click()" % text)

        # --- rotate order keeps the orientation
        orders = await E("[...document.querySelectorAll('#forge-ch-order option')].map((o) => o.value)")
        await E("%s.setTransform(null, 'rotate', 0, 30); %s.setTransform(null, 'rotate', 1, 20);" % (T, T))
        before = await E("[forge.view.tree.byId[%s.active().id].grp.quaternion.toArray(), forge.view.tree.byId[%s.active().id].rotOrder]" % (T, T))
        await E("const s = document.getElementById('forge-ch-order'); s.value = 'YZX'; s.dispatchEvent(new Event('change', {bubbles:true}));")
        await page.wait_for_timeout(60)
        after = await E("[forge.view.tree.byId[%s.active().id].grp.quaternion.toArray(), forge.view.tree.byId[%s.active().id].rotOrder, forge.view.tree.byId[%s.active().id].grp.rotation.order]" % (T, T, T))
        same_orient = all(abs(a - b) < 1e-5 for a, b in zip(before[0], after[0]))
        check("Rotate Order channel has the 6 orders and changing it keeps the orientation",
              orders == ["XYZ", "YZX", "ZXY", "XZY", "YXZ", "ZYX"] and same_orient and after[1] == "YZX" and after[2] == "YZX", [orders, before, after])

        # --- lock a channel from its right-click menu; typing then does nothing
        items = await menu_on('#forge-channel [data-ch="translate0"]')
        await click_menu("Lock This Channel")
        await page.wait_for_timeout(40)
        await E("%s.setTransform(null, 'translate', 0, 5);" % T)
        await E("(() => { const i = document.getElementById('forge-ch-tx'); i.value = '9'; i.dispatchEvent(new Event('input', {bubbles:true})); })()")
        locked = await E("[document.getElementById('forge-ch-tx').readOnly, document.querySelector('#forge-channel [data-ch=\"translate0\"]').classList.contains('locked'), %s.transform().translate[0]]" % T)
        check("right-click locks a channel: the field is read-only and typing is ignored",
              "Lock This Channel" in items and locked == [True, True, 5], [items, locked])
        await menu_on('#forge-channel [data-ch="translate0"]')
        await click_menu("Unlock This Channel")
        await page.wait_for_timeout(40)

        # --- hide a channel, then reveal it from Show > Hidden Channels
        await menu_on('#forge-channel [data-ch="scale2"]')
        await click_menu("Hide This Channel")
        await page.wait_for_timeout(40)
        hidden = await E("document.querySelector('#forge-channel [data-ch=\"scale2\"]').hidden")
        await E("[...document.querySelectorAll('#forge-channel .forge-pm')].find((b) => b.textContent === 'Show').click()")
        await page.wait_for_timeout(40)
        await click_menu("Hidden Channels")
        await page.wait_for_timeout(40)
        shown = await E("document.querySelector('#forge-channel [data-ch=\"scale2\"]').hidden")
        check("right-click hides a channel and Show > Hidden Channels reveals it", hidden is True and shown is False, [hidden, shown])

        # --- custom attributes: Add Attribute, rename, delete
        await E("[...document.querySelectorAll('#forge-channel .forge-pm')].find((b) => b.textContent === 'Edit').click()")
        await page.wait_for_timeout(40)
        await click_menu("Add Attribute")
        await page.wait_for_timeout(60)
        made = await E("[!document.getElementById('forge-ch-attrhead').hidden, document.querySelectorAll('#forge-ch-attrs .forge-ch-attrrow').length, document.querySelector('#forge-ch-attrs .forge-ch-attrname').value]")
        await E("(() => { const i = document.querySelector('#forge-ch-attrs .forge-ch-attrname'); i.value = 'heat'; i.dispatchEvent(new Event('input', {bubbles:true})); })()")
        renamed = await E("%s.active().attrs[0].name" % T)
        await E("document.querySelector('#forge-ch-attrs .forge-ch-attrrow').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}))")
        await page.wait_for_timeout(40)
        await click_menu("Delete Attribute")
        await page.wait_for_timeout(60)
        gone = await E("document.querySelectorAll('#forge-ch-attrs .forge-ch-attrrow').length")
        check("Add Attribute makes a renameable custom channel; its right-click deletes it",
              made == [True, 1, "attr1"] and renamed == "heat" and gone == 0, [made, renamed, gone])

        # --- Tab hops to the next value field
        await E("document.getElementById('forge-ch-tx').focus(); document.getElementById('forge-ch-tx').select();")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(40)
        focus = await E("document.activeElement && document.activeElement.id")
        check("Tab moves to the next channel value field", focus == "forge-ch-ty", focus)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
