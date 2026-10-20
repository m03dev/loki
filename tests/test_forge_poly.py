"""Forge poly modelling + DynaMesh (app/ui/forge_poly.js) in node: every primitive is closed (or a plane) with its
faces pointing outward (signed volume > 0), extrude / inset / Catmull-Clark keep the mesh closed and grow it the
right way, and DynaMesh turns a sphere (and a cube with a hole in it) into an even quad mesh of about the same size.
Skips without node. Well under a minute.

    python tests/test_forge_poly.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


JS = r"""
const P = require(process.argv[1]);
const out = {};
function closed(m) {            // every edge used exactly twice, once each way
  const e = new Map();
  for (const f of m.f) for (let k = 0; k < f.length; k++) {
    const a = f[k], b = f[(k + 1) % f.length], key = a + ">" + b;
    if (e.has(key)) return false; e.set(key, 1);
  }
  for (const key of e.keys()) { const [a, b] = key.split(">"); if (!e.has(b + ">" + a)) return false; }
  return true;
}
for (const k of Object.keys(P.PRIMITIVES)) {
  const m = P.primitive(k, {});
  out[k] = { v: m.v.length, f: m.f.length, vol: P.volume(m), closed: closed(m) };
}
const cube = P.primitive("cube", { segments: 1 });
const top = cube.f.findIndex((f) => P.faceNormal(cube, f)[1] > 0.9);
const ex = P.extrude(cube, [top], 0.5);
out.extrude = { vol: P.volume(ex), closed: closed(ex), faces: ex.f.length };
const two = P.extrude(P.primitive("cube", { segments: 2 }), (() => { const c = P.primitive("cube", { segments: 2 });
  return c.f.map((f, i) => [i, P.faceNormal(c, f)[1]]).filter((x) => x[1] > 0.9).map((x) => x[0]); })(), 0.25);
out.region = { vol: P.volume(two), closed: closed(two) };
const ins = P.inset(cube, [top], 0.3);
out.inset = { vol: P.volume(ins), closed: closed(ins), faces: ins.f.length };
const sm = P.smooth(cube);
out.smooth = { vol: P.volume(sm), closed: closed(sm), faces: sm.f.length, quads: sm.f.every((f) => f.length === 4) };
const tri = P.triangulate(P.primitive("cylinder", {}));
out.tri = { ok: tri.idx.length % 3 === 0 && tri.tri2face.length === tri.idx.length / 3 };
const sph = P.triangulate(P.primitive("sphere", { segments: 32, rings: 16 }));
const t0 = Date.now(), dm = P.dynamesh(sph.pos, sph.idx, 48);
let rmax = 0, rmin = 9; for (const p of dm.v) { const r = Math.hypot(p[0], p[1], p[2]); rmax = Math.max(rmax, r); rmin = Math.min(rmin, r); }
out.dyna = { v: dm.v.length, f: dm.f.length, quads: dm.f.every((f) => f.length === 4), vol: P.volume(dm), closed: closed(dm), rmin, rmax, ms: Date.now() - t0 };
const holed = P.deleteFaces(P.primitive("cube", { segments: 4 }), [0]);
const ht = P.triangulate(holed), dh = P.dynamesh(ht.pos, ht.idx, 40);
out.holed = { vol: P.volume(dh), closed: closed(dh) };
out.edges = { cube: P.edges(cube).length, two: P.edges(cube).every((e) => e.faces.length === 2) };
const _pl = P.primitive("plane", { segments: 1 });
out.boundary = P.edges(_pl).filter((e) => e.faces.length === 1).length;
const _rm = { v: [[0, 0, 0], [1, 0, 0], [1, 0, 1]], f: [[0, 1, 2]] };
const _ring = [0, 1, 2];
out.align = P.alignRing(_rm, _ring, [0, 1, 0]) && _ring.join(",") === "2,1,0";
// edit-mode selection + transform (Blender's editmesh rules)
const c3 = P.primitive("cube", { segments: 3 }), T3 = P.topology(c3);
const vertical = T3.edges.findIndex((e) => { const a = c3.v[e.a], b = c3.v[e.b];
  return Math.abs(a[2] - 0.5) < 1e-6 && Math.abs(b[2] - 0.5) < 1e-6 && Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[0] + 1 / 6) < 1e-3 && Math.abs(a[1] + b[1]) < 1e-6; });
