"""The LOKI MCP API: LOKI's engine and its own code, as an MCP server an agent can drive.

LOKI Studio's development agent uses it (that is how it inspects and controls the running LOKI
while it works on LOKI's code), and so can Claude Code, Codex or Ziva (docs/LOKI_MCP.md has the
config snippet). Two halves:

  the running LOKI   status / version / update state, models doctor, General settings (never a
                     secret), background jobs (list, start, stop, logs), world + presence, memory
                     search, tools health, creations, restart the engine. Through the engine's own
                     loopback API with its bridge token (harness_data/app/engine.token); when LOKI
                     is not running these say so - and the log files on disk can still be read.
  LOKI's code        read / search / list / edit / write files, git status / diff / log, the test
                     suites (tools/ship.py --check, hermetic like check_loki) and ship (tools/ship.py,
                     health-gated on every machine) - ONLY inside the dev worktree, never the
                     owner's checkout, never harness_data/, .env files, tokens or .git.

Everything risky (settings_set, job_start, job_stop, restart_engine, ship) goes through
engine/policy.py and ASKS: the call is refused unless it carries the approval code of the
program that asked the owner (LOKI Studio holds LOKI_MCP_APPROVAL_SECRET and computes the code
only after the owner clicks Approve), or the server was started with --allow-risky (then the
client's own permission prompt - e.g. Claude Code's - is the gate). Ship is never automatic.

    python engine/loki_mcp.py --worktree <dev worktree>                 stdio (the default)
    python engine/loki_mcp.py --http --port 8770 --worktree <...>       streamable HTTP on 127.0.0.1,
                                                                        Bearer <the bridge token>
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ENGINE = Path(__file__).resolve().parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

import policy  # noqa: E402

REPO = ENGINE.parent
VERSION = "1"
RISKY_TOOLS = ("settings_set", "job_start", "job_stop", "restart_engine", "ship")
# Never readable or writable through this API, wherever they are.
DENY_PARTS = {".git", "harness_data", "node_modules", "__pycache__"}
DENY_NAMES = re.compile(r"(^|/)(\.env(\..*)?|.*\.token|.*\.pem|.*\.key|id_rsa.*|loki_session\.json)$", re.I)
MAX_READ = 60_000
LOGS = {"engine": "app/engine.out", "app": "app/loki_app.log", "bridge": "app/loki_bridge.log",
        "studio": "studio/studio.log"}


def data_dir() -> Path:
    return Path(os.getenv("LOKI_DATA") or (REPO / "harness_data"))


def approval_code(secret: str, tool: str, args: dict) -> str:
    """The code that proves the owner approved exactly this call (args without 'confirm')."""
    body = json.dumps({"tool": tool, "args": {k: v for k, v in sorted((args or {}).items()) if k != "confirm"}},
                      sort_keys=True, default=str)
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _redact(text: str) -> str:
    return re.sub(r"(nvapi-|sk-|gsk_|AIza|Bearer\s+|token=)[A-Za-z0-9._~+/=-]{6,}", r"\1[redacted]", str(text))


class LokiAPI:
    """The tools, as plain methods (LOKI Studio and the tests call them directly too)."""

    def __init__(self, worktree: str | Path | None = None, repo: str | Path | None = None,
                 data: str | Path | None = None, bridge_url: str = "", token_file: str | Path | None = None,
                 allow_risky: bool = False, approval_secret: str = "", python: str = "",
                 approver: Callable[[str, dict], bool] | None = None) -> None:
        self.repo = Path(repo or REPO).resolve()
        self.data = Path(data or data_dir()).resolve()
        self._worktree = Path(worktree).resolve() if worktree else None
        port = os.getenv("LOKI_APP_PORT", "8767") or "8767"
        self.bridge_url = (bridge_url or os.getenv("LOKI_BRIDGE_URL", "") or "http://127.0.0.1:%s" % port).rstrip("/")
        self.token_file = Path(token_file or os.getenv("LOKI_BRIDGE_TOKEN_FILE", "") or (self.data / "app" / "engine.token"))
        self.allow_risky = bool(allow_risky)
        self.secret = approval_secret or os.getenv("LOKI_MCP_APPROVAL_SECRET", "")
        self.python = python or sys.executable
        self.approver = approver
        self.policy = policy.PolicyEngine(path_check=self._inside, command_check=lambda c: (False, "no commands here"),
                                          parse_command=lambda c: None, dangerous=set(RISKY_TOOLS))

    # ------------------------------------------------------------- the dev worktree
    @property
    def worktree(self) -> Path:
        if self._worktree is None:
            self._worktree = ensure_worktree(self.repo, self.data / "studio" / "worktrees" / "dev", "studio/dev")
        return self._worktree

    def _inside(self, rel: str) -> Path:
        """`rel` as a path inside the dev worktree; raises when it escapes or is a secret."""
        raw = str(rel or ".").replace("\\", "/").strip()
        root = self.worktree
        target = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        try:
            inner = target.relative_to(root)
        except ValueError:
            raise PermissionError("%s is outside the dev worktree %s" % (rel, root)) from None
        parts = set(inner.parts)
        if parts & DENY_PARTS or DENY_NAMES.search(inner.as_posix()):
            raise PermissionError("%s is off limits (secrets, data, .git)" % rel)
        if target.resolve() == self.repo and root != self.repo:
            raise PermissionError("that is the owner's checkout, not the dev worktree")
        return target

    # ------------------------------------------------------------- approvals (policy.py)
    def gate(self, tool: str, args: dict) -> str:
        """"" when the call may run, else the refusal."""
        verdict = self.policy.tool_call(tool, args)
        if verdict.decision == policy.DENY:
            return "refused: " + verdict.reason
        if verdict.decision == policy.ALLOW:
            return ""
        if self.allow_risky:
            return ""
        if self.approver is not None:
            try:
                return "" if self.approver(tool, args) else "refused: the owner said no"
            except Exception as exc:  # noqa: BLE001
                return "refused: could not ask the owner (%s)" % exc
        given = str((args or {}).get("confirm") or "")
        if self.secret and given and hmac.compare_digest(given, approval_code(self.secret, tool, args)):
            return ""
        return ("needs the owner's approval: %s (%s). Ask the owner; the program that asks them (LOKI Studio) "
                "adds the approval code. Nothing was done." % (tool, verdict.reason))

    # ------------------------------------------------------------- the running LOKI
    def _token(self) -> str:
        try:
            return self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def bridge(self, method: str, path: str, body: dict | None = None, timeout: float = 8.0) -> tuple:
        """(status, payload); status 0 = LOKI is not running."""
        token = self._token()
        if not token:
            return 0, {"ok": False, "error": "LOKI is not running (no engine token at %s)" % self.token_file}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.bridge_url + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                return exc.code, {"ok": False, "error": "HTTP %s" % exc.code}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return 0, {"ok": False, "error": "LOKI is not running (%s)" % getattr(exc, "reason", exc)}

    def up(self) -> bool:
        return self.bridge("GET", "/health", timeout=2.0)[0] == 200

    def _out(self, status: int, payload: Any, keep: tuple = ()) -> str:
        if status == 0:
            return "LOKI is not running right now. %s Its logs on disk: engine_logs. LOKI Studio can start it." % (
                payload.get("error", "") if isinstance(payload, dict) else "")
        if isinstance(payload, dict) and keep:
            payload = {k: payload[k] for k in keep if k in payload}
        return _redact(json.dumps(payload, indent=1, default=str)[:MAX_READ])

    def loki_status(self) -> str:
        """Is LOKI running, which model answers, its version, and the update state (works when down too)."""
        status, health = self.bridge("GET", "/health", timeout=3.0)
        out: dict = {"running": status == 200}
        if status == 200:
            out.update({k: health.get(k) for k in ("mode", "provider", "model", "providers", "update", "ui_errors")})
        else:
            out["why_not"] = health.get("error", "")
        try:
            import updater  # pylint: disable=import-outside-toplevel
            out["version"] = updater.version(self.repo)
            rec = updater.health(self.repo)
            out["update_health"] = {k: rec.get(k) for k in ("last_good", "pending", "skip", "skip_reasons", "rolled_back_from")}
            out["update_history"] = (rec.get("history") or [])[-5:]
        except Exception as exc:  # noqa: BLE001
            out["version"] = {"error": str(exc)}
        return _redact(json.dumps(out, indent=1, default=str))

    def models_doctor(self) -> str:
        """Which model handles chat, code, pictures, long documents, background jobs and hard tasks, and why."""
        status, data = self.bridge("GET", "/models/doctor", timeout=20.0)
        if status == 200 and isinstance(data, dict) and data.get("text"):
            return _redact(data["text"])
        return self._out(status, data)

    def settings_get(self) -> str:
        """LOKI's General settings and their values. Secrets are never sent: only whether one is saved."""
        status, data = self.bridge("GET", "/settings/general")
        if status == 200:
            spec = data.get("settings") or {}
            values = {k: v for k, v in (data.get("values") or {}).items() if (spec.get(k) or {}).get("kind") != "secret"}
            return json.dumps({"values": values, "choices": {k: {kk: vv for kk, vv in s.items() if kk != "default"}
                                                             for k, s in spec.items() if s.get("kind") != "secret"}},
                              indent=1)
        return self._out(status, data)

    def settings_set(self, key: str, value: str, confirm: str = "") -> str:
        """Change one General setting (never a secret or a key). Asks the owner first."""
        refusal = self.gate("settings_set", {"key": key, "value": value, "confirm": confirm})
        if refusal:
            return refusal
        status, data = self.bridge("GET", "/settings/general")
        if status != 200:
            return self._out(status, data)
        spec = (data.get("settings") or {}).get(key)
        if spec is None or spec.get("kind") == "secret" or re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.I):
            return "refused: %s is not a General setting that may be changed here" % key
        return self._out(*self.bridge("POST", "/settings/general", {"values": {key: str(value)}}))

    def jobs_list(self) -> str:
        """LOKI's background jobs: id, title, status, model, error."""
        status, data = self.bridge("GET", "/jobs")
        if status != 200:
            return self._out(status, data)
        jobs = [{k: j.get(k) for k in ("id", "title", "status", "model", "error", "created", "note")}
                for j in (data.get("jobs") or [])][-40:]
        return json.dumps({"jobs": jobs, "backends": data.get("backends")}, indent=1, default=str)

    def job_start(self, prompt: str, title: str = "", model: str = "", confirm: str = "") -> str:
        """Start a background job on the running LOKI (its policy decides as for any job). Asks the owner first."""
        args = {"prompt": prompt, "title": title, "model": model, "confirm": confirm}
        refusal = self.gate("job_start", args)
        if refusal:
            return refusal
        spec = {"backend": "local", "agent": "loki", "prompt": prompt, "title": title or prompt[:60]}
        if model:
            spec["model"] = model
        return self._out(*self.bridge("POST", "/jobs", spec), keep=("ok", "id", "error"))

    def job_stop(self, id: str, confirm: str = "") -> str:  # noqa: A002
        """Stop (cancel) a background job. Asks the owner first."""
        refusal = self.gate("job_stop", {"id": id, "confirm": confirm})
        if refusal:
            return refusal
        return self._out(*self.bridge("POST", "/jobs/cancel", {"id": id}), keep=("ok", "error"))

    def job_logs(self, id: str, lines: int = 80) -> str:  # noqa: A002
        """The last lines of one background job's log (read from disk: works when LOKI is down)."""
        safe = re.sub(r"[^A-Za-z0-9_-]", "", str(id or ""))
        path = self.data / "jobs" / (safe + ".log")
        if not safe or not path.is_file():
            return "no log for job %r" % id
        return _redact(_tail(path, lines))

    def engine_logs(self, which: str = "engine", lines: int = 80) -> str:
        """The last lines of LOKI's own logs on disk: engine | app | bridge | studio (works when LOKI is down)."""
        rel = LOGS.get(str(which or "engine").lower())
        if rel is None:
            return "which= one of: " + ", ".join(LOGS)
        path = self.data / rel
        return _redact(_tail(path, lines)) if path.is_file() else "(no %s log at %s yet)" % (which, path)

    def world_summary(self) -> str:
        """LOKI World: the other machines' avatars and the world chat (presence)."""
        return self._out(*self.bridge("GET", "/world/presence"))

    def memory_search(self, query: str) -> str:
        """What LOKI would recall for `query` from its memory (the same retrieval a request uses)."""
        from urllib.parse import quote  # pylint: disable=import-outside-toplevel
        status, data = self.bridge("GET", "/memory/core?q=" + quote(str(query or "")[:300]))
        if status == 200:
            items = [{k: i.get(k) for k in ("kind", "text", "score")} for i in (data.get("items") or [])][:12]
            return _redact(json.dumps(items, indent=1))
        return self._out(status, data)

    def tools_health(self) -> str:
        """Every tool's health: which work, which are hidden as dead, and the one-click fixes."""
        return self._out(*self.bridge("GET", "/tools/health"))

    def creations_list(self) -> str:
        """What LOKI made (pictures, videos, sketches, games): the newest ones."""
        status, data = self.bridge("GET", "/creations")
        if status == 200:
            items = [{k: c.get(k) for k in ("title", "kind", "path", "created")} for c in (data.get("creations") or [])][:30]
            return json.dumps(items, indent=1, default=str)
        return self._out(status, data)

    def restart_engine(self, confirm: str = "") -> str:
        """Restart the running LOKI engine (the app starts it again and reloads the window). Asks the owner first."""
        refusal = self.gate("restart_engine", {"confirm": confirm})
        if refusal:
            return refusal
        return self._out(*self.bridge("POST", "/engine/restart", {}), keep=("ok", "note", "error"))

    # ------------------------------------------------------------- LOKI's code (the dev worktree)
    def read_file(self, path: str, start_line: int = 0, end_line: int = 0) -> str:
        """Read a file of the dev worktree (start_line/end_line, 1-based, for a part of a big file)."""
        try:
            target = self._inside(path)
            text = target.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError) as exc:
            return "error: %s" % exc
        if start_line or end_line:
            lines = text.splitlines()
            a = max(1, int(start_line or 1))
            b = min(len(lines), int(end_line or len(lines)))
            text = "\n".join("%d: %s" % (i, lines[i - 1]) for i in range(a, b + 1))
        if len(text) > MAX_READ:
            text = text[:MAX_READ] + "\n... (%d more characters: read a range with start_line/end_line)" % (len(text) - MAX_READ)
        return text

    def list_files(self, path: str = ".", pattern: str = "") -> str:
        """List a folder of the dev worktree (pattern: an fnmatch glob like *.py)."""
        try:
            target = self._inside(path)
        except PermissionError as exc:
            return "error: %s" % exc
        if not target.is_dir():
            return "error: %s is not a folder" % path
        rows = []
        for child in sorted(target.iterdir()):
            if child.name in DENY_PARTS or DENY_NAMES.search(child.name):
                continue
            if pattern and not fnmatch.fnmatch(child.name, pattern):
                continue
            rows.append(child.name + ("/" if child.is_dir() else ""))
        return "\n".join(rows[:500]) or "(empty)"

    def search_files(self, pattern: str, glob: str = "", path: str = ".") -> str:
        """Search the dev worktree for a regular expression (glob like *.py narrows it): path:line: text."""
        try:
            rx = re.compile(pattern)
            root = self._inside(path)
        except (re.error, PermissionError) as exc:
            return "error: %s" % exc
        hits = []
        for file in sorted(root.rglob("*")):
            rel = file.relative_to(self.worktree)
            if not file.is_file() or set(rel.parts) & DENY_PARTS or DENY_NAMES.search(rel.as_posix()):
                continue
            if glob and not fnmatch.fnmatch(file.name, glob):
                continue
            if file.stat().st_size > 2_000_000:
                continue
            try:
                for n, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        hits.append("%s:%d: %s" % (rel.as_posix(), n, line.strip()[:200]))
                        if len(hits) >= 200:
                            return "\n".join(hits) + "\n... (more: narrow the search)"
            except OSError:
                continue
        return "\n".join(hits) or "no match"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        """Replace old_text (must appear exactly once - copy a few surrounding lines) with new_text."""
        try:
            target = self._inside(path)
            text = target.read_text(encoding="utf-8")
        except (PermissionError, OSError) as exc:
            return "error: %s" % exc
        count = text.count(old_text) if old_text else 0
        if count != 1:
            return "error: old_text appears %d times in %s; it must appear exactly once" % (count, path)
        target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return "edited %s (%+d lines)" % (path, new_text.count("\n") - old_text.count("\n"))

    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a file in the dev worktree."""
        try:
            target = self._inside(path)
        except PermissionError as exc:
            return "error: %s" % exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return "wrote %s (%d lines)" % (path, content.count("\n") + 1)

    def _git(self, *args: str, timeout: float = 60.0) -> str:
        try:
            proc = subprocess.run(["git", *args], cwd=str(self.worktree), capture_output=True, text=True,
                                  timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "error: %s" % exc
        return ((proc.stdout or "") + (proc.stderr or "")).strip()

    def git_status(self) -> str:
        """git status of the dev worktree (branch + changed files)."""
        return self._git("status", "--short", "--branch") or "(clean)"

    def git_diff(self, path: str = "") -> str:
        """The dev worktree's changes against its last commit (new files included)."""
        return diff_text(self.worktree, path)[:MAX_READ] or "(no changes)"

    def git_log(self, count: int = 10) -> str:
        """The dev worktree's recent commits."""
        return self._git("log", "--oneline", "-n", str(max(1, min(50, int(count or 10)))))

    def read_doc(self, name: str = "HANDOFF.md", section: str = "", lines: int = 200) -> str:
        """Read HANDOFF.md, ZIVA_TASKS.md, AGENTS.md or docs/BUILD_BRIEF.md (section= a heading to jump to)."""
        allowed = {"handoff": "HANDOFF.md", "ziva": "ZIVA_TASKS.md", "ziva_tasks": "ZIVA_TASKS.md",
                   "agents": "AGENTS.md", "brief": "docs/BUILD_BRIEF.md", "build_brief": "docs/BUILD_BRIEF.md"}
        key = str(name or "handoff").lower().replace(".md", "").replace("docs/", "")
        rel = allowed.get(key) or next((v for v in allowed.values() if v.lower() == str(name).lower()), "")
        if not rel:
            return "name= one of: HANDOFF.md, ZIVA_TASKS.md, AGENTS.md, docs/BUILD_BRIEF.md"
        try:
            text = (self.worktree / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return "error: %s" % exc
        start = 0
        if section:
            start = next((i for i, l in enumerate(text) if l.startswith("#") and section.lower() in l.lower()), 0)
        return "\n".join(text[start:start + max(20, min(800, int(lines or 200)))])

    def run_tests(self, suite: str = "") -> str:
        """Run LOKI's test suites in the dev worktree (tools/ship.py --check, hermetic like CI). suite= one
        name like test_portal for a quick check; empty runs them all (minutes)."""
        return run_check(self.worktree, suite, self.python)

    def ship(self, message: str, confirm: str = "") -> str:
        """Publish the dev worktree's change: tools/ship.py runs every suite, commits, rebases onto GitHub and
        pushes master; every machine takes it only through the health-gated updater. ALWAYS asks the owner."""
        refusal = self.gate("ship", {"message": message, "confirm": confirm})
        if refusal:
            return refusal
        return run_ship(self.worktree, message, self.python, self.data)


# ----------------------------------------------------------------- shared helpers (Studio uses them)
def _tail(path: Path, lines: int) -> str:
    try:
        data = path.read_bytes()[-400_000:].decode("utf-8", errors="replace").splitlines()
    except OSError as exc:
        return "error: %s" % exc
    return "\n".join(data[-max(1, min(2000, int(lines or 80))):])


def check_env(base: dict | None = None) -> dict:
    """Like loki.check_env: suites run like CI - no LOKI_* settings, no keys, no job variables."""
    env = dict(base if base is not None else os.environ)
    for name in list(env):
        if name.startswith(("LOKI_", "HARNESS_")) or re.search(r"(_API_KEY|_TOKEN|^HF_TOKEN)$", name) \
                or name == "GAME_PROJECT":
            env.pop(name, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_check(tree: Path, suite: str = "", python: str = "", timeout: float = 3600) -> str:
    tree = Path(tree)
    ship = tree / "tools" / "ship.py"
    if not ship.is_file():
        return "error: %s has no tools/ship.py" % tree
    argv = [python or sys.executable, str(ship), "--check", "--repo", str(tree)]
    suite = re.sub(r"[^a-z0-9_,]", "", str(suite or "").lower())
    if suite:
        argv += ["--only", suite]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(tree), env=check_env())
    except subprocess.TimeoutExpired:
        return "SOME FAILED\nthe tests took over %d s and were stopped" % timeout
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return ("ALL PASSED\n" if proc.returncode == 0 else "SOME FAILED\n") + out[-4000:]


def run_ship(tree: Path, message: str, python: str = "", data: Path | None = None, timeout: float = 3600) -> str:
    message = " ".join(str(message or "").split())
    if not message:
        return "NOT shipped: give a one-line message saying what changed and how it was checked"
    tree = Path(tree)
    env = check_env()
    if data is not None:
        env["LOKI_DATA"] = str(data)   # ship.py tells the linked machines with LOKI's own peer settings
    try:
        proc = subprocess.run([python or sys.executable, str(tree / "tools" / "ship.py"), "-m", message, "--repo", str(tree)],
                              capture_output=True, text=True, timeout=timeout, cwd=str(tree), env=env)
    except subprocess.TimeoutExpired:
        return "NOT shipped: shipping took over %d s and was stopped" % timeout
    except OSError as exc:
        return "NOT shipped: %s" % exc
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return ("shipped:\n" if proc.returncode == 0 else "NOT shipped:\n") + out[-4000:]


def diff_text(tree: Path, path: str = "") -> str:
    """git diff HEAD of `tree`, with new (untracked) files shown as added."""
    def git(*args):
        try:
            p = subprocess.run(["git", *args], cwd=str(tree), capture_output=True, text=True, timeout=60)
            return p.stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
    extra = ["--", path] if path else []
    out = git("diff", "HEAD", *extra)
    for rel in git("ls-files", "--others", "--exclude-standard", *extra).splitlines():
        if not rel.strip():
            continue
        try:
            body = (Path(tree) / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        out += "diff --git a/%s b/%s\nnew file\n--- /dev/null\n+++ b/%s\n@@ -0,0 +1,%d @@\n%s\n" % (
            rel, rel, rel, len(body), "\n".join("+" + l for l in body[:400]))
    return out


def ensure_worktree(repo: Path, target: Path, branch: str) -> Path:
    """A git worktree of `repo` at `target` on `branch` (made from HEAD when new)."""
    target = Path(target)
    if (target / ".git").exists():
        return target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    have = subprocess.run(["git", "rev-parse", "--verify", "--quiet", branch], cwd=str(repo),
                          capture_output=True, text=True, env=env).returncode == 0
    argv = ["git", "worktree", "add", str(target), branch] if have else \
        ["git", "worktree", "add", "-b", branch, str(target), "HEAD"]
    proc = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode != 0:
        raise RuntimeError("could not make the dev worktree: " + (proc.stderr or proc.stdout).strip()[-300:])
    return target.resolve()


# ----------------------------------------------------------------- the MCP server
TOOL_ORDER = ("loki_status", "models_doctor", "settings_get", "settings_set", "jobs_list", "job_start", "job_stop",
              "job_logs", "engine_logs", "world_summary", "memory_search", "tools_health", "creations_list",
              "restart_engine", "read_file", "list_files", "search_files", "edit_file", "write_file", "git_status",
              "git_diff", "git_log", "read_doc", "run_tests", "ship")


def build_server(api: LokiAPI):
    """An MCPServer (mcp>=2) with every LokiAPI tool."""
    from mcp.server.mcpserver import MCPServer  # pylint: disable=import-outside-toplevel
    server = MCPServer("loki", version=VERSION, instructions=(
        "LOKI's engine and its own code. Code tools work only inside the dev worktree %s. Risky tools (%s) "
        "need the owner's approval; ship is never automatic." % (api.worktree if api._worktree else "(made on first use)",
                                                               ", ".join(RISKY_TOOLS))))
    for name in TOOL_ORDER:
        server.tool(name=name, description=(getattr(api, name).__doc__ or name).strip(),
                    structured_output=False)(getattr(api, name))
    return server


def _http_app(server, token_file: Path):
    """The streamable HTTP app behind a Bearer check (the bridge token) and loopback only."""
    app = server.streamable_http_app()

    async def guarded(scope, receive, send):
        if scope.get("type") == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
            try:
                token = token_file.read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
            given = headers.get("authorization", "")
            host = headers.get("host", "").split(":")[0]
            if not token or not hmac.compare_digest(given, "Bearer " + token) or host not in ("127.0.0.1", "localhost"):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"bridge token required"}'})
                return
        await app(scope, receive, send)
    return guarded


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="The LOKI MCP API (docs/LOKI_MCP.md)")
    ap.add_argument("--worktree", default=os.getenv("LOKI_DEV_WORKTREE", ""), help="the dev worktree (default: "
                    "harness_data/studio/worktrees/dev, made from HEAD on branch studio/dev)")
    ap.add_argument("--repo", default=str(REPO), help="the LOKI checkout (for status, version, rollback)")
    ap.add_argument("--allow-risky", action="store_true", help="let risky tools run on the client's own approval")
    ap.add_argument("--http", action="store_true", help="streamable HTTP on 127.0.0.1 instead of stdio")
    ap.add_argument("--port", type=int, default=int(os.getenv("LOKI_MCP_PORT", "8770") or 8770))
    ap.add_argument("--list", action="store_true", help="print the tools and exit")
    args = ap.parse_args(argv)
    api = LokiAPI(worktree=args.worktree or None, repo=args.repo, allow_risky=args.allow_risky)
    if args.list:
        for name in TOOL_ORDER:
            print("%-16s %s" % (name, (getattr(api, name).__doc__ or "").strip().splitlines()[0]))
        return 0
    server = build_server(api)
    if args.http:
        import uvicorn  # pylint: disable=import-outside-toplevel
        uvicorn.run(_http_app(server, api.token_file), host="127.0.0.1", port=args.port, log_level="warning")
        return 0
    server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
