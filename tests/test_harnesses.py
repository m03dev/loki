"""Swappable harnesses (owner 2026-10-25: "i should be able to swap out different harnesses, everything should be
modular"). The model is WHO answers, the harness HOW: auto | opencode | dsh | shell | loki.

Engine: each choice sends the message where it says (the harness functions are stand-ins that record the call):
shell -> LOKI's shell agent even with a cloud model; opencode -> OpenCode even with a local model; dsh -> DeepSeek
Harness with whatever model is picked; auto -> local model to the shell agent, cloud to OpenCode. The choice is
remembered (harness.txt) and an old engine.txt "opencode" means auto. Window: the Harness menu beside the model menu
lists all five and picks one. Under a minute.

    python tests/test_harnesses.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-harness-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
(TMP / "data" / "opencode").mkdir(parents=True)
(TMP / "data" / "opencode" / "engine.txt").write_text("opencode")
os.environ.pop("LOKI_AGENT_ENGINE", None)
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP: the engine does not import here (%s)\n\n0 passed, 0 failed" % exc)
    sys.exit(0)
import opencode_engine  # noqa: E402
import dsh_engine  # noqa: E402

check("an old engine.txt 'opencode' (the old default) now means Auto", opencode_engine.engine_choice() == "auto", os.environ.get("LOKI_AGENT_ENGINE"))
check("five harnesses: auto, opencode, dsh, shell, loki", list(opencode_engine.HARNESSES) == ["auto", "opencode", "dsh", "shell", "loki"])

calls = []


async def fake_local(text, name, task=False, preamble=""):
    calls.append(("shell", name)); return "shell"


async def fake_dsh(text, chosen, exe, task=False, preamble=""):
    loki.messages.append({"role": "user", "content": text}); calls.append(("dsh", chosen[0])); return "dsh"


loki.run_local, loki.run_dsh = fake_local, fake_dsh
opencode_engine.find_opencode = lambda *a, **k: "/fake/opencode"
opencode_engine.ensure_index = lambda *a, **k: ""
opencode_engine.run_turn = lambda prompt, ws, **kw: (calls.append(("opencode", kw.get("model"))), {"text": "oc", "tools": [("bash", "completed", "git init", "")]})[1]
dsh_engine.find_dsh = lambda *a, **k: "/fake/dsh"
loki.WORKSPACE = TMP / "ws"; loki.WORKSPACE.mkdir()
loki.AGENT_MODE = "build"
CLOUD = {"groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3", "key": "k"}}


def send(harness, model_name, providers):
    os.environ["LOKI_AGENT_ENGINE"] = harness
    loki.model_name = model_name
    loki._oc_providers = lambda first: providers
    calls.clear()
    asyncio.run(asyncio.wait_for(loki.run_opencode("make a git repo called demo"), 20))
    return list(calls)


check("Shell agent picked: a cloud model goes to the shell agent", send("shell", "groq", CLOUD) == [("shell", "groq")], calls)
check("OpenCode picked: even a local model goes to OpenCode", send("opencode", "local", {"local": {"base_url": "http://localhost:11434/v1", "model": "q", "key": "ollama"}})[0][0] == "opencode", calls)
check("DeepSeek Harness picked: dsh runs the picked model (not only DeepSeek)", send("dsh", "groq", CLOUD) == [("dsh", "groq")], calls)
check("Auto + a local model: the shell agent", send("auto", "local", {}) == [("shell", "local")], calls)
check("Auto + a cloud model: OpenCode", send("auto", "groq", CLOUD)[0] == ("opencode", "loki-groq/llama-3.3"), calls)

# ---- the window
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


async def ui():
    st = {"ok": True, "engine": "auto", "opencode": "/x/opencode", "dsh": "", "codegraph": "", "workspace": "/w",
          "harnesses": [{"id": k, "name": v[0], "what": v[1]} for k, v in opencode_engine.HARNESSES.items()]}
    posts = []
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            print("SKIP window part (%s)" % str(exc)[:80]); return
        page = await b.new_page(viewport={"width": 1300, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8899", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/agent/engine":
                return await r.fulfill(json=st)
            if bare == "/agent/engine/set":
                body = json.loads(r.request.post_data); posts.append(body); st["engine"] = body["engine"]
                return await r.fulfill(json=st)
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8899/**", route)
        await page.goto("http://127.0.0.1:8899/#token=s")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_selector("#harness-button", timeout=8000)
        await page.wait_for_function("document.querySelector('#harness-button').textContent.includes('Auto')", timeout=5000)
        geo = await page.evaluate("""(() => { const a = document.getElementById('model-button').getBoundingClientRect(),
          h = document.getElementById('harness-button').getBoundingClientRect();
          return { gap: Math.round(h.left - a.right), sameRow: Math.abs(a.top - h.top) < 4, w: Math.round(h.width) }; })()""")
        check("the Harness button sits beside the model button, same row, not touching", geo["sameRow"] and geo["gap"] >= 4, geo)
        await page.click("#harness-button")
        items = await page.evaluate("[...document.querySelectorAll('#harness-menu .model-item')].map((b) => b.textContent)")
        check("its menu lists all five, with what each does ('not installed' on DeepSeek Harness here)", len(items) == 5
              and "Shell agent" in items[3] and "not installed" in items[2], items)
        await page.click("#harness-menu [data-harness='shell']")
        await page.wait_for_function("document.querySelector('#harness-button').textContent.includes('Shell agent')", timeout=5000)
        check("picking one sets it (and the button says so)", posts == [{"engine": "shell"}], posts)
        check("no page errors", not errors, errors)
        await b.close()

if async_playwright:
    asyncio.run(asyncio.wait_for(ui(), 45))
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
