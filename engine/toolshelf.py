"""The Tool Shelf: open-source game-dev tools LOKI installs and runs on request (owner 2026-10-25: "add all the tools").

Every tool is a recipe in engine/toolshelf/*.json (schema: docs/TOOLSHELF.md) - checked against its repo: licence,
weights' licence, how it installs, and the exact command lines LOKI runs. A tool lives in its own folder
<data>/tools/<id>/ with its own Python venv when it needs pip (so one tool's torch never breaks another's, or LOKI's),
its git clone in src/, release binaries in bin/, npm packages in node_modules/, model files in models/.

    shelf()                      every recipe, with installed / runnable here
    install(id, progress=)       pip | git | git-pip | release | npm | comfyui | manual - then `after` steps and models
    run(id, action, args, ws)    one action: the command template filled in, files checked to be inside the workspace,
                                 outputs made in the workspace; -> {ok, outputs, log}
    tool(args, ws, ask)          LOKI's "toolshelf" tool: list | info | install (asks the owner) | run | remove

Nothing runs through a shell: commands are argument lists. Installing downloads and runs other people's code, so the
owner allows each install first; running an installed tool on the workspace's files does not ask again.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
RECIPES = HERE / "toolshelf"
AREAS = ("audio", "2d", "3d", "animation", "video", "marketing", "godot")


class ShelfError(RuntimeError):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (HERE.parent / "harness_data"))


def tools_root() -> Path:
    return Path(os.environ.get("LOKI_TOOLS_DIR") or (data_dir() / "tools" / "shelf"))


def recipes() -> dict:
    out = {}
    for f in sorted(RECIPES.glob("*.json")):
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ShelfError("%s is not valid JSON: %s" % (f.name, exc)) from None
        for r in items if isinstance(items, list) else [items]:
            if isinstance(r, dict) and r.get("id"):
                out[r["id"]] = r
    return out


def recipe(tool_id: str) -> dict:
    r = recipes().get(str(tool_id or ""))
    if not r:
        raise ShelfError("no tool %r on the shelf (toolshelf action=list)" % tool_id)
    return r


def tool_dir(tool_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", str(tool_id)):
        raise ShelfError("bad tool id %r" % tool_id)
    return tools_root() / tool_id


def venv_python(d: Path) -> Path:
    return d / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _exe_name(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" and not name.endswith(".exe") else "")


def find_exe(d: Path, name: str) -> str:
    if not name:
        return ""
    for base in (d / "bin", d / "node_modules" / ".bin", d / "src", d):
        if base.is_dir():
            for cand in (_exe_name(name), name, name + ".cmd"):
                for p in base.rglob(cand):
                    if p.is_file():
                        return str(p)
    return shutil.which(name) or ""


def _plat() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def exe_for(r: dict) -> str:
    """The program's name: one name, or {platform: name} when the release names it per system."""
    inst = r.get("install") or {}
    exe = (inst.get("release") or {}).get("exe") or inst.get("exe") or ""
    return str(exe.get(_plat()) or "") if isinstance(exe, dict) else str(exe)


def placeholders(r: dict, d: Path) -> dict:
    inst = r.get("install") or {}
    exe_name = exe_for(r)
    py = venv_python(d)
    return {"python": str(py) if py.exists() else sys.executable, "exe": find_exe(d, exe_name), "src": str(d / "src"),
            "tool": str(d), "models": str(d / "models"), "loki_python": sys.executable,
            "runners": str(HERE / "runners"), "bin": "Scripts" if sys.platform == "win32" else "bin"}


def platform_ok(r: dict) -> bool:
    plats = r.get("platforms") or ["darwin", "win32", "linux"]
    return ("linux" if sys.platform.startswith("linux") else sys.platform) in plats


def installed(tool_id: str) -> bool:
    return (tool_dir(tool_id) / "installed.json").is_file()


def shelf() -> list:
    out = []
    for r in recipes().values():
        kind = (r.get("install") or {}).get("kind", "manual")
        out.append({"id": r["id"], "name": r.get("name", r["id"]), "area": r.get("area", ""), "what": r.get("what", ""),
                    "license": r.get("license", ""), "weights": r.get("weights"), "hardware": r.get("hardware", ""),
                    "repo": r.get("repo", ""), "kind": kind, "installed": installed(r["id"]),
                    "here": platform_ok(r), "actions": {k: v.get("what", "") for k, v in (r.get("actions") or {}).items()},
                    "manual": (r.get("install") or {}).get("manual", "") if kind == "manual" else ""})
    return sorted(out, key=lambda t: (AREAS.index(t["area"]) if t["area"] in AREAS else 99, t["name"].lower()))


