"""Your data: what LOKI keeps, where, what left this computer - and a backup you can restore
(research round 3: Open WebUI's "Export all chats" + database backup, Cherry Studio's backup/restore,
Jan's and Msty's local-first privacy pages, AnythingLLM's "your data stays on your machine").

  inventory()  every place LOKI stores something (size, file count, what it is), the chats, which
               model providers got your messages in the last 30 days (from the usage ledger: provider,
               calls, tokens - never the text), and plain facts (no analytics, no telemetry).
  backup()     one zip of LOKI's data folder + this workspace's chats, WITHOUT the secrets file
               (.env: keys, tokens) unless asked, without the big re-downloadable parts (the Python
               venv, local models, installed tools, caches). A manifest says what is inside.
  restore()    checks the zip (manifest, no path escapes, no links), makes a safety backup of now
               first, then puts the files back. Files that are not in the backup are left alone.
  clear()      deletes one kind of data (chats, logs, usage, previews, computer log) - asks first
               in the window; never the secrets, never memory (Settings > Memory forgets things).
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

FORMAT = "loki-backup"
SECRETS = ".env"
SKIP_DIRS = {".venv", "venv", "models", "tools", "__pycache__", "cache", ".cache", "node_modules", "bench",
             "backups", "tmp", "pw-browsers", "wan2gp", "imagegen"}
SKIP_SUFFIX = (".lock", ".pid", ".sock", ".tmp")
MAX_FILE = 200_000_000
KNOWN = {
    SECRETS: "Your keys and settings (secret - never shown, not in backups unless you ask)",
    "usage.jsonl": "Every model call: provider, model, tokens, cost (no message text)",
    "memory": "What LOKI remembers about you and your work",
    "memory.db": "What LOKI remembers about you and your work",
    "memory_core": "What LOKI remembers about you and your work",
    "jobs": "Background jobs: their requests, logs and results",
    "logs": "Engine logs",
    "artifacts": "Previews of pages and pictures LOKI wrote in chats",
    "prompts.json": "Your prompt library",
    "arena.json": "Your model comparison votes",
    "channels": "Telegram link (paired chat, last message id)",
    "computer_log.jsonl": "Every action computer use took",
    "tool_health.json": "Which tools work (calls, failures)",
    "crm.sqlite3": "Your CRM: contacts, companies, deals",
    "app": "Window state, creations settings",
    "loki_settings.json": "Tool categories you switched on or off",
    "provider_health.json": "Which model providers answered lately",
    "experience.jsonl": "What worked for which model (routing learns from it)",
    "user_tools": "Tools LOKI wrote for itself",
    ".venv": "LOKI's Python (re-installed by setup - not backed up)",
    "models": "Local models (re-downloadable - not backed up)",
    "tools": "Tools LOKI wrote for itself (backed up) and installed helper programs (re-downloadable - not backed up)",
}


def backup_dir() -> Path:
    raw = os.getenv("LOKI_BACKUP_DIR", "").strip()
    return Path(os.path.expanduser(raw)) if raw else Path.home() / "LOKI Backups"


def _walk(root: Path):
    """(path, size) of every regular file under root, skipping links and the re-downloadable parts."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        keep = []
        for d in dirnames:
            full = Path(dirpath, d)
            if full.is_symlink():
                continue
            if d not in SKIP_DIRS:
                keep.append(d)
            elif d == "tools" and full.parent == root:
                keep.append(d)          # data/tools holds LOKI's own tools (tool.json) next to installed programs
        if Path(dirpath).parent.name == "tools" and Path(dirpath).parent.parent == root \
                and not Path(dirpath, "tool.json").is_file():
            dirnames[:] = []
            continue                    # an installed program (sd.cpp, Wan2GP ...) - re-downloadable
        dirnames[:] = keep
        for name in filenames:
            p = Path(dirpath, name)
            if p.is_symlink() or name.endswith(SKIP_SUFFIX):
                continue
            try:
                yield p, p.stat().st_size
            except OSError:
                continue


def _dir_size(path: Path, cap: int = 50000) -> tuple:
    total = files = 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    for dirpath, _dirs, names in os.walk(path, followlinks=False):
        for n in names:
            try:
                total += Path(dirpath, n).stat().st_size
            except OSError:
                pass
            files += 1
            if files >= cap:
                return total, files
    return total, files


