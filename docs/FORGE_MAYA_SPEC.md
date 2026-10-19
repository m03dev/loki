# Maya 2027, as it really behaves - the spec Forge follows

Read off the owner's own install of **Autodesk Maya 2027** on the Mac mini (`/Applications/Autodesk/maya2027`) on
2026-10-19 by Claude: `scripts/startup/hotkeySetup.mel` (the default hotkey set, 534 bindings),
`scripts/others/dagMenuProc.mel` (the right-button menu), `contextPolyTools*MM.mel` (Shift+right-button),
`polyConvertMM.mel` (Ctrl+right-button), `selectMarkingMenuImpl.mel` / `translateMarkingMenuImpl.mel` (q / w + left
button), `startup/Hotbox*Menu.mel` (the hotbox zones) and `createOutlinerPanelMenu.mel` / `OutlinerEdMenu.mel`.

**What this file is, legally:** a list of *facts* about how Maya behaves - which key does what, which command sits at
which compass point. No Autodesk code, MEL, icon or text is copied into LOKI (LOKI is public AGPL-3.0; Maya's scripts
are Autodesk's and are not licensed for that). Forge re-implements the behaviour in its own code
(`app/ui/forge_maya.js`, `app/ui/forge_scene.js`). Keep it that way: read Maya, write LOKI.

Mac: Maya binds every Ctrl shortcut to **Cmd** as well (`-cmd` twins of each `-ctl` line), and Alt is **Option**.
Forge accepts Ctrl and Cmd alike everywhere.

## Hotkeys (object and component modelling - the ones Forge implements)

| Key | Maya command | Forge |
|---|---|---|
| q / w / e / r | Select / Move / Rotate / Scale tool | yes |
| hold q / w / e / r + left button | that tool's marking menu (select: NW Marquee, NE Drag, W Paint, SW Lasso, E Camera-based, SE Clear) | q, w, e |
| t / y | Show Manipulator / last non-sacred tool | both |
| g / Shift+G | Repeat last command / repeat at mouse position | g |
| z, Ctrl+Z / Shift+Z, Ctrl+Y | Undo / Redo | yes |
| Ctrl+D | Duplicate (in place) | yes |
| Shift+D | Duplicate with Transform (repeats the last duplicate's offset) | yes |
| Ctrl+G | Group (pivot at the centre of the group's contents) | yes |
| p / Shift+P | Parent (the LAST selected becomes the parent) / Unparent (to the world) | yes |
| h | Toggle visibility (keeps the selection) | yes |
| Ctrl+H / Shift+H / Ctrl+Shift+H / Alt+H | Hide selected / Show selected / Show last hidden / Hide unselected | yes |
| Ctrl+Shift+A, Alt+D, Ctrl+Shift+I | Select All / Select None / Invert Selection | yes |
| Up / Down / Left / Right | Pick-walk: parent / child / previous / next sibling | yes |
| Alt + arrows | Nudge the selection | yes |
| Delete, Ctrl+Backspace | Delete / delete poly components | yes |
| a / Shift+A | Frame all (active / all panels) | yes |
| f / Shift+F | Frame selected (active / all panels) | yes |
| [ / ] | Undo / redo view change | yes (outside Sculpt, where they are the brush size) |
| Alt+Home | Go to the default view | yes |
| d (hold), Insert | Pivot edit mode (the manipulator moves the pivot, not the object) | yes |
| x / c / v (hold) | Snap to grid / curve / point | all three: grid, the nearest edge (curve), the vertex under the mouse; or switched on in the Snap menu / the Grid-Edge-Point chips |
| j (hold) | Toggle step snap of the move/rotate/scale tool | yes |
| - / = | Manipulator smaller / bigger | yes |
| 0 / 1 / 2 / 3 | Display quality default / low / medium / high (smooth preview) | not yet (FORGE_MAYA.md T9) |
| 4 / 5 / 6 / 7 | Wireframe / Shaded / Textured / Use all lights | 4, 5, 7 |
| Ctrl+1 | Isolate select | yes |
| F8 | Object <-> component | yes |
| F9 / F10 / F11 / F12 / F7 | Vertex / Edge / Face / UV / Multi component | F9-F11 |
| Ctrl+E / Ctrl+B | Extrude / Bevel | Extrude; Bevel is a task (no bevel op yet) |
| Shift+> / Shift+< (component) | Grow / shrink selection | yes |
| Ctrl+A | Attribute Editor (or the Channel Box) | toggles the Channel Box |
| Space (hold) | Hotbox | yes - Maya's layout: Recent Commands + menu rows around the mouse, the five zones |
| Space (tap) | Single view <-> four views; a tap over a pane maximises THAT pane | yes |
| Alt+M | Hotbox display rows | - |
| Return / Esc | Complete current tool / abort it | yes (Esc never closes Forge) |
| Ctrl+Space | Hide the UI (only the viewport), again to bring it back | yes |
| Alt+X | X-ray | yes |
| b (component) / b, m + drag (sculpt) | Soft selection / brush size, strength | yes |

Outliner-only keys: **Return** renames the selected item, **f** reveals (scrolls to) the selection.

## Camera (the viewport)

Alt+left tumble, Alt+middle track, Alt+right dolly, wheel zooms. In an orthographic view (top / front / side) tumbling
is off. Without Alt the left button selects, the middle button drags the manipulator's active handle, the right button
is the marking menu.

## Marking menus - compass layout

**Right button on an object (dagMenuProc).** For a polygon object the component wedges are, in Maya's own fill order
N, W, S, E, SW, SE, NW:
N Edge, W Vertex, S UV, E Face, SW Vertex Face, SE UV Shell, NW Multi - and **NE Object Mode** whenever the object has
components. Below the ring Maya lists Select, Select All, Deselect, Select Hierarchy, Inverse Selection, Select
Similar, then Inputs / Outputs, Paint, Actions, material assignment.

**Shift + right button**
- on nothing (contextPolyToolsDefaultMM): the primitives - NE Disc, E Sphere, SE Torus, S Cube, SW Cone, W Cylinder,
  NW Plane.
- on an object (contextPolyToolsObjectMM): S Extrude, SW Insert Edge Loop, NE Fill Hole, N Merge Vertex Tool, W Multi-Cut,
  NW Sculpt Tool, E / SE Soften-Harden.
- on vertices: S Extrude Vertex, E Chamfer Vertex, SW Delete Vertex, N Merge (submenu), W Multi-Cut, NE Average.
- on edges: S Extrude Edge, E Bevel Edge, SW Delete Edge, N Merge/Collapse (submenu), NE Flip/Spin, W Multi-Cut.
- on faces: S Extrude Face, E Bevel Face, SW Wedge, NE Poke, SE Face Normals (submenu: Reverse, Conform), W Multi-Cut.

**Ctrl + right button (polyConvertMM)** - convert the selection: W To Vertices, N To Edges, S To Faces, E To UVs,
NE Grow, NW Shrink, SE Edge Loop, SW Edge Ring.

**w + left button (translate MM)**: W World, NW Object, and the axis-orientation entries.

## The hotbox (hold Space)

Rows of the menu bar's menus, plus five **zones**; press the left button in a zone for its marking menu:
- **Center**: N Perspective, W Top, S Front, E Side (switch the panel's camera).
- **North**: panel layouts - Single Perspective, Four View and the two-pane layouts; S toggles the Outliner.
- **South**: change the panel to N Outliner, E Graph Editor, S Hypergraph, W Hypershade, NW Render View, ...
- **East**: toggle UI elements (shelf, status line, channel box, tool settings ...).
- **West**: selection mode - NW Object/Component toggle, NE Hierarchy, SW Polygons ...

## The Outliner

Click selects, **Ctrl+click** toggles, **Shift+click** selects a range. Double-click or Return renames. The arrow
expands a node; **Shift+click on the arrow** expands the whole branch. Middle-drag (left-drag in recent versions) an
item onto another to parent it - onto *any* transform, not only groups; drop it between two items to re-order;
drop it on empty space to unparent it to the world. Right-click: Select Hierarchy, Duplicate, Group, Ungroup,
Rename, Hide/Show, Reveal Selected, Show DAG Objects Only, Shapes, Expand/Collapse all. Its Display menu has
DAG Objects Only and Shapes.

## Transforms and pivots

A transform node's matrix (Maya's MTransformationMatrix, simplified to one pivot):
`world = parent * T(translate) * T(pivotTranslate) * T(pivot) * R * S * T(-pivot)`.
- **Moving the pivot** (d / Insert) does not move the object: Maya keeps *translate* unchanged and absorbs the
  difference in the pivot-translate term, `C += (I - R*S)(P_old - P_new)`.
- **Center Pivot**: the pivot goes to the centre of the object's bounding box (its children included).
- **Reset Pivot**: the pivot goes back to the object's own origin.
- **Freeze Transformations**: translate/rotate/scale are baked into the geometry and become 0/0/1; the pivot stays
  where it was in the world.
- **Reset Transformations**: translate/rotate/scale back to 0/0/1, the geometry is not touched.
- **Group**: a new transform with translate 0 and its pivot at the centre of the contents; children keep their place.
- **Duplicate** copies the node with its hierarchy as a sibling, renamed with the next free number (`pCube1` -> `pCube2`).
- **Shift + drag** with a manipulator duplicates and drags the copy (owner's description of how they work).
