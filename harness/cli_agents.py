"""Claude Code and Codex as first-class Loki providers.

These two are not API clients. Once installed and signed in they are complete
coding agents that run on YOUR subscription allowance instead of per-token
billing - the flat rate you already pay, so an extra request costs nothing more.
Loki drives them in non-interactive mode inside the project folder, so they use
their own file/edit/shell tools on the real project, and Loki shows what they did.

Loki's own MCP servers are handed to Claude Code as well, so it also gets the
Godot editor tools. Codex has no MCP-passthrough flag, so it simply runs with its
own tools in the project directory.

Nothing here needs a key. Installation and sign-in are the user's job; when the
CLI is missing we say exactly what to run rather than failing obscurely.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import openai

# One place to look at when a CLI changes its flags. argv is built as
# [exe] + args, with the prompt appended.
CLI_AGENTS: dict[str, dict] = {
    "claude-code": {
        "label": "Claude Code",
        "exe": ("claude", "claude.cmd", "claude.exe", "claude.ps1"),
        "install": "npm install -g @anthropic-ai/claude-code",
        "signin": "claude   (then type /login and follow the browser prompt)",
        "args": ("-p", "--output-format", "json"),
        "parse": "json_result",
        "supports_mcp": True,
    },
    "codex": {
        "label": "Codex",
        "exe": ("codex", "codex.cmd", "codex.exe"),
        "install": "npm install -g @openai/codex",
        "signin": "codex login",
        # workspace-write: codex defaults to a read-only sandbox, so without this it
        # can read the project but every edit it attempts fails. --skip-git-repo-check
        # because not every Godot project is a git repo. --color never keeps the text
        # we hand back to the model clean.
        "args": ("exec", "--sandbox", "workspace-write", "--skip-git-repo-check",
                 "--color", "never"),
        "parse": "plain",
        "supports_mcp": False,
    },
}


class CliAgentError(openai.OpenAIError):
    """The CLI could not be found, refused to run, or is not signed in.

    Deliberately an OpenAIError so Loki's existing failure path reports the
    message and moves on to the next provider instead of crashing the run.
    """


def ensure_workspace(path: str) -> str:
    """Return a usable working directory, creating it when Loki pointed at one."""
    if not path:
        return ""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return ""


def find_cli(name: str) -> str:
    """Absolute path to the CLI executable, or "" when it is not installed."""
    spec = CLI_AGENTS.get(name)
    if spec is None:
        return ""
    override = os.getenv("LOKI_%s_EXE" % name.upper().replace("-", "_"), "").strip()
    if override and Path(override).exists():
        return override
    for candidate in spec["exe"]:
        found = shutil.which(candidate)
        if found:
            return found
    return ""


def is_available(name: str) -> bool:
    return bool(find_cli(name))


def missing_hint(name: str) -> str:
    spec = CLI_AGENTS[name]
    return ("%s is not installed. Install it, then sign in:\n"
            "  1. %s\n  2. %s\n"
            "Loki will then use your %s subscription - no API key, no per-token bill."
            % (spec["label"], spec["install"], spec["signin"], spec["label"]))


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def build_prompt(messages: list, workspace: str, max_chars: int = 24000) -> tuple[str, str]:
    """Turn Loki's message list into (system, prompt) for a CLI agent.

    Loki's own system prompt is deliberately NOT forwarded: it is almost entirely
    documentation of Loki's tools, which these agents have their own equivalents
    of. That keeps the command line short and avoids confusing them.
    """
    system = (
        "You are working inside the Godot project at %s. Use your own tools to read and "
        "edit files there. Make the change the user asks for, then state briefly what you "
        "changed and anything you could not do." % workspace
    )
    parts: list[str] = []
    for item in messages:
        role = item.get("role", "")
        if role == "system":
            continue
        content = item.get("content") or ""
        if isinstance(content, list):
            content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if not str(content).strip():
            if role == "assistant" and item.get("tool_calls"):
                parts.append("[assistant ran tools]")
            continue
        parts.append("%s: %s" % (role, content))
    return system, _clip("\n\n".join(parts), max_chars)


def mcp_config_args(servers_path: Path) -> list[str]:
    """Translate Loki's mcp_servers.json into Claude Code's --mcp-config file.

    Best effort: a server whose command cannot be expressed is skipped rather
    than breaking the whole launch.
    """
    if not servers_path.exists():
        return []
    try:
        raw = json.loads(servers_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = raw.get("mcpServers") if isinstance(raw, dict) else raw
    if not isinstance(entries, dict):
        return []
    translated: dict = {}
    for name, spec in entries.items():
        if not isinstance(spec, dict) or spec.get("enabled") is False:
            continue
        command = spec.get("command")
        if not command:
            continue
        entry = {"command": command, "args": list(spec.get("args") or [])}
        if spec.get("env"):
            entry["env"] = spec["env"]
        translated[name] = entry
    if not translated:
        return []
    out = servers_path.parent / ".godot" / "loki_claude_mcp.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"mcpServers": translated}, indent=2), encoding="utf-8")
    except Exception:
        return []
    return ["--mcp-config", str(out)]


def run(name: str, system: str, prompt: str, workspace: str, timeout: int = 900) -> str:
    """Run the CLI once, non-interactively, and return its final text."""
    spec = CLI_AGENTS.get(name)
    if spec is None:
        raise CliAgentError("unknown CLI agent %r" % name)
    exe = find_cli(name)
    if not exe:
        raise CliAgentError(missing_hint(name))

    argv = [exe, *spec["args"]]
    if spec["supports_mcp"]:
        argv += mcp_config_args(Path(__file__).with_name("mcp_servers.json"))
        argv += ["--append-system-prompt", system]
    argv.append(prompt)

    env = dict(os.environ)
    env["LOKI_CLI_AGENT"] = name
    # A cwd that does not exist makes CreateProcess fail with WinError 267 before the
    # CLI ever runs, so only pass a directory we have actually confirmed.
    cwd = workspace if workspace and os.path.isdir(workspace) else None
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CliAgentError("%s ran longer than %ds and was stopped." % (spec["label"], timeout)) from exc
    except OSError as exc:
        raise CliAgentError("%s could not be started: %s" % (spec["label"], exc)) from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0 and not stdout:
        raise CliAgentError("%s exited with code %d.\n%s" % (spec["label"], proc.returncode, stderr[:1500]))

    if spec["parse"] == "json_result":
        text = _extract_json_result(stdout) or stdout or stderr
    else:
        text = stdout or stderr

    # The CLI reports a missing or expired sign-in on stderr with a zero exit code.
    low = (stdout + "\n" + stderr).lower()
    if not text.strip() or ("not logged in" in low) or ("please log in" in low) or ("authentication" in low and "error" in low):
        raise CliAgentError("%s is not signed in.\n%s" % (spec["label"], spec["signin"]))
    return text


def _extract_json_result(stdout: str) -> str:
    """Pull the answer out of Claude Code's --output-format json envelope."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            for key in ("result", "text", "content"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return


