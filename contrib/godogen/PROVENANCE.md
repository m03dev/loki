# Godogen in LOKI

- Source: https://github.com/htdt/godogen (Alex Ermolov), MIT License (LICENSE.md here).
- Copied verbatim from commit `40542b6c8efbdc40112c2b004fbaa6d67141846d` (2026-10-16):
  `prompts/runtime.md`, `engines/*.md` (godot, godot-gdscript, bevy, babylon, threejs) and the
  whole `asset-gen/` skill (SKILL.md, api.md, motion.md, rembg.md, tools/*.py, tools/requirements.txt).
- Not copied: `publish.sh`, `scripts/render_dir.py`, `scripts/generate_codex_metadata.py` - their
  logic is ported to Python in `engine/godogen.py` (publish, render_dir, codex_metadata) so it runs
  on Windows too and never through a shell.
- LOKI never runs these files itself. `make_godot_game` copies them (with the `${...}` tokens
  filled in) into the game folder `~/LOKI Projects/<name>`, and the coding agent that builds the
  game reads them there; the asset-gen `tools/*.py` run inside that game folder, by that agent,
  with the job's approvals.
- Updating: copy the same files from a newer godogen commit, update the commit above, run
  `python tests/test_godogen.py`.
