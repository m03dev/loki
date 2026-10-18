"""LOKI extensions: a documented plugin format anyone can write (docs/APPS.md, "Writing an extension").

An extension is a folder (or a git repository) with an extension.json:

    {"format": "loki-extension/1", "id": "word_tools", "name": "Word tools", "version": "1.0.0",
     "description": "...", "author": "...", "homepage": "https://...",
     "tools": [{"name": "word_count", "description": "...", "file": "tools/word_count.py",
                "parameters": {"text": {"type": "string"}}, "required": ["text"],
                "network": false, "timeout": 30, "tests": [{"args": {"text": "a b"}, "expect": "2"}]}],
     "app":   "app",      # optional: a LOKI mini-app folder (manifest.json + index.html + app.js), listed in Apps
     "panel": "panel",    # optional: a UI panel (the same kind of page), opened from the extension's card
     "mode":  "mode.json" # optional: a mode (personas.py format) the extension brings
    }

Every python tool is `def run(args: dict) -> str|dict|list|number` - the same contract and the same
sandbox as the tools LOKI writes for itself (user_tools.py): its own `python -I` process with no keys
and no LOKI settings, a time limit, an output cap, and a static scan (no subprocess/eval/ctypes/deleting
files; network only when the tool says "network": true).

Installing is two steps, so the owner always sees what they get: stage(source) copies a folder or
clones a git URL (https only, shallow, no prompts) into a staging area and scans it - the manifest, every
tool's code (user_tools.scan), every text file against the rules downloaded skills are held to
(skill_scan.BLOCK_PATTERNS + skill_rules), executables that are not declared tools (never run), apps
that reach the internet - and returns the report; install(token) moves it in only when nothing blocked
it and the owner approved it in the window. A tool call asks the owner every time unless the owner
marked the extension trusted; tools never replace LOKI's own. Standard library only (plus git).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

FORMAT = "loki-extension/1"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MAX_FILES = 400
MAX_BYTES = 20_000_000
TEXT_SUFFIXES = {".md", ".txt", ".json", ".py", ".js", ".html", ".css", ".yaml", ".yml", ".toml"}
RUNNER = r"""
import json, sys, importlib.util, pathlib
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("loki_extension_tool", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
args = json.loads(sys.stdin.read() or "{}")
out = mod.run(args)
if not isinstance(out, str):
    out = json.dumps(out, ensure_ascii=False, default=str)
sys.stdout.write("\n<<<LOKI-TOOL-RESULT>>>\n" + out)
"""


def _root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root) / "extensions"
    explicit = os.getenv("LOKI_DATA", "").strip()
    return (Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data") / "extensions"


def _state_path(folder: Path) -> Path:
    return folder / ".loki_install.json"


def read_state(folder: Path) -> dict:
    try:
        data = json.loads(_state_path(folder).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(folder: Path, data: dict) -> None:
    _state_path(folder).write_text(json.dumps(data, indent=1), encoding="utf-8")


def read_manifest(folder: Path) -> dict:
    try:
        data = json.loads((Path(folder) / "extension.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _inside(folder: Path, rel: str) -> Path | None:
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        return None
    try:
        root = folder.resolve()
        path = (root / rel).resolve()
        path.relative_to(root)
        return path
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ scanning

def scan(folder: Path, reserved=()) -> dict:
    """{verdict: ok|review|blocked, id, name, problems (block), notes (look), tools, app, panel, mode, files, bytes}."""
    folder = Path(folder)
    blocked, notes = [], []
    meta = read_manifest(folder)
    if not meta:
        return {"verdict": "blocked", "problems": ["no extension.json (or it is not valid JSON)"], "notes": [], "tools": []}
    if meta.get("format") not in (FORMAT, None):
        notes.append("format %r (this LOKI reads %s)" % (meta.get("format"), FORMAT))
    ext_id = str(meta.get("id") or "")
    if not ID_RE.match(ext_id):
        blocked.append("id must be 2-40 lowercase letters, digits or _ (got %r)" % ext_id)
    if not str(meta.get("name") or "").strip():
        blocked.append("no name")
    files, total = [], 0
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if rel.startswith(".git/") or rel == ".git" or rel == _state_path(folder).name:
            continue
        if path.is_symlink():
            blocked.append("%s is a symbolic link (not allowed)" % rel)
            continue
        if path.is_file():
            files.append(rel)
            total += path.stat().st_size
    if len(files) > MAX_FILES:
        blocked.append("more than %d files" % MAX_FILES)
    if total > MAX_BYTES:
        blocked.append("larger than %d MB" % (MAX_BYTES // 1_000_000))
    import skill_scan  # pylint: disable=import-outside-toplevel
    import user_tools  # pylint: disable=import-outside-toplevel
    tool_files, tools = set(), []
    for spec in (meta.get("tools") or [])[:40]:
        if not isinstance(spec, dict):
            blocked.append("a tool entry is not an object")
            continue
        name = str(spec.get("name") or "")
        if not TOOL_RE.match(name):
            blocked.append("tool name %r must be 3-40 lowercase letters, digits or _" % name)
            continue
        if name in set(reserved):
            blocked.append("tool %s has the name of one of LOKI's own tools" % name)
            continue
        path = _inside(folder, str(spec.get("file") or ""))
        if path is None or not path.is_file() or path.suffix != ".py":
            blocked.append("tool %s: its file %r is not a .py file inside the extension" % (name, spec.get("file")))
            continue
        tool_files.add(path.relative_to(folder.resolve()).as_posix())
        code = path.read_text(encoding="utf-8", errors="replace")
        for problem in user_tools.scan(code, network=bool(spec.get("network"))):
            blocked.append("tool %s: %s" % (name, problem))
        if spec.get("network"):
            notes.append("tool %s uses the internet" % name)
        if len(str(spec.get("description") or "")) < 10:
            blocked.append("tool %s: describe what it does (a sentence the model reads)" % name)
        tools.append({"name": name, "description": str(spec.get("description") or "")[:600],
                      "network": bool(spec.get("network")), "file": path.relative_to(folder.resolve()).as_posix(),
                      "tests": len(spec.get("tests") or [])})
    for rel in files:
        path = folder / rel
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")[:400_000]
            for pattern in skill_scan.BLOCK_PATTERNS:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    blocked.append("%s tries to override LOKI's rules: %r" % (rel, match.group(0)[:60]))
            for pattern in skill_scan.REVIEW_PATTERNS:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    notes.append("%s asks to skip confirmations: %r (LOKI still asks)" % (rel, match.group(0)[:60]))
        is_exec = path.suffix.lower() in skill_scan.EXEC_SUFFIXES - {".py", ".js"}
        if path.suffix.lower() == ".py" and rel not in tool_files:
            is_exec = True
        if is_exec:
            notes.append("%s is a program LOKI will not run (only declared tools run, in the sandbox)" % rel)
    for scanner in list(skill_scan.NATIVE_SCANNERS) + list(skill_scan.EXTERNAL_SCANNERS):
        try:
            findings = scanner(folder) or []
        except Exception:  # noqa: BLE001
            findings = []
        for severity, message in findings:
            (blocked if str(severity).lower() in skill_scan.BLOCKING_SEVERITIES else notes).append(
                "scanner [%s]: %s" % (severity, message))
    parts = {}
    for key in ("app", "panel"):
        if meta.get(key):
            sub = _inside(folder, str(meta[key]))
            if sub is None or not (sub / "index.html").is_file():
                blocked.append("%s %r has no index.html" % (key, meta[key]))
                continue
            import apps  # pylint: disable=import-outside-toplevel
            for page in sub.rglob("*.html"):
                for problem in apps.html_problems(page.read_text(encoding="utf-8", errors="replace")):
                    notes.append("%s/%s: %s" % (meta[key], page.name, problem))
            parts[key] = str(meta[key])
    mode = None
    if meta.get("mode"):
        path = _inside(folder, str(meta["mode"]))
        try:
            import personas  # pylint: disable=import-outside-toplevel
            mode = personas.clean(json.loads(path.read_text(encoding="utf-8"))) if path else None
        except (OSError, ValueError) as exc:
            blocked.append("mode: %s" % exc)
    verdict = "blocked" if blocked else ("review" if notes or tools else "ok")
    return {"verdict": verdict, "id": ext_id, "name": str(meta.get("name") or "")[:60],
            "version": str(meta.get("version") or "")[:20], "description": str(meta.get("description") or "")[:400],
            "author": str(meta.get("author") or "")[:80], "homepage": str(meta.get("homepage") or "")[:200],
            "problems": sorted(set(blocked)), "notes": sorted(set(notes)), "tools": tools,
            "app": parts.get("app", ""), "panel": parts.get("panel", ""), "mode": (mode or {}).get("name", ""),
            "files": len(files), "bytes": total}


# ------------------------------------------------------------------ staging and installing

GIT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]+?(\.git)?/?$")


def _rmtree(path: Path) -> None:
    """shutil.rmtree, but a read-only file is made writable and retried first: git writes its object files
    read-only, and on Windows plain rmtree(ignore_errors=True) leaves .git behind (the clone test caught it)."""
    def _clear(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear)
    else:   # pragma: no cover - older pythons
        shutil.rmtree(path, onerror=lambda func, target, exc: _clear(func, target, exc))
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _clone(url: str, dest: Path, local_ok: bool = False) -> str:
    git = shutil.which("git")
    if not git:
        return "git is not installed on this computer"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", GCM_INTERACTIVE="never")
    kwargs = {"capture_output": True, "text": True, "timeout": 180, "env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run([git, "-c", "protocol.file.allow=" + ("always" if local_ok else "never"), "-c", "core.symlinks=false", "clone",
                               "--depth", "1", "--no-tags", "--single-branch", "--", url, str(dest)], **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "git clone failed: %s" % exc
    if proc.returncode != 0:
        return "git clone failed: %s" % ((proc.stderr or "").strip().splitlines() or ["exit %d" % proc.returncode])[-1][:300]
    _rmtree(dest / ".git")   # an installed extension is files, not a repository (read-only git objects need a nudge)
    return ""


def stage(source: str, root: Path | None = None, reserved=()) -> dict:
    """Copy a folder or clone a git URL into staging and scan it. Returns {ok, token, report} - nothing is installed."""
    source = str(source or "").strip()
    if not source:
        return {"ok": False, "error": "give a folder or a git URL (https://...)"}
    staging = _root(root) / ".staging"
    for old in staging.glob("*") if staging.is_dir() else []:   # staged and never installed for a day: gone
        try:
            if time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    token = secrets.token_hex(8)
    dest = staging / token
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.startswith(("http://", "git@", "ssh://", "file:", "ext::")):
        return {"ok": False, "error": "only https:// git URLs or a folder on this computer"}
    if source.startswith("https://"):
        if not GIT_URL.match(source):
            return {"ok": False, "error": "that does not look like a git URL"}
        err = _clone(source, dest)
        if err:
            shutil.rmtree(dest, ignore_errors=True)
            return {"ok": False, "error": err}
    else:
        src = Path(source).expanduser()
        if not (src / "extension.json").is_file():
            return {"ok": False, "error": "%s has no extension.json" % src}
        try:
            shutil.copytree(src, dest, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__", ".loki_install.json"))
        except OSError as exc:
            return {"ok": False, "error": "could not copy it: %s" % exc}
    report = scan(dest, reserved)
    (dest / ".loki_source").write_text(source, encoding="utf-8")
    return {"ok": True, "token": token, "report": report, "source": source}


def install(token: str, root: Path | None = None, reserved=()) -> dict:
    """Move a staged extension in (the owner approved the report in the window). Re-scanned first."""
    if not re.match(r"^[0-9a-f]{16}$", str(token or "")):
        return {"ok": False, "error": "bad token"}
    staged = _root(root) / ".staging" / token
    if not staged.is_dir():
        return {"ok": False, "error": "nothing staged with that token (scan it again)"}
    report = scan(staged, reserved)
    if report["verdict"] == "blocked":
        return {"ok": False, "error": "blocked: " + "; ".join(report["problems"][:4]), "report": report}
    dest = _root(root) / report["id"]
    if dest.is_dir():
        backup = _root(root) / ".old" / ("%s-%d" % (report["id"], int(time.time())))
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(backup))
    source = ""
    try:
        source = (staged / ".loki_source").read_text(encoding="utf-8")
        (staged / ".loki_source").unlink()
    except OSError:
        pass
    shutil.move(str(staged), str(dest))
    checks = run_tests(dest)
    state = {"enabled": all(c["ok"] for c in checks), "trusted": False,   # a new version is never trusted until the owner says so again
             "installed": time.time(), "source": source, "verdict": report["verdict"], "checks": checks}
    _write_state(dest, state)
    _install_mode(dest, root)
    return {"ok": True, "id": report["id"], "enabled": state["enabled"], "checks": checks, "report": report}


def _install_mode(folder: Path, root: Path | None) -> None:
    meta = read_manifest(folder)
    if not meta.get("mode"):
        return
    path = _inside(folder, str(meta["mode"]))
    try:
        import personas  # pylint: disable=import-outside-toplevel
        mode = json.loads(path.read_text(encoding="utf-8"))
        mode.setdefault("id", "ext_" + str(meta.get("id")))
        personas.save(mode, root)
    except Exception:  # noqa: BLE001 - a broken mode never stops the tools installing
        pass


def run_tests(folder: Path) -> list:
    """Each declared tool's own tests, in the sandbox. A tool without tests is accepted (noted)."""
    out = []
    meta = read_manifest(folder)
    for spec in meta.get("tools") or []:
        name = str(spec.get("name") or "")
        path = _inside(folder, str(spec.get("file") or ""))
        if not TOOL_RE.match(name) or path is None:
            continue
        tests = spec.get("tests") or []
        failed = []
        for i, test in enumerate(tests[:10] if isinstance(tests, list) else []):
            ok, text = execute(path, test.get("args") if isinstance(test, dict) else {}, folder, timeout=min(int(spec.get("timeout") or 30), 60))
            if not ok or str(test.get("expect", "")) not in text:
                failed.append("test %d: got %r" % (i + 1, text[:160]))
        out.append({"tool": name, "ok": not failed, "tests": len(tests), "detail": "; ".join(failed)[:600]})
    return out


def execute(path: Path, args: dict, cwd: Path, timeout: int = 30, python: str = "") -> tuple:
    """Run one extension tool file in its own sandboxed process: (ok, text). Same rules as user_tools.execute."""
    import user_tools  # pylint: disable=import-outside-toplevel
    argv = [python or sys.executable, "-I", "-c", RUNNER, str(path)]
    kwargs: dict = {"input": json.dumps(args or {}), "capture_output": True, "text": True, "encoding": "utf-8",
                    "errors": "replace", "cwd": str(cwd), "env": user_tools.sandbox_env(),
                    "timeout": max(1, min(int(timeout or 30), user_tools.MAX_TIMEOUT))}
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
    if user_tools.MARK in out:
        printed, result = out.split(user_tools.MARK, 1)
        result = result.lstrip("\n")
        if printed.strip():
            result += "\n(printed: %s)" % printed.strip()[:2000]
        return proc.returncode == 0, result[:user_tools.MAX_OUTPUT]
    err = (proc.stderr or "").strip().splitlines()
    return False, "error: the tool failed: %s" % ((err[-1] if err else "exit %s" % proc.returncode)[:2000])


# ------------------------------------------------------------------ installed extensions

def listing(root: Path | None = None) -> list:
    out = []
    base = _root(root)
    if not base.is_dir():
        return out
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and ID_RE.match(p.name)):
        meta, state = read_manifest(folder), read_state(folder)
        if not meta:
            continue
        out.append({"id": folder.name, "name": str(meta.get("name") or folder.name)[:60],
                    "version": str(meta.get("version") or "")[:20], "description": str(meta.get("description") or "")[:400],
                    "author": str(meta.get("author") or "")[:80], "enabled": bool(state.get("enabled")),
                    "trusted": bool(state.get("trusted")), "source": str(state.get("source") or "")[:300],
                    "installed": state.get("installed", 0), "checks": state.get("checks") or [],
                    "tools": [str(t.get("name")) for t in meta.get("tools") or [] if isinstance(t, dict)],
                    "app": bool(meta.get("app")), "panel": bool(meta.get("panel")),
                    "app_url": "/apps/x/%s/index.html" % folder.name if meta.get("app") else "",
                    "panel_url": "/apps/p/%s/index.html" % folder.name if meta.get("panel") else ""})
    return out


