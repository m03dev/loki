"""Repository review - the blueprint's repository browser (5.1) and the first steps of
the import pipeline (5.2).

Given a LOCAL folder, it reports identity, licence, size, languages, entry points and
dependencies. It only READS files and never runs them: the blueprint is explicit that a
repository being listed must not make its code executable, so nothing here executes,
imports or installs anything.

Pure functions over a Path, so they are unit-testable without network access.
"""
from __future__ import annotations

import os
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".godot",
             "dist", "build", ".idea", ".mypy_cache"}
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md", "license")
MANIFESTS = ("project.godot", "package.json", "pyproject.toml", "requirements.txt",
             "Cargo.toml", "go.mod", "setup.py", "Gemfile", "CMakeLists.txt")


def _iter_files(root: Path, limit: int = 20000):
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in filenames:
            yield Path(dirpath) / name
            seen += 1
            if seen >= limit:
                return


def review(root) -> dict:
    """Inspect a local folder. Read-only; returns a plain dict (never raises)."""
    root = Path(root)
    if not root.is_dir():
        return {"path": str(root), "error": "not a folder"}
    files = list(_iter_files(root))
    total = 0
    languages: dict = {}
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            pass
        ext = path.suffix.lower().lstrip(".") or "(no extension)"
        languages[ext] = languages.get(ext, 0) + 1
    try:
        entries = sorted(p.name for p in root.iterdir() if p.name not in SKIP_DIRS)
    except OSError:
        entries = []
    licence = next((n for n in entries if n in LICENSE_NAMES), "")
    readme = next((n for n in entries if n.lower().startswith("readme")), "")
    return {
        "path": str(root),
        "name": root.name,
        "files": len(files),
        "bytes": total,
        "licence": licence,
        "readme": readme,
        "languages": dict(sorted(languages.items(), key=lambda kv: kv[1], reverse=True)[:12]),
        "manifests": [m for m in MANIFESTS if (root / m).exists()],
        "top_level": entries[:40],
    }


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit) if unit != "B" else "%dB" % n
        n /= 1024.0
    return "%dB" % n


def render(report: dict) -> str:
    if report.get("error"):
        return "repository review failed: %s (%s)" % (report["error"], report.get("path", ""))
    langs = report.get("languages") or {}
    lines = [
        "repository: %s" % report.get("name", "?"),
        "  path        %s" % report.get("path", "?"),
        "  size        %d files, %s" % (report.get("files", 0), _human(int(report.get("bytes", 0)))),
        "  licence     %s" % (report.get("licence") or "NONE FOUND - do not reuse without checking"),
        "  readme      %s" % (report.get("readme") or "(none)"),
        "  manifests   %s" % (", ".join(report.get("manifests") or []) or "(none)"),
        "  languages   %s" % (", ".join("%s x%d" % (k, v) for k, v in list(langs.items())[:8]) or "(none)"),
        "  top level   %s" % ", ".join((report.get("top_level") or [])[:16]),
        "  note        read-only review - nothing was executed or installed",
    ]
    return "\n".join(lines)
