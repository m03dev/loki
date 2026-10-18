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
    d = o["dyna"]
    check("DynaMesh: a closed all-quad mesh facing outward", d["quads"] and d["closed"] and d["vol"] > 0, d)
    check("DynaMesh keeps the sphere's size", 0.42 < d["rmin"] and d["rmax"] < 0.56 and abs(d["vol"] - 0.5236) < 0.08, d)
    check("DynaMesh closes a model with a hole in it", o["holed"]["closed"] and o["holed"]["vol"] > 0.7, o["holed"])
    print("\n%d passed, %d failed (DynaMesh at 48: %d ms)" % (len(PASS), len(FAIL), d["ms"]))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
