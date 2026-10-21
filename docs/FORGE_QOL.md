# Forge - modelling quality of life (research, 2026-10-21)

Owner 03:39: "do research quality of life and patch notes deep dive what we need and what people want". A research
pass over the reference package's release notes (2022-2027), another open-source modeller's 4.x modelling notes,
and modeller forums (Polycount threads on the modelling toolkit, symmetry and scripts people ask for). Product names
are left out on purpose (owner 2026-10-19); "the pro tool" = the reference package Forge follows.

Status: **done** = in Forge now, **part** = some of it, **open** = not yet. Effort for a three.js/JS build: S / M / L.

| # | Feature | Why modellers want it | Status | Effort |
| --- | --- | --- | --- | --- |
| 1 | Hide / show set: hide selected, hide unselected, show last hidden, h toggle, isolate | basic scene hygiene every workflow assumes | done (2026-10-21: keys back after a channel edit) | S |
| 2 | Display layers V / P / blank-T-R + colour | the main way to lock and declutter | done V T R colour; P (playback) open | M |
| 3 | Free image planes: alpha gain, all views / one camera, keep aspect | reference pictures to model over | done (alpha, aspect, view-facing); "looking through camera" open | S-M |
| 4 | Outliner: hidden greyed, search, shapes, DAG-only, drag parent / reorder, colour | finding and organising objects | part (grey, search, drag, filters); per-node colour open | M |
| 5 | Symmetry that holds the centre seam with every tool | top forum complaint | part (X/Y/Z sculpt + mirror ops); seam weld across poly tools open | L |
| 6 | Mirror that never flips normals (or freezes a -1 scale) | black, reversed halves after mirroring | open - check Mesh > Mirror on a negatively scaled object | S |
| 7 | Context marking menus (right / Shift-right), extrude + bevel ones | most modelling happens from them | done | M |
| 8 | Snap from a chosen base point to a target vertex | precise placement | open | M |
| 9 | Tumble / track while a transform runs | no need to stop the move to look | open | S |
| 10 | Snap kind shown at the cursor (vertex / midpoint / edge) | knowing what you will snap to | open | S |
| 11 | Grid snap + custom rotate / scale steps | precise hard-surface work | part (grid, j step) | S |
| 12 | Soften / harden edges by angle, changeable later | clean shading on hard-surface models | open | S |
| 13 | Bevel limited to selected / hard / above-angle edges | bevel the whole model at once without wrecking it | open | M |
| 14 | One interactive "smart" extrude that cuts, merges and unions | fewer clean-up steps | open | L |
| 15 | Shape-following bevel on messy / boolean topology | bevels that survive real models | open | L |
| 16 | Live booleans with visible inputs (slice, hole punch) | non-destructive hard-surface | open | L |
| 17 | Grow / shrink loop and ring selections, one side only | fast selections | part (grow / shrink, loop / ring) | S-M |
| 18 | Multi-cut showing % along the edge + edge-loop insert | exact cuts | part (multi-cut, insert loop); % readout open | M |
| 19 | Manipulator aligned to the selected component without re-picking | fewer clicks | open | S |
| 20 | Bridge not twisted by default | fewer undo-and-retry | check bridge twist default | S |
| 21 | Wireframe colour / opacity per object | reading busy scenes | open | S |
| 22 | Unsmooth (reverse a subdivision) | take a smoothed mesh back to a cage | open (the sculpt engine's levels can do Lower) | M |
| 23 | Extrude makes sensible UVs | less UV clean-up | open | M |
| 24 | Hotkeys printed in every menu; toolkit tools stay on when switching | discoverability | part (hotbox drops show keys) | S |
| 25 | Hard-surface helpers: vertex bevel, dynamic duplicate (array), a screws / bolts kit | the most-installed add-ons | open | M-L |

## The pro tool's exact behaviours (facts Forge copies)

- **Free image plane**: its own transform node; width / height = the picture's pixels / 100 once a picture is in;
  keeps its aspect; display "in all views" (default) or "looking through camera"; display mode None / Outline /
  RGB / RGBA (default) / Luminance / Alpha; Alpha Gain default 1 (typing above 1 allowed); Depth only applies to
  camera-attached planes. No lock attribute - people lock channels or use an R layer.
- **Display layers**: V visible; P visible in playback; third box blank = normal, T = template (wireframe, not
  selectable, not snappable), R = reference (normal shading, snappable, not selectable or editable); colour per
  layer; Enable Overrides off = the layer does nothing.
- **Hide hotkeys**: Ctrl+H hide, Shift+H show, Ctrl+Shift+H show last hidden, Alt+H hide unselected, H toggle
  (Independent / Dependent mode), Shift+L view selected; 4 / 5 / 6 / 7 wire / shaded / textured / lights; 1 / 2 / 3
  smoothness.
- **New scene**: persp / top / front / side startup cameras (undeletable, hidden from normal listings); ortho
  cameras 1000.1 from the origin; persp at about (28, 21, 28).
- **Outliner**: hidden objects in grey; "hide in Outliner"; Display > Shapes, DAG only, sort; Show filters;
  search; middle-drag to parent / reorder / unparent; P / Shift+P parent / unparent; per-node colour.

Sources: the reference package's online help (Display Layer Editor, image plane attributes, display hotkeys,
Display menu, Outliner), CG Channel's release write-ups 2022-2027, the open-source modeller's 4.0-4.2 modelling
release notes, Polycount threads (modelling toolkit wishes, symmetry, script requests, ortho cameras),
tech-artists.org (startup cameras), 80.lv (a popular hard-surface add-on's 3.0 release).

## Second pass (2026-10-21 10:00) - layout, menus, sculpt, UV and node-editor wishes

Owner 09:49: "research quality of life and patch notes deep dive what we need and what people want". Sources: recent
release notes of the big modellers / sculptors / painters (2024-2026) and user wish lists (paper-cut threads, idea
forums, Polycount, sculpting-app forums). Paraphrased; links for checking.

| # | Wish | Why | Status after this session |
| --- | --- | --- | --- |
| L1 | Drag any panel onto an edge to dock it, with drop zones | the newest open-source modeller only got this in 4.3, after years of asking ([notes](https://developer.blender.org/docs/release_notes/4.3/user_interface/)) | **done** (forge_dock.js) |
| L2 | Save / load / reset named layouts | resetting one workspace without a factory reset is a classic complaint; Material Maker 1.7 added it | **done** (Windows > Layouts) |
| L3 | Correct scaling on mixed-DPI and small / big screens | popups whose close button cannot be reached on 4K + 1080p setups | **done**: interface size Auto / fixed % |
| L4 | Separate UI / font / panel-width controls | a mobile sculpting app ships four sliders ([manual](https://nomadsculpt.com/manual/interface)) | part: size + every panel width in % |
| L5 | Panels remember where they were; vertical monitors | toolbars forgetting their side | **done**: per workspace AND per screen shape |
| L6 | Editable radial / marking menus as data | the main reason people stay with a tool; pie-menu editors are top add-ons | **done** (Menu Settings editor) |
| L7 | Resizable radial menus | one sculpting app lets you resize and rotate its wheel | **done** size + opacity; rotate open |
| L8 | Tear-off menus | a pro-tool staple | **done** (menu bar, hotbox, wheel) |
| L9 | A favourites / Quick Menu | top request on a sculpting forum | **done** (Alt+Q, right-click to add) |
| L10 | Search every command | quick search / command palettes | part (the command line); a fuzzy palette is open |
| L11 | Scroll bars only where something scrolls | small regions should not show bars | **done** (also the app-wide 38 px page scroll fixed) |
| M1 | Crash-proof undo, autosave with rotating backups | the most-cited complaint is crashes and settings resetting, not missing tools | open (autosave) |
| M2 | Multi-Cut that snaps reliably and stays active | | part |
| M3 | Shape-aware bevel with live width / segments | the newest pro release's headline | open (HANDOFF problem 5) |
| S1 | Dense-mesh speed; entering sculpt fast | an open-source sculpt refactor went 11 s -> 1.9 s on 16M faces | part (C++ engine) |
| S2 | Reduce / decimate | export and games need light meshes | **done** (C++, meshoptimizer's simplifier) |
| U1 | UV packing with pixel padding, holes filled | users leave for dedicated packers | part (xatlas) |
| U2 | Moving UVs never moves the mesh | a known pro UV complaint | check |
| N1 | Typo-tolerant node search; drop a node on a wire to insert it | node-editor basics in a material designer's 13.1 | open (Materials workspace) |
| N2 | Frames, sticky notes, reroute dots, auto-layout | | open |
| N3 | Preview any node's output | | part (the map thumbnails) |
