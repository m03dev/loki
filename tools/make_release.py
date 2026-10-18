"""Build a LOKI release: the update zip, the installers' seed, portable zips, and the friends kit.

    python tools/make_release.py                          # dist/release/: seed + Loki-<v>.zip + manifest.json
    python tools/make_release.py --portable               # + dist/Loki-<v>-<os>-portable.zip (this OS)
    python tools/make_release.py --friends                # the zip(s) to send friends, into dist/ (below)
    python tools/make_release.py --asset-base https://github.com/m03dev/loki/releases/download/v0.17.0

Writes into --out (default dist/release):
    seed/                 the LOKI tree the installers bundle (with RELEASE.json)
    Loki-<version>.zip    the same tree, for updates (engine/release_update.py)
    manifest.json         {version, url, sha256, size, notes, min_launcher}  -> upload next to the zip
    manifest.json.sig     only when LOKI_SIGNING_KEY points at the private key (tools/loki_sign.py)

Only files git tracks go in (never harness_data, .env, keys you made, models or venvs), and not what
an installed LOKI never runs (tests, the phone app, the cloud relay, CI, the big design docs).
EVERY build is secret-scanned (tools/secret_scan.py) and refused when anything looks like a key.
The version is VERSION + the patch number ("0.16" + 412 commits -> "0.16.412").
The feed defaults to LOKI's public GitHub Releases (engine/release_update.DEFAULT_FEED).

--friends (session 30, docs/TESTERS.md): builds from `git archive HEAD` - the COMMITTED tracked files
only, nothing from the working tree - scans it, then makes for THIS computer's OS:
    dist/Loki-<v>-<os>-portable.zip   unzip, double-click (with the bundled Python when dist/runtime
                                      exists or --bundle-runtime makes it: no download at first start)
    dist/release/Loki-<v>.zip         the update zip + manifest (what installed copies download)
    dist/FRIENDS.txt                  what to send, sizes, sha256, the 3-step install
The Windows installer (.exe) and the macOS .dmg come from CI (.github/workflows/installers.yml).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import secret_scan  # noqa: E402  pylint: disable=wrong-import-position

LAUNCHER_VERSION = 2
SKIP_TOP = ("tests", "mobile", "cloud", ".github")   # packaging/installer stays: the launcher updates itself from it
KEEP_DOCS = ("docs/help/", "docs/INSTALL.md", "docs/THIRD_PARTY.md", "docs/TESTERS.md")
DEFAULT_FEED = "https://github.com/m03dev/loki/releases/latest/download/manifest.json"   # = release_update.DEFAULT_FEED


class SecretFound(RuntimeError):
    def __init__(self, findings: list):
        self.findings = findings
        super().__init__("refusing to package: %d thing(s) look like keys or private files:\n  %s" % (
            len(findings), "\n  ".join("%s%s: %s" % (f["path"], (":%d" % f["line"]) if f["line"] else "", f["what"])
                                        for f in findings[:30])))


def tracked(repo: Path, untracked: bool = False) -> list:
    """git-tracked files; with untracked=True also new files git does not ignore (tests, local builds).
    A folder that is not a git checkout (a `git archive` export): every file in it."""
    if not (repo / ".git").exists():
        return sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())
    args = ["git", "-C", str(repo), "ls-files", "-z"] + (["-co", "--exclude-standard"] if untracked else [])
    out = subprocess.run(args, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def wanted(path: str) -> bool:
    top = path.split("/", 1)[0]
    if top in SKIP_TOP or top.startswith("harness_data"):
        return False
    if top == "docs":
        return path.startswith(KEEP_DOCS)
    if path.startswith("packaging/launcher/target/"):
        return False
    return not path.endswith((".pyc",)) and "/__pycache__/" not in path


def release_version(repo: Path) -> str:
    sys.path.insert(0, str(repo / "engine"))
    import updater  # pylint: disable=import-outside-toplevel
    info = updater.version(repo)
    return "%s.%d" % (info.get("version") or "0.0", info.get("patch") or 0)


def git_commit(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True).stdout.strip()


def build(repo: Path, out: Path, version: str, feed: str, notes: str, untracked: bool = False, compress: bool = True,
          asset_base: str = "", commit: str = "") -> dict:
    files = [p for p in sorted(set(tracked(repo, untracked))) if wanted(p) and (repo / p).is_file()]
    findings = secret_scan.scan(repo, files)
    if findings:
        raise SecretFound(findings)
    seed = out / "seed"
    shutil.rmtree(seed, ignore_errors=True)
    for rel in files:
        dst = seed / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, dst)
    commit = commit or git_commit(repo)
    info = {"version": version, "feed": feed, "commit": commit, "built": int(time.time()), "launcher": LAUNCHER_VERSION}
    (seed / "RELEASE.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    name = "Loki-%s.zip" % version
    zpath = out / name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as zf:
        for path in sorted(seed.rglob("*")):
            if path.is_file():
                zf.write(path, "Loki-%s/%s" % (version, path.relative_to(seed).as_posix()))
    data = zpath.read_bytes()
    url = (asset_base.rstrip("/") + "/" + name) if asset_base else name
    manifest = {"version": version, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                "notes": notes, "min_launcher": LAUNCHER_VERSION, "commit": commit}
    mpath = out / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    signed = False
    if os.environ.get("LOKI_SIGNING_KEY"):
        proc = subprocess.run([sys.executable, str(REPO / "tools" / "loki_sign.py"), "sign", str(mpath)], capture_output=True, text=True)
        signed = proc.returncode == 0
        if not signed:
            print("signing failed: " + (proc.stdout + proc.stderr).strip(), file=sys.stderr)
    return {"files": len(files), "zip": str(zpath), "manifest": str(mpath), "signed": signed, "seed": str(seed), **manifest}


# ------------------------------------------------------------------ portable zips
def os_name(platform: str | None = None) -> str:
    platform = platform or sys.platform
    return "windows" if platform == "win32" else "macos" if platform == "darwin" else "linux"


WINDOWS_README = """LOKI (portable)

