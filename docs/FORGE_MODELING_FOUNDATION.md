# Forge modeling foundation: the staged rework

The owner asked on 2026-10-25: "all the modeling systems and features need rework and thought-out depth and logic ...
everything needs to be redesigned properly. This is a huge task: break it up in parts, tackle what you can and hand it
off for later stages, flesh out single things completely one at a time ... we have 20 years of patches to go through
and quality-of-life features. Be very thorough."

The rule for every stage is to finish one system completely before starting the next. That means Maya's behaviour
first (Unreal where Maya has none), a test that drives it like a user would, and the docs. Each stage below is one
system.

## Done

| Stage | System | Where | Test |
|---|---|---|---|
| 0a | Flatten = scale to 0, never past flat (components and objects) | forge_toolkit.js `forgeScaleZeroSnap`, forge_polyops.js `P.flatten` | test_forge_flatten_ui, js/test_forge_flatten |
| 0b | One settings window: navigation, manipulators, pivot placement, snapping, soft selection, create, hotkeys, menus | forge_settings.js | test_forge_settings_ui |
| 1 | **Baseline.** New primitives sit on the grid (pivot at the base). `t` / INPUTS / In-View Editor has a Baseline attribute from -1 to 1. Settings > Create > Baseline sets the default; -0.5 is the old centred cube. | forge_poly.js `P.primitive(kind, {baseline})`, forge_model.js, forge_toolkit.js | test_forge_baseline_ui |
| 2 | **Several objects' components at once (Maya hilite).** In component mode, Shift + click another mesh adds it. F9 with several meshes picked shows them all. F8, Sculpt or editing another object splits the cage back into the objects, each in its own space with its transform untouched. Undo works inside the session, and an undo in object mode never leaves the objects joined. | forge_poly.js `multiJoin / multiSplit`, forge_scene.js `multiBegin / multiEnd / multiIds`, forge_pro.js `forgeProComponents` | test_forge_multiedit_ui, js/test_forge_multiedit |

How stage 2 works: the editor has one cage (`view.poly`), so the session joins the other meshes into it. Each mesh is
first carried into the working object's space, and nothing is welded. The other meshes' shapes step aside while the
session runs. The session lives on the working node (`multiSession`), so undo snapshots carry it.

The split works one of two ways:

- If the topology is unchanged (only moves), the exact vertex ranges come back.
- Otherwise, every connected piece goes to the object most of its untouched vertices came from. If every vertex
  moved, it goes to the object whose middle is nearest.

The selection survives a join or split because it is kept by world position.

## Next stages (in order)

| Stage | System | What "complete" means |
|---|---|---|
| 3 | **Pivot system** | `d` / Insert edits the pivot in object AND component mode. Bake pivot, reset pivot, pivot to the selection / bbox bottom / world, and `d` + `v` snap. The pivot is remembered per object (Maya's custom pivot). |
| 4 | **Selection depth** | Loop and ring with a step, Select > Similar, grow/shrink per mode, convert selection (Ctrl+F9..F11), select border / shell, the paint-select brush, saved selection sets, highlight preselection everywhere. The multi-object session from stage 2 must work with each of these. |
| 5 | **Manipulator modes** | Move in world, object, component (normal), parent and custom axis; tweak mode (drag a component without selecting it first); step snapping per mode; discrete rotate; scale about the pivot vs. per component (Maya's "Preserve children", "Pin component pivot"). |
| 6 | **Primitive creation** | Interactive creation (click-drag on the grid for the base, drag up for the height, like Maya's interactive creation / Unreal's box tool). Every primitive's attributes are in its INPUTS node, including subdivisions on all axes, caps, radius and axis. Undoable as one step. |
| 7 | **Construction history across objects** | INPUTS show every node of every picked object. Delete history by type, a non-deformer history, and history kept through combine and separate. |
| 8 | **Modeling tools pass** | Go through each tool (Extrude, Bevel, Bridge, Bridge Edge Loops, Multi-Cut, Insert Edge Loop, Offset Edge Loop, Merge / Target Weld, Collapse, Fill Hole, Append to Polygon, Poke, Wedge, Chamfer Vertex, Duplicate Face, Extract, Mirror, Booleans, Smooth, Reduce, Retopologize, Quad Draw). For each: Maya's options box, the In-View Editor, it working on the multi-object session, keeping UVs, one undo step, and a user-driven test. |
| 9 | **Booleans to Manifold** | WASM build, already in ZIVA_TASKS. Exact and watertight; the three-bvh-csg fallback stays. |
| 10 | **Quality-of-life sweep** | Repeat last (`g`), the tool settings remembered per tool, hotkey conflicts zero, and every message says what happened and what to do next. |

Stages 3 to 5 are the next in-session work. Stages 6 to 10 are handed off in ZIVA_TASKS.md with the same "complete"
bar.
