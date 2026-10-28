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

SYSTEM = """You are LOKI, an agent that gets things done on the owner's computer by running shell commands. Your
focus is the owner's own work outside the LOKI app (projects, games, files, repos); LOKI's own code is LOKI Studio's.

Every reply has a short THOUGHT, then exactly ONE shell code block with ONE command (or commands joined with && ).
The command runs, and you are shown its real output. Then you reply again with the next command.

```bash
your_command_here
```

Rules:
- One code block per reply. Never invent output - wait for the real output.
- Each command runs in a fresh shell in the working folder; `cd x && ...` only lasts for that command.
- Create files with a heredoc:  cat > path/file.py <<'EOF' ... EOF
- A new project (a repo, an app, a site) goes in its OWN new folder inside the working folder: mkdir name && cd name
  && git init -b main. Never run git init in the working folder itself, and never commit .loki/ (private chats).
- GitHub: `gh auth status` first, then `gh repo view OWNER/name` to see if the repo already exists.
  New repo: cd name && gh repo create name --private --source=. --remote=origin --push
  It already exists: do NOT make another one - ASK the owner whether to push into it (see QUESTION below).
  Push refused (403 / 401 / "Permission denied" / "Authentication failed"): run `gh auth setup-git` once (git then uses
  gh's login) and push again. Still refused: STOP and tell the owner exactly what to run (e.g. `gh auth login`).
  The remote is always called origin.
- LOKI's chats are not files: never touch the .loki folder. List them with `loki chats list`, delete with
  `loki chats delete <id>` or `loki chats delete --all` (keeps the chat you are in). The owner is asked first.
- Deleting or overwriting anything (rm, mv over a file, git reset --hard, git clean, force push ...) is fine when
  asked - LOKI shows the owner your THOUGHT and the command and waits for Allow. Say in your THOUGHT exactly what goes.
- Never repeat what already failed. Two failures of the same kind = change approach or stop and explain.
- QUESTION: when you need the owner's decision (overwrite? which one? a login?), reply with one line
  QUESTION: <your question>   and no code block. You stop there; the owner's answer comes as the next message.
- Pictures, 3D and video: never draw with text - run LOKI's makers:
  loki-make image "<full art-director prompt>" --style concept-art --count 2   (styles: concept-art comic
  photo pixel-art 3d-render texture ...; --upscale 4)
  loki-make 3d "<object>" [--backend pixal3d]   loki-make video "<clip>"   loki-make upscale pic.png
  loki-make pixel pic.png --size 64   loki-make music "<style>" --seconds 60   loki-make voice --action speak --text "Hi"
  loki-make shelf --action list   (more: sfx, sprites, LODs; loki-make manga / design)
- The owner's other machine: loki-make machines   loki-make run-on "<full task>" --machine mac   loki-make job --job <id> --machine mac
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


def make_wrapper() -> str:
    """A `loki-make` command on the agent's PATH: LOKI's makers (pictures, 3D, video, upscale, the other machine) for a
    shell-only agent (engine/make_mcp.py's CLI). Returns the folder it is in ("" if it could not be written)."""
    try:
        import creative  # pylint: disable=import-outside-toplevel
        d = Path(creative.data_dir()) / "bin"
        d.mkdir(parents=True, exist_ok=True)
        mcp = Path(__file__).resolve().parent / "make_mcp.py"
        py = sys.executable.replace("\\", "/")
        sh = d / "loki-make"
        sh.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (py, str(mcp).replace("\\", "/")), encoding="utf-8")
        sh.chmod(0o755)
        if sys.platform == "win32":
            (d / "loki-make.cmd").write_text('@"%s" "%s" %%*\r\n' % (sys.executable, mcp), encoding="utf-8")
        return str(d)
    except Exception:  # noqa: BLE001
        return ""


