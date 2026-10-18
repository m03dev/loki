"""Godogen in LOKI: describe a game, a coding agent builds it in ~/LOKI Projects/<name>.

Godogen (github.com/htdt/godogen, MIT, Alex Ermolov) is not a game engine: it is a small set of
instructions that turn a coding agent (Claude Code, Codex, ...) into a game developer that builds,
generates assets, runs the engine and proves the result. Its `publish.sh` renders those
instructions into a fresh game repo; the agent then works inside that repo.

This module is that publish step ported to Python (publish.sh + scripts/render_dir.py +
scripts/generate_codex_metadata.py, no shell), reading godogen's own text from
contrib/godogen/ (commit in contrib/godogen/PROVENANCE.md), plus LOKI's entry point:

    publish(engine, agent, target)          -> writes CLAUDE.md or AGENTS.md, <engine>.md and the
                                               asset-gen skill into `target` (a game folder)
    plan_game(description, name, ...)       -> {"workspace", "agent", "engine", "prompt", ...}
    make_godot_game(description, name, ...) -> publish + a background job spec (the caller starts it)

Rules kept from LOKI: the game lives in ~/LOKI Projects/<name> (LOKI_PROJECTS_DIR), never in the
repo; nothing runs a shell string; the job is started by the engine's job supervisor, so the owner
approves it and sees it above the message box like every other background job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "contrib" / "godogen"

# engine -> (display name, folder the running game loads generated assets from)
ENGINES = {
    "godot": ("Godot", "assets"),                    # C# (needs the .NET build of Godot)
    "godot-gdscript": ("Godot", "assets"),           # GDScript: any Godot 4 build (LOKI's default)
    "bevy": ("Bevy", "assets"),
    "babylon": ("Babylon.js", "src/assets"),
    "threejs": ("three.js", "src/assets"),
}
DEFAULT_ENGINE = "godot-gdscript"
# How each coding agent reads its instructions: Claude Code reads CLAUDE.md + .claude/skills,
# the rest read AGENTS.md (+ .agents/skills, Codex's layout).
FLAVORS = {
    "claude": {"manifest": "CLAUDE.md", "skills": ".claude/skills", "name": "Claude", "command": "/asset-gen"},
    "codex": {"manifest": "AGENTS.md", "skills": ".agents/skills", "name": "Codex", "command": "$asset-gen"},
}
AGENT_FLAVOR = {"claude-code": "claude", "codex": "codex", "opencode": "codex", "nanocoder": "codex",
                "openhands": "codex", "hermes": "codex", "loki": "codex"}
# "auto" picks the first installed agent in this order; LOKI's own agent always works.
AUTO_ORDER = ("claude-code", "codex", "opencode", "nanocoder")
AGENT_EXE = {"claude-code": "claude", "codex": "codex", "opencode": "opencode", "nanocoder": "nanocoder"}
MAX_DESCRIPTION = 4000


class GodogenError(ValueError):
    """A readable reason the game could not be set up."""


def projects_dir(env: dict | None = None) -> Path:
    env = env if env is not None else os.environ
    return Path(env.get("LOKI_PROJECTS_DIR") or (Path.home() / "LOKI Projects"))


def slug(text: str, limit: int = 40) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:limit].strip("-")
    return out or "game"


# ------------------------------------------------------------------ godogen's publish, in Python
def render_text(text: str, values: dict) -> str:
    """render_dir.py: replace every ${KEY} token with its value (only the keys given)."""
    for key, value in values.items():
        text = text.replace("${%s}" % key, str(value))
    return text


def render_dir(root: Path, values: dict) -> int:
    """render_dir.py over a tree: text files only, symlinks skipped. Returns files changed."""
    changed = 0
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = render_text(text, values)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def _frontmatter(text: str) -> dict:
    """generate_codex_metadata.py's parse_frontmatter: simple `key: value` and `key: |` blocks."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    lines = text[4:end].splitlines()
    data: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or ":" not in line:
            i += 1
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if value == "|":
            i += 1
            block = []
            while i < len(lines):
                cand = lines[i]
                if cand and not cand.startswith(" ") and ":" in cand:
                    break
                block.append(cand[2:] if cand.startswith("  ") else cand)
                i += 1
            data[key] = "\n".join(block).strip()
            continue
        data[key] = value.lower() == "true" if value.lower() in ("true", "false") else value.strip("\"'")
        i += 1
    return data


