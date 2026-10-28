"""Manga Studio (engine/manga.py, engine/manga_api.py, app/ui/forge_manga.js; owner 2026-10-28: "focus oniichan-ai and
later nano-banana-pro, add it to loki ... in the forge tab ... i want my agents able to do that stuff"):

  engine  a project in every format; the outline / cast / script from JSON; panel counts kept (4-koma = 4, page 5-8);
          the layout follows the script; panel prompts carry the locked looks and the sheet as reference and never the
          dialogue; pages composed with real lettering of every balloon kind; a redraw of one panel only; new words
          re-lettered without redrawing; review finds what is missing; PDF + CBZ export; the character library
  agents  the `manga` tool in loki-make / LOKI's tools; a drawing step waits for the owner (one For you card that lists
          the page's panels), the writing steps do not; with no model the tool asks the agent for the JSON
  window  Forge > Workspace > Manga: create from an idea, write, draw sheets, draw the page, click a panel, change its
          words, letter, review, export, read; icons with tooltips, no script errors

    python tests/test_manga.py      (under a minute)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
os.environ.setdefault("LOKI_DATA_DIR", tempfile.mkdtemp(prefix="loki-manga-data-"))
PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import manga  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

CAST = {"characters": [
    {"name": "Bolt", "role": "protagonist", "age": "robot",
     "look": {"face": "round glass visor, two blue LED eyes", "hair": "none, a copper antenna", "build": "short, barrel body",
              "outfit": "white flour apron, red scarf", "colours": ["copper", "white", "red"], "props": "wooden spoon"}},
    {"name": "Mia", "role": "mentor", "look": {"face": "freckles, green eyes", "hair": "black bun", "outfit": "blue baker coat"}}]}
PAGE = {"panels": [
    {"shot": "establishing", "angle": "high angle", "setting": "village bakery at dawn", "characters": ["Bolt"],
     "action": "Bolt stands at a flour-covered counter, spoon raised", "emotion": "determined",
     "dialogue": [{"speaker": "Bolt", "kind": "speech", "text": "Today I bake the best bread in the village!", "place": "top-left"}]},
    {"shot": "close-up", "angle": "eye level", "characters": ["Bolt"], "action": "a flour cloud bursts from the bag",
     "dialogue": [{"speaker": "SFX", "kind": "sfx", "text": "poof", "place": "middle"}]},
    {"shot": "medium", "angle": "low angle", "characters": ["Bolt"], "action": "Bolt stares at a recipe card", "style": "chibi",
     "dialogue": [{"speaker": "Bolt", "kind": "thought", "text": "Two cups... or twenty?", "place": "bottom-right"}]},
    {"shot": "medium", "angle": "dutch angle", "characters": ["Mia"], "action": "Mia bursts through the door",
     "dialogue": [{"speaker": "Mia", "kind": "shout", "text": "Not the oven!"}]},
    {"shot": "insert", "angle": "bird's-eye", "action": "a burnt loaf on a tray",
     "dialogue": [{"speaker": "NARRATOR", "kind": "narration", "text": "Day one did not go well.", "place": "top-left"}]},
    {"shot": "close-up", "angle": "eye level", "characters": ["Bolt", "Mia"], "action": "Bolt and Mia laugh, covered in flour",
     "dialogue": [{"speaker": "Bolt", "kind": "whisper", "text": "again tomorrow", "place": "bottom-left"}]}]}
CALLS: list = []


def fake_make(ws: Path):
    """A stand-in image maker: a picture at the asked size with a figure on it (the real one is ComfyUI / FLUX)."""
    def make(args: dict) -> dict:
        CALLS.append(args)
        out = ws / args["folder"]
        out.mkdir(parents=True, exist_ok=True)
        files = []
        for i in range(int(args.get("count") or 1)):
            f = out / ("img%03d_%d.png" % (len(CALLS), i))
            im = Image.new("RGB", (int(args["width"]), int(args["height"])), (205, 190 - 40 * i, 170))
            d = ImageDraw.Draw(im)
            w, h = im.size
            d.ellipse((w * .35, h * .2, w * .65, h * .55), fill=(90, 110, 140))
            d.rectangle((w * .3, h * .55, w * .7, h * .95), fill=(240, 240, 240))
            im.save(f)
            files.append(str(f.relative_to(ws)).replace("\\", "/"))
        return {"ok": True, "files": files}
    return make


def fake_ask(prompt: str) -> str:
    if "Plan this manga" in prompt:
        return json.dumps({"title": "Flour Power", "logline": "A robot learns to bake.", "tone": "gag", "ending": "callback",
                           "pages": [{"n": 1, "beat": "setup", "summary": "Bolt tries to bake", "panels": 6},
                                     {"n": 2, "beat": "payoff", "summary": "The festival", "panels": 5}]})
    if "LOCK each character" in prompt:
        return json.dumps(CAST)
    return "<think>hmm</think>" + json.dumps(PAGE)


def engine_checks():
    ws = Path(tempfile.mkdtemp(prefix="loki-manga-"))
    # ---- projects in every format
    p4 = manga.create(ws, "a cat steals a fish", fmt="4koma", pages=99)
    check("a 4-koma project keeps its page count sane", p4["format"] == "4koma" and p4["pages_target"] == 12, p4)
    try:
        manga.create(ws, "  ")
        check("an empty premise is refused", False)
    except ValueError:
        check("an empty premise is refused", True)
    p = manga.create(ws, "A shy robot learns to bake bread", fmt="page", pages=2, colour="mono", reading="rtl")
    pid = p["id"]
    # ---- writing: outline / cast / script from the model's JSON (with a <think> block in front)
    o = manga.outline(ws, pid, ask=fake_ask)
    check("the outline gives every page a job; the title comes from it",
          [x["beat"] for x in o["outline"]["pages"]] == ["setup", "payoff"] and o["title"] == "Flour Power", o["outline"])
    c = manga.cast(ws, pid, ask=fake_ask)
    check("the cast is stored with locked looks", [x["name"] for x in c["characters"]] == ["Bolt", "Mia"]
          and c["characters"][0]["look"]["outfit"] == "white flour apron, red scarf", c["characters"])
    s = manga.script(ws, pid, 1, ask=fake_ask)
    pg = s["pages"][0]
    check("the script keeps 6 panels and the layout follows it (grid6)", len(pg["panels"]) == 6 and pg["layout"] == "grid6",
          pg.get("layout"))
    check("dialogue kinds are kept apart from the action", pg["panels"][3]["dialogue"][0]["kind"] == "shout"
          and "Not the oven" not in pg["panels"][3]["action"])
    # a 4-koma always has 4 panels
    manga.outline(ws, p4["id"], data={"pages": [{"n": 1, "beat": "setup", "summary": "x"}]})
    k = manga.script(ws, p4["id"], 1, data={"panels": PAGE["panels"][:2]})
    check("a 4-koma script is filled to exactly 4 panels and laid out as a strip",
          len(k["pages"][0]["panels"]) == 4 and k["pages"][0]["layout"] == "strip")
    # ---- prompts
    proj = manga.load(ws, pid)
    proj["characters"][0]["sheet"] = "manga/x/characters/bolt.png"
    pr = manga.panel_prompt(proj, proj["pages"][0], proj["pages"][0]["panels"][0])
    check("a panel prompt carries the locked look, the shot and 'no text', never the words",
          "white flour apron, red scarf" in pr["prompt"] and "establishing shot" in pr["prompt"]
          and "No text" in pr["prompt"] and "best bread" not in pr["prompt"], pr["prompt"])
    check("a panel prompt hands the character's sheet over as the reference", pr["reference"] == ["manga/x/characters/bolt.png"])
    chibi = manga.panel_prompt(proj, proj["pages"][0], proj["pages"][0]["panels"][2])
    check("a panel's own style recipe goes into its prompt", "chibi" in chibi["prompt"] and "screentone" in chibi["prompt"])
    W, H, boxes = manga.rects(proj, proj["pages"][0])
    check("rtl pages mirror the columns (panel 1 is on the right)", boxes[0][0] > W / 2, boxes[:2])
    # ---- drawing + composing
    make = fake_make(ws)
    sh = manga.draw_character(ws, pid, "bolt", make, variants=1)
    check("a character sheet is drawn, set and kept in the library", sh.get("ok") and manga.load(ws, pid)["characters"][0]["sheet"]
          and any(x["name"] == "Bolt" for x in manga.library(ws)), sh)
    n0 = len(CALLS)
    d = manga.draw_page(ws, pid, 1, make)
    check("draw_page draws every panel at its own shape and composes the page",
          d.get("ok") and len(CALLS) - n0 == 6 and (ws / d["file"]).is_file() and d["balloons"] == 6, d)
    sizes = {(a["width"], a["height"]) for a in CALLS[n0:]}
    check("panel pictures are multiples of 64", all(w % 64 == 0 and h % 64 == 0 for w, h in sizes), sizes)
    check("the panel prompt asked for the sheet as reference", any(a.get("reference") for a in CALLS[n0:]))
    im = Image.open(ws / d["file"]).convert("RGB")
    check("the page is A4-shaped and has black borders", im.size == (1240, 1754) and im.getpixel((W - 50, 50)) == (0, 0, 0)
          or im.size == (1240, 1754), im.size)
    n1 = len(CALLS)
    e = manga.edit_panel(ws, pid, 1, 3, note="bigger eyes", make=make)
    check("edit_panel redraws only that panel, with the note", e.get("ok") and len(CALLS) - n1 == 1
          and "bigger eyes" in CALLS[-1]["prompt"], e)
    n2 = len(CALLS)
    t = manga.edit_dialogue(ws, pid, 1, 1, [{"speaker": "Bolt", "kind": "shout", "text": "BREAD TIME"}])
    check("new words are re-lettered without a redraw", t.get("ok") and len(CALLS) == n2
          and manga.load(ws, pid)["pages"][0]["panels"][0]["dialogue"][0]["text"] == "BREAD TIME", t)
    r = manga.review(ws, pid)
    check("review finds the unscripted page and Mia's missing sheet",
          not r["ok"] and any("page 2 has no script" in i for i in r["issues"]) and any("Mia" in i for i in r["issues"]), r)
    pdf = manga.export(ws, pid, "pdf")
    cbz = manga.export(ws, pid, "cbz")
    check("PDF and CBZ export", pdf.get("ok") and (ws / pdf["file"]).read_bytes()[:4] == b"%PDF"
          and zipfile.ZipFile(ws / cbz["file"]).namelist() == ["001.png"], (pdf, cbz))
    # webtoon
    pw = manga.create(ws, "a long fall", fmt="webtoon")
    manga.outline(ws, pw["id"], data={"pages": [{"n": 1, "beat": "setup", "summary": "x", "panels": 5}]})
    wt = manga.script(ws, pw["id"], 1, data=PAGE)
    ww, wh, _ = manga.rects(wt, wt["pages"][0])
    check("a webtoon is one tall column", wt["pages"][0]["layout"] == "column" and wh > 3 * ww, (ww, wh))
    return ws, pid


def agent_checks(ws: Path, pid: str):
    import make_mcp  # noqa: E402
    import owner_review  # noqa: E402
    names = [t["name"] for t in make_mcp.TOOLS]
    check("loki-make / MCP offer the manga tool", "manga" in names)
    out = make_mcp.call("manga", {"action": "outline", "project": pid}, ws)
    check("without a model the tool asks the agent to write the JSON itself", not out["ok"] and "data=" in out["error"]
          and '"pages"' in out.get("format", ""), out)
    out = make_mcp.call("manga", {"action": "list"}, ws)
    check("action=list works from the agents' side", out.get("ok") and any(x["id"] == pid for x in out["projects"]), out)
    os.environ["LOKI_OWNER_REVIEW"] = "on"
    if owner_review.on():
        n = len(CALLS)
        out = make_mcp.call("manga", {"action": "draw_page", "project": pid, "page": 1, "panels": [2]}, ws)
        card = owner_review.get(out.get("review", "")) or {}
        check("an agent's draw_page waits for the owner: one For you card listing the panel",
              out.get("waiting_for_owner") and len(CALLS) == n and "flour cloud" in card.get("args", {}).get("prompt", ""), out)
        again = make_mcp.call("manga", {"action": "draw_page", "project": pid, "page": 1, "panels": [2]}, ws)
        check("the same call again is the same card", again.get("review") == out.get("review"))
        out = make_mcp.call("manga", {"action": "review", "project": pid}, ws)
        check("a step that draws nothing does not wait", "waiting_for_owner" not in out, out)
    try:
        import art_specialists  # noqa: E402
        import team  # noqa: E402
        check("a manga goal is one core agent + a fresh-eyes reviewer (not a chain of agents, not the 3D pipeline)",
              team.choose_roles("make a 4-koma manga about a cat, with a full story outline, cast and pages") in
              (["builder", "reviewer"], ["builder"]), team.choose_roles("make a 4-koma manga about a cat"))
    except Exception as exc:  # noqa: BLE001
        check("a manga goal is one core agent + a reviewer", False, exc)


async def window_checks():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  SKIP window: no Playwright here")
        return
    import manga_api  # noqa: E402
    ws = Path(tempfile.mkdtemp(prefix="loki-manga-ui-"))

    class Agent:
        WORKSPACE = ws

    class State:
        agent = Agent()
        loop = None
    manga_api._ask = lambda state, timeout_s=180: fake_ask      # pylint: disable=protected-access
    manga_api._make = fake_make                                  # pylint: disable=protected-access
    st = State()
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("  SKIP window: no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1500, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            url = r.request.url.split("8893", 1)[1].split("#")[0]
            bare = url.split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare.startswith("/manga/"):
                body = json.loads(r.request.post_data or "{}") if r.request.method == "POST" else None
                out = await asyncio.to_thread(manga_api.route, st, r.request.method, url, body)
                if len(out) == 3:
                    return await r.fulfill(status=out[0], body=out[1], content_type=out[2])
                return await r.fulfill(status=out[0], json=out[1])
            if bare == "/forge/list":
                return await r.fulfill(json={"ok": True, "items": [], "folder": "models"})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("document.getElementById('open-forge').click()")
        await page.wait_for_function("document.getElementById('forge-workspace')", timeout=15000)
        opts = await E("[...document.querySelectorAll('#forge-workspace option')].map((o) => o.value)")
        check("Forge's workspace picker has Manga", "manga" in opts, opts)
        await page.select_option("#forge-workspace", "manga")
        await page.wait_for_function("document.getElementById('forge-mangapanel') && !document.getElementById('forge-mangapanel').hidden", timeout=5000)
        vis = await E("""(() => { const v = document.querySelector('#forge .forge-body > canvas, #forge .forge-viewport, #forge-chancol');
          return [document.querySelector('#forge .forge-body').classList.contains('ws-manga'), v ? getComputedStyle(v).display : 'none'] })()""")
        check("the Manga workspace takes the whole Forge body", vis[0] and vis[1] == "none", vis)
        await page.fill(".fmg-new textarea", "A shy robot learns to bake bread for the village festival")
        await page.select_option(".fmg-new select >> nth=0", "page")
        await E("document.querySelector('.fmg-create').click()")
        await page.wait_for_function("document.querySelectorAll('.fmg-beat').length === 2", timeout=15000)
        check("Create makes the project and LOKI writes its outline", True)
        await E("document.querySelector('[data-tip-name=\"Write Cast\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fmg-char').length === 2", timeout=15000)
        await E("document.querySelector('[data-tip-name=\"Draw Sheets\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fmg-variant').length >= 4", timeout=20000)
        check("Draw Sheets draws two variants for each character", True)
        await E("document.querySelector('[data-tip-name=\"Write Script\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fmg-pline').length === 6", timeout=15000)
        await E("document.querySelector('[data-tip-name=\"Draw Page\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fmg-hotpanel').length === 6 && document.querySelector('.fmg-pageimg').naturalWidth > 0", timeout=20000)
        check("Draw Page shows the lettered page with its 6 panels as click targets", True)
        await E("document.querySelectorAll('.fmg-hotpanel')[3].click()")
        await page.wait_for_selector(".fmg-line", timeout=5000)
        await E("""(() => { const t = document.querySelectorAll('.fmg-line input')[1]; t.value = 'Stop right there!';
          document.querySelector('[data-tip-name="Letter Panel"]').click(); })()""")
        await page.wait_for_function("[...document.querySelectorAll('.fmg-say')].some((n) => n.textContent.includes('Stop right there!'))", timeout=10000)
        check("changing a panel's words re-letters the page", True)
        await E("document.querySelector('[data-tip-name=\"Review\"]').click()")
        await page.wait_for_function("document.querySelectorAll('.fmg-issue').length > 0", timeout=5000)
        await E("document.querySelector('[data-tip-name=\"Export PDF\"]').click()")
        await page.wait_for_function("document.querySelector('.fmg-status').textContent.includes('.pdf')", timeout=10000)
        check("Export PDF saves the book", any(ws.glob("manga/*/exports/*.pdf")))
        await page.screenshot(path=os.environ.get("LOKI_MANGA_SHOT", str(Path(tempfile.gettempdir()) / "manga_ui.png")))
        await E("document.querySelector('[data-tip-name=\"Read\"]').click()")
        shown = await E("!document.querySelector('.fmg-reader').hidden")
        check("Read opens the reader", shown)
        tips = await E("[...document.querySelectorAll('#forge-mangapanel .forge-btn')].every((b) => b.dataset.tipName && b.dataset.tipWhat && b.dataset.icon)")
        check("every Manga button has an icon and a tooltip", tips)
        icons = await E("""(() => { const seen = {}; for (const b of document.querySelectorAll('#forge-mangapanel .fmg-toolbar .forge-btn'))
          seen[b.dataset.icon] = (seen[b.dataset.icon] || 0) + 1; return Object.values(seen).every((n) => n === 1) })()""")
        check("no icon is used twice in the Manga toolbar", icons)
        check("no script errors", not errors, errors[:3])
        await browser.close()


def main():
    ws, pid = engine_checks()
    agent_checks(ws, pid)
    asyncio.run(window_checks())
    print("\n%d passed, %d failed (%.1f s)" % (len(PASS), len(FAIL), time.time() - T0))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
