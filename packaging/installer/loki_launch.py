"""The launcher of an installed LOKI (Windows installer, macOS .dmg). Standard library only.

The installers put a LOKI tree (the "seed", built by tools/make_release.py) next to this file and
run it through bootstrap.ps1 / bootstrap.sh, which make LOKI's private Python first. This launcher:

  1. finds LOKI's data folder (%LOCALAPPDATA%\\Loki, ~/Library/Application Support/Loki, or LOKI_DATA)
  2. installs the seed into <data>/versions/<version> on the first run, or when a newer installer
     was run over an older install (the installer is trusted like a release)
  3. makes <data>/.venv from the Python that came WITH the installer (runtime/python next to this
     file, session 30: python-build-standalone with LOKI's packages already inside) - offline, in a
     fraction of a second, no download; an installer without one (a slim build) has the bootstrap
     download Python first, as before
  4. installs the current version's Python packages into <data>/.venv only when they differ from
     what the bundled runtime already has (an update that added a package)
  5. starts <data>/versions/<current>/app/loki_app.py with LOKI_RELEASE_ROOT set, so the app
     updates from release zips (engine/release_update.py) with pre-flight, trial and rollback
  6. starts it again when it exits with 76 (a new version, or a rollback to the last good one)

No console window anywhere on Windows: the shortcut runs this with pythonw.exe (or Loki.exe, the
small launcher in packaging/launcher), and every child process gets CREATE_NO_WINDOW.

    python loki_launch.py [--seed DIR] [--check]   (--check: set up and report, do not open LOKI)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAUNCHER_VERSION = 2
RELAUNCH_EXIT_CODE = 76
# where the installer put LOKI (seed/, runtime/): this file's folder, or, for a newer launcher a release
# left in <data>/launcher, the folder of the launcher that handed over (LOKI_INSTALL_DIR)
HERE = Path(os.environ.get("LOKI_INSTALL_DIR") or Path(__file__).resolve().parent)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW: no console flashes


def _quiet() -> dict:
    return {"creationflags": NO_WINDOW} if NO_WINDOW else {}


def data_dir() -> Path:
    if os.environ.get("LOKI_DATA"):
        return Path(os.environ["LOKI_DATA"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "Loki"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Loki"
    return Path.home() / ".local" / "share" / "loki"


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print("[loki-launch] " + msg, file=sys.stderr, flush=True)
    try:
        path = data_dir() / "app" / "launcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def vkey(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else -1 for p in str(v).replace("-", ".").split("."))


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def install_seed(root: Path, seed: Path) -> str:
    """The installer's own LOKI becomes current when there is none, or when it is newer."""
    info = read_json(seed / "RELEASE.json")
    version = str(info.get("version", ""))
    if not version or not (seed / "app" / "loki_app.py").is_file():
        return ""
    state = read_json(root / "state.json")
    cur = state.get("current", "")
    have = bool(cur) and (root / cur / "app" / "loki_app.py").is_file()
    if have and vkey(cur) >= vkey(version):
        return ""
    dest = root / version
    if not (dest / "app" / "loki_app.py").is_file():
        log("installing LOKI %s" % version)
        tmp = root / (version + ".installing")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(seed, tmp)
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(tmp, dest)
    state.update({"current": version, "last_good": version, "pending": "", "installed_at": time.time()})
    hist = [h for h in state.get("history", []) if isinstance(h, dict)][-29:]
    hist.append({"event": "installed", "version": version, "t": time.time()})
    state["history"] = hist
    write_json(root / "state.json", state)
    return version


def pick_tree(root: Path) -> Path | None:
    state = read_json(root / "state.json")
    for name in (state.get("current", ""), state.get("last_good", "")):
        if name and (root / name / "app" / "loki_app.py").is_file():
            if name != state.get("current"):
                log("version %s is missing; using %s" % (state.get("current"), name))
                state.update({"current": name, "pending": ""})
                write_json(root / "state.json", state)
            return root / name
    return None


