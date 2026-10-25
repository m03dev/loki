"""LOKI tests Forge: a QA sweep over every menu, button and command (owner 2026-10-22: "some [menu buttons] are not
functional and look weird, can't even click them ... start using loki to test the forge and everything").

What it does, in a real (headless) browser on the real UI:
  1. menus     opens every menu of the window's menu bar in every menu set and checks each row: on screen, the
               topmost thing under its middle (so a click lands on it), has a label, is not a dead "not in Forge yet"
               row, and its submenus open and fit on screen
  2. buttons   every button of the status line, tool box, panel bar and sculpt UI: visible ones must be clickable and
               not overlap each other
  3. hotbox    holds Space's hotbox and the Space wheel open and checks every menu name opens its list
  4. commands  runs EVERY command the menus offer, one by one, on a fresh cube (object, then component mode) and
               records page errors, "could not run" messages and commands that hang

The report is JSON (default: harness_data/qa/forge_qa.json, never committed) plus a short text summary. LOKI's QA
agents run it (engine/qa_team.py hands them the report) and file what it finds in LOKI_TASKS.md.

    python tools/forge_qa.py                 # everything (about a minute and a half on a slow box)
    python tools/forge_qa.py --only menus    # one part: menus, buttons, hotbox, commands
    python tools/forge_qa.py --out report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"

# commands the sweep must not run: they leave Forge, open the OS, or are the sweep's own plumbing
SKIP = {"close", "export", "saveObj", "save", "renderStudio", "hideUI", "more", "wheel", "quickMenu", "image",
        "imagePlane", "describe", "draw", "creature", "renderDialog", "renderPreview", "bakeMaps", "playPause"}

# the page side of the sweep: plain functions on window.__qa, so Python only drives and collects
QA_JS = r"""
window.__qa = {
  // is el the topmost thing at its middle (a click there lands on it), and on screen?
  hit(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return "zero-size";
    if (r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) return "off-screen";
    if (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1) return "clipped by the window";
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const top = document.elementFromPoint(x, y);
    if (!top) return "nothing under it";
    if (top !== el && !el.contains(top)) {
      const who = top.id ? "#" + top.id : (top.className && String(top.className).split(" ")[0]) || top.tagName;
      return "covered by " + who;
    }
    const cs = getComputedStyle(el);
    if (cs.pointerEvents === "none") return "pointer-events none";
    if (+cs.opacity < 0.2) return "invisible (opacity " + cs.opacity + ")";
    return "";
  },
  // a clean, light scene again: leave sculpt, delete everything, one fresh cube
  async reset() {
    const v = forge.view;
    try { if (v.mode === "sculpt") await forgeProRun(v, "sculptExit"); } catch (_) {}
    try { const t = v.tree && v.tree.api; if (t) { t.selectAll(); t.removeSelected(); } } catch (_) {}
    await forgeProRun(v, "cube");
    await new Promise((r) => setTimeout(r, 80));
  },
  heavy() { const v = forge.view; return !v.poly || v.poly.f.length > 3000 || v.mode === "sculpt"; },
  // bring el into view inside its nearest real scroller only (scrollIntoView also scrolls overflow:hidden panels,
  // which shifts the layout and makes false overlaps)
  reveal(el) {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      const sy = /(auto|scroll)/.test(cs.overflowY) && p.scrollHeight > p.clientHeight;
      const sx = /(auto|scroll)/.test(cs.overflowX) && p.scrollWidth > p.clientWidth;
      if (!sy && !sx) continue;
      const r = el.getBoundingClientRect(), q = p.getBoundingClientRect();
      if (sy) { if (r.top < q.top) p.scrollTop -= q.top - r.top; else if (r.bottom > q.bottom) p.scrollTop += r.bottom - q.bottom; }
      if (sx) { if (r.left < q.left) p.scrollLeft -= q.left - r.left; else if (r.right > q.right) p.scrollLeft += r.right - q.right; }
      return;
    }
  },
  label(el) { return (el.getAttribute("aria-label") || el.title || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 60); },
  closeAll() {
    try { if (typeof fmyCloseMenus === "function") fmyCloseMenus(); } catch (_) {}
    try { if (typeof forgeProHotboxHide === "function") forgeProHotboxHide(); } catch (_) {}
    try { if (typeof forgeProWheelClose === "function") forgeProWheelClose(); } catch (_) {}
    try { if (typeof forgeProMarkHide === "function") forgeProMarkHide(); } catch (_) {}
    for (const d of document.querySelectorAll(".fmy-drop, .fmy-sub")) d.remove();
  },
  // every row of an open drop-down (and its submenus, recursively)
  async auditDrop(path, out) {
    const drops = [...document.querySelectorAll(".fmy-drop")];
    const d = drops[drops.length - 1];
    if (!d) { out.push({ where: path, problem: "the menu did not open" }); return 0; }
    const dr = d.getBoundingClientRect();
    if (dr.bottom > innerHeight + 1 || dr.right > innerWidth + 1 || dr.left < -1 || dr.top < -1) {
      if (getComputedStyle(d).overflowY === "visible") out.push({ where: path, problem: "the menu runs off the window and does not scroll" });
    }
    let n = 0;
    const rows = [...d.children].filter((e) => e.matches(".fmy-ditem"));
    for (const b of rows) {
      n++;
      const lab = this.label(b.querySelector(".fmy-dlabel") || b);
      const where = path + " > " + lab;
      if (!lab) out.push({ where, problem: "a row with no label", id: b.dataset.proId });
      this.reveal(b);
      const h = this.hit(b);
      if (h) out.push({ where, problem: "cannot be clicked: " + h, id: b.dataset.proId });
      if (b.classList.contains("off")) out.push({ where, problem: "dead row: " + (b.title || "not in Forge yet"), id: b.dataset.proId });
      if (b.dataset.sub) {
        b.dispatchEvent(new PointerEvent("pointerenter", { bubbles: true }));
        b.click();
        await new Promise((r) => setTimeout(r, 30));
        const sub = [...document.querySelectorAll(".fmy-drop")].pop();
        if (!sub || sub === d) out.push({ where, problem: "the submenu does not open" });
        else { n += await this.auditDrop(where, out); sub.remove(); }
      }
    }
    // rows that overlap their neighbours
    for (let i = 1; i < rows.length; i++) {
      const a = rows[i - 1].getBoundingClientRect(), b = rows[i].getBoundingClientRect();
      if (b.top < a.bottom - 1 && a.height > 2 && b.height > 2) out.push({ where: path, problem: "rows overlap: " + this.label(rows[i - 1]) + " / " + this.label(rows[i]) });
    }
    return n;
  },
};
"""


async def boot(p, width=1300, height=860):
    exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
    args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
    browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
    page = await browser.new_page(viewport={"width": width, "height": height})
    errors: list = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

    async def route(r):
        bare = r.request.url.split("8892", 1)[1].split("#")[0].split("?")[0]
        if bare == "/":
            return await r.fulfill(path=str(UI / "index.html"))
        if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
            return await r.fulfill(path=str(UI / bare[4:]))
        return await r.fulfill(json={"ok": True})

    await page.route("http://127.0.0.1:8892/**", route)
    await page.goto("http://127.0.0.1:8892/#token=s3cret")
    await page.wait_for_function("window.LOKI_READY === true", timeout=30000)
    await page.evaluate("document.getElementById('open-forge').click()")
    await page.wait_for_selector("#forge:not([hidden])", timeout=8000)
    await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=20000)
    await page.add_script_tag(content=QA_JS)
    await page.evaluate("fmyRun('cube')")
    await page.wait_for_timeout(300)
    return browser, page, errors


async def audit_menus(page, report):
    out = report.setdefault("menus", [])
    sets = await page.evaluate("Object.keys(FORGE_PRO_SETS)")
    seen = set()
    rows = 0
    for key in sets:
        await page.evaluate("k => forgeMenuSet(k)", key)
        await page.wait_for_timeout(40)
        names = await page.evaluate("[...document.querySelectorAll('#fmy-menubar .fmy-mb')].map(b => b.dataset.menu)")
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            btn = page.locator('#fmy-menubar .fmy-mb[data-menu="%s"]' % name)
            h = await page.evaluate("n => __qa.hit(document.querySelector('#fmy-menubar .fmy-mb[data-menu=\"' + n + '\"]'))", name)
            if h:
                out.append({"where": "menu bar > " + name, "problem": "the menu name cannot be clicked: " + h})
                continue
            await btn.click()
            await page.wait_for_timeout(40)
            rows += await page.evaluate("async (n) => { const o = []; const k = await __qa.auditDrop(n, o); window.__qaOut = o; return k; }", name)
            out.extend(await page.evaluate("window.__qaOut"))
            await page.evaluate("__qa.closeAll()")
    await page.evaluate("forgeMenuSet('forge')")
    report["menu_rows_checked"] = rows
    return out


BUTTONS_JS = r"""(ws) => {
  const o = []; let n = 0;
  const sel = '#forge button, #fsc-head button, #fsc-side button, #fsc-strip button, .fmenu-torn button';
  // the view cube's far faces and its hover-only Home button are hidden on purpose; a leaf's twisty is empty
  const vis = [...new Set(document.querySelectorAll(sel))].filter((b) => b.offsetParent && b.getBoundingClientRect().width > 1
    && b.getBoundingClientRect().height > 1 && !b.closest('#fmy-cube') && !b.classList.contains('forge-out-tw'));
  for (const b of vis) {
    n++;
    const lab = ws + ': ' + (__qa.label(b) || b.dataset.proId || b.id || b.className);
    __qa.reveal(b);
    const h = __qa.hit(b);
    if (h) o.push({ where: lab, problem: 'cannot be clicked: ' + h, id: b.dataset.proId || '' });
    if (b.classList.contains('off') && b.dataset.proId) o.push({ where: lab, problem: 'dead button', id: b.dataset.proId || '' });
    if (!__qa.label(b) && !b.querySelector('svg, img, canvas')) o.push({ where: ws + ': ' + b.className, problem: 'a button with no label or icon' });
  }
  // buttons that sit on top of each other (one hides part of the other)
  for (const b of vis) __qa.reveal(b);
  // (only buttons that can be seen: one scrolled out of its row still has a box, under whatever is beside the row)
  const rs = vis.filter((b) => !__qa.hit(b)).map((b) => [b, b.getBoundingClientRect()]);
  for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
    const [a, p] = rs[i], [b, q] = rs[j];
    if (a.contains(b) || b.contains(a)) continue;
    const w = Math.min(p.right, q.right) - Math.max(p.left, q.left), h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
    if (w > 4 && h > 4) o.push({ where: ws + ': ' + __qa.label(a) + ' / ' + __qa.label(b), problem: 'buttons overlap (' + Math.round(w) + 'x' + Math.round(h) + ' px)' });
  }
  return { n, o };
}"""


async def audit_buttons(page, report):
    out = report.setdefault("buttons", [])
    total = 0
    for ws in ("model", "sculpt", "uv", "retopo", "bake", "mat", "anim"):
        try:
            await page.evaluate("ws => ForgeUVEditor.setWorkspace(ws)", ws)
        except Exception as exc:  # noqa: BLE001
            out.append({"where": ws, "problem": "the workspace does not open: " + str(exc)[:160]})
            continue
        await page.wait_for_timeout(900)             # panels slide into place: measure them settled
        res = await page.evaluate(BUTTONS_JS, ws)
        out.extend(res["o"])
        total += res["n"]
    await page.evaluate("ForgeUVEditor.setWorkspace('model')")
    report["buttons_checked"] = total
    return out


async def audit_hotbox(page, report):
    out = report.setdefault("hotbox", [])
    await page.evaluate("forgeProHotboxOpen(forge.view, [650, 430])")
    await page.wait_for_timeout(80)
    heads = await page.evaluate("[...document.querySelectorAll('#forge-pro-hotbox .forge-pro-row:not([hidden]) .forge-pro-head')].map(h => h.textContent)")
    for name in heads:
        res = await page.evaluate(r"""(n) => {
          const h = [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-row:not([hidden]) .forge-pro-head')].find((x) => x.textContent === n);
          const o = []; const hit = __qa.hit(h);
          if (hit) o.push({ where: 'hotbox > ' + n, problem: 'the menu name cannot be clicked: ' + hit });
          h.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 }));
          const list = h.parentElement.querySelector('.forge-pro-list');
          if (!list || list.hidden) o.push({ where: 'hotbox > ' + n, problem: 'the list does not open' });
          else {
            const walk = (l, path, depth) => {
              let k = 0;
              for (const it of l.querySelectorAll(':scope > .forge-pro-item')) {
                k++;
                __qa.reveal(it);
                const where = path + ' > ' + __qa.label(it.querySelector('.forge-pro-label') || it);
                const x = __qa.hit(it);
                if (x) o.push({ where, problem: 'cannot be clicked: ' + x, id: it.dataset.proId });
                if (it.classList.contains('off')) o.push({ where, problem: 'dead row', id: it.dataset.proId });
                if (it.dataset.proSub) {
                  it.click();
                  const fly = [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-fly')].find((f) => +f.dataset.depth === depth + 1);
                  if (!fly) o.push({ where, problem: 'the submenu does not fly out' });
                  else { k += walk(fly, where, depth + 1); forgeProFlyClose(document.getElementById('forge-pro-hotbox'), depth); }
                }
              }
              return k;
            };
            window.__qaRows = (window.__qaRows || 0) + walk(list, 'hotbox > ' + n, 0);
          }
          return o;
        }""", name)
        out.extend(res)
    await page.evaluate("__qa.closeAll()")
    # the Space wheel
    await page.evaluate("forgeProWheelOpen(forge.view, [650, 430])")
    await page.wait_for_timeout(60)
    res = await page.evaluate(r"""() => {
      const o = [];
      for (const w of document.querySelectorAll('#forge-pro-wheel .forge-wheel-wedge')) {
        const x = __qa.hit(w); if (x) o.push({ where: 'wheel > ' + w.textContent, problem: 'cannot be clicked: ' + x });
        w.click();
        const sub = document.querySelector('#forge-pro-wheel .forge-wheel-sub');
        if (!sub) { o.push({ where: 'wheel > ' + w.textContent, problem: 'the menu does not open' }); continue; }
        const walk = (path, depth) => {
          const items = [...sub.querySelectorAll('.forge-wheel-item')];
          for (const it of items) { __qa.reveal(it); const y = __qa.hit(it); if (y) o.push({ where: path + ' > ' + __qa.label(it), problem: 'cannot be clicked: ' + y }); }
          if (depth > 4) return;
          const subs = items.filter((it) => it.dataset.proSub).map((it) => it.dataset.proSub);
          for (const name of subs) {
            const it = [...sub.querySelectorAll('.forge-wheel-item')].find((x) => x.dataset.proSub === name);
            it.click(); walk(path + ' > ' + name, depth + 1);
            const back = sub.querySelector('[data-pro-back]'); if (back) back.click(); else o.push({ where: path + ' > ' + name, problem: 'no Back row in a wheel submenu' });
          }
        };
        walk('wheel > ' + w.textContent, 0);
      }
      return o;
    }""")
    out.extend(res)
    await page.evaluate("__qa.closeAll()")
    return out


async def audit_commands(page, errors, report, limit=None):
    out = report.setdefault("commands", [])
    ids = await page.evaluate(r"""() => {
      const s = new Set();
      const walk = (l) => { for (const x of l || []) { if (Array.isArray(x)) { if (Array.isArray(x[1])) walk(x[1]); else s.add(x[0]); } else if (typeof x === 'string' && !/^[-#]/.test(x)) s.add(x); } };
      for (const k of Object.keys(FORGE_PRO_MENUS)) walk(FORGE_PRO_MENUS[k]);
      return [...s].filter((id) => FORGE_PRO_CMDS[id]);
    }""")
    ids = [i for i in ids if i not in SKIP]
    dead = await page.evaluate("ids => ids.filter((id) => !FORGE_PRO_CMDS[id][1])", ids)
    report["commands_hidden_dead"] = dead          # not in Forge yet: the menus leave them out, so not a problem here
    ids = [i for i in ids if i not in dead][: limit or None]
    report["commands_total"] = len(ids)
    verbose = bool(os.getenv("FORGE_QA_VERBOSE"))
    for cid in ids:
        if verbose:
            print("  run", cid, flush=True)
        before = len(errors)
        t0 = time.time()
        try:
            res = await asyncio.wait_for(page.evaluate(r"""async (id) => {
              __qa.closeAll();
              const v = forge.view;
              try { if (v.edit && v.edit.mode && v.objectMode) v.objectMode(); } catch (_) {}
              const s = document.getElementById('forge-status'); if (s) { s.textContent = ''; s.classList.remove('bad'); }
              await forgeProRun(v, id);
              await new Promise((r) => setTimeout(r, 60));
              __qa.closeAll();
              // anything modal left open is closed the way a person would: Escape
              document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
              return { say: s ? s.textContent : '', bad: s ? s.classList.contains('bad') : false, dead: !FORGE_PRO_CMDS[id][1] };
            }""", cid), timeout=15)
        except asyncio.TimeoutError:
            out.append({"id": cid, "problem": "hangs (no answer in 15 s)"})
            continue
        except Exception as exc:  # noqa: BLE001
            out.append({"id": cid, "problem": "the page broke: " + str(exc)[:200]})
            continue
        new = errors[before:]
        label = await page.evaluate("id => FORGE_PRO_CMDS[id][0]", cid)
        if new:
            out.append({"id": cid, "label": label, "problem": "page error: " + new[0][:200]})
        elif res["dead"]:
            out.append({"id": cid, "label": label, "problem": "dead: " + res["say"][:160]})
        elif res["bad"] and "could not run" in res["say"]:
            out.append({"id": cid, "label": label, "problem": res["say"][:200]})
        if time.time() - t0 > 4:
            out.append({"id": cid, "label": label, "problem": "slow: %.1f s" % (time.time() - t0)})
        # a fresh, light cube whenever a command left a big mesh (a remesh) or none, so one command's result does not
        # slow or break the ones after it
        if await page.evaluate("__qa.heavy()"):
            try:
                await asyncio.wait_for(page.evaluate("__qa.reset()"), 30)
            except Exception:  # noqa: BLE001
                pass
    return out


def summary(report) -> str:
    lines = []
    total = 0
    for part in ("menus", "buttons", "hotbox", "commands"):
        items = report.get(part)
        if items is None:
            continue
        total += len(items)
        lines.append("%s: %d problem(s)" % (part, len(items)))
        for it in items[:60]:
            lines.append("  - %s: %s" % (it.get("where") or it.get("label") or it.get("id"), it["problem"]))
    lines.append("checked: %s menu rows, %s buttons, %s commands" % (report.get("menu_rows_checked", "-"), report.get("buttons_checked", "-"), report.get("commands_total", "-")))
    lines.insert(0, "Forge QA: %d problem(s)" % total)
    return "\n".join(lines)


async def run(only=None, out_path=None, limit=None, size=(1300, 860)):
    from playwright.async_api import async_playwright
    report: dict = {"when": time.strftime("%Y-%m-%d %H:%M:%S")}
    async with async_playwright() as p:
        browser, page, errors = await boot(p, *size)
        report["size"] = list(size)
        report["boot_errors"] = list(errors)
        parts = [only] if only else ["menus", "buttons", "hotbox", "commands"]
        for part in parts:
            try:
                if part == "menus":
                    await audit_menus(page, report)
                elif part == "buttons":
                    await audit_buttons(page, report)
                elif part == "hotbox":
                    await audit_hotbox(page, report)
                elif part == "commands":
                    await audit_commands(page, errors, report, limit)
            except Exception as exc:  # noqa: BLE001
                report.setdefault(part, []).append({"where": part, "problem": "the sweep itself failed: " + str(exc)[:300]})
        await browser.close()
    out = Path(out_path) if out_path else REPO / "harness_data" / "qa" / "forge_qa.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    report["file"] = str(out)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=["menus", "buttons", "hotbox", "commands"])
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--size", default="1300x860", help="the window, WIDTHxHEIGHT (try 900x1600 for a vertical monitor)")
    a = ap.parse_args(argv)
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Forge QA needs Playwright: pip install playwright")
        return 2
    w, h = (int(x) for x in a.size.lower().split("x"))
    report = asyncio.run(run(a.only, a.out, a.limit, (w, h)))
    print(summary(report))
    print("report:", report["file"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
