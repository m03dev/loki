# Forge, the way Maya works

Owner, 2026-10-19 (the date was written as 10-20 by mistake): *"I want my forge to be like maya ... menus depending on where my mouse clicks ... maya hot
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

Status, 2026-10-19 early morning: **T1, T2, T3 and T4 shipped** (patches 317 and 321). T4b, T5's gesture and T6
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

### DONE - T6: Construction history   (poly ops, DynaMesh and sculpt strokes)
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

**DONE (patch 325):** the stack, the panel and Delete History. `forgeModel.hist = { base, ops }` is built by
`forgeFaceOp` (extrude, inset, delete faces / verts / edges, flip, smooth) and by `forgeDynamesh` (a `dynamesh`
op carries its own source triangles because it IS the first mesh, so `base` is null). `forgeHistRebuild()`
replays `base -> ops` through `forgeHistApplyOp`, the amount slider now rebuilds the WHOLE chain instead of
one step, and the panel (History, under the Channel Box) lists each step with its number and a `x` to remove
it. Tests: two extrudes are recorded in order, changing the second one's amount rebuilds from the first and
moves the mesh, removing a step rebuilds without it, Delete History empties the stack, and a DynaMesh step
rebuilds when its resolution is changed.

### DONE - T6c: a sculpt stroke in the history (the option the owner chose: recorded vertex deltas)
**Shipped (patch 328).** A stroke is recorded as the **welded vertices it moved, with their positions before
and after** - seven numbers per vertex, never a list of dabs (a stroke is thousands of dabs but usually a few
hundred vertices). No change to the sculpting code was needed: `forge.js` calls `snapshot()` at the start of a
stroke, so the top of `view.undoStack` when the pointer is released is the state **before** the stroke
(`view.sculptStrokeEnd` is the same function, for tests and scripts). The History lists it as `sculpt · Nv`,
and removing it writes those vertices' old positions straight back, which is exactly what deleting Maya's
sculpt node does. Replaying the whole history walks the steps in order: the polygonal ones rebuild the mesh,
the sculpt ones re-apply their vertices.

**The known limitation, kept honest:** the vertex ids belong to the mesh as it was when the stroke was made, so
a polygonal step ABOVE it that is later edited can make the record stale. `forgeHistSculpt` skips ids that no
longer exist instead of writing into the wrong vertices; Maya warns in the same situation. The two ways it was
considered are kept below for the record.
1. **Record deltas**: at stroke start, keep the welded vertex ids under the brush and their positions; at
   stroke end, keep the new ones. Replay writes those positions back. Compact and exact, but only valid while
   the topology is unchanged, so a poly step ABOVE it that is edited afterwards invalidates it (Maya has the
   same constraint between history nodes - it warns rather than silently lying).
2. **Make the sculpt engine callable on a snapshot** (the brush maths is already pure functions of
   `(positions, normals, brush)`), so a stroke becomes a normal op in the chain. Cleaner, and a real refactor
   of `app/ui/forge.js`.
Either way a stroke is far larger than the other ops (one stroke is many dabs), so it should be stored as
affected-vertices + deltas, never as a list of dabs.

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

## 2026-10-19 (Claude): Maya 2027 read off the owner's own install, and the next layer built on it

The honesty note at the bottom is answered: Maya 2027 is installed on the Mac mini, so its **own scripts** were read
(the default hotkey set, every marking menu, the hotbox zones, the Outliner menus). The facts are in
**docs/FORGE_MAYA_SPEC.md** - read it before changing anything here. Nothing of Autodesk's is copied: facts only,
our own code. Everything Ziva built above is kept; this extends it.

### DONE (Claude, tests/test_forge_maya_ui.py, 55 checks, ~23 s)
- **Real pivots** (forge_scene.js): every node is outer (T+C+P, R, S) > inner (-P) > shape + children, i.e. Maya's
  matrix. Moving / centring / resetting the pivot never moves the object and never changes the Channel Box's
  translate (Maya's pivot-translate rule). Freeze keeps the pivot where it was in the world. T4b is now exact
  (before, Center Pivot shifted the vertices).
- **Every object is editable**: `api.makeWorking(id)` moves the tools' mesh (the viewer's holder) into the node you
  edit; the old one keeps a static copy, its poly cage and its history. A component wedge, F9-F11, F8, Sculpt or
  the Outliner's "Edit this mesh" does it.
- **Create makes NEW objects** named the Maya way (pCube1, pSphere1 ...); the old object stays.
- **Duplicate** copies the SELECTED node with its hierarchy as a sibling, next free number; **Shift+D**
  repeats the last offset; Shift+drag (T5) uses it.
- **Group** has translate 0 and its pivot at the centre (Maya), under the selection's own parent.
- **Parent / Unparent** (p / Shift+P, last selected is the parent); parenting under ANY node, cycles refused.
- **Hide / show** (h, Ctrl+H, Shift+H, Ctrl+Shift+H, Alt+H), **isolate** (Ctrl+1), **pick-walk** (arrows),
  **nudge** (Alt+arrows), select all / none / invert / hierarchy.