def set_flag(ext_id: str, flag: str, on: bool, root: Path | None = None) -> dict:
    folder = _root(root) / str(ext_id)
    if not ID_RE.match(str(ext_id)) or not (folder / "extension.json").is_file():
        return {"ok": False, "error": "no extension %s" % ext_id}
    if flag not in ("enabled", "trusted"):
        return {"ok": False, "error": "unknown setting"}
    state = read_state(folder)
    if flag == "enabled" and on:
        report = scan(folder)
        if report["verdict"] == "blocked":
            return {"ok": False, "error": "it no longer passes the scan: " + "; ".join(report["problems"][:3])}
    state[flag] = bool(on)
    _write_state(folder, state)
    return {"ok": True, "id": ext_id, flag: bool(on)}


def remove(ext_id: str, root: Path | None = None) -> dict:
    folder = _root(root) / str(ext_id)
    if not ID_RE.match(str(ext_id)) or not folder.is_dir():
        return {"ok": False, "error": "no extension %s" % ext_id}
    backup = _root(root) / ".old" / ("%s-%d" % (ext_id, int(time.time())))
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(backup))
    return {"ok": True, "id": ext_id}


def ui_folder(ext_id: str, part: str, root: Path | None) -> Path | None:
    """The folder of an enabled extension's app or panel (apps.app_file serves from it)."""
    folder = _root(root) / str(ext_id)
    if not ID_RE.match(str(ext_id)) or not read_state(folder).get("enabled"):
        return None
    rel = read_manifest(folder).get(part)
    return _inside(folder, str(rel)) if rel else None


