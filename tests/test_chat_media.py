"""Pictures and PDFs in the chat (engine/chat_media.py + app/ui/chat_media.js; owner 2026-10-25 "can you make it so
loki gives me jpg or pdf images in the chat"). Engine: only pictures and PDFs, only from the workspace or LOKI
Projects; a PNG comes back as a data URL with its size; Save as JPG / PDF write a copy beside it; a PDF reports its
pages. Window: a reply that names `images/fox.png` and a PDF shows the picture and the PDF page under it, with Open /
Save as JPG / Save as PDF and a big view. Under a minute.

    python tests/test_chat_media.py
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-chatmedia-"))
os.environ["LOKI_PROJECTS_DIR"] = str(TMP / "LOKI Projects")
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import chat_media  # noqa: E402

ws = TMP / "ws"; (ws / "images").mkdir(parents=True)
proj = TMP / "LOKI Projects" / "Comics" / "robot"; (proj / "pages").mkdir(parents=True)
try:
    from PIL import Image
    Image.new("RGBA", (40, 30), (200, 80, 40, 255)).save(ws / "images" / "fox.png")
    Image.new("RGB", (20, 20), (10, 10, 200)).save(proj / "pages" / "page 1.png")
    Image.new("RGB", (100, 140), (255, 255, 255)).save(proj / "book.pdf", "PDF")
    have_pil = True
except ImportError:
    have_pil = False
    (ws / "images" / "fox.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="))
(TMP / "secret.png").write_bytes((ws / "images" / "fox.png").read_bytes())
(ws / "notes.txt").write_text("hi")
state = types.SimpleNamespace(agent=types.SimpleNamespace(WORKSPACE=ws))

code, r = chat_media.route(state, "GET", "/chat/media", {"path": "images/fox.png"}, {})
check("a workspace picture by its relative path: a PNG data URL and its size", code == 200 and r["kind"] == "image"
      and r["data_url"].startswith("data:image/png;base64,") and (not have_pil or (r["width"], r["height"]) == (40, 30)), {k: r.get(k) for k in ("kind", "width", "height", "error")})
if have_pil:
    code, r = chat_media.route(state, "GET", "/chat/media", {"path": str(proj / "pages" / "page 1.png")}, {})
    check("a picture in LOKI Projects by its full path (spaces in it)", code == 200 and r["kind"] == "image", r.get("error"))
    code, r = chat_media.route(state, "GET", "/chat/media", {"path": "Comics/robot/book.pdf"}, {})
    check("a PDF in LOKI Projects: kind pdf, its page count", code == 200 and r["kind"] == "pdf" and r["pages"] == 1, {k: r.get(k) for k in ("kind", "pages", "note", "error")})
for bad, why in ((str(TMP / "secret.png"), "outside"), ("../secret.png", "outside"), ("notes.txt", "only pictures"), ("images/none.png", "no such")):
    code, r = chat_media.route(state, "GET", "/chat/media", {"path": bad}, {})
    check("refused: %s (%s)" % (bad, why), code == 400 and not r["ok"], r)
if have_pil:
    code, r = chat_media.route(state, "POST", "/chat/media/convert", {}, {"path": "images/fox.png", "to": "jpg"})
    check("Save as JPG: images/fox.jpg beside it, a real JPEG", code == 200 and Path(r["path"]).name == "fox.jpg"
          and Path(r["path"]).read_bytes()[:3] == b"\xff\xd8\xff", r)
    code, r = chat_media.route(state, "POST", "/chat/media/convert", {}, {"path": "images/fox.png", "to": "pdf"})
    check("Save as PDF: images/fox.pdf, a real PDF", code == 200 and Path(r["path"]).read_bytes()[:5] == b"%PDF-", r)
    code, r = chat_media.route(state, "POST", "/chat/media/convert", {}, {"path": "images/fox.png", "to": "jpg"})
    check("again: a new name (fox-2.jpg), never over the first", Path(r["path"]).name == "fox-2.jpg", r)
    code, r = chat_media.route(state, "POST", "/chat/media/convert", {}, {"path": "images/fox.png", "to": "exe"})
    check("only jpg or pdf", code == 400, r)
opened = []
r = chat_media.open_file(state, "images/fox.png", run=lambda argv: opened.append(argv))
check("Open hands the file to the computer's own app", r["ok"] and (sys.platform == "win32" or opened and opened[-1][-1].endswith("fox.png")), opened)

# ---- the window
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

PNG = "data:image/png;base64," + base64.b64encode((ws / "images" / "fox.png").read_bytes()).decode()
REPLY = ("Made it. The picture is `images/fox.png`, and the comic is in ![cover](Comics/robot/book.pdf). "
         "See https://example.com/x.png too (a web link, not ours).")


async def ui():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP window part: no Chromium (%s)" % str(exc)[:100]); return
        page = await browser.new_page(viewport={"width": 1300, "height": 860})
        errors, posts, asked = [], [], []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            url = r.request.url.split("8897", 1)[1]
            bare = url.split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if r.request.method == "POST":
                posts.append((bare, json.loads(r.request.post_data or "{}")))
            if bare == "/chat/media":
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(url).query); path = q.get("path", [""])[0]; asked.append(path)
                if path == "images/fox.png":
                    return await r.fulfill(json={"ok": True, "kind": "image", "name": "fox.png", "path": "/ws/images/fox.png", "width": 40, "height": 30, "data_url": PNG})
                if path in ("Comics/robot/book.pdf", "/p/book.pdf"):   # the next page asks by the full path
                    pg = int(q.get("page", ["1"])[0])
                    return await r.fulfill(json={"ok": True, "kind": "pdf", "name": "book.pdf", "path": "/p/book.pdf", "pages": 3, "page": pg, "image": PNG})
                return await r.fulfill(status=400, json={"ok": False, "error": "no such"})
            if bare == "/chat/media/convert":
                return await r.fulfill(json={"ok": True, "name": "fox.jpg", "path": "/ws/images/fox.jpg"})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8897/**", route)
        await page.goto("http://127.0.0.1:8897/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("setView('chat')"); await page.wait_for_timeout(200)   # off Home: the chat transcript shows
        await E("addLoki(%s)" % json.dumps(REPLY))
        try:
            await page.wait_for_selector(".turn.loki .cm-strip .cm-pdf", timeout=8000)
        except Exception:
            print(await E("""(() => { let n = document.querySelector('.cm-pdf'), out = []; while (n) { const cs = getComputedStyle(n);
              if (cs.display === 'none' || cs.visibility === 'hidden' || n.hidden) out.push((n.id || n.className || n.tagName) + ':' + cs.display);
              n = n.parentElement; } return out.join(' < '); })()"""))
            raise
        tiles = await E("[...document.querySelectorAll('.turn.loki .cm-tile')].map((t) => [t.className, t.textContent])")
        check("the reply shows the picture and the PDF right under it", len(tiles) == 2 and "cm-image" in tiles[0][0] and "fox.png" in tiles[0][1]
              and "cm-pdf" in tiles[1][0] and "page 1 of 3" in tiles[1][1], tiles)
        check("... the web link is not fetched as ours", not any("example.com" in a for a in asked), asked)
        await page.click(".cm-image .cm-btn:has-text('Save as JPG')")
        await page.wait_for_timeout(150)
        check("Save as JPG posts the picture's path and says where it went", [b for u, b in posts if u == "/chat/media/convert"][-1:] == [{"path": "/ws/images/fox.png", "to": "jpg"}]
              and "Saved fox.jpg" in await E("document.querySelector('.cm-image .cm-say').textContent"))
        await page.click(".cm-pdf .cm-btn:has-text('›')")
        await page.wait_for_timeout(200)
        pdf_text = await E("document.querySelector('.cm-pdf').textContent")
        check("the PDF turns the page (page 2 of 3)", "page 2 of 3" in pdf_text, [pdf_text, asked[-3:], errors])
        await page.click(".cm-image .cm-pic")
        await page.wait_for_selector("#cm-big img", timeout=3000)
        await page.keyboard.press("Escape")
        check("a click shows the picture big; Esc closes it", await E("!document.getElementById('cm-big')"))
        await page.click(".cm-image .cm-btn:has-text('Open')")
        await page.wait_for_timeout(100)
        check("Open asks the engine to open it in the computer's app", [b for u, b in posts if u == "/chat/media/open"][-1:] == [{"path": "/ws/images/fox.png"}])
        check("no script errors", not errors, errors[:3])
        await browser.close()

if async_playwright:
    asyncio.run(asyncio.wait_for(ui(), 45))
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))

# ------------------------------------------------------------------ what a turn made is shown even when not named
import time as _t  # noqa: E402
import tempfile as _tf  # noqa: E402
_ws = Path(_tf.mkdtemp())


class _A:
    WORKSPACE = str(_ws)


class _S:
    agent = _A()


_t0 = _t.time()
(_ws / "images").mkdir()
(_ws / "images" / "dragon.png").write_bytes(b"\x89PNG")
(_ws / "sprites").mkdir()
(_ws / "sprites" / "hero-pixel64.png").write_bytes(b"\x89PNG")
(_ws / "sprites" / "hero-pixel64-x8.png").write_bytes(b"\x89PNG")
_made = chat_media.made_since(_S(), _t0)
check("a turn's new pictures are found (not the pixel previews, not hidden folders)",
      _made == ["images/dragon.png", "sprites/hero-pixel64.png"], _made)
_txt = chat_media.with_made("I made an image of a dragon.", _made)
check("a reply that only says 'I made an image' gets the files named, so the chat shows them",
      "`images/dragon.png`" in _txt and "`sprites/hero-pixel64.png`" in _txt, _txt)
check("files the reply already names are not repeated", chat_media.with_made("See images/dragon.png", ["images/dragon.png"])
      == "See images/dragon.png")
check("a bare file name is found in the makers' folders", chat_media.find(_S(), "dragon.png") == (_ws / "images" / "dragon.png").resolve())
check("the bridge adds what the turn made to the chat reply", "made_since" in (REPO / "engine" / "loki_bridge.py").read_text())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
