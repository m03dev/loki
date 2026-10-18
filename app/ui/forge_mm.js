// Forge's Material Maker compiler: Material Maker's node graphs (.ptex) and node definitions (.mmg) -> one WebGL2
// fragment shader per PBR map. A port of material_maker/engine/nodes/gen_shader.gd (replace_variables,
// process_parameters, process_inputs, generic "#" expansion, includes, io type conversion) and of
// types/gradient.gd (get_shader) from Material Maker by Rodolphe Suescun and contributors, MIT licence
// (app/ui/vendor/material_maker/LICENSE). The node definitions themselves are Material Maker's own .mmg files,
// bundled unchanged in app/ui/vendor/material_maker/nodes.json by tools/import_mm_nodes.py.
//
// One difference from Material Maker: every node output is compiled to its own GLSL function
// `<type> o<id>_o<port>(vec2 uv)` and an input is a call to its source's function. Material Maker inlines
// outputs and generates functions only for "function" inputs; calling functions everywhere is slower for big
// graphs but makes every input usable at any uv (warp, tiling, normal-from-height) with one simple rule.
//
// Pure JS (no DOM, no three.js): window.ForgeMM = { load, compile, defaults, newGraph, toPtex, fromPtex }.
"use strict";

(function () {
  const IO = {   // material_maker/nodes/io_types.mmt: f, rgb, rgba and their conversions
    f: { type: "float", convert: { rgb: "vec3($(value))", rgba: "vec4(vec3($(value)), 1.0)" } },
    rgb: { type: "vec3", convert: { f: "(dot($(value), vec3(1.0))/3.0)", rgba: "vec4($(value), 1.0)" } },
    rgba: { type: "vec4", convert: { f: "(dot(($(value)).rgb, vec3(1.0))/3.0)", rgb: "(($(value)).rgb)" } },
  };
  const WORD = /[A-Za-z0-9_#]/;
  // The Material node (material_maker/nodes/material.mmg): its inputs, in Material Maker's port order.
  const MATERIAL_INPUTS = [
    ["albedo_tex", "rgb", "$albedo_color.rgb", "Albedo"], ["metallic_tex", "f", "$metallic", "Metallic"],
    ["roughness_tex", "f", "$roughness", "Roughness"], ["emission_tex", "rgb", "vec3(0.0)", "Emission"],
    ["normal_tex", "rgb", "vec3(0.5, 0.5, 1.0)", "Normal"], ["ao_tex", "f", "1.0", "Ambient occlusion"],
    ["depth_tex", "f", "0.0", "Height"], ["opacity_tex", "f", "1.0", "Opacity"],
  ];
  const MATERIAL_PARAMS = [
    { name: "albedo_color", type: "color", default: { r: 1, g: 1, b: 1, a: 1 }, shortdesc: "Albedo" },
    { name: "metallic", type: "float", default: 0, min: 0, max: 1, step: 0.01, shortdesc: "Metallic" },
    { name: "roughness", type: "float", default: 0.8, min: 0, max: 1, step: 0.01, shortdesc: "Roughness" },
    { name: "normal", type: "float", default: 1, min: 0, max: 10, step: 0.1, shortdesc: "Normal strength" },
    { name: "ao", type: "float", default: 1, min: 0, max: 1, step: 0.01, shortdesc: "Ambient occlusion" },
    { name: "depth_scale", type: "float", default: 0.5, min: 0, max: 1, step: 0.01, shortdesc: "Height scale" },
  ];
  // the maps Forge renders from the Material node: name -> GLSL that yields vec4 (uses the mm_* functions below)
  const MAPS = {
    albedo: "vec4(mm_albedo(uv), 1.0)",
    roughness: "vec4(vec3(mm_roughness(uv)), 1.0)",
    metallic: "vec4(vec3(mm_metallic(uv)), 1.0)",
    normal: "vec4(mm_normal(uv), 1.0)",
    ao: "vec4(vec3(mm_ao(uv)), 1.0)",
    height: "vec4(vec3(mm_height(uv)), 1.0)",
  };

  let LIB = { nodes: {}, functions: "" };

  function load(json) {
    LIB = { nodes: json.nodes || {}, functions: json._shader_functions || "", meta: json._meta || {} };
    return LIB;
  }

  function matching(s, i, op = "(", cp = ")") {   // gen_base.gd find_matching_parenthesis
    let level = 0;
    for (; i < s.length; i++) {
      if (s[i] === op) level++;
      else if (s[i] === cp) { level--; if (level === 0) return i; }
    }
    return s.length;
  }

  function splitParams(s) {   // top-level comma split
    const out = []; let level = 0, cur = "";
    for (const c of s) {
      if (c === "(") level++;
      if (c === ")") level--;
      if (c === "," && level === 0) { out.push(cur.trim()); cur = ""; } else cur += c;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  const asText = (x) => (Array.isArray(x) ? x.join("\n") : String(x || ""));
  const fmt = (v) => { const n = Number(v); return Number.isFinite(n) ? (Number.isInteger(n) ? n.toFixed(1) : String(n)) : "0.0"; };
  const vec4 = (c) => "vec4(" + [c.r, c.g, c.b, c.a === undefined ? 1 : c.a].map(fmt).join(", ") + ")";

  // gen_shader.gd expand_generic(): inputs/parameters/outputs whose name has "#" repeat generic_size times
  function expandGeneric(model, size) {
    const m = JSON.parse(JSON.stringify(model));
    const generic = (list, field) => (list || []).some((x) => String(x[field] || "").includes("#"));
    if (!generic(m.inputs, "name") && !generic(m.parameters, "name")) return m;
    const grow = (list, field) => {
      const out = [];
      const first = list.findIndex((x) => String(x[field]).includes("#"));
      if (first < 0) return list;
      let last = first;
      while (last < list.length && String(list[last][field]).includes("#")) last++;
      out.push(...list.slice(0, first));
      for (let g = 1; g <= size; g++) for (const x of list.slice(first, last)) {
        const y = JSON.parse(JSON.stringify(x));
        for (const k of ["name", "label", "shortdesc", "longdesc"]) if (typeof y[k] === "string") y[k] = y[k].split("#").join(String(g));
        out.push(y);
      }
      out.push(...list.slice(last));
      return out;
    };
    m.inputs = grow(m.inputs || [], "name");
    m.parameters = grow(m.parameters || [], "name");
    const code = (s) => {   // #for ... #end blocks, and # -> 1 elsewhere in outputs
      s = asText(s).split("#count").join(String(size));
      let out = "";
      for (;;) {
        const f = s.indexOf("#for");
        if (f < 0) { out += s; break; }
        out += s.slice(0, f); s = s.slice(f + 4);
        const e = s.indexOf("#end");
        const body = e < 0 ? s : s.slice(0, e);
        s = e < 0 ? "" : s.slice(e + 4);
        for (let g = 1; g <= size; g++) out += body.split("#").join(String(g));
      }
      return out;
    };
    m.code = code(m.code);
    m.instance = code(m.instance);
    m.outputs = (m.outputs || []).map((o) => {
      const y = { ...o };
      for (const t of ["f", "rgb", "rgba"]) if (y[t]) y[t] = code(y[t]).split("#").join("1");
      return y;
    });
    return m;
  }

  // types/gradient.gd get_shader(): a gradient parameter -> a GLSL function of x
  function gradientFn(name, g) {
    const pts = ((g && g.points) || []).slice().sort((a, b) => a.pos - b.pos);
    const col = (p) => vec4(p);
    let s = "vec4 " + name + "_gradient_fct(float x) {\n";
    if (!pts.length) return s + "  return vec4(0.0, 0.0, 0.0, 1.0);\n}\n";
    const interp = g.interpolation === undefined ? 1 : g.interpolation;
    if (interp === 0) {
      for (let i = 1; i < pts.length; i++) s += "  if (x < " + fmt(pts[i].pos) + ") return " + col(pts[i - 1]) + ";\n";
      return s + "  return " + col(pts[pts.length - 1]) + ";\n}\n";
    }
    s += "  if (x < " + fmt(pts[0].pos) + ") return " + col(pts[0]) + ";\n";
    for (let i = 0; i < pts.length - 1; i++) {
      const t = "(x-" + fmt(pts[i].pos) + ")/(" + fmt(pts[i + 1].pos) + "-" + fmt(pts[i].pos) + "+0.000001)";
      const f = interp === 2 ? "0.5-0.5*cos(3.14159265359*" + t + ")" : t;
      s += "  if (x < " + fmt(pts[i + 1].pos) + ") return mix(" + col(pts[i]) + ", " + col(pts[i + 1]) + ", " + f + ");\n";
    }
    return s + "  return " + col(pts[pts.length - 1]) + ";\n}\n";
  }

  function defaults(type) {
    if (type === "material") {
      const p = {};
      for (const d of MATERIAL_PARAMS) p[d.name] = d.default;
      return p;
    }
    const def = LIB.nodes[type];
    const out = {};
    if (!def) return out;
    const model = expandGeneric(def.shader_model, def.generic_size || 1);
    for (const p of model.parameters || []) out[p.name] = p.default !== undefined ? JSON.parse(JSON.stringify(p.default)) : 0;
    return out;
  }

  function modelOf(node) {
    if (node.type === "material") {
      return { inputs: MATERIAL_INPUTS.map(([name, type, def, label]) => ({ name, type, default: def, shortdesc: label })),
        outputs: [], parameters: MATERIAL_PARAMS, global: "", instance: "", code: "" };
    }
    const def = LIB.nodes[node.type];
    if (!def) return null;
    const size = Number(node.generic_size || def.generic_size || 1);
    return expandGeneric(node.shader_model || def.shader_model, Math.max(1, size));
  }

  // ------------------------------------------------------------------------------------------ compile
  // graph = { nodes: [{name, type, parameters, seed_int?, generic_size?}], connections: [{from, from_port, to, to_port}] }
  // -> { maps: {albedo: fragSource, ...}, uniforms: {name: {kind, value, node, param}}, errors: [] }
  function compile(graph) {
    const nodes = new Map(graph.nodes.map((n) => [n.name, n]));
    const ids = new Map();
    graph.nodes.forEach((n, i) => ids.set(n.name, "o" + i));
    const conn = new Map();   // "to:port" -> {from, port}
    for (const c of graph.connections || []) if (nodes.has(c.from) && nodes.has(c.to)) conn.set(c.to + ":" + c.to_port, { from: c.from, port: c.from_port });
    const globals = [], globalSeen = new Set(), defs = [], made = new Set(), uniforms = {}, errors = [];
    const addGlobal = (g) => { g = asText(g).trim(); if (g && !globalSeen.has(g)) { globalSeen.add(g); globals.push(g); } };
    const visiting = new Set();

    // build (once) the GLSL function for one output of one node; returns {fn, type}
    function outputFn(name, port) {
      const node = nodes.get(name), id = ids.get(name), model = modelOf(node);
      if (!model) { errors.push(name + ": unknown node type " + node.type); return null; }
      const out = (model.outputs || [])[port];
      if (!out) { errors.push(name + ": no output " + port); return null; }
      const type = out.type || ["rgba", "rgb", "f"].find((t) => out[t]);
      const fn = id + "_o" + port;
      if (made.has(fn)) return { fn, type };
      if (visiting.has(fn)) { errors.push(name + ": the graph has a loop"); return null; }
      visiting.add(fn);
      const vars = variables(node, model, id);
      if (!made.has(id + "#decl")) {   // per node, once: includes, global, instance
        made.add(id + "#decl");
        for (const inc of model.includes || []) { const d = LIB.nodes[inc]; if (d) addGlobal(d.shader_model.global); }
        addGlobal(model.global);
        const inst = replace(asText(model.instance), vars).trim();
        if (inst) defs.push(inst);
      }
      vars.uv = "uv";
      vars.name_uv = id + "_" + port;
      const code = replace(asText(model.code), vars);
      const expr = replace(String(out[type]).replace("@NOCODE", "").replace("@KEEPTYPE", "").trim(), vars);
      defs.push(IO[type].type + " " + fn + "(vec2 uv) {\n" + code + "\nreturn " + expr + ";\n}");
      made.add(fn);
      visiting.delete(fn);
      return { fn, type };
    }

    // the replacement table of one node (gen_shader.gd get_common_replace_variables + process_parameters/inputs)
    function variables(node, model, id) {
      const v = { name: id, node_id: id, time: "0.0", "?1": "0.0", "?2": "0.0", "?3": "0.0", "?4": "0.0" };
      const seedU = "seed_" + id;
      uniforms[seedU] = { kind: "float", value: (Number(node.seed_int || 0) % 1000) / 1000 + 0.123, node: node.name, param: "seed" };
      v.seed = seedU;
      const params = node.parameters || {};
      for (const p of model.parameters || []) {
        const val = params[p.name] !== undefined ? params[p.name] : p.default;
        const u = "p_" + id + "_" + p.name.replace(/[^A-Za-z0-9_]/g, "_");
        if (p.type === "float") {
          if (typeof val === "string") v[p.name] = "(" + val.replace(/\$rnd\([^)]*\)/g, "0.5") + ")";
          else { uniforms[u] = { kind: "float", value: Number(val) || 0, node: node.name, param: p.name }; v[p.name] = u; }
        } else if (p.type === "color") {
          uniforms[u] = { kind: "vec4", value: val || { r: 1, g: 1, b: 1, a: 1 }, node: node.name, param: p.name };
          v[p.name] = u;
        } else if (p.type === "enum") {
          const i = Number(val) >= 0 && Number(val) < (p.values || []).length ? Number(val) : 0;
          v[p.name] = (p.values && p.values.length) ? p.values[i].value : "";
        } else if (p.type === "boolean") v[p.name] = val ? "true" : "false";
        else if (p.type === "size") v[p.name] = fmt(Math.pow(2, Number(val) || 0));
        else if (p.type === "gradient") {
          const fname = id + "_" + p.name;
          defs.push(gradientFn(fname, val));
          v[p.name] = fname + "_gradient_fct";
        } else errors.push(node.name + ": parameter type " + p.type + " is not supported in Forge");
      }
      (model.inputs || []).forEach((input, index) => { v[input.name] = { input, index }; });
      v.__node = node; v.__vars = v;
      return v;
    }

    function inputCall(node, vars, input, index, args) {
      const src = conn.get(node.name + ":" + index);
      const uvArg = args === "" ? vars.uv : args;
      if (!src) {   // unconnected: the input's default expression with $uv = the call's argument
        const saved = vars.uv; vars.uv = "(" + uvArg + ")";
        const r = "(" + replace(String(input.default === undefined ? "0.0" : input.default), vars) + ")";
        vars.uv = saved;
        return r;
      }
      const o = outputFn(src.from, src.port);
      if (!o) return IO[input.type].type + "(0.0)";
      let call = o.fn + "(" + uvArg + ")";
      if (o.type !== input.type) call = "(" + IO[o.type].convert[input.type].replace("$(value)", call) + ")";
      return call;
    }

    // gen_shader.gd replace_variables(), right to left; an input followed by (args) or .variation(args) is a call
    function replace(string, vars) {
      let end = "";
      for (;;) {
        const d = string.lastIndexOf("$");
        if (d < 0) break;
        let vEnd, name;
        if (string[d + 1] === "(") { vEnd = matching(string, d + 1) + 1; name = string.slice(d + 2, vEnd - 1); }
        else { vEnd = d + 1; while (vEnd < string.length && WORD.test(string[vEnd])) vEnd++; name = string.slice(d + 1, vEnd); }
        end = string.slice(vEnd) + end;
        string = string.slice(0, d);
        const r = vars[name];
        if (r === undefined) { string += name === "uv" ? vars.uv : "(0.0/*" + name + "?*/)"; continue; }
        if (typeof r === "string") { string += r; continue; }
        let rest = end.replace(/^\s+/, ""), args = "";
        if (rest[0] === ".") {   // .variation(...) / .texture: Forge has no per-instance variations
          const m = /^\.\s*([A-Za-z_]+)\s*/.exec(rest);
          rest = rest.slice(m ? m[0].length : 1);
        }
        if (rest[0] === "(") {
          const close = matching(rest, 0);
          args = rest.slice(1, close);
          rest = rest.slice(close + 1);
          const parts = splitParams(args);
          if (parts.length > 1) args = parts[0];   // .variation(uv, seed) -> uv
        }
        end = rest;
        string += inputCall(vars.__node, vars, r.input, r.index, args.trim());
      }
      return string + end;
    }

    // the Material node -> mm_* functions, then one fragment shader per map
    const mat = graph.nodes.find((n) => n.type === "material");
    if (!mat) errors.push("no Material node");
    const mvars = mat ? variables(mat, modelOf(mat), ids.get(mat.name)) : {};
    const mfn = (iname, type, glslType) => {
      const idx = MATERIAL_INPUTS.findIndex((x) => x[0] === iname);
      mvars.uv = "uv";
      const body = mat ? replace("$" + iname + "(uv)", mvars) : "0.0";
      return glslType + " mm_" + iname.replace("_tex", "") + "_raw(vec2 uv) { return " + body + "; }";
    };
    const mm = [
      mfn("albedo_tex", "rgb", "vec3"), mfn("metallic_tex", "f", "float"), mfn("roughness_tex", "f", "float"),
      mfn("ao_tex", "f", "float"), mfn("depth_tex", "f", "float"), mfn("normal_tex", "rgb", "vec3"),
    ];
    const mid = mat ? ids.get(mat.name) : "o0";
    const has = (port) => mat && conn.has(mat.name + ":" + port);
    mm.push(
      "vec3 mm_albedo(vec2 uv) { return clamp(mm_albedo_raw(uv), 0.0, 1.0); }",
      "float mm_metallic(vec2 uv) { return clamp(mm_metallic_raw(uv), 0.0, 1.0); }",
      "float mm_roughness(vec2 uv) { return clamp(mm_roughness_raw(uv), 0.0, 1.0); }",
      "float mm_height(vec2 uv) { return clamp(mm_depth_raw(uv), 0.0, 1.0); }",
      // normal from the height map (Material Maker's normal_map node does this with a buffer + edge detect;
      // here: central differences of the height function, OpenGL convention like glTF)
      "vec3 mm_normal(vec2 uv) {\n" + (has(4) ? "  return clamp(mm_normal_raw(uv), 0.0, 1.0);\n" :
        "  float e = 1.0 / mm_size;\n  float s = p_" + mid + "_normal * " + fmt(1) + " * 8.0;\n" +
        "  float dx = mm_height(uv + vec2(e, 0.0)) - mm_height(uv - vec2(e, 0.0));\n" +
        "  float dy = mm_height(uv + vec2(0.0, e)) - mm_height(uv - vec2(0.0, e));\n" +
        "  return normalize(vec3(-dx * s, -dy * s, 1.0)) * 0.5 + 0.5;\n") + "}",
      // ambient occlusion: the input when connected, else a small cavity estimate from the height
      "float mm_ao(vec2 uv) {\n" + (has(5) ? "  return clamp(mm_ao_raw(uv), 0.0, 1.0);\n" :
        "  float h = mm_height(uv), occ = 0.0;\n  for (int i = 0; i < 8; i++) {\n" +
        "    float a = float(i) * 0.785398; vec2 o = vec2(cos(a), sin(a)) * 6.0 / mm_size;\n" +
        "    occ += max(0.0, mm_height(uv + o) - h);\n  }\n" +
        "  return clamp(1.0 - occ * 1.5 * p_" + mid + "_ao, 0.0, 1.0);\n") + "}");
    const head = () => "#version 300 es\nprecision highp float;\nprecision highp int;\nuniform float mm_size;\nin vec2 vUv;\nout vec4 mm_frag;\n" +
      Object.entries(uniforms).map(([n, u]) => "uniform " + u.kind + " " + n + ";").join("\n") + "\n" +
      // Godot shading-language helpers some nodes use, and Material Maker's shader_functions
      "vec3 rgb_to_hsv(vec3 c) { vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0); vec4 p = c.g < c.b ? vec4(c.bg, K.wz) : vec4(c.gb, K.xy);" +
      " vec4 q = c.r < p.x ? vec4(p.xyw, c.r) : vec4(c.r, p.yzx); float d = q.x - min(q.w, q.y); float e = 1.0e-10;" +
      " return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x); }\n" +
      "vec3 hsv_to_rgb(vec3 c) { vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0); vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);" +
      " return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y); }\n" + LIB.functions + "\n";
    const body = globals.join("\n\n") + "\n\n" + defs.join("\n\n") + "\n\n" + mm.join("\n");
    const maps = {};
    for (const [k, expr] of Object.entries(MAPS)) maps[k] = head() + body + "\nvoid main() { vec2 uv = vec2(vUv.x, 1.0 - vUv.y); mm_frag = " + expr + "; }\n";
    // a preview shader per node output (the thumbnails in the editor)
    const preview = (name, port) => {
      const o = outputFn(name, port);
      if (!o) return "";
      const e = o.type === "f" ? "vec4(vec3(" + o.fn + "(uv)), 1.0)" : o.type === "rgb" ? "vec4(" + o.fn + "(uv), 1.0)" : o.fn + "(uv)";
      return head() + globals.join("\n\n") + "\n\n" + defs.join("\n\n") + "\nvoid main() { vec2 uv = vec2(vUv.x, 1.0 - vUv.y); mm_frag = " + e + "; }\n";
    };
    return { maps, uniforms, errors, preview };
  }

  // ------------------------------------------------------------------------------------------ graphs and .ptex
  function newGraph() {
    const g = { nodes: [
      { name: "Material", type: "material", parameters: defaults("material"), node_position: { x: 520, y: 40 } },
    ], connections: [] };
    if (LIB.nodes.perlin && LIB.nodes.colorize) {
      g.nodes.push({ name: "perlin_1", type: "perlin", parameters: { ...defaults("perlin"), scale_x: 6, scale_y: 6, iterations: 5 },
        node_position: { x: 20, y: 40 }, seed_int: 1234 });
      g.nodes.push({ name: "colorize_1", type: "colorize", parameters: { gradient: { interpolation: 1, type: "Gradient", points: [
        { pos: 0, r: 0.35, g: 0.18, b: 0.1, a: 1 }, { pos: 1, r: 0.93, g: 0.47, b: 0.17, a: 1 }] } }, node_position: { x: 260, y: 20 } });
      g.connections.push({ from: "perlin_1", from_port: 0, to: "colorize_1", to_port: 0 },
        { from: "colorize_1", from_port: 0, to: "Material", to_port: 0 },
        { from: "perlin_1", from_port: 0, to: "Material", to_port: 6 });
    }
    return g;
  }

  function toPtex(graph) {   // Material Maker's project format (a "graph" generator)
    return { name: "material", label: "Forge material", type: "graph", parameters: {}, node_position: { x: 0, y: 0 },
      nodes: graph.nodes.map((n) => ({ name: n.name, type: n.type, parameters: n.parameters, node_position: n.node_position || { x: 0, y: 0 },
        seed_int: n.seed_int || 0, ...(n.generic_size ? { generic_size: n.generic_size } : {}) })),
      connections: graph.connections.map((c) => ({ ...c })) };
  }

  function fromPtex(data) {   // keeps what Forge can run; reports the rest
    const skipped = [];
    const nodes = [];
    for (const n of data.nodes || []) {
      const t = n.type === "material" || n.type === "material_export" ? "material" : n.type;
      if (t !== "material" && !LIB.nodes[t] && !(n.type === "shader" && n.shader_model)) { skipped.push(n.name + " (" + n.type + ")"); continue; }
      const node = { name: n.name, type: t, parameters: { ...defaults(t), ...(n.parameters || {}) },
        node_position: n.node_position || { x: 0, y: 0 }, seed_int: n.seed_int || n.seed || 0 };
      if (n.generic_size) node.generic_size = n.generic_size;
      if (n.type === "shader" && n.shader_model) {   // a custom node inside the project: its own definition
        LIB.nodes["custom:" + n.name] = { type: "shader", shader_model: n.shader_model, category: "Project" };
        node.type = "custom:" + n.name;
      }
      nodes.push(node);
    }
    if (!nodes.some((n) => n.type === "material")) nodes.push({ name: "Material", type: "material", parameters: defaults("material"), node_position: { x: 600, y: 0 } });
    const names = new Set(nodes.map((n) => n.name));
    const connections = (data.connections || []).filter((c) => names.has(c.from) && names.has(c.to));
    return { graph: { nodes, connections }, skipped };
  }

  window.ForgeMM = { load, compile, defaults, newGraph, toPtex, fromPtex, modelOf, MATERIAL_INPUTS, MAPS, lib: () => LIB };
})();
