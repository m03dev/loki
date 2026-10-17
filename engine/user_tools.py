"""Tools LOKI writes for itself (EVOLVE E9).

A tool is one folder in <DATA_DIR>/tools/<name>/:

    tool.json   {"name": "word_count", "description": "...", "parameters": {"text": {"type": "string"}},
                 "required": ["text"], "tests": [{"args": {"text": "a b"}, "expect": "2"}],
                 "timeout": 30, "network": false, "enabled": true, "created_by": "loki", "created": <t>,
                 "check": {"ok": true, "t": <t>, "detail": "..."}}
    tool.py     def run(args: dict) -> str | dict | list | number

The `make_tool` tool lets LOKI write one; it is CHECKED at once and loaded without a restart.
Every call runs like run_command:

  * approval first: the window asks the owner (no decision provider may skip it); a background
    job may only run it when the job was started with allow_commands - otherwise it is denied;
  * sandboxed: a separate `python -I` process (no user site, no PYTHON* variables), working in the
    workspace, with a minimal environment (no API keys, no LOKI_* settings), a time limit and an
    output cap; the code never runs inside the engine's own process;
  * checked before it is enabled: the code must compile, define run(args), pass a static scan
    (no subprocess/os.system/ctypes/eval/exec/deleting files; no network unless "network": true),
    and pass its own tests (each test's output must contain `expect`). A tool whose code or json
    changed since its last check is switched off until it passes again.

Settings > Tools lists them with enable / disable / check / delete (GET /user_tools, POST
/user_tools/{toggle,check,delete}). Standard library only.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MAX_CODE = 40_000
MAX_OUTPUT = 12_000
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300
# Modules a tool may not import (the sandbox is a process, not a jail: these are the obvious ways
# out of "a small function on its arguments and the workspace's files").
BLOCKED_IMPORTS = {"subprocess", "ctypes", "multiprocessing", "pty", "signal", "winreg", "_winapi", "msvcrt",
                   "importlib", "runpy", "code", "codeop", "pickle", "marshal", "shelve"}
NETWORK_IMPORTS = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "ssl", "telnetlib"}
BLOCKED_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "globals", "vars"}
BLOCKED_ATTRS = {"system", "popen", "spawnl", "spawnv", "spawnve", "execv", "execve", "execl", "execvp", "fork",
                 "kill", "unlink", "rmdir", "removedirs", "rmtree", "chmod", "chown", "startfile", "putenv",
                 "_exit", "setuid", "symlink", "link"}
OS_ONLY_ATTRS = {"remove", "rename", "replace", "truncate"}   # fine on a list or a str, not on os

RUNNER = r"""
import json, sys, importlib.util, pathlib
folder = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("loki_user_tool", folder / "tool.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
args = json.loads(sys.stdin.read() or "{}")
out = mod.run(args)
if not isinstance(out, str):
    out = json.dumps(out, ensure_ascii=False, default=str)
sys.stdout.write("\n<<<LOKI-TOOL-RESULT>>>\n" + out)
"""
MARK = "<<<LOKI-TOOL-RESULT>>>"


def _data_dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def tools_dir(root: Path | None = None) -> Path:
    return _data_dir(root) / "tools"


def folder(name: str, root: Path | None = None) -> Path:
    if not NAME_RE.match(str(name or "")):
        raise ValueError("a tool name is 3-40 lowercase letters, digits or _ and starts with a letter")
    return tools_dir(root) / name


def _fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    for part in ("tool.py", "tool.json"):
        try:
            data = (path / part).read_bytes()
        except OSError:
            data = b""
        if part == "tool.json":
            try:   # the check result and the switch are not part of what was checked
                meta = json.loads(data.decode("utf-8") or "{}")
                for k in ("enabled", "check", "updated"):
                    meta.pop(k, None)
                data = json.dumps(meta, sort_keys=True).encode("utf-8")
            except ValueError:
                pass
        h.update(part.encode() + b"\0" + data + b"\0")
    return h.hexdigest()[:16]


def read_meta(path: Path) -> dict:
    try:
        meta = json.loads((path / "tool.json").read_text(encoding="utf-8"))
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_meta(path: Path, meta: dict) -> None:
    tmp = path / "tool.json.tmp"
    tmp.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path / "tool.json")


def scan(code: str, network: bool = False) -> list:
    """Static problems with a tool's code: [] when it may be checked further."""
    problems = []
    if len(code) > MAX_CODE:
        return ["the code is longer than %d characters" % MAX_CODE]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ["it does not compile: %s (line %s)" % (exc.msg, exc.lineno)]
    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run" and node in tree.body:
            has_run = True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                top = name.split(".")[0]
                if top in BLOCKED_IMPORTS:
                    problems.append("imports %s (not allowed in a LOKI tool)" % name)
                if top in NETWORK_IMPORTS and not network:
                    problems.append("uses the network (%s) - set \"network\": true in tool.json if it must" % name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            problems.append("calls %s()" % node.func.id)
        if isinstance(node, ast.Attribute) and (node.attr in BLOCKED_ATTRS or (
                node.attr in OS_ONLY_ATTRS and isinstance(node.value, ast.Name) and node.value.id in ("os", "shutil"))):
            problems.append("uses .%s" % node.attr)
        if isinstance(node, ast.Name) and node.id in ("__builtins__", "__loader__"):
            problems.append("touches %s" % node.id)
    if not has_run:
        problems.append("it has no top-level def run(args)")
    return sorted(set(problems))


def sandbox_env(base: dict | None = None) -> dict:
    """The few variables a tool process gets: enough for Python to start, no keys or LOKI settings."""
    base = base if base is not None else os.environ
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "COMSPEC", "PATHEXT")
    env = {k: base[k] for k in keep if k in base}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def execute(path: Path, args: dict, cwd: Path, timeout: int = DEFAULT_TIMEOUT, python: str = "") -> tuple:
    """Run one tool in its own process: (ok, text)."""
    argv = [python or sys.executable, "-I", "-c", RUNNER, str(path)]
    kwargs: dict = {"input": json.dumps(args or {}), "capture_output": True, "text": True, "encoding": "utf-8",
                    "errors": "replace", "cwd": str(cwd), "env": sandbox_env(),
                    "timeout": max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.run(argv, **kwargs)
    except subprocess.TimeoutExpired:
        return False, "error: the tool ran longer than %ss and was stopped" % kwargs["timeout"]
    except OSError as exc:
        return False, "error: could not start the tool: %s" % exc
    out = proc.stdout or ""
    if MARK in out:
        printed, result = out.split(MARK, 1)
        result = result.lstrip("\n")
        if printed.strip():
            result += "\n(printed: %s)" % printed.strip()[:2000]
        return proc.returncode == 0, result[:MAX_OUTPUT]
    err = (proc.stderr or "").strip().splitlines()
    # the exception itself first (the last line), then where it happened
    shown = ([err[-1].strip()] + [ln.strip() for ln in err[-4:-1]]) if err else []
    return False, "error: the tool failed: %s" % (" | ".join(shown) or "exit %s" % proc.returncode)[:2000]


def check(name: str, root: Path | None = None, cwd: Path | None = None) -> dict:
    """Scan, compile and run the tool's own tests; record the result in tool.json."""
    path = folder(name, root)
    meta = read_meta(path)
    if not meta:
        return {"ok": False, "error": "no tool %s (or its tool.json is broken)" % name}
    try:
        code = (path / "tool.py").read_text(encoding="utf-8")
    except OSError:
        return {"ok": False, "error": "%s has no tool.py" % name}
    problems = scan(code, network=bool(meta.get("network")))
    details = []
    if not problems:
        tests = meta.get("tests") or []
        if not isinstance(tests, list) or not tests:
            problems.append("it has no tests (add at least one {\"args\": {...}, \"expect\": \"...\"})")
        for i, test in enumerate(tests[:10] if isinstance(tests, list) else []):
            args = test.get("args") if isinstance(test, dict) else None
            expect = str(test.get("expect", "")) if isinstance(test, dict) else ""
            ok, out = execute(path, args if isinstance(args, dict) else {}, cwd or path,
                              timeout=min(int(meta.get("timeout") or DEFAULT_TIMEOUT), 60))
            passed = ok and (expect in out)
            details.append("test %d: %s%s" % (i + 1, "ok" if passed else "FAILED", "" if passed else " - got %r" % out[:200]))
            if not passed:
                problems.append("test %d failed (expected the output to contain %r, got %r)" % (i + 1, expect, out[:160]))
    result = {"ok": not problems, "t": time.time(), "problems": problems, "detail": "; ".join(details)[:1500],
              "fingerprint": _fingerprint(path)}
    meta["check"] = result
    if problems:
        meta["enabled"] = False
    _write_meta(path, meta)
    return {"ok": not problems, "name": name, **result}


def make(name: str, description: str, code: str, parameters: dict | None = None, required=None,
         tests=None, timeout: int = DEFAULT_TIMEOUT, network: bool = False, by: str = "loki",
         root: Path | None = None, reserved=(), enable: bool = True) -> dict:
    """Write (or rewrite) a tool folder and check it; enabled only when the check passes."""
    try:
        path = folder(name, root)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if name in set(reserved) and not (path / "tool.json").is_file():
        return {"ok": False, "error": "%s is one of LOKI's built-in tools - pick another name" % name}
    description = " ".join(str(description or "").split())[:600]
    if len(description) < 10:
        return {"ok": False, "error": "describe what the tool does (a sentence the model will read)"}
    code = str(code or "")
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except ValueError:
            return {"ok": False, "error": "parameters must be a JSON object of {name: {type, description}}"}
    if isinstance(tests, str):
        try:
            tests = json.loads(tests)
        except ValueError:
            return {"ok": False, "error": "tests must be a JSON list of {args, expect}"}
    if isinstance(required, str):
        required = [r.strip() for r in required.split(",") if r.strip()]
    parameters = parameters if isinstance(parameters, dict) else {}
    for key, spec in list(parameters.items()):
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$", str(key)) or not isinstance(spec, dict):
            return {"ok": False, "error": "parameter %r must be a name with a {\"type\": ...} schema" % key}
        if spec.get("type") not in ("string", "integer", "number", "boolean", "array", "object"):
            spec["type"] = "string"
    problems = scan(code, network=bool(network))
    if problems:
        return {"ok": False, "error": "the code was not saved: " + "; ".join(problems)}
    path.mkdir(parents=True, exist_ok=True)
    old = read_meta(path)
    (path / "tool.py").write_text(code, encoding="utf-8")
    meta = {"name": name, "description": description, "parameters": parameters,
            "required": [r for r in (required or []) if r in parameters],
            "tests": tests if isinstance(tests, list) else [], "timeout": max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT)),
            "network": bool(network), "enabled": False, "created_by": old.get("created_by") or by,
            "created": old.get("created") or time.time(), "updated": time.time()}
    _write_meta(path, meta)
    result = check(name, root)
    if result["ok"] and enable:
        meta = read_meta(path)
        meta["enabled"] = True
        _write_meta(path, meta)
    return {"ok": result["ok"], "name": name, "enabled": bool(result["ok"] and enable), "check": result,
            "error": "" if result["ok"] else "saved but switched off until it passes: " + "; ".join(result["problems"])}


