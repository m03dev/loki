"""LOKI and Blender, on both machines (owner 2026-10-26: "get blender mcp going on both ... make it work i dont wanna be
coming back to blender").

Three files go into the machine's Blender once (setup), into Blender's own user scripts folder:
  scripts/startup/loki_blender.py      the loader (engine/blender_scripts/loki_blender_startup.py) - never changes
  scripts/loki/loki_blender_core.py    the core - jobs, the MCP watchdog; hot-reloaded when the file changes
  scripts/addons/blender_mcp.py        MCP for Blender (github.com/ahujasid/mcp-for-blender, MIT, contrib/blender_mcp)
In an open Blender the core runs jobs from ~/LOKI Projects/Home/blender/inbox and keeps the MCP add-on + its socket
(9876, for LOKI's "blender" MCP server) on. run() uses that window when it is alive, else a background Blender
(engine/blender_scripts/run_job.py) - so LOKI never needs the owner to open Blender.

    python engine/blender_link.py status
    python engine/blender_link.py setup [--install]      # --install: winget / brew (Mac: onto the external drive)
    python engine/blender_link.py update                  # copy the core again (a running Blender reloads it)
    python engine/blender_link.py proof [workspace]       # a campfire: built, rendered, exported - the check
    python engine/blender_link.py open

Telemetry stays off; the paid generators (Hyper3D, Sketchfab, Hunyuan) are never switched on. Standard library only.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "engine" / "blender_scripts"
ADDON_SRC = ROOT / "contrib" / "blender_mcp" / "addon.py"
STARTUP_SRC = SCRIPTS / "loki_blender_startup.py"
CORE_SRC = SCRIPTS / "loki_blender_core.py"
RUNNER_SRC = SCRIPTS / "run_job.py"
ADDON_NAME = "blender_mcp"
PORT = int(os.environ.get("BLENDER_PORT", "9876"))
WINDOW_FRESH_S = 20          # status.json newer than this = a Blender window with LOKI's loader is running
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


def inbox_root() -> Path:
    return Path(os.environ.get("LOKI_BLENDER_INBOX") or (Path.home() / "LOKI Projects" / "Home" / "blender"))


def window_status() -> dict:
    """The open Blender's status.json, with "fresh" true when its loader wrote it in the last WINDOW_FRESH_S."""
    try:
        st = json.loads((inbox_root() / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fresh": False}
    st["fresh"] = bool(st.get("alive")) and not st.get("background") and time.time() - float(st.get("at") or 0) < WINDOW_FRESH_S
    return st


# ----------------------------------------------------------------------------- install
# Runs inside Blender (background): copies the three files into Blender's own user scripts folder, turns the add-on
# on and saves that. Blender is asked where its folders are, so this is right for every version and both OSes.
INSTALL_EXPR = (
    "import bpy, addon_utils, sys, shutil, os\n"
    "addon, loader, core = sys.argv[sys.argv.index('--') + 1:][:3]\n"
    "base = bpy.utils.user_resource('SCRIPTS', create=True)\n"
    "for sub, src, name in (('addons', addon, 'blender_mcp.py'), ('startup', loader, 'loki_blender.py'),\n"
    "                       ('loki', core, 'loki_blender_core.py')):\n"
    "    os.makedirs(os.path.join(base, sub), exist_ok=True)\n"
    "    shutil.copyfile(src, os.path.join(base, sub, name))\n"
    "addon_utils.modules_refresh() if hasattr(addon_utils, 'modules_refresh') else None\n"
    "addon_utils.enable('blender_mcp', default_set=True, persistent=True)\n"
    "bpy.ops.wm.save_userpref()\n"
    "print('LOKI_BLENDER_SCRIPTS', base)\n"
    "print('LOKI_BLENDER_ADDON_OK', addon_utils.check('blender_mcp'))\n")


def _scripts_dir(blender: str, run=subprocess.run) -> str:
    """Blender's user scripts folder (asked from Blender itself)."""
    try:
        proc = run([blender, "--background", "--factory-startup", "--python-expr",
                    "import bpy; print('LOKI_SCRIPTS', bpy.utils.user_resource('SCRIPTS'))"],
                   capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    line = next((l for l in (proc.stdout or "").splitlines() if l.startswith("LOKI_SCRIPTS ")), "")
    return line.split(" ", 1)[1].strip() if line else ""


def status(run=subprocess.run) -> dict:
    blender = find_blender()
    base = _scripts_dir(blender, run) if blender else ""
    have = {n: bool(base) and (Path(base) / sub / n).is_file() for sub, n in
            (("addons", "blender_mcp.py"), ("startup", "loki_blender.py"), ("loki", "loki_blender_core.py"))}
    win = window_status()
    return {"blender": blender, "scripts": base, "installed": have, "window": win, "socket": socket_live(),
            "uvx": shutil.which("uvx") or "",
            "next": ("install Blender: python engine/blender_link.py setup --install" if not blender else
                     "python engine/blender_link.py setup" if not all(have.values()) else "ready")}


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
    for src in (ADDON_SRC, STARTUP_SRC, CORE_SRC):
        if not src.is_file():
            return {"ok": False, "error": "%s is missing" % src}
    proc = run([blender, "--background", "--factory-startup", "--python-expr", INSTALL_EXPR, "--", str(ADDON_SRC),
                str(STARTUP_SRC), str(CORE_SRC)], capture_output=True, text=True, timeout=180)
    out = proc.stdout or ""
    ok = "LOKI_BLENDER_ADDON_OK" in out
    base = next((l.split(" ", 1)[1].strip() for l in out.splitlines() if l.startswith("LOKI_BLENDER_SCRIPTS ")), "")
    return {"ok": ok, "blender": blender, "scripts": base,
            "log": "" if ok else (out + (proc.stderr or ""))[-1200:],
            "next": "open Blender once - from then on the core updates itself when its file changes"}


def update(run=subprocess.run) -> dict:
    """Copy the core again: a Blender window running LOKI's loader picks it up within seconds, no restart."""
    blender = find_blender()
    base = _scripts_dir(blender, run) if blender else ""
    if not base:
        return {"ok": False, "error": "Blender not found or not set up - python engine/blender_link.py setup"}
    dst = Path(base) / "loki" / "loki_blender_core.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CORE_SRC, dst)
    return {"ok": True, "core": str(dst)}


# ----------------------------------------------------------------------------- running jobs
def run(commands: list, name: str = "", timeout: float = 900, run_proc=subprocess.run, sleep=time.sleep,
        prefer_window: bool = True) -> dict:
    """Run LOKI Blender commands (see loki_blender_core.py): in the open Blender window when LOKI's loader is alive
    there (the owner sees it happen), else in a background Blender. Returns the core's answer."""
    name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (name or "job"))[:40] + "-" + uuid.uuid4().hex[:6]
    root = inbox_root()
    if prefer_window and window_status().get("fresh"):
        (root / "inbox").mkdir(parents=True, exist_ok=True)
        part = root / "inbox" / (name + ".json.part")
        part.write_text(json.dumps(commands), encoding="utf-8")
        os.replace(part, root / "inbox" / (name + ".json"))
        answer = root / "outbox" / (name + ".json")
        t_end = time.time() + timeout
        while time.time() < t_end:
            if answer.is_file():
                try:
                    res = json.loads(answer.read_text(encoding="utf-8"))
                    res["via"] = "window"
                    return res
                except ValueError:
                    pass
            if (root / "inbox" / (name + ".json")).exists() and not window_status().get("fresh"):
                break                                      # the window closed before it took the job
            sleep(0.5)
        job = root / "inbox" / (name + ".json")
        if job.exists():                                   # never taken: run it in the background instead
            try:
                job.unlink()
            except OSError:
                pass
        elif not answer.is_file():
            return {"ok": False, "error": "Blender took the job but gave no answer in %ds" % timeout, "via": "window"}
    blender = find_blender()
    if not blender:
        return {"ok": False, "error": "Blender not found - python engine/blender_link.py setup --install"}
    with tempfile.TemporaryDirectory(prefix="loki-blender-") as tmp:
        job = Path(tmp) / (name + ".json")
        ans = Path(tmp) / (name + ".answer.json")
        job.write_text(json.dumps(commands), encoding="utf-8")
        try:
            proc = run_proc([blender, "--background", "--factory-startup", "--python", str(RUNNER_SRC), "--",
                             str(CORE_SRC), str(job), str(ans)], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "background Blender ran over %ds" % timeout, "via": "background"}
        if not ans.is_file():
            return {"ok": False, "error": "background Blender gave no answer",
                    "log": ((proc.stdout or "") + (proc.stderr or ""))[-1500:], "via": "background"}
        res = json.loads(ans.read_text(encoding="utf-8"))
        res["via"] = "background"
        return res


def build_render_export(code: str, scene: str, out_dir: Path, stem: str, width: int = 1280, height: int = 720,
                        formats=("glb", "blend"), **kw) -> dict:
    """The usual making job: run `code` into its own scene, render a still, export the model. Files are named by
    engine/out_names.py into renders/ and models/ of out_dir."""
    import out_names  # pylint: disable=import-outside-toplevel
    png = out_names.path(Path(out_dir) / "renders", stem, "png")
    files = [out_names.path(Path(out_dir) / "models", stem, f) for f in formats]
    commands = [{"type": "python", "params": {"code": code, "scene": scene}},
                {"type": "scene_info", "params": {"scene": scene}},
                {"type": "render", "params": {"scene": scene, "path": str(png), "width": width, "height": height}}]
    commands += [{"type": "export", "params": {"scene": scene, "path": str(f)}} for f in files]
    res = run(commands, name=stem, **kw)
    res["files"] = {"render": str(png), "models": [str(f) for f in files]}
    return res


def polish(model: str | Path, out_dir: str | Path, name: str = "", size: float = 2.0, target: int = 20000,
           style: str = "studio", lods=(1.0, 0.5, 0.2), turntable: int = 0, remesh: float = 0.0, edits=None,
           formats=("glb", "gltf", "fbx", "blend"), repair: bool = True, symmetric: bool = False, **kw) -> dict:
    """AI model (or a free asset + `edits`) -> finished asset, in its own scene: import, cleanup, normalize (size m),
    [voxel remesh], [remix edits], decimate to `target` triangles, UVs only where missing (an AI model's own UVs carry
    its texture), smooth shading, a staged render, every format in `formats` (.glb, a .gltf folder, .fbx, .blend), LODs,
    optional turntable - and the sidecar Forge and Home read (models/.meta/<name>.glb.json: the render as its picture,
    triangles, formats, where it came from, licence / no_training carried over). Checked on the PC 2026-10-26
    (Blender 5.2.3): a Forge character 32.8k -> 20k triangles with its textures; a Poly Haven cannon remixed."""
    import out_names  # pylint: disable=import-outside-toplevel
    model, out_dir = Path(model), Path(out_dir)
    free = is_free_asset(model)
    if free and not edits:
        return {"ok": False, "error": "%s is a free asset (%s): change it first - give edits (tint, lowpoly, taper, "
                                      "bend, twist, displace, bevel, scale, material). Free assets are never used as "
                                      "they are." % (model.name, free)}
    stem_text = name or out_names.display_name(model.name) + (" remix" if free else " polished")
    sc = ("LOKI " + stem_text)[:60]
    png = out_names.path(out_dir / "renders", stem_text, "png")
    glb = out_names.path(out_dir / "models", stem_text, "glb")
    stem = glb.with_suffix("")
    outs = {"glb": glb, "gltf": Path(str(stem) + "_gltf") / (stem.name + ".gltf"), "fbx": stem.with_suffix(".fbx"),
            "blend": stem.with_suffix(".blend")}
    cmds = [{"type": "clear", "params": {"scene": sc}},
            {"type": "import", "params": {"scene": sc, "path": str(model)}},
            {"type": "cleanup", "params": {"scene": sc}},
            {"type": "normalize", "params": {"scene": sc, "size": size}}]
    if repair:                                   # AI garbage -> clean surface; its colours baked across when rebuilt
        cmds += [{"type": "repair", "params": {"scene": sc, "symmetric": bool(symmetric)}},
                 {"type": "bake", "params": {"scene": sc, "size": 2048, "folder": str(out_dir / "models" / "textures")}}]
    if remesh:
        cmds.append({"type": "remesh", "params": {"scene": sc, "voxel": remesh}})
    if edits:
        cmds.append({"type": "remix", "params": {"scene": sc, "edits": list(edits)}})
    cmds += [{"type": "decimate", "params": {"scene": sc, "target": target}},
             {"type": "uv", "params": {"scene": sc, "mode": "missing"}},
             {"type": "shade", "params": {"scene": sc}},
             {"type": "stage", "params": {"scene": sc, "style": style}},
             {"type": "render", "params": {"scene": sc, "path": str(png), "width": 1280, "height": 1280}}]
    cmds += [{"type": "export", "params": {"scene": sc, "path": str(outs[f])}} for f in formats if f in outs]
    if lods:
        cmds.append({"type": "lods", "params": {"scene": sc, "stem": str(stem), "ratios": list(lods)}})
    if turntable:
        cmds.append({"type": "turntable", "params": {"scene": sc, "frames": int(turntable),
                                                     "folder": str(png.with_suffix("")) + "_turntable"}})
    cmds.append({"type": "scene_info", "params": {"scene": sc}})
    res = run(cmds, name=stem_text, **kw)
    res["files"] = {"render": str(png), "models": [str(outs[f]) for f in formats if f in outs]}
    if turntable and res.get("ok"):
        res["files"]["turntable"] = turntable_mp4(Path(str(png.with_suffix("")) + "_turntable"))
    rep = next((r.get("result") for r in res.get("results", []) if r.get("type") == "repair"), None)
    if rep:
        res["quality"] = {"verdict": rep.get("verdict"),
                          "problems": sorted({p for v in (rep.get("objects") or {}).values() for p in v.get("problems", [])})}
    if res.get("ok"):
        info = next((r.get("result") for r in res.get("results", []) if r.get("type") == "scene_info"), {}) or {}
        if rep:
            info = dict(info, quality=res["quality"])
        write_sidecar(glb, out_dir, png, model, info, [f for f in formats if f in outs], free, edits)
    return res


def is_free_asset(path: Path) -> str:
    """'polyhaven/cannon_01' when `path` is a downloaded free asset (engine/free_assets.py), else ''."""
    p = Path(path)
    for d in [p.parent] + list(p.parents)[:3]:
        side = d / "loki_asset.json"
        if side.is_file():
            try:
                info = json.loads(side.read_text(encoding="utf-8"))
                return "%s/%s" % (info.get("source", "?"), info.get("id", d.name))
            except ValueError:
                return d.name
    return ""


def write_sidecar(glb: Path, out_dir: Path, png: Path, source: Path, info: dict, formats: list, free: str = "",
                  edits=None) -> Path:
    """models/.meta/<name>.glb.json - what Forge's list and Home's preview read (forge3d.list_models)."""
    meta_dir = Path(glb).parent / ".meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    src_meta = {}
    try:
        src_meta = json.loads((Path(source).parent / ".meta" / (Path(source).name + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        image = Path(png).resolve().relative_to(Path(out_dir).resolve()).as_posix()
    except ValueError:
        image = str(png)
    meta = {"prompt": src_meta.get("prompt") or "", "backend": "blender polish",
            "made_from": src_meta.get("backend") or ("free asset " + free if free else "imported model"),
            "source": str(source), "image": image, "triangles": int(info.get("triangles") or 0),
            "formats": formats, "t": time.time(), "quality": info.get("quality")}
    for k in ("licence", "licence_url", "no_training"):
        if src_meta.get(k):
            meta[k] = src_meta[k]
    if free:
        meta.update(free_asset=free, edits=[e.get("op") for e in (edits or [])],
                    licence=meta.get("licence") or "made from a CC0 asset, changed by LOKI")
    side = meta_dir / (Path(glb).name + ".json")
    side.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return side


def convert(path: str | Path, to: str, out_dir: str | Path | None = None, **kw) -> dict:
    """One model file -> another format (fbx, gltf, glb, obj, blend) through Blender (window or background); the new
    file goes beside the old one with the same name. Forge's Export uses it for FBX."""
    path = Path(path)
    to = str(to).lower().lstrip(".")
    if to not in ("fbx", "gltf", "glb", "obj", "blend"):
        return {"ok": False, "error": "convert to fbx, gltf, glb, obj or blend"}
    if not path.is_file():
        return {"ok": False, "error": "no such file: %s" % path.name}
    out_dir = Path(out_dir or path.parent)
    target = (out_dir / (path.stem + "_gltf") / (path.stem + ".gltf")) if to == "gltf" else out_dir / (path.stem + "." + to)
    if target.exists():
        target = target.with_name(target.stem + "_%s%s" % (time.strftime("%H%M%S"), target.suffix))
    sc = ("LOKI convert " + path.stem)[:60]
    res = run([{"type": "clear", "params": {"scene": sc}}, {"type": "import", "params": {"scene": sc, "path": str(path)}},
               {"type": "export", "params": {"scene": sc, "path": str(target)}},
               {"type": "clear", "params": {"scene": sc}}], name="convert " + path.stem, **kw)
    res["file"] = str(target) if Path(target).is_file() else ""
    if res.get("ok") and not res["file"]:
        res.update(ok=False, error="Blender wrote nothing")
    return res


def turntable_mp4(folder: Path, fps: int = 24) -> str:
    """frame_0001.png ... -> <folder>.mp4 with ffmpeg when it is installed ("" otherwise; the frames stay)."""
    ff = shutil.which("ffmpeg")
    if not ff or not any(Path(folder).glob("frame_*.png")):
        return ""
    out = Path(str(folder) + ".mp4")
    proc = subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(Path(folder) / "frame_%04d.png"),
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "veryfast", str(out)],
                          capture_output=True, text=True, timeout=300)
    return str(out) if proc.returncode == 0 and out.is_file() else ""


def proof(workspace: str | Path | None = None, **kw) -> dict:
    """The check: a low-poly campfire made from scratch (engine/blender_scripts/campfire.py), rendered and exported."""
    ws = Path(workspace or os.environ.get("LOKI_WORKSPACE") or Path.home() / "LOKI Projects" / "Home")
    return build_render_export((SCRIPTS / "campfire.py").read_text(encoding="utf-8"), "LOKI Campfire", ws,
                               "campfire blender", **kw)


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


# ----------------------------------------------------------------------------- the tool LOKI's agents use
TOOL = {"name": "blender",
        "description": "Make 3D in Blender (no window needed; the open Blender is used when LOKI's loader runs in it). "
                       "action=make: `code` is Blender Python building into `scene` (given as the variable scene; "
                       "bpy, bmesh ready; build with bpy.data / bmesh, link objects to scene.collection, set "
                       "scene.camera) - then it is rendered to renders/ and exported to models/ (.glb + .blend), named "
                       "after `name`. action=run: `commands` = a list of {type: python|render|export|scene_info, "
                       "params} - toolkit types: import, cleanup, normalize, decimate, remesh, uv, shade, stage, "
                       "render, export, lods, turntable, scene_info, clear. action=polish: `path` = an AI model "
                       "(.glb/.obj/.fbx from make_3d) -> cleaned, sized, decimated to `target` tris, staged render "
                       "+ .glb, .gltf, .fbx, .blend + LODs (+ `turntable` frames -> mp4); shows in Home as a 3D model and "
                       "opens in Forge. FREE ASSETS (assets/ from free_assets) MUST be changed: give `edits` "
                       "[{op: tint|lowpoly|taper|bend|twist|displace|bevel|scale|material, ...}] - without edits it is "
                       "refused. action=status: is Blender there.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["make", "run", "polish", "status"]},
            "path": {"type": "string"}, "target": {"type": "integer"}, "turntable": {"type": "integer"},
            "edits": {"type": "array", "items": {"type": "object"}},
            "style": {"type": "string", "enum": ["studio", "night", "outdoor"]},
            "name": {"type": "string"}, "code": {"type": "string"}, "scene": {"type": "string"},
            "width": {"type": "integer"}, "height": {"type": "integer"},
            "commands": {"type": "array", "items": {"type": "object"}}}, "required": ["action"]}}


def tool(args: dict, cwd: Path) -> dict:
    a = args or {}
    act = str(a.get("action") or "make")
    if act == "status":
        return {"ok": True, **status()}
    if act == "run":
        return run(list(a.get("commands") or []), name=str(a.get("name") or "run"))
    if act == "polish":
        p = Path(str(a.get("path") or ""))
        p = p if p.is_absolute() else Path(cwd) / p
        if not p.is_file():
            return {"ok": False, "error": "no model at %s (path= a .glb/.obj/.fbx in this folder)" % p}
        res = polish(p, Path(cwd), str(a.get("name") or ""), target=int(a.get("target") or 20000),
                     style=str(a.get("style") or "studio"), turntable=int(a.get("turntable") or 0),
                     edits=a.get("edits") if isinstance(a.get("edits"), list) else None)
        if res.get("ok"):
            res["made"] = [x for x in [res["files"]["render"]] + res["files"]["models"] + [res["files"].get("turntable", "")]
                           if x and Path(x).is_file()]
        return res
    code = str(a.get("code") or "")
    if not code.strip():
        return {"ok": False, "error": "give the Blender Python that builds the model (code)"}
    name = str(a.get("name") or "model")
    res = build_render_export(code, str(a.get("scene") or ("LOKI " + name)[:60]), Path(cwd), name,
                              int(a.get("width") or 1280), int(a.get("height") or 720))
    if res.get("ok"):
        res["made"] = [p for p in [res["files"]["render"]] + res["files"]["models"] if Path(p).is_file()]
    return res


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "setup":
        res = setup(install="--install" in argv)
    elif cmd == "update":
        res = update()
    elif cmd == "proof":
        res = proof(next((x for x in argv[2:] if not x.startswith("-")), None))
    elif cmd == "open":
        res = open_blender(next((x for x in argv[2:] if x.endswith(".blend")), ""))
    else:
        res = status()
    print(json.dumps(res, indent=2, default=str))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
