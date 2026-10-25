"""Set up Forge's Pixal3D / TRELLIS.2 on the computer ComfyUI runs on (the PC).

    python tools/setup_trellis.py                 what is ready, what is missing (ComfyUI at LOKI's Render address)
    python tools/setup_trellis.py install         download every missing model file into ComfyUI's models/ folders
    python tools/setup_trellis.py install --mode trellis2      only what TRELLIS.2 needs (5 files, one model less)
    ... --comfy "C:\\ComfyUI"                      the ComfyUI folder, when LOKI does not find it by itself

ComfyUI itself must be new enough to have the native TRELLIS.2 / Pixal3D nodes (August 2026 or newer): update it
(git pull in its folder, or the desktop app's update) and restart it. On an 8 GB card start it with --lowvram if a
run stops with "out of memory". Engine: engine/forge_trellis.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import forge_trellis  # noqa: E402  pylint: disable=wrong-import-position


def _arg(argv: list, name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main(argv: list) -> int:
    comfy = _arg(argv, "--comfy")
    mode = _arg(argv, "--mode")
    if argv and argv[0] == "install":
        def say(msg, frac=None):
            print("\r%s %s" % (msg, "" if frac is None else "%3d%%" % int(frac * 100)), end="", flush=True)
        try:
            res = forge_trellis.install(None, comfy, mode, progress=say)
        except forge_trellis.TrellisError as exc:
            print(str(exc))
            return 1
        print("\ninstalled: %s\nalready there: %s\ninto: %s" % (", ".join(res["installed"]) or "-",
                                                             ", ".join(res["already"]) or "-", res["comfy_dir"]))
        print("Restart ComfyUI (or refresh it) so it sees the new files.")
        return 0
    st = forge_trellis.status()
    print("ComfyUI: %s - %s" % (st["url"], "reachable" if st["reachable"] else st.get("error", "not reachable")))
    if st["reachable"] and not st["nodes_ok"]:
        print(st.get("error"))
    for m, info in st["modes"].items():
        print("  %-9s %s%s" % (m, "ready" if info["ready"] else "not ready",
                               (" - missing " + ", ".join(info["missing"])) if info["missing"] else ""))
    print("ComfyUI folder on this computer: %s" % (st["comfy_dir"] or "not found (use --comfy)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