# ----------------------------------------------------------------------------- installing
def find_python(version: str | None, which: Callable = shutil.which, run: Callable = subprocess.run) -> str:
    """A Python of that version on this computer ('' when there is none): this one, pythonX.Y, or py -X.Y."""
    if not version or "%d.%d" % sys.version_info[:2] == str(version):
        return sys.executable
    found = which("python%s" % version)
    if found:
        return found
    if sys.platform == "win32" and which("py"):
        try:
            proc = run(["py", "-%s" % version, "-c", "import sys; print(sys.executable)"], capture_output=True,
                       text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ""


def venv_command(version: str | None, target: Path, which: Callable = shutil.which,
                 run: Callable = subprocess.run) -> list:
    """How to make the tool's venv: with the Python it asks for; uv fetches that Python when the computer lacks it."""
    py = find_python(version, which, run)
    if py:
        return [py, "-m", "venv", str(target)]
    uv = which("uv")
    if uv:
        return [uv, "venv", "--seed", "--python", str(version), str(target)]
    raise ShelfError("this tool needs Python %s - install it (python.org), or install uv (astral.sh/uv) and LOKI "
                     "fetches it" % version)

def _fill(parts: list, ph: dict) -> list:
    out = []
    for p in parts:
        s = str(p)
        for k, v in ph.items():
            s = s.replace("{%s}" % k, str(v))
        out.append(s)
    return out


def _run(cmd: list, run: Callable, cwd: Path | None = None, timeout: float = 3600) -> str:
    proc = run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None)
    log = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
    if proc.returncode != 0:
        raise ShelfError("%s failed (exit %s): %s" % (" ".join(cmd[:4]), proc.returncode, log[-800:]))
    return log


def _download(url: str, dest: Path, opener=urllib.request.urlopen, say=None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with opener(urllib.request.Request(url, headers={"User-Agent": "Loki/1.0"}), timeout=300) as resp, \
            open(part, "wb") as fh:
        total = int(getattr(resp, "headers", {}).get("Content-Length") or 0) if hasattr(resp, "headers") else 0
        got = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if say and total:
                say("downloading %s" % dest.name, got / total)
    os.replace(part, dest)
    return dest


def _unpack(archive: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    root = into.resolve()
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                target = (into / m.filename).resolve()
                if root != target and root not in target.parents:
                    continue                                   # nothing outside the folder
                z.extract(m, into)
                mode = (m.external_attr >> 16) & 0o777
                if mode and target.is_file():
                    os.chmod(target, mode | 0o600)
    elif re.search(r"\.(tar\.gz|tgz|tar\.xz|tar\.bz2|tar)$", name):
        with tarfile.open(archive) as t:
            safe = [m for m in t.getmembers() if not m.issym() and not m.islnk()
                    and (root == (into / m.name).resolve() or root in (into / m.name).resolve().parents)]
            t.extractall(into, members=safe)
    else:                                                      # a bare binary
        target = into / archive.name
        shutil.copy2(archive, target)
        os.chmod(target, 0o755)
    archive.unlink(missing_ok=True)


def _unpack_dmg(dmg: Path, into: Path, run: Callable) -> None:
    """A macOS disk image: mount it, copy what is on it (the .app), unmount it."""
    mnt = dmg.with_suffix(".mnt")
    mnt.mkdir(parents=True, exist_ok=True)
    _run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mnt), str(dmg)], run)
    try:
        into.mkdir(parents=True, exist_ok=True)
        for item in mnt.iterdir():
            if item.name.startswith(".") or item.is_symlink():
                continue
            dest = into / item.name
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
    finally:
        _run(["hdiutil", "detach", str(mnt)], run)
    dmg.unlink(missing_ok=True)


