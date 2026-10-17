# LOKI World (game/loki-world) - licence notes

- **Everything in this folder is original LOKI code and content**: GDScript, shaders, the scene,
  the icon. Every model (islands, trees, houses, people, the fox, rabbits, monsters) is built at
  run time from Godot's primitive meshes (BoxMesh, CylinderMesh, SphereMesh, PrismMesh, QuadMesh)
  and one generated ArrayMesh; the HUD icons are drawn with lines and shapes. No textures, fonts,
  sounds or models from anywhere else; nothing is downloaded from a CDN.
- **Third-party assets: none.** If one is ever added it must be CC0 or MIT, and its licence file
  goes next to it here, with a line in this list and in docs/THIRD_PARTY.md.
- **Godot Engine** (the editor and the export templates that run this project) is MIT
  (Copyright (c) 2014-present Godot Engine contributors; Copyright (c) 2007-2014 Juan Linietsky,
  Ariel Manzur). A shipped build (Steam, the web build in app/ui/world_godot/) must carry Godot's
  licence text and its third-party notices: Godot shows them in Help > About > Third-party
  Licenses and in `Engine.get_license_text()` / `Engine.get_copyright_info()`; ship them as
  `LICENSES-godot.txt` next to the exported game.
- The text uses Godot's built-in default font (Open Sans SemiBold, OFL-1.1, part of Godot's
  third-party notices above).
