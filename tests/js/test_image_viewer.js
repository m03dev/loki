// The picture viewer's pure parts (app/ui/image_viewer.js): stepping stops at the ends, Cropper's pixel box ->
// shares of the picture, the list keeps pictures once and in order.
//   node tests/js/test_image_viewer.js   (< 1 s)
"use strict";
const path = require("path");
global.window = global;
const V = require(path.join(__dirname, "../../app/ui/image_viewer.js"));
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d))); };
check("next from the first", V.step(0, 1, 5) === 1);
check("no wrap past the last", V.step(4, 1, 5) === 4);
check("no wrap before the first", V.step(0, -1, 5) === 0);
check("empty list", V.step(3, 1, 0) === 0);
check("box as shares", JSON.stringify(V.shareBox({ x: 100, y: 50, width: 200, height: 100 }, 1000, 500)) === JSON.stringify([0.1, 0.1, 0.2, 0.2]), V.shareBox({ x: 100, y: 50, width: 200, height: 100 }, 1000, 500));
check("box clamped to the picture", V.shareBox({ x: 900, y: -10, width: 300, height: 100 }, 1000, 500)[2] === 0.1);
check("no box outside", V.shareBox({ x: 1200, y: 0, width: 10, height: 10 }, 1000, 500) === null);
const c = V.clean([{ src: "a" }, { src: "b", path: "images/b.png" }, { src: "a" }, null, { name: "no src" }]);
check("pictures once, in order", c.length === 2 && c[0].src === "a" && c[1].path === "images/b.png", c);
// thumbs + settings (engine/image_settings.py's "honoured" lists drive the panel)
const steps = { key: "steps", label: "Steps", type: "int", honoured: ["sdcpp", "mflux", "nvidia", "auto"] };
check("a setting the model honours is live", V.fieldState(steps, "mflux").on === true);
check("a setting the model ignores is greyed with why", V.fieldState({ key: "sampler", label: "Sampler", honoured: ["sdcpp"] }, "nvidia").on === false
      && /ignores Sampler/.test(V.fieldState({ key: "sampler", label: "Sampler", honoured: ["sdcpp"] }, "nvidia").why));
const schema = [{ key: "aspect", type: "enum" }, { key: "megapixels", type: "float" }, { key: "width", type: "int" },
  { key: "height", type: "int" }, { key: "steps", type: "int" }, { key: "negative", type: "text" }, { key: "from_picture", type: "bool" }];
const a = V.collect({ aspect: "16:9", megapixels: "1", width: "800", height: "600", steps: "", negative: "", from_picture: true }, schema, false);
check("aspect + megapixels unless exact size; empty fields left out", JSON.stringify(a) === JSON.stringify({ aspect: "16:9", megapixels: 1, from_picture: true }), a);
const b = V.collect({ aspect: "16:9", megapixels: "1", width: "800", height: "600", steps: "12" }, schema, true);
check("exact size: width and height in pixels, numbers as numbers", b.width === 800 && b.height === 600 && b.steps === 12 && !("aspect" in b), b);
check("thumbs: up, down, none", JSON.stringify([V.thumbs(1), V.thumbs(-1), V.thumbs(0)]) === "[[true,false],[false,true],[false,false]]");
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
