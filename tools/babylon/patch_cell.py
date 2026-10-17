"""Patch Babylon's CellMaterial so per-instance colours reach the shader (LOKI paints every
thin instance its own colour). Run on a Babylon.js source checkout before gen_shaders.py:

    python tools/babylon/patch_cell.py <Babylon.js checkout>

It rewrites `#ifdef VERTEXCOLOR` around the colour varying / multiply in the two cell shaders
to also accept instance colours. Safe to run twice."""
import pathlib
import sys

NEW = "#if defined(VERTEXCOLOR) || defined(INSTANCESCOLOR) && defined(INSTANCES)"


def patch(root: pathlib.Path) -> int:
    changed = 0
    for name in ("cell.vertex.fx", "cell.fragment.fx"):
        p = root / "packages/dev/materials/src/cell" / name
        text = p.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            # only the colour varying and the colour multiply; the `color` attribute stays as is
            if line.strip() == "#ifdef VERTEXCOLOR" and (nxt.startswith("varying vec4 vColor") or "*= vColor.rgb" in nxt):
                lines[i] = NEW
                changed += 1
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


if __name__ == "__main__":
    n = patch(pathlib.Path(sys.argv[1]))
    print(f"patched {n} colour blocks")
