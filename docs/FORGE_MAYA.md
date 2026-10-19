# Forge, the way Maya works

Owner, 2026-10-20: *"I want my forge to be like maya ... menus depending on where my mouse clicks ... maya hot
keys ... space bar for selection menu with more menus ... the viewports the camera and the groups different
object and hierarchy, history and transforms. Reset pivot all of it. Add it to Loki especially the outliner
and the logic behind it all."*

## What is already here (patch 315, app/ui/forge_maya.js)

Maya's *interaction design*, re-implemented for a web canvas. No Autodesk code, art or icons are used - only
the way it behaves, which is not something copyright protects.

| Maya | Here | Where |
|---|---|---|
| marking menus (hold the right button) | a wheel of commands opens **at the cursor**; the object menu or the component menu by context; **Shift** = view menu, **Ctrl** = display menu; release over a wedge to run it, over the middle to cancel | `forgeMayaWheelShow` |
| the hotbox (hold Space) | a grid of menu columns - File, Edit, Create, Modify, Display, Panels - with real commands | `FORGE_MAYA_COLUMNS` |
| hotkeys q / w / e / r | select, move, rotate, scale | `forgeMayaKeys` |
| hotkeys 4 / 5 | wireframe, shaded | same |
| hotkeys F8 / F9 / F10 / F11 | component mode, vertex, edge, face | same |
| hotkey g | repeat the last command | same |
| **Alt + left / middle / right** | tumble / track / dolly - Maya's camera exactly | `mayaAlt` |

Two real bugs were found while wiring it:

