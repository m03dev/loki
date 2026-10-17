"""SkillSpector's agent-skill abuse rules, built into LOKI's skill scan (no add-on needed).

Ported into LOKI (session 27 harvest) from NVIDIA SkillSpector (github.com/NVIDIA/SkillSpector,
src/skillspector/yara_rules/agent_skills.yar - the four agent-skill rules and their
conditions - and the prohibition-context idea of nodes/analyzers/prohibition_context.py),
Apache-2.0, Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES - see
engine/licenses/SkillSpector-Apache-2.0.txt. YARA is not installed on LOKI's machines, so the
rule strings are Python regexes and the conditions are the same boolean combinations:

  credential_exfiltration_webhook (critical)  reads secrets AND sends data AND to a collector
                                               (Discord/Telegram/Slack webhooks, webhook.site,
                                               requestbin, pipedream, ngrok)
  remote_bootstrap_execution (high)           exec/eval of downloaded code, npm postinstall
                                               curl|wget, pip install from a URL
  prompt_injection_hidden_instructions (high) hidden HTML/markdown comments telling the agent to
                                               ignore/override, parameter text that injects, or
                                               zero-width / right-to-left override characters
  destructive_autonomous_actions (high)       rm -rf /, or a destructive command (rm -rf ~,
                                               rmtree of home/workspace, git reset --hard /
                                               push --force, history wipe) together with
                                               "without asking" / "do not ask" / "silently" -
                                               unless the line forbids it ("never ...")

`scan_folder(folder)` -> [(severity, message)]; skill_scan.NATIVE_SCANNERS runs it on every
skill. critical/high block the skill from loading (skill_scan.BLOCKING_SEVERITIES).
"""
from __future__ import annotations

import re
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
                 ".json", ".yaml", ".yml", ".toml", ".rb", ".pl", ".html", ".xml", ""}
MAX_FILES = 200
MAX_BYTES = 400_000

I = re.IGNORECASE
SECRET = [re.compile(p, I) for p in (
    r"os\.environ\s*(\.items\s*\(\)|\[[^\]]+\]|\.get\s*\()", r"os\.getenv\s*\(", r"process\.env(\.|\[|\s|$)",
    r"open\s*\(\s*['\"][^'\"]*\.env['\"]", r"(\.ssh/(id_rsa|id_ed25519)|authorized_keys)",
    r"(OPENAI_API_KEY|ANTHROPIC_API_KEY|NVIDIA_INFERENCE_KEY|AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|HF_TOKEN)")]
SEND = [re.compile(p, I) for p in (
    r"(requests|httpx)\.(post|put)\s*\(", r"(fetch|axios\.post)\s*\(", r"curl\s+.*(-X\s+POST|-d\s+|--data)")]
COLLECTOR = [re.compile(p, I) for p in (
    r"discord\.com/api/webhooks", r"api\.telegram\.org/bot", r"hooks\.slack\.com/services", r"webhook\.site",
    r"(requestbin|pipedream\.net|ngrok-free\.app|ngrok\.io)")]
BOOTSTRAP = [re.compile(p, I) for p in (
    r"exec\s*\(\s*(requests|httpx)\.get\s*\([^)]*\)\.(text|content)",
    r"(exec|eval)\s*\(\s*urlopen\s*\([^)]*\)\.read\s*\(\s*\)",
    r"eval\s*\(\s*await\s*\(\s*await\s+fetch\s*\([^)]*\)\s*\)\s*\.\s*text\s*\(\s*\)\s*\)",
    r"\"postinstall\"\s*:\s*\"[^\"]*(curl|wget|powershell|node\s+-e)",
    r"pip\s+install\s+(--upgrade\s+)?(git\+https?://|https?://)",
    r"(curl|wget)\s+[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b")]
