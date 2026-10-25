"""Vendor three-bvh-csg into app/ui/vendor/three-bvh-csg/ for Forge's Mesh > Booleans (docs/FORGE_BOOLEANS.md).

three-bvh-csg (github.com/gkjohnson/three-bvh-csg, MIT, Garrett Johnson) does CSG on three-mesh-bvh, which Forge
already vendors - so booleans come from a maintained library instead of LOKI's own code (owner 2026-10-25: "isn't there
an open source solution for this ... just copy what works"). It is plain JavaScript, so it runs under LOKI's page CSP
(script-src 'self', no WASM in the window). The upgrade path is Manifold (Apache-2.0, WASM, more robust; needs a
worker with 'wasm-unsafe-eval' like the sculpt worker) - ZIVA_TASKS.md has the build task.

The sources are copied as they are; bare imports are rewritten like tools/vendor_pathtracer.py does ('three' ->
vendor/three/three.module.js, 'three-mesh-bvh' -> vendor/three-mesh-bvh/index.js). Left out: src/workers/,
*.d.ts. Nothing from the clone is executed.

    git clone https://github.com/gkjohnson/three-bvh-csg.git <dir>/csg && git -C <dir>/csg checkout 7f00d37
    python tools/vendor_csg.py --csg <dir>/csg
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vendor_pathtracer as VP  # noqa: E402  (rewrite_imports, check_relative_imports)

DEST = VP.VENDOR / "three-bvh-csg"
SKIP_DIRS = {"workers"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csg", required=True, type=Path)
    a = ap.parse_args(argv)
    src = a.csg / "src"
    if not (src / "index.js").is_file():
        raise SystemExit("not a three-bvh-csg checkout: %s" % a.csg)
    if DEST.exists():
        shutil.rmtree(DEST)
    n = 0
    for f in sorted(src.rglob("*.js")):
        rel = f.relative_to(src)
        if rel.parts[0] in SKIP_DIRS:
            continue
        out = DEST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        text, _ = VP.rewrite_imports(f.read_text(encoding="utf-8"), out)
        out.write_text(text, encoding="utf-8")
        n += 1
    shutil.copy2(a.csg / "LICENSE", DEST / "LICENSE")
    # index.js re-exports the workers too: drop those lines (Forge runs CSG on the main thread)
    idx = DEST / "index.js"
    idx.write_text("".join(l for l in idx.read_text(encoding="utf-8").splitlines(True) if "workers/" not in l), encoding="utf-8")
    bad = VP.check_relative_imports(DEST)
    if bad:
        raise SystemExit("broken imports: %s" % bad[:5])
    print("vendored %d files into %s" % (n, DEST))
    return 0


if __name__ == "__main__":
    sys.exit(main())