def codex_metadata(skill_dir: Path) -> None:
    """generate_codex_metadata.py: agents/openai.yaml from the skill's SKILL.md frontmatter."""
    skill = Path(skill_dir) / "SKILL.md"
    if not skill.is_file():
        return
    meta = _frontmatter(skill.read_text(encoding="utf-8"))
    name = str(meta.get("name") or Path(skill_dir).name)
    description = " ".join(str(meta.get("description") or "").split())
    if len(description) > 120:
        description = description[:117].rstrip() + "..."
    display = str(meta.get("display_name") or " ".join(p.capitalize() for p in re.split(r"[-_]+", name) if p))
    lines = ["interface:", "  display_name: %s" % json.dumps(display),
             "  short_description: %s" % json.dumps(str(meta.get("short_description") or description or display)),
             "  default_prompt: %s" % json.dumps(str(meta.get("default_prompt") or "Use $%s when this skill is relevant." % name))]
    if "allow_implicit_invocation" in meta:
        lines += ["", "policy:", "  allow_implicit_invocation: %s" % ("true" if meta["allow_implicit_invocation"] else "false")]
    out = Path(skill_dir) / "agents"
    out.mkdir(parents=True, exist_ok=True)
    (out / "openai.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def assets_checkout(env: dict | None = None) -> str:
    """godogen_assets (local GPU asset generators) when the owner set it up, else "none" (paid APIs only)."""
    env = env if env is not None else os.environ
    path = str(env.get("LOKI_GODOGEN_ASSETS") or "").strip()
    if path and (Path(path) / "README.md").is_file() and (Path(path) / "bin").is_dir():
        return path
    return "none"


def gitignore_lines(engine: str, flavor: str) -> list:
    lines = [".claude", "CLAUDE.md"] if flavor == "claude" else [".agents", "AGENTS.md", ".codex"]
    lines += ["%s.md" % engine, "/tripo-out"]
    lines += {"godot": ["assets", "screenshots", ".godot", "*.import", "bin/", "obj/"],
              "godot-gdscript": ["assets", "screenshots", ".godot", "*.import"],
              "bevy": ["/target", "/screenshots"]}.get(engine, ["/node_modules", "/dist", "/screenshots"])
    return lines


def publish(engine: str, flavor: str, target: Path, env: dict | None = None, source: Path | None = None,
            runner=subprocess.run) -> dict:
    """publish.sh: render godogen's runtime files for `engine` and the agent `flavor` into `target`."""
    if engine not in ENGINES:
        raise GodogenError("engine must be one of " + ", ".join(ENGINES))
    if flavor not in FLAVORS:
        raise GodogenError("agent flavor must be claude or codex")
    source = Path(source or SOURCE)
    if not (source / "prompts" / "runtime.md").is_file():
        raise GodogenError("godogen's files are missing (contrib/godogen)")
    spec = FLAVORS[flavor]
    display, asset_dir = ENGINES[engine]
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    skill_dir = target / spec["skills"] / "asset-gen"
    if skill_dir.exists():
        shutil.rmtree(skill_dir)                     # rsync --delete: always the current skill
    shutil.copytree(source / "asset-gen", skill_dir, ignore=shutil.ignore_patterns("__pycache__"))
    render_dir(skill_dir, {"AGENT_NAME": spec["name"], "ASSET_GEN_SKILL_DIR": spec["skills"] + "/asset-gen",
                           "ASSET_SKILL_COMMAND": spec["command"], "RUNTIME_ASSET_DIR": asset_dir,
                           "GODOGEN_ASSETS": assets_checkout(env)})
    if flavor == "codex":
        codex_metadata(skill_dir)
    manifest = render_text((source / "prompts" / "runtime.md").read_text(encoding="utf-8"),
                           {"ENGINE_NAME": display, "ENGINE_GUIDE_FILE": "%s.md" % engine,
                            "ASSET_SKILL_COMMAND": spec["command"]})
    (target / spec["manifest"]).write_text(manifest, encoding="utf-8")
    shutil.copyfile(source / "engines" / ("%s.md" % engine), target / ("%s.md" % engine))
    written = [spec["manifest"], "%s.md" % engine, spec["skills"] + "/asset-gen/"]
    ignore = target / ".gitignore"
    if not ignore.exists():
        ignore.write_text("\n".join(gitignore_lines(engine, flavor)) + "\n", encoding="utf-8")
        written.append(".gitignore")
    git = shutil.which("git")
    if git and not (target / ".git").exists():
        try:
            runner([git, "init", "-q"], cwd=str(target), capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass                                     # git is a nicety; the game works without it
    return {"ok": True, "target": str(target), "manifest": spec["manifest"], "written": written,
            "assets": assets_checkout(env)}


# ------------------------------------------------------------------ LOKI's entry point
def pick_agent(agent: str = "auto", which=shutil.which) -> str:
    agent = str(agent or "auto").strip().lower()
    if agent != "auto":
        if agent not in AGENT_FLAVOR:
            raise GodogenError("agent must be auto or one of " + ", ".join(AGENT_FLAVOR))
        return agent
    for name in AUTO_ORDER:
        if which(AGENT_EXE[name]):
            return name
    return "loki"


def job_prompt(description: str, engine: str, manifest: str) -> str:
    display = ENGINES[engine][0]
    return ("Build this %s game in the current folder: %s\n\n"
            "Read %s first and follow it (the runtime process), then %s.md (the engine guide). Keep "
            "README.md as the project status. Ask before any paid asset generation. Work only inside "
            "this folder. When you stop, say what runs, what is left, and how to run it."
            % (display, description.strip(), manifest, engine))


def plan_game(description: str, name: str = "", engine: str = DEFAULT_ENGINE, agent: str = "auto",
              env: dict | None = None, which=shutil.which) -> dict:
    """Everything make_godot_game will do, without touching the disk."""
    description = " ".join(str(description or "").split())
    if not description:
        raise GodogenError("describe the game first")
    if len(description) > MAX_DESCRIPTION:
        raise GodogenError("the description is longer than %d characters" % MAX_DESCRIPTION)
    engine = str(engine or DEFAULT_ENGINE).strip().lower()
    if engine not in ENGINES:
        raise GodogenError("engine must be one of " + ", ".join(ENGINES))
    chosen = pick_agent(agent, which)
    flavor = AGENT_FLAVOR[chosen]
    folder = slug(name or description)
    workspace = projects_dir(env) / folder
    manifest = FLAVORS[flavor]["manifest"]
    return {"workspace": str(workspace), "name": folder, "engine": engine, "agent": chosen, "flavor": flavor,
            "manifest": manifest, "prompt": job_prompt(description, engine, manifest),
            "title": "Godogen: %s" % description[:60]}


def make_godot_game(description: str, name: str = "", engine: str = DEFAULT_ENGINE, agent: str = "auto",
                    env: dict | None = None, which=shutil.which, runner=subprocess.run) -> dict:
    """Publish godogen into ~/LOKI Projects/<name> and return the background job spec to start."""
    plan = plan_game(description, name, engine, agent, env, which)
    target = Path(plan["workspace"])
    if target.exists() and any(target.iterdir()) and not (target / plan["manifest"]).is_file():
        raise GodogenError("%s already exists and is not a godogen game - pick another name" % target)
    published = publish(plan["engine"], plan["flavor"], target, env=env, runner=runner)
    job = {"backend": "local", "agent": plan["agent"], "prompt": plan["prompt"], "workspace": str(target),
           "isolate": False, "title": plan["title"], "allow_commands": True, "timeout_s": 4 * 3600}
    return {"ok": True, **plan, "published": published, "job": job}
