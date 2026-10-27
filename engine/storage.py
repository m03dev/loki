"""Storage: what LOKI keeps, what it may throw away, and a budget it stays inside (owner 2026-10-27: "what are we doing
about data management i dont have that much space we cant keep this stuff its just for testing and later people will
need some sort of solutions if this is going to be a real app").

Measured on the PC (2026-10-27): 38 finished-job worktrees of LOKI's own code (~80 MB each, ~3 GB), an npm project
with node_modules the agents built in the Home workspace, every 3D model saved 4-6 times (identical "LOD" copies,
textures in three folders), a 30 MB 4x upscale nobody asked for, logs and job folders that only grow. Nothing ever left.

Modelled on how others do it - Hugging Face's cache (scan, then a delete strategy that shows the space it frees and
runs exactly that), `docker system df` / `prune` (usage per kind; regenerable caches go first), Photos' "Recently
Deleted" and Lightroom's rejected flag (a cleanup goes to a trash that empties itself later; what you liked is kept):

  scan()      usage per CATEGORY (and the free space on the drive) - nothing is changed
  plan()      what may go, item by item, with why and how much it frees, by the RULES below; a plan has an id
  clean(id)   runs exactly that plan: regenerable things are deleted, your outputs go to the trash
              (<data>/storage_trash/<batch>/ + a manifest), restore(batch) puts them back
  auto        every 6 h (the autopilot): ONLY regenerable things - never the owner's work (owner 2026-10-27: "i hope
              you didnt make any system that automatically deletes things without my permission cache and little
              running things are fine but not real stuff"). The safe regenerable rules always; download caches too
              when LOKI is over its budget (LOKI_STORAGE_BUDGET_GB, default 20) or the drive is low (LOKI_MIN_FREE_GB,
              default 25). It never moves anything of the owner's to the trash and never empties the trash - the owner
              does both in Lab > Storage. LOKI_STORAGE_AUTO=off|safe|budget (default budget)

Rules (never anything you liked or kept, never a folder outside LOKI's data and workspace; "manual" = only when the
owner runs that plan, never automatically):
  worktrees     LOKI's code checked out for a finished improve job                     regenerable  safe
  job_runs      a finished job's log and run folder, older than 7 days                regenerable  safe
  agent_junk    caches agents left in the workspace (node_modules, __pycache__,       regenerable  safe
                .next, coverage, *.log, *.tmp, .loki/messages) older than 3 days
  caches        pip / uv / npm / Hugging Face download caches in LOKI's big/ folder    regenerable  budget
  builds        dist/ and build/ folders in the workspace (could be an export)         yours        manual
  rejected      what you deleted on Home (the workspace trash/), older than 7 days     yours        manual
  drafts        what standing goals and tests made, older than LOKI_DRAFT_DAYS (7)     yours        manual
                and not liked or kept
  duplicates    byte-identical copies of an output (the newest copy stays)             yours        manual
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

DAY = 86400.0
OUTPUT_DIRS = ("images", "sprites", "models", "renders", "turnarounds", "music", "audio", "voice", "video", "videos",
               "scenes", "pipeline", "library", "brand", "qa")
JUNK_DIRS = {"node_modules", ".pytest_cache", "__pycache__", ".next", ".parcel-cache", "coverage", ".turbo"}
BUILD_DIRS = {"dist", "build"}     # a build's output may be the owner's export: only ever on the owner's say
JUNK_FILES = (".log", ".tmp")
CACHE_DIRS = ("uv-cache", "pip-cache", "npm-cache", "huggingface", "torch")
CATEGORIES = {
    "worktrees": ("LOKI's code for finished improve jobs", "regenerable", "safe"),
    "job_runs": ("logs and folders of finished jobs", "regenerable", "safe"),
    "agent_junk": ("caches agents left (node_modules, __pycache__, logs)", "regenerable", "safe"),
    "caches": ("download caches (pip, uv, npm, models)", "regenerable", "budget"),
    "builds": ("dist / build folders in the workspace", "yours", "manual"),
    "rejected": ("pictures and models you deleted on Home", "yours", "manual"),
    "drafts": ("what standing goals and tests made", "yours", "manual"),
    "duplicates": ("identical copies of the same output", "yours", "manual"),
}
_lock = threading.Lock()
_cache: dict = {}


def _env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return float(default)


def budget_bytes() -> int:
    return int(_env("LOKI_STORAGE_BUDGET_GB", 20) * 1e9)


def min_free_bytes() -> int:
    return int(_env("LOKI_MIN_FREE_GB", 25) * 1e9)


def auto_mode() -> str:
    m = str(os.getenv("LOKI_STORAGE_AUTO", "budget")).strip().lower()
    return m if m in ("off", "safe", "budget") else "budget"


def size_of(path: Path, deadline: float | None = None) -> int:
    """Bytes under path (files only, links not followed). Stops counting at the deadline (a huge tree)."""
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total, stack = 0, [path]
    while stack:
        if deadline and time.time() > deadline:
            break
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def newest_mtime(path: Path, limit: int = 2000) -> float:
    """The newest change under path (cheap: the first `limit` entries)."""
    try:
        best = path.stat().st_mtime
    except OSError:
        return 0.0
    if path.is_dir():
        n = 0
        for p in path.rglob("*"):
            n += 1
            if n > limit:
                break
            try:
                best = max(best, p.stat().st_mtime)
            except OSError:
                continue
    return best


def disk_free(path: Path) -> tuple:
    try:
        u = shutil.disk_usage(str(path))
        return u.free, u.total
    except OSError:
        return 0, 0


def _sha(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ what is kept
UNKNOWN = "*"     # in kept_paths(): the owner's likes could not be read - nothing of theirs is offered


def kept_paths(workspace: Path, data_dir: Path) -> set:
    """Relative workspace paths that are never cleaned: liked (thumbs up), pinned here (storage_keep.json)."""
    keep = set()
    try:
        import image_feedback  # pylint: disable=import-outside-toplevel
        for rel, r in (image_feedback.ratings(workspace, data_dir) or {}).items():
            if int(r.get("rating") or 0) > 0:
                keep.add(str(rel).replace("\\", "/"))
    except Exception:  # noqa: BLE001 - the likes could not be read: fail CLOSED (UNKNOWN = offer none of the owner's
        keep.add(UNKNOWN)   # files), never "nothing is liked" (2026-10-27: a liked picture showed up as a draft)
    for name in OUTPUT_DIRS:   # a picture's own sidecar (<folder>/.meta/<file>.json) saying liked - a second record
        meta = Path(workspace) / name / ".meta"
        if not meta.is_dir():
            continue
        for m in meta.glob("*.json"):
            try:
                if json.loads(m.read_text(encoding="utf-8")).get("liked") is True:
                    keep.add("%s/%s" % (name, m.name[:-5]))
            except (OSError, ValueError, AttributeError):
                continue
    try:
        keep |= set(json.loads((data_dir / "storage_keep.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return keep


def keep(data_dir: Path, rel: str, on: bool = True) -> list:
    path = Path(data_dir) / "storage_keep.json"
    try:
        cur = set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        cur = set()
    (cur.add if on else cur.discard)(str(rel).replace("\\", "/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(cur), indent=1), encoding="utf-8")
    return sorted(cur)


def draft_paths(data_dir: Path) -> dict:
    """{relative path: finished time} of files that standing goals made (the task board's rows of kind "goal")."""
    out = {}
    try:
        board = json.loads((data_dir / "task_board.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for row in board.get("rows") or []:
        if row.get("kind") != "goal":
            continue
        for rel in row.get("files") or []:
            out[str(rel)] = float(row.get("finished") or row.get("started") or 0)
    return out


# ------------------------------------------------------------------ the rules
class Ctx:
    def __init__(self, data_dir: Path, workspace: Path | None, now: float | None = None,
                 job_status: Callable[[str], str] | None = None, deadline_s: float = 20.0):
        self.data = Path(data_dir)
        self.ws = Path(workspace) if workspace else None
        self.now = time.time() if now is None else now
        self.job_status = job_status or (lambda job_id: "")
        self.deadline = time.time() + deadline_s
        self.kept = kept_paths(self.ws, self.data) if self.ws else set()

    def item(self, cat: str, path: Path, why: str, size: int | None = None, rel: str = "") -> dict:
        size = size_of(path, self.deadline) if size is None else size
        return {"category": cat, "path": str(path), "rel": rel, "size": size, "why": why,
                "action": "delete" if CATEGORIES[cat][1] == "regenerable" else "trash"}


def _uncommitted(path: Path) -> bool:
    """A worktree with changes nobody committed: never cleaned (its branch would keep the commits, not those)."""
    if not (path / ".git").exists():
        return False
    try:
        r = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                           text=True, timeout=30, creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        return True     # cannot tell: keep it
    return r.returncode != 0 or bool(r.stdout.strip())


def rule_worktrees(c: Ctx) -> list:
    root = c.data / "worktrees"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue    # _baseline_loki is the reference checkout new worktrees start from
        status = c.job_status(d.name)
        age = c.now - newest_mtime(d, 300)
        if status in ("queued", "starting", "working", "blocked"):
            continue
        if (status in ("done", "failed", "cancelled") or age > 2 * DAY) and not _uncommitted(d):
            out.append(c.item("worktrees", d, "improve job %s is %s" % (d.name, status or "gone (%d days old)" % (age // DAY))))
    return out


def rule_job_runs(c: Ctx) -> list:
    out = []
    for root in (c.data / "jobs", c.data / "opencode" / "jobs"):
        if not root.is_dir():
            continue
        for p in root.iterdir():
            job_id = p.name.split(".")[0]
            age = c.now - newest_mtime(p, 200)
            if age < 7 * DAY or c.job_status(job_id) in ("queued", "starting", "working", "blocked"):
                continue
            out.append(c.item("job_runs", p, "finished job, %d days old" % (age // DAY)))
    return out


def rule_agent_junk(c: Ctx) -> list:
    out = []
    if c.ws is None or not c.ws.is_dir():
        return out
    for p in c.ws.iterdir():
        age = c.now - newest_mtime(p, 300)
        if age < 3 * DAY:
            continue
        rel = p.name
        if p.is_dir() and p.name in JUNK_DIRS:
            out.append(c.item("agent_junk", p, "%s that an agent built in the workspace" % p.name, rel=rel))
        elif p.is_file() and p.suffix.lower() in JUNK_FILES:
            out.append(c.item("agent_junk", p, "a log an agent left", rel=rel))
    msgs = c.ws / ".loki" / "messages"
    if msgs.is_dir():
        for p in msgs.iterdir():
            if c.now - newest_mtime(p) > DAY:
                out.append(c.item("agent_junk", p, "a long message handed to an agent", rel=".loki/messages/" + p.name))
    return out


def rule_builds(c: Ctx) -> list:
    out = []
    if c.ws is None or not c.ws.is_dir():
        return out
    for p in c.ws.iterdir():
        if p.is_dir() and p.name in BUILD_DIRS and c.now - newest_mtime(p, 300) >= 3 * DAY:
            out.append(c.item("builds", p, "%s folder in the workspace (a build's output)" % p.name, rel=p.name))
    return out


def rule_caches(c: Ctx) -> list:
    out = []
    big = c.data / "big"
    for name in CACHE_DIRS:
        p = big / name
        if p.is_dir():
            out.append(c.item("caches", p, "%s - downloaded again when needed" % name))
    return out


def rule_rejected(c: Ctx) -> list:
    out = []
    if c.ws is None:
        return out
    root = c.ws / "trash"
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file() and c.now - p.stat().st_mtime > 7 * DAY:
            out.append(c.item("rejected", p, "you deleted it on Home %d days ago" % ((c.now - p.stat().st_mtime) // DAY),
                              rel=str(p.relative_to(c.ws)).replace("\\", "/")))
    return out


def rule_drafts(c: Ctx) -> list:
    out = []
    if c.ws is None:
        return out
    days = _env("LOKI_DRAFT_DAYS", 7)
    if UNKNOWN in c.kept:
        return out
    for rel, t in draft_paths(c.data).items():
        p = c.ws / rel
        if rel in c.kept or not p.is_file():
            continue
        made = max(t or 0, p.stat().st_mtime)      # the file's own age counts (a later run may have rewritten it)
        if c.now - made < days * DAY:
            continue
        out.append(c.item("drafts", p, "a standing goal made it %d days ago and nobody kept it" % ((c.now - made) // DAY), rel=rel))
    return out


def rule_duplicates(c: Ctx) -> list:
    out = []
    if c.ws is None or UNKNOWN in c.kept:
        return out
    by_size: dict = {}
    for name in OUTPUT_DIRS:
        root = c.ws / name
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if time.time() > c.deadline:
                break
            try:
                if p.is_file() and not p.name.endswith(".json") and p.stat().st_size >= 100_000:
                    by_size.setdefault(p.stat().st_size, []).append(p)
            except OSError:
                continue
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        groups: dict = {}
        for p in paths:
            try:
                groups.setdefault(_sha(p), []).append(p)
            except OSError:
                continue
        for same in groups.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for p in same[1:]:
                rel = str(p.relative_to(c.ws)).replace("\\", "/")
                if rel in c.kept:
                    continue
                out.append(c.item("duplicates", p, "identical to %s" % same[0].relative_to(c.ws).as_posix(), size=size, rel=rel))
    return out


RULES = {"builds": rule_builds, "worktrees": rule_worktrees, "job_runs": rule_job_runs, "agent_junk": rule_agent_junk, "caches": rule_caches,
         "rejected": rule_rejected, "drafts": rule_drafts, "duplicates": rule_duplicates}


# ------------------------------------------------------------------ scan / plan / clean
def scan(data_dir: Path, workspace: Path | None, deadline_s: float = 15.0) -> dict:
    """Usage per area (LOKI's data, its caches, the workspace outputs) and the drives' free space."""
    deadline = time.time() + deadline_s
    data_dir = Path(data_dir)
    areas = []

    def add(name, label, path):
        if path.exists():
            areas.append({"id": name, "label": label, "path": str(path), "size": size_of(path, deadline)})

    for sub, label in (("worktrees", "Code copies for improve jobs"), ("jobs", "Job logs"), ("opencode", "Agent sessions"),
                       ("big", "Downloads and caches"), ("comfyui", "ComfyUI and its models"), ("renders", "Farm renders"),
                       (".venv", "LOKI's Python"), ("storage_trash", "LOKI's trash")):
        add(sub, label, data_dir / sub)
    if workspace:
        ws = Path(workspace)
        for name in OUTPUT_DIRS:
            add("ws:" + name, "Workspace " + name, ws / name)
        add("ws:trash", "Workspace trash (deleted on Home)", ws / "trash")
        add("ws:node_modules", "node_modules an agent installed", ws / "node_modules")
    free, total = disk_free(data_dir)
    out = {"areas": sorted(areas, key=lambda a: -a["size"]), "total": sum(a["size"] for a in areas),
           "free": free, "disk": total, "budget": budget_bytes(), "min_free": min_free_bytes(), "auto": auto_mode()}
    if workspace:
        wfree, wtotal = disk_free(Path(workspace))
        if wtotal and wtotal != total:
            out.update(ws_free=wfree, ws_disk=wtotal)
    return out


def plan(data_dir: Path, workspace: Path | None, categories=None, job_status=None, now=None) -> dict:
    c = Ctx(data_dir, workspace, now=now, job_status=job_status)
    items = []
    for cat in (categories or list(RULES)):
        if cat in RULES:
            try:
                items += RULES[cat](c)
            except Exception as exc:  # noqa: BLE001 - one broken rule never stops the others
                items.append({"category": cat, "path": "", "size": 0, "why": "could not check: %s" % exc, "action": "none"})
    items = [i for i in items if i.get("path")]
    for i in items:
        i["id"] = hashlib.sha1(("%s|%s" % (i["category"], i["path"])).encode()).hexdigest()[:12]
    by_cat: dict = {}
    for i in items:
        b = by_cat.setdefault(i["category"], {"count": 0, "size": 0, "label": CATEGORIES[i["category"]][0],
                                              "kind": CATEGORIES[i["category"]][1], "when": CATEGORIES[i["category"]][2]})
        b["count"] += 1
        b["size"] += i["size"]
    pid = hashlib.sha1(json.dumps(sorted(i["id"] for i in items)).encode()).hexdigest()[:12]
    out = {"id": pid, "items": items, "categories": by_cat, "frees": sum(i["size"] for i in items), "t": time.time()}
    with _lock:
        _cache[pid] = out
    return out


def _inside(path: Path, roots: list) -> bool:
    try:
        rp = path.resolve()
    except OSError:
        return False
    for r in roots:
        try:
            rp.relative_to(Path(r).resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def _remove_worktree(path: Path, repo: Path | None) -> bool:
    if repo is None or not (Path(repo) / ".git").exists():
        return False
    try:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(path)], capture_output=True, timeout=60,
                       creationflags=0x08000000 if os.name == "nt" else 0)
        subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True, timeout=60,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        return False
    return not path.exists()


def clean(data_dir: Path, workspace: Path | None, plan_id: str, ids=None, repo: Path | None = None) -> dict:
    """Run exactly a plan made by plan() (all of it, or the item ids picked from it). Regenerable items are deleted;
    the owner's things go to <data>/storage_trash/<batch>/ with a manifest (restore()). Only inside LOKI's data folder
    and the workspace - anything else in a plan is refused."""
    with _lock:
        p = _cache.get(plan_id)
    if p is None:
        return {"ok": False, "error": "That plan is gone - look again (plans are kept until LOKI restarts)."}
    data_dir = Path(data_dir)
    roots = [data_dir] + ([Path(workspace)] if workspace else [])
    batch = time.strftime("%Y%m%d-%H%M%S")
    tdir = data_dir / "storage_trash" / batch
    manifest, done, freed, errors = [], [], 0, []
    for it in p["items"]:
        if ids and it["id"] not in ids:
            continue
        path = Path(it["path"])
        if not _inside(path, roots) or path.resolve() in [Path(r).resolve() for r in roots]:
            errors.append("%s: outside LOKI's folders - not touched" % path)
            continue
        if not path.exists():
            continue
        try:
            if it["category"] == "worktrees" and _remove_worktree(path, repo):
                pass
            elif it["action"] == "delete":
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            else:
                rel = it.get("rel") or path.name
                dest = tdir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
                manifest.append({"from": str(path), "to": str(dest), "size": it["size"], "category": it["category"]})
            done.append(it["id"])
            freed += it["size"]
        except OSError as exc:
            errors.append("%s: %s" % (path, exc))
    if manifest:
        (tdir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    _log(data_dir, {"t": time.time(), "batch": batch if manifest else "", "removed": len(done), "freed": freed, "errors": errors[:5]})
    return {"ok": not errors, "removed": len(done), "freed": freed, "batch": batch if manifest else "", "errors": errors[:10]}


def restore(data_dir: Path, batch: str) -> dict:
    tdir = Path(data_dir) / "storage_trash" / batch
    try:
        manifest = json.loads((tdir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "no such trash batch"}
    back, errors = 0, []
    for m in manifest:
        src, dst = Path(m["to"]), Path(m["from"])
        if not src.exists():
            continue
        if dst.exists():
            errors.append("%s is back already" % dst)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            back += 1
        except OSError as exc:
            errors.append(str(exc))
    if not errors:
        shutil.rmtree(tdir, ignore_errors=True)
    return {"ok": not errors, "restored": back, "errors": errors[:10]}


def trash(data_dir: Path) -> list:
    root = Path(data_dir) / "storage_trash"
    out = []
    if root.is_dir():
        for d in sorted(root.iterdir(), reverse=True):
            if d.is_dir():
                try:
                    n = len(json.loads((d / "manifest.json").read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    n = 0
                out.append({"batch": d.name, "items": n, "size": size_of(d), "t": d.stat().st_mtime})
    return out


def empty_trash(data_dir: Path, older_than_days: float | None = None, now: float | None = None) -> dict:
    days = _env("LOKI_TRASH_DAYS", 7) if older_than_days is None else older_than_days
    now = time.time() if now is None else now
    freed, gone = 0, 0
    for b in trash(data_dir):
        if now - b["t"] >= days * DAY:
            freed += b["size"]
            shutil.rmtree(Path(data_dir) / "storage_trash" / b["batch"], ignore_errors=True)
            gone += 1
    return {"emptied": gone, "freed": freed}


def _log(data_dir: Path, row: dict) -> None:
    try:
        with (Path(data_dir) / "storage_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def auto(data_dir: Path, workspace: Path | None, job_status=None, repo: Path | None = None) -> dict:
    """The autopilot's storage duty: safe rules always; budget rules only when over budget or low on space."""
    mode = auto_mode()
    if mode == "off":
        return {"ok": True, "skipped": "LOKI_STORAGE_AUTO=off"}
    # regenerable things only - never the owner's work, whatever the budget says (owner 2026-10-27)
    cats = [c for c, (_l, kind, when) in CATEGORIES.items() if when == "safe" and kind == "regenerable"]
    s = scan(data_dir, workspace, deadline_s=10)
    tight = s["total"] > s["budget"] or (s["free"] and s["free"] < s["min_free"]) or \
        (s.get("ws_free") is not None and s["ws_free"] < s["min_free"])
    if mode == "budget" and tight:
        cats += [c for c, (_l, kind, when) in CATEGORIES.items() if when == "budget" and kind == "regenerable"]
    p = plan(data_dir, workspace, cats, job_status=job_status)
    res = clean(data_dir, workspace, p["id"], repo=repo) if p["items"] else {"removed": 0, "freed": 0}
    # the trash is NOT emptied here: what is in it is the owner's, and only the owner empties it (Lab > Storage)
    res.update(tight=bool(tight), categories=cats)
    return res


def route(data_dir: Path, workspace: Path | None, method: str, path: str, body: dict, job_status=None, repo=None) -> tuple:
    """GET /storage (usage + the plan + the trash); POST /storage/clean {plan, ids?}, /storage/restore {batch},
    /storage/keep {path, on}, /storage/empty-trash."""
    if method == "GET":
        cats = [c for c in str(body.get("categories") or "").split(",") if c] or None
        p = plan(data_dir, workspace, cats, job_status=job_status)
        return 200, {"ok": True, "usage": scan(data_dir, workspace), "plan": p, "trash": trash(data_dir)}
    if path == "/storage/clean":
        return 200, clean(data_dir, workspace, str(body.get("plan") or ""), set(body.get("ids") or []) or None, repo=repo)
    if path == "/storage/restore":
        return 200, restore(data_dir, str(body.get("batch") or ""))
    if path == "/storage/keep":
        return 200, {"ok": True, "kept": keep(data_dir, str(body.get("path") or ""), bool(body.get("on", True)))}
    if path == "/storage/empty-trash":
        return 200, {"ok": True, **empty_trash(data_dir, 0)}
    return 404, {"ok": False, "error": "Unknown storage endpoint."}


if __name__ == "__main__":
    here = Path(os.getenv("LOKI_DATA") or Path(__file__).resolve().parent.parent / "harness_data")
    ws = Path(os.getenv("LOKI_WORKSPACE") or Path.home() / "LOKI Projects" / "Home")
    if sys.argv[1:2] == ["plan"]:
        pl = plan(here, ws)
        for k, v in pl["categories"].items():
            print("%-12s %5d items  %8.1f MB  %s" % (k, v["count"], v["size"] / 1e6, v["label"]))
        print("frees %.1f MB in all (nothing changed - this is the plan)" % (pl["frees"] / 1e6))
    else:
        s = scan(here, ws)
        for a in s["areas"]:
            print("%8.1f MB  %s" % (a["size"] / 1e6, a["label"]))
        print("free on the drive: %.1f GB of %.1f GB" % (s["free"] / 1e9, s["disk"] / 1e9))