def shell_env() -> dict:
    env = dict(os.environ)
    extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"] if sys.platform != "win32" else []
    wrap = make_wrapper()
    env["PATH"] = os.pathsep.join(([wrap] if wrap else []) + [env.get("PATH", "")] +
                                  [d for d in extra if d not in env.get("PATH", "")])
    env.update(PAGER="cat", GIT_PAGER="cat", MANPAGER="cat", GIT_TERMINAL_PROMPT="0", TERM="dumb")
    env.setdefault("GIT_AUTHOR_NAME", "LOKI")
    env.setdefault("GIT_AUTHOR_EMAIL", "loki@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    try:   # git in a job folder can never reach LOKI's own repo (engine/live_guard.py)
        import live_guard  # pylint: disable=import-outside-toplevel
        live_guard.git_env(env)
    except Exception:  # noqa: BLE001
        pass
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
        out = (out[:MAX_OUTPUT // 2] + "\n... (%d characters not shown HERE - the file/output itself is complete, "
               "only this view is shortened; use head/tail/grep/wc to look at parts) ...\n" %
               (len(out) - MAX_OUTPUT) + out[-MAX_OUTPUT // 2:])
    return "<returncode>%d</returncode>\n<output>\n%s\n</output>" % (code, out)


def run_command(cmd: str, cwd: Path, timeout: float = 180, shell: list | None = None, run=subprocess.run) -> tuple:
    try:   # never a git command that changes the LOKI that is running (engine/live_guard.py)
        import live_guard  # pylint: disable=import-outside-toplevel
        why = live_guard.touches_live(cmd, str(cwd))
        if why:
            return 1, why
    except ImportError:
        pass
    try:
        p = run((shell or find_shell()[0]) + [cmd], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                env=shell_env(), stdin=subprocess.DEVNULL)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "the command took longer than %d s and was stopped (run long jobs in the background: cmd &)" % timeout
    except OSError as exc:
        return 127, "could not run it: %s" % exc


def protect(ws: Path) -> None:
    """LOKI's private folder (.loki/: the chats) is never committed by any repo above it: a .gitignore of "*" inside it.
    (2026-10-25: the agent ran git init in the workspace and committed .loki/loki_conversations.json.)"""
    d = ws / ".loki"
    try:
        if d.is_dir() and not (d / ".gitignore").is_file():
            (d / ".gitignore").write_text("# LOKI's private data - never in git\n*\n", encoding="utf-8")
    except OSError:
        pass


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
    LAST_USAGE.clear()
    if "message" in data:              # Ollama: its own counters (tokens in / out, how long the answer took)
        dur = float(data.get("eval_duration") or 0) / 1e9
        LAST_USAGE.update(model=str(data.get("model") or model), input=int(data.get("prompt_eval_count") or 0),
                          output=int(data.get("eval_count") or 0),
                          tps=round(int(data.get("eval_count") or 0) / dur, 1) if dur else 0.0)
        return str((data.get("message") or {}).get("content") or "")
    u = data.get("usage") or {}
    LAST_USAGE.update(model=str(data.get("model") or model), input=int(u.get("prompt_tokens") or 0),
                      output=int(u.get("completion_tokens") or 0), tps=0.0)
    return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


LAST_USAGE: dict = {}       # the last reply's tokens, for the live meter (chat() fills it)


# ------------------------------------------------------------------ the loop
CTX_CHARS = int(os.getenv("LOKI_LOCAL_AGENT_CTX", "16384")) * 3     # about 3 characters a token, room for the reply


def compact(msgs: list, budget: int | None = None, keep_last: int = 8) -> list:
    """The conversation, kept inside the model's context: the system prompt and the task always, the last few
    steps in full, older command outputs shortened to one line. Ollama silently cuts the FRONT of a too-long prompt -
    the task itself - and the model then loops (2026-10-25: a team job at 300k tokens re-appending one file)."""
    budget = budget or CTX_CHARS
    head = [m for m in msgs[:2]]
    body = msgs[2:]
    size = lambda ms: sum(len(str(m.get("content") or "")) for m in ms)  # noqa: E731
    if size(msgs) <= budget:
        return msgs
    out = []
    for i, m in enumerate(body):
        recent = i >= len(body) - keep_last
        c = str(m.get("content") or "")
        if not recent and m["role"] == "user" and c.startswith(("exit ", "Exit ", "OBSERVATION", "<returncode>")) or (
                not recent and m["role"] == "user" and len(c) > 400):
            first = c.strip().splitlines()[0][:160] if c.strip() else ""
            c = "%s ... (older output, %d characters, left out to keep the task in view)" % (first, len(c))
        elif not recent and m["role"] == "assistant" and len(c) > 600:
            c = c[:600] + " ..."
        out.append({"role": m["role"], "content": c})
    while size(head + out) > budget and len(out) > keep_last:
        out.pop(0)
    for m in out[:-2]:                      # still too long: shorten the recent outputs too, all but the newest
        if size(head + out) <= budget:
            break
        if m["role"] == "user" and len(m["content"]) > 1500:
            m["content"] = m["content"][:700] + "\n... (shortened to keep the task in view) ...\n" + m["content"][-500:]
    return head + out


def _cmd_key(cmd: str) -> str:
    return re.sub(r"\s+", " ", (cmd or "").strip().splitlines()[0] if (cmd or "").strip() else "")[:200]


def run(task: str, workspace: str | Path, base_url: str, model: str, *, key: str = "", max_steps: int = 30,
        wall_s: float = 1800, deny: tuple = (), progress: Callable[[str, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None, ask: Callable = None, execute: Callable = None,
        history: list | None = None, approve: Callable | None = None, builtins: Callable | None = None) -> dict:
    """Run the task to the end with the local model. ask(messages) -> reply text and execute(cmd) -> (code, output)
    can be swapped (tests); history: earlier [user, assistant] turns of the chat, for context."""
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda kind, text: None)
    shell, shell_name = find_shell()
    ask = ask or (lambda msgs: chat(base_url, model, msgs, key))
    execute = execute or (lambda cmd: run_command(cmd, ws, shell=shell))
    import dsh_engine  # pylint: disable=import-outside-toplevel - the folder before/after
    protect(ws)
    root_git = (ws / ".git").exists()
    before = dsh_engine.snapshot(ws)
    mac = " On macOS use `sed -i ''` (not `sed -i`)." if sys.platform == "darwin" else ""
    msgs = [{"role": "system", "content": SYSTEM}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:2000]})
    msgs.append({"role": "user", "content": TASK.format(task=task, cwd=ws, system=platform.system() or sys.platform,
                                                         shell=shell_name, mac=mac)})
    started, steps, bad, last_thought, ran, exit_reason = time.time(), 0, 0, "", [], "steps"
    tot_in = tot_out = 0
    fails: list = []
    nudged = 0
    while steps < max_steps:
        if cancelled and cancelled():
            exit_reason = "cancelled"
            break
        if time.time() - started > wall_s:
            exit_reason = "time"
            break
        steps += 1
        say("thinking", "Local model (%s), step %d..." % (model, steps))
        reply, err_note = None, ""
        for attempt in range(3):
            try:
                view = compact(msgs)
                reply = ask(view if attempt == 0 else view + [{"role": "user", "content": (
                    "Your last answer could not be read (%s). Answer again: a short THOUGHT, then ONE ```bash block. "
                    "Plain text only - no <tool_call> or other tags." % err_note[:160])}])
                break
            except Exception as exc:  # noqa: BLE001 - Ollama answers 500 when its output parser chokes (qwen3.5 on the
                err_note = str(exc)         # Mac, 2026-10-25: a tool-call tag with no tools) - ask again, don't give up
                say("error", "The model's answer broke (%s) - asking again." % err_note[:160])
        if reply is None:
            return {"ok": False, "reply": "NOT DONE - the local model did not answer: %s" % err_note, "steps": steps,
                    "changes": dsh_engine.changes(before, dsh_engine.snapshot(ws)), "exit": "model"}
        if LAST_USAGE:                 # the live meter under the steps: which model, tokens so far, speed
            tot_in += LAST_USAGE.get("input", 0)
            tot_out += LAST_USAGE.get("output", 0)
            host = (re.match(r"https?://([^/:]+)", base_url or "") or [None, ""])[1]
            where = "this computer" if host in ("127.0.0.1", "localhost", "::1", "") else host
            say("usage", json.dumps({"model": LAST_USAGE.get("model") or model, "where": where, "step": steps,
                                     "input": tot_in, "output": tot_out, "tps": LAST_USAGE.get("tps", 0),
                                     "seconds": round(time.time() - started, 1)}))
        msgs.append({"role": "assistant", "content": reply})
        q = re.search(r"^\s*QUESTION:\s*(.+)$", re.sub(r"<think>.*?</think>", "", reply, flags=re.S), re.M)
        if q and not _BLOCK.search(reply):
            last_thought = "QUESTION: " + q.group(1).strip()
            exit_reason = "question"
            break
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
        if ".loki" in cmd and not re.match(r"^\s*loki\s+chats\b", cmd):
            msgs.append({"role": "user", "content": observation(126, "REFUSED by LOKI: .loki is LOKI's own private data "
                                                                     "(the chats). Use `loki chats list` / `loki chats "
                                                                     "delete` instead.")})
            continue
        if needs_ok(cmd):
            # removes or overwrites something: the owner sees what and why, and says yes first (owner 2026-10-25:
            # "i asked it to remove chats ... it didn't prompt me anything and just said it deleted stuff")
            ok = approve(cmd, (thought or "")[:600]) if approve else False
            if not ok:
                say("error", "Not allowed: " + cmd[:200])
                msgs.append({"role": "user", "content": observation(126, "NOT RUN - the owner did not allow it%s." % (
                    "" if approve else " (nobody is there to ask)"))})
                continue
        recent = [_cmd_key(c) for c, _ in ran[-8:]]
        if recent.count(_cmd_key(cmd)) >= 3:
            # going round in circles (cat the file, append to it, cat it again ...): say so once, then stop
            if nudged:
                last_thought = ("BLOCKED - going round in circles: `%s` ran %d times in the last 8 steps without "
                                "getting anywhere." % (_cmd_key(cmd)[:120], recent.count(_cmd_key(cmd)) + 1))
                exit_reason = "stuck"
                break
            nudged = 1
            msgs.append({"role": "user", "content": "STOP: you already ran `%s` %d times. Long outputs are only "
                         "SHORTENED in your view - the files on disk are complete. Check with `wc -l` or `tail`, then "
                         "move to the next part of the task or finish." % (_cmd_key(cmd)[:120], recent.count(_cmd_key(cmd)))})
            continue
        say("tool", "$ " + cmd[:400])
        code, out = (builtins(cmd) if builtins and re.match(r"^\s*loki\s+chats\b", cmd) else None) or execute(cmd)
        ran.append((cmd, code))
        fails.append(_failure_key(code, out))
        if len(fails) >= 3 and fails[-1] and fails[-1] == fails[-2] == fails[-3]:
            # the same failure three times in a row: stop and say what is wrong instead of burning steps (owner's Mac
            # 2026-10-25: 30 steps of 'git push ... 403')
            last_thought = "BLOCKED - the same error three times:\n```\n%s\n```" % out.strip()[-1200:]
            exit_reason = "stuck"
            break
        say("tool_result" if code == 0 else "error", ("exit %d: %s" % (code, out))[:400])
        extra = ""
        if len([b for b in _BLOCK.findall(re.sub(r"<think>.*?</think>", "", reply, flags=re.S)) if b.strip()]) > 1:
            extra = "\n(Only your FIRST code block ran. Send the next command now.)"
        msgs.append({"role": "user", "content": observation(code, out) + extra})
    chs = dsh_engine.changes(before, dsh_engine.snapshot(ws))
    reply = verify(task, ws, chs, last_thought, exit_reason, ran, shell)
    if not root_git and (ws / ".git").exists() and not re.search(r"\b(this|the) (folder|workspace)\b", task, re.I):
        reply += ("\n\nNote: it also turned the whole working folder (%s) into a git repo. That was not asked for - "
                  "remove its .git folder if you don't want it (your chats in .loki/ are kept out of git)." % ws)
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


_RISKY = re.compile(r"(^|[;&|(]\s*|\b(sudo|xargs|exec)\s+)(rm|rmdir|unlink|shred|srm|trash|del|erase|rd|Remove-Item)\b"
                    r"|\bgit\s+(reset\s+--hard|clean\b|push\b[^\n]*(--force|\s-f\b)|branch\s+-D|checkout\s+--|stash\s+(drop|clear))"
                    r"|\bfind\b[^\n]*\s-delete\b|\bmv\b[^\n]*\s-f\b|\bloki\s+chats\s+delete\b|\btruncate\b"
                    r"|\bdropdb\b|\bDROP\s+(TABLE|DATABASE)\b", re.I)


def needs_ok(cmd: str) -> bool:
    """Does this command remove or overwrite something (so the owner is asked first)?"""
    return bool(_RISKY.search(cmd or ""))


def _failure_key(code: int, out: str) -> str:
    """The kind of failure ('' for a success): the error line with numbers and paths blurred, so 'push ... 403' twice
    with different wording still matches."""
    if code == 0:
        return ""
    lines = [ln for ln in (out or "").splitlines() if re.search(r"error|fatal|denied|refused|not found|403|401|failed", ln, re.I)]
    key = (lines[-1] if lines else (out or "").strip().splitlines()[-1:] or [""])
    key = key if isinstance(key, str) else key[0]
    return re.sub(r"[0-9a-f]{7,}|\d+|/[^\s'\"]+", "#", key.lower()).strip()[:200]


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
    pushed_ok = None
    if re.search(r"\b(push|publish|upload|github)\b", task, re.I):
        # pushing changes no file: LOKI asks GitHub itself whether the repo's commit is really there
        named = [d for d in sorted(ws.iterdir()) if (d / ".git").is_dir() and re.search(r"\b%s\b" % re.escape(d.name), task, re.I)] \
            if ws.is_dir() else []
        for d in named[:2]:
            code, out = run_command("git remote get-url origin && git rev-parse HEAD && git ls-remote origin", d,
                                    timeout=40, shell=shell)
            parts = out.split()
            here = parts[1] if len(parts) > 1 else ""
            pushed_ok = bool(code == 0 and here and here in parts[2:])
            lines.append("Checked by LOKI - on GitHub: %s" % (
                "%s has commit %s - pushed." % (re.sub(r"\.git$", "", parts[0]), here[:7]) if pushed_ok else
                "NOT pushed (%s)." % (out.strip().splitlines()[-1][:300] if out.strip() else "no remote")))
    wants_change = bool(re.search(r"\b(make|create|build|write|add|commit|init|set ?up|generate|fix|change|edit|"
                                  r"rename|move|delete|install)\b", task, re.I))
    if exit_reason == "done" and pushed_ok is False:
        lines.insert(0, "NOT DONE - the push did not reach GitHub.")
    if exit_reason != "done" or (wants_change and not chs and not pushed_ok):
        why = {"steps": "it ran out of steps", "time": "it ran out of time", "format": "the model stopped giving "
               "commands", "cancelled": "you stopped it", "done": "it said done but nothing changed in the folder"}
        if exit_reason in ("question", "stuck"):     # a question for the owner / a clear blocker: said as it is
            return "\n\n".join(lines).strip()
        lines.insert(0, "NOT DONE - %s (%d commands run)." % (why.get(exit_reason, exit_reason), len(ran)))
    if wants_change and re.search(r"\bgit\b", task, re.I) and re.search(r"\b(repo|repository|init|commit)\b", task, re.I) \
            and not repos and exit_reason == "done":
        lines.insert(0, "NOT DONE - no git repository was made or changed in %s." % ws)
    return "\n\n".join(lines).strip() or "(the local model finished without a word)"
