"""LOKI runs a request's own check commands itself, in LOKI's real folder, before any agent touches it (owner
2026-10-28: "fix whats going on with loki ... i told you to fix my core system").

Why: most LOKI_TASKS.md requests are "in LOKI's folder: `harness_data\\.venv\\Scripts\\python.exe tests\\x.py` ...
qa/x.md: the outputs word for word". On the PC the agents ran them from LOKI Projects/Home (no LOKI there), built a fake
engine/, harness_data/.venv and job logs in Home, and pasted made-up outputs (qa/opencode-exe.md, qa/agent-system.md
= "{{status_data}}"). A note in the prompt ("LOKI's folder is D:/loki, cd there") did not stop it. The harness runs
deterministic steps; the model does only the parts that need a model (research says the same: mini-swe-agent's
"the trajectory is the proof", Tool Receipts arXiv 2603.10060).

  commands(text)            the request's read-only commands: LOKI's venv python (tests, `-c` checks, engine/*.py
                            status), `curl -s` GETs to this machine's LOKI. Never ship.py, git, installs, POSTs,
                            deletes, redirects - an agent (with the owner's OK where needed) does those.
  run(text, key, data_dir)  runs them in LOKI's folder (<port> and <engine token> filled in), each output recorded as a
                            receipt (engine/receipts.py, key "pre-<key>") and written to <qa name>.loki-ran.md in the
                            workspace; returns the note the team gets: "LOKI already ran these - copy, don't re-run".

Standard library only; each command at most 60 s, all of them at most 150 s.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TICK = re.compile(r"`([^`\n]{6,1500})`")
_PY = re.compile(r"^(harness_data[\\/]\.venv[\\/](Scripts[\\/]python\.exe|bin[\\/]python3?)|python3?)\s+", re.I)
_PY_OK = re.compile(r"^(tests[\\/]test_\w+\.py|engine[\\/][\w]+\.py(\s+(status|plan|proof))?|-c\s+\")", re.I)
_CURL = re.compile(r"^curl\s+-s\s+(-H\s+\"Authorization: Bearer <engine token>\"\s+)?"
                   r"http://127\.0\.0\.1:<[^>]*port[^>]*>/[\w/?=&.,-]*$", re.I)
_NEVER = re.compile(r"\b(ship\.py|git\s|pip\s|install|rm\s|del\s|remove|delete|shutil\.rmtree|unlink|os\.remove|"
                    r"subprocess|-X\s+POST|--data|\bPOST\b|setup\b|winget|npm\s|npx\s)", re.I)
MAX_ONE_S = 60     # the owner's rule: a test run takes at most 1 minute
MAX_ALL_S = 150


def _venv_python() -> str:
    py = ROOT / "harness_data" / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    return str(py) if py.is_file() else sys.executable


def commands(text: str) -> list:
    """The read-only commands in a request, in order, as written."""
    out = []
    for m in _TICK.finditer(str(text or "")):
        cmd = m.group(1).strip()
        cmd = re.sub(r"^cd\s+\S+\s*&&\s*", "", cmd)          # "cd ~/Documents/loki && ..." - LOKI's folder is ours
        bare = re.sub(r"<[^<>]{1,40}>", "", cmd).replace("->", "")   # <engine token>, <port> are not redirects
        if _NEVER.search(cmd) or ">" in bare or "|" in bare:
            continue
        pm = _PY.match(cmd)
        if pm and _PY_OK.match(cmd[pm.end():]):
            out.append(cmd)
        elif _CURL.match(cmd):
            out.append(cmd)
    return list(dict.fromkeys(out))[:8]


def _engine(data_dir: Path) -> tuple:
    try:
        token = (Path(data_dir) / "app" / "engine.token").read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    port = os.getenv("LOKI_APP_PORT", "") or os.getenv("LOKI_PORT", "") or "8767"
    return port, token


def _argv(cmd: str, data_dir: Path) -> list | None:
    pm = _PY.match(cmd)
    if pm:
        rest = cmd[pm.end():].strip()
        if rest.startswith("-c "):
            code = rest[3:].strip()
            if code.startswith('"') and code.endswith('"'):
                code = code[1:-1]
            return [_venv_python(), "-c", code]
        return [_venv_python()] + rest.replace("\\", "/").split()
    if cmd.lower().startswith("curl"):
        port, token = _engine(data_dir)
        url = re.search(r"http://\S+", cmd).group(0)
        url = re.sub(r"<[^>]*port[^>]*>", port, url)
        return ["curl", "-s", "--max-time", "60", "-H", "Authorization: Bearer %s" % token, url]
    return None


def run(text: str, key: str, data_dir, workspace, runner=subprocess.run) -> str:
    """Run the request's read-only commands in LOKI's folder; record and write them. Returns the team's note ("" when
    there was nothing to run)."""
    cmds = commands(text)
    if not cmds:
        return ""
    import receipts  # pylint: disable=import-outside-toplevel
    data_dir = Path(data_dir)
    t_end = time.time() + MAX_ALL_S
    parts = ["# Ran by LOKI itself (real output - copy from here, do not re-run, never edit this file)", "",
             "Folder: %s" % ROOT.as_posix(), "Time: %s" % time.strftime("%Y-%m-%d %H:%M"), ""]
    for cmd in cmds:
        argv = _argv(cmd, data_dir)
        if not argv:
            continue
        left = t_end - time.time()
        if left < 5:
            parts += ["## `%s`" % cmd, "", "NOT RUN - LOKI's time budget for these checks ran out.", ""]
            continue
        env = dict(os.environ, PYTHONIOENCODING="utf-8", LOKI_PROOF_RUNNER="1")
        try:
            done = runner(argv, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=min(MAX_ONE_S, left), env=env)
            out = ((done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")).strip()
            code = done.returncode
        except subprocess.TimeoutExpired:
            out, code = "TIMED OUT after %d s" % min(MAX_ONE_S, left), 124
        except Exception as exc:  # noqa: BLE001
            out, code = "could not start: %s" % exc, 127
        receipts.record("loki-proof-runner", cmd, out, code, key="pre-" + key)
        parts += ["## `%s`" % cmd, "", "Exit code: %s" % code, "", "```", out[-20000:] or "(no output)", "```", ""]
    qa = re.search(r"(?<![\w/])qa/([\w.-]+)\.md", text)
    name = (qa.group(1) if qa else "request-" + key[:8]) + ".loki-ran.md"
    path = Path(workspace) / "qa" / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(parts), encoding="utf-8")
    except OSError:
        return ""
    return ("LOKI ALREADY RAN this request's check commands in LOKI's real folder (%s) - their REAL outputs are in "
            "qa/%s. Do NOT run them again and do NOT write any engine/, harness_data/ or tests/ files in this folder. "
            "Copy those outputs word for word where the request asks for them, then do only the steps that are left "
            "(the ones that need you). A pasted output that no tool printed is caught and the task fails."
            % (ROOT.as_posix(), name))
