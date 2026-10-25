"""LOKI's agent for a model running on THIS computer (Ollama, LM Studio, llama.cpp ...), fully offline.

Owner 2026-10-25 12:37: "i want it to make me a git repo with my offline local model ... there are out of the box
solutions to this problem ... simply get other code that works". What failed before: a 9B local model behind OpenCode
gets a ~12,000-token system prompt and 20+ tool schemas every step (Ollama's log on the Mac: 25-70 s a step, then it
gave up or "said done"), and native tool calling in a small model is fragile.

What works for small local models is the mini-swe-agent recipe (github.com/SWE-agent/mini-swe-agent, MIT - the bash-only
agent from the SWE-bench team; its text-based config is the base of the prompts below): a SHORT prompt, ONE tool - the
shell - written as a plain ```bash block (no tool-calling API needed, any model can do it), one command per step, the
real output shown back, and a fixed word to finish. LOKI adds what it always adds: thinking off (Ollama think=false, so a
step is seconds, not a minute), dangerous commands refused, and the result checked on disk (the folder before/after,
`git log` run by LOKI itself) - never the model's word for it.

    run(task, workspace, base_url, model, ...) -> {"ok", "reply", "steps", "changes", "exit"}
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

DONE_WORD = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
MAX_OUTPUT = 6000

SYSTEM = """You are LOKI, an agent that gets things done on the owner's computer by running shell commands.

Every reply has a short THOUGHT, then exactly ONE shell code block with ONE command (or commands joined with && ).
The command runs, and you are shown its real output. Then you reply again with the next command.

```bash
your_command_here
```

Rules:
- One code block per reply. Never invent output - wait for the real output.
- Each command runs in a fresh shell in the working folder; `cd x && ...` only lasts for that command.
- Create files with a heredoc:  cat > path/file.py <<'EOF' ... EOF
- When the task is done AND you have checked it (ls, cat, run it, git log ...), reply with exactly:
```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```
  and nothing else in that block. If it cannot be done, explain why and finish the same way."""

TASK = """Task: {task}

