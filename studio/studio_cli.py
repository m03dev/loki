"""Claude Code or Codex as a Studio session's driver (the owner's own subscriptions).

Instead of Studio's own loop, the CLI does the turn with ITS tools, in the session's root (the
LOKI worktree or the Godot project), and gets Studio's tools through Studio's MCP server
(studio_mcp.py: the live Godot editor, playtest, find lag, screenshots, the Godot docs, the
project index) - plus, in a LOKI session, the LOKI MCP API bound to the worktree (risky tools
still refuse without the owner). Its output streams into the thread; the conversation continues
with --resume (Claude Code) on the next message. Plan / Ask mode -> the CLI's read-only mode.

    model "claude-code":  claude -p <prompt> --output-format stream-json --verbose --mcp-config <cfg>
                          --permission-mode acceptEdits|plan [--resume <id>]
    model "codex":        codex exec --json -s workspace-write|read-only -c mcp_servers.loki_studio... <prompt>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import studio_paths
import studio_godot

TIMEOUT_S = float(os.getenv("LOKI_STUDIO_CLI_TIMEOUT", "3600") or 3600)


def mcp_servers(session, studio) -> dict:
    servers = {"loki_studio": {"command": sys.executable,
                               "args": [str(studio_paths.HERE / "studio_mcp.py"), "--connect", str(studio_godot.connect_path()),
                                        "--project", str(session.work_root)]}}
    if session.kind == "loki":
        servers["loki"] = {"command": sys.executable, "args": [str(studio_paths.ENGINE / "loki_mcp.py"), "--worktree",
                                                              str(session.work_root), "--repo", str(studio.repo)]}
    return servers


def argv_for(which: str, prompt: str, session, studio) -> list:
    mode = session.meta.get("mode") or "default"
    servers = mcp_servers(session, studio)
    if which == "claude-code":
        cfg = session.root / "mcp.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"mcpServers": servers}, indent=1), encoding="utf-8")
        argv = [shutil.which("claude") or "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
                "--mcp-config", str(cfg), "--permission-mode", "plan" if mode in ("plan", "ask") else "acceptEdits"]
        if session.meta.get("cli_session"):
            argv += ["--resume", str(session.meta["cli_session"])]
        return argv
    argv = [shutil.which("codex") or "codex", "exec", "--json", "-s", "read-only" if mode in ("plan", "ask") else "workspace-write"]
    for name, spec in servers.items():
        argv += ["-c", "mcp_servers.%s.command=%s" % (name, json.dumps(spec["command"])),
                 "-c", "mcp_servers.%s.args=%s" % (name, json.dumps(spec["args"]))]
    return argv + [prompt]


def parse_line(which: str, line: str) -> list:
    """[(kind, text)] from one JSON line of the CLI's stream; ("final", text) for the answer, ("session", id)."""
    try:
        ev = json.loads(line)
    except ValueError:
        return [("progress", line.strip()[:400])] if line.strip() else []
    out = []
    if which == "claude-code":
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    out.append(("assistant_part", block["text"]))
                elif block.get("type") == "tool_use":
                    out.append(("tool", "%s(%s)" % (block.get("name"), json.dumps(block.get("input"), ensure_ascii=False)[:300])))
                elif block.get("type") == "thinking" and block.get("thinking"):
                    out.append(("thinking", block["thinking"][:4000]))
        elif ev.get("type") == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    text = content if isinstance(content, str) else " ".join(c.get("text", "") for c in content or [] if isinstance(c, dict))
                    out.append(("result", str(text)[:3000]))
        elif ev.get("type") == "result":
            if ev.get("session_id"):
                out.append(("session", ev["session_id"]))
            out.append(("final", str(ev.get("result") or "")))
        elif ev.get("type") == "system" and ev.get("session_id"):
            out.append(("session", ev["session_id"]))
        return out
    item = ev.get("item") or ev.get("msg") or {}
    kind = str(item.get("type") or ev.get("type") or "")
    text = item.get("text") or item.get("message") or ""
    if kind in ("agent_message", "assistant_message"):
        out.append(("final", str(text)))
    elif kind in ("reasoning", "agent_reasoning"):
        out.append(("thinking", str(text)[:4000]))
    elif kind in ("command_execution", "exec_command_begin", "mcp_tool_call", "file_change"):
        out.append(("tool", json.dumps({k: item.get(k) for k in ("command", "tool", "server", "changes", "status") if item.get(k)},
                                       default=str)[:400]))
    elif ev.get("type") == "thread.started" and ev.get("thread_id"):
        out.append(("session", ev["thread_id"]))
    return out


def run(which: str, prompt: str, session, studio, emit, stop, popen=subprocess.Popen) -> dict:
    """Drive one turn with the CLI. emit(kind, text) streams into the thread."""
    binary = "claude" if which == "claude-code" else "codex"
    if not shutil.which(binary) and popen is subprocess.Popen:
        return {"ok": False, "text": "%s is not installed on this machine (Studio looks for `%s` on PATH). Install it and sign in, "
                                      "or pick another model with /model." % (which, binary)}
    argv = argv_for(which, prompt, session, studio)
    emit("progress", "Running %s in %s..." % (which, session.work_root))
    try:
        proc = popen(argv, cwd=str(session.work_root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                     encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "text": "could not start %s: %s" % (which, exc)}
    final, parts, sid = "", [], ""
    killer = threading.Thread(target=_watch, args=(proc, stop, time.time() + TIMEOUT_S), daemon=True)
    killer.start()
    for line in proc.stdout:
        for kind, text in parse_line(which, line):
            if kind == "final":
                final = text
            elif kind == "assistant_part":
                parts.append(text)
            elif kind == "session":
                sid = text
            else:
                emit(kind, text)
    code = proc.wait()
    text = final or "\n".join(parts)
    if stop.is_set():
        return {"ok": False, "text": "stopped", "session": sid}
    return {"ok": code == 0, "text": text or ("%s exited with %s" % (which, code)), "session": sid}


def _watch(proc, stop, deadline: float) -> None:
    while proc.poll() is None:
        if stop.is_set() or time.time() > deadline:
            try:
                proc.terminate()
            except OSError:
                pass
            return
        time.sleep(0.3)
