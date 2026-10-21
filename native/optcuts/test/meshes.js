/* Test meshes for test_optcuts.js (LOKI, AGPL-3.0): consistently oriented (outward), manifold triangle meshes. */
"use strict";

function icosphere(levels) {
  const t = (1 + Math.sqrt(5)) / 2;
  let v = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]];
  let f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
           [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
  const norm = (p) => { const l = Math.hypot(p[0], p[1], p[2]); return [p[0] / l, p[1] / l, p[2] / l]; };
  v = v.map(norm);
  for (let s = 0; s < levels; s++) {
    const mid = new Map(), nf = [];
    const m = (a, b) => {
      const k = a < b ? a + "," + b : b + "," + a;
      if (!mid.has(k)) { v.push(norm([(v[a][0] + v[b][0]) / 2, (v[a][1] + v[b][1]) / 2, (v[a][2] + v[b][2]) / 2])); mid.set(k, v.length - 1); }
      return mid.get(k);
    };
    for (const [a, b, c] of f) { const ab = m(a, b), bc = m(b, c), ca = m(c, a); nf.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]); }
    f = nf;
  }
  return { pos: Float32Array.from(v.flat()), tris: Int32Array.from(f.flat()) };
}

// open cylinder (a tube with two boundary loops): genus 0, two holes -> OptCuts' cut_to_disk path
function cylinder(seg, rings, radius = 1, height = 3) {
  const p = [], f = [];
  for (let j = 0; j <= rings; j++) for (let i = 0; i < seg; i++) {
    const a = (i / seg) * Math.PI * 2; p.push(radius * Math.cos(a), (j / rings) * height, radius * Math.sin(a));
  }
  for (let j = 0; j < rings; j++) for (let i = 0; i < seg; i++) {
    const a = j * seg + i, b = j * seg + (i + 1) % seg, c = a + seg, d = b + seg;
    f.push(a, c, b, b, c, d);
  }
  return { pos: Float32Array.from(p), tris: Int32Array.from(f) };
}

// torus: genus 1
function torus(seg, sides, R = 2, r = 0.7) {
  const p = [], f = [];
  for (let i = 0; i < seg; i++) for (let j = 0; j < sides; j++) {
    const u = (i / seg) * Math.PI * 2, w = (j / sides) * Math.PI * 2;
    p.push((R + r * Math.cos(w)) * Math.cos(u), r * Math.sin(w), (R + r * Math.cos(w)) * Math.sin(u));
  }
  const id = (i, j) => (i % seg) * sides + (j % sides);
  for (let i = 0; i < seg; i++) for (let j = 0; j < sides; j++) {
    const a = id(i, j), b = id(i + 1, j), c = id(i, j + 1), d = id(i + 1, j + 1);
    f.push(a, c, b, b, c, d);
  }
  return { pos: Float32Array.from(p), tris: Int32Array.from(f) };
}

// latitude-longitude sphere (closed, genus 0): 2 * seg * (rings - 1) triangles
function uvSphere(seg, rings, radius = 1) {
  const p = [0, radius, 0], f = [];
  for (let j = 1; j < rings; j++) for (let i = 0; i < seg; i++) {
    const th = (j / rings) * Math.PI, ph = (i / seg) * Math.PI * 2;
    p.push(radius * Math.sin(th) * Math.cos(ph), radius * Math.cos(th), radius * Math.sin(th) * Math.sin(ph));
  }
  p.push(0, -radius, 0);
  const S = p.length / 3 - 1, id = (j, i) => 1 + (j - 1) * seg + (i % seg);
  for (let i = 0; i < seg; i++) f.push(0, id(1, i + 1), id(1, i));
  for (let j = 1; j < rings - 1; j++) for (let i = 0; i < seg; i++) {
    const a = id(j, i), b = id(j, i + 1), c = id(j + 1, i), d = id(j + 1, i + 1);
    f.push(a, b, c, b, d, c);
  }
  for (let i = 0; i < seg; i++) f.push(S, id(rings - 1, i), id(rings - 1, i + 1));
  return { pos: Float32Array.from(p), tris: Int32Array.from(f) };
}

module.exports = { icosphere, cylinder, torus, uvSphere };
