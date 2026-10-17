"""The launcher of an installed LOKI (Windows installer, macOS .dmg). Standard library only.

The installers put a LOKI tree (the "seed", built by tools/make_release.py) next to this file and
run it through bootstrap.ps1 / bootstrap.sh, which make LOKI's private Python first. This launcher:

  1. finds LOKI's data folder (%LOCALAPPDATA%\\Loki, ~/Library/Application Support/Loki, or LOKI_DATA)
  2. installs the seed into <data>/versions/<version> on the first run, or when a newer installer
     was run over an older install (the installer is trusted like a release)
  3. installs the current version's Python packages into <data>/.venv when they changed
  4. starts <data>/versions/<current>/app/loki_app.py with LOKI_RELEASE_ROOT set, so the app
     updates from release zips (engine/release_update.py) with pre-flight, trial and rollback
  5. starts it again when it exits with 76 (a new version, or a rollback to the last good one)

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

LAUNCHER_VERSION = 1
RELAUNCH_EXIT_CODE = 76
HERE = Path(__file__).resolve().parent


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


def ensure_packages(python: Path, tree: Path, data: Path) -> bool:
    """pip install the tree's requirements when they changed since the last install."""
    reqs = [tree / "engine" / "requirements.txt", tree / "app" / "requirements.txt"]
    digest = hashlib.sha256(b"".join(r.read_bytes() for r in reqs if r.is_file())).hexdigest()
    marker = data / ".venv" / "loki-requirements.sha256"
    try:
        if marker.read_text(encoding="utf-8").strip() == digest:
            return True
    except OSError:
        pass
    log("installing LOKI's Python packages (one time, needs the internet)")
    args = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    for r in reqs:
        if r.is_file():
            args += ["-r", str(r)]
    proc = subprocess.run(args, capture_output=True, text=True)
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


def main(argv: list) -> int:
    seed = HERE / "seed"
    if "--seed" in argv:
        seed = Path(argv[argv.index("--seed") + 1]).resolve()
    data = data_dir()
    root = data / "versions"
    root.mkdir(parents=True, exist_ok=True)
    install_seed(root, seed)
    python = venv_python(data)
    if python is None:
        log("LOKI's Python is missing in %s - run the bootstrap (it comes with the installer)" % (data / ".venv"))
        return 3
    relaunches = []
    while True:
        tree = pick_tree(root)
        if tree is None:
            log("no LOKI version is installed in %s - run the installer again" % root)
            return 4
        if not ensure_packages(python, tree, data):
            log("could not install LOKI's packages; check the internet connection and open LOKI again")
            return 5
        self_update(tree, data)
        if "--check" in argv:
            print(json.dumps({"ok": True, "version": tree.name, "python": str(python), "data": str(data)}))
            return 0
        env = dict(os.environ, LOKI_DATA=str(data), LOKI_RELEASE_ROOT=str(root), LOKI_ENGINE_PYTHON=str(python),
                   LOKI_LAUNCHER=str(Path(__file__).resolve()))
        log("starting LOKI %s" % tree.name)
        window_py = python.with_name("pythonw.exe") if sys.platform == "win32" else python   # no console window
        if not window_py.is_file():
            window_py = python
        code = subprocess.call([str(window_py), str(tree / "app" / "loki_app.py")] + [a for a in argv if a not in ("--seed", str(seed))],
                               cwd=str(tree), env=env)
        if code != RELAUNCH_EXIT_CODE:
            return code
        now = time.time()
        relaunches = [t for t in relaunches if now - t < 120] + [now]
        if len(relaunches) > 4:
            log("LOKI asked to restart 5 times in 2 minutes; stopping")
            return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
