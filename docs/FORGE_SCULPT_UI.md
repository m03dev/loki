# Forge - sculpt mode, redone (2026-10-21)

Owner 13:59: "sculpting needs a complete overhaul ... a wheel with all the brushes ... a bar with brush icons you can slide
through horizontally just like zbrush for ipad ... modern and minimalist ... i cant even get out of the sculpting mode".
Code: app/ui/forge_sculpt_ui.js (+ the end of forge.css). Test: tests/test_forge_sculpt_ui.py.

## What is on screen while sculpting
| Where | What |
| --- | --- |
| top centre | the SCULPT chip, the brush name, Symmetry X / Y / Z, Dynamic detail, level stepper (< L1/3 >), Remesh, Reduce, Undo / Redo, the matcap, More (every engine setting), **Done** |
| left edge | Size and Strength sliders (Nomad-style), sticky Invert and Smooth toggles (as if Ctrl / Shift were held) |
| bottom | the brush strip: category chips (Favourites, Recent, the engine's categories, All), search, icons that slide sideways (wheel, drag, arrows); right-click = favourite; 1-9 = the first nine favourites |
| right button | the brush wheel at the mouse: the favourites around it; Undo, Divide, Remesh, Frame, All brushes, Exit Sculpt under it; press-drag-release picks, a quick click keeps it open |
| viewport | a thin accent border while sculpting; the poly-count HUD hides |

Leaving: Done, q, F8, Esc, the wheel's Exit Sculpt, Menu Set: Modeling. Keys: d / Shift+d level up / down (d adds a
level at the top), x symmetry X, l lazy mouse, b / m + drag size / strength, Ctrl invert, Shift smooth.

## Research it follows (paraphrased)
- ZBrush for iPad: left toolbar with size / focal / ZAdd-ZSub, a customisable bottom brush strip, a modifier wheel and
  Quick Menu; praised as clean - https://help.maxon.net/zbp/en-us/Content/html/3_interface-and-gestures_canvas-interface-bottom-toolbar.html ,
  https://help.maxon.net/zbp/en-us/Content/html/3_interface-and-gestures_canvas-interface-modifier-wheel.html
- Nomad Sculpt: tall radius / intensity sliders on the left, sticky sub / smooth / mask toggles, hides what does not apply -
  https://nomadsculpt.com/manual/interface , https://nomadsculpt.com/manual/tools
- Blender 4.3 brush assets: a horizontal brush shelf; users missed visible names, an active highlight and per-brush
  shortcuts - https://code.blender.org/2024/07/brush-assets-is-out/ , https://devtalk.blender.org/t/brush-assets-feedback/35498
- Maya sculpt: b / m drag, Ctrl invert, Shift smooth, settings grouped Brush / Stroke / Falloff / Symmetry / Stamp -
  https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Modeling/files/GUID-C53434C7-0A0D-4DF8-BB9A-BF60DE751987.htm
- Look: three neutral greys, one accent, line icons, plain brush names, tooltips with the shortcut.

## Added 2026-10-21 22:30 (owner 22:13: "add those sculpting features ... nothing should ever overlap")
- **Masking**: the Mask toggle (or Ctrl+Shift+drag) paints the engine's mask; masked parts are drawn dark
  (app/ui/forge_sculpt_mask.js: an overlay mesh sharing the sculpt mesh's buffers) and never move. Invert mask
  (Ctrl+Shift+I), Clear mask (Shift+U), Hide masked / Show all (h) - on the left panel and in the right-button wheel.
  C++ fix: mask dabs now report their vertices to the host (core/src/brush.cpp), the worker sends the mask with every
  update (`msk`) and after a mask op (`t: "mask"`).
- **Per-brush hotkeys**: right-click a brush > Set a hotkey (e.g. Shift+P); keys sculpt mode already uses are refused;
  the key shows on the tile.
- **Reorder favourites**: drag a tile onto another (Favourites tab), or right-click > Move left / right.
- **Layout from the free room** (fscLayout): header under the viewport's toolbar and clear of the view cube, sliders
  side by side between header and strip, strip right of the sliders and above any bottom bar - 12 px apart always.
  tests/test_ui_spacing.py checks Home and sculpt mode at 1400x860, 1000x700, 1920x1080 and a 900x1500 vertical monitor.

## Open
- A hotkey editor listing every brush, a sub-ring in the wheel for whole categories, the More panel as a proper Tool
  Settings pane, mask by cavity / by colour, isolate one part (needs separate parts in the engine).
