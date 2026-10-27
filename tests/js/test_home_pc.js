// Home's "Your PC" button (app/ui/home.js pcText): what it says for each state of /offload/status (engine/offload.py).
//   node tests/js/test_home_pc.js   (< 1 s)
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
global.window = global;
Object.defineProperty(global, "navigator", { value: { platform: "MacIntel", userAgent: "" }, configurable: true });
global.localStorage = { getItem: () => null, setItem: () => {} };
global.document = { addEventListener: () => {}, getElementById: () => null };
vm.runInThisContext(fs.readFileSync(path.join(__dirname, "../../app/ui/home.js"), "utf8"));
const H = window.LokiHome;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d))); };
const on = H.pcText({ role: "light", gives: { image: "pc", img2img: "pc", make_3d: "pc", polish: "pc" }, machines: [{ name: "pc", online: true, work: ["image"] }] });
check("PC takes the work: green, and says which work", on.on && /pictures, area edits, 3D models, model clean-ups run on pc/.test(on.what), on);
const none = H.pcText({ role: "light", gives: {}, machines: [] });
check("no PC linked: says how to link it", !none.on && /link code/.test(none.what), none);
const off = H.pcText({ role: "light", gives: {}, machines: [{ name: "pc", online: false, error: "cannot reach pc" }] });
check("PC offline: says to open LOKI there", !off.on && /not answering/.test(off.name) && /Open LOKI on pc/.test(off.what), off);
const old = H.pcText({ role: "light", gives: {}, machines: [{ name: "pc", online: true }] });
check("older LOKI on the PC: says it needs an update", /needs an update/.test(old.name), old);
const why = H.pcText({ role: "light", gives: {}, machines: [{ name: "pc", online: true, work: [], work_why: { polish: "Blender is not installed here" } }] });
check("PC up but not set up: says what is missing", /model clean-ups: Blender is not installed/.test(why.what), why);
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
