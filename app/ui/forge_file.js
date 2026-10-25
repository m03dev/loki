// Forge's File menu rows (docs/FORGE_MAYA_PARITY.md, File was 2 of 24): New Scene, Open Scene..., Save Scene As...,
// Import... - Maya's names and places.
//   New Scene      every object goes (one undo step brings them back); the working object is a fresh empty one
//   Open Scene...  a .glb / .gltf from disk becomes the scene (New Scene first)
//   Import...      .glb / .gltf / .obj / .stl from disk become NEW objects beside what is there (Maya's Import)
//   Save Scene As  the Export dialog with glTF picked (name, unit scale) - saves into the workspace's models
"use strict";

const ForgeFile = (() => {
  const T = () => (typeof forge !== "undefined" && forge.view && forge.view.tree && forge.view.tree.api) || null;
  const say = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); return t; };

  /** OBJ text -> a poly {v, f} (v / f lines; f takes v, v/vt, v/vt/vn, v//vn and negative indices). */
  function parseObj(text) {
    const v = [], f = [];
    for (const raw of String(text).split(/\r?\n/)) {
      const line = raw.trim();
      if (line.startsWith("v ")) { const p = line.split(/\s+/).slice(1, 4).map(Number); if (p.length === 3 && p.every(Number.isFinite)) v.push(p); }
      else if (line.startsWith("f ")) {
        const ids = line.split(/\s+/).slice(1).map((t) => { const i = parseInt(t.split("/")[0], 10); return i < 0 ? v.length + i : i - 1; });
        if (ids.length >= 3 && ids.every((i) => i >= 0 && i < v.length)) f.push(ids);
      }
    }
    return { v, f };
  }
  /** STL (binary or ASCII) -> triangles {pos, idx}. */
  function parseStl(buf) {
    const u8 = new Uint8Array(buf), head = new TextDecoder().decode(u8.slice(0, 256)).trim().toLowerCase();
    const dv = new DataView(buf), n = buf.byteLength >= 84 ? dv.getUint32(80, true) : 0;
    const pos = [];
    if (n && 84 + n * 50 === buf.byteLength) {
      for (let t = 0; t < n; t++) { const o = 84 + t * 50 + 12; for (let k = 0; k < 9; k++) pos.push(dv.getFloat32(o + k * 4, true)); }
    } else if (head.startsWith("solid")) {
      const re = /vertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g, text = new TextDecoder().decode(u8);
      let m; while ((m = re.exec(text))) pos.push(+m[1], +m[2], +m[3]);
    }
    return { pos: Float32Array.from(pos), idx: Uint32Array.from({ length: pos.length / 3 }, (_, i) => i) };
  }

  function pick(accept) {
    return new Promise((resolve) => {
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = accept; inp.style.display = "none";
      inp.addEventListener("change", () => { resolve(inp.files && inp.files[0] ? inp.files[0] : null); inp.remove(); });
      document.body.append(inp);
      inp.click();
    });
  }

  /** New Scene: every object goes, in one undo step. */
  function newScene() {
    const t = T(), v = typeof forge !== "undefined" && forge.view;
    if (!t || !v) return say("Open Forge first.");
    const run = () => {
      t.newObject();                             // a fresh working object (the old one becomes an ordinary node)
      v.showPoly({ v: [], f: [] }, false, true);  // ... and it is empty (the view kept the old mesh on screen)
      const r = t.root().id;
      for (const n of t.list().slice()) if (n.id !== r && t.node(n.id) && n.parent === 0) t.remove(n.id);
      t.selectNone && t.selectNone();
    };
    if (v.undoChunk) v.undoChunk("new scene", run); else run();
    return say("New scene. Ctrl+Z brings the old one back.");
  }

  /** Bring one file in as NEW object(s). Returns the message. */
  async function importFile(file) {
    const t = T(), v = typeof forge !== "undefined" && forge.view, P = window.ForgePoly;
    if (!t || !v || !file) return say(file ? "Open Forge first." : "Nothing picked.");
    const name = file.name.replace(/\.[^.]+$/, "").replace(/[^\w-]+/g, "_") || "imported";
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    try {
      if (ext === "obj") {
        const m = parseObj(await file.text());
        if (!m.f.length) return say(file.name + ": no faces in it.", true);
        v.undoChunk ? v.undoChunk("import", () => { t.newObject(name); v.showPoly(m, false, true); }) : (t.newObject(name), v.showPoly(m, false, true));
        return say("Imported " + file.name + ": " + m.f.length + " faces.");
      }
      if (ext === "stl") {
        const tri = parseStl(await file.arrayBuffer());
        if (!tri.idx.length) return say(file.name + ": no triangles in it.", true);
        const m = P.fromTriangles(tri.pos, tri.idx);
        v.undoChunk ? v.undoChunk("import", () => { t.newObject(name); v.showPoly(m, false, true); }) : (t.newObject(name), v.showPoly(m, false, true));
        return say("Imported " + file.name + ": " + m.f.length + " faces.");
      }
      if (ext === "glb" || ext === "gltf") {
        t.newObject(name);
        await v.load(await file.arrayBuffer());
        if (t.root().auto) t.rename(t.root().id, name);
        return say("Imported " + file.name + ".");
      }
    } catch (exc) {
      return say("Could not read " + file.name + ": " + ((exc && exc.message) || exc), true);
    }
    return say("Forge imports .glb, .gltf, .obj and .stl.", true);
  }

  async function openScene() {
    const file = await pick(".glb,.gltf");
    if (!file) return "";
    newScene();
    return importFile(file);
  }

  if (typeof FORGE_PRO_CMDS !== "undefined") {
    FORGE_PRO_CMDS.newScene = ["New Scene", () => newScene()];
    FORGE_PRO_CMDS.openScene = ["Open Scene...", async () => openScene()];
    FORGE_PRO_CMDS.importFile = ["Import...", async () => { const f = await pick(".glb,.gltf,.obj,.stl"); return f ? importFile(f) : ""; }];
    FORGE_PRO_CMDS.saveAs = ["Save Scene As...", () => {
      if (typeof forgeExportDialog !== "function") return say("Open Forge first.");
      forgeExportDialog();
      const fmt = document.querySelector("#forge-export-dialog select, .forge-export select");
      if (fmt) { fmt.value = "glb"; fmt.dispatchEvent(new Event("change")); }
      return say("Save Scene As: give it a name and Save (glTF).");
    }];
  }
  return { newScene, importFile, openScene, parseObj, parseStl };
})();
window.ForgeFile = ForgeFile;
