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
    differenceBA: ["REVERSE_SUBTRACTION", "Difference (B - A)"], intersection: ["INTERSECTION", "Intersection"],
    // Maya's open booleans: only the FIRST mesh's surface is kept, cut where the others cross it - nothing of theirs
    holePunch: ["HOLLOW_SUBTRACTION", "Hole Punch"],      // the first mesh minus the others, the hole left open
    cutOut: ["HOLLOW_INTERSECTION", "Cut Out"],           // only the part of the first mesh inside the others
    slice: ["SLICE", "Slice"],                            // both parts, as separate pieces of one object
    splitEdges: ["SPLIT", "Split Edges"] };               // the same surface, with new edges where the others cross it

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
    const brush = (poly) => { const b = new L.Brush(toGeometry(THREE, poly)); b.updateMatrixWorld(); return b; };
    let out;
    if (spec[0] === "SLICE" || spec[0] === "SPLIT" || spec[0].startsWith("HOLLOW")) {
      // the cutters first become one (their union), then they cut the first mesh's surface
      let cut = brush(parts[1].poly);
      for (const p of parts.slice(2)) cut = ev.evaluate(cut, brush(p.poly), L.ADDITION);
      const a = brush(parts[0].poly);
      const piece = (k) => fromGeometry(ev.evaluate(a, cut, L[k]).geometry);
      if (spec[0].startsWith("HOLLOW")) out = piece(spec[0]);
      else {
        const outside = piece("HOLLOW_SUBTRACTION"), inside = piece("HOLLOW_INTERSECTION"), P = window.ForgePoly;
        if (!inside.f.length) return spec[1] + ": the others do not cross " + parts[0].name + ".";
        if (spec[0] === "SLICE") out = P.combine([outside, inside]);      // two pieces, not welded: pull them apart
        else {                                                           // one surface again, welded along the cut
          const both = P.combine([outside, inside]), pos = [], idx = [];
          both.v.forEach((q) => pos.push(q[0], q[1], q[2]));
          for (const f of both.f) for (let k = 1; k + 1 < f.length; k++) idx.push(f[0], f[k], f[k + 1]);
          out = P.fromTriangles(Float32Array.from(pos), idx);
          if (P.fixTJunctions) out = P.fixTJunctions(P.weld(out, 1e-6), 1e-6);   // the two sides' seams meet: one closed surface
          if (P.quadrangulate) { const q = P.quadrangulate(out, out.f.map((_, i) => i), { angle: 1, keepHardEdges: false }); if (q && q.m && q.m.f.length) out = q.m; }
        }
      }
    } else {
      let acc = brush(parts[0].poly);
      for (const p of parts.slice(1)) acc = ev.evaluate(acc, brush(p.poly), L[spec[0]]);
      out = fromGeometry(acc.geometry);
    }
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
    FORGE_PRO_CMDS.boolSlice = ["Slice", () => run("slice")];
    FORGE_PRO_CMDS.boolHolePunch = ["Hole Punch", () => run("holePunch")];
    FORGE_PRO_CMDS.boolCutOut = ["Cut Out", () => run("cutOut")];
    FORGE_PRO_CMDS.boolSplitEdges = ["Split Edges", () => run("splitEdges")];
  }
  return { run, toGeometry, fromGeometry, OPS };
})();
window.ForgeBoolean = ForgeBoolean;
