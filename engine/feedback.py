"""Send feedback: a zip of LOKI's logs WITHOUT keys or chats, and a GitHub issue / email draft (session 30).

Settings > General > Send feedback (app/ui/feedback.js) posts here (routes in usability_api.py):

    GET  /feedback          what would be sent (the file list), where it goes
    POST /feedback/send     {note, logs: bool, how: "github" | "email" | "folder"}
         -> {ok, zip, size, files, url}: the zip is saved (Desktop, else <data>/feedback/), its folder is
            shown, and a NEW GitHub issue (prefilled, the person attaches the zip themselves) or an email
            draft opens. Nothing is uploaded by LOKI.

What goes in: LOKI's own log files (the app, launcher, bootstrap, engine, updates; the newest
256 KB of each), the release/update state, and system.json (LOKI version, OS, CPU, memory, which
providers are switched on - names only - and the welcome tour's state).
What never goes in: .env, keys, tokens, chats, memory, files, the workspace, harness_data's
databases. Every line is redacted before it is written: anything key-like (tools/secret_scan.py
patterns), "Bearer ...", "#token=...", KEY=value for *_KEY/*_TOKEN/*_SECRET/PASSWORD names,
e-mail addresses, and the home folder (-> ~).
Standard library only.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ISSUES = "https://github.com/m03dev/loki/issues/new"
TAIL_BYTES = 256 * 1024
LOG_NAMES = ("loki_app.log", "launcher.log", "bootstrap.log", "engine.out", "loki_bridge.log", "update_health.json")
LOG_DIRS = ("app", "logs")

try:   # the same patterns the release secret scan refuses (tools/ ships with every release)
    sys.path.insert(0, str(REPO / "tools"))
    import secret_scan as _scan  # type: ignore
    _PATTERNS = [rx for _, rx in _scan.PATTERNS]
except Exception:  # noqa: BLE001 - a small built-in list then
    _PATTERNS = [re.compile(r"(sk-[A-Za-z0-9_\-]{20,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,}|nvapi-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,})")]
_EXTRA = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(#token=|[?&](?:token|key|api_key|access_token)=)[^&\s\"']+"),
    re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*\s*[=:]\s*)[\"']?[^\s\"',}]{4,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_LONG_SECRET = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def redact(text: str, home: str | None = None) -> str:
    for rx in _EXTRA:
        text = rx.sub(lambda m: (m.group(1) if m.groups() and m.group(1) else "") + "[redacted]", text)
    for rx in _PATTERNS:
        text = rx.sub("[redacted]", text)
    text = _EMAIL.sub("[email]", text)
    # a long random-looking word is a token more often than not (git hashes stay: hex of 40 is allowed)
    text = _LONG_SECRET.sub(lambda m: m.group(0) if re.fullmatch(r"[0-9a-f]{40,64}", m.group(0)) else "[redacted]", text)
    home = home if home is not None else str(Path.home())
    if home and len(home) > 3:
        text = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    return text


def data_dir(agent: Any = None) -> Path:
    if agent is not None and getattr(agent, "DATA_DIR", None):
        return Path(agent.DATA_DIR)
    return Path(os.environ.get("LOKI_DATA") or (REPO / "harness_data"))


def log_files(data: Path) -> list:
    """LOKI's own logs only - never .env, chats, memory, keys, databases."""
    found = []
    for sub in LOG_DIRS:
        folder = data / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and (path.name in LOG_NAMES or path.suffix in (".log",)) and "token" not in path.name.lower():
                found.append(path)
    state = data / "versions" / "state.json"
    if state.is_file():
        found.append(state)
    return found[:40]


