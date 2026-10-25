// Mesh > Booleans - Union, Difference, Difference (B - A), Intersection, as Maya's Mesh > Booleans menu has them
// (owner 2026-10-25: "isn't there an open source solution ... just copy what works"). The CSG itself is
// three-bvh-csg (MIT, gkjohnson - vendored in app/ui/vendor/three-bvh-csg by tools/vendor_csg.py), built on the
// three-mesh-bvh Forge already uses; LOKI only converts its polygon mesh in and out:
//   pick two or more meshes (the FIRST picked is the one the others are cut from, like Maya), run the command, and
//   they become one new object (polySurface1) in world space, the pivot at its middle; one undo step brings them back.
// The result is triangles from the CSG; coplanar pairs are joined back into quads (quadrangulate, 1 degree), so a
// box minus a box is still made of quads where it can be. docs/FORGE_BOOLEANS.md. Upgrade path: Manifold (WASM).
"use strict";

const ForgeBoolean = (() => {
  let lib = null;
  const load = async () => (lib = lib || await import("/ui/vendor/three-bvh-csg/index.js"));
  const OPS = { union: ["ADDITION", "Union"], difference: ["SUBTRACTION", "Difference"],
    differenceBA: ["REVERSE_SUBTRACTION", "Difference (B - A)"], intersection: ["INTERSECTION", "Intersection"] };

  /** A Forge polygon mesh {v, f} -> an indexed triangle BufferGeometry (faces fan-triangulated). */
  function toGeometry(THREE, m) {
    const pos = new Float32Array(m.v.length * 3);
    m.v.forEach((p, i) => pos.set(p, i * 3));
    const idx = [];
    for (const f of m.f) for (let k = 1; k + 1 < f.length; k++) idx.push(f[0], f[k], f[k + 1]);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
  }
  /** The CSG's (non-indexed) triangles -> a welded Forge mesh, coplanar triangle pairs joined into quads. */
  function fromGeometry(g) {
    const P = window.ForgePoly;
    const pos = g.attributes.position.array;
    const idx = g.index ? Array.from(g.index.array) : Array.from({ length: pos.length / 3 }, (_, i) => i);
    let m = P.fromTriangles(pos, idx);
    if (P.quadrangulate) {
      const q = P.quadrangulate(m, m.f.map((_, i) => i), { angle: 1, keepHardEdges: false });
      if (q && q.m && q.m.f && q.m.f.length) m = q.m;
    }
    return m;
  }

  /** Run one boolean on the picked meshes; returns a message for the status line. */
  async function run(op) {
    const v = typeof forge !== "undefined" && forge.view, t = v && v.tree && v.tree.api;
    const spec = OPS[op];
    if (!spec || !t || !t.worldPolys) return "Open Forge first.";
    const parts = t.worldPolys();
    if (parts.length < 2) return "Booleans: pick two or more meshes (the first one picked is the one the others act on).";
    const L = await load();
    const THREE = v.THREE;
    const ev = new L.Evaluator();
    ev.attributes = ["position", "normal"];
    ev.useGroups = false;
    let acc = new L.Brush(toGeometry(THREE, parts[0].poly));
    acc.updateMatrixWorld();
    for (const p of parts.slice(1)) {
      const b = new L.Brush(toGeometry(THREE, p.poly));
      b.updateMatrixWorld();
      acc = ev.evaluate(acc, b, L[spec[0]]);
    }
    const out = fromGeometry(acc.geometry);
    if (!out.f.length) return spec[1] + ": nothing is left (the meshes do not overlap that way).";
    const n = t.replaceWith(parts.map((p) => p.id), out, "polySurface");
    if (!n) return spec[1] + " did not work.";
    v.dirty = true;
    return spec[1] + ": " + parts.map((p) => p.name).join(", ") + " -> " + n.name + " (" + out.f.length + " faces).";
  }

  if (typeof FORGE_PRO_CMDS !== "undefined") {
    FORGE_PRO_CMDS.boolUnion = ["Union", () => run("union")];
    FORGE_PRO_CMDS.boolDifference = ["Difference", () => run("difference")];
    FORGE_PRO_CMDS.boolDifferenceBA = ["Difference (B - A)", () => run("differenceBA")];
    FORGE_PRO_CMDS.boolIntersection = ["Intersection", () => run("intersection")];
  }
  return { run, toGeometry, fromGeometry, OPS };
})();
window.ForgeBoolean = ForgeBoolean;