1. Unzip this folder anywhere (Desktop, Documents, a USB stick).
2. Double-click Loki.exe. Windows may say "Windows protected your PC": More info > Run anyway
   (LOKI is not code-signed yet).
3. The welcome tour asks how LOKI should think: on this computer (free, private) or a free
   online account. Every step can be skipped.

Your chats, settings and keys live in %LOCALAPPDATA%\\Loki, not in this folder.
Problems? Settings > General > Send feedback, or see docs/TESTERS.md.
"""
UNIX_README = """LOKI (portable)

1. Unzip it.
2. macOS: right-click LOKI.app > Open > Open (only the first time: LOKI is not notarized yet).
   Linux: run ./start-loki.sh
3. The welcome tour asks how LOKI should think: on this computer (free, private) or a free
   online account. Every step can be skipped.

Your chats, settings and keys live in ~/Library/Application Support/Loki (macOS) or
~/.local/share/loki (Linux), not in this folder. Problems? Settings > General > Send feedback.
"""
START_SH = """#!/bin/bash
# LOKI portable: start the bundled Python on the launcher (or the bootstrap without one)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LOKI_INSTALL_DIR="$HERE"
if [ -x "$HERE/runtime/python/bin/python3" ]; then
  exec "$HERE/runtime/python/bin/python3" "$HERE/loki_launch.py" --seed "$HERE/seed" "$@"
