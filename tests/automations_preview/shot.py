"""Settings > Automations in headless Chromium: the REAL window (app/ui/index.html + automations.js) against the
REAL engine code (engine/automations.py ui_route) with seeded automations in a temp folder; every other engine
endpoint answers a small fake. Writes screenshots and returns what it saw (tests/test_automations.py uses it).

    python tests/automations_preview/shot.py [out_dir]     (default docs/operations/screens)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))

import automations as A  # noqa: E402

FAKE = {
    "/health": {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "", "route": [],
                "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []},
    "/world": {"ok": True, "agents": [], "machines": [], "self": {"name": "test"}, "creations": {"count": 0, "latest": []}},
}


class Seeded(A.Sources):
    def __init__(self, ws):
        self.ws = ws

    def machine(self):
        return {"name": "gaming-pc", "kind": "pc"}

    def workspace(self):
        return self.ws


class State:
    pass


def seed(root: Path) -> State:
    ws = root / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    rt = A.Automations(root / "automations", Seeded(ws), env={}, sync=True)
    brief = A.draft("every morning at 8 send me the weather and my calendar on Telegram")["automation"]
    brief["name"] = "Morning briefing"
    rt.save(dict(brief, enabled=True))
    pdf = A.draft("when a PDF lands in Downloads, summarize it into notes")["automation"]
    pdf["name"] = "Summarize new PDFs"
    rt.save(dict(pdf, enabled=True))
    price = next(t for t in A.templates() if t["id"] == "price-watch")["automation"]
    rt.save(dict(price, enabled=False))
    hook = rt.save({"name": "Door sensor", "enabled": True, "triggers": [{"type": "webhook"}],
                    "steps": [{"type": "http", "method": "POST", "url": "https://home.example/api/lights", "body": "on"}]})
    first = rt.list()[0]
    rt.fire(first["id"], {})          # fails: Telegram is not set up here -> a run with a log
    rt.fire(hook["id"], {})           # waits for the owner's OK
    state = State()
    state.automations = rt
    return state


def run(out_dir: Path) -> dict:
    from playwright.sync_api import sync_playwright  # type: ignore
    chromium = next((p for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if p and os.path.exists(p)), None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state = seed(Path(tempfile.mkdtemp(prefix="loki-auto-shot-")))
    errors: list = []
    result = {"errors": errors}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        def route(r):
            url = r.request.url.split("8899", 1)[1]
            path = url.split("#")[0]
            bare = path.split("?")[0]
            if bare == "/":
                return r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return r.fulfill(path=str(UI / bare[4:]))
            if bare.startswith("/automations"):
                body = json.loads(r.request.post_data or "{}") if r.request.method == "POST" else {}
                code, payload = A.ui_route(state, r.request.method, path, body, 8766)
                return r.fulfill(status=code, json=payload)
            return r.fulfill(json=FAKE.get(bare, {"ok": True}))

        page.route("http://127.0.0.1:8899/**", route)
        page.goto("http://127.0.0.1:8899/#token=t")
        page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        page.click("#open-settings")
        page.click('.tabs [data-tab="automations"]')
        page.wait_for_selector(".auto-row", timeout=10000)
        page.wait_for_timeout(400)
        result["rows"] = page.locator(".auto-row").count()
        page.hover('.tabs [data-tab="automations"]')
        page.wait_for_timeout(500)
        result["tip"] = page.inner_text(".icon-tip") if page.locator(".icon-tip").count() else ""
        png = out_dir / "automations-list.png"
        page.screenshot(path=str(png))
        result["png"] = str(png)
        page.mouse.move(700, 10)
        page.fill(".auto-say", "every weekday at 9am check https://shop.example/p and tell me on telegram")
        page.click('.auto-make button[aria-label="Draft it"]')
        page.wait_for_selector(".auto-card.draft", timeout=5000)
        result["draft"] = page.inner_text(".auto-card.draft")
        page.screenshot(path=str(out_dir / "automations-draft.png"))
        page.click('.auto-card.draft button[aria-label="Discard"]')
        page.click('.auto-row >> nth=0 >> button[aria-label="History"]')
        page.wait_for_selector(".auto-run", timeout=5000)
        page.click(".auto-run summary >> nth=0")
        page.wait_for_timeout(300)
        result["history"] = page.inner_text(".auto-history")
        page.screenshot(path=str(out_dir / "automations-history.png"))
        page.click('.auto-row >> nth=0 >> button[aria-label="Edit"]')
        page.wait_for_selector(".auto-card.editor", timeout=5000)
        page.screenshot(path=str(out_dir / "automations-editor.png"))
        browser.close()
    return result


if __name__ == "__main__":
    out = run(Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "operations" / "screens")
    print(json.dumps({k: (v if not isinstance(v, str) else v[:400]) for k, v in out.items()}, indent=1))
    sys.exit(1 if out["errors"] else 0)
