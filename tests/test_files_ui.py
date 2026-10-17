"""Session 29, offline: the Files view in headless Chromium (screenshot) against the REAL engine/files_api.py
behind a fake engine - open, PDF page preview, CSV table, a real DataTransfer drop, Ask LOKI about this file,
recent files and collections, and in the chat: tables, file links that open Files, pictures shown inline.
Split from tests/test_documents.py so each suite stays under a minute. Skips without Playwright + Chromium.

    python tests/test_files_ui.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-filesui-"))
DATA = TMP / "data"
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def run(coro):
    return asyncio.run(coro)


import doc_read  # noqa: E402
import doc_write  # noqa: E402
import files_api  # noqa: E402
import knowledge  # noqa: E402

SAMPLES = WS / "samples"
SAMPLES.mkdir()
doc_write.markdown_to_pdf_builtin("# Annual report\n\nRevenue grew **12%**.\n\n| Region | Sales |\n| --- | --- |\n| North | 10 |\n\n"
                                  "\\pagebreak\n\n## Appendix\n\nPage two.", SAMPLES / "report.pdf", title="Annual report")
(SAMPLES / "sales.csv").write_text("date,region,units\n" + "\n".join("2026-01-%02d,%s,%d" % (1 + i % 28, "NSE"[i % 3], 10 + i)
                                                                      for i in range(60)))
try:
    from PIL import Image  # noqa: E402
    Image.new("RGB", (320, 200), "white").save(SAMPLES / "photo.png")
except ImportError:
    pass
COLL = TMP / "contracts"
COLL.mkdir()
shutil.copy(SAMPLES / "report.pdf", COLL / "report.pdf")
knowledge.add_collection(DATA, COLL, "Contracts")


class FakeAgent:
    WORKSPACE = WS
    DATA_DIR = DATA


class FakeState:
    agent = FakeAgent()


S = FakeState()

# --------------------------------------------------------------------------- the Files view in headless Chromium
def chromium_path() -> str:
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None

if async_playwright is not None and chromium_path():
    print("the Files view (headless Chromium, the real files_api behind a fake engine)")
    UI = REPO / "app" / "ui"
    FAKE = {"/health": {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "", "route": [],
                        "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []},
            "/world": {"ok": True, "agents": [], "machines": [], "self": {"name": "test"}, "creations": {"count": 0, "latest": []}}}
    shot = TMP / "files_view.png"

    async def ui_test():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chromium_path(), args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            page = await browser.new_page(viewport={"width": 1360, "height": 860})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

            async def route(r):
                url = r.request.url.split("8899", 1)[1]
                path = url.split("?")[0].split("#")[0]
                if path == "/":
                    return await r.fulfill(path=str(UI / "index.html"))
                if path.startswith("/ui/"):
                    f = UI / path[4:]
                    if f.is_file():
                        return await r.fulfill(path=str(f))
                    return await r.fulfill(json={"ok": True})
                if path == "/files/upload":
                    code, body = files_api.save_upload(S, url.split("?", 1)[1], io.BytesIO(r.request.post_data_buffer or b""),
                                                       len(r.request.post_data_buffer or b""))
                    return await r.fulfill(status=code, json=body)
                if path.startswith("/files/"):
                    body = json.loads(r.request.post_data or "{}") if r.request.method == "POST" else {}
                    code, out = files_api.handle(S, r.request.method, url, body)
                    return await r.fulfill(status=code, json=out)
                return await r.fulfill(json=FAKE.get(path, {"ok": True}))
            await page.route("http://127.0.0.1:8899/**", route)
            await page.goto("http://127.0.0.1:8899/#token=t")
            await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
            check("the window starts with files.js loaded", await page.evaluate("typeof openFiles === 'function'"), errors[:3])
            check("the Files button is an icon with a tooltip name", await page.get_attribute("#open-files", "data-tip-name") == "Files"
                  and await page.evaluate("!!document.querySelector('#open-files svg')"))
            await page.click("#open-files")
            await page.wait_for_selector("#files-list .file-row")
            check("Files opens and lists the workspace", await page.is_visible("#files") and await page.locator("#files-list .file-row").count() >= 1)
            await page.click('#files-list .file-row[data-path="samples"]')
            await page.wait_for_selector('#files-list .file-row[data-path="samples/report.pdf"]')
            await page.click('#files-list .file-row[data-path="samples/report.pdf"]')
            await page.wait_for_selector("#files-preview .fp-pages")
            text = await page.inner_text("#files-preview")
            check("a PDF previews with page navigation and its text", "Page 1 of" in text and "Revenue grew" in text, text[:200])
            if doc_read.can_render_pdf():
                check("...and the page picture", await page.evaluate("!!document.querySelector('#files-preview img.page')"))
            await page.screenshot(path=str(shot))
            await page.click('#files-list .file-row[data-path="samples/sales.csv"]')
            await page.wait_for_selector("#files-preview .fp-table")
            check("a CSV previews as a table", await page.locator("#files-preview .fp-table tbody tr").count() == 60)
            # drop a file on the Files view (a real DataTransfer with a File)
            await page.evaluate("""() => { const dt = new DataTransfer(); dt.items.add(new File(['a,b\\n1,2\\n'], 'dropped.csv', {type: 'text/csv'}));
                 const sheet = document.getElementById('files');
                 sheet.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true}));
                 sheet.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true})); }""")
            await page.wait_for_function("document.getElementById('files-note').textContent.includes('Copied in')", timeout=8000)
            check("drag & drop copies the file into the folder shown", (WS / "samples" / "dropped.csv").read_text() == "a,b\n1,2\n")
            await page.wait_for_selector("#files-recent .chip")
            check("recent files and collections are shown", await page.locator("#files-recent .chip").count() >= 1
                  and "Contracts" in await page.inner_text("#files-collections"))
            await page.click('#files-preview button[data-tip-name="Ask LOKI about this file"]')
            check("Ask LOKI about this file fills the message box", (await page.input_value("#prompt")).startswith("About the file `samples/sales.csv`")
                  and await page.is_hidden("#files"))
            # the chat: a table renders, a file path opens Files, a chart shows inline
            await page.evaluate("addLoki('| Region | Units |\\n| --- | --- |\\n| North | 10 |\\n\\nSaved `samples/photo.png` and `samples/report.pdf`.')")
            check("a Markdown table renders as a table in the chat", await page.locator(".turn.loki table.md-table td").count() == 2)
            try:
                await page.wait_for_selector(".turn.loki code.file-link", state="attached", timeout=10000)
                if (SAMPLES / "photo.png").exists():
                    await page.wait_for_selector(".turn.loki img.chat-img", state="attached", timeout=10000)
            except Exception:  # noqa: BLE001 - the checks below say what is missing
                pass
            if (SAMPLES / "photo.png").exists():
                check("a picture path in a reply shows the picture inline", await page.locator(".turn.loki img.chat-img").count() == 1)
            check("file paths in a reply become links", await page.locator(".turn.loki code.file-link").count() == 2)
            await page.evaluate("([...document.querySelectorAll('.turn.loki code.file-link')].find((c) => c.textContent === 'samples/report.pdf') || document.body).click()")
            try:
                await page.wait_for_selector("#files-preview .fp-pages", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            check("a file path in a reply opens it in Files", await page.is_visible("#files"))
            check("no script errors in the Files view", not errors, errors[:5])
            await browser.close()
    run(ui_test())
    check("screenshot of the Files view saved (%s)" % shot, shot.is_file() and shot.stat().st_size > 20_000)
    out_dir = os.getenv("LOKI_SUITE_SCREENSHOTS", "")
    if out_dir and shot.is_file():
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy(shot, Path(out_dir) / "files_view.png")
else:
    print("SKIP the Files view: no Playwright/Chromium here")


print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(TMP, ignore_errors=True) if not FAIL and not os.getenv("LOKI_SUITE_KEEP") else print("kept " + str(TMP))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
