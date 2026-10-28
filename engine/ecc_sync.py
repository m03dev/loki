"""Fetch agent/skill libraries from GitHub into harness_data/vendor.

Standard library only - it downloads each repository zip over HTTPS, so it works
with no git and no extra packages. Usable as a module or a CLI:

    python ecc_sync.py            # fetch anything missing
    python ecc_sync.py --force    # re-download everything
    python ecc_sync.py --status   # report what is installed

Every source follows the SAME convention - `agents/*.md` and `skills/<name>/SKILL.md`
- so loki.py loads them all through one loader:

  ECC                general-purpose agent + skill library (affaan-m/ECC)
  GodotPrompter      Godot 4 domain skills + agents (jame581/GodotPrompter)
  Superpowers        the core agentic-workflow skills (obra/superpowers)
  awesome-gamedev    game-dev skills across engines (gamedev-skills/...)
  gamedev-plugin     game design/engineering/narrative skills (fcsouza/agent-skills)
  ponytail           the "lazy senior dev" coding standard (AGENTS.md only)

Premade specialists and real references for the Prompt Expert and every agent (owner 2026-10-28: "needs real ref
... we need premade, just add them to loki"; engine/prompt_library.py picks from them per task):

  wshobson-agents      ~180 agents + ~185 skills across dev, content, design, game dev (wshobson/agents, MIT)
  voltagent-subagents  ~130 specialist agents in 10 categories (VoltAgent/awesome-claude-code-subagents, MIT)
  nano-banana-prompts  real image prompts with the pictures they made (YouMind-OpenLab, CC BY 4.0)
  gpt-image-prompts    the same for GPT Image 2 (YouMind-OpenLab, CC BY 4.0)
  chatgpt-prompts      ~2,700 role prompts for any task (f/awesome-chatgpt-prompts, CC0)
  wan-prompts          Alibaba's own Wan2.2 video prompt rules (Wan-Video/Wan2.2, Apache-2.0)

Sources that need only a few files use "raw" (each file straight from raw.githubusercontent.com) instead of the
repository zip - the prompts repository's zip is over 200 MB for one 9 MB file.
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
    """Downloads belong with the rest of the user data, not inside engine/."""
    explicit = os.getenv("LOKI_DATA", "").strip()
    if explicit:
        return Path(explicit)
    return ROOT.parent / "harness_data"


VENDOR = _data_dir() / "vendor"

# name -> repo, and which top-level folders to keep (None keeps everything).
SOURCES = {
    "ECC": {"repo": "affaan-m/ECC", "keep": ("agents", "skills")},
    "GodotPrompter": {"repo": "jame581/GodotPrompter", "keep": ("agents", "skills")},
    "Superpowers": {"repo": "obra/superpowers", "keep": ("skills",)},
    "awesome-gamedev": {"repo": "gamedev-skills/awesome-gamedev-agent-skills",
                        "keep": ("skills", "router")},
    "gamedev-plugin": {"repo": "fcsouza/agent-skills", "keep": ("plugins/game-dev",)},
    "agentic-gamedev": {"repo": "abagames/agentic-gamedev-skills", "keep": (".agents",)},
    "ponytail": {"repo": "DietrichGebert/ponytail", "keep": None,
                 "files": ("AGENTS.md", "LICENSE")},
    "wshobson-agents": {"repo": "wshobson/agents", "keep": ("plugins", "LICENSE")},
    "voltagent-subagents": {"repo": "VoltAgent/awesome-claude-code-subagents", "keep": ("categories", "LICENSE")},
    "nano-banana-prompts": {"repo": "YouMind-OpenLab/awesome-nano-banana-pro-prompts", "raw": ("README.md", "LICENSE")},
    "gpt-image-prompts": {"repo": "YouMind-OpenLab/awesome-gpt-image-2", "raw": ("README.md", "LICENSE")},
    "chatgpt-prompts": {"repo": "f/awesome-chatgpt-prompts", "raw": ("prompts.csv", "LICENSE-CC0")},
    "wan-prompts": {"repo": "Wan-Video/Wan2.2", "raw": ("wan/utils/system_prompt.py", "LICENSE.txt")},
}
_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

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


def _fetch_raw(repo: str, files: tuple, target: Path) -> int:
    """Each file on its own; the first file decides the branch. A missing extra (a LICENSE) is not an error."""
    written = 0
    for branch in _BRANCHES:
        for i, path in enumerate(files):
            try:
                request = urllib.request.Request(_RAW.format(repo=repo, branch=branch, path=path),
                                                 headers={"User-Agent": "loki-ecc-sync"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = response.read()
            except Exception:
                if i == 0:
                    break
                continue
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            written += 1
        if written:
            return written
    raise RuntimeError(f"could not download {repo}")


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
        if folders and not relative.startswith(folders) and relative not in keep:
            continue
        if files and relative not in files:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(member))
        written += 1
    return written


def head_sha(repo: str) -> str:
    """The commit the branch is at right now (so the upstream check knows what LOKI has); "" when GitHub can't say."""
    for branch in _BRANCHES:
        try:
            request = urllib.request.Request("https://api.github.com/repos/%s/commits/%s" % (repo, branch),
                                             headers={"User-Agent": "loki-ecc-sync", "Accept": "application/vnd.github.sha"})
            with urllib.request.urlopen(request, timeout=8) as response:
                sha = response.read().decode("ascii", "replace").strip()
                if len(sha) >= 7:
                    return sha[:40]
        except Exception:
            continue
    return ""