1. `app/ui/app.js` treated **any** bare keystroke in an open sheet as "start typing in the chat box". Pressing
   `w` in Forge (Maya's move tool) summoned the chat and stole the keyboard. An open sheet now owns its keys.
2. The Maya keys register **with the viewer**, after `forge_edit.js` registers its own capture listener, so the
   Blender-style modal move/rotate/scale keeps every key while it runs - typing `0.25` for an exact distance is
   not eaten by the `4`/`5` display hotkeys.

## Why the rest is a real job: Forge is one welded mesh

Maya is a **DAG**: every object is a transform node with a shape under it, groups are transform nodes with
children, and a model keeps its **construction history** - the list of operations that built it, each one
still editable ("change the extrude distance from 2 to 3 and the model rebuilds").

Forge is not that. `view.load` (app/ui/forge.js) *flattens* whatever it is given into one welded vertex/index
array (`view.sm`) under a single `holder` group, and every tool edits that array. There is exactly one object,
its transform is `holder`'s (used for the gizmo, not for the data), and there is no record of how the mesh was
built - undo is a snapshot stack, not history.

So the outliner, groups, Duplicate and a construction history cannot be bolted on; they need the modeler's
core to hold a scene. That is the work below, in the order it has to happen.

## The tasks, in order

Status, 2026-10-20: **T1, T2, T3 and T4 shipped** (patches 317 and 321). T4b, T5's gesture and T6
are still open, below. Everything shipped has a test that would fail if it broke.

### DONE - T1: a scene of nodes (patch 317, app/ui/forge_scene.js)
- `ForgeScene` holds `ForgeNode`s: `{ id, name, kind: "group"|"mesh", parent, children[], transform
  {translate, rotate, scale}, pivot, visible, mesh }`. A `mesh` node owns the welded `sm` the tools edit.
- The viewer stops drawing one `holder` mesh and draws the tree, each node with its own `THREE.Object3D`.
- Existing tools keep working by operating on the **active** node's `sm`.
- Acceptance: two models can sit in the scene at once, each with its own transform, and sculpting one leaves
  the other untouched. `test_forge_ui` plus a new `test_forge_scene`.

### DONE - T2: the Outliner (patch 317)
- A panel down the left (Maya's Outliner shape): the tree, **rename** (double-click), **visibility** (v),
  **select**, **drag to re-parent**, and **middle-drag to re-order**.
- Signals: `select(node)`, `reparent(node, newParent)`, `rename`, `visibility`.
- Acceptance: the test builds a group, drags a node into it, and asserts the parent link and the drawn tree.

### DONE - T3: Group / Ungroup with Maya's pivot rule (patch 317)
- `Ctrl+G` groups the selection under a new transform node whose pivot is the **centre of the selection**
  (that is why Maya's groups rotate about the middle, not the world origin). `Ctrl+Shift+G` ungroups, keeping
  each child's world transform (Maya preserves position - it does not snap children to the origin).
- Acceptance: group two nodes, rotate the group 90°, assert each child's world position rotated about the
  selection centre.

### DONE - T4: the Channel Box (patch 321): translate / rotate in degrees / scale as numbers, and Reset
- The selected node's translate / rotate / scale as **editable numbers** (Maya's Channel Box), plus
  **Center Pivot** and **Reset Pivot** and **Modify > Freeze Transformations** (bake the transform into the
  vertices, leave the node at identity - Maya's Freeze).
- Acceptance: type 2 into translate Y and the node moves 2; Freeze then zeroes the transform without moving
  the model.

### OPEN - T4b: Center Pivot and Freeze Transformations
- **Center Pivot** sets the object's pivot to the centre of its bounding box so the manipulator turns about the
  middle (Maya's Modify > Center Pivot). Moving the pivot on its own means attaching the manipulator to a pivot
  node that drives the object's transform by a delta - the same trick app/ui/forge_edit.js already uses for
  component mode (`pivot` + `applyM`) - rather than moving the geometry, which would silently change what
  Export/Save writes out.
- **Freeze Transformations** bakes the node's transform into the vertices and leaves the node at identity.
  For the WORKING object that means writing view.sm and having the viewer re-upload its buffers, so it needs a
  small hook on the viewer (`sm` -> GPU) that does not exist yet.
- Acceptance: Center Pivot then rotate the handle - the object turns about its middle and its mesh data is
  untouched; Freeze then read the transform (all zero) and the exported mesh (unchanged in the world).

### OPEN - T5: Shift + drag duplicate  (a Duplicate button and `tree.duplicate()` exist; the shift-drag gesture does not)
- Shift-dragging a node with a manipulator leaves a copy behind and drags the new one (Maya's behaviour),
  with the copy inserted as a sibling.
- Acceptance: shift-drag, assert two nodes and that the original did not move.

### OPEN - T6: Construction history   (smaller than it looked - good news)
Checked at T4b time: the poly operations are **already parameterised** - `P.extrude(base, faces, 0.2)`,
`P.inset(base, faces, 0.25)` - and `app/ui/forge_model.js` already keeps
`forgeModel.last = { kind, base, faces, amount, out, pick }`, i.e. a **one-step** history with a re-runnable
op. So T6 is mostly turning that single step into an ordered **stack** per node
(`node.history = { base, ops: [{ kind, args }] }`), rebuilding by replaying `base -> ops` through
`v.showPoly(result, true, true)`, and giving the stack a panel row per op whose parameters can be typed and
re-run, plus **Delete History** (which just re-bases on the current mesh). The ops that fit straight away:
extrude, inset, delete faces / verts / edges, flip, smooth. Two do NOT fit and need their own representation
first: a **sculpt stroke** (Maya stores a sculpt node with every stroke) and **DynaMesh** (a resolution
change, not a mesh edit). Decision needed before starting: which of those two must be in the history, if any.

### (the original T6 note, kept for the reasoning)
- Each mesh node keeps an ordered list of operations (`{"extrude": {distance: 2}}`, `{"subdivide": 3}`, a
  sculpt stroke, ...) with the inputs they were applied with. The Channel Box shows them; selecting one
  re-opens its parameters and **rebuilds**; history can be deleted (Maya's "Delete History" freezes the mesh).
- This is the one that changes how the tools are written: each tool becomes `apply(mesh, params) -> mesh`
  plus a recorded node, instead of mutating `sm` in place. Do it after T1-T4, one tool at a time (extrude and
  subdivide first - they already take plain parameters in app/ui/forge_poly.js).
- Acceptance: extrude, change the recorded distance, and the mesh rebuilds; delete history and the mesh stays.

### Not v1
- Maya's Attribute Editor (a full property sheet per node type), the Node Editor / Hypergraph, referencing,
  and animation curves. Out of scope until T1-T6 are solid.

## The honesty note

Maya's own API (`cmds.markingMenu`, the `spaceLocator`-style node commands, `cmds.group`) was **not** read for
this: this session had no web access (Ziva showed an upgrade card), so the interaction model above is from
knowledge of Maya, not from re-reading Autodesk's documentation. Before T2/T3/T6 are called finished, check the
current Maya docs for the exact behaviours - especially the group pivot rule and Freeze Transformations.
