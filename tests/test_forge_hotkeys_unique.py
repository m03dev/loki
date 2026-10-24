"""Forge's hotkeys: nothing is used twice (owner 2026-10-22: "go through them all and make sure nothing is used twice").

Every Forge key lives in ONE table (app/ui/forge_keys.js FORGE_KEY_DEFAULTS, run by forge_pro.js). This checks:
  * no chord is listed twice in the table (a second entry silently replaced the first);
  * every action in the table is a real command (FORGE_PRO_CMDS / the sculpt and mask commands) or a special "@" one;
  * no other Forge file grabs a bare key of its own any more (sculpt mode's d / x / l / h / q / 1-9, forge.js's old
    Esc / w / e / r / [ ] handler, the hard-coded fallback switch in forge_pro.js);
  * the table keeps clear of the app's mode-bar keys (Option+1..4 on a Mac, Ctrl+F1..F4 on Windows).
Static (no browser), a few seconds.

    python tests/test_forge_hotkeys_unique.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


keys_src = (UI / "forge_keys.js").read_text(encoding="utf-8")
body = keys_src.split("const FORGE_KEY_DEFAULTS = [", 1)[1].split("\n];", 1)[0]
pairs = re.findall(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]', body)
check("the table was read", len(pairs) > 80, len(pairs))
seen, dups = {}, []
for chord, act in pairs:
    if chord in seen:
        dups.append("%s = %s and %s" % (chord, seen[chord], act))
    seen[chord] = act
check("no key is listed twice in the hotkey table", not dups, dups)

# chords are written the canonical way forgeKeyChord produces (ctrl, alt, shift, key - in that order)
bad_order = [c for c, _ in pairs if "+" in c.strip("+") and c.split("+")[:-1] != [m for m in ("ctrl", "alt", "shift") if m in c.split("+")[:-1]]]
check("every chord is written ctrl+alt+shift+key (so the lookup can find it)", not bad_order, bad_order)

# every action is a command somewhere in Forge
ui_src = "\n".join(p.read_text(encoding="utf-8") for p in UI.glob("forge*.js"))
special = set(re.findall(r'"(@\w+)":', keys_src.split("const FORGE_KEY_SPECIAL = {", 1)[1].split("};", 1)[0]))
missing = []
for _, act in pairs:
    if act.startswith("@"):
        if act not in special:
            missing.append(act)
        continue
    defined = re.search(r'(^|[\s{,])%s:\s*\[' % re.escape(act), ui_src, re.M) or \
        re.search(r'(FORGE_PRO_CMDS|\bC)\.%s\s*=' % re.escape(act), ui_src) or \
        re.search(r'\badd\(\s*"%s"\s*,\s*"' % re.escape(act), ui_src) or \
        re.search(r'C\["sculptFav" \+ \(i \+ 1\)\]', ui_src) and act.startswith("sculptFav") or \
        re.search(r'FORGE_PRO_CMDS\["menuSet" \+ k\]', ui_src) and act.startswith("menuSet")
    if not defined:
        missing.append(act)
check("every action in the table is a real command", not missing, sorted(set(missing)))

# the app's mode keys stay the app's
mode_keys = {"alt+%d" % i for i in range(1, 5)} | {"ctrl+f%d" % i for i in range(1, 5)}
check("the table keeps clear of the mode bar's keys (Option+1..4, Ctrl+F1..F4)", not (mode_keys & set(seen)), mode_keys & set(seen))

# sculpt keys are in the table (one meaning in every workspace)
for chord, act in (("pageup", "sculptLevelUp"), ("pagedown", "sculptLevelDown"), ("l", "sculptLazy"),
                   ("shift+u", "maskClear"), ("alt+shift+h", "maskHideToggle"), ("ctrl+shift+1", "sculptFav1")):
    check("sculpt: %s = %s" % (chord, act), seen.get(chord) == act, seen.get(chord))
for chord, act in (("d", "@pivotHold"), ("x", "@snapGrid"), ("h", "hideToggle"), ("1", "smooth1"), ("q", "select"), ("f8", "objComp")):
    check("the Maya key %s keeps one meaning (%s), in sculpt mode too" % (chord, act), seen.get(chord) == act, seen.get(chord))

# Maya 2027's own default keys (docs/forge/maya2027_layout.json, read from hotkeySetup.mel): where Forge has the command,
# Forge's key is Maya's key (owner 2026-10-22: "almost 1:1 to maya")
for chord, act in (("ctrl+s", "save"), ("ctrl+shift+x", "multiCut"), ("ctrl+shift+q", "quadDraw"), ("shift+x", "@snapGrid"),
                   ("shift+c", "@snapEdge"), ("shift+v", "@snapPoint"), ("ctrl+alt+arrowleft", "spinEdgeBack"),
                   ("ctrl+alt+arrowright", "spinEdge"), ("alt+f12", "uvShell"), ("f2", "menuSetModeling"), ("f4", "menuSetAnimation"),
                   ("f6", "menuSetRendering"), ("ctrl+1", "isolate"), ("alt+shift+d", "deleteHistory"), ("ctrl+e", "extrude"), ("ctrl+b", "bevel")):
    check("Maya's key %s = %s" % (chord, act), seen.get(chord) == act, seen.get(chord))
check("Maya's Ctrl+I is Import, so Forge doesn't use it for anything else", "ctrl+i" not in seen, seen.get("ctrl+i"))
sculpt_ctx = dict(re.findall(r'"([^"]+)":\s*"(\w+)"', keys_src.split("const FORGE_KEY_SCULPT = {", 1)[1].split("};", 1)[0]))
check("while sculpting Ctrl/Cmd+Shift+I inverts the mask (Maya's sculpt-tool key), and only that key changes meaning",
      sculpt_ctx == {"ctrl+shift+i": "maskInvert"} and seen.get("ctrl+shift+i") == "invert", sculpt_ctx)

# no file grabs bare keys of its own any more
sc = (UI / "forge_sculpt_ui.js").read_text(encoding="utf-8")
handler = sc.split("// keys in sculpt mode:", 1)[1].split("}, true);", 1)[0]
grabs = re.findall(r'(?:e\.key|k)\s*===\s*"([^"]+)"', handler)
check("sculpt mode's key handler only knows Esc (+ a brush's own key)", set(grabs) <= {"Escape"}, grabs)
check("a brush's own key can't take a key the table has", "function fscTaken(c)" in sc and "forgeKeyAction(c)" in sc)
fj = (UI / "forge.js").read_text(encoding="utf-8")
check("forge.js's old key handler is gone (Esc closed Forge, w / e / r and [ ] meant other things)",
      'v.toggleTransform({ w: "translate"' not in fj and "if (e.key === \"Escape\") { forgeClose(); return; }" not in fj)
fp = (UI / "forge_pro.js").read_text(encoding="utf-8")
check("forge_pro.js has no hard-coded key switch left beside the table", 'case "q": return run("select");' not in fp and "forgeKeyAction(chord)" in fp)
fe = (UI / "forge_edit.js").read_text(encoding="utf-8")
check("the Blender-style G / R / S modal (and its keys) is gone", "view.modalStart" not in fe and "Blender's modal transform" not in fe)
check("picking another tool leaves sculpt mode (the pro way)", "FORGE_PRO_LEAVE_SCULPT" in fp and "forgeSculptUI.exit()" in fp)

# the table really loads in JS (node) and gives each chord one action
node = shutil.which("node")
if node:
    js = keys_src.replace("window.forgeHotkeys = forgeHotkeys;", "").replace("window.forgeOwnsKey = forgeOwnsKey;", "")
    js = "const window = {}; const localStorage = { getItem: () => null, setItem() {} };\n" + js + \
        "\nconsole.log(JSON.stringify({ n: FORGE_KEY_DEFAULTS.length, m: Object.keys(forgeKeysDefaultMap()).length }));"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    try:
        r = json.loads(out.stdout.strip().splitlines()[-1])
        check("in JS too: as many keys in the map as rows in the table", r["n"] == r["m"], r)
    except Exception as exc:  # noqa: BLE001
        check("forge_keys.js runs in node", False, (out.stderr or str(exc))[-400:])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