- **Viewport selection** in object mode: click, Shift toggles, Ctrl/Cmd removes, Ctrl/Cmd+Shift adds, box drag;
  selected objects outlined (the last green, Maya's colours).
- **Marking menus by context**, picked by DIRECTION past a dead zone like Maya: right button on an object (Maya's
  exact compass: N Edge, W Vertex, E Face, S UV, NE Object Mode ...), on nothing (views), Shift (Create on nothing,
  mesh/vertex/edge/face tools on a selection), Ctrl (convert selection), q / w / e + left button. Entries Forge
  can't do yet are shown greyed in Maya's place with the reason.
- **Hotbox** with nine menus and the five zones (centre = Persp/Top/Front/Side ...); **Space tap** = one/four views,
  over a pane = that pane big; orthographic **Top / Front / Side** views (tumble off, like Maya).
- **Pivot edit** (hold d, or Insert), **snap** (hold x grid, j step), manipulator size (- / =), **[ / ]** view
  undo, Alt+Home default view, a / f frame all / selected, Ctrl+A Channel Box, Enter / Esc.
- **Camera**: without Alt no button turns the view (left selects, right = menus); Alt/Option + left / middle /
  right = tumble / track / dolly; Cmd = Ctrl everywhere for the Mac.
- **Outliner**: expand / collapse (Shift = the whole branch), Shift+click range, Ctrl/Cmd+click toggle, drag onto a
  row = parent, between rows = re-order, onto empty space = unparent, Return renames, f reveals, right-click menu.
- **Maya only** (owner, 05:23): the Blender hotkeys and mouse moves are gone - no 1/2/3, no G/R/S, no middle-drag
  orbit, no Alt+click loop (a double-click on an edge takes the loop, Maya's way); Alt/Option is only ever the camera.
  tests/test_forge_edit_ui.py now drives component mode with Maya's keys.

### DONE (Claude, 2026-10-19 later morning) - Maya's workspace, the hotbox, snapping
- **Workspace**: Forge fills the window - the Outliner column on the left, the viewport, the Channel Box column
  (with History) on the right. The Create panel, Materials, the shelf (the old floating bars) and the Modeling
  Toolkit are hidden and come back from Space > Windows (ticked when showing), remembered per machine
  (`loki-forge-panels` - ONE store: Ziva's `window.forgePanels`, the UI button and the Outliner fold now sit on it); Ctrl+Space hides everything but the viewport and brings it back; Esc never closes Forge.
- **Space = Ziva's wheel at the mouse** (owner to Ziva: "float where my mouse is ... like a wheel and when you hover over
  it brings down a new menu"): twelve wedges - Recent + the eleven menus below - each dropping its menu OUTWARD (never
  over the ring), ticks on switches, and every menu ends with "All menus", the full hotbox:
- **Hotbox like Maya's**: Recent Commands + File Edit Create Select Modify Display Windows above the mouse, Mesh / Edit
  Mesh / Mesh Tools / Snap below it, each opening its own list on hover; the five zones around the middle.
- **Snapping**: hold x (grid), c (edge / curve - the diagonal a quad was split along is not an edge), v (vertex under
  the mouse, or the nearest on screen) while dragging a handle; keeps the handle's axis; works for objects, the pivot
  (d) and components (onto other objects and the grid). Grid / Edge / Point chips bottom-left of the viewport and the
  Snap menu keep them on. A ground grid like Maya's (Display > Grid).
- Fixed: the first handle drag after Ctrl+Z did nothing (the handle's matrices were stale).
- Open for Ziva: components snapping onto the SAME mesh's other vertices (needs the moving vertices left out of the
  pick), and showing a new primitive's inputs (subdivisions) in the Channel Box like Maya's INPUTS section.

### OPEN - next, in this order (Ziva: these are yours, see ZIVA_TASKS.md "Ziva's long run")
- **T7 Real-machine pass**: use Forge for 20 minutes the way the owner uses Maya (WebView2 on the PC, WKWebView on
  the Mac): every hotkey in FORGE_MAYA_SPEC.md, Option-camera on the Mac trackpad and mouse, the hotbox zones, the
  Outliner drag. Fix what feels wrong; write down what Maya does differently.
- **T8 Missing modelling tools in Maya's places** (greyed wedges today): Bevel (Ctrl+B), Insert Edge Loop, Multi-Cut,
  Merge / Merge to Center, Fill Hole, Chamfer, Poke - on `P.topology` / `P.edgeRing` (forge_poly.js; GoBuild is
  GPL-3.0 and already vendored). Each one: a history op (T6), a test, and its wedge turned on.
- **T9 Smooth preview (1 / 2 / 3)**: display-only Catmull-Clark of the working mesh (P.smooth on a copy), the cage
  kept editable; 1 back to the cage.
- **T10 Export the whole scene**: Save .glb writes every visible node with its hierarchy and transforms (today it
  writes the working mesh only) - GLTFExporter on the outer groups, without the selection boxes / overlays.
- **T11 Sculpt strokes in the history (T6c)** - DONE by Ziva in fa19bc1 (a stroke = the vertices it moved, before and
  after); merged into the new forge_scene.js, recorded only when a stroke really happened. Still outside the history:
  Freeze Transformations on the edited mesh - make it a step too.
- **T12 Attribute Editor lite + UV editing**: per-node attributes (name, visibility, pivot numbers) and a first UV
  view, then turn on the UV wedges.

## The honesty note (answered 2026-10-19 - see the section above and docs/FORGE_MAYA_SPEC.md)

Maya's own API (`cmds.markingMenu`, the `spaceLocator`-style node commands, `cmds.group`) was **not** read for
this: this session had no web access (Ziva showed an upgrade card), so the interaction model above is from
knowledge of Maya, not from re-reading Autodesk's documentation. Before T2/T3/T6 are called finished, check the
current Maya docs for the exact behaviours - especially the group pivot rule and Freeze Transformations.
