// Home's 3D preview (app/ui/model_preview.js): the framing maths - centred on the model, far enough back that the
// whole bounding sphere fits the field of view, whatever the model's size.
//   node tests/js/test_model_preview.js   (< 1 s)
"use strict";
const path = require("path");
global.window = global;
const P = require(path.join(__dirname, "../../app/ui/model_preview.js"));
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d))); };
const f = P.frame({ min: [-1, 0, -1], max: [1, 2, 1] }, 35);
check("centre of the box", JSON.stringify(f.center) === JSON.stringify([0, 1, 0]), f.center);
check("radius = half the diagonal", Math.abs(f.radius - Math.sqrt(12) / 2) < 1e-9, f.radius);
check("the sphere fits the view (distance * sin(fov/2) >= radius)", f.distance * Math.sin(35 * Math.PI / 360) >= f.radius, f);
const tiny = P.frame({ min: [0, 0, 0], max: [0, 0, 0] }, 35);
check("an empty box still gives a usable camera", tiny.radius > 0 && isFinite(tiny.distance) && tiny.distance > 0, tiny);
const big = P.frame({ min: [-500, -500, -500], max: [500, 500, 500] }, 35);
check("scales with the model", big.distance / f.distance > 100, [big.distance, f.distance]);
check("mount is exported for Home", typeof P.mount === "function");
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