Working folder: {cwd}
System: {system}. Shell: {shell}.{mac}
Work step by step: look, do, check the result, then finish."""


def find_shell() -> tuple:
    """(argv prefix, name): bash everywhere it exists (Git Bash on Windows), else PowerShell."""
    if sys.platform == "win32":
        for p in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe",
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe")):
            if p and Path(p).is_file() and "system32" not in p.lower():     # WSL's bash.exe is not Git Bash
                return [p, "-c"], "bash (Git Bash)"
        return ["powershell", "-NoProfile", "-Command"], "PowerShell"
    return [shutil.which("bash") or "/bin/bash", "-c"], "bash"


def shell_env() -> dict:
    env = dict(os.environ)
    extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"] if sys.platform != "win32" else []
    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + [d for d in extra if d not in env.get("PATH", "")])
    env.update(PAGER="cat", GIT_PAGER="cat", MANPAGER="cat", GIT_TERMINAL_PROMPT="0", TERM="dumb")
    env.setdefault("GIT_AUTHOR_NAME", "LOKI")
    env.setdefault("GIT_AUTHOR_EMAIL", "loki@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    return env


_BLOCK = re.compile(r"```[ \t]*(?:bash|sh|shell|zsh|console|powershell|ps1|cmd|mswea_bash_command)?[ \t]*\n(.*?)```", re.S | re.I)


def parse_action(text: str) -> tuple:
    """(command or "", error or ""): exactly one code block wanted; <think> blocks ignored."""
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S | re.I)
    blocks = [b.strip() for b in _BLOCK.findall(text) if b.strip()]
    if not blocks:
        return "", "no command found - put exactly ONE command in a ```bash block"
    return blocks[0], ""        # several blocks: a small model often does that - the first one runs (the rest wait)


def observation(code: int, out: str) -> str:
    out = out or ""
    if len(out) > MAX_OUTPUT:
        out = (out[:MAX_OUTPUT // 2] + "\n... (%d characters cut - use head/tail/grep for less) ...\n" %
               (len(out) - MAX_OUTPUT) + out[-MAX_OUTPUT // 2:])
    return "<returncode>%d</returncode>\n<output>\n%s\n</output>" % (code, out)


def run_command(cmd: str, cwd: Path, timeout: float = 180, shell: list | None = None, run=subprocess.run) -> tuple:
    try:
        p = run((shell or find_shell()[0]) + [cmd], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                env=shell_env(), stdin=subprocess.DEVNULL)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "the command took longer than %d s and was stopped (run long jobs in the background: cmd &)" % timeout
    except OSError as exc:
        return 127, "could not run it: %s" % exc


# ------------------------------------------------------------------ the model
def chat(base_url: str, model: str, messages: list, key: str = "", timeout: float = 600,
         opener=urllib.request.urlopen) -> str:
    """One reply. Ollama: its own /api/chat with thinking OFF and a 16k context; any other local server: /v1."""
    base = base_url.rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    if ":11434" in root or os.getenv("LOKI_LOCAL_AGENT_API") == "ollama":
        body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": "30m",
                "options": {"num_ctx": int(os.getenv("LOKI_LOCAL_AGENT_CTX", "16384")), "temperature": 0.2}}
        url = root + "/api/chat"
    else:
        body = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 2048}
        url = (base if base.endswith("/v1") else base + "/v1") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if key and key not in ("ollama", "none"):
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else ""
        if exc.code == 400 and "think" in detail.lower() and body.pop("think", None) is not None:   # an older Ollama
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
            with opener(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
        else:
            raise RuntimeError("the local model answered HTTP %s: %s" % (exc.code, detail)) from exc
    if "message" in data:
        return str((data.get("message") or {}).get("content") or "")
    return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


# ------------------------------------------------------------------ the loop
def run(task: str, workspace: str | Path, base_url: str, model: str, *, key: str = "", max_steps: int = 30,
        wall_s: float = 1800, deny: tuple = (), progress: Callable[[str, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None, ask: Callable = None, execute: Callable = None,
        history: list | None = None) -> dict:
    """Run the task to the end with the local model. ask(messages) -> reply text and execute(cmd) -> (code, output)
    can be swapped (tests); history: earlier [user, assistant] turns of the chat, for context."""
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda kind, text: None)
    shell, shell_name = find_shell()
    ask = ask or (lambda msgs: chat(base_url, model, msgs, key))
    execute = execute or (lambda cmd: run_command(cmd, ws, shell=shell))
    import dsh_engine  # pylint: disable=import-outside-toplevel - the folder before/after
    before = dsh_engine.snapshot(ws)
    mac = " On macOS use `sed -i ''` (not `sed -i`)." if sys.platform == "darwin" else ""
    msgs = [{"role": "system", "content": SYSTEM}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:2000]})
    msgs.append({"role": "user", "content": TASK.format(task=task, cwd=ws, system=platform.system() or sys.platform,
                                                         shell=shell_name, mac=mac)})
    started, steps, bad, last_thought, ran, exit_reason = time.time(), 0, 0, "", [], "steps"
    while steps < max_steps:
        if cancelled and cancelled():
            exit_reason = "cancelled"
            break
        if time.time() - started > wall_s:
            exit_reason = "time"
            break
        steps += 1
        say("thinking", "Local model (%s), step %d..." % (model, steps))
        try:
            reply = ask(msgs)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reply": "NOT DONE - the local model did not answer: %s" % exc, "steps": steps,
                    "changes": dsh_engine.changes(before, dsh_engine.snapshot(ws)), "exit": "model"}
        msgs.append({"role": "assistant", "content": reply})
        cmd, err = parse_action(reply)
        thought = _BLOCK.sub("", re.sub(r"<think>.*?</think>", "", reply, flags=re.S)).strip()
        if thought:
            last_thought = thought
            say("assistant", thought[:300])
        if err:
            bad += 1
            if bad >= 4:
                exit_reason = "format"
                break
            msgs.append({"role": "user", "content": "Format error: %s. Reply with a short THOUGHT and exactly one "
                                                    "```bash block." % err})
            continue
        bad = 0
        if DONE_WORD in cmd:
            exit_reason = "done"
            break
        low = cmd.lower()
        hit = next((d for d in deny if d in low), "")
        if hit:
            say("error", "Refused: %s" % cmd[:200])
            msgs.append({"role": "user", "content": observation(126, "REFUSED by LOKI: '%s' is a dangerous command "
                                                                     "and never runs. Do it another way." % hit.strip())})
            continue
        say("tool", "$ " + cmd[:400])
        code, out = execute(cmd)
        ran.append((cmd, code))
        say("tool_result" if code == 0 else "error", ("exit %d: %s" % (code, out))[:400])
        extra = ""
        if len([b for b in _BLOCK.findall(re.sub(r"<think>.*?</think>", "", reply, flags=re.S)) if b.strip()]) > 1:
            extra = "\n(Only your FIRST code block ran. Send the next command now.)"
        msgs.append({"role": "user", "content": observation(code, out) + extra})
    chs = dsh_engine.changes(before, dsh_engine.snapshot(ws))
    reply = verify(task, ws, chs, last_thought, exit_reason, ran, shell)
    return {"ok": exit_reason == "done" and not reply.startswith("NOT DONE"), "reply": reply, "steps": steps,
            "changes": chs, "exit": exit_reason, "commands": len(ran)}


def _git_repos(ws: Path, chs: list) -> list:
    """The git repos the changes are in (a new .git, or files inside an existing repo)."""
    repos = set()
    for _, path in chs:
        parts = Path(path).parts
        if ".git" in parts:
            i = parts.index(".git")
            repos.add(Path(*parts[:i]) if i else Path("."))
            continue
        for i in range(len(parts) - 1, -1, -1):
            if (ws / Path(*parts[:i]) / ".git").is_dir() if i else (ws / ".git").is_dir():
                repos.add(Path(*parts[:i]) if i else Path("."))
                break
    return sorted(repos)


def verify(task: str, ws: Path, chs: list, thought: str, exit_reason: str, ran: list, shell: list) -> str:
    """LOKI's own check of the result: what changed in the folder, and the git log of any repo made or changed."""
    lines = []
    if thought:
        lines.append(thought.strip())
    repos = _git_repos(ws, chs)
    for r in repos[:3]:
        code, out = run_command("git log --oneline -5 && git status --short", ws / r, timeout=30, shell=shell)
        lines.append("Checked by LOKI - `git log` in %s:\n```\n%s\n```" % (r.as_posix() or ".", out.strip() or "(no commits yet)"))
    if chs:
        import dsh_engine  # pylint: disable=import-outside-toplevel
        lines.append("In the folder: %s." % dsh_engine.describe(chs))
    wants_change = bool(re.search(r"\b(make|create|build|write|add|commit|init|set ?up|generate|fix|change|edit|"
                                  r"rename|move|delete|install)\b", task, re.I))
    if exit_reason != "done" or (wants_change and not chs):
        why = {"steps": "it ran out of steps", "time": "it ran out of time", "format": "the model stopped giving "
               "commands", "cancelled": "you stopped it", "done": "it said done but nothing changed in the folder"}
        lines.insert(0, "NOT DONE - %s (%d commands run)." % (why.get(exit_reason, exit_reason), len(ran)))
    if wants_change and re.search(r"\bgit\b", task, re.I) and re.search(r"\b(repo|repository|init|commit)\b", task, re.I) \
            and not repos and exit_reason == "done":
        lines.insert(0, "NOT DONE - no git repository was made or changed in %s." % ws)
    return "\n\n".join(lines).strip() or "(the local model finished without a word)"
