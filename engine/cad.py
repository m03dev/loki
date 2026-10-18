"""CAD in LOKI: CADCraft, an open-source AutoCAD-style drafting program, driven by LOKI.

CADCraft (github.com/storytold/cadcraft, MIT OR Apache-2.0, pure Rust, ~180k lines) is a
separate program: LOKI does not re-implement it, it drives it.
  * LOKI's agents talk to it over MCP (engine/mcp_servers.json "cadcraft": `cadcraft-cli mcp`,
    tools command_line / execute / inspect_drawing / query_entities / render), so "draw me a
    floor plan 6 x 4 m with a door" becomes real CAD commands in a real DXF.
  * This module finds or installs `cadcraft-cli` and runs it headless for the window and for
    creations: a command script -> a .dxf and a .png / .svg / .pdf preview.

Install (python tools/setup_extras.py cadcraft): the official release build for this machine
from GitHub Releases, its SHA-256 checked against the release's SHA256SUMS.txt, unpacked into
<data>/addons/cadcraft. Windows: the portable zip (cadcraft.exe + cadcraft-cli.exe); macOS: the
signed, notarized universal cadcraft-cli zip. Nothing runs through a shell string.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "storytold/cadcraft"
RELEASES = "https://api.github.com/repos/%s/releases/latest" % REPO
LICENSE = "MIT OR Apache-2.0"
EXE = "cadcraft-cli.exe" if os.name == "nt" else "cadcraft-cli"


def data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def install_dir() -> Path:
    return data_dir() / "addons" / "cadcraft"


def cli_path() -> str:
    """Where cadcraft-cli is on this machine, or "" (env > LOKI's add-on folder > PATH > the Mac app)."""
    explicit = os.getenv("LOKI_CADCRAFT_CLI", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    base = install_dir()
    if base.is_dir():
        for found in sorted(base.rglob(EXE)):
            if found.is_file():
                return str(found)
    on_path = shutil.which("cadcraft-cli")
    if on_path:
        return on_path
    if sys.platform == "darwin":
        app = Path("/Applications/CADCraft.app/Contents/MacOS/cadcraft-cli")
        if app.is_file():
            return str(app)
    return ""


def asset_patterns(system: str | None = None, machine: str | None = None) -> list:
    """Which release files fit this computer, best first (name fragments)."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "windows":
        arch = "arm64" if machine in ("arm64", "aarch64") else ("x86" if machine in ("x86", "i386", "i686") else "x64")
        return ["windows-%s-portable.zip" % arch]
    if system == "darwin":
        return ["cadcraft-cli-", "macos-universal.zip"]
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return ["linux-%s" % arch]


def pick_asset(assets: list, patterns: list) -> dict | None:
    """The release asset whose name has every pattern fragment (and is a .zip/.tar.gz/.AppImage)."""
    for asset in assets:
        name = str(asset.get("name", ""))
        if all(p in name for p in patterns) and not name.endswith((".sig", ".zsync", ".txt")):
            return asset
    return None


def _get(url: str, opener=urllib.request.urlopen, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Loki/1.0", "Accept": "application/octet-stream, application/json"})
    with opener(req, timeout=timeout) as resp:
        return resp.read()


def install(opener=urllib.request.urlopen, say=print) -> dict:
    """Download, verify and unpack the official build for this machine."""
    try:
        release = json.loads(_get(RELEASES, opener).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "could not read CADCraft's releases (%s)" % type(exc).__name__}
    assets = release.get("assets") or []
    asset = pick_asset(assets, asset_patterns())
    if asset is None:
        return {"ok": False, "error": "no CADCraft build for this computer in %s" % release.get("tag_name", "the latest release")}
    sums = pick_asset(assets, ["SHA256SUMS"]) or next((a for a in assets if a.get("name") == "SHA256SUMS.txt"), None)
    say("Downloading %s (%s)..." % (asset["name"], release.get("tag_name", "")))
    blob = _get(asset["browser_download_url"], opener, timeout=600)
    digest = hashlib.sha256(blob).hexdigest()
    if sums is None:
        return {"ok": False, "error": "the release has no SHA256SUMS.txt; not installing an unchecked file"}
    listed = {}
    for line in _get(sums["browser_download_url"], opener).decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            listed[parts[-1].lstrip("*")] = parts[0].lower()
    if listed.get(asset["name"]) != digest:
        return {"ok": False, "error": "checksum mismatch for %s - not installed" % asset["name"]}
    target = install_dir()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = target / asset["name"]
    archive.write_bytes(blob)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            root = target.resolve()
            for member in zf.namelist():
                if not (target / member).resolve().is_relative_to(root):
                    return {"ok": False, "error": "unsafe path in the archive: %s" % member}
            zf.extractall(target)
        archive.unlink()
    found = cli_path()
    if found and os.name != "nt":
        os.chmod(found, 0o755)
    if not found:
        return {"ok": False, "error": "unpacked %s but found no %s in it" % (asset["name"], EXE)}
    say("CADCraft %s is in %s" % (release.get("tag_name", ""), target))
    return {"ok": True, "version": release.get("tag_name", ""), "cli": found}


def run(script: str = "", source: str = "", save: str = "", export: str = "", timeout: int = 120,
        runner=subprocess.run) -> dict:
    """One headless CADCraft run: optional drawing to open, a command script, then save/export.

    cadcraft-cli run [<file>|--sample] --script '<commands>' --save out.dxf --export out.png"""
    cli = cli_path()
    if not cli:
        return {"ok": False, "error": "CADCraft is not installed (python tools/setup_extras.py cadcraft)"}
    argv = [cli, "run"]
    argv += [source] if source else []
    if script:
        argv += ["--script", script]
    if save:
        argv += ["--save", save]
    if export:
        argv += ["--export", export]
    try:
        done = runner(argv, capture_output=True, text=True, timeout=timeout,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "CADCraft took longer than %d s" % timeout}
    except OSError as exc:
        return {"ok": False, "error": "could not start CADCraft (%s)" % exc}
    out = {"ok": done.returncode == 0, "output": (done.stdout or "")[-4000:], "error": (done.stderr or "")[-2000:]}
    if save:
        out["dxf"] = save
    if export:
        out["preview"] = export
    return out


def status() -> dict:
    cli = cli_path()
    return {"installed": bool(cli), "cli": cli, "license": LICENSE, "repo": "https://github.com/" + REPO}