def inventory(data_dir: Path, workspace: Path, usage_entries: list | None = None,
              is_local: Callable[[str], bool] | None = None, conversations: int = 0) -> dict:
    data_dir, workspace = Path(data_dir), Path(workspace)
    places = []
    if data_dir.is_dir():
        for entry in sorted(data_dir.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_symlink():
                continue
            size, files = _dir_size(entry)
            places.append({"name": entry.name, "what": KNOWN.get(entry.name, "Other LOKI data"), "bytes": size,
                           "files": files, "secret": entry.name == SECRETS,
                           "backed_up": entry.name not in SKIP_DIRS})
    chats_file = workspace / ".loki" / "loki_conversations.json"
    chats = {"path": str(chats_file), "bytes": chats_file.stat().st_size if chats_file.is_file() else 0,
             "count": int(conversations or 0)}
    since = time.time() - 30 * 86400
    providers: dict = {}
    for e in usage_entries or []:
        if float(e.get("t", 0) or 0) < since:
            continue
        name = str(e.get("provider") or "?")
        row = providers.setdefault(name, {"provider": name, "calls": 0, "tokens_in": 0, "tokens_out": 0,
                                          "local": bool(is_local(name)) if is_local else False, "last": 0})
        row["calls"] += 1
        row["tokens_in"] += int(e.get("in") or 0)
        row["tokens_out"] += int(e.get("out") or 0)
        row["last"] = max(row["last"], float(e.get("t", 0) or 0))
    sent = sorted(providers.values(), key=lambda r: (r["local"], -r["calls"]))
    cloud = [r for r in sent if not r["local"]]
    return {"data_dir": str(data_dir), "places": places, "chats": chats, "providers": sent,
            "summary": {"bytes": sum(p["bytes"] for p in places) + chats["bytes"],
                        "cloud_calls_30d": sum(r["calls"] for r in cloud),
                        "local_calls_30d": sum(r["calls"] for r in sent if r["local"]),
                        "cloud_providers": [r["provider"] for r in cloud]},
            "facts": ["LOKI sends no analytics or telemetry anywhere.",
                      "Your messages go only to the model that answers them; local models never leave this computer.",
                      "Keys live in %s on this computer only and are never shown in the window." % (data_dir / SECRETS),
                      "The two machines talk over a signed link only when you linked them (Settings > Machines)."]}


def _manifest(z: zipfile.ZipFile) -> dict:
    try:
        data = json.loads(z.read("manifest.json").decode("utf-8"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) and data.get("format") == FORMAT else {}


def backup(data_dir: Path, workspace: Path, dest: Path | None = None, include_secrets: bool = False,
           label: str = "", version: str = "") -> dict:
    data_dir, workspace = Path(data_dir), Path(workspace)
    dest = Path(dest) if dest else backup_dir()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "loki-backup-%s%s.zip" % (stamp, ("-" + "".join(c for c in label if c.isalnum() or c in "-_")[:20]) if label else "")
    target = dest / name
    tmp = target.with_suffix(".part")
    count = total = skipped = 0
    dest_res = dest.resolve()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, prefix in ((data_dir, "data"), (workspace / ".loki", "workspace-loki")):
            for path, size in _walk(root):
                rel = path.relative_to(root)
                if dest_res == path.parent.resolve() or dest_res in path.resolve().parents:
                    continue                      # never back up the backups
                if rel.parts[0] == SECRETS and not include_secrets:
                    continue
                if size > MAX_FILE:
                    skipped += 1
                    continue
                try:
                    z.write(path, "%s/%s" % (prefix, rel.as_posix()))
                except OSError:
                    skipped += 1
                    continue
                count += 1
                total += size
        z.writestr("manifest.json", json.dumps({"format": FORMAT, "version": 1, "created": time.time(),
                                                "machine": platform.node(), "os": platform.system(),
                                                "loki": version, "files": count, "bytes": total,
                                                "secrets": bool(include_secrets), "label": label}, indent=1))
    tmp.replace(target)
    return {"ok": True, "path": str(target), "name": name, "files": count, "bytes": total, "skipped": skipped,
            "secrets": bool(include_secrets), "zip_bytes": target.stat().st_size}


def list_backups(dest: Path | None = None) -> list:
    dest = Path(dest) if dest else backup_dir()
    out = []
    if not dest.is_dir():
        return out
    for p in sorted(dest.glob("loki-backup-*.zip"), key=lambda q: q.stat().st_mtime, reverse=True)[:50]:
        try:
            with zipfile.ZipFile(p) as z:
                m = _manifest(z)
        except (zipfile.BadZipFile, OSError):
            m = {}
        out.append({"name": p.name, "path": str(p), "bytes": p.stat().st_size, "created": m.get("created", p.stat().st_mtime),
                    "files": m.get("files", 0), "secrets": bool(m.get("secrets")), "machine": m.get("machine", ""),
                    "valid": bool(m)})
    return out


def _safe_member(name: str) -> PurePosixPath | None:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name.split("/")[0]:
        return None
    return p


def restore(archive: Path, data_dir: Path, workspace: Path, dest: Path | None = None) -> dict:
    archive = Path(archive)
    if not archive.is_file():
        return {"ok": False, "error": "no backup at %s" % archive}
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        return {"ok": False, "error": "%s is not a zip file" % archive.name}
    with z:
        manifest = _manifest(z)
        if not manifest:
            return {"ok": False, "error": "%s is not a LOKI backup (no manifest)" % archive.name}
        plan = []
        for info in z.infolist():
            if info.is_dir() or info.filename == "manifest.json":
                continue
            rel = _safe_member(info.filename)
            if rel is None or len(rel.parts) < 2 or rel.parts[0] not in ("data", "workspace-loki"):
                return {"ok": False, "error": "the backup holds an unsafe path (%s) - nothing was restored" % info.filename}
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                return {"ok": False, "error": "the backup holds a link (%s) - nothing was restored" % info.filename}
            if rel.parts[1] in SKIP_DIRS and rel.parts[1] != "tools":
                continue
            base = Path(data_dir) if rel.parts[0] == "data" else Path(workspace) / ".loki"
            plan.append((info, base / Path(*rel.parts[1:]), base))
        safety = backup(data_dir, workspace, dest, include_secrets=True, label="before-restore")
        restored = 0
        for info, target, base in plan:
            if base.resolve() not in target.resolve().parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            restored += 1
    return {"ok": True, "restored": restored, "safety_backup": safety.get("name", ""),
            "from_machine": manifest.get("machine", ""), "secrets": bool(manifest.get("secrets")),
            "note": "Restart LOKI so everything reloads. Your state just before this is in %s." % safety.get("name", "")}


CLEARABLE = {"logs": "engine and job logs", "previews": "chat previews (artifacts)", "computer_log": "the computer-use log",
             "usage": "the usage ledger", "chats": "every chat"}


def clear(kind: str, data_dir: Path, clear_chats: Callable[[], None] | None = None,
          reset_usage: Callable[[], None] | None = None) -> dict:
    kind = str(kind or "").strip().lower()
    data_dir = Path(data_dir)
    if kind not in CLEARABLE:
        return {"ok": False, "error": "can clear: " + ", ".join(CLEARABLE)}
    removed = 0
    if kind == "chats":
        if clear_chats is None:
            return {"ok": False, "error": "the engine cannot clear chats here"}
        clear_chats()
        return {"ok": True, "cleared": CLEARABLE[kind]}
    if kind == "usage":
        if reset_usage is not None:
            reset_usage()
        else:
            (data_dir / "usage.jsonl").unlink(missing_ok=True)
        return {"ok": True, "cleared": CLEARABLE[kind]}
    targets = {"logs": [data_dir / "logs", *(data_dir / "jobs").glob("*.log")],
               "previews": [data_dir / "artifacts"],
               "computer_log": [data_dir / "computer_log.jsonl"]}[kind]
    for t in targets:
        try:
            if t.is_dir() and not t.is_symlink():
                for p, _s in list(_walk(t)):
                    p.unlink()
                    removed += 1
            elif t.is_file():
                t.unlink()
                removed += 1
        except OSError:
            pass
    return {"ok": True, "cleared": CLEARABLE[kind], "files": removed}