const corner = T3.edges.findIndex((e) => [e.a, e.b].some((i) => c3.v[i].every((x) => Math.abs(Math.abs(x) - 0.5) < 1e-6)));
const usph = P.primitive("sphere", { segments: 16, rings: 8 }), TS = P.topology(usph);
const eq = TS.edges.findIndex((e) => Math.abs(usph.v[e.a][1] - usph.v[e.b][1]) < 1e-9 && Math.abs(usph.v[e.a][1]) < 1e-6);
const pl4 = P.primitive("plane", { segments: 4 }), TP = P.topology(pl4);
const ring = P.edgeRing(c3, T3, vertical);
const cut = P.loopCut(c3, vertical, 0.5);
const cutClosed = (() => { const directed = new Set(); for (const face of cut.f) for (let k = 0; k < face.length; k++) {
  const a = face[k], b = face[(k + 1) % face.length]; if (directed.has(a + ">" + b)) return false; directed.add(a + ">" + b);
} for (const key of directed) { const [a, b] = key.split(">"); if (!directed.has(b + ">" + a)) return false; } return true; })();
const fl = P.flushSelection(c3, T3, { v: c3.f[0], e: [], f: [] }, "vert");
const fe = P.flushSelection(c3, T3, { v: [], e: T3.faceEdges[0], f: [] }, "edge");
const ff = P.flushSelection(c3, T3, { v: [], e: [], f: [0, 1] }, "face");
const gr = P.grow(c3, T3, c3.f[0]);
const wt = P.weights(c3, [0], 0.4, "smooth");
const far = [...wt.keys()].every((i) => Math.hypot(...[0, 1, 2].map((k) => c3.v[i][k] - c3.v[0][k])) <= 0.4 + 1e-9);
const M = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0.5, 0, 1];          // translate +0.5 in y (column-major)
const moved = P.applyMatrix(c3, wt, M);
out.edit = {
  loop: P.edgeLoop(c3, T3, vertical).length, pole: P.edgeLoop(c3, T3, corner).length,
  ringE: ring.edges.length, ringF: ring.faces.length, cutFaces: cut.f.length, cutQuads: cut.f.every((f) => f.length === 4), cutClosed,
  cutVertices: cut.v.length, cutFinite: cut.v.every((p) => p.every(Number.isFinite)), equator: P.edgeLoop(usph, TS, eq).length,
  border: P.edgeLoop(pl4, TP, TP.edges.findIndex((e) => e.faces.length === 1)).length,
  flushV: [fl.f.size, fl.e.size], flushE: [fe.f.size, fe.v.size], flushF: [ff.v.size, ff.e.size],
  grow: gr.size, shrink: P.shrink(c3, T3, gr).size, linked: P.linked(c3, T3, [0]).size, nv: c3.v.length,
  w1: wt.get(0), wn: wt.size, far, falloffEnds: Object.values(P.FALLOFF).every((fn) => Math.abs(fn(1) - 1) < 1e-9 && fn(0) >= 0 && fn(0) < 1e-9 || fn === P.FALLOFF.constant),
  dy0: moved.v[0][1] - c3.v[0][1], partial: [...wt.entries()].filter(([i, x]) => x < 1).every(([i, x]) => Math.abs(moved.v[i][1] - c3.v[i][1] - 0.5 * x) < 1e-9),
  still: c3.v.every((p, i) => wt.has(i) || moved.v[i].every((x, k) => x === p[k])),
  delV: P.deleteVerts(c3, [0]).f.length, delE: P.deleteEdges(c3, T3, [vertical]).f.length, median: P.median(c3, c3.f[0]),
};
const _c2 = P.primitive("cube", { segments: 2 });
const _half = P.deleteFaces(_c2, _c2.f.map((f, i) => (P.centroid(_c2, f)[0] < 0 ? i : -1)).filter((i) => i >= 0));
const _mir = P.mirror(_half, [0, 0, 0], [1, 0, 0]);
const _two = P.combine([_c2, P.transform(_c2, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1])]);
out.tools = { mirV: _mir.v.length, mirF: _mir.f.length, mirVol: P.volume(_mir), mirClosed: closed(_mir), halfF: _half.f.length,
  combF: _two.f.length, combVol: P.volume(_two), shells: P.shells(_two).map((m) => m.f.length), moved: P.transform(_c2, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1]).v[0][0] - _c2.v[0][0] };
