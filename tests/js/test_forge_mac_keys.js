// On a Mac, Forge never takes Cmd+H / Q / W / M - macOS hides, quits, closes or minimizes the whole app on those (owner
// 2026-10-25: "loki just crashed while i was modeling ... a hot key": Cmd+H was Forge's Hide and macOS's Hide Loki).
// Their Forge commands are on the real Control key there; the labels say so.   node tests/js/test_forge_mac_keys.js
"use strict";
const fs = require("fs"), path = require("path");
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d))); };
const src = fs.readFileSync(path.join(__dirname, "../../app/ui/forge_keys.js"), "utf8").replace(/^"use strict";/m, "");
function load(platform) {
  Object.defineProperty(globalThis, "navigator", { value: { platform }, configurable: true });
  global.window = global;
  return new Function(src + "\nreturn { forgeKeyChord, forgeKeyLabel, FORGE_KEYS: typeof FORGE_KEYS !== 'undefined' ? FORGE_KEYS : null };")();
}
const ev = (o) => Object.assign({ key: "h", code: "KeyH", ctrlKey: false, metaKey: false, altKey: false, shiftKey: false }, o);
let K = load("MacIntel");
for (const [key, what] of [["h", "Hide Loki"], ["q", "Quit"], ["w", "Close"], ["m", "Minimize"]]) {
  check("Mac: Cmd+" + key.toUpperCase() + " is left to macOS (" + what + ")", K.forgeKeyChord(ev({ key, code: "Key" + key.toUpperCase(), metaKey: true })) === "");
}
check("Mac: Control+H is Forge's Hide (ctrl+h)", K.forgeKeyChord(ev({ ctrlKey: true })) === "ctrl+h");
check("Mac: other Cmd shortcuts still work (Cmd+Z = ctrl+z, Cmd+D = ctrl+d)", K.forgeKeyChord(ev({ key: "z", code: "KeyZ", metaKey: true })) === "ctrl+z"
  && K.forgeKeyChord(ev({ key: "d", code: "KeyD", metaKey: true })) === "ctrl+d");
check("Mac: the menus show Control+H for Hide, Cmd+Z for Undo", K.forgeKeyLabel("ctrl+h") === "Control+H" && K.forgeKeyLabel("ctrl+z") === "Cmd+Z", [K.forgeKeyLabel("ctrl+h"), K.forgeKeyLabel("ctrl+z")]);
K = load("Win32");
check("Windows: Ctrl+H is Hide, shown as Ctrl+H", K.forgeKeyChord(ev({ ctrlKey: true })) === "ctrl+h" && K.forgeKeyLabel("ctrl+h") === "Ctrl+H");
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
