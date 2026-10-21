"""Vendor three-gpu-pathtracer and three-mesh-bvh into app/ui/vendor/ for Forge's Render (docs/FORGE_RENDER.md).

Both are MIT, by Garrett Johnson (github.com/gkjohnson). LOKI's page CSP is script-src 'self' with no import map and
no eval, so the ES-module sources are copied as they are and every bare import is rewritten to a relative path:

    'three'                          -> app/ui/vendor/three/three.module.js
    'three/examples/jsm/<x>' and
    'three/addons/<x>'               -> app/ui/vendor/three/addons/<x>
    'three-mesh-bvh'                 -> app/ui/vendor/three-mesh-bvh/index.js

What is left out (not used by the WebGL path tracer, and each would pull a dependency LOKI does not vendor):
    both: src/webgpu/ (the WebGPU / TSL versions), *.d.ts typings
    pathtracer: src/utils/UVUnwrapper.js (needs xatlas-web + a .wasm file; not exported by src/index.js)
    three-mesh-bvh: src/workers/ (Web Workers built from import.meta.url; Forge builds the BVH on the main thread)

three-mesh-bvh keeps some code as `*.template.js` and expands each one into a `.generated.js` (direct) and an
`_indirect.generated.js` file with rollup + the `preprocess` npm package at build time. npm is not used here: the
three directives those templates use (`/* @if INDIRECT */ ... /* @else */ ... /* @endif */` and
`/* @echo INDIRECT_STRING */`) are expanded by `expand_template` below, which does the same thing.

Nothing from the downloaded repositories is executed (no npm install, no build scripts) - this only reads files.

    git clone https://github.com/gkjohnson/three-gpu-pathtracer.git <dir>/gpt && git -C <dir>/gpt checkout v0.0.27
    git clone https://github.com/gkjohnson/three-mesh-bvh.git <dir>/bvh && git -C <dir>/bvh checkout v0.9.16
    python tools/vendor_pathtracer.py --pathtracer <dir>/gpt --bvh <dir>/bvh
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "app" / "ui" / "vendor"
THREE = VENDOR / "three"
DEST_PT = VENDOR / "pathtracer"
DEST_BVH = VENDOR / "three-mesh-bvh"

SKIP_PT = {"utils/UVUnwrapper.js"}

# The only edits to the upstream code (API drift against three r187dev; listed in docs/FORGE_RENDER.md, "Patches").
# Each must match exactly once, or the script stops so a new upstream version is looked at by hand.
PATCHES = [
    ("pathtracer/uniforms/EquirectHdrInfoUniform.js",
     "HalfFloatType, Source, RepeatWrapping", "HalfFloatType, TextureSource, RepeatWrapping",
     "three r186 renamed Source to TextureSource (the old name only warns)"),
    ("pathtracer/uniforms/EquirectHdrInfoUniform.js",
     "map.source = new Source( { ...map.image } );", "map.source = new TextureSource( { ...map.image } );",
     "three r186 renamed Source to TextureSource (the old name only warns)"),
    ("pathtracer/core/PathTracingSceneGenerator.js",
     "maxLeafTris: 1,", "targetLeafSize: 1,",
     "three-mesh-bvh 0.9 renamed maxLeafTris to targetLeafSize (the old name only warns)"),
]
SKIP_DIRS = {"webgpu", "workers"}
IMPORT_RE = re.compile(r"""(\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])([^'"]+)\2""")
IF_RE = re.compile(r"/\*\s*@if\s+INDIRECT\s*\*/(.*?)/\*\s*@else\s*\*/(.*?)/\*\s*@endif\s*\*/", re.S)
ECHO_RE = re.compile(r"/\*\s*@echo\s+INDIRECT_STRING\s*\*/")


def rel(from_file: Path, to: Path) -> str:
    r = os.path.relpath(to, from_file.parent).replace(os.sep, "/")
    return r if r.startswith(".") else "./" + r


def rewrite_imports(text: str, out_file: Path) -> tuple[str, list]:
    """Turn every bare specifier into a relative path; return the new text and the specifiers that were changed."""
    changed = []

    def sub(m):
        spec = m.group(3)
        target = None
        if spec == "three":
            target = THREE / "three.module.js"
        elif spec.startswith("three/examples/jsm/"):
            target = THREE / "addons" / spec[len("three/examples/jsm/"):]
        elif spec.startswith("three/addons/"):
            target = THREE / "addons" / spec[len("three/addons/"):]
        elif spec == "three-mesh-bvh":
            target = DEST_BVH / "index.js"
        elif not spec.startswith("."):
            raise SystemExit("unexpected bare import %r in %s" % (spec, out_file))
        if target is None:
            return m.group(0)
        if not target.is_file() and target.parent != DEST_BVH:
            raise SystemExit("%s imports %s, which is not vendored (%s)" % (out_file, spec, target))
        changed.append(spec)
        return m.group(1) + m.group(2) + rel(out_file, target) + m.group(2)

    # line by line, leaving // and * comment lines alone (a TODO that mentions "three/webgpu" is not an import)
    out = []
    for line in text.split("\n"):
        s = line.lstrip()
        out.append(line if s.startswith("//") or (s.startswith("*") and not s.startswith("*/")) else IMPORT_RE.sub(sub, line))
    return "\n".join(out), changed


def expand_template(text: str, indirect: bool, name: str) -> str:
    """The rollup-templating step of three-mesh-bvh, without npm: keep one branch of each @if INDIRECT block."""
    body = IF_RE.sub(lambda m: m.group(1) if indirect else m.group(2), text)
    body = ECHO_RE.sub("_indirect" if indirect else "", body)
    if "@if" in body or "@else" in body or "@endif" in body or "@echo" in body:
        raise SystemExit("template directive left unexpanded in " + name)
    stars = "*" * len(name)
    return ("/***********************************%s/\n/* This file is generated from the template \"%s\". */\n"
            "/***********************************%s/\n" % (stars, name, stars)) + body


def wanted(rel_path: str, skip: set) -> bool:
    parts = rel_path.split("/")
    return (rel_path.endswith(".js") and not rel_path.endswith(".d.ts") and rel_path not in skip
            and not (set(parts[:-1]) & SKIP_DIRS))


def vendor(src: Path, dest: Path, skip: set, templates: bool) -> dict:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files, rewrites = 0, 0
    for p in sorted((src / "src").rglob("*.js")):
        r = p.relative_to(src / "src").as_posix()
        if not wanted(r, skip):
            continue
        text = p.read_text(encoding="utf-8")
        outs = []
        if templates and r.endswith(".template.js"):
            base = r[: -len(".template.js")]
            outs = [(base + ".generated.js", expand_template(text, False, p.name)),
                    (base + "_indirect.generated.js", expand_template(text, True, p.name))]
        else:
            outs = [(r, text)]
        for out_rel, body in outs:
            out = dest / out_rel
            out.parent.mkdir(parents=True, exist_ok=True)
            body, changed = rewrite_imports(body, out)
            rewrites += len(changed)
            out.write_text(body, encoding="utf-8", newline="\n")
            files += 1
    shutil.copyfile(src / "LICENSE", dest / "LICENSE")
    pkg = json.loads((src / "package.json").read_text(encoding="utf-8"))
    return {"name": pkg["name"], "version": pkg["version"], "files": files, "rewrites": rewrites}


def check_relative_imports(dest: Path) -> list:
    """Every relative import must point at a file that exists after the copy."""
    missing = []
    for p in dest.rglob("*.js"):
        for m in IMPORT_RE.finditer(p.read_text(encoding="utf-8")):
            spec = m.group(3)
            if spec.startswith(".") and not (p.parent / spec).resolve().is_file():
                missing.append("%s -> %s" % (p.relative_to(VENDOR), spec))
    return missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pathtracer", required=True, type=Path, help="a checkout of gkjohnson/three-gpu-pathtracer")
    ap.add_argument("--bvh", required=True, type=Path, help="a checkout of gkjohnson/three-mesh-bvh")
    a = ap.parse_args(argv)
    if not (THREE / "three.module.js").is_file():
        print("app/ui/vendor/three/three.module.js is missing", file=sys.stderr)
        return 1
    b = vendor(a.bvh, DEST_BVH, set(), True)
    t = vendor(a.pathtracer, DEST_PT, SKIP_PT, False)
    for f, old, new, why in PATCHES:
        p = VENDOR / f
        text = p.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print("patch no longer applies (%s): %s" % (why, f), file=sys.stderr)
            return 1
        p.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
        print("patched %s: %s" % (f, why))
    missing = check_relative_imports(DEST_BVH) + check_relative_imports(DEST_PT)
    for x in (b, t):
        print("%s %s: %d files, %d imports rewritten" % (x["name"], x["version"], x["files"], x["rewrites"]))
    if missing:
        print("broken relative imports:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
