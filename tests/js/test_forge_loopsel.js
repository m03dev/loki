// Select > Grow / Shrink Along Loop, Contiguous Edges, Every Nth (forge_polyops.js; FORGE_MODELING_FOUNDATION stage 4)
//   node tests/js/test_forge_loopsel.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
require("../../app/ui/forge_polyops.js");
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + String(JSON.stringify(d)).slice(0, 300))); };

// a 4 x 4 quad grid (5 x 5 vertices), y = 0
const I = (x, y) => y * 5 + x, g = { v: [], f: [] };
for (let y = 0; y < 5; y++) for (let x = 0; x < 5; x++) g.v.push([x, 0, y]);
for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) g.f.push([I(x, y), I(x + 1, y), I(x + 1, y + 1), I(x, y + 1)]);
const row = (y, a, b) => { const out = []; for (let x = a; x < b; x++) out.push([I(x, y), I(x + 1, y)]); return out; };
const has = (es, a, b) => es.some(([p, q]) => (p === a && q === b) || (p === b && q === a));

let s = P.growAlongLoop(g, { e: [[I(2, 2), I(3, 2)]] });
check("Grow Along Loop: one edge -> one more at each end (3)", s.e.length === 3 && has(s.e, I(1, 2), I(2, 2)) && has(s.e, I(3, 2), I(4, 2)), s.e);
s = P.growAlongLoop(g, s);
check("... again: the loop meets the border, so 4 (it never jumps off the row)", s.e.length === 4 && s.e.every(([a, b]) => g.v[a][2] === 2 && g.v[b][2] === 2), s.e);
s = P.shrinkAlongLoop(g, { e: row(2, 0, 4) });
check("Shrink Along Loop: the ends go back (4 -> 2)", s.e.length === 2 && has(s.e, I(1, 2), I(2, 2)), s.e);
check("Shrink of one edge: nothing left", P.shrinkAlongLoop(g, { e: [[I(2, 2), I(3, 2)]] }).e.length === 0);

const cube = P.addDivisions(P.primitive("cube"), [0, 1, 2, 3, 4, 5], { divisions: 1 }).m;   // 2 x 2 per side
const Tc = P.topology(cube);
const mid = Tc.edges.findIndex((e, i) => P.edgeLoop(cube, Tc, i).length === 8);
const loop = P.edgeLoop(cube, Tc, mid).map((ei) => [Tc.edges[ei].a, Tc.edges[ei].b]);
check("(a closed loop of 8 round the cube)", loop.length === 8, loop.length);
check("a closed loop: Grow and Shrink Along Loop leave it as it is", P.growAlongLoop(cube, { e: loop }).e.length === 8
  && P.shrinkAlongLoop(cube, { e: loop }).e.length === 8);
check("Every 2nd of the closed loop: 4, no two touching", (() => { const o = P.everyNth(cube, { e: loop }, 2).e;
  const vs = o.flat(); return o.length === 4 && new Set(vs).size === 8; })());
check("Every 3rd of an open row of 4: the 1st and the 4th", (() => { const o = P.everyNth(g, { e: row(2, 0, 4) }, 3).e;
  return o.length === 2 && has(o, I(0, 2), I(1, 2)) && has(o, I(3, 2), I(4, 2)); })());
const ring = []; for (let y = 0; y < 5; y++) ring.push([I(2, y), I(3, y)]);
check("Every 2nd of a ring (5 edges across the strip): 3", (() => { const o = P.everyNth(g, { e: ring }, 2).e;
  return o.length === 3 && has(o, I(2, 0), I(3, 0)) && has(o, I(2, 2), I(3, 2)) && has(o, I(2, 4), I(3, 4)); })(), P.everyNth(g, { e: ring }, 2).e);

// faces: a strip of quads along row 1
const fid = (x, y) => y * 4 + x;
s = P.growAlongLoop(g, { f: [fid(1, 1), fid(2, 1)] });
check("Grow Along Loop on faces: the strip takes the next face at both ends", s.f.length === 4 && s.f.includes(fid(0, 1)) && s.f.includes(fid(3, 1)), s.f);
s = P.shrinkAlongLoop(g, { f: [fid(0, 1), fid(1, 1), fid(2, 1), fid(3, 1)] });
check("Shrink Along Loop on faces: the end faces go", s.f.length === 2 && s.f.includes(fid(1, 1)) && s.f.includes(fid(2, 1)), s.f);
check("Every 2nd face of the strip", P.everyNth(g, { f: [0, 1, 2, 3] }, 2).f.join() === "0,2");

// vertices grow like the edges between them
s = P.growAlongLoop(g, { v: [I(2, 2), I(3, 2)] });
check("Grow Along Loop on vertices: one more vertex each way", s.v.length === 4 && s.v.includes(I(1, 2)) && s.v.includes(I(4, 2)), s.v);

// Contiguous Edges goes on through a pole where an ordinary loop stops
const p = { v: g.v.map((x) => x.slice()), f: g.f.filter((_, i) => i !== fid(2, 2)) };
p.f.push([I(2, 2), I(3, 2), I(3, 3)], [I(2, 2), I(3, 3), I(2, 3)]);   // one quad split in two: (2,2) is a 5-pole
const Tp = P.topology(p), e0 = Tp.edge(I(0, 2), I(1, 2));
check("(the ordinary loop stops at the pole: 2 edges)", P.edgeLoop(p, Tp, e0).length === 2, P.edgeLoop(p, Tp, e0).length);
s = P.contiguousEdges(p, { e: [[I(0, 2), I(1, 2)]] });
check("Contiguous Edges: straight on through the pole, the whole row (4)", s.e.length === 4 && s.e.every(([a, b]) => g.v[a][2] === 2 && g.v[b][2] === 2), s.e);
check("Contiguous Edges never turns a 90° corner (cube edge: stops at the corners)", (() => {
  const ce = Tc.edges.findIndex((e) => Tc.edges.indexOf(e) >= 0 && e.faces.length === 2 && [cube.v[e.a], cube.v[e.b]].every((q) => Math.abs(Math.abs(q[0]) - 0.5) < 1e-6 && Math.abs(Math.abs(q[2]) - 0.5) < 1e-6));
  const o = P.contiguousEdges(cube, { e: [[Tc.edges[ce].a, Tc.edges[ce].b]] }).e; return ce >= 0 && o.length === 2; })());
console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
