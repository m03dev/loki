"""LOKI's agent is OpenCode now, with CodeGraph as its code map (owner 2026-10-25: "get rid of LOKI['s agent], replace
it ... just make my agent actually work"; picked "a proven agent + CodeGraph").

Why: LOKI's own loop let a model answer "Done! I created the repo" without calling a tool, and nothing happened.
OpenCode (github.com/anomalyco/opencode, MIT) is a working open-source coding agent - files, edits, bash, git, MCP.
CodeGraph (github.com/colbymchenry/codegraph, MIT) gives it a pre-indexed graph of the code (one MCP tool,
codegraph_explore). LOKI drives OpenCode and shows what it did; it does not run its own loop for these turns.

How one turn runs (run_turn):
  opencode run --format json --dir <workspace> [--session <id>] [--model loki-<provider>/<model>] [--agent plan] <text>
  with OPENCODE_CONFIG pointing at a config LOKI writes (build_config):
    provider   every provider LOKI has a key for, as an OpenAI-compatible provider "loki-<name>"; the key is passed in
               an environment variable ({env:LOKI_OC_KEY_<NAME>}), never written to the file
    mcp        codegraph (codegraph serve --mcp) when CodeGraph is installed
    permission everything in the workspace is allowed; LOKI's destructive command list is DENIED; anything outside
               the workspace is denied. (`opencode run` cannot ask a human - an "ask" would just be rejected.)
  stdout is JSON lines: {"type": "text"|"tool_use"|"step_start"|"step_finish"|"reasoning"|"error", "sessionID", "part"}
  -> every tool call is reported to LOKI's window as it happens, and counted.

Ask / Plan mode use OpenCode's read-only "plan" agent. One OpenCode session per LOKI conversation (sessions.json), so
a chat keeps its context. If the chosen provider fails before doing anything, the next configured one is tried.
Standard library only; the subprocess runner is injectable for tests.
"""
from __future__ import annotations

import live_guard  # noqa: E402 - engine/ is on sys.path for every LOKI module
import json
import os
import sys
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_TIMEOUT = int(os.getenv("LOKI_OPENCODE_TIMEOUT", "1200"))
INSTALL = {"opencode": "npm i -g opencode-ai@latest", "codegraph": "npm i -g @colbymchenry/codegraph",
           "dsh": "npm i -g @deepseek-ai/dsh"}   # dsh: DeepSeek Harness, the agent for a DeepSeek model (dsh_engine.py)
OC_EXE = ("opencode", "opencode.cmd", "opencode.exe")
CG_EXE = ("codegraph", "codegraph.cmd", "codegraph.exe")


# ------------------------------------------------------------------ finding the programs
def _find(names: Iterable[str], env_key: str, extra: Iterable[str] = ()) -> str:
    from win_shim import real_exe  # pylint: disable=import-outside-toplevel
    own = os.getenv(env_key, "").strip()
    if own and Path(own).is_file():
        return real_exe(own)
    for n in names:
        found = shutil.which(n)
        if found:   # Windows: npm's opencode.cmd runs inside cmd.exe (8,191-char line) - start the real .exe
            return real_exe(found)
    for p in extra:
        if p and Path(p).is_file():
            return real_exe(p)
    return ""


def _global_bins() -> list:
    """Where npm / brew put programs - a Mac app does not get the shell's PATH, so look there too."""
    home = Path.home()
    out = ["/opt/homebrew/bin", "/usr/local/bin", str(home / ".npm-global" / "bin"), str(home / ".local" / "bin"),
           str(home / ".bun" / "bin")]
    if os.name == "nt":
        out += [str(Path(os.getenv("APPDATA", "")) / "npm")]
    try:
        out += sorted(str(p) for p in (home / ".nvm" / "versions" / "node").glob("*/bin"))[-3:]
    except OSError:
        pass
    return out


def _in_bins(names: Iterable[str]) -> list:
    return [str(Path(d) / n) for d in _global_bins() for n in names]


