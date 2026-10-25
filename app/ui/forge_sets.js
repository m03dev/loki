// Create > Sets > Quick Select Set (Maya: CreateQuickSelectSet) and the Sets window (Maya: Windows > Relationship
// Editors > Sets): a saved selection - objects in object mode, one mesh's vertices / edges / faces in component mode.
// The sets live in the scene (forge_scene.js tree.sets), so undo and a scene snapshot carry them.
//   Select   picks the set again (the right object and component mode first); Shift+Select adds it to what is picked
//   +  / -   adds the current selection to the set / takes it out
//   x        deletes the set (the objects and components stay)
"use strict";

const ForgeSets = (() => {
  const V = () => (typeof forge !== "undefined" && forge.view) || null;
  const T = () => { const v = V(); return (v && v.tree && v.tree.api) || null; };
  const say = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); return t; };
  const comp = (v) => (typeof forgeProComp === "function" ? forgeProComp(v) : v && v.mode === "poly");
  const KIND = { vert: "vertices", edge: "edges", face: "faces", objects: "objects" };

  /** What is picked now, as a set's { kind, node, items, nv } - or null when nothing is. */
  function current() {
    const v = V(), t = T();
    if (!v || !t) return null;
    if (comp(v) && v.edit && v.poly) {
      const mode = v.edit.mode, s = v.edit.sel;
      const items = mode === "edge" ? (v.edgePairs ? v.edgePairs() : []) : mode === "face" ? [...s.f] : [...s.v];
      return items.length ? { kind: mode, node: t.root().id, items, nv: v.poly.v.length } : null;
    }
    const ids = t.selected().filter((id) => t.node(id));
    return ids.length ? { kind: "objects", node: 0, items: ids, nv: 0 } : null;
  }
  const keyOf = (kind, x) => (kind === "edge" ? Math.min(x[0], x[1]) + "_" + Math.max(x[0], x[1]) : String(x));

  /** Create > Sets > Quick Select Set: the current selection, saved under a name (set1, set2 ... when none). */
  function create(name) {
    const v = V(), t = T(), cur = current();
    if (!t) return say("Open Forge first.");
    if (!cur) return say("Pick objects, or components (F9 / F10 / F11), then make the set.", true);
    let id = 0;
    v.undoChunk("quick select set", () => { id = t.setAdd({ name, ...cur }); });
    render();
    const s = t.setGet(id);
    return say("Set " + s.name + ": " + s.items.length + " " + KIND[s.kind] + ". Select it again from Windows > Sets.");
  }

  /** Pick a set again. how: "set" (default) or "add". */
  async function select(id, how) {
    const v = V(), t = T(), s = t && t.setGet(id);
    if (!s) return say("No set " + id + ".", true);
    if (s.kind === "objects") {
      const ids = s.items.filter((x) => t.node(x));
      if (!ids.length) return say("Set " + s.name + ": its objects are gone.", true);
      if (comp(v) && typeof forgeProObjectMode === "function") await forgeProObjectMode(v);
      ids.forEach((x, k) => t.select(x, k === 0 && how !== "add" ? "set" : "add"));
      return say("Set " + s.name + ": " + ids.length + " objects.");
    }
    if (!t.node(s.node)) return say("Set " + s.name + ": its object is gone.", true);
    if (t.root().id !== s.node || !comp(v)) {
      t.select(s.node, "set");
      if (typeof forgeProComponents === "function") await forgeProComponents(v, s.kind);
    }
    if (v.setSelMode && v.edit.mode !== s.kind) v.setSelMode(s.kind);
    const n = v.poly.v.length, nf = v.poly.f.length;
    let ids;
    if (s.kind === "edge") ids = s.items.map(([a, b]) => v.edgeIdOf(a, b)).filter((i) => i >= 0);
    else if (s.kind === "face") ids = s.items.filter((i) => i >= 0 && i < nf);
    else ids = s.items.filter((i) => i >= 0 && i < n);
    v.selectItems(s.kind, ids, how === "add" ? "add" : "set");
    const changed = s.nv && s.nv !== n;
    return say("Set " + s.name + ": " + ids.length + " " + KIND[s.kind] + "." + (changed
      ? " The mesh has changed since the set was made, so some may have moved to other places." : ""), changed);
  }

  /** +: the current selection goes into the set (same kind and object). -: it comes out. */
  function edit(id, sign) {
    const v = V(), t = T(), s = t && t.setGet(id), cur = current();
    if (!s) return say("No set " + id + ".", true);
    if (!cur || cur.kind !== s.kind || (s.kind !== "objects" && cur.node !== s.node)) {
      return say("Set " + s.name + " holds " + KIND[s.kind] + (s.kind === "objects" ? "" : " of one object") + ": pick those first.", true);
    }
    const have = new Map(s.items.map((x) => [keyOf(s.kind, x), x]));
    for (const x of cur.items) { const k = keyOf(s.kind, x); if (sign > 0) have.set(k, x); else have.delete(k); }
    v.undoChunk(sign > 0 ? "add to set" : "remove from set", () => t.setUpdate(s.id, [...have.values()]));
    render();
    return say("Set " + s.name + ": " + have.size + " " + KIND[s.kind] + ".");
  }
  function remove(id) {
    const v = V(), t = T(), s = t && t.setGet(id);
    if (!s) return "";
    v.undoChunk("delete set", () => t.setRemove(s.id));
    render();
    return say("Set " + s.name + " deleted (what it held stays). Ctrl+Z brings it back.");
  }
  function rename(id, name) {
    const v = V(), t = T();
    let ok = false;
    v.undoChunk("rename set", () => { ok = t.setRename(id, name); });
    render();
    return ok ? "" : say("That name is taken or empty.", true);
  }

  // ---- the Sets window
  let box = null;
  const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const btn = (text, tip, fn) => { const b = mk("button", "mini forge-btn", text); b.type = "button"; b.title = tip; b.dataset.tipName = tip; b.addEventListener("click", fn); return b; };
  function render() {
    if (!box || box.hidden) return;
    const t = T(), list = box.querySelector(".fsets-list");
    list.textContent = "";
    const sets = t ? t.setList() : [];
    if (!sets.length) list.append(mk("div", "fsets-empty", "No sets yet. Pick objects or components, then New Set (Create > Sets > Quick Select Set)."));
    for (const s of sets) {
      const row = mk("div", "fsets-row"); row.dataset.set = s.id;
      const name = mk("input", "fsets-name"); name.value = s.name; name.setAttribute("aria-label", "Set name");
      name.addEventListener("change", () => rename(s.id, name.value));
      name.addEventListener("keydown", (e) => e.stopPropagation());
      const info = mk("span", "fsets-info", s.count + " " + KIND[s.kind]);
      row.append(name, info,
        btn("Select", "Select the set (Shift: add it to what is picked)", (e) => select(s.id, e.shiftKey ? "add" : "set")),
        btn("+", "Add what is picked to the set", () => edit(s.id, +1)),
        btn("−", "Take what is picked out of the set", () => edit(s.id, -1)),
        btn("×", "Delete the set (what it holds stays)", () => remove(s.id)));
      list.append(row);
    }
  }
  function open() {
    const host = document.getElementById("forge");
    if (!host) return say("Open Forge first.");
    if (!box) {
      box = mk("div", "forge-float forge-setsdlg"); box.id = "forge-sets";
      const head = mk("div", "fx-head"); head.append(mk("b", "", "Sets"));
      const x = btn("×", "Close", () => { box.hidden = true; }); x.dataset.icon = "close";
      head.append(x);
      const foot = mk("div", "fx-foot");
      foot.append(btn("New Set", "Save what is picked now as a set", () => create()));
      box.append(head, mk("div", "fsets-list"), foot);
      host.append(box);
    }
    box.hidden = false;
    render();
    return "";
  }

  if (typeof FORGE_PRO_CMDS !== "undefined") {
    FORGE_PRO_CMDS.quickSet = ["Quick Select Set...", () => { const m = create(); open(); return m; }];
    FORGE_PRO_CMDS.setEditor = ["Sets", () => open()];
  }
  // a scene undo / redo can change the sets: keep the window honest
  document.addEventListener("keyup", () => { if (box && !box.hidden) render(); });
  return { create, select, edit, remove, rename, open, current, render };
})();
window.ForgeSets = ForgeSets;