def install(tool_id: str, progress: Callable | None = None, run: Callable = subprocess.run,
            opener=urllib.request.urlopen) -> dict:
    r = recipe(tool_id)
    say = progress or (lambda msg, frac=None: None)
    inst = r.get("install") or {}
    kind = inst.get("kind", "manual")
    if kind == "manual":
        return {"ok": False, "manual": True, "error": inst.get("manual") or "install it by hand: %s" % r.get("repo", "")}
    if not platform_ok(r):
        raise ShelfError("%s does not run on this computer (%s only)" % (r.get("name"), ", ".join(r.get("platforms"))))
    import big_storage  # pylint: disable=import-outside-toplevel
    if big_storage.low_space() and not str(tools_root()).startswith(str(big_storage.big_dir())):
        raise ShelfError(big_storage.install_note(r.get("name") or tool_id))
    d = tool_dir(tool_id)
    d.mkdir(parents=True, exist_ok=True)
    log = []
    plat = "linux" if sys.platform.startswith("linux") else sys.platform
    if kind in ("git", "git-pip", "comfyui"):
        src = d / "src"
        if not (src / ".git").is_dir():
            say("cloning %s" % inst["git"], 0.1)
            log.append(_run(["git", "clone", "--depth", "1"] + (["--branch", inst["ref"]] if inst.get("ref") and not
                            re.fullmatch(r"[0-9a-f]{7,40}", inst["ref"]) else []) + [inst["git"], str(src)], run))
            if inst.get("ref") and re.fullmatch(r"[0-9a-f]{7,40}", inst["ref"]):
                log.append(_run(["git", "-C", str(src), "fetch", "--depth", "1", "origin", inst["ref"]], run))
                log.append(_run(["git", "-C", str(src), "checkout", inst["ref"]], run))
    if kind in ("pip", "git-pip") or inst.get("pip") or inst.get("requirements_file"):
        py = venv_python(d)
        if not py.exists():
            say("making its own Python environment", 0.2)
            log.append(_run(venv_command(inst.get("python"), d / "venv"), run))
        pip = [str(py), "-m", "pip", "install", "--disable-pip-version-check"]
        index = (inst.get("pip_index") or {}).get(plat)
        extra = ["--extra-index-url", index] if index else []
        ph = placeholders(r, d)
        pkgs = _fill(list(inst.get("pip") or []) + list((inst.get("pip_platform") or {}).get(plat, [])), ph)
        if inst.get("requirements_file"):
            say("installing its requirements", 0.35)
            log.append(_run(pip + extra + ["-r", str(d / "src" / inst["requirements_file"])], run))
        if pkgs:
            say("installing %s" % ", ".join(pkgs)[:120], 0.5)
            log.append(_run(pip + extra + pkgs, run))
    if kind == "release":
        rel = inst["release"]
        asset = (rel.get("assets") or {}).get(plat)
        if not asset:
            raise ShelfError("%s has no release build for this computer" % r.get("name"))
        url = "https://github.com/%s/releases/download/%s/%s" % (rel["repo"], rel["tag"], asset)
        say("downloading %s" % asset, 0.3)
        got = _download(url, d / "dl" / asset, opener, say)
        name = exe_for(r)
        if asset.lower().endswith(".dmg"):
            _unpack_dmg(got, d / "bin", run)
        elif re.search(r"\.(zip|tar\.gz|tgz|tar\.xz|tar\.bz2|tar)$", asset.lower()):
            _unpack(got, d / "bin")
        else:                                   # a bare program (an AppImage, a single binary): give it its name
            (d / "bin").mkdir(parents=True, exist_ok=True)
            target = d / "bin" / _exe_name(name)
            shutil.move(str(got), str(target))
            os.chmod(target, 0o755)
        exe = find_exe(d, name)
        if not exe:
            raise ShelfError("%s unpacked but %s was not found in it" % (asset, name))
        os.chmod(exe, os.stat(exe).st_mode | 0o755)
    if kind == "npm":
        npm = shutil.which("npm")
        if not npm:
            raise ShelfError("this tool needs Node.js (npm) - install it from nodejs.org first")
        say("installing with npm", 0.4)
        log.append(_run([npm, "install", "--prefix", str(d)] + list(inst.get("npm") or []), run))
    if kind == "comfyui":
        import forge_trellis  # pylint: disable=import-outside-toplevel - where ComfyUI lives on this computer
        comfy = forge_trellis.find_comfy_dir()
        if comfy is None:
            raise ShelfError("this is a ComfyUI node - no ComfyUI on this computer (Forge > Output > Folder)")
        dest = comfy / "custom_nodes" / tool_id
        if not dest.exists():
            shutil.copytree(d / "src", dest)
        log.append("copied into %s - restart ComfyUI" % dest)
    for m in inst.get("models") or []:
        target = (d / m["to"]).resolve()
        if d.resolve() not in target.parents:
            raise ShelfError("a model path leaves the tool's folder: %s" % m["to"])
        if not target.is_file():
            say("downloading %s" % target.name, 0.7)
            _download(m["url"], target, opener, say)
    ph = placeholders(r, d)
    for step in inst.get("after") or []:
        say("finishing: %s" % " ".join(step[:3]), 0.85)
        log.append(_run(_fill(step, ph), run, cwd=d, timeout=3600))
    (d / "installed.json").write_text(json.dumps({"t": time.time(), "recipe": r}, indent=1), encoding="utf-8")
    ok, note = check(tool_id, run)
    return {"ok": True, "tool": tool_id, "checked": ok, "check": note[-500:], "folder": str(d)}


