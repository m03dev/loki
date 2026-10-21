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

## Open
- Masking (the engine has masks; Forge has no mask display yet), hide / isolate parts, a brush-hotkey editor per brush,
  reordering the strip by drag, a sub-ring in the wheel for whole categories, the More panel as a proper Tool Settings pane.
