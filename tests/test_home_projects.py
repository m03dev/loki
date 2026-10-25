"""The home screen is the preview hub (owner, 2026-10-21: "preview projects we're working on in the home screen,
combine studio with home"; "it'll be the home ... where we do preview of render and other things").

    python tests/test_home_projects.py      (< 60 s; the window half skips without Playwright + Chromium)

1. engine/home_projects.py - GET /home/projects over a real bridge: renders (<data>/renders/<job>/manifest.json),
   Forge models (workspace models/*.glb), Godot projects (LOKI_PROJECTS_DIR), Studio sessions and jobs, newest first,
   each with {kind, name, path_or_id, updated, thumb, open}; one broken source never breaks the answer.
2. The window: three title-bar tabs + Render (Home / Forge / Render / Godot, Ctrl+1..4, no Studio or World tab),
   the hub's cards (thumbnail or kind icon, name, when; icons with tooltips; one row + All; jobs in a 'working' chip), the big preview, opening a card where
   it lives (Forge + its model, Godot + its project, Studio inside Home, Render), Studio's back / Esc / shortcut, an
   empty state that says how to make each kind, the chat still one click away, and it fits a small window.
"""
from __future__ import annotations

import asyncio
import base64
import http.client
import json
import os
import struct
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

T0 = time.time()
REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-home-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PROJECTS_DIR"] = str(TMP / "projects")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def glb() -> bytes:
    """The smallest valid glTF binary (one JSON chunk)."""
    js = json.dumps({"asset": {"version": "2.0"}}).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


# ------------------------------------------------------------------ fixtures: one of each kind
now = time.time()
data, ws = TMP / "data", TMP / "ws"
r1 = data / "renders" / "r-0001"
r1.mkdir(parents=True)
(r1 / "beauty.png").write_bytes(png(8, 6, (220, 160, 60)))
(r1 / "manifest.json").write_text(json.dumps({"name": "Castle at dusk", "kind": "path", "status": "done", "created": now - 60,
                                              "outputs": ["beauty.png"], "thumb": "beauty.png"}), encoding="utf-8")
r2 = data / "renders" / "r-0002"
r2.mkdir(parents=True)
(r2 / "manifest.json").write_text(json.dumps({"name": "AI pass", "kind": "comfyui", "status": "queued", "created": now - 30,
                                              "outputs": [], "thumb": "../../secret.png"}), encoding="utf-8")
(data / "renders" / "broken").mkdir()
(data / "renders" / "broken" / "manifest.json").write_text("{not json", encoding="utf-8")
(ws / "models" / ".meta").mkdir(parents=True)
(ws / "images").mkdir(parents=True)
(ws / "images" / "20261021-101010-a-fox.png").write_bytes(png(4, 4, (200, 90, 40)))
(ws / "models" / "20261021-101010-a-fox.glb").write_bytes(glb())
(ws / "models" / ".meta" / "20261021-101010-a-fox.glb.json").write_text(json.dumps(
    {"prompt": "a fox", "image": str(ws / "images" / "20261021-101010-a-fox.png"), "triangles": 1200}), encoding="utf-8")