def listing(root: Path | None = None) -> list:
    """Every tool folder: name, description, enabled, check state, stale (changed since its check)."""
    out = []
    base = tools_dir(root)
    if not base.is_dir():
        return out
    for path in sorted(p for p in base.iterdir() if p.is_dir()):
        meta = read_meta(path)
        if not meta or not NAME_RE.match(path.name):
            continue
        chk = meta.get("check") or {}
        stale = bool(chk) and chk.get("fingerprint") != _fingerprint(path)
        out.append({"name": path.name, "description": meta.get("description", ""),
                    "parameters": meta.get("parameters") or {}, "required": meta.get("required") or [],
                    "enabled": bool(meta.get("enabled")) and bool(chk.get("ok")) and not stale,
                    "checked": bool(chk), "check_ok": bool(chk.get("ok")), "problems": chk.get("problems") or [],
                    "check_detail": chk.get("detail", ""), "checked_at": chk.get("t", 0), "stale": stale,
                    "network": bool(meta.get("network")), "created_by": meta.get("created_by", ""),
                    "created": meta.get("created", 0), "tests": len(meta.get("tests") or [])})
    return out


def set_enabled(name: str, on: bool, root: Path | None = None) -> dict:
    try:
        path = folder(name, root)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    meta = read_meta(path)
    if not meta:
        return {"ok": False, "error": "no tool %s" % name}
    if on:
        chk = meta.get("check") or {}
        if not chk.get("ok") or chk.get("fingerprint") != _fingerprint(path):
            result = check(name, root)
            if not result["ok"]:
                return {"ok": False, "error": "it does not pass its check: " + "; ".join(result["problems"])}
            meta = read_meta(path)
    meta["enabled"] = bool(on)
    _write_meta(path, meta)
    return {"ok": True, "name": name, "enabled": bool(on)}


