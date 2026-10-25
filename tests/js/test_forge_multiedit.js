// ForgePoly.multiJoin / multiSplit: several objects' components edited as one cage, split back after
// (owner 2026-10-25: "Shift select another mesh and see its verts and select them as well, just like Maya").
//   node tests/js/test_forge_multiedit.js
"use strict";
global.window = global;
require("../../app/ui/forge_poly.js");
try { require("../../app/ui/forge_polyops.js"); } catch (_) { /* the kernel alone is enough for most */ }
const P = window.ForgePoly;
let pass = 0, fail = 0;
const check = (name, ok, detail) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  <- " + JSON.stringify(detail).slice(0, 300))); };
const move = (m, d) => ({ v: m.v.map((p) => [p[0] + d[0], p[1] + d[1], p[2] + d[2]]), f: m.f.map((f) => f.slice()) });
const same = (a, b) => a.v.length === b.v.length && a.f.length === b.f.length && a.v.every((p, i) => p.every((x, j) => Math.abs(x - b.v[i][j]) < 1e-9)) && a.f.every((f, i) => f.join() === b.f[i].join());

const A = P.primitive("cube"), B = move(P.primitive("sphere"), [3, 0, 0]), C = move(P.primitive("cylinder"), [-3, 0, 0]);
const { m, info } = P.multiJoin([A, B, C]);
check("join: every vertex and face, nothing welded", m.v.length === A.v.length + B.v.length + C.v.length && m.f.length === A.f.length + B.f.length + C.f.length);
let back = P.multiSplit(m, info);
check("split right after join: the exact parts back", back.length === 3 && same(back[0], A) && same(back[1], B) && same(back[2], C));

// only moves (a vertex of the cube and a vertex of the sphere): exact, positions follow
const m2 = { v: m.v.map((p) => p.slice()), f: m.f };
m2.v[0][1] += 0.4; m2.v[A.v.length + 5][0] += 0.25;
back = P.multiSplit(m2, info);
check("moved components: same topology per part, the moves kept", back[0].v.length === A.v.length && Math.abs(back[0].v[0][1] - (A.v[0][1] + 0.4)) < 1e-9
  && Math.abs(back[1].v[5][0] - (B.v[5][0] + 0.25)) < 1e-9 && back[2].f.length === C.f.length);

// a whole part moved (no vertex where it was): still its own part (nearest middle)
const m3 = { v: m.v.map((p, i) => (i >= A.v.length + B.v.length ? [p[0] - 0.2, p[1] + 0.1, p[2]] : p.slice())), f: m.f.map((f) => f.slice()) };
m3.f.push(m3.f[0].slice());   // and a topology change so the vote path runs
back = P.multiSplit(m3, info);
check("vote path: a part moved as a whole still goes back to its object", back[2].f.length === C.f.length && back[1].f.length === B.f.length && back[0].f.length === A.f.length + 1);

// topology change: extrude one face of the sphere part (if the ops are here), delete a face of the cube part
if (P.extrude) {
  const fi = A.f.length + 3, ex = P.extrude(m, [fi], 0.3);
  const mm = ex.m || ex;
  back = P.multiSplit(mm, info);
  check("extrude a face of the 2nd object: the new faces go to it, the others keep theirs", back[1].f.length === B.f.length + B.f[3].length && back[0].f.length === A.f.length && back[2].f.length === C.f.length,
    back.map((b) => b.f.length));
}
const del = { v: m.v, f: m.f.filter((_, i) => i !== 0) };
back = P.multiSplit(del, info);
check("delete a face of the 1st object: it loses that face, nothing else changes", back[0].f.length === A.f.length - 1 && back[1].f.length === B.f.length && back[2].f.length === C.f.length);
const gone = { v: m.v, f: m.f.slice(A.f.length) };
back = P.multiSplit(gone, info);
check("delete the whole 1st object's faces: its part is empty, the others intact", back[0].f.length === 0 && back[1].f.length === B.f.length && back[2].f.length === C.f.length);
// two parts that share nothing even when they overlap in space
const D = P.primitive("cube"), E = P.primitive("cube");
const j2 = P.multiJoin([D, E]);
const ch = { v: j2.m.v, f: j2.m.f.concat([[0, 1, 2]]) };   // force the vote path
back = P.multiSplit(ch, j2.info);
check("two cubes in the same place: each piece goes to one of them, all faces kept", back[0].f.length + back[1].f.length === D.f.length + E.f.length + 1);

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
