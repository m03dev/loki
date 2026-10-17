# Rebuilding LOKI's Babylon.js

`app/ui/vendor/babylon/babylon.loki.js` is Babylon.js 8.9.1 (Apache-2.0), built from source
with only what LOKI World needs. It is checked in, so nobody has to rebuild it to run LOKI.
No CDN: the UI's CSP allows only `script-src 'self'`.

1. `git clone --depth 1 --branch 8.9.1 https://github.com/BabylonJS/Babylon.js bsrc`
2. `python tools/babylon/patch_cell.py bsrc` (CellMaterial takes per-instance colours)
3. `python tools/babylon/gen_shaders.py bsrc/packages/dev` (turns the `.fx` shaders into `.ts`,
   the same as Babylon's own buildShaders tool)
4. Bundle `tools/babylon/entry.ts` with esbuild (tsconfig `experimentalDecorators: true`):

       esbuild tools/babylon/entry.ts --bundle --minify --format=iife --ignore-annotations \
         --external:draco3dgltf --alias:core=bsrc/packages/dev/core/src \
         --alias:materials=bsrc/packages/dev/materials/src --outfile=app/ui/vendor/babylon/babylon.loki.js

   `--ignore-annotations` matters: the materials package says `sideEffects: false`, which
   would drop the shader registrations.
5. Run `python tools/ship.py --check`. tests/test_portal.py checks that the world loads it lazily.