console.log(JSON.stringify(out));
"""


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("SKIP: no node")
        return 0
    res = subprocess.run([node, "-e", JS, str(REPO / "app" / "ui" / "forge_poly.js")], capture_output=True, text=True,
                         timeout=50, check=False)
    if res.returncode != 0:
        check("forge_poly.js runs", False, res.stderr)
        return 1
    o = json.loads(res.stdout)
    for k in ("cube", "sphere", "quadsphere", "cylinder", "cone", "torus"):
        check("%s is closed and faces outward" % k, o[k]["closed"] and o[k]["vol"] > 0, o[k])
    check("plane is flat (no volume)", abs(o["plane"]["vol"]) < 1e-9, o["plane"])
    check("unit cube has volume 1", abs(o["cube"]["vol"] - 1) < 1e-6, o["cube"])
    check("extrude grows the cube by half (closed)", o["extrude"]["closed"] and abs(o["extrude"]["vol"] - 1.5) < 1e-6, o["extrude"])
    check("a 4-face selection extrudes as one region (no inner walls)", o["region"]["closed"] and abs(o["region"]["vol"] - 1.25) < 1e-6, o["region"])
    check("inset keeps the volume and adds a ring", o["inset"]["closed"] and abs(o["inset"]["vol"] - 1) < 1e-6 and o["inset"]["faces"] == 10, o["inset"])
    check("Catmull-Clark: closed quads, rounder (smaller) than the cube", o["smooth"]["closed"] and o["smooth"]["quads"]
          and o["smooth"]["faces"] == 24 and 0.3 < o["smooth"]["vol"] < 1, o["smooth"])
    check("triangulate maps every triangle to its face", o["tri"]["ok"])
    check("the edge table: a cube has 12 edges, each shared by 2 faces",
          o["edges"]["cube"] == 12 and o["edges"]["two"], o["edges"])
    check("...and a plane's border edges are used once", o["boundary"] == 4, o["boundary"])
    check("alignRing flips a ring that faces the wrong way", o["align"])
    d = o["dyna"]
    check("DynaMesh: a closed all-quad mesh facing outward", d["quads"] and d["closed"] and d["vol"] > 0, d)
    check("DynaMesh keeps the sphere's size", 0.42 < d["rmin"] and d["rmax"] < 0.56 and abs(d["vol"] - 0.5236) < 0.08, d)
    check("DynaMesh closes a model with a hole in it", o["holed"]["closed"] and o["holed"]["vol"] > 0.7, o["holed"])
    e = o["edit"]
    check("edge loop: a valence-4 walk goes all the way round (12 edges on a 3x3x3 cube)", e["loop"] == 12, e)
    check("edge loop stops at a pole (a cube corner has 3 edges)", e["pole"] < 12, e)
    check("edge loop round a UV sphere's equator: one edge per segment (16)", e["equator"] == 16, e)
    check("edge loop along an open border follows the border (16 on a 4x4 plane)", e["border"] == 16, e)
    check("edge ring + face loop: across 12 quads and back to the start", e["ringE"] == 12 and e["ringF"] == 12, e)
    check("loop cut splits each crossed quad into two closed quads", e["cutFaces"] == 66 and e["cutQuads"] and e["cutClosed"] and e["cutVertices"] > 64, e)
    check("loop cut coordinates stay finite", e["cutFinite"], e)
    check("selection flushes like Blender: a face's 4 vertices select the face and its 4 edges", e["flushV"] == [1, 4], e)
    check("...4 edges select the face and its 4 vertices; 2 faces give their vertices and edges",
          e["flushE"] == [1, 4] and e["flushF"][0] == 6 and e["flushF"][1] == 7, e)
    check("Select More / Less / Linked", e["grow"] > 4 and e["shrink"] == 4 and e["linked"] == e["nv"], e)
    check("proportional weights: the vertex 1, only neighbours inside the radius, Blender's falloffs end at 0 and 1",
          e["w1"] == 1 and e["wn"] > 1 and e["far"] and e["falloffEnds"], e)
    check("applyMatrix moves the selection the whole way, its neighbours by their weight, nothing else",
          abs(e["dy0"] - 0.5) < 1e-9 and e["partial"] and e["still"], e)
    check("delete vertices / edges takes the faces that use them", e["delV"] == 51 and e["delE"] == 52, e)
    t = o["tools"]
    check("Mirror: half a cube mirrored across x = 0 is the whole cube again - closed, welded on the seam, facing out",
          t["halfF"] == 12 and t["mirF"] == 24 and t["mirV"] == 26 and t["mirClosed"] and abs(t["mirVol"] - 1) < 1e-6, t)
    check("Combine puts two cubes in one mesh; Separate (shells) finds the two again; transform moves by the matrix",
          t["combF"] == 48 and abs(t["combVol"] - 2) < 1e-6 and t["shells"] == [24, 24] and abs(t["moved"] - 3) < 1e-9, t)
    print("\n%d passed, %d failed (DynaMesh at 48: %d ms)" % (len(PASS), len(FAIL), d["ms"]))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
