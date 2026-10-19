# anyCreature (vendored)

The ACS engine and the front/side/top/hero view renderer from **anyCreature** by Ariescar.

- Upstream: https://github.com/Ariescar/anyCreature
- Version: 1.3.2 (commit `88041c1efb316370dd78963f422decd854fd9067`)
- Licence: **MIT** - the full upstream text is kept beside this file as `LICENSE`.
- Vendored 2026-10-18, byte-for-byte unchanged from the `main` branch.

What is here:
- `engine/` - the zero-dependency Node compiler: `node engine/cli.js <spec.json> <out.glb>`
  compiles one JSON spec into a skinned, animated, vertex-coloured GLB.
- `harness/outline.py` - the pure-Python software rasteriser that draws the FRONT / SIDE / TOP /
  HERO silhouettes the quality gates judge (no browser, no GPU).
- `example/wolf.json` - the worked example spec.

Nothing else from upstream is copied. LOKI's own glue around it lives outside this folder.