def check(tool_id: str, run: Callable = subprocess.run) -> tuple:
    r = recipe(tool_id)
    cmd = r.get("check")
    if not cmd:
        return True, "no check"
    ph = placeholders(r, tool_dir(tool_id))
    try:
        proc = run(_fill(cmd, ph), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return proc.returncode == 0, ((proc.stdout or "") + (proc.stderr or ""))[-600:]


def remove(tool_id: str) -> dict:
    d = tool_dir(tool_id)
    if d.exists():
        shutil.rmtree(d)
    return {"ok": True, "removed": tool_id}


# ----------------------------------------------------------------------------- running
def build_command(r: dict, action: str, args: dict, ws: Path, d: Path) -> tuple:
    act = (r.get("actions") or {}).get(action)
    if not act:
        raise ShelfError("%s has no action %r (it has: %s)" % (r["id"], action, ", ".join(r.get("actions") or {})))
    ws = Path(ws).resolve()
    vals, outputs = {}, []
    for name, spec in (act.get("args") or {}).items():
        kind = spec.get("type", "text")
        given = args.get(name)
        if given in (None, "") and "default" in spec:
            given = spec["default"]
        if given in (None, ""):
            if spec.get("optional") or kind == "bool":
                vals[name] = None
                continue
            raise ShelfError("%s needs %s (%s)" % (action, name, spec.get("what", kind)))
        if kind in ("file", "dir", "out"):
            raw = str(given)
            if kind == "out":
                stem = Path(str(vals.get("input") or "out")).stem
                raw = raw.replace("{input_stem}", stem)
                for k, v in vals.items():                   # e.g. "{preset}.wav"
                    if isinstance(v, str) and "{%s}" % k in raw:
                        raw = raw.replace("{%s}" % k, Path(v).stem if os.sep in v or "/" in v else v)
            p = (ws / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
            if ws != p and ws not in p.parents and not spec.get("anywhere"):
                raise ShelfError("%s must be inside the workspace: %s" % (name, raw))
            if kind == "file" and not p.is_file():
                raise ShelfError("no such file: %s" % raw)
            if kind == "dir" and not p.is_dir():
                raise ShelfError("no such folder: %s" % raw)
            if kind == "file" and spec.get("exts") and p.suffix.lower() not in [e.lower() for e in spec["exts"]]:
                raise ShelfError("%s must be one of %s" % (name, ", ".join(spec["exts"])))
            if kind == "out":
                p.parent.mkdir(parents=True, exist_ok=True)
                outputs.append(p)
            vals[name] = str(p)
        elif kind in ("number", "int"):
            try:
                v = float(given)
            except (TypeError, ValueError):
                raise ShelfError("%s must be a number" % name) from None
            if "min" in spec:
                v = max(float(spec["min"]), v)
            if "max" in spec:
                v = min(float(spec["max"]), v)
            vals[name] = str(int(v)) if kind == "int" or v.is_integer() else str(v)
        elif kind == "bool":
            vals[name] = given in (True, 1, "1", "true", "yes", "on")
        elif kind == "choice":
            if str(given) not in [str(c) for c in spec.get("choices") or []]:
                raise ShelfError("%s is one of %s" % (name, ", ".join(map(str, spec.get("choices") or []))))
            vals[name] = str(given)
        else:
            vals[name] = str(given)[:4000]
    ph = placeholders(r, d)
    cmd = []
    for part in act["cmd"]:
        part = str(part)
        m = re.fullmatch(r"\{(\w+)\}", part)
        if m and m.group(1) in vals:
            spec = (act.get("args") or {}).get(m.group(1), {})
            v = vals[m.group(1)]
            if v is None or v is False:
                continue                                       # an optional arg left out
            if spec.get("flag"):
                cmd += [spec["flag"]] if v is True else [spec["flag"], v]
                continue
            cmd.append(str(v))
            continue
        for k, v in list(ph.items()) + [(k, v) for k, v in vals.items() if isinstance(v, str)]:
            part = part.replace("{%s}" % k, v)
        cmd.append(part)
    if not cmd or (cmd[0] in ("", "{exe}")):
        raise ShelfError("%s is not installed (toolshelf action=install id=%s)" % (r.get("name"), r["id"]))
    return cmd, outputs, int(act.get("timeout") or 1800)


def run(tool_id: str, action: str, args: dict, ws: Path, runner: Callable = subprocess.run) -> dict:
    r = recipe(tool_id)
    d = tool_dir(tool_id)
    if not installed(tool_id):
        raise ShelfError("%s is not installed yet (toolshelf action=install id=%s)" % (r.get("name"), tool_id))
    cmd, outputs, timeout = build_command(r, action, args or {}, Path(ws), d)
    env = dict(os.environ)
    for k in (r.get("env") or {}):
        env.setdefault(k, str(r["env"][k]))
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ws), env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "%s took longer than %d s" % (action, timeout)}
    log = ((proc.stdout or "") + (proc.stderr or ""))[-6000:]
    made = [os.path.relpath(p, ws) for p in outputs if p.exists()]
    ok = proc.returncode == 0 and (not outputs or bool(made))
    out = {"ok": ok, "tool": tool_id, "action": action, "outputs": made, "log": log[-3000:]}
    if not ok:
        out["error"] = ("exit %s" % proc.returncode) if proc.returncode else "it ran but made no output file"
    return out


