"""Skill safety scan - downloaded skills are untrusted text.

A skill is a folder with a SKILL.md (YAML-style frontmatter `name`, `description`, then
instructions). Loki only ever READS a skill into the conversation; it never runs files
that come with one. Still, a skill can carry scripts, or text that tries to talk the agent
out of its rules. `scan()` reports both, before a skill's text reaches the model:

    ok       - instructions only
    review   - ships executable files (Loki will not run them), or asks to skip
               confirmations / declares tool permissions (ignored - Loki's policy decides)
    blocked  - tries to grant itself permissions or override Loki's policy/approvals

Blocked skills are not loaded. Pure, standard library only.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

EXEC_SUFFIXES = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".psm1",
                 ".bat", ".cmd", ".exe", ".dll", ".so", ".dylib", ".rb", ".pl", ".jar", ".command",
                 ".applescript", ".scpt", ".vbs"}
# Frontmatter keys a skill must not use to give itself power.
ESCALATION_KEYS = {"permissions", "auto_approve", "auto-approve", "grant", "policy", "trust",
                   "dangerously-skip-permissions"}
# Standard Agent Skills fields Loki does not honour (it has its own policy). Noted, not blocked.
IGNORED_KEYS = {"allowed-tools", "allowed_tools"}
# Text aimed at the agent's safety rules rather than at the task.
BLOCK_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|your) (instructions|rules|guidelines)",
    r"disregard (the |your )?(system prompt|safety rules|policy)",
    r"LOKI_AUTO_APPROVE\s*=\s*1",
    r"LOKI_COMMAND_POLICY\s*=\s*0",
    r"bypassPermissions",
    r"--dangerously-skip-permissions",
    r"(disable|turn off|bypass) (the |loki'?s )?(policy engine|approval prompts?|sandbox|safety checks?)",
]
# Worth a look but common in honest skills.
REVIEW_PATTERNS = [
    r"(do not|don't|never) ask (the user )?(for )?(approval|permission|confirmation)",
    r"without (asking|approval|confirmation)",
]
MAX_FILES = 400
# Extra scanners (e.g. NVIDIA SkillSpector) registered by Loki when enabled:
# callable(folder) -> [(severity, message)]. high/critical findings block the skill.
EXTERNAL_SCANNERS: list = []
BLOCKING_SEVERITIES = {"critical", "high", "error"}


def frontmatter(text: str) -> tuple[dict, str]:
    """Minimal `---` frontmatter parser: top-level `key: value` lines only."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta: dict = {}
    for line in text[3:end].splitlines():
        if not line or line[0] in " \t#-":
            continue
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4:].lstrip("\n")


def scan(skill_md: Path) -> dict:
    """{verdict, name, description, problems[], executables[]} for one SKILL.md."""
    skill_md = Path(skill_md)
    problems: list[str] = []
    executables: list[str] = []
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"verdict": "blocked", "name": skill_md.parent.name, "description": "",
                "problems": ["unreadable: %s" % exc], "executables": []}
    meta, body = frontmatter(text)
    if not meta.get("name"):
        problems.append("no name in frontmatter")
    if not meta.get("description"):
        problems.append("no description in frontmatter")
    escalations = sorted(k for k in meta if k in ESCALATION_KEYS)
    blocked = [("frontmatter key %r grants permissions" % k) for k in escalations]
    for pattern in BLOCK_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            blocked.append("tries to override Loki's rules: %r" % match.group(0)[:60])
    notes = ["frontmatter %r is ignored - Loki's policy decides" % k for k in sorted(meta) if k in IGNORED_KEYS]
    for pattern in REVIEW_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            notes.append("asks to skip confirmations: %r (Loki still asks)" % match.group(0)[:60])
    root = skill_md.parent
    for count, path in enumerate(sorted(p for p in root.rglob("*") if p.is_file())):
        if count >= MAX_FILES:
            problems.append("more than %d files; scan stopped" % MAX_FILES)
            break
        rel = str(path.relative_to(root))
        is_exec = path.suffix.lower() in EXEC_SUFFIXES
        if not is_exec and os.name != "nt":
            try:
                is_exec = bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            except OSError:
                pass
        if not is_exec:
            try:
                with path.open("rb") as handle:
                    is_exec = handle.read(2) == b"#!"
            except OSError:
                pass
        if is_exec:
            executables.append(rel)
    for scanner in list(EXTERNAL_SCANNERS):
        try:
            findings = scanner(root) or []
        except Exception:  # noqa: BLE001 - an external scanner failing never blocks on its own
            findings = []
        for severity, message in findings:
            (blocked if str(severity).lower() in BLOCKING_SEVERITIES else notes).append(
                "scanner [%s]: %s" % (severity, message))
    verdict = "blocked" if blocked else ("review" if executables or notes else "ok")
    return {"verdict": verdict, "name": meta.get("name", root.name),
            "description": meta.get("description", ""), "problems": blocked + notes + problems,
            "executables": executables, "body": body}


def safe_text(skill_md: Path, limit: int = 12000) -> str:
    """The skill as the agent should see it: refused when blocked, annotated when it
    ships scripts (which Loki never runs)."""
    report = scan(skill_md)
    if report["verdict"] == "blocked":
        return ("REFUSED: the skill %r was not loaded because it %s. Continue without it."
                % (report["name"], "; ".join(report["problems"][:3])))
    text = Path(skill_md).read_text(encoding="utf-8", errors="replace")[:limit]
    if report["executables"]:
        text = ("[Loki note: this skill ships %d executable file(s) (%s). Loki does not run "
                "files that come with a skill; follow the written guidance only.]\n\n"
                % (len(report["executables"]), ", ".join(report["executables"][:5]))) + text
    return text


def safe_doc(path: Path, limit: int = 12000) -> str:
    """A single instruction file (an agent .md): refused if it tries to override Loki's rules."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for pattern in BLOCK_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return ("REFUSED: %s was not loaded because it tries to override Loki's rules (%r). "
                    "Continue without it." % (Path(path).stem, match.group(0)[:60]))
    return text[:limit]