os.utime(ws / "models" / "20261021-101010-a-fox.glb", (now - 600, now - 600))
game = TMP / "projects" / "Racer"
game.mkdir(parents=True)
(game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
(game / "icon.png").write_bytes(png(4, 4, (70, 140, 200)))
for p in (game / "project.godot", game / "icon.png", game):
    os.utime(p, (now - 1200, now - 1200))
(TMP / "projects" / "not-a-project").mkdir()
sess = data / "studio" / "sessions" / "s1"
sess.mkdir(parents=True)
(sess / "session.json").write_text(json.dumps({"id": "s1", "kind": "loki", "title": "Add a dark mode", "status": "idle",
                                               "updated": now - 1800, "destination": {"kind": "loki", "name": "LOKI"}}), encoding="utf-8")


class Store:
    def __init__(self, jobs):
        self._jobs = jobs

    def all(self):
        return list(self._jobs)


class Jobs:
    store = Store([{"id": "j1", "title": "Render frames 1-24 on the PC", "status": "working", "machine": "pc",
                    "created": now - 120, "started": now - 110, "finished": 0},
                   {"id": "j2", "title": "Upscale", "status": "done", "created": now - 9000, "finished": now - 8000}])

    def status(self):
        return {"jobs": [], "counts": {}}


class Agent:
    DATA_DIR = str(data)
    WORKSPACE = str(ws)


class State:
    agent = Agent()
    jobs = Jobs()


# the agents' brand / marketing work (owner 2026-10-22)
(ws / "brand" / "logo").mkdir(parents=True, exist_ok=True)
(ws / "brand" / "name.md").write_text("# Names\n", encoding="utf-8")
(ws / "brand" / "logo" / "mark.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>', encoding="utf-8")
(ws / "brand" / ".hidden.md").write_text("x", encoding="utf-8")

import home_projects  # noqa: E402

print("== 1. GET /home/projects")
out = home_projects.collect(State())
items = out["items"]
kinds = [i["kind"] for i in items]
check("every kind is listed: render, forge, godot, studio, content, job", set(kinds) == {"render", "forge", "godot", "studio", "content", "job"}, kinds)
cont = sorted((i for i in items if i["kind"] == "content"), key=lambda i: i["path_or_id"])
check("Content: the brand/ files (not hidden ones), a picture with a thumbnail, opened in Files",
      [i["path_or_id"] for i in cont] == ["brand/logo/mark.svg", "brand/name.md"] and cont[0]["thumb"].startswith("data:image/svg")
      and cont[0]["open"] == {"mode": "files", "path": "brand/logo/mark.svg"} and cont[0]["detail"] == "logo · svg", cont)
check("newest first", [i["updated"] for i in items] == sorted((i["updated"] for i in items), reverse=True), [(i["kind"], i["updated"]) for i in items])
check("every item has the shape the window reads", all(set(i) >= {"kind", "name", "path_or_id", "updated", "thumb", "open"}
                                                       and isinstance(i["open"], dict) and i["open"].get("mode") for i in items), items[:2])
by = {(i["kind"], i["path_or_id"]): i for i in items}
r = by.get(("render", "r-0001"), {})
check("a render: its name, status, a data: thumbnail of its output, opens in Render", r.get("name") == "Castle at dusk"
      and r.get("status") == "done" and str(r.get("thumb", "")).startswith("data:image/png;base64,")
      and r.get("open") == {"mode": "render", "job": "r-0001"}, r)
check("a render's thumb never leaves its folder (../ is ignored)", by.get(("render", "r-0002"), {}).get("thumb") is None)
check("a broken manifest is skipped, not fatal", ("render", "broken") not in by and not out["errors"], out["errors"])
f = by.get(("forge", "models/20261021-101010-a-fox.glb"), {})
check("a Forge model: its prompt as the name, the picture it came from (/creations/images/...), opens Forge with it",
      f.get("name") == "a fox" and f.get("thumb") == "/creations/images/20261021-101010-a-fox.png"
      and f.get("open") == {"mode": "forge", "model": "20261021-101010-a-fox.glb"} and "1,200" in f.get("detail", ""), f)
g = by.get(("godot", "Racer"), {})
check("a Godot project in LOKI Projects: its icon.png, opens the Godot tab on it", str(g.get("thumb", "")).startswith("data:image/png")
      and g.get("open") == {"mode": "godot", "project": "Racer"}, g)
check("a folder without project.godot is not a Godot project", ("godot", "not-a-project") not in by)
check("no built-in LOKI World project any more", not any(i["kind"] == "godot" and "world" in i["path_or_id"].lower() for i in items))
s = by.get(("studio", "s1"), {})
check("a Studio session opens Studio on it", s.get("name") == "Add a dark mode" and s.get("open") == {"mode": "studio", "session": "s1"}, s)
j = by.get(("job", "j1"), {})
check("a job: its status and the machine it runs on (the farm)", j.get("status") == "working" and j.get("detail") == "pc"
      and j.get("open") == {"mode": "job", "id": "j1"}, j)


def boom(_state):
    raise RuntimeError("disk gone")


bad = home_projects.collect(State(), dict(home_projects.SOURCES, godot=boom))
check("one source failing never fails the whole answer (the others are there, the error is named)",
      bad["ok"] and "godot" in bad["errors"] and "disk gone" in bad["errors"]["godot"]
      and {i["kind"] for i in bad["items"]} == {"render", "forge", "studio", "content", "job"}, bad["errors"])
none = home_projects.collect(type("S", (), {"agent": type("A", (), {"DATA_DIR": str(TMP / "nothing"), "WORKSPACE": str(TMP / "nothing")})(), "jobs": None})())
check("nothing made yet: ok, empty", none["ok"] and [i for i in none["items"] if i["kind"] != "godot"] == [], none)
check("a big picture is not inlined (thumb stays small)", home_projects.data_url(TMP / "missing.png") is None)

# the real bridge answers it (token required)
import loki_bridge  # noqa: E402
loki_bridge.PORT = 0
bstate = loki_bridge.BridgeState(Agent(), "home-secret")
bstate.jobs = Jobs()
bserver = loki_bridge.BridgeHTTPServer(bstate)
port = bserver.server_address[1]
loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % port, "localhost:%d" % port)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def get(path, token="home-secret"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Authorization": "Bearer " + token} if token else {})
    resp = conn.getresponse()
    return resp.status, resp.read()


code, body = get("/home/projects")
got = json.loads(body or b"{}")
check("GET /home/projects through the engine (bridge route)", code == 200 and got.get("ok") and len(got.get("items", [])) >= 5, (code, body[:200]))
code, _ = get("/home/projects", token="")
check("...and it needs the engine token", code == 401, code)
for gone in ("/world/build", "/world/presence", "/mmo/state", "/character"):
    code, _ = get(gone)
    check("the old world route %s is gone" % gone, code == 404, code)
bserver.shutdown()
src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge routes it like the other GET routes", 'route == "/home/projects"' in src and "home_projects.route(" in src)

# ------------------------------------------------------------------ 2. the window
print("== 2. the window (headless Chromium)")
index = (UI / "index.html").read_text(encoding="utf-8")
check("index.html loads home.js and home.css, not world.js", '<script src="/ui/home.js" defer></script>' in index
      and '<link rel="stylesheet" href="/ui/home.css">' in index and "world.js" not in index and "world-bg" not in index)
check("no inline script or style in the hub (CSP script-src 'self')", "eval(" not in (UI / "home.js").read_text(encoding="utf-8")
      and "new Function" not in (UI / "home.js").read_text(encoding="utf-8"))
for name in ("Maya", "Blender", "Discord", "ZBrush", "Substance"):
    check("no product name %s in the hub's or the mode bar's words" % name,
          name not in (UI / "home.js").read_text(encoding="utf-8") and name not in (UI / "modebar.js").read_text(encoding="utf-8"))
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

ITEMS = {"ok": True, "errors": {}, "items": [
    {"kind": "render", "name": "Castle at dusk", "path_or_id": "r-0001", "updated": now - 60, "status": "done", "detail": "path",
     "thumb": "data:image/png;base64," + base64.b64encode(png(16, 9, (220, 160, 60))).decode(), "open": {"mode": "render", "job": "r-0001"}},
    {"kind": "job", "name": "Render frames 1-24 on the PC", "path_or_id": "j1", "updated": now - 110, "status": "working", "detail": "pc",
     "thumb": None, "open": {"mode": "job", "id": "j1"}},
    {"kind": "forge", "name": "a fox", "path_or_id": "models/fox.glb", "updated": now - 600, "thumb": None, "detail": "",
     "open": {"mode": "forge", "model": "fox.glb"}},
    {"kind": "godot", "name": "Racer", "path_or_id": "Racer", "updated": now - 1200, "thumb": None, "detail": "",
     "open": {"mode": "godot", "project": "Racer"}},
    {"kind": "studio", "name": "Add a dark mode", "path_or_id": "s1", "updated": now - 1800, "thumb": None, "status": "idle",
     "detail": "LOKI", "open": {"mode": "studio", "session": "s1"}}]}


async def window():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP the window: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1280, "height": 820})
        errors, posts, state = [], [], {"items": ITEMS}
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if r.request.method == "POST":
                posts.append(bare)
            if bare == "/home/projects":
                return await r.fulfill(json=state["items"])
            if bare == "/studio/embed":
                return await r.fulfill(json={"ok": True, "running": True, "url": "about:blank#token=x"})
            if bare == "/godot-editor/status":
                return await r.fulfill(json={"ok": True, "projects": [{"name": "Other", "label": "Other"}, {"name": "Racer", "label": "Racer"}],
                                             "native": "/x/godot", "projects_dir": "p"})
            if bare == "/jobs":
                return await r.fulfill(json={"ok": True, "jobs": [{"id": "j1", "title": "Render frames", "status": "working", "output": "frame 7 of 24"}], "counts": {"working": 1}})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_selector(".home-card", timeout=10000)
        E = page.evaluate

        tabs = await E("[...document.querySelectorAll('.modebar-tab')].map((b) => b.dataset.mode)")
        check("the title bar: Home, Forge, Render, Godot - no Studio or World tab", tabs == ["loki", "forge", "render", "godot"], tabs)
        names = await E("[...document.querySelectorAll('.modebar-tab span')].map((s) => s.textContent)")
        check("the first tab is called Home", names[:1] == ["Home"], names)
        check("no live world behind the home screen", not await E("!!document.querySelector('.world-bg, #world-home, iframe.world-godot')"))
        cards = await E("[...document.querySelectorAll('.home-card')].map((c) => c.dataset.kind)")
        check("the hub shows a card per thing, newest first - jobs are not cards", cards == ["render", "forge", "godot", "studio"], cards)
        live = await E("(() => { const l = document.querySelector('.home-live'); return l && !l.hidden ? l.textContent : ''; })()")
        check("a 'working now' chip counts what runs", live == "1 working", live)
        check("no refresh or fold buttons (it refreshes itself)", not await E("!!document.querySelector('.home-refresh, .home-fold')"))
        info = await E("""(() => { const c = document.querySelector('.home-card[data-kind=render]'), f = document.querySelector('.home-card[data-kind=forge]');
          return { img: !!c.querySelector('.home-card-thumb img'), icon: !!f.querySelector('.home-card-thumb svg'),
                   name: c.querySelector('.home-card-name').textContent, when: c.querySelector('.home-card-when').textContent,
                   tip: c.dataset.tipName, what: c.dataset.tipWhat }; })()""")
        check("a card: its picture (or its kind's icon), name and when", info["img"] and info["icon"] and info["name"] == "Castle at dusk"
              and info["when"] == "1 min ago", info)
        check("cards and icons have hover tooltips (name + what it does)", info["tip"] == "Castle at dusk" and "Render" in info["what"]
              and await E("[...document.querySelectorAll('.home-ico')].every((b) => b.dataset.tipName && b.dataset.tipWhat && b.getAttribute('aria-label'))"), info)
        hero = await E("(() => { const h = document.querySelector('.home-hero'); return h && !h.hidden ? h.querySelector('.home-hero-name').textContent : ''; })()")
        check("the big preview shows the latest render", hero == "Castle at dusk", hero)
        await page.click(".home-card[data-kind=godot]")
        check("a click on a card shows it big", await E("document.querySelector('.home-hero-name').textContent") == "Racer")
        await page.hover(".home-kind[data-kind=forge]")
        await page.wait_for_timeout(500)
        check("hovering an icon shows its tooltip", await E("(() => { const t = document.querySelector('.icon-tip'); return !!t && !t.hidden && t.textContent.includes('Forge'); })()"))
        await page.click(".home-kind[data-kind=forge]")
        check("the kind icons filter the grid", await E("[...document.querySelectorAll('.home-card')].map((c) => c.dataset.kind)") == ["forge"])
        await page.click(".home-kind[data-kind=all]")

        # open where it lives
        await page.click(".home-card[data-kind=godot] .home-card-open")
        await page.wait_for_timeout(600)
        check("a Godot card opens the Godot tab on that project", await E("document.body.dataset.mode") == "godot"
              and await E("document.querySelector('[data-mode-pane=godot] select').value") == "Racer")
        await page.keyboard.press("Control+F1")   # Home's one key here (Option+1 on a Mac)
        await page.wait_for_timeout(200)
        check("Ctrl+F1 is Home again", await E("document.body.dataset.mode") == "loki" and await E("!document.getElementById('home-hub').hidden"))
        await E("window.forgeLoad = (n) => { window.__loaded = n; return Promise.resolve(); }")
        await page.dblclick(".home-card[data-kind=forge]")
        await page.wait_for_timeout(600)
        check("a Forge card opens Forge and loads that model", await E("document.body.dataset.mode") == "forge" and await E("window.__loaded") == "fox.glb",
              await E("[document.body.dataset.mode, window.__loaded]"))
        await page.keyboard.press("Control+F3")
        await page.wait_for_timeout(300)
        check("Ctrl+F3 is Studio (the render farm and Render Studio, or what to do when it is not in this window yet)",
              await E("document.body.dataset.mode") == "render" and await E("!!document.querySelector('[data-mode-pane=render] .render-empty, [data-mode-pane=render] #render-studio, [data-mode-pane=render] #studio-farm')"))
        await page.keyboard.press("Control+F4")
        await page.wait_for_timeout(200)
        check("Ctrl+F4 is Engine", await E("document.body.dataset.mode") == "godot")
        await page.keyboard.press("Control+F1")
        await page.wait_for_timeout(200)
        await page.click(".home-card[data-kind=render] .home-card-open")
        await page.wait_for_timeout(300)
        check("a render card opens Studio", await E("document.body.dataset.mode") == "render")
        await page.keyboard.press("Control+F1")
        await page.wait_for_timeout(200)

        # Studio inside Home
        await page.evaluate("LokiHome.openStudio()")
        await page.wait_for_timeout(500)
        st = await E("""(() => { const s = document.getElementById('home-studio'), m = document.getElementById('main').getBoundingClientRect(),
          r = s ? s.getBoundingClientRect() : null; return { open: !!s && !s.hidden, frame: !!(s && s.querySelector('iframe[src*="about:blank"]')),
          full: !!r && Math.abs(r.height - m.height) < 2 && Math.abs(r.width - m.width) < 2, mode: document.body.dataset.mode }; })()""")
        check("Studio opens as a full-height pane inside Home (the /studio/embed frame), not a tab", st["open"] and st["frame"] and st["full"]
              and st["mode"] == "loki" and "/studio/embed" in posts, (st, posts))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
        check("Esc closes Studio, back to the hub", await E("document.getElementById('home-studio').hidden"))
        await page.keyboard.press("Control+Shift+S")
        await page.wait_for_timeout(200)
        check("Ctrl/Cmd+Shift+S opens Studio", not await E("document.getElementById('home-studio').hidden"))
        await page.click(".home-studio-back")
        check("the back control closes it", await E("document.getElementById('home-studio').hidden"))
        await page.click(".home-card[data-kind=studio] .home-card-open")
        await page.wait_for_timeout(300)
        check("a Studio card opens Studio on that session", await E("document.querySelector('#home-studio iframe').src.includes('session=s1')")
              and posts.count("/studio/embed") == 1, (await E("document.querySelector('#home-studio iframe').src"), posts))
        await page.keyboard.press("Escape")
        await page.evaluate("document.getElementById('open-studio').click()")
        await page.wait_for_timeout(200)
        check("the sidebar's LOKI Studio button opens it in Home too", not await E("document.getElementById('home-studio').hidden"))
        await page.keyboard.press("Escape")

        # a job card -> its status; the chat stays reachable
        await page.click(".home-live")
        await page.wait_for_timeout(400)
        check("the working chip shows the job live in the preview", "frame 7 of 24" in await E("document.querySelector('.home-hero').textContent"))
        # the split (home_layout.css / chat_view.js): the chat column is always beside the hub, in both views
        await page.click("#prompt")
        await page.wait_for_timeout(300)
        fold = await E("""(() => { const h = document.getElementById('home-hub'), c = document.getElementById('composer'), s = document.getElementById('loki-split');
          const hr = h.getBoundingClientRect(), cr = c.getBoundingClientRect();
          return { split: !!s && h.parentNode === s, hub: !h.hidden, hero: getComputedStyle(h.querySelector('.home-hero')).display,
                   composer: cr.height > 0 && getComputedStyle(c).display !== 'none', beside: cr.left >= hr.right - 1 }; })()""")
        check("the chat box is always there, beside the hub (no hidden display, no summon click)", fold["split"] and fold["hub"]
              and fold["hero"] != "none" and fold["composer"] and fold["beside"], fold)
        await E("showChat(); renderMessages(Array.from({length: 40}, (_, i) => ({role: i % 2 ? 'assistant' : 'user', content: 'line ' + i + ' ' + 'word '.repeat(40)})))")
        await page.wait_for_timeout(300)
        chat = await E("""(() => { const t = document.getElementById('transcript'), h = document.getElementById('home-hub');
          return { hub: !h.hidden, shown: getComputedStyle(t).display !== 'none' && t.clientHeight > 80, scroll: getComputedStyle(t).overflowY,
                   long: t.scrollHeight > t.clientHeight, bottom: t.scrollHeight - t.scrollTop - t.clientHeight < 4 }; })()""")
        check("a running conversation shows beside the hub, scrolls, and opens at the latest message", chat["hub"] and chat["shown"]
              and chat["scroll"] == "auto" and chat["long"] and chat["bottom"], chat)
        await E("(() => { const t = document.getElementById('transcript'); t.scrollTop = 0; t.dispatchEvent(new Event('scroll')); })()")
        try:
            await page.wait_for_function("!document.getElementById('jump-latest').hidden", timeout=3000)
        except Exception:  # noqa: BLE001 - the check below reports it
            pass
        check("scrolled up: a 'Latest' button appears", await E("!document.getElementById('jump-latest').hidden"))
        await E("addLoki('a new answer while you read')")
        await page.wait_for_timeout(150)
        check("new output does not yank you down while you read", await E("document.getElementById('transcript').scrollTop < 50"))
        await page.click("#jump-latest")
        await page.wait_for_timeout(700)
        check("'Latest' brings you back to the newest message", await E("(() => { const t = document.getElementById('transcript'); return t.scrollHeight - t.scrollTop - t.clientHeight < 4 && document.getElementById('jump-latest').hidden; })()"))
        await page.click("#hub-toggle")
        await page.wait_for_timeout(200)
        off = await E("({ hub: document.getElementById('home-hub').hidden, w: document.getElementById('chat-col').getBoundingClientRect().width, W: document.getElementById('loki-split').getBoundingClientRect().width, saved: localStorage.getItem('loki-hub-off') })")
        check("the panel button folds the hub away and the chat takes the window (remembered)", off["hub"] and off["w"] > off["W"] - 2 and off["saved"] == "1", off)
        await page.click("#hub-toggle")
        await page.wait_for_timeout(200)
        check("... and brings it back", await E("!document.getElementById('home-hub').hidden"))
        row = await E("""(() => { const r = document.querySelector('.composer-row'), b = r.getBoundingClientRect();
          return [...r.children].filter((c) => c.offsetParent).every((c) => { const x = c.getBoundingClientRect(); return x.left >= b.left - 1 && x.right <= b.right + 1; }); })()""")
        check("every button under the message box is inside it (they wrap, never cut off)", row)
        # ---- modular: the panes swap slots (Godot-style presets and drag), the chat resizes, all remembered
        POS = """(() => { const x = (s) => { const e = document.querySelector(s); return e ? Math.round(e.getBoundingClientRect().left) : -1; };
          return [['sidebar', x('.sidebar')], ['hub', x('#home-hub')], ['chat', x('#chat-col')]].sort((a, b) => a[1] - b[1]).map((p) => p[0]); })()"""
        check("default layout: chats | Home | chat", await E(POS) == ["sidebar", "hub", "chat"], await E(POS))
        await page.click("#layout-btn")
        await page.click('.layout-opt[data-order="sidebar,chat,hub"]')
        await page.wait_for_timeout(150)
        check("Layout > Chat in the middle", await E(POS) == ["sidebar", "chat", "hub"], await E(POS))
        await page.click("#layout-btn")
        await page.click('.layout-opt[data-order="hub,chat,sidebar"]')
        await page.wait_for_timeout(150)
        check("Layout > Chats on the right (the sidebar at the other end)", await E(POS) == ["hub", "chat", "sidebar"], await E(POS))
        # drag the chat's grip onto the left slot
        g = await E("(() => { const b = document.querySelector('#chat-col > .pane-grip').getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
        await page.mouse.move(g[0], g[1]); await page.mouse.down()
        await page.mouse.move(60, 400, steps=6)
        slots = await E("document.querySelectorAll('.lk-slots .lk-slot').length")
        await page.mouse.up(); await page.wait_for_timeout(150)
        check("dragging a pane's grip shows the three slots; dropping the chat on the left puts it there", slots == 3 and (await E(POS))[0] == "chat", [slots, await E(POS)])
        check("the sidebar never lands in the middle", (await E(POS))[1] != "sidebar", await E(POS))
        saved = await E("JSON.parse(localStorage.getItem('loki-home-layout')).order")
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_timeout(400)
        check("the layout is remembered after a restart", await E(POS) == saved, [saved, await E(POS)])
        # the chat column's inner edge resizes it
        w0 = await E("document.getElementById('chat-col').getBoundingClientRect().width")
        eb = await E("(() => { const b = document.querySelector('#chat-col > .chat-edge').getBoundingClientRect(); return [b.left + b.width / 2, b.top + 200]; })()")
        first = await E("document.getElementById('loki-split').classList.contains('chat-first')")
        await page.mouse.move(eb[0], eb[1]); await page.mouse.down(); await page.mouse.move(eb[0] + (120 if first else -120), eb[1], steps=5); await page.mouse.up()
        w1 = await E("document.getElementById('chat-col').getBoundingClientRect().width")
        check("dragging the chat's edge makes it wider (and it is saved)", w1 > w0 + 60 and await E("JSON.parse(localStorage.getItem('loki-home-layout')).chatW > 0"), [w0, w1])
        await page.click("#layout-btn")
        await page.click(".layout-opt.layout-wide:last-child")
        await page.wait_for_timeout(150)
        check("Layout > Reset: back to chats | Home | chat", await E(POS) == ["sidebar", "hub", "chat"], await E(POS))
        check("one font on every system: the bundled Inter is loaded", await E("document.fonts.check('14px \"LOKI Inter\"') && getComputedStyle(document.body).fontFamily.startsWith('\"LOKI Inter\"')"))
        await E("showHome()")
        await page.wait_for_timeout(200)

        # empty state + a small window
        state["items"] = {"ok": True, "errors": {}, "items": []}
        await E("LokiHome.refresh()")
        await page.wait_for_timeout(400)
        start = await E("[...document.querySelectorAll('.home-start-btn')].map((b) => b.dataset.kind)")
        check("empty: one calm line and three places to start", start == ["forge", "render", "godot"]
              and not await E("document.querySelectorAll('.home-empty-row').length"), start)
        await page.click(".home-kind[data-kind=godot]")
        rows = await E("[...document.querySelectorAll('.home-empty-row')].map((r) => r.textContent)")
        check("one kind picked and none of it: how to make one", len(rows) == 1 and "LOKI Projects" in rows[0], rows)
        await page.click(".home-kind[data-kind=all]")
        many = dict(ITEMS, items=[dict(ITEMS["items"][2], name="m%d" % i, path_or_id="models/m%d.glb" % i) for i in range(20)])
        state["items"] = many
        await E("LokiHome.refresh()")
        await page.wait_for_timeout(300)
        row = await E("(() => { const c = [...document.querySelectorAll('.home-card')]; return { n: c.length, tops: new Set(c.map((x) => Math.round(x.getBoundingClientRect().top))).size, more: document.querySelector('.home-more').textContent }; })()")
        check("two rows of recent things beside the chat, 'All 20' for the rest", row["tops"] == 2 and 2 <= row["n"] < 20 and row["more"] == "All 20", row)
        await page.click(".home-more")
        check("All shows every one", await E("document.querySelectorAll('.home-card').length") == 20)
        await page.click(".home-more")
        state["items"] = ITEMS
        await E("LokiHome.refresh()")
        await page.set_viewport_size({"width": 760, "height": 540})
        await page.wait_for_timeout(400)
        fit = await E("""(() => { const h = document.getElementById('home-hub').getBoundingClientRect(), W = innerWidth;
          const cards = [...document.querySelectorAll('.home-card')].map((c) => c.getBoundingClientRect());
          return { inside: h.right <= W + 0.5 && cards.every((r) => r.right <= h.right + 0.5 && r.left >= h.left - 0.5),
                   noX: document.documentElement.scrollWidth <= W + 1 }; })()""")
        check("it fits a small window (no sideways scroll, cards inside)", fit["inside"] and fit["noX"], fit)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if async_playwright is None:
    print("SKIP the window: no Playwright here")
elif time.time() - T0 > 40:
    print("SKIP the window: out of time")
else:
    asyncio.run(window())

check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
