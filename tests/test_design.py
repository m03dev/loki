"""Design with OpenPencil (engine/design.py, engine/design_api.py, app/ui/forge_design.js) and phone testing with
mobile-mcp (engine/mobile_test.py, engine/mcp_servers.json "mobile"; owner 2026-10-28: "add mobile next mcp server for
testing ... as well as open-pencil somewhere"):

  engine  the exact OpenPencil command lines (import / render via an args file / export / lint / tree / eval), a preview
          after every change, PDF refused with the reason, names kept inside designs/, telemetry off, no Node = a clear
          error; one real OpenPencil run when Node is here (LOKI_SUITE_OPENPENCIL=0 skips it)
  agents  `design` in loki-make / MCP; the Tool Shelf recipes for openpencil and mobile-mcp validate; the MCP servers
          start only when they can work (a device / the desktop app)
  window  Forge > Workspace > Design: list with previews, Draw It, Export, Check Design shows lint problems, Ask an
          Agent hands the brief to a background agent; icons with tooltips; no script errors

    python tests/test_design.py      (under a minute)
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import design  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00"
       b"\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


class Fake:
    """Stands in for `openpencil ...`: records the command, writes the file it would write."""
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, cwd=None, env=None, input=None, **_):  # noqa: A002
        cmd = list(cmd)
        self.calls.append({"cmd": cmd, "cwd": cwd, "env": env, "input": input})
        args = cmd[len(design.cli()):] if cmd[:len(design.cli())] == design.cli() else cmd[1:]
        out = ""
        code = 0
        if "-o" in args:
            target = Path(cwd) / args[args.index("-o") + 1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(PNG if target.suffix == ".png" else b"fig")
        if args[:1] == ["import"]:
            out = json.dumps({"pages": 1, "rootElements": 1})
        if args[:2] == ["tool", "call"]:
            argf = Path(cwd) / args[args.index("--args-file") + 1]
            self.calls[-1]["args_file"] = json.loads(argf.read_text())
            out = json.dumps({"id": "1:1", "name": "Card"})
        if args[:1] == ["lint"]:
            code, out = 1, json.dumps({"messages": [{"ruleId": "color-contrast", "message": "Contrast 2.9:1 is below WCAG AA",
                                                     "nodeName": "Go"}]})
        if args[:1] == ["tree"]:
            out = json.dumps([{"id": "0:4", "name": "card", "type": "FRAME"}])
        if args[:1] == ["eval"]:
            out = json.dumps(["card"])
        return subprocess.CompletedProcess(cmd, code, out, "")


def engine_checks():
    if not design.cli():
        design.cli = lambda: ["openpencil"]       # the fake runner does not need Node
    ws = Path(tempfile.mkdtemp(prefix="loki-design-"))
    fake = Fake()
    r = design.tool({"action": "new", "name": "Login Screen", "html": "<div class='c'>Hi</div>", "css": ".c{color:red}"},
                    ws, runner=fake)
    imp = fake.calls[0]["cmd"]
    check("new imports HTML + CSS into designs/<name>.fig with the page name",
          r.get("ok") and r["file"] == "designs/login-screen.fig" and "import" in imp and "--css" in imp
          and "--pageName" in imp, (r, imp))
    check("every change writes a PNG preview", r.get("preview") == "designs/login-screen.png"
          and (ws / "designs" / "login-screen.png").is_file())
    check("telemetry is off for every run", fake.calls[0]["env"].get("OPENPENCIL_TELEMETRY") == "0"
          and fake.calls[0]["env"].get("DO_NOT_TRACK") == "1")
    again = design.tool({"action": "new", "name": "login-screen"}, ws, runner=fake)
    check("an existing design is never overwritten by new", not again.get("ok") and "already exists" in again["error"])
    jsx = '<Frame name="Card" w={300} h={200} bg="#7c3aed"><Text size={24}>Hello</Text></Frame>'
    r = design.tool({"action": "render", "name": "login-screen", "jsx": jsx}, ws, runner=fake)
    rc = next(c for c in fake.calls if c["cmd"][-5:-3] == ["--args-file", ".login-screen.args.json"] or "render" in c["cmd"])
    check("render runs OpenPencil's render tool with the JSX in an args file, written back",
          r.get("ok") and rc.get("args_file", {}).get("jsx") == jsx and "-w" in rc["cmd"]
          and not (ws / "designs" / ".login-screen.args.json").exists(), (r, rc["cmd"]))
    check("render with no JSX says what to send", "jsx=" in design.tool({"action": "render", "name": "x"}, ws, runner=fake)["error"])
    r = design.tool({"action": "export", "name": "login-screen", "format": "tailwind-jsx"}, ws, runner=fake)
    check("export writes into designs/exports", r.get("ok") and r["file"] == "designs/exports/login-screen.jsx", r)
    r = design.tool({"action": "export", "name": "login-screen", "format": "png", "scale": 3}, ws, runner=fake)
    check("a picture export carries its scale", r.get("ok") and r["file"].endswith("@3x.png") and "-s" in fake.calls[-1]["cmd"], r)
    design.tool({"action": "call", "name": "login-screen", "tool": "describe", "args": {"tool": "set_fill"}}, ws, runner=fake)
    check("an agent asking what a core tool takes (call tool=describe) gets 'tool describe <name>', not an error",
          fake.calls[-1]["cmd"][-4:] == ["tool", "describe", "set_fill", "--json"], fake.calls[-1]["cmd"])
    r = design.tool({"action": "export", "name": "login-screen", "format": "pdf"}, ws, runner=fake)
    check("PDF is refused with the reason (broken in 0.16.0)", not r["ok"] and "svg" in r["error"])
    r = design.tool({"action": "lint", "name": "login-screen"}, ws, runner=fake)
    check("lint reports the problems and is not clean", not r["ok"] and r["report"]["messages"][0]["ruleId"] == "color-contrast", r)
    r = design.tool({"action": "tree", "name": "login-screen"}, ws, runner=fake)
    check("tree returns the layers", r.get("ok") and r["tree"][0]["name"] == "card", r)
    r = design.tool({"action": "eval", "name": "login-screen", "code": "return 1"}, ws, runner=fake)
    check("eval sends the code on stdin and reads JSON back", r.get("ok") and fake.calls[-1]["input"] == "return 1"
          and r["result"] == ["card"], r)
    try:
        design._file(ws, "../../etc/passwd")
        bad = design._file(ws, "../../etc/passwd").parent == (ws / "designs").resolve()
    except ValueError:
        bad = True
    check("a name can never leave designs/", bad)
    listed = design.tool({"action": "list"}, ws, runner=fake)
    check("list shows the design with its preview", listed["designs"][0]["preview"] == "designs/login-screen.png", listed)
    old = design.cli
    design.cli = lambda: []
    try:
        r = design.tool({"action": "lint", "name": "login-screen"}, ws, runner=fake)
        check("no Node: a clear error, nothing run", "Node" in str(r.get("error") or r.get("report")), r)
    finally:
        design.cli = old
    return ws


def real_openpencil():
    if os.environ.get("LOKI_SUITE_OPENPENCIL", "1") == "0" or not shutil.which("npx"):
        print("  SKIP real OpenPencil run (no npx or LOKI_SUITE_OPENPENCIL=0)")
        return
    import importlib
    importlib.reload(design)
    ws = Path(tempfile.mkdtemp(prefix="loki-design-real-"))
    t = time.time()
    r = design.tool({"action": "render", "name": "badge", "jsx": '<Frame name="Badge" w={240} h={96} bg="#7c3aed" rounded={16} '
                     'p={20}><Text size={28} color="#ffffff" weight="bold">Manga</Text></Frame>'}, ws)
    if not r.get("ok") and ("npm" in str(r.get("error")) or "ENOTFOUND" in str(r.get("error"))):
        print("  SKIP real OpenPencil run (the package could not be fetched)")
        return
    ok = r.get("ok") and (ws / "designs" / "badge.png").is_file()
    size = ()
    if ok:
        from PIL import Image
        with Image.open(ws / "designs" / "badge.png") as im:
            size, px = im.size, im.convert("RGB").getpixel((5, 48))
        ok = size == (240, 96) and px[2] > 200 and px[1] < 100
    check("a real OpenPencil run draws the JSX: a 240x96 purple badge (%.0f s)" % (time.time() - t), ok, (r, size))


def agent_checks():
    import make_mcp  # noqa: E402
    import toolshelf  # noqa: E402
    import mobile_test  # noqa: E402
    check("loki-make / MCP offer the design tool", "design" in [t["name"] for t in make_mcp.TOOLS])
    for rid in ("openpencil", "mobile-mcp"):
        check("the Tool Shelf recipe %s is valid" % rid, toolshelf.validate(toolshelf.recipe(rid)) == [])
    cfg = json.loads((REPO / "engine" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
    mob, op = cfg.get("mobile") or {}, cfg.get("openpencil") or {}
    check("mobile-mcp is pinned, telemetry off, started only with a device",
          "@mobilenext/mobile-mcp@1.0.14" in mob.get("args", []) and mob.get("env", {}).get("MOBILEMCP_DISABLE_TELEMETRY") == "1"
          and mob.get("requires_check") == "mobile_test.devices_ready" and len(mob.get("tools", [])) <= 16, mob)
    check("OpenPencil's MCP starts only while its app is open",
          op.get("requires_check") == "design.app_running" and "@open-pencil/mcp@0.16.0" in op.get("args", []), op)

    def fake_run(cmd, **_):
        if cmd[:2] == ["xcrun", "simctl"]:
            return subprocess.CompletedProcess(cmd, 0, "== Devices ==\n    iPhone 16 (ABC) (Booted)\n", "")
        return subprocess.CompletedProcess(cmd, 0, "List of devices attached\nemulator-5554\tdevice\nR58M\tunauthorized\n", "")
    old_adb = mobile_test.adb
    mobile_test.adb = lambda: "adb"
    try:
        devs = mobile_test.devices(runner=fake_run)
    finally:
        mobile_test.adb = old_adb
    check("devices finds the Android emulator (and skips an unauthorised phone)",
          {"platform": "android", "kind": "emulator", "name": "emulator-5554"} in devs
          and not any(d["name"] == "R58M" for d in devs), devs)


async def window_checks():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  SKIP window: no Playwright here")
        return
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("  SKIP window: no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1500, "height": 950})
        errors, posts = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        st = {"designs": [{"name": "home", "file": "designs/home.fig", "preview": "designs/home.png", "updated": 1, "size": 9}],
              "job": {}}

        async def route(r):
            url = r.request.url.split("8893", 1)[1].split("#")[0]
            bare = url.split("?")[0]
            if bare == "/":   # with the window's REAL security policy - blob: pictures came out blank in the app
                import loki_bridge  # noqa: E402 - pylint: disable=import-outside-toplevel
                return await r.fulfill(path=str(UI / "index.html"), headers={"Content-Security-Policy": loki_bridge.UI_CSP.replace(
                    "script-src 'self'", "script-src 'self' 'unsafe-eval'")})   # (the test driver evaluates scripts)
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            body = json.loads(r.request.post_data or "{}") if r.request.method == "POST" else {}
            if r.request.method == "POST":
                posts.append((bare, body))
            if bare == "/design/list":
                return await r.fulfill(json={"ok": True, "designs": st["designs"], "cli": True, "app": False,
                                             "mobile": {"devices": [{"platform": "ios", "kind": "simulator", "name": "iPhone 16"}],
                                                        "app_id": "dev.m03.loki"}})
            if bare == "/design/file":
                return await r.fulfill(body=PNG, content_type="image/png")
            if bare == "/design/do":
                act = body.get("action")
                res = {"ok": True, "file": "designs/%s.fig" % body.get("name"), "preview": "designs/%s.png" % body.get("name")}
                if act == "lint":
                    res = {"ok": False, "report": {"messages": [{"message": "Contrast 2.9:1 is below WCAG AA", "nodeName": "Go"}]}}
                if act == "render" and body.get("name") not in [d["name"] for d in st["designs"]]:
                    st["designs"].insert(0, {"name": body["name"], "file": res["file"], "preview": res["preview"], "updated": 2})
                st["job"] = res
                return await r.fulfill(json={"ok": True, "job": "j1"})
            if bare == "/design/job":
                return await r.fulfill(json={"ok": True, "status": "done", "result": st["job"]})
            if bare == "/jobs":
                return await r.fulfill(json={"ok": True, "id": "bg1", "jobs": []})
            if bare == "/forge/list":
                return await r.fulfill(json={"ok": True, "items": [], "folder": "models"})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("document.getElementById('open-forge').click()")
        await page.wait_for_function("document.getElementById('forge-workspace')", timeout=15000)
        await page.select_option("#forge-workspace", "design")
        await page.wait_for_function("document.getElementById('forge-designpanel') && !document.getElementById('forge-designpanel').hidden"
                                     " && document.querySelectorAll('.fds-item').length === 1", timeout=8000)
        check("Forge > Design lists the designs with previews", True)
        await page.fill(".fds-name", "login")
        await E("document.querySelector('[data-tip-name=\"Draw It\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fds-item').length === 2", timeout=8000)
        sent = [b for (u, b) in posts if u == "/design/do" and b.get("action") == "render"]
        check("Draw It sends the JSX to render into the named design", sent and sent[0]["name"] == "login" and "<Frame" in sent[0]["jsx"], posts)
        await E("document.querySelector('[data-tip-name=\"Check Design\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fds-result .fmg-issue').length === 1", timeout=8000)
        check("Check Design lists the lint problems", True)
        await page.select_option(".fds-format", "svg")
        await E("document.querySelector('[data-tip-name=\"Export\"]').click()")
        await page.wait_for_function("document.querySelector('.fds-status').textContent.includes('Exporting done')", timeout=8000)
        check("Export asks for the picked format", any(b.get("action") == "export" and b.get("format") == "svg" for (u, b) in posts))
        await page.fill(".fds-brief", "a dark login screen for the LOKI phone app")
        await E("document.querySelector('[data-tip-name=\"Ask an Agent\"]').click()")
        await page.wait_for_function("document.querySelector('.fds-status').textContent.includes('agent')", timeout=8000)
        job = [b for (u, b) in posts if u == "/jobs"]
        check("Ask an Agent hands the brief (and the owner's design playbook) to a background agent",
              job and "dark login screen" in job[0]["prompt"] and "playbook" in job[0]["prompt"], job)
        mob = await E("document.querySelector('.fds-mobile').textContent")
        check("Phone testing shows the device", "iPhone 16" in mob, mob)
        tips = await E("[...document.querySelectorAll('#forge-designpanel .forge-btn')].every((b) => b.dataset.tipName && b.dataset.tipWhat && b.dataset.icon)")
        check("every Design button has an icon and a tooltip", tips)
        check("no script errors", not errors, errors[:3])
        await browser.close()


def main():
    engine_checks()
    agent_checks()
    real_openpencil()
    asyncio.run(window_checks())
    print("\n%d passed, %d failed (%.1f s)" % (len(PASS), len(FAIL), time.time() - T0))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
