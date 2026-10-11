"""Fetch the ECC agent/skill library from GitHub into harness/vendor.

Standard library only - it downloads the repository zip over HTTPS, so it
works with no git and no extra packages. Usable as a module or a CLI:

    python ecc_sync.py            # fetch anything missing
    python ecc_sync.py --force    # re-download everything
    python ecc_sync.py --status   # report what is installed
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _data_dir() -> Path:
    """Downloads belong with the rest of the user data, not inside the addon."""
    explicit = os.getenv("LOKI_DATA", "").strip()
    if explicit:
        return Path(explicit)
    for candidate in (ROOT, *ROOT.parents):
        if (candidate / "project.godot").is_file():
            return candidate / "harness_data"
    return ROOT / "harness_data"


VENDOR = _data_dir() / "vendor"

# name -> repo, and which top-level folders to keep (None keeps everything)
SOURCES = {
    "ECC": {"repo": "affaan-m/ECC", "keep": ("agents", "skills")},
    "ponytail": {"repo": "DietrichGebert/ponytail", "keep": None,
                 "files": ("AGENTS.md", "LICENSE")},
}

_ZIP = "https://codeload.github.com/{repo}/zip/refs/heads/{branch}"
_BRANCHES = ("main", "master")


def _download(repo: str) -> bytes | None:
    for branch in _BRANCHES:
        try:
            request = urllib.request.Request(
                _ZIP.format(repo=repo, branch=branch),
                headers={"User-Agent": "loki-ecc-sync"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except Exception:
            continue
    return None


def _extract(repo: str, keep: tuple | None, files: tuple | None, target: Path) -> int:
    data = _download(repo)
    if data is None:
        raise RuntimeError(f"could not download {repo}")
    archive = zipfile.ZipFile(io.BytesIO(data))
    prefix = archive.namelist()[0].split("/")[0] + "/"
    folders = tuple(f"{part}/" for part in keep) if keep else ()
    written = 0
    for member in archive.namelist():
        relative = member[len(prefix):]
        if not relative or member.endswith("/"):
            continue
        if folders and not relative.startswith(folders):
            continue
        if files and relative not in files:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(member))
        written += 1
    return written


def sync(force: bool = False, log=print) -> dict:
    """Download each source unless it is already present (or force is set)."""
    report: dict = {}
    for name, spec in SOURCES.items():
        target = VENDOR / name
        marker = target / ".loki_sync.json"
        if target.is_dir() and marker.exists() and not force:
            report[name] = json.loads(marker.read_text(encoding="utf-8")).get("files", 0)
            continue
        try:
            count = _extract(spec["repo"], spec.get("keep"), spec.get("files"), target)
        except Exception as exc:
            log(f"[ecc] {name}: failed - {exc}")
            report[name] = f"error: {exc}"
            continue
        marker.write_text(
            json.dumps({"repo": spec["repo"], "files": count, "when": time.time()}),
            encoding="utf-8",
        )
        log(f"[ecc] {name}: {count} files from {spec['repo']}")
        report[name] = count
    return report


def installed() -> dict:
    """What is on disk right now."""
    agents_dir = VENDOR / "ECC" / "agents"
    skills_dir = VENDOR / "ECC" / "skills"
    return {
        "agents": len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0,
        "skills": len(list(skills_dir.glob("*/SKILL.md"))) if skills_dir.is_dir() else 0,
        "ponytail": (VENDOR / "ponytail" / "AGENTS.md").is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the ECC agent library.")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument("--status", action="store_true", help="report what is installed")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(installed(), indent=2))
        return 0

    report = sync(force=args.force)
    print(json.dumps({"synced": report, "installed": installed()}, indent=2))
    return 0 if not any(isinstance(v, str) for v in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
