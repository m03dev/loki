"""Build a LOKI release for the installers and the release updater (engine/release_update.py).

    python tools/make_release.py --feed https://example.org/loki/manifest.json
    python tools/make_release.py --out dist/release --version 0.16.500 --notes "what changed"

Writes into --out (default dist/release):
    seed/                 the LOKI tree the installers bundle (with RELEASE.json)
    Loki-<version>.zip    the same tree, for updates
    manifest.json         {version, url, sha256, size, notes, min_launcher}  -> upload next to the zip
    manifest.json.sig     only when LOKI_SIGNING_KEY points at the private key (tools/loki_sign.py)

Only files git tracks go in (never harness_data, keys you made, models or venvs), and not what an
installed LOKI never runs (tests, the phone app, the cloud relay, CI, the big design docs).
The version is VERSION + the patch number ("0.16" + 412 commits -> "0.16.412").
Installed LOKIs refuse an unsigned feed unless LOKI_RELEASE_REQUIRE_SIG=0, so sign what you publish.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER_VERSION = 1
SKIP_TOP = ("tests", "mobile", "cloud", ".github")   # packaging/installer stays: the launcher updates itself from it
KEEP_DOCS = ("docs/help/", "docs/INSTALL.md", "docs/THIRD_PARTY.md")


def tracked(repo: Path, untracked: bool = False) -> list:
    """git-tracked files; with untracked=True also new files git does not ignore (tests, local builds)."""
    args = ["git", "-C", str(repo), "ls-files", "-z"] + (["-co", "--exclude-standard"] if untracked else [])
    out = subprocess.run(args, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def wanted(path: str) -> bool:
    top = path.split("/", 1)[0]
    if top in SKIP_TOP or top.startswith("harness_data"):
        return False
    if top == "docs":
        return path.startswith(KEEP_DOCS)
    return not path.endswith((".pyc",)) and "/__pycache__/" not in path


def release_version(repo: Path) -> str:
    sys.path.insert(0, str(repo / "engine"))
    import updater  # pylint: disable=import-outside-toplevel
    info = updater.version(repo)
    return "%s.%d" % (info.get("version") or "0.0", info.get("patch") or 0)


def build(repo: Path, out: Path, version: str, feed: str, notes: str, untracked: bool = False, compress: bool = True) -> dict:
    files = [p for p in sorted(set(tracked(repo, untracked))) if wanted(p) and (repo / p).is_file()]
    seed = out / "seed"
    shutil.rmtree(seed, ignore_errors=True)
    for rel in files:
        dst = seed / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, dst)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True).stdout.strip()
    info = {"version": version, "feed": feed, "commit": commit, "built": int(time.time()), "launcher": LAUNCHER_VERSION}
    (seed / "RELEASE.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    name = "Loki-%s.zip" % version
    zpath = out / name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as zf:
        for path in sorted(seed.rglob("*")):
            if path.is_file():
                zf.write(path, "Loki-%s/%s" % (version, path.relative_to(seed).as_posix()))
    data = zpath.read_bytes()
    manifest = {"version": version, "url": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                "notes": notes, "min_launcher": LAUNCHER_VERSION, "commit": commit}
    mpath = out / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    signed = False
    if os.environ.get("LOKI_SIGNING_KEY"):
        proc = subprocess.run([sys.executable, str(repo / "tools" / "loki_sign.py"), "sign", str(mpath)], capture_output=True, text=True)
        signed = proc.returncode == 0
        if not signed:
            print("signing failed: " + (proc.stdout + proc.stderr).strip(), file=sys.stderr)
    return {"files": len(files), "zip": str(zpath), "manifest": str(mpath), "signed": signed, **manifest}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a LOKI release (seed tree + zip + manifest).")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out", default=str(REPO / "dist" / "release"))
    ap.add_argument("--version", default="")
    ap.add_argument("--feed", default=os.environ.get("LOKI_RELEASE_FEED", ""), help="where installed LOKIs look for updates")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()
    repo, out = Path(args.repo).resolve(), Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = build(repo, out, args.version or release_version(repo), args.feed, args.notes)
    print(json.dumps(result, indent=2))
    if not args.feed:
        print("note: no --feed given; installed copies of this release will not look for updates", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
