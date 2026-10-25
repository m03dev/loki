"""Background jobs - Loki keeps agents working while you do something else.

A *job* is one piece of work handed to a *backend* that runs it out of the chat loop:

    local  - a coding CLI (Claude Code / Codex) as a detached process, output to a log.
    herdr  - the same CLIs, each in its own herdr workspace (herdr.dev). herdr keeps the
             terminal alive, tracks working / blocked / idle / done, and lets you attach
             (`herdr`) to watch or answer a prompt. Survives Loki restarts.
    cua    - a virtual computer (trycua/cua): a Docker Linux desktop or a Lume macOS VM.
             Runs shell commands inside the VM, or a computer-use agent that drives the
             VM's screen. The VM is the sandbox; your own desktop is never touched.

The Supervisor owns a JSON job store, starts queued jobs up to a per-backend limit, polls
running ones, enforces a wall-clock timeout and records a short output tail. One tick is
a pure-ish function over the store, so the tests drive it with fake backends; the bridge
runs `Supervisor.start()` which ticks on a daemon thread.

Safety rules (see docs/operations/BACKGROUND_WORKERS.md):
  * Jobs are created by the user (the app / API), never self-spawned by the model.
  * Host backends (local, herdr) only run a known coding agent - never a raw shell string.
    Raw commands are allowed only on `cua`, inside the virtual computer.
  * By default a host job works in its own git worktree on a `loki/job-<id>` branch, so
    background edits never land in your working tree until you merge them.
  * Every job has a timeout; cancel always works.

Standard library only. herdr and cua are optional and detected at runtime.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

STATUSES = ("queued", "starting", "working", "blocked", "done", "failed", "cancelled")
FINAL = frozenset({"done", "failed", "cancelled"})
ACTIVE = frozenset({"starting", "working", "blocked"})
AGENTS = ("loki", "claude-code", "codex", "hermes", "opencode", "openhands", "nanocoder")
# The built-in agent: Loki's own loop, headless, on Loki's model (local by default). It
# needs nothing installed, so background work always has at least one agent.
BUILTIN_AGENTS = {"loki"}
LOKI_PY = Path(__file__).with_name("loki.py")


def loki_job_argv(job_file: str) -> list[str]:
    """How to start a headless Loki job: the engine's own Python, or the packaged app."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--agent-job", job_file]
    return [sys.executable, "-u", str(LOKI_PY), "--job", job_file]
HERDR_ONLY_AGENTS: set = set()   # interactive-only agents (none at present)
BACKENDS = ("local", "herdr", "cua")
DEFAULT_TIMEOUT_S = 3600
MAX_TIMEOUT_S = 24 * 3600
MAX_PROMPT_CHARS = 16_000
TAIL_CHARS = 4000
DEFAULT_LIMITS = {"local": 2, "herdr": 4, "cua": 1}


def _now() -> float:
    return time.time()


def _stamp(t: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else ""


def _clip(text: str, limit: int = TAIL_CHARS) -> str:
    text = str(text or "")
    return text if len(text) <= limit else "..." + text[-limit:]


# --------------------------------------------------------------------- agent command lines
# How each coding agent is started for an unattended job. Claude Code gets acceptEdits:
# it may edit files in the (isolated) workspace but still cannot run arbitrary shell
# commands without its own allowlist. LOKI_JOB_CLAUDE_MODE overrides it.
def agent_argv(agent: str, prompt: str, interactive: bool = False, env: dict | None = None) -> list[str]:
    env = env if env is not None else os.environ
    if agent == "loki":
        return [sys.executable, str(LOKI_PY)]  # the real argv is built in LocalBackend.start
    if agent == "claude-code":
        mode = env.get("LOKI_JOB_CLAUDE_MODE", "acceptEdits") or "acceptEdits"
        argv = ["claude", "--permission-mode", mode]
        return argv if interactive else argv + ["-p", prompt]
    if agent == "hermes":
        # Hermes Agent (Nous Research, MIT). `hermes -z PROMPT` is its scripted one-shot
        # (final answer on stdout, no banner); interactive `hermes` runs in a herdr pane.
        # Model/provider follow LOKI_HERMES_MODEL / LOKI_HERMES_PROVIDER when set (passed as
        # Hermes' own -m / --provider flags). Never --yolo: Hermes keeps its approvals.
        argv = ["hermes"]
        if env.get("LOKI_HERMES_MODEL"):
            argv += ["-m", env["LOKI_HERMES_MODEL"]]
        if env.get("LOKI_HERMES_PROVIDER"):
            argv += ["--provider", env["LOKI_HERMES_PROVIDER"]]
        return argv if interactive else argv + ["-z", prompt]
    if agent == "opencode":
        # OpenCode (anomalyco/opencode, MIT): `opencode run` is its one-shot mode. Model
        # follows LOKI_OPENCODE_MODEL (provider/model, e.g. opencode/deepseek-v4-flash-free).
        argv = ["opencode"]
        if interactive:
            return argv
        argv.append("run")
        if env.get("LOKI_OPENCODE_MODEL"):
            argv += ["-m", env["LOKI_OPENCODE_MODEL"]]
        return argv + [prompt]
    if agent == "openhands":
        # OpenHands CLI (OpenHands/OpenHands, MIT; the standalone CLI is no longer actively
        # maintained but works). Headless one-shot with JSON events; the model comes from the
        # LLM_* variables (openhands_env), so --override-with-envs makes them win over its config.
        if interactive:
            return ["openhands", "--override-with-envs"]
        return ["openhands", "--headless", "--json", "--override-with-envs", "-t", prompt]
    if agent == "nanocoder":
        # Nanocoder (Nano-Collective/nanocoder, MIT): `nanocoder run` is its one-shot mode. auto-accept
        # (its default for run) still stops on shell commands, git commits and deletes, so an unattended
        # job ends with "approval required" instead of doing them. --trust-directory skips its first-run
        # folder prompt (the job runs in its own worktree); --plain = no full-screen UI in a log file.
        # Provider/model follow LOKI_NANOCODER_PROVIDER / LOKI_NANOCODER_MODEL (its agents.config.json).
        argv = ["nanocoder"]
        if env.get("LOKI_NANOCODER_PROVIDER"):
            argv += ["--provider", env["LOKI_NANOCODER_PROVIDER"]]
        if env.get("LOKI_NANOCODER_MODEL"):
            argv += ["--model", env["LOKI_NANOCODER_MODEL"]]
        if interactive:
            return argv
        return argv + ["--mode", "auto-accept", "--trust-directory", "--plain", "run", prompt]
    if agent == "codex":
        if interactive:
            return ["codex", "--sandbox", "workspace-write"]
        return ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check",
                "--color", "never", prompt]
    raise ValueError("unknown agent: %s" % agent)


