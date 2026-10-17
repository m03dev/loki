"""Security analyzer for commands: rate what a shell command (or tool call) would do - LOW, MEDIUM, HIGH.

Ported from OpenHands' PatternSecurityAnalyzer and its normalizer (OpenHands/software-agent-sdk,
openhands/sdk/security/defense_in_depth/pattern.py and utils._normalize), MIT - see
engine/licenses/OpenHands-MIT.txt. Standard library only.

The design kept from OpenHands:

  * Two corpora. Shell-destructive and code-execution patterns are matched only against what
    will be EXECUTED (the command); injection patterns ("ignore all previous instructions")
    against everything, because they are dangerous wherever they appear.
  * Normalization first: null bytes, zero-width/bidi/format characters removed, NFKC (fullwidth
    "ｒｍ" becomes "rm"), whitespace collapsed - so an evasion does not slip past a regex.
  * Bounded patterns (no unbounded .* around alternations), stable detector ids.

LOKI's use (engine/loki.py run_command): HIGH is refused in a background job (nobody is there to
approve it) and always asks in the window, even when a decision provider would have said yes;
MEDIUM keeps the normal approval. engine/loki.py command_policy still refuses its hard list
first; this adds a graded view on top.
"""
from __future__ import annotations

import re
import unicodedata

LOW, MEDIUM, HIGH = "LOW", "MEDIUM", "HIGH"
_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}

HIGH_PATTERNS = [
    (r"\brm\s+(?:-[frR]{2,}|-[rR]\s+-f|-f\s+-[rR]|--recursive\s+--force|--force\s+--recursive)\b",
     "recursive force-delete (rm -rf)", "exec.destruct.rm_rf"),
    (r"\bsudo\s+rm\b", "privileged file deletion", "exec.destruct.sudo_rm"),
    (r"\bmkfs\.\w+", "filesystem format", "exec.destruct.mkfs"),
    (r"\bdd\b.{0,100}of=/dev/", "raw disk write", "exec.destruct.dd_raw_disk"),
    (r"\beval\s*\(", "dynamic code evaluation", "exec.code.eval_call"),
    (r"\bexec\s*\(", "dynamic code execution", "exec.code.exec_call"),
    (r"\bos\.system\s*\(", "OS-level command execution", "exec.code.os_system"),
    (r"\bsubprocess\.(?:call|run|Popen|check_output|check_call)\s*\(", "subprocess invocation",
     "exec.code.subprocess"),
    (r"\bcurl\b[^|]{0,200}\|\s*(?:ba|z)?sh\b", "download and run (curl | sh)", "exec.net.curl_pipe_exec"),
    (r"\bwget\b[^|]{0,200}\|\s*(?:ba|z)?sh\b", "download and run (wget | sh)", "exec.net.wget_pipe_exec"),
    # LOKI additions for Windows, same shape
    (r"\b(?:rd|rmdir)\s+/s\b", "recursive directory delete (Windows)", "exec.destruct.rd_s"),
    (r"\bdel\s+(?:/[a-z]\s+){0,4}/s\b", "recursive delete (Windows)", "exec.destruct.del_s"),
    (r"\bformat\s+[a-z]:", "drive format (Windows)", "exec.destruct.format"),
    (r"\bremove-item\b.{0,120}-recurse\b.{0,60}-force\b|\bremove-item\b.{0,120}-force\b.{0,60}-recurse\b",
     "recursive force-delete (PowerShell)", "exec.destruct.remove_item"),
    (r"\b(?:iex|invoke-expression)\b", "dynamic code execution (PowerShell)", "exec.code.iex"),
    (r"\bgit\s+push\b.{0,80}(?:--force\b|\s-f\b)", "force push", "exec.vcs.force_push"),
    (r"\bgit\s+reset\s+--hard\b", "hard reset", "exec.vcs.reset_hard"),
    (r"\bchmod\s+(?:-R\s+)?777\s+/", "world-writable root", "exec.perm.chmod_root"),
]
MEDIUM_PATTERNS = [
    (r"\bcurl\b.{0,100}https?://", "HTTP request via curl", "exec.net.curl"),
    (r"\bwget\b.{0,100}https?://", "download via wget", "exec.net.wget"),
    (r"\b(?:pip|pip3|npm|pnpm|yarn|brew|winget|choco|apt|apt-get)\s+(?:install|add|i)\b", "installs software",
     "exec.pkg.install"),
    (r"\bgit\s+(?:push|clean\s+-[a-z]*f)\b", "changes a remote or deletes untracked files", "exec.vcs.push_clean"),
    (r"\brm\s+", "deletes files", "exec.destruct.rm"),
    (r"\bdel\s+", "deletes files (Windows)", "exec.destruct.del"),
]
INJECTION_HIGH = [
    (r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:previous|prior|above)\s+"
     r"(?:instructions?|prompts?|rules?|directives?)\b", "instruction override attempt", "inject.override"),
]
INJECTION_MEDIUM = [
    (r"\byou\s+are\s+now\s+(?:in\s+)?(?:\w+\s+)?mode\b", "mode switching attempt", "inject.mode_switch"),
    (r"\bpretend\s+(?:you\s+are|to\s+be)\s+(?:a\s+)?different\b", "identity manipulation", "inject.identity"),
]
_COMPILED = {name: [(re.compile(p, re.I), d, i) for p, d, i in pats] for name, pats in (
    ("high", HIGH_PATTERNS), ("medium", MEDIUM_PATTERNS), ("inj_high", INJECTION_HIGH), ("inj_medium", INJECTION_MEDIUM))}
# zero-width, bidi, format and other invisible characters (OpenHands strips ~200; these are the common ones)
_INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠋-᠏​-‏‪-‮"
                        "⁠-⁯ㅤ︀-️﻿ﾠ\U000e0000-\U000e007f]")
_C0C1 = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def normalize(text: str) -> str:
    text = str(text or "").replace("\x00", "")
    text = _INVISIBLE.sub("", text)
    text = _C0C1.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def assess(command: str, context: str = "") -> dict:
    """{"risk": LOW|MEDIUM|HIGH, "reasons": [...], "detectors": [...]} for one command.
    `context` (the model's reasoning, a page it read) is scanned for injection only."""
    exec_text = normalize(command)
    all_text = normalize(command + " " + str(context or ""))
    risk, reasons, ids = LOW, [], []

    def hit(level: str, desc: str, det: str) -> None:
        nonlocal risk
        if _ORDER[level] > _ORDER[risk]:
            risk = level
        reasons.append(desc)
        ids.append(det)
    for rx, desc, det in _COMPILED["high"]:
        if rx.search(exec_text):
            hit(HIGH, desc, det)
    for rx, desc, det in _COMPILED["inj_high"]:
        if rx.search(all_text):
            hit(HIGH, desc, det)
    if risk != HIGH:
        for rx, desc, det in _COMPILED["medium"]:
            if rx.search(exec_text):
                hit(MEDIUM, desc, det)
        for rx, desc, det in _COMPILED["inj_medium"]:
            if rx.search(all_text):
                hit(MEDIUM, desc, det)
    return {"risk": risk, "reasons": list(dict.fromkeys(reasons)), "detectors": list(dict.fromkeys(ids))}


def at_least(risk: str, level: str) -> bool:
    return _ORDER.get(risk, 0) >= _ORDER.get(level, 0)
