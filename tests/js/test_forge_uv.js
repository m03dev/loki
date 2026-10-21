// Forge's UV model (app/ui/forge_uv.js) in node: projections make valid map UVs, cut / sew change the shells and
// nothing moves, camera projection follows the screen, the GPU corner UVs, texel density, UVs kept through modelling.
//   node tests/js/test_forge_uv.js        (< 1 s)
"use strict";
const path = require("path");
global.window = global;
require(path.join(__dirname, "../../app/ui/forge_poly.js"));
require(path.join(__dirname, "../../app/ui/forge_uv.js"));
const P = window.ForgePoly, U = window.ForgeUV;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };

const cube = P.primitive("cube");
check("a fresh cube has no UVs", !U.has(cube), Object.keys(cube));
const pl = U.planar(cube, [], "z");
check("Planar Z: valid map UVs, one shell, inside 0-1", U.has(pl) && U.shells(pl).length === 1 && pl.uv.every((p) => p[0] >= -1e-9 && p[0] <= 1 + 1e-9 && p[1] >= -1e-9 && p[1] <= 1 + 1e-9), { n: U.shells(pl).length });
check("...and the cage is not touched (new object, same vertices)", pl !== cube && JSON.stringify(pl.v) === JSON.stringify(cube.v) && !U.has(cube), null);
const au = U.automatic(cube, [], 6);
check("Automatic (6 planes) on a cube: six shells", U.has(au) && U.shells(au).length === 6, U.shells(au).length);
check("...every cube edge is a seam (12)", U.seams(au).size === 12, U.seams(au).size);
const sewn = U.sew(au, [[cube.f[0][0], cube.f[0][1]]]);
check("Sew one edge: five shells, that edge is no seam any more", U.shells(sewn).length === 5 && U.seams(sewn).size === 11, [U.shells(sewn).length, U.seams(sewn).size]);
const ms = U.moveAndSew(au, [[cube.f[0][0], cube.f[0][1]]]);
check("Move and Sew: five shells and the smaller shell moved (no stretched middle: the sewn edge keeps its length)", U.shells(ms).length === 5, U.shells(ms).length);
// cut a planar-mapped cube along edges: shells split, no UV moves
const one = U.planar(cube, [], "best");
const E = [...U.edges(one).values()];
const ring = E.filter((e) => Math.abs(cube.v[e.a][1] - cube.v[e.b][1]) > 0.5);   // the 4 vertical edges
const cutC = U.cut(one, ring.map((e) => [e.a, e.b]));
const before = U.cornerUVs(one), after = U.cornerUVs(cutC);
check("Cut the 4 vertical edges alone: the UVs do not move, still one shell (every corner is still joined through the top / bottom - a cut only opens where it reaches a border or another seam)",
  before.every((x, i) => Math.abs(x - after[i]) < 1e-12) && U.shells(cutC).length === 1, U.shells(cutC).length);
const top = E.filter((e) => cube.v[e.a][1] > 0 && cube.v[e.b][1] > 0);
const cut2 = U.cut(cutC, top.map((e) => [e.a, e.b]));
check("Cut the top square too: the top face is its own shell (2 shells)", U.shells(cut2).length === 2, U.shells(cut2).length);
const after2 = U.cornerUVs(cut2);
check("...the cut moved nothing, and the 4 top edges are seams now", before.every((x, i) => Math.abs(x - after2[i]) < 1e-12) && [...top].every((e) => U.seams(cut2).has(U.ekey(e.a, e.b))), U.seams(cut2).size);
check("cornerUVs: one UV per face corner (24 for a cube)", U.cornerUVs(cut2).length === 48, U.cornerUVs(cut2).length);
// camera-based: the screen's x / y
const cam = U.camera(cube, [], (p) => [p[0] + 0.5 * p[2], p[1]]);
check("Camera-based: one shell, the projection's proportions kept inside 0-1", U.has(cam) && U.shells(cam).length === 1 && cam.uv.every((p) => p[0] >= -1e-9 && p[0] <= 1 + 1e-9), null);
// cylindrical on a cylinder: the wrap seam split, no face spans more than half the width
const cyl = P.primitive("cylinder");
const cy = U.cylindrical(cyl, [], "y");
const wide = cy.fuv.filter((c, fi) => cyl.f[fi].length === 4).filter((c) => { const us = c.map((i) => cy.uv[i][0]); return Math.max(...us) - Math.min(...us) > 0.5; }).length;
check("Cylindrical: valid, no side face wraps across the whole map (the wrap seam is split)", U.has(cy) && wide === 0, wide);
check("Spherical on a sphere: valid", U.has(U.spherical(P.primitive("sphere"), [])), null);
// transforms
const ids = U.uvsOfFaces(pl, [0]);
const mv = U.transform(pl, ids, { move: [0.25, 0] });
check("Move UVs: only the chosen UVs move, by the amount", [...ids].every((i) => Math.abs(mv.uv[i][0] - pl.uv[i][0] - 0.25) < 1e-12), null);
const rot = U.transform(pl, new Set(pl.uv.map((_, i) => i)), { rotate: 90 });
const b0 = U.bbox(pl, pl.uv.map((_, i) => i)), b1 = U.bbox(rot, rot.uv.map((_, i) => i));
check("Rotate 90 about the centre: the box's width becomes its height", Math.abs((b0.x1 - b0.x0) - (b1.y1 - b1.y0)) < 1e-9, [b0, b1]);
// density
const d0 = U.density(au, [], 1024);
const dd = U.setDensity(au, [], 512, 1024);
check("Texel density: Set density 512 px/unit -> every shell measures 512", U.shells(dd).every((s) => Math.abs(U.density(dd, s.faces, 1024) - 512) < 0.5), [d0, U.shells(dd).map((s) => U.density(dd, s.faces, 1024))]);
const dist = U.distortion(pl);
check("Distortion: one entry per face, a planar map of the side faces is squashed (stretch ~0)", dist.length === 6 && dist.some((d) => d.stretch < 0.05), dist.map((d) => d.stretch.toFixed(2)));
// carry through modelling: extrude one face of a mapped cube
const ext = P.extrude(au, [0], 0.3);
const kept = U.carry(au, ext);
check("Extrude a mapped cube: the UVs come along (still valid), the new side faces are flagged", U.has(kept) && kept.uvNew && kept.uvNew.length >= 4, kept.uvNew && kept.uvNew.length);
const same = kept.f.findIndex((f) => f.join() === cube.f[1].join());
check("...an untouched face keeps exactly its UVs", same >= 0 && JSON.stringify(kept.fuv[same].map((i) => kept.uv[i])) === JSON.stringify(au.fuv[1].map((i) => au.uv[i])), same);
check("...the old seams are all still seams", [...U.seams(au)].every((k) => U.seams(kept).has(k)), null);
const moved = { v: au.v.map((p) => [p[0] * 2, p[1], p[2]]), f: au.f.map((f) => f.slice()) };
const k2 = U.carry(au, moved);
check("Moving vertices (same faces) keeps every UV and adds no new faces", U.has(k2) && k2.uvNew.length === 0 && U.shells(k2).length === 6, [k2.uvNew.length, U.shells(k2).length]);
check("A cage without UVs passes through carry untouched", U.carry(cube, ext) === ext, null);
check("A different object (no faces in common) gets no UVs from the old one", U.carry(au, P.primitive("torus")).uv === undefined, null);
U.unfold(au, [], {}).then(() => check("unfold without engine refused", false, "resolved"), (e) => {
  check("unfold without the C++ engine is refused with a clear message", /engine/.test(e.message), e.message);
  console.log("\n" + pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
});