def current_local_model(env: dict | None = None) -> tuple[str, str]:
    """(model, base_url) of the local model LOKI is using now: LOKI_LOCAL_MODEL when pinned,
    else what the running engine resolved (loki.LOCAL_STATE), else the stock qwen3:8b."""
    env = env if env is not None else os.environ
    base = "http://localhost:11434/v1"
    pinned = str(env.get("LOKI_LOCAL_MODEL", "") or "").strip()
    if pinned:
        return pinned, base
    engine = sys.modules.get("loki")
    state = getattr(engine, "LOCAL_STATE", None) if engine is not None else None
    if isinstance(state, dict) and state.get("name"):
        return str(state["name"]), str(state.get("base_url") or base)
    return "qwen3:8b", base


def openhands_env(env: dict | None = None) -> dict:
    """OpenHands' LLM_* settings: LOKI's current local Ollama model unless the owner chose one
    (LOKI_OPENHANDS_MODEL / _BASE_URL / _API_KEY, or LLM_* already set)."""
    env = dict(env if env is not None else os.environ)
    model, base = current_local_model(env)
    out = {
        "LLM_MODEL": str(env.get("LOKI_OPENHANDS_MODEL") or env.get("LLM_MODEL") or ("openai/" + model)),
        "LLM_BASE_URL": str(env.get("LOKI_OPENHANDS_BASE_URL") or env.get("LLM_BASE_URL") or base),
        # A local server ignores the key, but OpenHands refuses to start without one.
        "LLM_API_KEY": str(env.get("LOKI_OPENHANDS_API_KEY") or env.get("LLM_API_KEY") or "ollama"),
    }
    env.update(out)
    return env


LOCAL_MODEL_NAMES = {"local", "local-small", "local-coder", "local-hermes", "local-reasoning", "local-tools",
                     "local-fast", "loki-tuned", "smart", "lmstudio", "llamacpp", "mlx", "vllm", "jan"}


def uses_local_model(job: dict, env: dict | None = None) -> bool:
    """Will this job run LOKI's own loop on this machine's local model?"""
    env = env if env is not None else os.environ
    if job.get("agent") != "loki" or job.get("backend") != "local" or job.get("selfcheck"):
        return False   # a System check job asks no model, so it never waits for the model slot
    model = str(job.get("model") or env.get("LOKI_MODEL", "smart")).strip().lower()
    if model == "smart":
        return str(env.get("LOKI_PREFER", "local")).strip().lower() == "local"
    return model in LOCAL_MODEL_NAMES


def local_model_limit(env: dict | None = None) -> int:
    env = env if env is not None else os.environ
    try:
        return max(1, int(env.get("LOKI_LOCAL_MODEL_JOBS", "1") or 1))
    except ValueError:
        return 1


