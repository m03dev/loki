"""Material Maker (github.com/RodZill4/material-maker, MIT, Rodolphe Suescun and contributors) next to Forge.

Forge's Materials side (app/ui/forge_materials.js) runs Material Maker's own node definitions (.mmg) in the
window; this module finds the real Material Maker app on this computer so a material (.ptex) or a model
(.glb/.obj) can be opened in it - Material Maker reads both from its command line (main_window.gd:
`for a in OS.get_cmdline_args(): ... "ptex", "mmpp" -> do_load_project; "obj", "glb", "gltf", "fbx" -> mesh`).

Where it looks (both platforms): LOKI_MATERIAL_MAKER (a path to the program), then
  macOS:   /Applications/material_maker.app, ~/Applications/material_maker.app (any *aterial*aker*.app)
  Windows: %LOCALAPPDATA%\\Programs, %ProgramFiles%, ~/Downloads, ~/Desktop: material_maker*/material_maker.exe
  both:    harness_data/tools/material_maker*/ (an unzipped release)
Nothing is installed or downloaded by LOKI; the window shows the release page when it is missing.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DOWNLOAD = "https://github.com/RodZill4/material-maker/releases/latest"
RUN = subprocess.Popen     # tests swap this


def _data_dir() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data"))


def _candidates() -> list:
    home = Path.home()
    roots = [_data_dir() / "tools"]
    if sys.platform == "darwin":
        roots += [Path("/Applications"), home / "Applications", home / "Downloads"]
    elif sys.platform == "win32":
        for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / ("Programs" if env == "LOCALAPPDATA" else ""))
        roots += [home / "Downloads", home / "Desktop"]
    else:
        roots += [home / "Applications", home / "Downloads", Path("/opt")]
    return roots


def find() -> str:
    """The Material Maker program to start ('' when it is not on this computer)."""
    explicit = os.environ.get("LOKI_MATERIAL_MAKER", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    for root in _candidates():
        try:
            if not root.is_dir():
                continue
            entries = [p for p in root.iterdir() if "material" in p.name.lower() and "maker" in p.name.lower()]
        except OSError:
            continue
        for p in sorted(entries):
            if sys.platform == "darwin" and p.suffix == ".app":
                return str(p)
            if p.is_dir():
                for name in ("material_maker.exe", "material_maker.x86_64", "material_maker"):
                    if (p / name).is_file():
                        return str(p / name)
            elif p.is_file() and (p.suffix.lower() == ".exe" or os.access(p, os.X_OK)):
                return str(p)
    return ""


def status() -> dict:
    path = find()
    return {"installed": bool(path), "path": path, "download": DOWNLOAD, "licence": "MIT"}


def open_in_mm(file: Path) -> dict:
    """Start Material Maker with this file (a .ptex project, or a .glb/.obj mesh to paint)."""
    exe = find()
    if not exe:
        return {"ok": False, "error": "Material Maker is not installed", "download": DOWNLOAD}
    if sys.platform == "darwin" and exe.endswith(".app"):
        argv = ["open", "-a", exe, "--args", str(file)]
    else:
        argv = [exe, str(file)]
    try:
        RUN(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
    except OSError as exc:
        return {"ok": False, "error": "could not start Material Maker: %s" % exc}
    return {"ok": True, "opened": Path(file).name, "with": exe}