def _tail(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            size = path.stat().st_size
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            return fh.read().decode("utf-8", "replace")
    except OSError as exc:
        return "(could not read: %s)" % exc


def system_info(agent: Any = None) -> dict:
    info = {"loki": "", "os": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
            "installed": bool(os.environ.get("LOKI_RELEASE_ROOT")), "time": time.strftime("%Y-%m-%d %H:%M:%S %z")}
    try:
        import updater  # pylint: disable=import-outside-toplevel
        v = updater.status()
        info["loki"] = v.get("label") or v.get("commit") or ""
    except Exception:  # noqa: BLE001
        pass
    if agent is not None:
        try:
            info["providers_on"] = sorted(n for n in getattr(agent, "SMART_ORDER", []) if agent.provider_configured(n))
            info["model"] = getattr(agent, "model_name", "")
            hw = getattr(agent, "HARDWARE", None) or {}
            info["memory_gb"], info["gpu"] = hw.get("ram_gb"), hw.get("gpu")
        except Exception:  # noqa: BLE001
            pass
    return info


def summary(agent: Any = None) -> dict:
    data = data_dir(agent)
    return {"ok": True, "files": [p.name for p in log_files(data)], "where": str(save_dir()), "issues": ISSUES,
            "never": ["keys and tokens", "your chats", "LOKI's memory", "your files", "the .env settings file"]}


def save_dir() -> Path:
    desk = Path.home() / "Desktop"
    return desk if desk.is_dir() and os.access(desk, os.W_OK) else data_dir() / "feedback"


def make_bundle(note: str = "", logs: bool = True, agent: Any = None, out_dir: Path | None = None) -> dict:
    data = data_dir(agent)
    out = Path(out_dir or save_dir())
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / ("LOKI-feedback-%s.zip" % time.strftime("%Y%m%d-%H%M%S"))
    names = []
    info = system_info(agent)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system.json", redact(json.dumps(info, indent=2)))
        names.append("system.json")
        if note.strip():
            zf.writestr("note.txt", redact(note.strip()[:8000]))
            names.append("note.txt")
        if logs:
            for path in log_files(data):
                arc = "logs/%s-%s" % (path.parent.name, path.name)
                zf.writestr(arc, redact(_tail(path)))
                names.append(arc)
        zf.writestr("README.txt", "LOKI feedback bundle. Logs are redacted: no keys, tokens, chats, memory or files.\n")
    return {"ok": True, "zip": str(zpath), "size": zpath.stat().st_size, "files": names, "info": info}


def issue_url(note: str, info: dict, zip_name: str) -> str:
    title = "Feedback: " + (note.strip().splitlines()[0][:70] if note.strip() else "LOKI %s" % info.get("loki", ""))
    body = ("**What happened**\n%s\n\n**LOKI** %s · %s · %s\n\nPlease drag **%s** (saved on your Desktop or in "
            "LOKI's data folder) into this box - it has LOKI's logs with keys and chats removed.\n"
            % (redact(note.strip()[:1500]) or "(describe it here)", info.get("loki", "?"), info.get("os", "?"),
               info.get("machine", "?"), zip_name))
    return ISSUES + "?" + urllib.parse.urlencode({"title": redact(title), "body": body, "labels": "tester-feedback"})


def mail_url(note: str, info: dict, zip_name: str) -> str:
    to = os.environ.get("LOKI_FEEDBACK_EMAIL", "").strip()
    subject = "LOKI feedback (%s)" % info.get("loki", "")
    body = ("%s\n\nLOKI %s, %s %s\nAttached: %s (logs with keys and chats removed)\n"
            % (redact(note.strip()[:1500]), info.get("loki", "?"), info.get("os", "?"), info.get("machine", "?"), zip_name))
    return "mailto:%s?%s" % (urllib.parse.quote(to), urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote))


def reveal(path: Path) -> None:
    """Show the zip in Explorer / Finder so it can be dragged into the issue or the email."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def send(data: dict, agent: Any = None, opener=None, revealer=None) -> tuple:
    how = str(data.get("how") or "github")
    if how not in ("github", "email", "folder"):
        return 400, {"ok": False, "error": "how must be github, email or folder"}
    note = str(data.get("note") or "")
    try:
        result = make_bundle(note, bool(data.get("logs", True)), agent)
    except OSError as exc:
        return 500, {"ok": False, "error": "could not save the feedback file: %s" % exc}
    name = Path(result["zip"]).name
    url = issue_url(note, result["info"], name) if how == "github" else mail_url(note, result["info"], name) if how == "email" else ""
    if os.environ.get("LOKI_FEEDBACK_NO_OPEN") != "1":
        (revealer or reveal)(Path(result["zip"]))
        if url:
            threading.Thread(target=opener or webbrowser.open, args=(url,), daemon=True).start()
    result.pop("info", None)
    return 200, dict(result, url=url, how=how)