def _shell_join(argv: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


# --------------------------------------------------------------------- job store
class JobStore:
    """Jobs persisted as one JSON file. Thread-safe; writes are atomic."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self._jobs: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            jobs = data.get("jobs", []) if isinstance(data, dict) else []
            self._jobs = [j for j in jobs if isinstance(j, dict) and j.get("id")]
        except (OSError, json.JSONDecodeError):
            self._jobs = []

    def save(self) -> None:
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"jobs": self._jobs}, indent=2), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass

    def add(self, job: dict) -> dict:
        with self.lock:
            self._jobs.append(job)
            self.save()
            return dict(job)

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            for job in self._jobs:
                if job["id"] == job_id:
                    return job
            return None

    def update(self, job_id: str, **fields: Any) -> dict | None:
        with self.lock:
            job = self.get(job_id)
            if job is None:
                return None
            job.update(fields)
            job["updated"] = _now()
            self.save()
            return dict(job)

    def all(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self._jobs]

    def remove(self, job_id: str) -> bool:
        """Forget one finished job (the System check cleans up after itself)."""
        with self.lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if not (j["id"] == job_id and j.get("status") in FINAL)]
            if len(self._jobs) != before:
                self.save()
                return True
            return False

    def remove_finished(self, keep: int = 50) -> int:
        """Drop old finished jobs beyond the newest `keep`."""
        with self.lock:
            finished = sorted((j for j in self._jobs if j.get("status") in FINAL),
                              key=lambda j: j.get("created", 0))
            excess = max(0, len(finished) - max(0, keep))
            drop = {j["id"] for j in finished[:excess]}
            self._jobs = [j for j in self._jobs if j["id"] not in drop]
            if drop:
                self.save()
            return len(drop)


# --------------------------------------------------------------------- workspace isolation
def _git(args: list[str], cwd: str, runner=subprocess.run) -> subprocess.CompletedProcess:
    return runner(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def prepare_workspace(job: dict, data_dir: Path, runner=subprocess.run) -> tuple[str, str]:
    """(workspace, note). With isolation on and a git repo, a fresh worktree on its own
    branch; otherwise the folder itself. Never touches the user's working tree."""
    workspace = str(Path(job["workspace"]).expanduser())
    if not job.get("isolate", True):
        return workspace, "working directly in " + workspace
    if not Path(workspace, ".git").exists():
        return workspace, "not a git repository - working directly in " + workspace
    top = _git(["rev-parse", "--show-toplevel"], workspace, runner)
    if top.returncode != 0:
        return workspace, "git unavailable - working directly in " + workspace
    branch = "loki/job-" + job["id"]
    target = Path(data_dir) / "worktrees" / job["id"]
    target.parent.mkdir(parents=True, exist_ok=True)
    made = _git(["worktree", "add", "-b", branch, str(target), "HEAD"], workspace, runner)
    if made.returncode != 0:
        raise RuntimeError("could not create a worktree: " + (made.stderr or made.stdout).strip()[:300])
    return str(target), "isolated worktree %s on branch %s" % (target, branch)


# --------------------------------------------------------------------- backends
class Backend:
    name = "base"

    def available(self) -> tuple[bool, str]:
        return False, "not implemented"

    def start(self, job: dict) -> dict:
        """Start the job; return fields to merge (status, handle, note...)."""
        raise NotImplementedError

    def poll(self, job: dict) -> dict:
        """Return fields to merge (status, exit_code, output...). {} = no change."""
        return {}

    def stop(self, job: dict) -> None:
        pass


class LocalBackend(Backend):
    """A coding CLI as a detached child process; stdout+stderr go to a log file."""

    name = "local"

    def __init__(self, data_dir: Path, which: Callable[[str], str | None] = shutil.which,
                 popen: Callable[..., Any] = subprocess.Popen) -> None:
        self.data_dir = Path(data_dir)
        self.which = which
        self.popen = popen
        self.procs: dict[str, Any] = {}

    def available(self) -> tuple[bool, str]:
        found = ["loki (built-in)"] + [a for a in AGENTS if a not in BUILTIN_AGENTS
                                        and a not in HERDR_ONLY_AGENTS and self.which(agent_argv(a, "")[0])]
        return True, "agents: " + ", ".join(found)

    def start(self, job: dict) -> dict:
        env = None
        if job["agent"] == "loki":
            job_file = self.data_dir / "jobs" / (job["id"] + ".job.json")
            job_file.parent.mkdir(parents=True, exist_ok=True)
            job_file.write_text(json.dumps({
                "id": job["id"], "prompt": job["prompt"], "profile": job.get("profile") or {},
                "allow_commands": bool(job.get("allow_commands")), "no_shell": bool(job.get("no_shell")), "model": job.get("model", ""),
                "selfcheck": bool(job.get("selfcheck")),
                # stop a minute before the supervisor's kill, saying BLOCKED and keeping partial work
                "deadline_s": max(60, int(job.get("timeout_s") or DEFAULT_TIMEOUT_S) - 60),
                "result_path": str(self.data_dir / "jobs" / (job["id"] + ".result.txt")),
            }), encoding="utf-8")
            argv = loki_job_argv(str(job_file))
            # The child works in the job's folder, shares Loki's data (keys, memory, models)
            # and never inherits the engine's own workspace.
            env = dict(os.environ, LOKI_WORKSPACE=job["run_dir"], LOKI_DATA=str(self.data_dir),
                       LOKI_MODE="build", PYTHONUNBUFFERED="1", LOKI_JOB_ID=job["id"],
                       LOKI_TEAM_ID=str(job.get("team") or ""),
                       LOKI_TEAM_ROLE=str((job.get("profile") or {}).get("name") or ""))
            env.pop("GAME_PROJECT", None)
            if "godot_editor" in str(job.get("prompt") or ""):
                env["LOKI_GODOT_LIVE"] = "1"   # a job for the live Godot editor (the Godot tab): its tool leads the list
            if (Path(job["run_dir"]) / "project.godot").is_file():
                env["GAME_PROJECT"] = job["run_dir"]
        else:
            argv = agent_argv(job["agent"], job["prompt"])
            if job["agent"] == "openhands":
                env = openhands_env(os.environ)
            exe = self.which(argv[0])
            if not exe:
                raise RuntimeError("%s is not installed" % argv[0])
            argv[0] = exe
        log_path = self.data_dir / "jobs" / (job["id"] + ".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "ab")
        kwargs: dict[str, Any] = {"cwd": job["run_dir"], "stdout": handle, "stderr": subprocess.STDOUT,
                                  "stdin": subprocess.DEVNULL}
        if env is not None:
            kwargs["env"] = env
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        proc = self.popen(argv, **kwargs)
        handle.close()
        self.procs[job["id"]] = proc
        return {"status": "working", "handle": {"pid": proc.pid, "log": str(log_path)}}

    def _tail(self, job: dict) -> str:
        try:
            data = Path(job.get("handle", {}).get("log", "")).read_bytes()
            return _clip(data[-TAIL_CHARS * 2:].decode("utf-8", "replace"))
        except OSError:
            return ""

    def poll(self, job: dict) -> dict:
        proc = self.procs.get(job["id"])
        if proc is None:
            # Loki restarted: we no longer own the process. Check if it is alive.
            pid = int(job.get("handle", {}).get("pid") or 0)
            if pid and _pid_alive(pid):
                return {"output": self._tail(job)}
            return {"status": "done", "output": self._tail(job),
                    "note": "finished while Loki was closed (exit code unknown)"}
        code = proc.poll()
        if code is None:
            return {"output": self._tail(job)}
        self.procs.pop(job["id"], None)
        return {"status": "done" if code == 0 else "failed", "exit_code": code, "output": self._tail(job)}

    def stop(self, job: dict) -> None:
        proc = self.procs.pop(job["id"], None)
        pid = proc.pid if proc is not None else int(job.get("handle", {}).get("pid") or 0)
        if not pid:
            return
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True,
                                 text=True, timeout=10).stdout
            return str(pid) in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# herdr agent status words (herdr.dev/docs/cli-reference): idle working blocked done unknown
HERDR_STATES = ("idle", "working", "blocked", "done", "unknown")


def find_key(obj: Any, keys: tuple[str, ...]) -> Any:
    """First value found under any of `keys`, searching nested dicts/lists depth-first."""
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and not isinstance(obj[key], (dict, list)):
                return obj[key]
        for value in obj.values():
            found = find_key(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_key(value, keys)
            if found is not None:
                return found
    return None


def herdr_agent_state(obj: Any) -> str:
    value = find_key(obj, ("agent_status", "status", "state"))
    value = str(value or "").lower()
    return value if value in HERDR_STATES else "unknown"


class HerdrBackend(Backend):
    """Each job gets its own herdr workspace running an interactive coding agent.

    Stages (kept in handle.stage):
      booting  - agent launched in the pane; wait until herdr sees it idle
      prompted - the task was sent; wait until it works and then goes idle/done
    herdr owns the terminal, so a job keeps running if Loki quits. `herdr` attaches.
    """

    name = "herdr"
    BOOT_TIMEOUT_S = 120

    def __init__(self, runner: Callable[..., Any] = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        self.runner = runner
        self.which = which

    def _herdr(self, *args: str, timeout: int = 30) -> Any:
        exe = self.which("herdr") or "herdr"
        proc = self.runner([exe, *args], capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError("herdr %s failed: %s" % (args[0] if args else "",
                                                       (proc.stderr or proc.stdout or "").strip()[:300]))
        text = (proc.stdout or "").strip()
        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError:
            return text

    def available(self) -> tuple[bool, str]:
        if not self.which("herdr"):
            return False, "herdr not installed (curl -fsSL https://herdr.dev/install.sh | sh)"
        try:
            self._herdr("status", "server", timeout=10)
            return True, "herdr server running"
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            return False, "herdr installed but its server is not running - open `herdr` once (%s)" % exc

    def start(self, job: dict) -> dict:
        created = self._herdr("workspace", "create", "--cwd", job["run_dir"],
                              "--label", "loki-" + job["id"], "--no-focus")
        pane = find_key(created, ("pane_id",))
        workspace_id = find_key(created, ("workspace_id",))
        if not pane:
            raise RuntimeError("herdr did not return a pane id: %s" % str(created)[:200])
        self._herdr("pane", "run", str(pane), _shell_join(agent_argv(job["agent"], "", interactive=True)))
        return {"status": "starting", "handle": {"pane": str(pane), "workspace": str(workspace_id or ""),
                                                 "stage": "booting", "since": _now()},
                "note": "attach with `herdr` to watch (workspace loki-%s)" % job["id"]}

    def _read(self, pane: str) -> str:
        try:
            text = self._herdr("pane", "read", pane, "--lines", "60")
            return _clip(text if isinstance(text, str) else json.dumps(text))
        except (RuntimeError, OSError, subprocess.SubprocessError):
            return ""

    def poll(self, job: dict) -> dict:
        handle = dict(job.get("handle") or {})
        pane = handle.get("pane", "")
        try:
            state = herdr_agent_state(self._herdr("agent", "get", pane))
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            if handle.get("stage") == "booting" and _now() - handle.get("since", _now()) < self.BOOT_TIMEOUT_S:
                return {}
            return {"status": "failed", "error": "herdr lost the agent: %s" % exc, "output": self._read(pane)}
        if handle.get("stage") == "booting":
            if state in ("idle", "done"):
                self._herdr("agent", "prompt", pane, job["prompt"])
                handle.update(stage="prompted", since=_now(), seen_working=False)
                return {"status": "working", "handle": handle}
            if _now() - handle.get("since", _now()) > self.BOOT_TIMEOUT_S:
                return {"status": "failed", "error": "the agent did not become ready in herdr",
                        "output": self._read(pane)}
            return {}
        out: dict[str, Any] = {"output": self._read(pane)}
        if state == "working":
            if not handle.get("seen_working"):
                handle["seen_working"] = True
                out["handle"] = handle
            out["status"] = "working"
        elif state == "blocked":
            out["status"] = "blocked"
            out["note"] = "the agent is waiting for you - attach with `herdr` to answer"
        elif state in ("idle", "done"):
            # Ignore the idle moment right after prompting, before it starts working.
            if handle.get("seen_working") or _now() - handle.get("since", _now()) > 30:
                out["status"] = "done"
        return out

    def stop(self, job: dict) -> None:
        handle = job.get("handle") or {}
        for args in (("pane", "send-keys", handle.get("pane", ""), "ctrl+c"),
                     ("workspace", "close", handle.get("workspace", ""))):
            if args[2]:
                try:
                    self._herdr(*args)
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    pass


class CuaBackend(Backend):
    """Jobs inside a virtual computer from trycua/cua (pip install cua-computer cua-agent).

    job["commands"]: shell commands run inside the VM, in order.
    job["prompt"] with no commands: a computer-use agent (cua-agent ComputerAgent, model
    from LOKI_CUA_MODEL) drives the VM's screen to do the task.
    Provider from LOKI_CUA_PROVIDER: docker (Linux desktop, default) or lume (macOS VM on
    Apple Silicon). Each job runs on its own thread with its own event loop.
    """

    name = "cua"

    def __init__(self, data_dir: Path, env: dict | None = None, importer=None) -> None:
        self.data_dir = Path(data_dir)
        self.env = env if env is not None else os.environ
        self.importer = importer or __import__
        self.threads: dict[str, dict] = {}

    def _computer_cls(self):
        return self.importer("computer", fromlist=["Computer"]).Computer

    def available(self) -> tuple[bool, str]:
        try:
            self._computer_cls()
        except Exception:
            return False, "pip install cua-computer cua-agent (into Loki's venv)"
        provider = self.provider()
        if provider == "docker" and not shutil.which("docker"):
            return False, "Docker is not installed (needed for the Linux virtual computer)"
        if provider == "lume" and not shutil.which("lume"):
            return False, "Lume is not installed (needed for the macOS virtual computer)"
        return True, "provider: " + provider

    def provider(self) -> str:
        value = (self.env.get("LOKI_CUA_PROVIDER") or "docker").lower()
        return value if value in ("docker", "lume", "windows_sandbox", "cloud") else "docker"

    def computer_kwargs(self) -> dict:
        provider = self.provider()
        if provider == "lume":
            return {"os_type": "macos", "provider_type": "lume",
                    "name": self.env.get("LOKI_CUA_IMAGE") or "macos-sequoia-cua:latest"}
        if provider == "windows_sandbox":
            return {"os_type": "windows", "provider_type": "windows_sandbox"}
        if provider == "cloud":
            return {"os_type": "linux", "provider_type": "cloud",
                    "name": self.env.get("LOKI_CUA_SANDBOX", ""), "api_key": self.env.get("CUA_API_KEY", "")}
        return {"os_type": "linux", "provider_type": "docker",
                "image": self.env.get("LOKI_CUA_IMAGE") or "trycua/cua-xfce:latest"}

    def start(self, job: dict) -> dict:
        box = {"status": "working", "output": "", "error": "", "cancel": threading.Event(),
               "shot": str(self.data_dir / "jobs" / (job["id"] + ".png"))}
        Path(box["shot"]).parent.mkdir(parents=True, exist_ok=True)
        thread = threading.Thread(target=lambda: asyncio.run(self._run(job, box)),
                                  name="loki-cua-" + job["id"], daemon=True)
        self.threads[job["id"]] = box
        thread.start()
        return {"status": "starting", "handle": {"provider": self.provider(), "screenshot": box["shot"]},
                "note": "starting a %s virtual computer" % self.provider()}

    async def _run(self, job: dict, box: dict) -> None:
        lines: list[str] = []
        computer = None
        try:
            computer = self._computer_cls()(**self.computer_kwargs())
            await computer.run()
            box["status"] = "working"
            if job.get("commands"):
                for command in job["commands"]:
                    if box["cancel"].is_set():
                        break
                    result = await computer.interface.run_command(command)
                    code = getattr(result, "returncode", None)
                    lines.append("$ %s\n%s%s" % (command, getattr(result, "stdout", "") or "",
                                                 getattr(result, "stderr", "") or ""))
                    box["output"] = _clip("\n".join(lines))
                    if code not in (None, 0):
                        raise RuntimeError("command exited %s: %s" % (code, command))
            else:
                agent_mod = self.importer("agent", fromlist=["ComputerAgent"])
                model = self.env.get("LOKI_CUA_MODEL", "")
                if not model:
                    raise RuntimeError("set LOKI_CUA_MODEL to a computer-use model for agent jobs")
                agent = agent_mod.ComputerAgent(model=model, tools=[computer])
                async for result in agent.run([{"role": "user", "content": job["prompt"]}]):
                    if box["cancel"].is_set():
                        break
                    for item in (result or {}).get("output", []) if isinstance(result, dict) else []:
                        if item.get("type") == "message":
                            for part in item.get("content") or []:
                                if part.get("text"):
                                    lines.append(part["text"])
                        elif item.get("type") == "computer_call":
                            lines.append("> " + json.dumps(item.get("action", {}))[:200])
                    box["output"] = _clip("\n".join(lines))
            try:
                shot = await computer.interface.screenshot()
                if isinstance(shot, (bytes, bytearray)):
                    Path(box["shot"]).write_bytes(shot)
            except Exception:
                pass
            box["status"] = "cancelled" if box["cancel"].is_set() else "done"
        except Exception as exc:  # noqa: BLE001 - every failure is reported on the job
            box["status"] = "failed"
            box["error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            if computer is not None:
                try:
                    await computer.disconnect()
                except Exception:
                    pass

    def poll(self, job: dict) -> dict:
        box = self.threads.get(job["id"])
        if box is None:
            return {"status": "failed", "error": "Loki restarted while the virtual computer job ran"}
        out = {"output": box["output"]}
        if box["status"] in FINAL:
            self.threads.pop(job["id"], None)
            out["status"] = box["status"]
            if box["error"]:
                out["error"] = box["error"]
        elif box["status"] == "working":
            out["status"] = "working"
        return out

    def stop(self, job: dict) -> None:
        box = self.threads.get(job["id"])
        if box is not None:
            box["cancel"].set()


# --------------------------------------------------------------------- supervisor
class Supervisor:
    def __init__(self, store: JobStore, backends: dict[str, Backend], data_dir: Path,
                 limits: dict[str, int] | None = None, tick_s: float = 3.0,
                 workspace_preparer: Callable[[dict, Path], tuple[str, str]] = prepare_workspace,
                 on_change: Callable[[dict], None] | None = None) -> None:
        self.store = store
        self.backends = backends
        self.data_dir = Path(data_dir)
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self.tick_s = tick_s
        self.prepare = workspace_preparer
        self.on_change = on_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        self._avail: dict[str, tuple[float, bool, str]] = {}

    def availability(self, name: str, max_age_s: float = 15.0) -> tuple[bool, str]:
        """backend.available(), cached briefly (the UI polls; herdr's check is a subprocess)."""
        cached = self._avail.get(name)
        if cached and _now() - cached[0] < max_age_s:
            return cached[1], cached[2]
        try:
            ok, detail = self.backends[name].available()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        self._avail[name] = (_now(), ok, detail)
        return ok, detail

    # ----------------------------------------------------------- API
    def create(self, spec: dict) -> dict:
        """Validate a job spec and queue it. Raises ValueError with a readable message."""
        backend = str(spec.get("backend") or "local").strip().lower()
        if backend not in self.backends:
            raise ValueError("unknown backend %r (use %s)" % (backend, ", ".join(self.backends)))
        prompt = str(spec.get("prompt") or "").strip()
        commands = spec.get("commands") or []
        if isinstance(commands, str):
            commands = [c for c in commands.splitlines() if c.strip()]
        commands = [str(c).strip() for c in commands if str(c).strip()]
        if commands and backend != "cua":
            raise ValueError("raw commands only run inside a virtual computer (backend cua)")
        if not prompt and not commands:
            raise ValueError("a job needs a prompt (or commands for a virtual computer)")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError("the prompt is longer than %d characters" % MAX_PROMPT_CHARS)
        agent = str(spec.get("agent") or ("claude-code" if backend == "herdr" else "loki")).strip().lower()
        if backend in ("local", "herdr") and agent not in AGENTS:
            raise ValueError("agent must be one of %s" % ", ".join(AGENTS))
        if backend == "herdr" and agent in BUILTIN_AGENTS:
            raise ValueError("the built-in Loki agent runs on This computer (backend local)")
        if backend == "local" and agent in HERDR_ONLY_AGENTS:
            raise ValueError("%s runs only on herdr" % agent)
        workspace = str(spec.get("workspace") or "").strip()
        if backend in ("local", "herdr"):
            if not workspace or not Path(workspace).expanduser().is_dir():
                raise ValueError("workspace must be an existing folder")
        try:
            timeout = int(spec.get("timeout_s") or DEFAULT_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_S
        timeout = max(30, min(timeout, MAX_TIMEOUT_S))
        title = str(spec.get("title") or prompt or commands[0]).strip().splitlines()[0][:80]
        job = {
            "id": uuid.uuid4().hex[:8], "title": title, "backend": backend,
            "agent": agent if backend != "cua" else "cua", "prompt": prompt, "commands": commands,
            "workspace": workspace, "isolate": bool(spec.get("isolate", True)),
            "timeout_s": timeout, "status": "queued", "created": _now(), "updated": _now(),
            "started": 0, "finished": 0, "handle": {}, "output": "", "error": "", "note": "",
            "exit_code": None, "run_dir": "",
            "profile": spec.get("profile") if isinstance(spec.get("profile"), dict) else {},
            "allow_commands": bool(spec.get("allow_commands")),
            "no_shell": bool(spec.get("no_shell")),   # the shell is on for OpenCode jobs unless this is set
            "model": str(spec.get("model") or ""),
            "fallback": str(spec.get("fallback") or "")[:80],
            "team": str(spec.get("team") or "")[:40],
            # The agent this job runs as (agent builder) and its colour in the agents list.
            "agent_id": str(spec.get("agent_id") or "")[:40],
            "color": str(spec.get("color") or "")[:7],
            # Lab > Make (engine/studio_agents.py): art / 3d / comic / novel / website ... for the Agents view
            "make_kind": str(spec.get("make_kind") or "")[:20],
            # LOKI's System check: the built-in agent proves the job path (spawn, log, poll,
            # events, world) and exits at once - no model, no tools (loki.run_job).
            "selfcheck": bool(spec.get("selfcheck")) and backend == "local" and agent == "loki",
        }
        stored = self.store.add(job)
        _emit_job_event(stored, "task.created")
        return stored

    def cancel(self, job_id: str) -> dict | None:
        job = self.store.get(job_id)
        if job is None or job.get("status") in FINAL:
            return dict(job) if job else None
        if job.get("status") in ACTIVE:
            try:
                self.backends[job["backend"]].stop(dict(job))
            except Exception:
                pass
        return self._set(job_id, status="cancelled", finished=_now())

    def status(self) -> dict:
        backends = {}
        for name in self.backends:
            ok, detail = self.availability(name)
            backends[name] = {"available": ok, "detail": detail, "limit": self.limits.get(name, 1)}
        jobs = [present(j) for j in sorted(self.store.all(), key=lambda j: j.get("created", 0), reverse=True)]
        counts = {s: 0 for s in STATUSES}
        for job in jobs:
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        return {"backends": backends, "jobs": jobs, "counts": counts, "running": self.running()}

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ----------------------------------------------------------- loop
    def _set(self, job_id: str, **fields: Any) -> dict | None:
        before = (self.store.get(job_id) or {}).get("status")
        job = self.store.update(job_id, **fields)
        if job is not None and fields.get("status") and fields["status"] != before:
            _emit_job_event(job)
        if job is not None and self.on_change is not None:
            try:
                self.on_change(job)
            except Exception:
                pass
        return job

    def tick(self) -> None:
        with self._tick_lock:
            jobs = self.store.all()
            now = _now()
            for job in jobs:
                if job["status"] not in ACTIVE:
                    continue
                backend = self.backends.get(job["backend"])
                if backend is None:
                    self._set(job["id"], status="failed", error="backend gone", finished=now)
                    continue
                if job.get("started") and now - job["started"] > job.get("timeout_s", DEFAULT_TIMEOUT_S):
                    try:
                        backend.stop(job)
                    except Exception:
                        pass
                    self._set(job["id"], status="failed", finished=now,
                              error="timed out after %ds" % job.get("timeout_s", 0))
                    continue
                try:
                    fields = backend.poll(job) or {}
                except Exception as exc:  # noqa: BLE001
                    fields = {"status": "failed", "error": "%s: %s" % (type(exc).__name__, exc)}
                if fields.get("status") not in (None, *STATUSES):
                    fields.pop("status")
                if fields.get("status") in FINAL:
                    fields["finished"] = now
                changed = {k: v for k, v in fields.items() if job.get(k) != v}
                if changed:
                    self._set(job["id"], **changed)
            jobs = self.store.all()
            active = {name: 0 for name in self.backends}
            local_model_jobs = 0
            for job in jobs:
                if job["status"] in ACTIVE and job["backend"] in active:
                    active[job["backend"]] += 1
                    local_model_jobs += uses_local_model(job)
            local_limit = local_model_limit()
            for job in sorted(jobs, key=lambda j: j.get("created", 0)):
                if job["status"] != "queued":
                    continue
                name = job["backend"]
                if active.get(name, 0) >= self.limits.get(name, 1):
                    continue
                if uses_local_model(job) and local_model_jobs >= local_limit:
                    # One GPU, one local model: two agents on it at once crawl (0.2 tok/s seen on
                    # the 8 GB PC) and stall. Wait for the slot; cloud-model jobs still run.
                    continue
                self._launch(job)
                active[name] = active.get(name, 0) + 1
                local_model_jobs += uses_local_model(job)

    def _launch(self, job: dict) -> None:
        backend = self.backends[job["backend"]]
        ok, detail = self.availability(job["backend"], max_age_s=0)
        if not ok:
            self._set(job["id"], status="failed", finished=_now(), error="%s unavailable: %s" % (job["backend"], detail))
            return
        try:
            note = ""
            if job["backend"] in ("local", "herdr"):
                run_dir, note = self.prepare(job, self.data_dir)
                job["run_dir"] = run_dir
            fields = backend.start(dict(job)) or {}
            merged_note = "; ".join(n for n in (note, fields.pop("note", "")) if n)
            self._set(job["id"], run_dir=job.get("run_dir", ""), started=_now(),
                      note=merged_note, **{"status": "starting", **fields})
        except Exception as exc:  # noqa: BLE001
            self._set(job["id"], status="failed", finished=_now(), error="%s: %s" % (type(exc).__name__, exc))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                print("[loki-jobs] tick failed: %s" % exc, file=sys.stderr, flush=True)
            self._stop.wait(self.tick_s)

    def start(self) -> None:
        if self.running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="loki-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


_STATUS_EVENTS = {"starting": "task.started", "working": "task.started", "blocked": "task.blocked",
                  "done": "task.completed", "failed": "task.failed", "cancelled": "task.failed"}


def _emit_job_event(job: dict, type_: str = "") -> None:
    """Tell the event stream (engine/events.py) what a background agent is doing."""
    try:
        import events  # pylint: disable=import-outside-toplevel
        type_ = type_ or _STATUS_EVENTS.get(job.get("status", ""), "")
        if not type_:
            return
        role = (job.get("profile") or {}).get("name") or ("Loki agent" if job.get("agent") == "loki" else job.get("agent", "agent"))
        payload = {"title": job.get("title", ""), "status": job.get("status", ""), "backend": job.get("backend", "")}
        if type_ in ("task.completed", "task.failed"):
            payload["result"] = (job.get("output") or job.get("error") or "")[-600:]
        events.emit(type_, role, payload, task=job.get("id", ""), team=job.get("team", ""))
    except Exception:  # noqa: BLE001 - events never break a job
        pass


def present(job: dict) -> dict:
    """The job as the UI sees it: no internal handle details beyond what helps."""
    handle = job.get("handle") or {}
    return {
        "id": job["id"], "title": job.get("title", ""), "backend": job.get("backend", ""),
        "agent": job.get("agent", ""), "status": job.get("status", ""),
        "created": _stamp(job.get("created")), "started": _stamp(job.get("started")),
        "finished": _stamp(job.get("finished")), "note": job.get("note", ""),
        "error": job.get("error", ""), "output": job.get("output", ""),
        "exit_code": job.get("exit_code"), "run_dir": job.get("run_dir", ""),
        "pane": handle.get("pane", ""), "screenshot": bool(handle.get("screenshot"))
        and Path(handle.get("screenshot", "")).is_file(),
        "agent_id": job.get("agent_id", ""), "color": job.get("color", ""),
        "machine": job.get("machine", ""),
    }


def default_supervisor(data_dir: Path, env: dict | None = None) -> Supervisor:
    env = env if env is not None else os.environ
    data_dir = Path(data_dir)
    limits = {}
    for name in BACKENDS:
        try:
            value = int(env.get("LOKI_JOBS_%s_LIMIT" % name.upper(), "") or 0)
            if value > 0:
                limits[name] = value
        except ValueError:
            pass
    backends: dict[str, Backend] = {
        "local": LocalBackend(data_dir),
        "herdr": HerdrBackend(),
        "cua": CuaBackend(data_dir, env),
    }
    return Supervisor(JobStore(data_dir / "jobs.json"), backends, data_dir, limits)