def venv_python(data: Path) -> Path | None:
    for p in (data / ".venv" / "Scripts" / "python.exe", data / ".venv" / "bin" / "python3", data / ".venv" / "bin" / "python"):
        if p.is_file():
            return p
    return None


def bundled_python(here: Path = HERE) -> Path | None:
    """The Python that came with the installer (tools/bundle_runtime.py): runtime/python/..."""
    base = here / "runtime" / "python"
    for p in (base / "python.exe", base / "bin" / "python3", base / "bin" / "python"):
        if p.is_file():
            return p
    return None


def requirements_digest(tree: Path) -> str:
    reqs = [tree / "engine" / "requirements.txt", tree / "app" / "requirements.txt"]
    return hashlib.sha256(b"".join(r.read_bytes() for r in reqs if r.is_file())).hexdigest()


def _venv_home(venv: Path) -> str:
    try:
        for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home":
                return value.strip()
    except OSError:
        pass
    return ""


def ensure_venv(data: Path, base: Path | None) -> Path | None:
    """<data>/.venv on top of the bundled Python (its packages are visible: --system-site-packages),
    remade when the app was moved (the venv points at the old place) or is broken. Offline, ~0.2 s.
    Without a bundled Python the venv the bootstrap made is used as it is."""
    venv = data / ".venv"
    current = venv_python(data)
    if base is None:
        return current
    want = {base.parent.resolve(), base.resolve().parent}   # a symlinked python reports either
    if current is not None and _venv_home(venv) and Path(_venv_home(venv)).resolve() in want:
        return current
    log("making LOKI's Python environment from the bundled runtime" + (" (it moved)" if current else ""))
    shutil.rmtree(venv, ignore_errors=True)
    proc = subprocess.run([str(base), "-m", "venv", "--system-site-packages", "--without-pip", str(venv)],
                          capture_output=True, text=True, **_quiet())
    made = venv_python(data)
    if proc.returncode != 0 or made is None:
        log("could not make the environment: " + (proc.stdout + proc.stderr)[-600:])
        return None
    runtime = base.parent.parent.parent if base.parent.name == "bin" else base.parent.parent   # runtime/python/[bin/]python
    bundled = runtime / "loki-requirements.sha256"
    try:   # the bundle's packages are installed already: say so, so ensure_packages has nothing to do
        (venv / "loki-requirements.sha256").write_text(bundled.read_text(encoding="utf-8").strip(), encoding="utf-8")
    except OSError:
        pass
    return made


def ensure_packages(python: Path, tree: Path, data: Path) -> bool:
    """pip install the tree's requirements when they differ from what is installed (an update that
    added a package). With the bundled runtime the first start installs nothing (offline)."""
    reqs = [tree / "engine" / "requirements.txt", tree / "app" / "requirements.txt"]
    digest = requirements_digest(tree)
    marker = data / ".venv" / "loki-requirements.sha256"
    try:
        if marker.read_text(encoding="utf-8").strip() == digest:
            return True
    except OSError:
        pass
    if os.environ.get("LOKI_LAUNCH_NO_PIP") == "1":
        return True
    log("installing LOKI's Python packages (needs the internet)")
    args = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-q"]
    for r in reqs:
        if r.is_file():
            args += ["-r", str(r)]
    proc = subprocess.run(args, capture_output=True, text=True, **_quiet())
    if proc.returncode != 0:
        log("package install failed: " + (proc.stdout + proc.stderr)[-800:])
        return False
    marker.write_text(digest, encoding="utf-8")
    return True


def self_update(tree: Path, data: Path) -> None:
    """A good release may carry a newer launcher: keep a copy in <data>/launcher for the next start."""
    state = read_json(data / "versions" / "state.json")
    new = tree / "packaging" / "installer" / "loki_launch.py"
    if state.get("last_good") != tree.name or not new.is_file():
        return
    text = new.read_text(encoding="utf-8")
    try:
        theirs = int(text.split("LAUNCHER_VERSION = ", 1)[1].split()[0])
    except (IndexError, ValueError):
        return
    if theirs > LAUNCHER_VERSION:
        dest = data / "launcher" / "loki_launch.py"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        log("launcher %d saved for the next start" % theirs)