# ----------------------------------------------------------------------------- recipe checks
KINDS = ("pip", "git", "git-pip", "release", "npm", "comfyui", "manual")
ARG_TYPES = ("file", "dir", "out", "text", "number", "int", "bool", "choice")


def validate(r: dict) -> list:
    """What is wrong with a recipe (an empty list: nothing)."""
    p = []
    rid = r.get("id", "?")
    for k in ("id", "name", "area", "what", "repo", "license", "install"):
        if not r.get(k):
            p.append("%s: no %s" % (rid, k))
    if r.get("area") not in AREAS:
        p.append("%s: area %r" % (rid, r.get("area")))
    inst = r.get("install") or {}
    kind = inst.get("kind")
    if kind not in KINDS:
        p.append("%s: install kind %r" % (rid, kind))
    if kind in ("git", "git-pip", "comfyui") and not str(inst.get("git", "")).startswith("https://"):
        p.append("%s: git url" % rid)
    if kind == "release":
        rel = inst.get("release") or {}
        if not (rel.get("repo") and rel.get("tag") and rel.get("assets") and rel.get("exe")):
            p.append("%s: release needs repo, tag, assets, exe" % rid)
    if kind == "pip" and not inst.get("pip") and not inst.get("pip_platform"):
        p.append("%s: pip kind with no packages" % rid)
    if kind == "manual" and not inst.get("manual"):
        p.append("%s: manual kind says nothing" % rid)
    for m in inst.get("models") or []:
        if not str(m.get("url", "")).startswith("https://") or ".." in str(m.get("to", "")):
            p.append("%s: model %r" % (rid, m))
    for name, act in (r.get("actions") or {}).items():
        if not isinstance(act.get("cmd"), list) or not act["cmd"]:
            p.append("%s.%s: cmd must be a list" % (rid, name))
            continue
        used = set(re.findall(r"\{(\w+)\}", " ".join(map(str, act["cmd"]))))
        known = set(act.get("args") or {}) | {"python", "exe", "src", "tool", "models", "input_stem", "loki_python",
                                              "runners", "bin"}
        if used - known:
            p.append("%s.%s: unknown placeholders %s" % (rid, name, sorted(used - known)))
        for an, spec in (act.get("args") or {}).items():
            if spec.get("type", "text") not in ARG_TYPES:
                p.append("%s.%s.%s: type %r" % (rid, name, an, spec.get("type")))
            if spec.get("type") == "choice" and not spec.get("choices"):
                p.append("%s.%s.%s: choice without choices" % (rid, name, an))
        if any(str(x).startswith(("sh", "bash", "cmd", "powershell")) and len(act["cmd"]) > 1
               and str(act["cmd"][1]) in ("-c", "/c", "-Command") for x in act["cmd"][:1]):
            p.append("%s.%s: no shell strings" % (rid, name))
    if kind != "manual" and not r.get("actions") and r.get("area") != "godot":
        p.append("%s: no actions" % rid)
    return p


