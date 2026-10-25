"""Every menu, popover and dialog in LOKI's window stays on screen, and the mode tabs live in the title strip.

The owner (2026-10-17): "sometimes the menus open but there's not enough screen space so I can't click on them; things
should be a % so it always adjusts", and the tabs belong in the window's title bar. Headless Chromium at 900x600, half a
1080p screen (960x1040) and 1920x1080, against a fake engine: open the chat model menu, the chat menu, the mode picker,
the / palette, a right-click menu, a Settings model picker, Settings and Files - each must be fully inside the window and
its last item clickable (elementFromPoint hits it). The title strip: present, holds the tabs, its empty parts drag the
window (.pywebview-drag-region) and the tab buttons do not. LOKI_TITLEBAR is a Settings > General choice. < 60 s.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
# pywebview's drag script with the values LOKI's window gets (app/loki_app.py sets DRAG_REGION_DIRECT_TARGET_ONLY);
# from a checkout at ../ext/pywebview or the installed package; skipped when neither is here.
def _pywebview_drag() -> str:
    for base in (REPO.parent / "ext" / "pywebview" / "webview", ):
        f = base / "js" / "customize.js"
        if f.is_file():
            break
    else:
        try:
            import webview  # noqa: F401  pylint: disable=import-outside-toplevel
            f = Path(webview.__file__).parent / "js" / "customize.js"
        except Exception:  # noqa: BLE001
            return ""
    if not f.is_file():
        return ""
    return f.read_text(encoding="utf-8") % {"text_select": "True", "drag_selector": ".pywebview-drag-region",
                                             "drag_region_direct_target_only": "True", "zoomable": "True",
                                             "draggable": "True", "easy_drag": "False"}


PYWEBVIEW_DRAG = _pywebview_drag()

PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %s" % (detail,)))


src = (REPO / "engine" / "portal_api.py").read_text(encoding="utf-8")
check("LOKI_TITLEBAR custom|native is in Settings > General", '"LOKI_TITLEBAR": {"kind": "choice", "choices": ["custom", "native"]' in src)
app_py = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
check("macOS: the window is made frameless at creation (full-size content, transparent bar), easy_drag off, "
      "the traffic lights shown again before it appears",
      '{"frameless": True, "easy_drag": False}' in app_py and "standardWindowButton_(button).setHidden_(False)" in app_py
      and "events.before_show += lambda: mac_buttons(win)" in app_py and 'titlebar_mode() == "custom"' in app_py)
check("only the bare strip drags the window (pywebview DRAG_REGION_DIRECT_TARGET_ONLY)",
      'webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True' in app_py)
check("double-click on the strip maximises/restores through a tiny js_api", "def toggle_maximize" in app_py and "js_api=WindowApi()" in app_py)
check("Windows: frameless with LOKI's strip as the title bar (LOKI_TITLEBAR=native keeps the system frame)",
      'sys.platform == "win32" and titlebar_mode() == "custom"' in app_py and "if (mac_strip or win_strip)" in app_py
      and "&titlebar=win" in app_py)
sys.path.insert(0, str(REPO / "app"))
import loki_app  # noqa: E402


class _Handle:
    def ToInt64(self):
        return 4242


class _Form:
    Handle = _Handle()
    InvokeRequired = False


class _User32:
    def __init__(self):
        self.sent = []

    def ReleaseCapture(self):
        self.sent.append("release")

    def SendMessageW(self, hwnd, msg, wparam, lparam):
        self.sent.append((hwnd, msg, wparam, lparam))


u = _User32()
ok_move = loki_app.win_hit(type("W", (), {"native": _Form()})(), "move", user32=u)
ok_se = loki_app.win_hit(type("W", (), {"native": _Form()})(), "se", user32=u)
check("Windows: the strip hands a press to Windows' own move (HTCAPTION) and resize (HTBOTTOMRIGHT)",
      ok_move and ok_se and u.sent == ["release", (4242, 0xA1, 2, 0), "release", (4242, 0xA1, 17, 0)], u.sent)
check("Windows: an unknown edge or no window does nothing", not loki_app.win_hit(None, "move", user32=u)
      and not loki_app.win_hit(type("W", (), {"native": _Form()})(), "x", user32=u))
index = (UI / "index.html").read_text(encoding="utf-8")
check("place.js is loaded before app.js (it reads the titlebar flag first)",
      index.index('src="/ui/place.js"') < index.index('src="/ui/app.js"'))
for f in ("app.js", "settings.js", "chat_plus.js", "clipboard.js", "modes.js", "workbench.js"):
    check("%s places its menu with LokiPlace" % f, "LokiPlace." in (UI / f).read_text(encoding="utf-8"))

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None
chromium = next((p for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if p and Path(p).exists()), "")

MODELS = {"ok": True, "current": "smart", "resolved_label": "x", "groups": [{"id": "auto", "label": "Automatic"}, {"id": "cloud", "label": "Cloud"}],
          "entries": [{"name": "smart", "label": "Smart", "group": "auto", "ready": True}]
          + [{"name": "m%d" % i, "label": "Model number %d" % i, "group": "cloud", "ready": True, "model": "vendor/model-%d" % i} for i in range(40)]}
PROVIDERS = {"ok": True, "groups": [{"id": "cloud", "label": "Cloud"}], "connected": 1, "default": "groq", "active": "groq",
             "providers": [{"id": "groq", "name": "Groq", "group": "cloud", "available": True, "configured": True, "has_key": True,
                            "enabled": True, "model": "llama", "env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1"}]}
FAKE = {
    "/health": {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "", "route": [],
                "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []},
    "/models": MODELS, "/providers": PROVIDERS,
    "/providers/models": {"ok": True, "models": ["vendor/model-%d" % i for i in range(80)]},
    "/personas": {"ok": True, "modes": [{"id": "p%d" % i, "name": "Mode %d" % i, "description": "What mode %d does, at some length" % i, "icon": "*"} for i in range(14)]},
    "/files/list": {"ok": True, "crumbs": [{"name": "workspace", "dir": ""}], "entries": [{"name": "f%d.txt" % i, "path": "f%d.txt" % i, "kind": "file", "size": 10} for i in range(60)]},
    "/files/recent": {"ok": True, "recent": []},
    "/world": {"ok": True, "agents": [], "machines": [], "self": {"name": "test"}, "creations": {"count": 0, "latest": []}},
}

JS_INSIDE = """(sel) => { const els = [...document.querySelectorAll(sel)].filter(e => !e.hidden && e.offsetParent !== null || (e.style && e.style.position === 'fixed' && !e.hidden));
  const e = els[els.length - 1]; if (!e) return {found: false};
  const r = e.getBoundingClientRect(); const W = innerWidth, H = innerHeight;
  const kids = [...e.querySelectorAll('button, [role=option], [role=menuitem], [role=menuitemradio], .mpick-item, .wb-item')].filter(k => k.offsetParent !== null);
  const last = kids[kids.length - 1]; let hit = null;
  if (last) { last.scrollIntoView({block: 'nearest'}); const lr = last.getBoundingClientRect();
    const x = Math.min(W - 1, Math.max(0, lr.left + lr.width / 2)), y = Math.min(H - 1, Math.max(0, lr.top + lr.height / 2));
    const at = document.elementFromPoint(x, y); hit = !!at && (at === last || last.contains(at)); }
  return {found: true, inside: r.left >= -0.5 && r.top >= -0.5 && r.right <= W + 0.5 && r.bottom <= H + 0.5,
          rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)], W, H, items: kids.length, lastClickable: hit}; }"""


def run(pw, size, mac):
    b = pw.chromium.launch(**({"executable_path": chromium} if chromium else {}))
    page = b.new_page(viewport={"width": size[0], "height": size[1]})
    page.set_default_timeout(4000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def route(r):
        p = r.request.url.split("8896", 1)[1].split("?")[0].split("#")[0]
        if p == "/":
            return r.fulfill(path=str(UI / "index.html"))
        if p.startswith("/ui/"):
            f = UI / p[4:]
            return r.fulfill(path=str(f)) if f.is_file() else r.fulfill(json={"ok": True})
        if p == "/settings/general":
            return r.fulfill(json={"ok": True, "settings": {"LOKI_TITLEBAR": {"kind": "choice", "choices": ["custom", "native"], "default": "custom", "label": "Title bar"}},
                                   "values": {"LOKI_TITLEBAR": "custom"}, "secrets_saved": {}})
        return r.fulfill(json=FAKE.get(p, {"ok": True}))

    page.route("http://127.0.0.1:8896/**", route)
    win = mac == "win"
    page.goto("http://127.0.0.1:8896/#token=t" + ("&titlebar=win" if win else "&titlebar=mac" if mac else ""))
    page.wait_for_function("window.LOKI_READY === true", timeout=15000)
    page.wait_for_timeout(600)
    if PYWEBVIEW_DRAG and not win:
        page.evaluate("() => { window.pywebview = {platform: 'cocoa', _jsApiCallback: () => {}}; }")
        page.add_script_tag(content=PYWEBVIEW_DRAG)
    tag = "%dx%d%s" % (size[0], size[1], " win" if win else " mac" if mac else "")

    strip = page.evaluate("""() => { const s = document.getElementById('titlestrip'); if (!s) return null; const r = s.getBoundingClientRect();
        const tabs = [...s.querySelectorAll('.modebar-tab')]; const shell = document.querySelector('.shell').getBoundingClientRect();
        const banner = document.getElementById('update-banner'); banner.hidden = false; const br = banner.getBoundingClientRect(); banner.hidden = true;
        const side = document.querySelector('.sidebar').getBoundingClientRect();
        return {top: r.top, h: r.height, w: r.width, tabs: tabs.length, drag: [...s.querySelectorAll('.titlestrip-side')].every(x => x.classList.contains('pywebview-drag-region')),
          center: tabs.length ? (tabs[0].getBoundingClientRect().left + tabs[tabs.length - 1].getBoundingClientRect().right) / 2 : 0,
          tabsDrag: tabs.some(t => t.classList.contains('pywebview-drag-region') || t.closest('.modebar').classList.contains('pywebview-drag-region')),
          firstTab: tabs[0] ? tabs[0].getBoundingClientRect().left : 0, shellTop: shell.top, bannerTop: br.top, sideTop: side.top,
          mac: document.documentElement.classList.contains('titlebar-mac')}; }""")
    check("[%s] the title strip spans the top with the 4 tabs (Home, Forge, Render, Godot)" % tag, strip and strip["top"] == 0 and 30 <= strip["h"] <= 44
          and strip["w"] == size[0] and strip["tabs"] == 4, strip)
    if not win:
        check("[%s] the strip drags the window, the tabs do not" % tag, strip and strip["drag"] and not strip["tabsDrag"], strip)
    else:   # Windows (2026-10-18 "the tabs are floating here"): frameless, the strip IS the title bar
        w = page.evaluate("""() => { const calls = []; window.pywebview = {_jsApiCallback: (n, a) => calls.push([n, ...a])};
            const down = (el) => el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, button: 0, detail: 1}));
            down(document.querySelector('.modebar-tab')); const afterTab = calls.length;
            down(document.querySelector('.titlestrip-side')); down(document.querySelector('.winedge-se'));
            const ctl = [...document.querySelectorAll('.titlestrip-side:last-child .winctl')];
            ctl.forEach((b) => b.click());
            const close = ctl[2] && ctl[2].getBoundingClientRect();
            return {afterTab, calls, ctl: ctl.map((b) => b.getAttribute('aria-label')), edges: document.querySelectorAll('.winedge').length,
              closeRight: close ? Math.round(close.right) : -1, win: document.documentElement.classList.contains('titlebar-win'),
              pyDrag: !!document.querySelector('.titlestrip .pywebview-drag-region')}; }""")
        check("[%s] Windows: LOKI's own minimise / maximise / close in the top-right corner" % tag,
              w["win"] and w["ctl"] == ["Minimise", "Maximise", "Close"] and w["closeRight"] == size[0], w)
        check("[%s] Windows: a press on a tab moves nothing; the empty strip and the edges go to Windows' own move/resize" % tag,
              w["afterTab"] == 0 and w["calls"][:2] == [["grab", "move"], ["grab", "se"]] and w["edges"] == 8 and not w["pyDrag"], w)
        check("[%s] Windows: the buttons minimise, maximise and close the window" % tag,
              [c[0] for c in w["calls"][2:]] == ["minimize", "toggle_maximize", "close"], w)
    check("[%s] the banner, the sidebar and the page start below the strip" % tag, strip and strip["shellTop"] >= strip["h"] - 0.5
          and strip["bannerTop"] >= strip["h"] - 0.5 and strip["sideTop"] >= strip["h"] - 0.5, strip)
    if mac and not win:
        check("[%s] on the Mac the tabs start after the traffic lights" % tag, strip["mac"] and strip["firstTab"] > 78, strip)
    check("[%s] the tabs sit in the centre of the top bar" % tag, strip and abs(strip["center"] - size[0] / 2) <= 4, strip)

    # pywebview's own drag script (webview/js/customize.js), as LOKI's window runs it: a press on a tab must never
    # move the window (the owner, 2026-10-17: "clicking it makes it run away from me"); a press on the empty strip does.
    moved = page.evaluate("""() => {
        const moves = []; window.pywebview = {_jsApiCallback: (name) => moves.push(name)};
        const fire = (el) => { const r = el.getBoundingClientRect(); const o = {bubbles: true, clientX: r.left + 3, clientY: r.top + 3, screenX: 10, screenY: 10};
            el.dispatchEvent(new MouseEvent('mousedown', o)); window.dispatchEvent(new MouseEvent('mousemove', {...o, screenX: 60, screenY: 40}));
            window.dispatchEvent(new MouseEvent('mouseup', o)); };
        const tabMoves = () => { const n = moves.length; fire(document.querySelector('.modebar-tab')); return moves.length - n; };
        const sideMoves = () => { const n = moves.length; fire(document.querySelector('.titlestrip-side:last-child')); return moves.length - n; };
        return {tab: tabMoves(), side: sideMoves()}; }""") if PYWEBVIEW_DRAG and strip and not win else None
    if moved is not None:
        check("[%s] clicking a tab never moves the window; dragging the empty strip does" % tag,
              moved["tab"] == 0 and moved["side"] > 0, moved)

    def look(name, sel):
        res = page.evaluate(JS_INSIDE, sel)
        check("[%s] %s is fully on screen" % (tag, name), res.get("found") and res.get("inside"), res)
        if res.get("items"):
            check("[%s] %s: its last item can be clicked" % (tag, name), res.get("lastClickable"), res)

    def close():
        page.keyboard.press("Escape")
        page.evaluate("document.body.click(); typeof summon === 'function' && summon(true)")
        page.wait_for_timeout(150)

    page.click("#prompt")
    page.wait_for_timeout(200)
    page.click("#model-button")
    page.wait_for_timeout(300)
    look("the chat model menu (40 models)", "#model-menu")
    close()
    if page.query_selector("#chat-menu-btn"):
        page.click("#chat-menu-btn")
        page.wait_for_timeout(200)
        look("the chat menu", ".chat-menu")
        close()
    if page.query_selector("#mode-pick"):
        page.evaluate("LokiModes.refresh && LokiModes.refresh()")
        page.wait_for_timeout(200)
        page.click("#mode-pick")
        page.wait_for_timeout(200)
        look("the mode picker (14 modes)", ".mode-menu")
        close()
    page.focus("#prompt")
    page.keyboard.type("/")
    page.wait_for_timeout(300)
    look("the / command palette", ".wb-menu")
    page.keyboard.press("Escape")
    page.evaluate("document.getElementById('prompt').value = ''")
    box = page.query_selector("#prompt").bounding_box()
    page.mouse.click(box["x"] + 5, box["y"] + 5, button="right")
    page.wait_for_timeout(200)
    look("the right-click menu", ".clip-menu")
    close()
    page.click("#open-settings")
    page.wait_for_timeout(400)
    look("Settings", "#settings .sheet-panel")
    page.click('[data-tab="connections"]')
    page.wait_for_timeout(500)
    btn = page.query_selector(".mpick-btn")
    if btn:
        btn.scroll_into_view_if_needed()
        btn.click()
        page.wait_for_timeout(500)
        look("a Settings model picker (80 models)", ".mpick-pop")
        page.keyboard.press("Escape")
    else:
        print("  (no model picker on this fake Connections page)")
    page.keyboard.press("Escape")
    page.evaluate("document.getElementById('settings').hidden = true")
    page.click("#open-files")
    page.wait_for_timeout(300)
    look("Files", "#files .sheet-panel")
    check("[%s] no script errors" % tag, not errors, errors[:3])
    b.close()


if sync_playwright is None:
    print("SKIP the window checks: no Playwright here")
else:
    with sync_playwright() as pw:
        for size, mac in (((900, 600), False), ((960, 1040), True), ((1920, 1080), "win")):
            if time.time() - T0 > 45:
                print("  SKIP %s: out of time" % (size,))
                continue
            try:
                run(pw, size, mac)
            except Exception as exc:  # noqa: BLE001
                check("the window at %s" % (size,), False, exc)

check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
