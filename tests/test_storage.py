"""engine/storage.py (owner 2026-10-27: "i dont have that much space we cant keep this stuff its just for testing ...
people will need some sort of solutions"). A fake LOKI data folder and workspace shaped like the PC's: finished-job
worktrees, old job logs, an agent's node_modules, a Home delete, standing-goal drafts, identical copies, a liked
picture. Checked: the scan, the plan (what, why, how much), that cleaning runs exactly the plan, that your things go to
a trash you can restore and regenerable things are deleted, that liked / kept / running / recent things and anything
outside LOKI's folders are never touched, and that auto only takes drafts and caches when over budget.

    python tests/test_storage.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
T0 = time.time()
import storage  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


ROOT = Path(tempfile.mkdtemp(prefix="loki-storage-"))
DATA, WS, OUTSIDE = ROOT / "harness_data", ROOT / "Home", ROOT / "owner-files"
OLD = time.time() - 12 * 86400


def put(path: Path, size: int = 1000, t: float | None = None, data: bytes | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else os.urandom(size))
    if t:
        os.utime(path, (t, t))
    return path


def age_tree(path: Path, t: float):
    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t))


put(DATA / "worktrees" / "_baseline_loki" / "engine" / "loki.py", 5000, OLD)
put(DATA / "worktrees" / "aaaa1111" / "engine" / "loki.py", 80_000, OLD); age_tree(DATA / "worktrees" / "aaaa1111", OLD)
put(DATA / "worktrees" / "bbbb2222" / "engine" / "loki.py", 80_000)            # its job is still working
put(DATA / "jobs" / "old1.log", 30_000, OLD)
put(DATA / "jobs" / "new1.log", 30_000)
put(DATA / "big" / "uv-cache" / "archive" / "x.whl", 200_000)
put(WS / "node_modules" / "jest" / "index.js", 150_000, OLD); age_tree(WS / "node_modules", OLD)
put(WS / "music_run.log", 4000, OLD)
put(WS / "trash" / "images" / "ugly.png", 60_000, OLD)
put(WS / "images" / "liked.png", 120_000, OLD)
put(WS / "images" / "draft-sprite.png", 120_000, OLD)
put(WS / "images" / "fresh.png", 120_000)
same = os.urandom(300_000)
put(WS / "models" / "hero.glb", data=same, t=OLD)
put(WS / "models" / "hero_lod0.glb", data=same, t=OLD + 60)
put(OUTSIDE / "my-scene.ma", 50_000, OLD)
(DATA / "task_board.json").write_text(json.dumps({"rows": [
    {"kind": "goal", "files": ["images/draft-sprite.png", "images/liked.png", "images/fresh.png"], "finished": OLD},
    {"kind": "request", "files": ["models/hero.glb"], "finished": OLD}]}), encoding="utf-8")
put(DATA / "feedback" / "ratings.jsonl", data=(json.dumps({"path": "images/liked.png", "rating": 1, "t": OLD}) + "\n").encode())
STATUS = {"aaaa1111": "done", "bbbb2222": "working", "old1": "done", "new1": "done"}


def js(job_id):
    return STATUS.get(job_id, "")


s = storage.scan(DATA, WS)
ids = {a["id"] for a in s["areas"]}
check("the scan measures LOKI's folders and the workspace", {"worktrees", "jobs", "big", "ws:images", "ws:node_modules"} <= ids, ids)
check("... and the drive's free space", s["free"] > 0 and s["disk"] >= s["free"])

p = storage.plan(DATA, WS, job_status=js)
by = {}
for it in p["items"]:
    by.setdefault(it["category"], []).append(Path(it["path"]).relative_to(ROOT).as_posix())
check("a finished job's code copy may go", by.get("worktrees") == ["harness_data/worktrees/aaaa1111"], by.get("worktrees"))
check("... not the baseline, not one whose job still runs", not any("_baseline" in x or "bbbb" in x for x in by.get("worktrees", [])))
check("old job logs may go, new ones stay", by.get("job_runs") == ["harness_data/jobs/old1.log"], by.get("job_runs"))
check("the node_modules an agent built and its logs may go", set(by.get("agent_junk", [])) == {"Home/node_modules", "Home/music_run.log"}, by.get("agent_junk"))
check("download caches may go", by.get("caches") == ["harness_data/big/uv-cache"], by.get("caches"))
check("what you deleted on Home a while ago may go", by.get("rejected") == ["Home/trash/images/ugly.png"], by.get("rejected"))
check("an old standing-goal draft may go", by.get("drafts") == ["Home/images/draft-sprite.png"], by.get("drafts"))
check("... never one you liked, never a fresh one", not any("liked" in x or "fresh" in x for x in by.get("drafts", [])))
check("an identical copy may go, the newest copy stays", by.get("duplicates") == ["Home/models/hero.glb"], by.get("duplicates"))
check("nothing outside LOKI's folders is ever in a plan", not any("owner-files" in x for v in by.values() for x in v))
check("the plan says how much it frees", p["frees"] == sum(i["size"] for i in p["items"]) and p["frees"] > 500_000, p["frees"])
check("scanning and planning changed nothing", (DATA / "worktrees" / "aaaa1111").exists() and (WS / "node_modules").exists())

# clean only part of the plan: the draft, the node_modules and the worktree
pick = {i["id"] for i in p["items"] if i["category"] in ("drafts", "agent_junk", "worktrees")}
res = storage.clean(DATA, WS, p["id"], ids=pick, repo=None)
check("cleaning runs exactly what was picked", res["removed"] == len(pick) and not (WS / "node_modules").exists()
      and not (WS / "images" / "draft-sprite.png").exists() and (DATA / "jobs" / "old1.log").exists(), res)
check("regenerable things are deleted, yours go to the trash", res["batch"] and
      (DATA / "storage_trash" / res["batch"] / "images" / "draft-sprite.png").is_file()
      and not list((DATA / "storage_trash" / res["batch"]).rglob("index.js")), res)
check("a code copy goes even without git (deleted)", not (DATA / "worktrees" / "aaaa1111").exists())
check("liked and fresh pictures are still there", (WS / "images" / "liked.png").is_file() and (WS / "images" / "fresh.png").is_file())
check("the trash lists the batch", storage.trash(DATA)[0]["batch"] == res["batch"])
back = storage.restore(DATA, res["batch"])
check("restore puts your draft back", back["restored"] == 1 and (WS / "images" / "draft-sprite.png").is_file(), back)
check("an unknown plan is refused", not storage.clean(DATA, WS, "nope")["ok"])

# a plan that somehow points outside is refused
p2 = storage.plan(DATA, WS, ["rejected"], job_status=js)
p2["items"].append({"id": "evil", "category": "drafts", "path": str(OUTSIDE / "my-scene.ma"), "size": 1, "action": "trash", "rel": "x"})
res2 = storage.clean(DATA, WS, p2["id"], repo=None)
check("a path outside LOKI's folders is never touched", (OUTSIDE / "my-scene.ma").is_file() and any("outside" in e for e in res2["errors"]), res2)

# a code copy with uncommitted work is never planned (its branch keeps commits, not those)
import subprocess  # noqa: E402
wt = DATA / "worktrees" / "cccc3333"
put(wt / "a.py", 100, OLD)
if subprocess.run(["git", "init", "-q", str(wt)], capture_output=True).returncode == 0:
    subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "add", "a.py"], capture_output=True)
    subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], capture_output=True)
    (wt / "a.py").write_text("changed, not committed", encoding="utf-8")
    age_tree(wt, OLD)
    STATUS["cccc3333"] = "done"
    check("a finished job's code copy with uncommitted work is kept", not any("cccc3333" in i["path"] for i in storage.plan(DATA, WS, ["worktrees"], job_status=js)["items"]))

# keep: pinning a draft keeps it out of every plan
storage.keep(DATA, "images/draft-sprite.png")
check("a picture you keep never shows up as a draft", not any(i["category"] == "drafts" for i in storage.plan(DATA, WS, ["drafts"])["items"]))

# auto: safe rules always, drafts/caches only when over budget
os.environ["LOKI_STORAGE_BUDGET_GB"] = "1000"
os.environ["LOKI_MIN_FREE_GB"] = "0"
put(DATA / "jobs" / "old2.log", 30_000, OLD)
STATUS["old2"] = "done"
a = storage.auto(DATA, WS, job_status=js)
check("auto within budget: the safe rules only", "caches" not in a["categories"] and not (DATA / "jobs" / "old2.log").exists()
      and (DATA / "big" / "uv-cache").exists(), a)
# owner 2026-10-27: "i hope you didnt make any system that automatically deletes things without my permission cache
# and little running things are fine but not real stuff" - auto never touches the owner's work, even over budget
mine = [put(WS / "images" / "old-goal-draft.png", 50_000, OLD), put(WS / "trash" / "images" / "deleted-long-ago.png", 50_000, OLD),
        put(WS / "dist" / "my-game-export.html", 50_000, OLD), put(WS / "images" / "copy-a.png", 10, OLD, b"same"),
        put(WS / "images" / "copy-b.png", 10, OLD, b"same")]
age_tree(WS / "dist", OLD)
old_batch = storage.trash(DATA)
for b in old_batch:
    os.utime(DATA / "storage_trash" / b["batch"], (OLD, OLD))
os.environ["LOKI_STORAGE_BUDGET_GB"] = "0.000001"
a = storage.auto(DATA, WS, job_status=js)
check("auto over budget: caches go too", a["tight"] and "caches" in a["categories"] and not (DATA / "big" / "uv-cache").exists(), a)
check("... and only regenerable things: never drafts, duplicates, Home deletes or build output",
      set(a["categories"]) <= {"worktrees", "job_runs", "agent_junk", "caches"}, a["categories"])
check("... every one of the owner's files is still where it was (draft, old Home delete, dist export, copies)",
      all(f.exists() for f in mine), [str(f) for f in mine if not f.exists()])
check("... the trash is not emptied by auto, however old (only the owner empties it)",
      len(storage.trash(DATA)) == len(old_batch) and "trash" not in a, (old_batch, storage.trash(DATA)))
manual = {i["category"] for i in storage.plan(DATA, WS, job_status=js)["items"]}
check("the owner's own plan (Lab > Storage) still offers them, to choose", {"builds", "rejected"} <= manual, manual)
e = storage.empty_trash(DATA)
check("the owner's Empty trash removes trash older than a week", e["emptied"] == len(old_batch) and not storage.trash(DATA), e)
_saved_fb = sys.modules.get("image_feedback")
sys.modules["image_feedback"] = None          # the likes cannot be read (a broken install)
try:
    blind = {i["category"] for i in storage.plan(DATA, WS, ["drafts", "duplicates"], job_status=js)["items"]}
finally:
    if _saved_fb is not None:
        sys.modules["image_feedback"] = _saved_fb
    else:
        sys.modules.pop("image_feedback", None)
check("when the owner's likes cannot be read, none of their files is offered (fails closed - a liked picture once "
      "showed up as a draft)", not blind, blind)
os.environ["LOKI_STORAGE_AUTO"] = "off"
check("LOKI_STORAGE_AUTO=off does nothing", storage.auto(DATA, WS).get("skipped"))
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