def tell_user(message: str) -> None:
    """A launcher started by a double click has no console: say what went wrong in a dialog."""
    log(message)
    if os.environ.get("LOKI_NO_DIALOGS") or os.environ.get("CI") or "--check" in sys.argv:
        return
    text = "%s\n\nThe details are in %s" % (message, data_dir() / "app" / "launcher.log")
    try:
        if sys.platform == "win32":
            import ctypes  # pylint: disable=import-outside-toplevel
            ctypes.windll.user32.MessageBoxW(None, text, "LOKI", 0x40)   # type: ignore[attr-defined]  MB_ICONINFORMATION
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", "display alert \"LOKI\" message %s" % json.dumps(text)], timeout=300)
    except Exception:  # noqa: BLE001 - the log has it
        pass


def newer_launcher(data: Path) -> Path | None:
    """A good release may have left a newer launcher in <data>/launcher (self_update): use it."""
    path = data / "launcher" / "loki_launch.py"
    try:
        theirs = int(path.read_text(encoding="utf-8").split("LAUNCHER_VERSION = ", 1)[1].split()[0])
    except (OSError, IndexError, ValueError):
        return None
    return path if theirs > LAUNCHER_VERSION and path.resolve() != Path(__file__).resolve() else None


def _passthrough(argv: list) -> list:
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
        elif a == "--seed":
            skip = True
        elif a != "--check":
            out.append(a)
    return out


def main(argv: list) -> int:
    seed = HERE / "seed"
    if "--seed" in argv:
        seed = Path(argv[argv.index("--seed") + 1]).resolve()
    data = data_dir()
    newer = newer_launcher(data)
    if newer is not None and os.environ.get("LOKI_LAUNCHER_HANDOFF") != "1":
        os.environ.update(LOKI_LAUNCHER_HANDOFF="1", LOKI_INSTALL_DIR=str(HERE))
        log("using the newer launcher in %s" % newer.parent)
        return subprocess.call([sys.executable, str(newer), "--seed", str(seed)] + _passthrough(argv) + (["--check"] if "--check" in argv else []),
                               **_quiet())
    root = data / "versions"
    root.mkdir(parents=True, exist_ok=True)
    install_seed(root, seed)
    python = ensure_venv(data, bundled_python())
    if python is None:
        tell_user("LOKI's Python is missing in %s. Run the installer again (or open LOKI through its bootstrap, "
                  "which downloads it)." % (data / ".venv"))
        return 3
    relaunches = []
    while True:
        tree = pick_tree(root)
        if tree is None:
            tell_user("No LOKI version is installed in %s. Run the installer again." % root)
            return 4
        if not ensure_packages(python, tree, data):
            tell_user("LOKI could not install the Python packages this version needs. Check the internet "
                      "connection and open LOKI again.")
            return 5
        self_update(tree, data)
        if "--check" in argv:
            print(json.dumps({"ok": True, "version": tree.name, "python": str(python), "data": str(data),
                              "bundled": bundled_python() is not None}))
            return 0
        env = dict(os.environ, LOKI_DATA=str(data), LOKI_RELEASE_ROOT=str(root), LOKI_ENGINE_PYTHON=str(python),
                   LOKI_LAUNCHER=str(Path(__file__).resolve()))
        log("starting LOKI %s" % tree.name)
        window_py = python.with_name("pythonw.exe") if sys.platform == "win32" else python   # no console window
        if not window_py.is_file():
            window_py = python
        code = subprocess.call([str(window_py), str(tree / "app" / "loki_app.py")] + _passthrough(argv),
                               cwd=str(tree), env=env, **_quiet())
        if code != RELAUNCH_EXIT_CODE:
            return code
        now = time.time()
        relaunches = [t for t in relaunches if now - t < 120] + [now]
        if len(relaunches) > 4:
            log("LOKI asked to restart 5 times in 2 minutes; stopping")
            return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
