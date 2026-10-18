"""Make the Python runtime that ships INSIDE LOKI's installers (session 30: zero-dependency install).

    python tools/bundle_runtime.py                       # -> dist/runtime/ for THIS computer's OS/CPU
    python tools/bundle_runtime.py --seed dist/release/seed --out dist/runtime
    python tools/bundle_runtime.py --python-dir DIR      # use an unpacked python-build-standalone here

What it makes (run it on the OS the installer is for - CI does, one job per OS):
    <out>/python/                  python-build-standalone CPython 3.12 ("install_only"), the same
                                   relocatable Python uv uses, with every package LOKI needs
                                   (engine/requirements.txt + app/requirements.txt) already installed
    <out>/loki-requirements.sha256 which requirements are inside (packaging/installer/loki_launch.py
                                   compares it, so a first start installs nothing and needs no internet)
    <out>/RUNTIME.json             python version, platform, package list, size
Then it byte-compiles the runtime and the seed with that same Python (unchecked-hash .pyc, so the
first start does not compile ~1,700 files: docs/SPEED.md measured 2.2 s -> 0.9 s for the engine).

Where Python comes from: `uv python install 3.12` (uv downloads python-build-standalone from its
GitHub releases and checks it); --python-dir skips the download. uv is only needed on the BUILD
machine - nobody who installs LOKI needs uv, Python, pip or the internet.
Licences: CPython (PSF-2.0), python-build-standalone (MPL-2.0 build scripts) - docs/THIRD_PARTY.md.
"""
from __future__ import annotations

import argparse
import compileall
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY_VERSION = os.environ.get("LOKI_BUNDLE_PYTHON", "3.12")
# never needed by LOKI and big: the CPython test suite, IDLE, turtle demos
STRIP = ("test", "idlelib", "turtledemo", "lib2to3/tests", "tkinter/test", "unittest/test", "ensurepip/_bundled")


def requirements_digest(tree: Path) -> str:
    """The same digest as packaging/installer/loki_launch.py requirements_digest()."""
    reqs = [tree / "engine" / "requirements.txt", tree / "app" / "requirements.txt"]
    return hashlib.sha256(b"".join(r.read_bytes() for r in reqs if r.is_file())).hexdigest()


def python_in(base: Path) -> Path:
    for p in (base / "python.exe", base / "bin" / "python3", base / "bin" / "python"):
        if p.is_file():
            return p
    raise FileNotFoundError("no python executable in %s" % base)


def fetch_python(dest: Path) -> Path:
    """python-build-standalone via uv, copied (resolved, no links) into dest."""
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is needed on the build machine (pip install uv, or https://docs.astral.sh/uv/) - "
                         "or pass --python-dir with an unpacked python-build-standalone 'install_only' build")
    store = dest.parent / ".uv-python"
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(store))
    subprocess.run([uv, "python", "install", PY_VERSION], check=True, env=env)
    found = sorted(p for p in store.glob("cpython-%s*" % PY_VERSION) if p.is_dir() and not p.is_symlink())
    if not found:
        raise SystemExit("uv installed Python, but not into %s" % store)
    return found[-1]


def copy_python(src: Path, dest: Path) -> Path:
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest, symlinks=True)
    for marker in list(dest.rglob("EXTERNALLY-MANAGED")):   # uv marks its Pythons; this one is LOKI's own
        marker.unlink()
    return dest


def strip(base: Path) -> int:
    removed = 0
    for lib in [p for p in (base / "Lib", *sorted((base / "lib").glob("python3.*"))) if p.is_dir()]:
        for rel in STRIP:
            target = lib / rel
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                removed += 1
    for cache in list(base.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    return removed


def install_packages(python: Path, seed: Path) -> list:
    reqs = [seed / "engine" / "requirements.txt", seed / "app" / "requirements.txt"]
    args = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-warn-script-location",
            "--only-binary=:all:"]
    for r in reqs:
        if r.is_file():
            args += ["-r", str(r)]
    proc = subprocess.run(args)
    if proc.returncode != 0:   # a package without a wheel for this platform: let pip build it
        subprocess.run([a for a in args if a != "--only-binary=:all:"], check=True)
    out = subprocess.run([str(python), "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                         capture_output=True, text=True, check=True).stdout
    return sorted("%s==%s" % (p["name"], p["version"]) for p in json.loads(out))


def precompile(python: Path, *trees: Path) -> None:
    """Byte-compile with the bundled Python itself (its magic number), unchecked-hash: the .pyc are
    used as they are (versions never change in place - an update is a new folder)."""
    for tree in trees:
        if tree.is_dir():
            subprocess.run([str(python), "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
                            str(tree)], check=False)


def size_mb(path: Path) -> float:
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink()) / 2**20, 1)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bundle python-build-standalone + LOKI's packages for an installer.")
    ap.add_argument("--out", default=str(REPO / "dist" / "runtime"))
    ap.add_argument("--seed", default=str(REPO / "dist" / "release" / "seed"), help="the release seed (its requirements; compiled too)")
    ap.add_argument("--python-dir", default="", help="an unpacked python-build-standalone install_only folder")
    ap.add_argument("--no-packages", action="store_true", help="only Python (tests)")
    ap.add_argument("--no-compile", action="store_true")
    args = ap.parse_args(argv)
    out, seed = Path(args.out).resolve(), Path(args.seed).resolve()
    if not (seed / "engine").is_dir():
        seed = REPO   # no release built yet: use the checkout's requirements (the seed is not compiled then)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(args.python_dir).resolve() if args.python_dir else fetch_python(out)
    base = copy_python(src, out / "python")
    removed = strip(base)
    python = python_in(base)
    packages = [] if args.no_packages else install_packages(python, seed)
    (out / "loki-requirements.sha256").write_text(requirements_digest(seed), encoding="utf-8")
    if not args.no_compile:
        precompile(python, base, *( [seed] if seed != REPO else []))
    version = subprocess.run([str(python), "-c", "import sys; print(sys.version.split()[0])"], capture_output=True, text=True).stdout.strip()
    info = {"python": version, "platform": sys.platform, "machine": platform.machine().lower(), "packages": packages,
            "size_mb": size_mb(base), "stripped": removed, "requirements_sha256": requirements_digest(seed)}
    (out / "RUNTIME.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    shutil.rmtree(out / ".uv-python", ignore_errors=True)
    print(json.dumps({k: v for k, v in info.items() if k != "packages"} | {"packages": len(packages), "out": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