def tools(root: Path | None = None) -> list:
    """[{name, description, parameters, required, path, folder, timeout, ext, trusted}] of every enabled extension."""
    out = []
    for item in listing(root):
        if not item["enabled"]:
            continue
        folder = _root(root) / item["id"]
        for spec in read_manifest(folder).get("tools") or []:
            if not isinstance(spec, dict) or not TOOL_RE.match(str(spec.get("name") or "")):
                continue
            path = _inside(folder, str(spec.get("file") or ""))
            if path is None or not path.is_file():
                continue
            params = spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {}
            out.append({"name": spec["name"], "description": str(spec.get("description") or "")[:600],
                        "parameters": params, "required": [r for r in spec.get("required") or [] if r in params],
                        "path": path, "folder": folder, "timeout": int(spec.get("timeout") or 30),
                        "ext": item["id"], "ext_name": item["name"], "trusted": item["trusted"]})
    return out


class Registry:
    """Keeps loki.py's tool tables in step with the enabled extensions' tools (like user_tools.Registry)."""

    def __init__(self, engine, root_fn, runner) -> None:
        self.engine, self.root_fn, self.runner = engine, root_fn, runner
        self.names: set = set()

    def builtin(self) -> set:
        return set(self.engine.LOCAL_TOOLS) - self.names

    def sync(self) -> list:
        eng = self.engine
        builtin = self.builtin()
        wanted = {t["name"]: t for t in tools(self.root_fn()) if t["name"] not in builtin}
        ours = set(self.names) | set(wanted)
        for name in list(self.names):
            if name not in wanted:
                eng.LOCAL_TOOLS.pop(name, None)
                eng.MODEL_TOOL_NAMES.discard(name)
                self.names.discard(name)
        for table in (eng.TOOL_SCHEMAS, eng.MODEL_TOOL_SCHEMAS):
            table[:] = [t for t in table if t["function"]["name"] not in ours or t["function"]["name"] in builtin]
        for name, item in wanted.items():
            eng.LOCAL_TOOLS[name] = self.runner(item)
            eng.MODEL_TOOL_NAMES.add(name)
            sch = {"type": "function", "function": {
                "name": name, "description": "[extension %s; asks before it runs] %s" % (item["ext_name"], item["description"]),
                "parameters": {"type": "object", "properties": item["parameters"], "required": item["required"]}}}
            eng.TOOL_SCHEMAS.append(sch)
            eng.MODEL_TOOL_SCHEMAS.append(sch)
            self.names.add(name)
        eng.TOOL_CATEGORIES["extensions"] = sorted(self.names)
        return sorted(self.names)
