"""LOKI World - the character creator and "Join world" (offline, well under a minute).

    python tests/test_character.py

engine/character.py (GET/POST /character, <data>/world/character.json) validates and keeps the
character; app/ui/character.js is the creator; app/ui/mmo/mmo_core.js dresses your avatar in
it; GET /mmo/state carries it as profile.look for the Godot client (docs/MMO_API.md).
The window part runs in headless Chromium when Playwright is there (skipped otherwise).
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import character  # noqa: E402

PASS, FAIL = [], []
UI = REPO / "app" / "ui"
TMP = Path(tempfile.mkdtemp(prefix="loki-char-"))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:400]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


class Agent:
    DATA_DIR = str(TMP / "data")
    WORKSPACE = str(TMP / "ws")


class State:
    agent = Agent()


GOOD = {"name": "Wren", "role": "artist", "body": "slim", "skin": "#a8754f", "hair": "curly", "hair_color": "#c4512e",
        "eyes": "wide", "eye_color": "#3f9a5a", "top": "hoodie", "top_color": "#d26aa8", "bottom": "skirt",
        "bottom_color": "#3b4a6b", "accessory": "scarf", "accessory_color": "#e0a73a"}

# ------------------------------------------------------------------------------------------
section("the route: save, load, validate")
code, out = character.route(State(), "GET", "/character", {})
check("GET /character with none made yet -> character null, with the options", code == 200 and out["character"] is None
      and out["options"]["role"] == ["builder", "explorer", "artist", "scholar"] and out["name_max"] == 24, out)
check("every role has a name and one line of what it means", all(r["name"] and r["about"] for r in out["roles"].values())
      and set(out["roles"]) == set(out["options"]["role"]))
code, out = character.route(State(), "POST", "/character", GOOD)
check("POST /character saves a good character", code == 200 and out["character"]["name"] == "Wren"
      and out["character"]["hair"] == "curly", out)
code, out = character.route(State(), "GET", "/character", {})
check("...and GET /character loads it back", code == 200 and {k: out["character"][k] for k in GOOD} == GOOD, out)
saved = TMP / "data" / "world" / "character.json"
check("kept per machine in <data>/world/character.json", saved.is_file() and json.loads(saved.read_text())["name"] == "Wren")
code, out = character.route(State(), "POST", "/character", {"name": "  Kit   Fox "})
check("missing fields take the defaults; spaces tidied", code == 200 and out["character"]["name"] == "Kit Fox"
      and out["character"]["role"] == "builder", out)
bad_cases = [
    ("an empty name", {"name": "   "}),
    ("no name", {"role": "artist"}),
    ("a name over 24 characters", {"name": "x" * 25}),
    ("a name that is not text", {"name": 7}),
    ("an unknown role", dict(GOOD, role="wizard")),
    ("an unknown hair style", dict(GOOD, hair="mohawk")),
    ("a colour not in the palette", dict(GOOD, top_color="#123456")),
    ("free CSS as a colour", dict(GOOD, skin="red;}")),
    ("a number as an option", dict(GOOD, body=3)),
    ("an unknown field", dict(GOOD, script="<b>")),
    ("not an object", ["Wren"]),
]
for label, body in bad_cases:
    code, out = character.route(State(), "POST", "/character", body)
    check("refused: %s (400, says why)" % label, code == 400 and out.get("ok") is False and out.get("error"), (code, out))
check("a refused save leaves the saved one alone", character.load(Path(Agent.DATA_DIR))["name"] == "Kit Fox")
check("control and bidi characters are stripped from the name",
      character.validate({"name": "Mo‮\x00ha"})["name"] == "Moha")
check("exactly 24 characters is fine", character.validate({"name": "y" * 24})["name"] == "y" * 24)
check("upper-case options are read as the same option", character.validate(dict(GOOD, hair="LONG"))["hair"] == "long")
saved.write_text("{broken", encoding="utf-8")
check("a broken file reads as no character (the creator shows again)", character.load(Path(Agent.DATA_DIR)) is None)
saved.write_text(json.dumps(dict(GOOD, hair="mohawk")), encoding="utf-8")
check("a hand-edited file with an unknown option reads as no character", character.load(Path(Agent.DATA_DIR)) is None)
check("other methods / paths", character.route(State(), "PUT", "/character", {})[0] == 405
      and character.route(State(), "GET", "/characters", {})[0] == 404)
character.save(Path(Agent.DATA_DIR), GOOD)

section("the bridge, /mmo/state and the Godot client")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("loki_bridge routes GET and POST /character to engine/character.py",
      bridge.count('route == "/character"') == 2 and bridge.count("character.route(") == 2)
try:
    import mmo_state  # noqa: E402

    class Store:
        def all(self):
            return []

    class Jobs:
        store = Store()

    State.jobs = Jobs()
    State.chat_lock = None
    code, out = mmo_state.route(State(), "GET", "/mmo/state", {}, lambda *a: (200, {}))
    look = out.get("profile", {}).get("look") or {}
    check("GET /mmo/state carries the character as profile.look, and its name", code == 200 and look.get("hair") == "curly"
          and out["profile"]["name"] == "Wren", (code, str(out)[:300]))
except ImportError as exc:   # pragma: no cover
    check("mmo_state imports", False, exc)
api_doc = (REPO / "docs" / "MMO_API.md").read_text(encoding="utf-8")
check("docs/MMO_API.md documents profile.look and /character", "profile.look" in api_doc and "/character" in api_doc)
player_gd = (REPO / "game" / "loki-world" / "scripts" / "actors" / "player.gd").read_text(encoding="utf-8")
check("the Godot player builds its model from profile.look", 'p.get("look")' in player_gd and "top_color" in player_gd)

section("the window files")
js = (UI / "character.js").read_text(encoding="utf-8")
core = (UI / "mmo" / "mmo_core.js").read_text(encoding="utf-8")
html = (UI / "index.html").read_text(encoding="utf-8")
m = re.search(r"const OPTIONS = (\{.*?\n  \});", js, re.S)
js_opts = json.loads(re.sub(r"(\w+):", r'"\1":', re.sub(r",\s*\}", "}", m.group(1)))) if m else {}
check("the creator offers exactly the engine's options", js_opts == character.OPTIONS, (js_opts.keys(), character.OPTIONS.keys()))
check("index.html loads character.js after mmo_core.js", html.index("/ui/mmo/mmo_core.js") < html.index("/ui/character.js"))
check("the world button says Join world (translated), not Play", 'tr("world.join", "Join world")' in js
      and '"\\u25B6 Join world"' in core and "Play\"" not in core and "▶ Play" not in core)
check("no inline handlers, no eval, nothing from the network", "onclick=" not in js and "eval(" not in js
      and not re.search(r"https?://", js))
check("the preview reuses LOKI World's own renderer (shaders, meshes, blit) and person model",
      all(x in js for x in ("makeProgram(gl, VS, FS", "OUTLINE_VS", "BLIT_FS", "MESH_SRC", "M.person(")))
check("Randomize, Edit character and keyboard radios are there", all(x in js for x in ("randomize", "world.edit", 'role", "radio"', "u-arrows")))
en = json.loads((UI / "i18n" / "en.json").read_text(encoding="utf-8"))
check("Join world is in every string table", all(json.loads((UI / "i18n" / (l + ".json")).read_text(encoding="utf-8")).get("world.join")
                                                for l in ("en", "es", "fr", "de", "ar", "hi", "zh", "ja")) and en["world.join"] == "Join world")
hot = core.split("// HOT:BEGIN", 1)[1].split("// HOT:END", 1)[0]
person_src = core.split("function person(", 1)[1].split("MMO.person = person;", 1)[0]
bad = [x for x in ("new ", "Object.assign", ".map(", ".filter(", "=> ", "JSON.") if x in person_src]
check("person() allocates nothing per frame (pooled, like avatar())", not bad and not re.findall(r"(?<![\w\]\)])\[\s*-?[\d.]+\s*,", person_src), bad)
check("the scene draws your look when you have one", "MMO.look ? personAt : avatar" in hot)
if shutil.which("node"):
    for f in ("character.js", "mmo/mmo_core.js"):
        proc = subprocess.run(["node", "--check", str(UI / f)], capture_output=True, text=True)
        check("%s parses" % f, proc.returncode == 0, proc.stderr)
ship = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("ship.py runs this suite", '"test_character"' in ship)

# ------------------------------------------------------------------------------------------
section("in the window (headless Chromium)")
try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None


def chromium_path() -> str:
    import os
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


async def window(have: dict | None) -> dict:
    """Open the window against a fake engine whose /character answers `have`; returns findings."""
    found: dict = {"errors": [], "posts": []}
    async with async_playwright() as p:
        exe = chromium_path()
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            found["skip"] = str(exc)[:160]
            return found
        page = await browser.new_page(viewport={"width": 1240, "height": 820})
        page.on("pageerror", lambda e: found["errors"].append(str(e)))
        store = {"c": have}
        fake = {
            "/health": {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "", "route": [],
                        "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0"}, "ui_errors": []},
            "/world": {"ok": True, "agents": [], "machines": [], "self": {"name": "test", "os": "Linux"}, "creations": {"count": 0, "latest": []}},
            "/settings/general": {"ok": True, "values": {"LOKI_WORLD": "background", "LOKI_WORLD_ENGINE": "classic"}},
        }

        async def route(r):
            path = r.request.url.split("8898", 1)[1].split("?")[0].split("#")[0]
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/"):
                f = UI / path[4:]
                if f.is_file():
                    return await r.fulfill(path=str(f))
                return await r.fulfill(json={"ok": True})
            if path == "/character":
                if r.request.method == "POST":
                    body = json.loads(r.request.post_data or "{}")
                    found["posts"].append(body)
                    code, out = character.route(State(), "POST", "/character", body)
                    if code == 200:
                        store["c"] = out["character"]
                    return await r.fulfill(status=code, json=out)
                return await r.fulfill(json={"ok": True, "character": store["c"], "options": character.OPTIONS})
            return await r.fulfill(json=fake.get(path, {"ok": True}))

        await page.route("http://127.0.0.1:8898/**", route)
        await page.goto("http://127.0.0.1:8898/#token=t")
        await page.wait_for_function("window.LOKI_READY === true && window.LokiCharacter && window.LokiCharacter.loaded", timeout=20000)
        await page.click("#open-settings")
        await page.evaluate("showTab('world')")
        await page.wait_for_selector("#world-join", timeout=8000)
        await page.wait_for_timeout(300)
        found["join_text"] = (await page.text_content("#world-join") or "").strip()
        found["join_tip"] = await page.get_attribute("#world-join", "data-tip-name")
        found["join_icon"] = bool(await page.query_selector("#world-join svg.icon"))
        found["active_before"] = await page.evaluate("MMO.active")
        if not found["active_before"]:
            await page.click("#world-join")
        await page.wait_for_timeout(300)
        found["dialog_open"] = await page.is_visible("#character-dialog")
        if found["dialog_open"]:
            found["focus"] = await page.evaluate("document.activeElement && document.activeElement.id")
            await page.fill("#char-name", "")
            await page.click("#char-join")
            await page.wait_for_timeout(150)
            found["empty_err"] = (await page.text_content(".char-err") or "").strip()
            await page.fill("#char-name", "Juno")
            await page.click("#char-randomize")
            # keyboard: arrows move through a radio group and choose
            await page.focus('[data-field="hair"] [aria-checked="true"]')
            before = await page.evaluate("document.activeElement.dataset.value")
            await page.keyboard.press("ArrowRight")
            found["arrow_moved"] = await page.evaluate("document.activeElement.dataset.value") != before
            found["arrow_checked"] = await page.evaluate("document.activeElement.getAttribute('aria-checked')") == "true"
            await page.click('[data-field="top_color"] [data-value="#55b85c"]')
            await page.click('[data-field="role"] [data-value="scholar"]')
            await page.wait_for_timeout(200)
            found["preview_pixels"] = await page.evaluate("""() => {
                const c = document.querySelector('.char-canvas'); if (!c || c.hidden) return -1;
                const g = c.getContext('webgl'); const px = new Uint8Array(4 * 9); let lit = 0;
                for (let i = 0; i < 9; i++) { g.readPixels(Math.floor(c.width * (0.3 + 0.05 * i)), Math.floor(c.height * 0.5), 1, 1, g.RGBA, g.UNSIGNED_BYTE, px.subarray(i * 4)); }
                for (let i = 0; i < 9; i++) if (Math.abs(px[i*4] - 41) + Math.abs(px[i*4+1] - 46) + Math.abs(px[i*4+2] - 59) > 30) lit++;
                return lit; }""")
            await page.click("#char-join")
            await page.wait_for_timeout(400)
            found["dialog_after"] = await page.is_visible("#character-dialog")
        found["active_after"] = await page.evaluate("MMO.active")
        found["look"] = await page.evaluate("MMO.look && {name: MMO.look.name, top: MMO.look.raw.top_color, role: MMO.look.role}")
        found["cls"] = await page.evaluate("MMO.myClass()")
        # what the world draws for you this frame: the scene description every renderer gets
        found["drawn"] = await page.evaluate("""() => {
            const L = { solids: [], clear: [], shadows: [], glows: [], puffs: [], lights: [] };
            MMO.scene(L, 1, 0.016, {}, performance.now());
            return L.solids.map((o) => o.color.map((v) => Math.round(v * 255)).join(','));
        }""")
        found["spectate_text"] = (await page.text_content("#world-join") or "").strip()
        found["edit_text"] = (await page.text_content("#world-edit-character") or "").strip()
        await browser.close()
    return found


def rgb(hexs: str) -> str:
    return ",".join(str(int(hexs[i:i + 2], 16)) for i in (1, 3, 5))


if async_playwright is None:
    print("  SKIP: no Playwright here")
else:
    w = asyncio.run(window(None))
    if w.get("skip"):
        print("  SKIP: Playwright has no Chromium (%s)" % w["skip"])
    else:
        check("the button that enters the world reads Join world, with an icon and a tooltip",
              w["join_text"] == "Join world" and w["join_tip"] == "Join world" and w["join_icon"], w)
        check("with no character you are not walking yet", w["active_before"] is False, w)
        check("Join world with no character opens the creator, focus on the name", w["dialog_open"] and w.get("focus") == "char-name", w)
        check("an empty name is refused in the window too", "name" in w.get("empty_err", "").lower(), w.get("empty_err"))
        check("arrow keys move through and choose in an option group", w.get("arrow_moved") and w.get("arrow_checked"), w)
        check("the live preview draws (pixels other than the background)", (w.get("preview_pixels") or 0) >= 2, w.get("preview_pixels"))
        check("Join world in the creator saves to the engine and enters the world", w["posts"] and w["posts"][-1]["name"] == "Juno"
              and w["posts"][-1]["top_color"] == "#55b85c" and not w["dialog_after"] and w["active_after"] is True, w)
        check("the world's player uses the saved look and name", w["look"] == {"name": "Juno", "top": "#55b85c", "role": "scholar"}
              and rgb("#55b85c") in w["drawn"], (w["look"], w["drawn"][:12]))
        check("the role is your class (Scholar -> Mage)", w["cls"] == "Mage", w["cls"])
        check("once in, the buttons read Spectate and Edit character", w["spectate_text"] == "Spectate" and w["edit_text"] == "Edit character", w)
        check("no script errors", not w["errors"], w["errors"][:3])
        w2 = asyncio.run(window(dict(GOOD)))
        check("with a saved character the world opens with you in it, no creator", not w2.get("dialog_open")
              and w2["active_before"] is True and w2["active_after"] is True and w2["spectate_text"] == "Spectate", w2)
        check("...drawn in the saved look (hoodie colour) with its name", w2["look"] and w2["look"]["name"] == "Wren"
              and rgb(GOOD["top_color"]) in w2["drawn"] and rgb(GOOD["skin"]) in w2["drawn"], (w2["look"], w2["drawn"][:12]))
        check("no script errors (saved character)", not w2["errors"], w2["errors"][:3])

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