def delete(name: str, root: Path | None = None) -> dict:
    try:
        path = folder(name, root)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not (path / "tool.json").is_file():
        return {"ok": False, "error": "no tool %s" % name}
    shutil.rmtree(path, ignore_errors=True)
    return {"ok": True, "name": name}


def schema_of(item: dict) -> dict:
    return {"type": "function", "function": {
        "name": item["name"],
        "description": "[a tool LOKI wrote for itself; asks before it runs] " + item["description"],
        "parameters": {"type": "object", "properties": item.get("parameters") or {},
                       "required": list(item.get("required") or [])}}}


# ------------------------------------------------------------------ the engine side (loki.py)

class Registry:
    """Keeps loki.py's tool tables in step with the enabled tool folders (no restart needed).

    sync() adds every enabled, checked tool to LOCAL_TOOLS / TOOL_SCHEMAS / MODEL_TOOL_SCHEMAS /
    MODEL_TOOL_NAMES / TOOL_CATEGORIES["my_tools"] and removes the ones that were switched off or
    deleted. A built-in tool is never replaced."""

    def __init__(self, engine, root_fn, runner) -> None:
        self.engine = engine          # the loki module
        self.root_fn = root_fn        # () -> DATA_DIR
        self.runner = runner          # name -> callable(**args) for LOCAL_TOOLS
        self.names: set = set()

    def builtin(self) -> set:
        return set(self.engine.LOCAL_TOOLS) - self.names

    def sync(self) -> list:
        eng = self.engine
        builtin = self.builtin()
        wanted = {i["name"]: i for i in listing(self.root_fn()) if i["enabled"] and i["name"] not in builtin}
        ours = set(self.names) | set(wanted)       # every schema this registry put in (or will)
        for name in list(self.names):
            if name not in wanted:
                eng.LOCAL_TOOLS.pop(name, None)
                eng.MODEL_TOOL_NAMES.discard(name)
                self.names.discard(name)
        for table in (eng.TOOL_SCHEMAS, eng.MODEL_TOOL_SCHEMAS):
            table[:] = [t for t in table if t["function"]["name"] not in ours or t["function"]["name"] in builtin]
        for name, item in wanted.items():
            eng.LOCAL_TOOLS[name] = self.runner(name)
            eng.MODEL_TOOL_NAMES.add(name)
            sch = schema_of(item)
            eng.TOOL_SCHEMAS.append(sch)
            eng.MODEL_TOOL_SCHEMAS.append(sch)
            self.names.add(name)
        eng.TOOL_CATEGORIES["my_tools"] = sorted(self.names)
        return sorted(self.names)