# --- OpenAI-shaped face so Loki's turn loop cannot tell a CLI agent from an API ---
class _CliMessage:
    def __init__(self, content: str) -> None:
        self.role = "assistant"
        self.content = content
        self.tool_calls = None
        self.reasoning_content = None


class _CliChoice:
    def __init__(self, content: str) -> None:
        self.index = 0
        self.message = _CliMessage(content)
        self.finish_reason = "stop"


class _CliResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_CliChoice(content)]
        self.usage = None
        self.model = "cli-agent"


class _CliCompletions:
    """Mimics openai's async completions endpoint.

    A CLI agent is already a complete agent: it does its own tool use inside the
    project and returns finished prose. So every call answers with no tool_calls,
    which is exactly how Loki's loop recognises "this turn is the final answer".
    """

    def __init__(self, name: str, workspace: str, timeout: int) -> None:
        self._name = name
        self._workspace = workspace
        self._timeout = timeout

    async def create(self, **kwargs):
        system, prompt = build_prompt(kwargs.get("messages") or [], self._workspace)
        text = await asyncio.to_thread(run, self._name, system, prompt, self._workspace, self._timeout)
        return _CliResponse(text)


class _CliChat:
    def __init__(self, completions: _CliCompletions) -> None:
        self.completions = completions


class CliAgentClient:
    """An AsyncOpenAI lookalike whose .chat.completions.create() runs a CLI agent."""

    def __init__(self, name: str, workspace: str, timeout: int = 900) -> None:
        self.name = name
        self.chat = _CliChat(_CliCompletions(name, workspace, timeout))


def make_client(name: str, workspace: str, timeout: int = 900) -> CliAgentClient:
    """Build a client for a CLI agent ("claude-code" / "codex")."""
    return CliAgentClient(name, workspace, timeout)