# ----------------------------------------------------------------------------- LOKI's tool
def tool(args: dict, ws: Path, ask: Callable | None = None, runner: Callable = subprocess.run, opener=None) -> dict:
    action = str(args.get("action") or "list").lower()
    try:
        if action == "list":
            area = str(args.get("area") or "")
            return {"ok": True, "tools": [{k: t[k] for k in ("id", "name", "area", "what", "installed", "here", "actions")}
                                          for t in shelf() if not area or t["area"] == area]}
        tid = str(args.get("id") or args.get("tool") or "")
        if action == "info":
            r = recipe(tid)
            return {"ok": True, "installed": installed(tid), **{k: r.get(k) for k in (
                "id", "name", "area", "what", "repo", "license", "weights", "hardware", "platforms", "notes", "actions")}}
        if action == "install":
            r = recipe(tid)
            inst = r.get("install") or {}
            detail = ("Install %s (%s, licence %s%s) into LOKI's tools folder - it downloads and runs its code:\n%s" % (
                r.get("name"), r.get("repo"), r.get("license"),
                ("; weights: %s" % (r["weights"].get("license") if isinstance(r.get("weights"), dict) else r["weights"]))
                if r.get("weights") else "", json.dumps({k: v for k, v in inst.items() if k != "manual"})[:1500]))
            if ask is not None and not ask("toolshelf_install", detail):
                return {"ok": False, "error": "not installed - the owner said no"}
            return install(tid, run=runner, **({"opener": opener} if opener else {}))
        if action == "run":
            what = str(args.get("run") or args.get("what") or "")
            r = recipe(tid)
            act = (r.get("actions") or {}).get(what) or {}
            if act.get("ask"):                     # publishing, changing an agent's setup: the owner sees it first
                detail = "%s - %s\n\n%s" % (r.get("name"), act.get("what", what),
                                              json.dumps(args.get("args") or {}, indent=1)[:3000])
                if ask is None or not ask("toolshelf_" + what, detail):
                    return {"ok": False, "error": "not done - this action needs the owner's OK (it was not given)"}
            return run(tid, what, args.get("args") or {}, ws, runner)
        if action == "remove":
            if ask is not None and not ask("toolshelf_remove", "Remove %s and everything it downloaded" % tid):
                return {"ok": False, "error": "kept - the owner said no"}
            return remove(tid)
    except ShelfError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "action is list, info, install, run or remove"}


TOOL = {"name": "toolshelf",
        "description": "LOKI's Tool Shelf: open-source game-dev tools installed on request and run on workspace files - "
                       "sound effects, music, voices, captions, sprite cleanup, normal maps, frame in-betweening, mesh "
                       "LODs, UV unwrap, quad remesh, auto-rigging, text-to-motion, trailers, store art, posting, Godot "
                       "lint/format/tests. action=list (area= audio|2d|3d|animation|video|marketing|godot) | info id= | "
                       "install id= (asks the owner) | run id= run=<action> args={...} (paths inside the workspace) | "
                       "remove id=.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "info", "install", "run", "remove"]},
            "area": {"type": "string"}, "id": {"type": "string"}, "run": {"type": "string"},
            "args": {"type": "object"}}, "required": ["action"]}}


def route(state: Any, method: str, path: str, query: dict, body: dict, ask: Callable | None = None) -> tuple:
    """GET /tools/shelf, POST /tools/shelf/install {id} (a job; the window asked first), POST /tools/shelf/remove {id}."""
    try:
        if method == "GET" and path == "/tools/shelf":
            return 200, {"ok": True, "tools": shelf(), "folder": str(tools_root())}
        if method == "POST" and path == "/tools/shelf/install":
            import forge3d  # pylint: disable=import-outside-toplevel - its job runner shows progress in the window
            tid = str(body.get("id") or "")
            recipe(tid)
            return 200, forge3d.start_job(lambda progress: install(tid, progress=lambda m, f=None: progress(m, f or 0.5)),
                                          kind="install", label=tid)
        if method == "POST" and path == "/tools/shelf/remove":
            return 200, remove(str(body.get("id") or ""))
    except ShelfError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
