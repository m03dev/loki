# Forge's modelling behaviour - the spec Forge follows

Forge follows the conventions of the industry-standard professional modelling packages (owner, 2026-10-19: no
product or vendor is named anywhere in LOKI). This file lists the *behaviour* - which key does what, which command
sits at which compass point of a marking menu, how pivots and the Outliner work.

**Legally:** these are facts about behaviour. No third-party code, script, icon or text is copied into LOKI (LOKI is
public AGPL-3.0). Forge implements the behaviour in its own code (`app/ui/forge_pro.js`, `app/ui/forge_chrome.js`,
`app/ui/forge_scene.js`). Keep it that way.

Mac: every Ctrl shortcut also works with **Cmd**, and Alt is **Option**.
Forge accepts Ctrl and Cmd alike everywhere.

## Hotkeys (object and component modelling - the ones Forge implements)

| Key | Command | Forge |
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
| 1 / 2 / 3 | Smooth preview: the cage / smooth + cage / smooth (a display only; the selection wire stays the cage's) | yes |
| 4 / 5 / 6 / 7 | Wireframe / Shaded / Textured / Use all lights | 4, 5, 7 |
| Ctrl+1 | Isolate select | yes |
| F8 | Object <-> component | yes |
| F9 / F10 / F11 / F12 / F7 | Vertex / Edge / Face / UV / Multi component | F9-F11 |
| Ctrl+E / Ctrl+B | Extrude / Bevel | Extrude; Bevel is a task (no bevel op yet) |
| Shift+> / Shift+< (component) | Grow / shrink selection | yes |
| Ctrl+A | Attribute Editor (or the Channel Box) | toggles the Channel Box |
| Space (hold) | Hotbox | yes - centred on the mouse: the menu rows hug the pointer (12 px above / below), a menu drops down where you hover and stays after Space is released until you click; the five zones. The older radial wheel is Windows > Radial Menus |
| Space (tap) | Single view <-> four views; a tap over a pane maximises THAT pane | yes |
| Alt+M | Hotbox display rows | - |
| Return / Esc | Complete current tool / abort it | yes (Esc never closes Forge) |
| Ctrl+Space | Hide the UI (only the viewport), again to bring it back | yes |
| Alt+X | X-ray | yes |
| b (component) / b, m + drag (sculpt) | Soft selection / brush size, strength | yes |

Outliner-only keys: **Return** renames the selected item, **f** reveals (scrolls to) the selection.

## Camera (the viewport)

Forge's own controller (`forgeProCamera` in `app/ui/forge_pro.js`, 2026-10-19 evening); OrbitControls only keeps the
centre of interest. What a drag does is decided at the press, from the button and the keys held then:

| Drag | Does |
|---|---|
| Alt/Option + left | tumble about the centre of interest: left/right turns about the world's up axis, up/down tilts (stops just short of straight up/down) |
| Alt/Option + middle | track: the picture moves 1:1 with the mouse at the centre of interest |
| Alt/Option + right | dolly toward / away from the centre of interest: right or down = in, left or up = out (exponential, so it feels the same near and far) |
| Alt/Option + left + middle | dolly |
| + Shift | tumble / track locked to the first direction moved |
| Alt/Option + Ctrl/Cmd + left | box dolly: a box drawn left -> right fills the view with it, right -> left moves out |
| wheel | dolly in / out in steps |

In an orthographic view (top / front / side) tumbling is off. Without Alt the left button selects, the middle button
drags the manipulator's active handle, the right button is the marking menu. Every camera move that ends can be
undone with [ and redone with ].

## Right button

The marking menu appears the moment the button goes down, under the pointer, and only while it is held. Let go over a
wedge or a list item - or flick toward a wedge - and it runs; let go in place and it closes with nothing run (a quick
click does nothing). On empty space it is a short list: Complete Tool, Select All, Select None, Undo, Redo, Repeat
Last, Frame All, More. Esc closes it.

## Marking menus - compass layout

**Right button on an object .** For a polygon object the component wedges are, in the standard fill order
N, W, S, E, SW, SE, NW:
N Edge, W Vertex, S UV, E Face, SW Vertex Face, SE UV Shell, NW Multi - and **NE Object Mode** whenever the object has
components. Below the ring the menu lists Select, Select All, Deselect, Select Hierarchy, Inverse Selection, Select
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

A transform node's matrix (the standard transformation matrix, simplified to one pivot):
`world = parent * T(translate) * T(pivotTranslate) * T(pivot) * R * S * T(-pivot)`.
- **Moving the pivot** (d / Insert) does not move the object: Forge keeps *translate* unchanged and absorbs the
  difference in the pivot-translate term, `C += (I - R*S)(P_old - P_new)`.
- **Center Pivot**: the pivot goes to the centre of the object's bounding box (its children included).
- **Reset Pivot**: the pivot goes back to the object's own origin.
- **Freeze Transformations**: translate/rotate/scale are baked into the geometry and become 0/0/1; the pivot stays
  where it was in the world.
- **Reset Transformations**: translate/rotate/scale back to 0/0/1, the geometry is not touched.
- **Group**: a new transform with translate 0 and its pivot at the centre of the contents; children keep their place.
- **Duplicate** copies the node with its hierarchy as a sibling, renamed with the next free number (`pCube1` -> `pCube2`).
- **Shift + drag** with a manipulator duplicates and drags the copy (owner's description of how they work).

## The look (2026-10-19 evening: modern, high contrast)

Owner 17:06: "it looks old and washed out, bring up the contrast and make pixels sharper ... modern and seamless". The
layout stays (menu bar, status line, tool box, Outliner, viewport, Channel Box, time slider, help line); the colours
are re-tuned at the end of `app/ui/forge.css`:

| Part | Forge |
|---|---|
| panels / menu bar / status line | #2b2c2f, text #ededed (font smoothing on, weight 500) |
| lists / fields | #212225 / #161719 |
| selection, menu highlight, active tool | #2f7fd0 |
| menus (every drop-down, the hotbox, the marking list, the Outliner menu) | #26272a, 20 px rows, tick column, hotkey right-aligned in #9ea3aa, hairline separators |
| viewport gradient | #8099b8 -> #627a98 -> #435570 -> #26303d -> #12161b -> #0b0c0e |
| the picture | drawn at 1.5x a standard screen's pixels (supersampled), full density on high-DPI screens up to 3x |
| shelf | hidden until Windows > UI Elements > Shelf |
| component display | edges thin light blue (#86c6e6), selected orange (#ff8a1a), vertices purple (#a94fd1) only in vertex mode, selected yellow; selected faces a light orange tint; no object wire on the object being edited; the object wire always follows edits (no ghost of the old shape) |

### Earlier measurements (afternoon, kept for reference)


Screenshots of the owner's reference package (General workspace, an unsaved scene with a cube) were sampled pixel by pixel:

| Part | Reference | Forge |
|---|---|---|
| panels, menu bar, status line, tool box | #444444 | same |
| Outliner list background | #373737 | same |
| fields (Channel Box, time slider, command line) | #2b2b2b | same |
| selected row / menu highlight | #5285a6 | same |
| active tool button | #487588 | same |
| shelf tabs / shelf | #383639 / #4a4643, orange-ish icons | same |
| viewport gradient | #879bb3 top -> #5f7187 -> #2a323d -> #131418 bottom | same stops |
| grid | dark lines over the gradient, darker axes through the origin | black at low opacity, axes darker |
| shading | lambert1: flat matte grey, faces #626262-#717171 on screen | matte grey (view.proShade), the standard default light from the camera |
| selection | the object's own edges in teal-green (~#65fdcd), the others white | EdgesGeometry wire (a box only above 80k triangles) |
| heads-up display | Verts / Edges / Faces / Tris / UVs, three columns (all / selected / components), top-left; camera name bottom-centre; axis triad bottom-left; view cube top-right | same |
| Channel Box | Channels Edit Object Show menu, name, Translate X..Visibility rows (labels right-aligned), SHAPES, INPUTS | same; INPUTS = Forge's history with the standard node names |
| Outliner | Display Show Help menu, search field, persp / top / front / side greyed first | same |
| bottom | time slider + range slider (1-120, 24 fps), help line ("Move Tool: ..."), command line | same; the command line runs a small command language (polyCube, move, select -cl, setAttr, xform -cp ...) |

## Mesh tools (2026-10-19 evening)

| Menu | Forge | Command line |
|---|---|---|
| Mesh > Combine | the selected meshes become one new object polySurfaceN (world space, pivot at its middle); the originals go, their children move to the world | polyUnite |
| Mesh > Separate | each piece that shares no vertex becomes its own object, grouped under `<name>_parts` | polySeparate |
| Mesh > Mirror (X / Y / Z) | the edited object gets a mirrored copy across the world plane through the origin, the seam welded, faces on the plane dropped; in the history as polyMirror | polyMirrorFace -axis 0/1/2 |
| Edit Mesh > Insert Edge Loop | a loop half way round the quad ring the picked edge crosses; in the history as polySplitRing | polySplitRing |
| Edit Mesh > Merge | picked vertices closer than 0.001 x the model size become one (their average); collapsed faces go; history polyMergeVert | polyMergeVertex |
| Edit Mesh > Merge to Center | all the picked vertices become one, at their middle | - |
| Edit Mesh > Fill Hole | each open border the picked components touch (all of them when nothing is picked) gets one face, wound to face out; history polyCloseBorder | polyCloseBorder |