def find_opencode() -> str:
    home = Path.home()
    return _find(OC_EXE, "LOKI_OPENCODE_EXE", [str(home / ".opencode" / "bin" / "opencode"),
                                               str(home / ".opencode" / "bin" / "opencode.exe")] + _in_bins(OC_EXE))


def find_codegraph() -> str:
    home = Path.home()
    return _find(CG_EXE, "LOKI_CODEGRAPH_EXE", [str(home / ".codegraph" / "bin" / "codegraph")] + _in_bins(CG_EXE))


def find_npm() -> str:
    return _find(("npm", "npm.cmd"), "LOKI_NPM_EXE", _in_bins(("npm", "npm.cmd")))


def _find_dsh() -> str:
    import dsh_engine  # pylint: disable=import-outside-toplevel
    return dsh_engine.find_dsh()


def install(which: Iterable[str] = ("opencode", "codegraph", "dsh"), runner=subprocess.run) -> dict:
    """npm i -g the missing ones (the button in Settings > Agent). {name: "ok" | "already" | error}."""
    have = {"opencode": find_opencode, "codegraph": find_codegraph, "dsh": _find_dsh}
    pkgs = {"opencode": "opencode-ai@latest", "codegraph": "@colbymchenry/codegraph", "dsh": "@deepseek-ai/dsh"}
    npm = find_npm()
    out = {}
    for name in which:
        if name not in pkgs:
            continue
        if have[name]():
            out[name] = "already"
            continue
        if not npm:
            out[name] = "npm (Node.js) is not installed - install Node.js from nodejs.org, then press Install again"
            continue
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([str(Path(npm).parent)] + _global_bins() + [env.get("PATH", "")])
        try:
            r = runner([npm, "i", "-g", pkgs[name]], capture_output=True, text=True, timeout=600, env=env,
                       stdin=subprocess.DEVNULL)
            out[name] = "ok" if r.returncode == 0 and have[name]() else ("npm failed: " + (r.stderr or r.stdout or "")[-300:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            out[name] = "npm failed: %s" % exc
    return out


# The harness that runs a message - swappable (owner 2026-10-25: "i should be able to swap out different harnesses,
# everything should be modular"). Settings > Agent and the Harness menu next to the model menu set it.
HARNESSES = {
    "auto": ("Auto", "The best one for the model picked: a model on this computer -> Shell agent; DeepSeek -> DeepSeek "
                     "Harness when installed; anything else -> OpenCode (Shell agent when OpenCode is not installed)."),
    "opencode": ("OpenCode", "OpenCode + CodeGraph: files, edits, bash, git and a code map. Best with strong cloud models."),
    "dsh": ("DeepSeek Harness", "DeepSeek's own open-source agent (dsh). Made for DeepSeek, runs any OpenAI-compatible model."),
    "shell": ("Shell agent", "mini-swe-agent's recipe: one shell command per step, the real output back. Small prompt - "
                             "the one for local models, works with any model."),
    "codex": ("Codex (your ChatGPT plan)", "OpenAI's Codex CLI signed in with YOUR ChatGPT account - the latest GPT "
                                           "(GPT-6 on Plus and up) on your plan's allowance. Needs `codex login` once."),
    "claude-code": ("Claude Code (your Claude plan)", "Anthropic's Claude Code CLI on YOUR Claude subscription. Needs "
                                                      "`claude` + /login once."),
    "loki": ("LOKI classic", "LOKI's own built-in loop with all of LOKI's tools (pictures, apps, browser, memory ...)."),
}


def engine_choice(env: dict | None = None) -> str:
    """LOKI_AGENT_ENGINE: auto (default) | opencode | dsh | shell | loki."""
    value = str((env if env is not None else os.environ).get("LOKI_AGENT_ENGINE", "auto")).strip().lower()
    return value if value in HARNESSES else "auto"


# ------------------------------------------------------------------ the config OpenCode runs with
def key_env(name: str) -> str:
    return "LOKI_OC_KEY_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


def provider_id(name: str) -> str:
    return "loki-" + re.sub(r"[^a-z0-9-]", "-", name.lower())


def deny_rules(snippets: Iterable[str]) -> dict:
    """LOKI's destructive command list as OpenCode bash rules: allow everything, then deny these (last match wins).

    OpenCode checks each command of a pipeline on its own, case-insensitively on Windows. A snippet that ends in a space
    is a COMMAND NAME ("format " = the disk formatter): it becomes "format *" (that command, with any arguments) - never
    "*format*", which denied every PowerShell `Format-Table` / `Format-List` (2026-10-27, the PC: jobs could not even
    list a folder). The others match anywhere in the command."""
    rules = {"*": "allow"}
    for s in snippets:
        raw = str(s)
        s = " ".join(raw.split())
        if not s:
            continue
        if raw.endswith(" ") and " " not in s:
            rules[s + " *"] = "deny"
        else:
            rules["*" + s + "*"] = "deny"
    return rules


def outside_dirs() -> list:
    """Folders outside the job's workspace an unattended job may use: LOKI's own folder (the tasks say "in LOKI's
    folder: ..."), the owner's LOKI Projects and the temp folder. Everything else stays denied - `opencode run` cannot
    ask anyone, and an "ask" is a refusal (2026-10-27, the PC: every DO FIRST task died on its first command in D:/loki).
    LOKI_OC_ALLOW_DIRS (os.pathsep-separated) adds more."""
    import tempfile  # pylint: disable=import-outside-toplevel
    dirs = [Path(__file__).resolve().parent.parent, Path.home() / "LOKI Projects", Path(tempfile.gettempdir())]
    data = os.getenv("LOKI_DATA", "").strip()
    if data:
        dirs.append(Path(data))
    if os.name != "nt":   # the shell's /tmp is not Python's temp folder on a Mac (/var/folders/...): an agent that wrote
        dirs += [Path("/tmp")]   # /tmp/out.json could not read it back (2026-10-28, the Mac, job 09a081f5 - stuck)
    dirs += [Path(p) for p in os.getenv("LOKI_OC_ALLOW_DIRS", "").split(os.pathsep) if p.strip()]
    for d in list(dirs):  # and the real path behind a link (/tmp -> /private/tmp, /var -> /private/var)
        try:
            r = d.resolve()
            if r != d:
                dirs.append(r)
        except OSError:
            pass
    out, seen = [], set()
    for d in dirs:
        key = str(d).replace("\\", "/").rstrip("/")
        if key and key.lower() not in seen:
            seen.add(key.lower())
            out.append(key)
    return out


def external_rules(plan: bool = False) -> dict | str:
    if plan:
        return "deny"
    rules: dict = {"*": "deny"}
    for d in outside_dirs():
        rules[d + "/*"] = "allow"
        rules[d] = "allow"
    return rules


# DeepSeek's own tool-call markup (<｜DSML｜function_calls> ... - full-width bars, sometimes ASCII ones): a provider that
# does not parse it hands it back as TEXT, so the tool never runs (owner 2026-10-25: "<｜DSML｜ calls>" x10 in a reply)
_DSML = re.compile(r"<\s*/?\s*[｜|]\s*DSML\s*[｜|][^>]*>", re.I)


def leaked_tool_markup(text: str) -> bool:
    return bool(_DSML.search(str(text or "")))


def strip_tool_markup(text: str) -> str:
    """The reply without DeepSeek's raw tool-call tags (and the lines that held only them)."""
    out = [ln for ln in _DSML.sub("", str(text or "")).splitlines()]
    cleaned, blank = [], 0
    for ln in out:
        blank = blank + 1 if not ln.strip() else 0
        if blank <= 1:
            cleaned.append(ln)
    return "\n".join(cleaned).strip()


def make_tools_command(python: str = "") -> list:
    """LOKI's making tools (engine/make_mcp.py: pictures, 3D models, video) as an MCP server for OpenCode."""
    return [python or sys.executable, str(Path(__file__).resolve().parent / "make_mcp.py")]


# hosts whose free tier caps output tokens PER MINUTE below one normal reply: asking more is refused outright
# (2026-10-25: Groq "Request too large ... output tokens per minute (OTPM): Limit 1000")
OUTPUT_CAPS = {"groq.com": 900}


def output_cap(base_url: str) -> int:
    for host, cap in OUTPUT_CAPS.items():
        if host in str(base_url or ""):
            return int(os.environ.get("LOKI_OC_MAX_OUTPUT_" + host.split(".")[0].upper(), cap) or cap)
    return int(os.environ.get("LOKI_OC_MAX_OUTPUT", "8192") or 8192)


def build_config(providers: dict, codegraph: str = "", plan: bool = False, deny: Iterable[str] = (),
                 make_tools: bool = True, workspace: str = "") -> dict:
    """providers: name -> {"base_url", "model", "key"}; returns OpenCode's config (keys referenced by env, not inlined)."""
    prov = {}
    for name, p in providers.items():
        base = str(p.get("base_url") or "")
        if not base.startswith("http"):
            continue
        prov[provider_id(name)] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LOKI: " + name,
            "options": {"baseURL": base.rstrip("/"), "apiKey": "{env:%s}" % key_env(name)},
            # a modest output cap: OpenCode otherwise asks for 32000 tokens a reply, and OpenRouter refuses that
            # on a free-credit account (2026-10-25: the PC's hand-off job failed "requested 32000 max_tokens, can
            # afford 3133" before it ever reached make_image). LOKI_OC_MAX_OUTPUT raises it.
            "models": {str(p.get("model")): {"name": str(p.get("model")), "limit": {
                "context": int(p.get("context") or (32768 if "11434" in base else 128000)),
                "output": output_cap(p.get("upstream") or base)}}},
        }
    cfg: dict = {"$schema": "https://opencode.ai/config.json", "provider": prov,
                 "permission": {"edit": "deny" if plan else live_guard.edit_rules(workspace),
                                "read": "allow", "glob": "allow", "grep": "allow",
                                "list": "allow", "webfetch": "allow", "todowrite": "allow",
                                "bash": "deny" if plan else {**deny_rules(deny), **live_guard.bash_rules(workspace)},
                                "external_directory": external_rules(plan)},
                 "autoupdate": False, "share": "disabled"}
    mcp: dict = {}
    if codegraph:
        mcp["codegraph"] = {"type": "local", "command": [codegraph, "serve", "--mcp"], "enabled": True}
    # owner 2026-10-25: "make real things like art 3d models or paintings comic books" - OpenCode writes and runs
    # code by itself; pictures, models and clips come from LOKI's own makers (not in Plan mode: they make files)
    if make_tools and not plan:
        mcp["loki-make"] = {"type": "local", "command": make_tools_command(), "enabled": True}
    # Godot AI (github.com/hi-godot/godot-ai, MIT): the live Godot editor's 46 tools, when a project has the add-on
    if not plan:
        gai = godot_ai_mcp()
        if gai:
            mcp["godot-ai"] = gai
    # showtime (github.com/FavioVazquez/showtime, MIT): the local video studio's MCP tools, once it is on the shelf
    if not plan:
        st = showtime_mcp()
        if st:
            mcp["showtime"] = st
    # VoiceStudio's own MCP server (engine/voice_studio.py) when its backend answers: speech, voices, transcription
    if not plan:
        try:
            import voice_studio  # pylint: disable=import-outside-toplevel
            vs = voice_studio.mcp_entry()
            if vs:
                mcp["voicestudio"] = vs
        except Exception:  # noqa: BLE001 - never blocks the agent
            pass
    if mcp:
        cfg["mcp"] = mcp
    return cfg


def job_data_env(folder, home: str | None = None) -> dict:
    """XDG_DATA_HOME / XDG_STATE_HOME of one background job's own OpenCode (its sessions database), with the owner's
    OpenCode sign-in (auth.json) copied in so OpenCode's own models still work there."""
    import shutil  # pylint: disable=import-outside-toplevel
    folder = Path(folder)
    data, state = folder / "data", folder / "state"
    (data / "opencode").mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    src_home = Path(home or os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    auth = src_home / "opencode" / "auth.json"
    try:
        if auth.is_file() and not (data / "opencode" / "auth.json").exists():
            shutil.copy2(auth, data / "opencode" / "auth.json")
    except OSError:
        pass
    return {"XDG_DATA_HOME": str(data), "XDG_STATE_HOME": str(state)}


def windows_bash(which=shutil.which, isfile=os.path.isfile, env: dict | None = None) -> str:
    """Git for Windows' bash.exe, or "". OpenCode on Windows otherwise runs every command in powershell.exe - on the
    PC that is Windows PowerShell 5.1, where `a && b` is a parse error. Every model writes `cd X && python ...`, got
    "The token '&&' is not a valid statement separator in this version" and wrote the same command again, step after
    step (2026-10-27, the PC: jobs b9903fd0 / decb449c looped on it until the context passed 200k tokens).
    OpenCode takes $SHELL when it points at an existing file (packages/core/src/shell/select.ts), so jobs get bash."""
    env = os.environ if env is None else env
    found = []
    git = which("git")
    if git:   # ...\Git\cmd\git.exe or ...\Git\bin\git.exe -> ...\Git\bin\bash.exe (OpenCode's own rule)
        found.append(str(Path(git).resolve().parent.parent / "bin" / "bash.exe"))
    for root in (env.get("ProgramFiles", r"C:\Program Files"), env.get("ProgramW6432", ""),
                 env.get("LOCALAPPDATA", "") and str(Path(env.get("LOCALAPPDATA", "")) / "Programs")):
        if root:
            found.append(str(Path(root) / "Git" / "bin" / "bash.exe"))
    return next((f for f in found if isfile(f)), "")


def shell_for(env: dict) -> str:
    """The shell OpenCode's bash tool will use with this env: 'bash' or 'powershell' (Windows) / 'sh'."""
    if os.name != "nt":
        return "bash"
    shell = str(env.get("SHELL") or "")
    return "bash" if shell and os.path.isfile(shell) else "powershell"


def shell_note(shell: str) -> str:
    """One paragraph for the agent's instructions: which shell its commands run in, so it writes them right first."""
    if shell == "powershell":
        return ("# Your shell\nYour commands run in Windows PowerShell 5.1: `&&` and `||` do NOT work there - use `;` "
                "(or `if ($?) { ... }`). Quote every path with a space in it. If a command fails, read the error and "
                "change the command - never send the same command again.")
    if os.name == "nt":
        return ("# Your shell\nYour commands run in Git Bash on Windows: `&&` works; write paths as /d/loki/... or "
                "\"D:/loki/...\" (quoted, forward slashes). Quote every path with a space in it. If a command fails, "
                "read the error and change the command - never send the same command again.")
    return ("# Your shell\nYour commands run in bash. Quote every path with a space in it. If a command fails, read "
            "the error and change the command - never send the same command again.")


def env_for(providers: dict, base: dict | None = None) -> dict:
    env = dict(base if base is not None else os.environ)
    for name, p in providers.items():
        key = str(p.get("key") or "")
        env[key_env(name)] = key if key and key != "none" else "none"
    env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
    live_guard.git_env(env)          # git in a job folder can never reach LOKI's own repo (the PC's stray commit)
    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + [d for d in _global_bins() if Path(d).is_dir()])
    if os.name == "nt" and os.getenv("LOKI_OC_SHELL", "bash").strip().lower() != "powershell" \
            and not (env.get("SHELL") and os.path.isfile(str(env.get("SHELL")))):
        bash = windows_bash(env=env)
        if bash:
            env["SHELL"] = bash
    return env


# ------------------------------------------------------------------ the same mistake again and again
_ERR_WORDS = re.compile(r"error|exception|traceback|not a valid|not recognized|no such file|not found|cannot|"
                        r"could not|denied|prevents you|failed|invalid|unexpected token|exit (-?[1-9]\d*)\b", re.I)


def error_signature(name: str, status: str, output: str) -> str:
    """What makes a failed tool call 'the same failure': the tool and its first error line, numbers and quoted bits
    blanked (two `cd X && ...` variants give one signature). "" for a call that did not fail."""
    text = str(output or "")
    if status == "completed" and not _ERR_WORDS.search(text):
        return ""
    line = next((ln for ln in text.splitlines() if _ERR_WORDS.search(ln)), text.strip().splitlines()[0] if text.strip() else status)
    line = re.sub(r"\d+", "#", line)
    line = re.sub(r"(['\"]).*?\1", "''", line)
    line = re.sub(r"[A-Za-z]:[\\/][^\s'\"]*", "<path>", line)
    return "%s: %s" % (name, " ".join(line.split())[:160])


class RepeatGuard:
    """Says when a turn is stuck: the same failure LOKI_OC_REPEAT_LIMIT times (default 3), or the very same call
    (tool + input) that many times in a row. The caller then stops the turn and hands it on (another model, told what
    went wrong) instead of letting a model burn its context on one broken command."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = max(2, int(limit or os.getenv("LOKI_OC_REPEAT_LIMIT", "3") or 3))
        self.fails: dict = {}
        self.last_call, self.same_calls = "", 0
        self.stuck = ""

    def see(self, name: str, status: str, shown: str, output: str) -> str:
        if status not in ("completed", "error"):
            return self.stuck                     # pending / running: the call is not finished yet
        call = "%s %s" % (name, " ".join(str(shown or "").split()))
        self.same_calls = self.same_calls + 1 if call == self.last_call else 1
        self.last_call = call
        sig = error_signature(name, status, output)
        if sig:
            self.fails[sig] = self.fails.get(sig, 0) + 1
            if self.fails[sig] >= self.limit and not self.stuck:
                self.stuck = "the same error %d times: %s (last command: %s)" % (self.fails[sig], sig, str(shown)[:200])
        if self.same_calls >= self.limit and not self.stuck and name not in ("todowrite", "team_read"):
            self.stuck = "the same call %d times in a row: %s" % (self.same_calls, call[:200])
        return self.stuck


# ------------------------------------------------------------------ sessions: one per LOKI conversation
class Sessions:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, conversation: str) -> str:
        return str(self._load().get(conversation or "default", "") or "")

    def set(self, conversation: str, session: str) -> None:
        with self.lock:
            d = self._load()
            d[conversation or "default"] = session
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(d, indent=1), encoding="utf-8")
            except OSError:
                pass

    def drop(self, conversation: str) -> None:
        with self.lock:
            d = self._load()
            d.pop(conversation or "default", None)
            try:
                self.path.write_text(json.dumps(d, indent=1), encoding="utf-8")
            except OSError:
                pass


# ------------------------------------------------------------------ one turn
def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) and ev.get("type") else None


def tool_summary(part: dict) -> tuple:
    """(tool name, status, short input text, short output or error)."""
    st = part.get("state") or {}
    name = str(part.get("tool") or part.get("name") or "tool")
    inp = st.get("input") or {}
    if isinstance(inp, dict):
        shown = inp.get("command") or inp.get("filePath") or inp.get("path") or inp.get("pattern") or inp.get("query") \
            or json.dumps(inp)[:200]
    else:
        shown = str(inp)
    out = st.get("error") or st.get("output") or ""
    return name, str(st.get("status") or ""), str(shown)[:300], str(out)[:600]


# A message longer than this is sent as an attached file (--file) instead of on the command line. Windows' limit is
# 32,767 characters for the whole line; the other arguments and the exe path need room too. LOKI_OC_ARGV_MAX overrides.
ARGV_MAX = int(os.getenv("LOKI_OC_ARGV_MAX", "") or (24000 if os.name == "nt" else 120000))
LONG_MESSAGE_POINTER = ("Your full instructions are in the attached file %s (they were too long for the command line). "
                        "Read ALL of it first, then do exactly what it says.")


def long_message_file(text: str, workspace: str, limit: int | None = None) -> str:
    """The path of a file holding `text` when it is too long for the command line, else "". The file goes in the
    workspace's .loki/messages/ (OpenCode may read inside its folder); old ones are pruned."""
    limit = ARGV_MAX if limit is None else limit
    if len(text or "") <= limit:
        return ""
    folder = Path(workspace or ".") / ".loki" / "messages"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for old in sorted(folder.glob("msg-*.md"))[:-20]:
            try:
                old.unlink()
            except OSError:
                pass
        path = folder / ("msg-%d-%d.md" % (int(time.time() * 1000), os.getpid()))
        path.write_text(text, encoding="utf-8")
        return str(path)
    except OSError:
        return ""


def run_turn(text: str, workspace: str, *, exe: str, config_path: str, env: dict, session: str = "", model: str = "",
             agent: str = "", timeout: int = DEFAULT_TIMEOUT, on_event: Callable[[dict], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False, popen=subprocess.Popen) -> dict:
    """Run one OpenCode turn. Returns {text, tools: [(name, status, input, output)], session, error, exit}."""
    argv = [exe, "run", "--format", "json", "--dir", workspace]
    if session:
        argv += ["--session", session]
    if model:
        argv += ["--model", model]
    if agent:
        argv += ["--agent", agent]
    from win_shim import argv_limit, is_batch  # pylint: disable=import-outside-toplevel
    # Still a .cmd (no .exe found behind it)? cmd.exe allows 8,191 chars and breaks arguments at newlines.
    msg_file = long_message_file(text, workspace, limit=0 if is_batch(exe) and "\n" in (text or "")
                                 else argv_limit(exe, ARGV_MAX))
    if msg_file:   # Windows caps a whole command line at 32,767 characters (the PC, 2026-10-27: 35+ jobs died on
        # "The command line is too long" - every provider in turn); a long message goes as an attached file
        argv += ["--file", msg_file, LONG_MESSAGE_POINTER % Path(msg_file).name]
    else:
        argv.append(text)
    env = dict(env)
    env["OPENCODE_CONFIG"] = config_path
    out = {"text": "", "tools": [], "session": session, "error": "", "exit": None}
    texts: list = []
    try:
        proc = popen(argv, cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                     creationflags=0x08000000 if os.name == "nt" else 0)
    except OSError as exc:
        out["error"] = "could not start OpenCode: %s" % exc
        return out
    err_lines: list = []
    t = threading.Thread(target=lambda: err_lines.extend(proc.stderr.readlines() if proc.stderr else []), daemon=True)
    t.start()
    started = time.monotonic()
    for raw in iter(proc.stdout.readline, ""):
        ev = parse_line(raw)
        if ev is None:
            continue
        if ev.get("sessionID"):
            out["session"] = str(ev["sessionID"])
        kind = ev.get("type")
        part = ev.get("part") or {}
        if kind == "text" and part.get("text"):
            texts.append(str(part["text"]))
        elif kind == "tool_use":
            out["tools"].append(tool_summary(part))
        elif kind == "error":
            e = ev.get("error") or {}
            out["error"] = str((e.get("data") or {}).get("message") or e.get("message") or e.get("name") or e)[:800]
        if on_event:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001 - the UI never breaks a turn
                pass
        if cancelled() or time.monotonic() - started > timeout:
            proc.kill()
            out["error"] = out["error"] or ("stopped" if cancelled() else "timed out after %ss" % timeout)
            break
    try:
        out["exit"] = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out["exit"] = -9
    t.join(timeout=2)
    out["text"] = "\n\n".join(x.strip() for x in texts if x.strip())
    if not out["error"] and out["exit"] not in (0, None) and not out["text"]:
        out["error"] = ("".join(err_lines).strip()[-800:] or "OpenCode exited with %s" % out["exit"])
    return out


def tool_counts(tools: list) -> tuple:
    ok = sum(1 for t in tools if t[1] == "completed" and not re.match(r"exit (-?[1-9]\d*)\b", t[3] or ""))
    return ok, len(tools) - ok


# ------------------------------------------------------------------ CodeGraph: index the workspace once
def ensure_index(workspace: str, codegraph: str, runner=subprocess.run) -> str:
    """`codegraph init --yes` the first time (it then auto-syncs); "" when done or not needed, else why not."""
    if not codegraph or not workspace:
        return "CodeGraph is not installed"
    if (Path(workspace) / ".codegraph").is_dir():
        return ""
    try:
        r = runner([codegraph, "init", "--yes", workspace], cwd=workspace, capture_output=True, text=True, timeout=600,
                   stdin=subprocess.DEVNULL)
        return "" if r.returncode == 0 else ("codegraph init failed: %s" % ((r.stderr or r.stdout or "")[-300:]))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "codegraph init failed: %s" % exc


def godot_ai_mcp(projects: list | None = None, uvx: str | None = None) -> dict:
    """OpenCode's entry for Godot AI: `godot-ai attach` (stdio) pinned to the add-on version in the owner's project
    (its docs/client-configuration.md shape). Nothing when no project has addons/godot_ai or uv is missing."""
    import re as _re  # pylint: disable=import-outside-toplevel
    from pathlib import Path as _P  # pylint: disable=import-outside-toplevel
    if projects is None:
        try:
            import agent_folders  # pylint: disable=import-outside-toplevel
            root = _P(agent_folders.projects_dir())
        except Exception:  # noqa: BLE001
            root = _P.home() / "LOKI Projects"
        env_p = os.environ.get("LOKI_GODOT_PROJECT")
        projects = ([_P(env_p)] if env_p else []) + ([p.parent.parent.parent for p in root.glob("*/addons/godot_ai/plugin.cfg")]
                                                     + [p.parent.parent.parent for p in root.glob("*/*/addons/godot_ai/plugin.cfg")]
                                                     if root.is_dir() else [])
    version = ""
    for proj in projects:
        cfg = _P(proj) / "addons" / "godot_ai" / "plugin.cfg"
        if cfg.is_file():
            m = _re.search(r'^version="([0-9][0-9A-Za-z.\-]*)"', cfg.read_text(encoding="utf-8", errors="replace"), _re.M)
            if m:
                version = m.group(1)
                break
    if not version:
        return {}
    uvx = uvx if uvx is not None else (shutil.which("uvx") or next((str(p) for p in (
        _P.home() / ".local" / "bin" / "uvx", _P.home() / ".cargo" / "bin" / "uvx") if p.exists()), ""))
    if not uvx:
        return {}
    return {"type": "local", "enabled": True, "command": [
        uvx, "--isolated", "--no-config", "--no-env-file", "--no-sources", "--no-build", "--index-strategy",
        "first-index", "--keyring-provider", "disabled", "--index", "https://pypi.org/simple", "--default-index",
        "https://pypi.org/simple", "--find-links", "https://pypi.org/simple/godot-ai/", "--link-mode", "copy",
        "--from", "godot-ai==" + version, "godot-ai", "attach", "--port", "8000", "--ws-port", "9500"]}


def showtime_mcp() -> dict:
    """OpenCode's entry for showtime's MCP server when the Tool Shelf installed it (engine/toolshelf.py)."""
    try:
        import toolshelf  # pylint: disable=import-outside-toplevel
        if not toolshelf.installed("showtime"):
            return {}
        exe = toolshelf.find_exe(toolshelf.tool_dir("showtime"), "showtime-mcp")
    except Exception:  # noqa: BLE001
        return {}
    return {"type": "local", "command": [exe], "enabled": True} if exe else {}


_NON_ANSWER = re.compile(
    r"internal guardrails|unable to answer question|i can(?:'|no)t (?:help|assist) with (?:that|this)|"
    r"(?:don't|do not|didn't|did not) see (?:a|any) (?:specific )?(?:team )?(?:goal|task|project)|"
    r"could you (?:please )?provide|please provide (?:the|more) (?:details|goal|task)|what (?:is the|specific) (?:team )?goal",
    re.I)


def non_answer(reply: str) -> bool:
    """A short reply that did no work: a provider's guardrail refusal, or asking for a goal it was given."""
    text = str(reply or "").strip()
    return bool(text) and len(text) < 1500 and bool(_NON_ANSWER.search(text))
