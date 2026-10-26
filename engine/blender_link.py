"""Blender MCP on both machines (owner 2026-10-26: "get blender mcp going on both").

MCP for Blender (github.com/ahujasid/mcp-for-blender, MIT, vendored in contrib/blender_mcp/) has two halves:
  - an add-on inside Blender that listens on 127.0.0.1:9876 and runs what it is asked (auto-starts with Blender);
  - an MCP server (`uvx mcp-for-blender`) LOKI's agents talk to; it forwards to the add-on.
This module does the Blender half and tells LOKI whether the server half can start:

    python engine/blender_link.py status            # where Blender is, add-on installed?, socket live?
    python engine/blender_link.py setup             # install + enable the add-on in this machine's Blender
    python engine/blender_link.py setup --install   # also install Blender if missing (winget / brew, big files
                                                    #   on the external drive on the Mac)
    python engine/blender_link.py open              # start Blender so the socket is live
    python engine/blender_link.py proof [workspace] # build + render + export a campfire through the add-on

Telemetry stays off (the add-on's consent defaults to off; the server gets DISABLE_TELEMETRY=true from
mcp_servers.json) and the paid generators (Hyper3D, Sketchfab, Hunyuan) are never switched on here.
Standard library only.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON_SRC = ROOT / "contrib" / "blender_mcp" / "addon.py"
STARTUP_SRC = ROOT / "engine" / "blender_scripts" / "loki_blender_startup.py"   # turns the add-on on + file inbox
ADDON_NAME = "blender_mcp"                 # the module name inside Blender's add-ons folder
PORT = int(os.environ.get("BLENDER_PORT", "9876"))
# Mac: the internal drive is full - big installs live on the external drive (Xero, LokiSSD while Xero is away)
MAC_BIG_DRIVES = ("/Volumes/Xero", "/Volumes/LokiSSD")


def candidates(platform: str | None = None, home: Path | None = None) -> list:
    """Places Blender's executable can be, most likely first."""
    platform = platform or sys.platform
    home = Path(home or Path.home())
    found = []
    env = os.environ.get("LOKI_BLENDER")
    if env:
        found.append(env)
    if platform == "darwin":
        for base in ("/Applications",) + tuple(d + "/Applications" for d in MAC_BIG_DRIVES) + (str(home / "Applications"),):
            found += sorted(glob.glob(base + "/Blender*.app/Contents/MacOS/Blender"), reverse=True)
    elif platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                     str(home / "AppData" / "Local" / "Programs")):
            if base:
                found += sorted(glob.glob(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe")), reverse=True)
        found += sorted(glob.glob(str(home / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "blender*.exe")))
    which = shutil.which("blender")
    if which:
        found.append(which)
    out = []
    for f in found:
        if f and f not in out:
            out.append(f)
    return out


def find_blender() -> str:
    for c in candidates():
        if Path(c).is_file():
            return c
    return ""


def socket_live(port: int = PORT, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# the script Blender runs (in the background) to install + enable the add-on and save that choice. It copies the file
# into Blender's own add-ons folder itself (the addon_install operator moved in Blender 4.2's extensions rework).
INSTALL_EXPR = (
    "import bpy, addon_utils, sys, shutil, os\n"
    "src = sys.argv[sys.argv.index('--') + 1]\n"
    "dst = bpy.utils.user_resource('SCRIPTS', path='addons', create=True)\n"
    "shutil.copyfile(src, os.path.join(dst, '%s.py'))\n"
    "start = bpy.utils.user_resource('SCRIPTS', path='startup', create=True)\n"
    "shutil.copyfile(sys.argv[sys.argv.index('--') + 2], os.path.join(start, 'loki_blender.py'))\n"
    "addon_utils.modules_refresh() if hasattr(addon_utils, 'modules_refresh') else None\n"
    "addon_utils.enable('%s', default_set=True, persistent=True)\n"
    "bpy.ops.wm.save_userpref()\n"
    "print('LOKI_BLENDER_ADDON_OK', addon_utils.check('%s'))\n" % (ADDON_NAME, ADDON_NAME, ADDON_NAME))


def _installed_copy(blender: str, run=subprocess.run) -> str:
    """The add-on file Blender would load (empty when not installed). Asks Blender itself where its add-ons live."""
    try:
        proc = run([blender, "--background", "--factory-startup", "--python-expr",
                    "import bpy; print('LOKI_ADDONS', bpy.utils.user_resource('SCRIPTS', path='addons'))"],
                   capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("LOKI_ADDONS "):
            p = Path(line.split(" ", 1)[1].strip()) / (ADDON_NAME + ".py")
            return str(p) if p.is_file() else ""
    return ""


def status(run=subprocess.run) -> dict:
    blender = find_blender()
    return {"blender": blender, "addon": _installed_copy(blender, run) if blender else "",
            "socket": socket_live(), "port": PORT, "uvx": shutil.which("uvx") or "",
            "next": ("install Blender (python engine/blender_link.py setup --install)" if not blender else
                     "open Blender (python engine/blender_link.py open)" if not socket_live() else "ready")}


def install_blender(run=subprocess.run) -> dict:
    """Install Blender with the OS's package manager. Mac: onto the external drive (internal drive is full)."""
    if sys.platform.startswith("win"):
        if not shutil.which("winget"):
            return {"ok": False, "error": "winget is missing - install Blender from blender.org"}
        argv = ["winget", "install", "-e", "--id", "BlenderFoundation.Blender", "--silent",
                "--accept-package-agreements", "--accept-source-agreements"]
    elif sys.platform == "darwin":
        drive = next((d for d in MAC_BIG_DRIVES if Path(d).is_dir()), "")
        if not drive:
            return {"ok": False, "error": "no external drive (Xero / LokiSSD) mounted - not installing on the full "
                                          "internal drive"}
        if not shutil.which("brew"):
            return {"ok": False, "error": "Homebrew is missing - download Blender from blender.org into %s/Applications"
                    % drive}
        (Path(drive) / "Applications").mkdir(exist_ok=True)
        argv = ["brew", "install", "--cask", "blender", "--appdir=%s/Applications" % drive]
    else:
        return {"ok": False, "error": "install Blender with your package manager"}
    proc = run(argv, capture_output=True, text=True, timeout=1800)
    return {"ok": proc.returncode == 0, "log": ((proc.stdout or "") + (proc.stderr or ""))[-800:]}


def setup(install: bool = False, run=subprocess.run) -> dict:
    blender = find_blender()
    if not blender and install:
        res = install_blender(run)
        if not res.get("ok"):
            return res
        blender = find_blender()
    if not blender:
        return {"ok": False, "error": "Blender not found (looked in %s); run with --install or set LOKI_BLENDER"
                % ", ".join(candidates()[:4] or ["the usual places"])}
    if not ADDON_SRC.is_file():
        return {"ok": False, "error": "contrib/blender_mcp/addon.py is missing"}
    proc = run([blender, "--background", "--factory-startup", "--python-expr", INSTALL_EXPR, "--", str(ADDON_SRC), str(STARTUP_SRC)],
               capture_output=True, text=True, timeout=180)
    ok = "LOKI_BLENDER_ADDON_OK" in (proc.stdout or "")
    return {"ok": ok, "blender": blender, "addon": _installed_copy(blender, run) if ok else "",
            "log": "" if ok else ((proc.stdout or "") + (proc.stderr or ""))[-800:],
            "next": "open Blender - the add-on starts its server on port %d by itself" % PORT}


def proof(workspace: str | Path | None = None, run=subprocess.run) -> dict:
    """Make something real through the add-on in this machine's Blender: a low-poly campfire built with the MCP
    commands (engine/blender_scripts/mcp_proof.py), rendered to renders/ and exported to models/ in the workspace."""
    import out_names  # pylint: disable=import-outside-toplevel
    blender = find_blender()
    if not blender:
        return {"ok": False, "error": "Blender not found - python engine/blender_link.py setup --install"}
    ws = Path(workspace or os.environ.get("LOKI_WORKSPACE") or Path.home() / "LOKI Projects" / "Home")
    glb = out_names.path(ws / "models", "campfire blender mcp", "glb")
    png = out_names.path(ws / "renders", "campfire blender mcp", "png")
    script = Path(__file__).resolve().parent / "blender_scripts" / "mcp_proof.py"
    proc = run([blender, "--background", "--factory-startup", "--python", str(script), "--", str(ADDON_SRC), str(glb),
                str(png)], capture_output=True, text=True, timeout=900)
    out = (proc.stdout or "") + (proc.stderr or "")
    line = next((l for l in out.splitlines() if l.startswith("LOKI_PROOF ")), "")
    if not line:
        return {"ok": False, "error": "the proof did not finish", "log": out[-1500:]}
    rep = json.loads(line[len("LOKI_PROOF "):])
    rep["ok"] = Path(rep.get("glb") or "").is_file()
    return rep


def open_blender(blend: str = "", popen=subprocess.Popen) -> dict:
    """Start Blender's window (the add-on only listens with a UI, not in --background)."""
    blender = find_blender()
    if not blender:
        return {"ok": False, "error": "Blender not found - python engine/blender_link.py setup --install"}
    if socket_live():
        return {"ok": True, "already": True, "port": PORT}
    argv = [blender] + ([blend] if blend else [])
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | NEW_PROCESS_GROUP: no console
    else:
        kwargs["start_new_session"] = True
    popen(argv, **kwargs)
    return {"ok": True, "started": blender, "port": PORT}


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "setup":
        res = setup(install="--install" in argv)
    elif cmd == "proof":
        res = proof(next((a for a in argv[2:] if not a.startswith("-")), None))
    elif cmd == "open":
        res = open_blender(next((a for a in argv[2:] if a.endswith(".blend")), ""))
    else:
        res = status()
    print(json.dumps(res, indent=2))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