HIDDEN = [re.compile(p, I) for p in (
    r"<!--[^>]{0,240}(SYSTEM|DEVELOPER|ASSISTANT)[^>]{0,240}(ignore|override|bypass|disregard)[^>]{0,240}-->",
    r"\[//\]:\s*#\s*\([^)]{0,240}(ignore|override|bypass|disregard)[^)]{0,240}\)",
    r"(parameter|argument|description).{0,160}(ignore previous|override safety|exfiltrate|SYSTEM:)")]
INVISIBLE = re.compile("[​‌‍‭‮⁦⁧⁨⁩]")
DESTRUCTIVE = [re.compile(p, I) for p in (
    r"rm\s+-[rfRF]+\s+(\./|\.\./|~/|\$HOME|workspace|repo|project)",
    r"(shutil\.rmtree|fs\.rmSync|fs\.rm)\s*\([^)]*(HOME|home|workspace|repo|project)",
    r"(del|rmdir)\s+.*(/s|/q).*%?(USERPROFILE|HOMEPATH|CD)%?",
    r"git\s+(clean\s+-fdx|reset\s+--hard|push\s+--force)",
    r"(history\s+-c|rm\s+[^;\n]*\.bash_history|Clear-History)")]
RM_ROOT = re.compile(r"rm\s+-[rfRF]+\s+/(\s|$)")
AUTONOMY = [re.compile(p, I) for p in (
    r"without\s+(asking|confirmation|prompting)", r"do\s+not\s+(ask|prompt|request\s+confirmation)",
    r"(silently|non-interactive|unattended)")]
PROHIBITION = re.compile(r"\b(never|don'?t|do not|must not|avoid|forbidden|dangerous|warning|caution|unless)\b", I)


def _texts(folder: Path):
    folder = Path(folder)
    for count, path in enumerate(sorted(p for p in folder.rglob("*") if p.is_file())):
        if count >= MAX_FILES:
            return
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            yield path.relative_to(folder).as_posix(), path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue


def _first(patterns, text):
    for rx in patterns:
        m = rx.search(text)
        if m:
            return m
    return None


def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:end if end >= 0 else len(text)]


def scan_text(name: str, text: str) -> list:
    out = []
    s, d, c = _first(SECRET, text), _first(SEND, text), _first(COLLECTOR, text)
    if s and d and c:
        out.append(("critical", "%s: reads secrets (%r) and sends them to %r (credential exfiltration)"
                    % (name, s.group(0)[:40], c.group(0)[:40])))
    b = _first(BOOTSTRAP, text)
    if b and not PROHIBITION.search(_line_of(text, b.start())):
        out.append(("high", "%s: downloads and runs remote code: %r" % (name, b.group(0)[:60])))
    h = _first(HIDDEN, text)
    if h:
        out.append(("high", "%s: hidden instructions aimed at the agent: %r" % (name, h.group(0)[:60])))
    inv = INVISIBLE.search(text)
    if inv:
        out.append(("high", "%s: invisible zero-width / right-to-left override character U+%04X at line %d"
                    % (name, ord(inv.group(0)), text.count("\n", 0, inv.start()) + 1)))
    r = RM_ROOT.search(text)
    if r and not PROHIBITION.search(_line_of(text, r.start())):
        out.append(("high", "%s: deletes the whole disk: %r" % (name, r.group(0))))
    a = _first(AUTONOMY, text)
    if a:
        for rx in DESTRUCTIVE:
            for m in rx.finditer(text):
                if PROHIBITION.search(_line_of(text, m.start())):
                    continue          # "never git push --force" is advice, not an action
                out.append(("high", "%s: destructive action %r with %r (no confirmation)"
                            % (name, m.group(0)[:40], a.group(0)[:30])))
                break
            else:
                continue
            break
    return out


def scan_folder(folder: Path) -> list:
    """[(severity, message)] for every text file in a skill folder."""
    findings = []
    for name, text in _texts(folder):
        findings.extend(scan_text(name, text))
        if len(findings) >= 10:
            break
    return findings
