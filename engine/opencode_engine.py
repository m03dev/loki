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
INSTALL = {"opencode": "npm i -g opencode-ai@latest", "codegraph": "npm i -g @colbymchenry/codegraph"}
OC_EXE = ("opencode", "opencode.cmd", "opencode.exe")
CG_EXE = ("codegraph", "codegraph.cmd", "codegraph.exe")


# ------------------------------------------------------------------ finding the programs
def _find(names: Iterable[str], env_key: str, extra: Iterable[str] = ()) -> str:
    own = os.getenv(env_key, "").strip()
    if own and Path(own).is_file():
        return own
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    for p in extra:
        if p and Path(p).is_file():
            return p
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


def install(which: Iterable[str] = ("opencode", "codegraph"), runner=subprocess.run) -> dict:
    """npm i -g the missing ones (the button in Settings > Agent). {name: "ok" | "already" | error}."""
    have = {"opencode": find_opencode, "codegraph": find_codegraph}
    pkgs = {"opencode": "opencode-ai@latest", "codegraph": "@colbymchenry/codegraph"}
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


def engine_choice(env: dict | None = None) -> str:
    """LOKI_AGENT_ENGINE: opencode (default) | loki (the old built-in loop, only if you ask for it)."""
    value = str((env if env is not None else os.environ).get("LOKI_AGENT_ENGINE", "opencode")).strip().lower()
    return "loki" if value == "loki" else "opencode"


# ------------------------------------------------------------------ the config OpenCode runs with
def key_env(name: str) -> str:
    return "LOKI_OC_KEY_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


def provider_id(name: str) -> str:
    return "loki-" + re.sub(r"[^a-z0-9-]", "-", name.lower())


def deny_rules(snippets: Iterable[str]) -> dict:
    """LOKI's destructive command list as OpenCode bash rules: allow everything, then deny these (last match wins)."""
    rules = {"*": "allow"}
    for s in snippets:
        s = " ".join(str(s).split())
        if s:
            rules["*" + s + "*"] = "deny"
    return rules


def make_tools_command(python: str = "") -> list:
    """LOKI's making tools (engine/make_mcp.py: pictures, 3D models, video) as an MCP server for OpenCode."""
    return [python or sys.executable, str(Path(__file__).resolve().parent / "make_mcp.py")]


def build_config(providers: dict, codegraph: str = "", plan: bool = False, deny: Iterable[str] = (),
                 make_tools: bool = True) -> dict:
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
            "models": {str(p.get("model")): {"name": str(p.get("model"))}},
        }
    cfg: dict = {"$schema": "https://opencode.ai/config.json", "provider": prov,
                 "permission": {"edit": "deny" if plan else "allow", "read": "allow", "glob": "allow", "grep": "allow",
                                "list": "allow", "webfetch": "allow", "todowrite": "allow",
                                "bash": "deny" if plan else deny_rules(deny),
                                "external_directory": "deny"},
                 "autoupdate": False, "share": "disabled"}
    mcp: dict = {}
    if codegraph:
        mcp["codegraph"] = {"type": "local", "command": [codegraph, "serve", "--mcp"], "enabled": True}
    # owner 2026-10-25: "make real things like art 3d models or paintings comic books" - OpenCode writes and runs
    # code by itself; pictures, models and clips come from LOKI's own makers (not in Plan mode: they make files)
    if make_tools and not plan:
        mcp["loki-make"] = {"type": "local", "command": make_tools_command(), "enabled": True}
    if mcp:
        cfg["mcp"] = mcp
    return cfg


def env_for(providers: dict, base: dict | None = None) -> dict:
    env = dict(base if base is not None else os.environ)
    for name, p in providers.items():
        key = str(p.get("key") or "")
        env[key_env(name)] = key if key and key != "none" else "none"
    env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + [d for d in _global_bins() if Path(d).is_dir()])
    return env


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
