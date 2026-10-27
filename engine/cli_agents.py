"""Claude Code, Codex and OpenCode as first-class Loki providers.

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
        # `claude -p` reads the prompt from stdin when none is given: long prompts go that way,
        # because Windows caps a whole command line at 32,767 characters.
        "stdin_prompt": True,
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
    # OpenCode (github.com/anomalyco/opencode, MIT): open-source coding agent that works
    # with any provider, including OpenCode Zen's free models. `opencode run` is its
    # non-interactive mode; LOKI_OPENCODE_MODEL=provider/model picks the model.
    "opencode": {
        "label": "OpenCode",
        "exe": ("opencode", "opencode.cmd", "opencode.exe"),
        "install": "npm i -g opencode-ai@latest   (or: brew install anomalyco/tap/opencode)",
        "signin": "opencode auth login   (or use Zen's free models with no sign-in)",
        "args": ("run",),
        "parse": "plain",
        "supports_mcp": False,
        "system_in_prompt": True,
        "model_env": "LOKI_OPENCODE_MODEL",
    },
    # OpenHands CLI (OpenHands/OpenHands, MIT). Headless one-shot: --json prints JSON events,
    # -t is the task. The model is LOKI's local Ollama model unless LOKI_OPENHANDS_MODEL says
    # otherwise (workers.openhands_env sets LLM_MODEL / LLM_BASE_URL / LLM_API_KEY).
    "openhands": {
        "label": "OpenHands",
        "exe": ("openhands", "openhands.exe", "openhands.cmd"),
        "install": "uv tool install openhands --python 3.12   (or: python tools/setup_extras.py openhands)",
        "signin": "nothing to sign in to: it uses LOKI's local Ollama model (set LOKI_OPENHANDS_MODEL for another)",
        "args": ("--headless", "--json", "--override-with-envs", "-t"),
        "parse": "jsonl_last",
        "supports_mcp": False,
        "system_in_prompt": True,
        "llm_env": True,
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
    from win_shim import real_exe  # pylint: disable=import-outside-toplevel
    if override and Path(override).exists():
        return real_exe(override)
    for candidate in spec["exe"]:
        found = shutil.which(candidate)
        if found:   # Windows: an npm .cmd shim runs in cmd.exe (8,191-char line, mangled newlines) - use its .exe
            return real_exe(found)
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
    # NOT inside engine/: this is runtime state and must not litter the source tree.
    base = Path(os.environ.get("LOKI_DATA") or tempfile.gettempdir())
    out = base / "loki_claude_mcp.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"mcpServers": translated}, indent=2), encoding="utf-8")
    except Exception:
        return []
    return ["--mcp-config", str(out)]


ARGV_LIMIT = 24000   # characters; Windows allows 32,767 for the whole command line


def _clean_arg(text: str) -> str:
    """Text safe to pass as one command-line argument: no NUL or other control bytes."""
    return "".join(ch for ch in str(text or "") if ch in "\t\n\r" or ord(ch) >= 32)


def run(name: str, system: str, prompt: str, workspace: str, timeout: int = 900) -> str:
    """Run the CLI once, non-interactively, and return its final text."""
    spec = CLI_AGENTS.get(name)
    if spec is None:
        raise CliAgentError("unknown CLI agent %r" % name)
    exe = find_cli(name)
    if not exe:
        raise CliAgentError(missing_hint(name))

    # A NUL byte (from a binary file the agent read) makes CreateProcess raise "embedded null
    # character" on Windows and kills the whole job: drop them (and other C0 controls but tabs
    # and newlines) from everything that goes on the command line.
    system = _clean_arg(system)
    prompt = _clean_arg(prompt)
    argv = [exe, *spec["args"]]
    if spec.get("model_env") and os.getenv(spec["model_env"], "").strip():
        argv += ["-m", os.getenv(spec["model_env"], "").strip()]
    if spec["supports_mcp"]:
        argv += mcp_config_args(Path(__file__).with_name("mcp_servers.json"))
        argv += ["--append-system-prompt", system]
    if spec.get("system_in_prompt") and system.strip():
        prompt = system.strip() + "\n\n" + prompt
    stdin_text = None
    if spec.get("stdin_prompt") and (len(prompt) + sum(len(a) for a in argv)) > ARGV_LIMIT:
        if "--append-system-prompt" in argv and sum(len(a) for a in argv) > ARGV_LIMIT:
            at = argv.index("--append-system-prompt")   # a huge system prompt rides in the prompt too
            prompt = argv[at + 1] + "\n\n" + prompt
            del argv[at:at + 2]
        stdin_text = prompt
    else:
        if len(prompt) + sum(len(a) for a in argv) > ARGV_LIMIT:
            prompt = prompt[-max(2000, ARGV_LIMIT - sum(len(a) for a in argv)):]   # keep the newest part
        argv.append(prompt)

    env = dict(os.environ)
    if spec.get("llm_env"):
        import workers  # pylint: disable=import-outside-toplevel  (stdlib only, no cycle)
        env = workers.openhands_env(env)
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
            input=stdin_text,
            stdin=None if stdin_text is not None else subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CliAgentError("%s ran longer than %ds and was stopped." % (spec["label"], timeout)) from exc
    except (OSError, ValueError) as exc:
        raise CliAgentError("%s could not be started: %s" % (spec["label"], exc)) from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0 and not stdout:
        raise CliAgentError("%s exited with code %d.\n%s" % (spec["label"], proc.returncode, stderr[:1500]))

    if spec["parse"] == "json_result":
        text = _extract_json_result(stdout) or stdout or stderr
    elif spec["parse"] == "jsonl_last":
        text = extract_jsonl_message(stdout) or stdout or stderr
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


def extract_jsonl_message(stdout: str) -> str:
    """The last thing the agent said, from a JSON-events stream (OpenHands --json)."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        for node in (data, data.get("message") if isinstance(data.get("message"), dict) else None,
                     data.get("args") if isinstance(data.get("args"), dict) else None):
            if not isinstance(node, dict):
                continue
            for key in ("final_thought", "content", "message", "text", "result"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


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