fi
exec /bin/bash "$HERE/bootstrap.sh" "$@"
"""
START_CMD = ("@echo off\r\nrem LOKI portable without Loki.exe: start the bundled Python with no console window\r\n"
             "cd /d \"%~dp0\"\r\nset LOKI_INSTALL_DIR=%~dp0\r\n"
             "if exist \"runtime\\python\\pythonw.exe\" (start \"\" \"runtime\\python\\pythonw.exe\" \"loki_launch.py\" --seed \"seed\") "
             "else (start \"\" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"bootstrap.ps1\")\r\n")


def _add_tree(zf: zipfile.ZipFile, src: Path, arc: str) -> int:
    n = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src).as_posix()
        if path.is_symlink():   # python-build-standalone on macOS/Linux has bin/python3 -> python3.12
            info = zipfile.ZipInfo("%s/%s" % (arc, rel))
            info.external_attr = (0o120777 << 16)
            info.create_system = 3
            zf.writestr(info, os.readlink(path))
        elif path.is_file():
            info = zipfile.ZipInfo.from_file(path, "%s/%s" % (arc, rel))
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as fh:
                zf.writestr(info, fh.read())
        n += path.is_file()
    return n


def _text(zf: zipfile.ZipFile, name: str, text: str, mode: int = 0o644) -> None:
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.external_attr = (0o100000 | mode) << 16
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, text)


def portable(seed: Path, out_dir: Path, version: str, platform: str | None = None, runtime: Path | None = None,
             launcher: Path | None = None, app_bundle: Path | None = None) -> dict:
    """Loki-<v>-<os>-portable.zip: LOKI/ with seed/, the launcher, the bootstrap, a start file and (when
    given) the bundled runtime. macOS: when app_bundle (LOKI.app from tools/macos/make_dmg.sh) is given,
    the zip holds that app instead (it carries everything inside)."""
    osn = os_name(platform)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "Loki-%s-%s-portable.zip" % (version, osn)
    zpath = out_dir / name
    inst = REPO / "packaging" / "installer"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        if osn == "macos" and app_bundle is not None and app_bundle.is_dir():
            count = _add_tree(zf, app_bundle, "LOKI.app")
            _text(zf, "README.txt", UNIX_README)
        else:
            count = _add_tree(zf, seed, "LOKI/seed")
            zf.write(inst / "loki_launch.py", "LOKI/loki_launch.py")
            if osn == "windows":
                zf.write(inst / "bootstrap.ps1", "LOKI/bootstrap.ps1")
                if launcher is not None and launcher.is_file():
                    zf.write(launcher, "LOKI/Loki.exe")
                else:
                    _text(zf, "LOKI/Start LOKI.cmd", START_CMD)
                _text(zf, "LOKI/README.txt", WINDOWS_README.replace("\n", "\r\n"))
            else:
                info = zipfile.ZipInfo.from_file(inst / "bootstrap.sh", "LOKI/bootstrap.sh")
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, (inst / "bootstrap.sh").read_bytes())
                if launcher is not None and launcher.is_file():
                    info = zipfile.ZipInfo.from_file(launcher, "LOKI/Loki")
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, launcher.read_bytes())
                _text(zf, "LOKI/start-loki.sh", START_SH, 0o755)
                _text(zf, "LOKI/README.txt", UNIX_README)
            if runtime is not None and (runtime / "python").is_dir():
                count += _add_tree(zf, runtime, "LOKI/runtime")
    data_len = zpath.stat().st_size
    return {"zip": str(zpath), "os": osn, "files": count, "size": data_len, "sha256": sha256_file(zpath),
            "bundled_python": bool(runtime is not None and (runtime / "python").is_dir()) or (osn == "macos" and app_bundle is not None)}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ friends
def export_head(repo: Path, dest: Path) -> str:
    """`git archive HEAD` into dest: committed, tracked files only (no working-tree edits, nothing
    untracked, nothing ignored like harness_data or .env). Returns the commit."""
    data = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "HEAD"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        try:
            tf.extractall(dest, filter="data")   # no absolute paths, no .., no device files
        except TypeError:   # Python < 3.12
            tf.extractall(dest)  # noqa: S202 - our own git archive
    return git_commit(repo)


def dirty(repo: Path) -> list:
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def friends(repo: Path, dist: Path, version: str, feed: str, notes: str, runtime: Path | None, launcher: Path | None,
            bundle: bool = False, platform: str | None = None) -> dict:
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="loki-friends-") as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        commit = export_head(repo, src)
        rel = build(src, dist / "release", version, feed, notes, commit=commit)
    seed = Path(rel["seed"])
    if bundle and runtime is None:
        runtime = dist / "runtime"
        subprocess.run([sys.executable, str(REPO / "tools" / "bundle_runtime.py"), "--out", str(runtime), "--seed", str(seed)], check=True)
    if runtime is None and (dist / "runtime" / "python").is_dir():
        runtime = dist / "runtime"
    app_bundle = None
    if os_name(platform) == "macos" and shutil.which("hdiutil"):
        env = dict(os.environ, LOKI_SEED=str(seed), LOKI_DIST=str(dist), LOKI_RUNTIME=str(runtime or ""), LOKI_NO_DMG="1")
        if subprocess.run(["bash", str(REPO / "tools" / "macos" / "make_dmg.sh")], env=env).returncode == 0:
            app_bundle = dist / "dmg-stage" / "Loki.app"
    port = portable(seed, dist, version, platform, runtime, launcher, app_bundle)
    left = dirty(repo)
    lines = ["LOKI %s for friends (commit %s)" % (version, commit), "",
             "Send: %s  (%.0f MB, sha256 %s)" % (Path(port["zip"]).name, port["size"] / 2**20, port["sha256"]),
             "      %s" % ("Python is inside: no download at first start" if port["bundled_python"]
                           else "no bundled Python: the first start downloads it once (build dist/runtime with "
                                "tools/bundle_runtime.py, or --bundle-runtime, to avoid that)"),
             "Also built: release/%s  (the update zip installed copies download - not for people)" % Path(rel["zip"]).name, "",
             "Installers: the Windows .exe and the macOS .dmg come from GitHub Actions (Installers workflow) -",
             "see docs/TESTERS.md. Secret scan: clean."]
    if left:
        lines += ["", "NOTE: %d uncommitted change(s) are NOT in these zips (only the last commit is)." % len(left)]
    (dist / "FRIENDS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"commit": commit, "release": rel, "portable": port, "uncommitted": left}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a LOKI release (seed tree + zip + manifest), portable zips, the friends kit.")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out", default=str(REPO / "dist" / "release"))
    ap.add_argument("--dist", default=str(REPO / "dist"), help="where --portable / --friends put their zips")
    ap.add_argument("--version", default="")
    ap.add_argument("--feed", default=os.environ.get("LOKI_RELEASE_FEED", "") or DEFAULT_FEED,
                    help="where installed LOKIs look for updates (default: LOKI's GitHub Releases)")
    ap.add_argument("--asset-base", default=os.environ.get("LOKI_ASSET_BASE", ""),
                    help="absolute URL folder of the zip (GitHub: .../releases/download/<tag>)")
    ap.add_argument("--notes", default="")
    ap.add_argument("--portable", action="store_true", help="also the portable zip for this OS")
    ap.add_argument("--friends", action="store_true", help="the shareable zip(s) from the last commit, scanned")
    ap.add_argument("--runtime", default="", help="a bundled runtime (tools/bundle_runtime.py output) to put inside")
    ap.add_argument("--bundle-runtime", action="store_true", help="--friends: make dist/runtime first (needs uv + internet)")
    ap.add_argument("--launcher", default="", help="the built Rust launcher (Loki.exe / Loki) to put inside")
    ap.add_argument("--platform", default="", help="pretend to be win32/darwin/linux (tests)")
    ap.add_argument("--from-seed", default="", help="--portable from an already built seed (CI's OS jobs), no new build")
    args = ap.parse_args()
    repo, out, dist = Path(args.repo).resolve(), Path(args.out).resolve(), Path(args.dist).resolve()
    version = args.version or release_version(repo)
    runtime = Path(args.runtime).resolve() if args.runtime else None
    launcher = Path(args.launcher).resolve() if args.launcher else None
    try:
        if args.from_seed:
            seed = Path(args.from_seed).resolve()
            info = json.loads((seed / "RELEASE.json").read_text(encoding="utf-8"))
            findings = secret_scan.scan(seed)
            if findings:
                raise SecretFound(findings)
            if runtime is None and (dist / "runtime" / "python").is_dir():
                runtime = dist / "runtime"
            print(json.dumps(portable(seed, dist, str(info["version"]), args.platform or None, runtime, launcher), indent=2))
            return 0
        if args.friends:
            result = friends(repo, dist, version, args.feed, args.notes, runtime, launcher, args.bundle_runtime, args.platform or None)
            print(json.dumps({"portable": result["portable"], "zip": result["release"]["zip"], "commit": result["commit"],
                              "uncommitted": len(result["uncommitted"])}, indent=2))
            print((dist / "FRIENDS.txt").read_text(encoding="utf-8"))
            return 0
        out.mkdir(parents=True, exist_ok=True)
        result = build(repo, out, version, args.feed, args.notes, asset_base=args.asset_base)
        if args.portable:
            if runtime is None and (dist / "runtime" / "python").is_dir():
                runtime = dist / "runtime"
            result["portable"] = portable(Path(result["seed"]), dist, version, args.platform or None, runtime, launcher)
    except SecretFound as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
