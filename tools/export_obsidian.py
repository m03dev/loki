"""Export Loki's knowledge as an Obsidian vault (a human view; Loki never reads it back).

    python tools/export_obsidian.py                    # -> ~/Loki-Knowledge
    python tools/export_obsidian.py --out PATH --workspace DIR

Writes Markdown notes with [[wiki links]]: an index, your memory, the project state,
one note per capability (from its manifest), recent background jobs, and links to the
project's docs. Re-running replaces only the files it wrote (under Loki/); anything
else in the vault is left alone. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))

import manifests  # noqa: E402


def _slug(text: str) -> str:
    return re.sub(r"[^\w .-]+", "-", str(text)).strip()[:80] or "note"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def export(data_dir: Path, workspace: Path, out: Path, repo: Path = REPO) -> list[Path]:
    base = Path(out) / "Loki"
    (base / "Capabilities").mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def note(rel: str, body: str) -> None:
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
        written.append(path)

    stamp = time.strftime("%Y-%m-%d %H:%M")
    memory = _read(Path(data_dir) / "memory.md")
    note("Memory.md", "# Memory\n\nWhat Loki keeps about you and your work. Edit it in Loki "
         "(Settings > Memory); this copy is overwritten on export.\n\n" + (memory or "_empty_"))
    state_text = ""
    try:
        state = json.loads(_read(Path(data_dir) / "project_state.json") or "{}")
        state_text = "\n".join("- **%s**: %s" % (k, v if not isinstance(v, (list, dict)) else json.dumps(v))
                               for k, v in state.items()) if isinstance(state, dict) else ""
    except ValueError:
        state_text = ""
    note("Project state.md", "# Project state\n\n" + (state_text or "_no project state saved yet_"))

    registry = manifests.default_registry(repo, data_dir)
    cap_links = []
    for row in registry.present():
        perms = "\n".join("- `%s` - %s" % (p["id"], p["text"]) for p in row["permissions"]) or "- none"
        note("Capabilities/%s.md" % _slug(row["name"]),
             "# %s\n\n%s\n\n- Status: **%s**\n- Kind: %s\n- Version: %s\n- License: %s\n- Homepage: %s\n\n"
             "## Permissions\n%s\n\n[[Loki index]]"
             % (row["name"], row["description"], row["status"], row["kind"], row["version"],
                row["license"] or "-", row["homepage"] or "-", perms))
        cap_links.append("- [[%s]] - %s" % (_slug(row["name"]), row["status"]))

    jobs = []
    try:
        jobs = json.loads(_read(Path(data_dir) / "jobs.json") or "{}").get("jobs", [])
    except ValueError:
        jobs = []
    lines = ["| status | backend | job |", "|---|---|---|"]
    for job in sorted(jobs, key=lambda j: j.get("created", 0), reverse=True)[:40]:
        lines.append("| %s | %s | %s |" % (job.get("status", ""), job.get("backend", ""),
                                           str(job.get("title", "")).replace("|", "/")))
    note("Background jobs.md", "# Background jobs\n\n" + ("\n".join(lines) if jobs else "_none yet_"))

    docs = sorted((Path(workspace) / "docs").rglob("*.md")) if (Path(workspace) / "docs").is_dir() else []
    doc_lines = ["- [%s](file://%s)" % (d.relative_to(Path(workspace)).as_posix(), d.resolve().as_posix())
                 for d in docs[:200]]
    note("Project docs.md", "# Project docs\n\nOpen in the project (links are file URLs).\n\n"
         + ("\n".join(doc_lines) or "_no docs folder_"))

    note("Loki index.md", "# Loki knowledge\n\nExported %s from %s.\n\n- [[Memory]]\n- [[Project state]]\n"
         "- [[Background jobs]]\n- [[Project docs]]\n\n## Capabilities\n%s\n"
         % (stamp, workspace, "\n".join(cap_links) or "- none"))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(Path.home() / "Loki-Knowledge"))
    parser.add_argument("--workspace", default=os.environ.get("LOKI_WORKSPACE") or str(Path.home() / "LOKI Projects" / "Home"))
    parser.add_argument("--data", default=os.environ.get("LOKI_DATA") or str(REPO / "harness_data"))
    args = parser.parse_args(argv)
    files = export(Path(args.data), Path(args.workspace), Path(args.out))
    print("wrote %d notes to %s" % (len(files), Path(args.out) / "Loki"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