def sync(force: bool = False, log=print, only: tuple | list | None = None) -> dict:
    """Download each source unless it is already present (or force is set). `only` = just these source names (the
    upstream check's Adopt refreshes one library)."""
    report: dict = {}
    for name, spec in SOURCES.items():
        if only and name not in only:
            continue
        target = VENDOR / name
        marker = target / ".loki_sync.json"
        if target.is_dir() and marker.exists() and not force:
            report[name] = json.loads(marker.read_text(encoding="utf-8")).get("files", 0)
            continue
        try:
            if spec.get("raw"):
                count = _fetch_raw(spec["repo"], spec["raw"], target)
            else:
                count = _extract(spec["repo"], spec.get("keep"), spec.get("files"), target)
        except Exception as exc:
            log(f"[sync] {name}: failed - {exc}")
            report[name] = f"error: {exc}"
            continue
        marker.write_text(
            json.dumps({"repo": spec["repo"], "files": count, "when": time.time(), "sha": head_sha(spec["repo"])}),
            encoding="utf-8",
        )
        log(f"[sync] {name}: {count} files from {spec['repo']}")
        report[name] = count
    return report


def _count(root: Path, kind: str) -> int:
    """Count agents/skills recursively - repositories nest them differently."""
    if not root.is_dir():
        return 0
    if kind == "agents":
        return len(list(root.glob("**/agents/*.md"))) + len(
            [p for p in root.glob("categories/*/*.md") if p.name.lower() != "readme.md"])
    return len(list(root.glob("**/SKILL.md")))


def installed() -> dict:
    """What is on disk right now, per source and in total."""
    sources: dict = {}
    agents = skills = 0
    for name in SOURCES:
        if name == "ponytail":
            sources[name] = (VENDOR / name / "AGENTS.md").is_file()
            continue
        a, s = _count(VENDOR / name, "agents"), _count(VENDOR / name, "skills")
        sources[name] = {"agents": a, "skills": s}
        agents += a
        skills += s
    return {"sources": sources, "totals": {"agents": agents, "skills": skills}}


def missing() -> list:
    """Sources whose download marker is absent (never fetched)."""
    return [name for name in SOURCES if not (VENDOR / name / ".loki_sync.json").exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the agent/skill libraries.")
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
