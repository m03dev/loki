"""The task board and retries (owner 2026-10-27: "why hasnt windows been working by itself ... there should be a clear
finished jobs and tasks"). On the PC the autopilot started each request once; 159 of 281 teams ended "needs you" and
nothing noticed. Checked here, no model and no network (teams and jobs faked):
  - a failed request is counted, tried again after RETRY_AFTER_S told WHY the last try failed, given up after the last
    try - with the reason on the board; a request that worked is "done" with its answer and what it made
  - failures from before the board existed (> 48 h) are listed, not re-run; the inbox and retries come before goals
  - a standing goal that failed three times in a row rests
  - the board, its plain-text report, Try again now and Dismiss
  - OpenCode: a message too long for the Windows command line goes as an attached file

    python tests/test_task_board.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
os.environ["LOKI_AUTOPILOT"] = "on"
os.environ["LOKI_MACHINE_ROLE"] = "main"
os.environ["LOKI_AUTOPILOT_SLOTS"] = "3"
T0 = time.time()
import autopilot  # noqa: E402
import opencode_engine  # noqa: E402
import task_board  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


class Clock:
    def __init__(self, t=2_000_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


TMP = Path(tempfile.mkdtemp(prefix="loki-board-"))
REPOD = TMP / "repo"
REPOD.mkdir()
WS = TMP / "ws"
(WS / "images").mkdir(parents=True)
(REPOD / "LOKI_TASKS.md").write_text("""# tasks
## Requests

- [ ] [loki] make a knight picture
- [ ] [loki] make a dragon model

## Always

- [loki] draw a sprite
""", encoding="utf-8")

TEAMS: dict = {}
JOBS: dict = {}
STARTS: list = []
clock = Clock()


def start_team(text):
    tid = "t%d" % (len(TEAMS) + 1)
    jid = "j%d" % (len(JOBS) + 1)
    TEAMS[tid] = {"id": tid, "goal": text, "status": "working", "verdict": "", "finished": 0, "jobs": {"builder": jid},
                  "workspace": str(WS), "stage": "build"}
    JOBS[jid] = {"id": jid, "status": "working", "output": ""}
    STARTS.append(text)
    return "started team %s (Builder) on %s." % (tid, WS)


def finish(tid, ok, answer):
    t = TEAMS[tid]
    t.update(status="done", finished=clock(), verdict="verified: every check passed" if ok else "needs you: Builder could not finish (see the board)")
    JOBS[t["jobs"]["builder"]].update(status="done" if ok else "failed", output=answer)


agent = types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=lambda tid: TEAMS.get(tid)), WORKSPACE=str(WS), DATA_DIR=str(TMP / "data"))
state = types.SimpleNamespace(jobs=types.SimpleNamespace(store=types.SimpleNamespace(get=lambda jid: JOBS.get(jid), all=lambda: list(JOBS.values()))),
                              last_request_at=0.0, try_busy=lambda: ["x"], release_busy=lambda h: None)
auto = autopilot.Autopilot(data_dir=TMP / "data", repo=REPOD, clock=clock, agent=agent, state=state, start_team=start_team)

auto.duty_inbox()
check("both requests start", len(STARTS) == 2, STARTS)
knight = next(k for k, v in auto.data["started"].items() if "knight" in v["text"])
dragon = next(k for k, v in auto.data["started"].items() if "dragon" in v["text"])
check("the board says they are working", {r["status"] for r in auto.board()["rows"]} == {"running"})

clock.t += 300
(WS / "images" / "knight.png").write_bytes(b"\x89PNG fake")
os.utime(WS / "images" / "knight.png", (clock.t, clock.t))
finish(auto.data["started"][knight]["team"], True, "DONE: drew images/knight.png")
finish(auto.data["started"][dragon]["team"], False, "BLOCKED: NOT DONE - OpenCode stopped: The command line is too long.")
check("settle counts both", auto.settle() == 2)
board = {r["id"]: r for r in auto.board()["rows"]}
check("the knight is finished", board[knight]["status"] == "done" and board[knight]["summary"] == "Done and checked.", board[knight])
check("... with its answer", "knight.png" in board[knight]["answer"])
check("... and what it made", board[knight]["files"] == ["images/knight.png"], board[knight]["files"])
check("the dragon failed and will be tried again", board[dragon]["status"] == "retrying", board[dragon]["status"])
check("... and the board says why", "command line is too long" in board[dragon]["why"], board[dragon]["why"])
check("settle never counts a team twice", auto.settle() == 0)

clock.t += task_board.RETRY_AFTER_S + 5
n = len(STARTS)
auto.duty_always()
check("once its next try is due, a request comes before standing goals", len(STARTS) == n, STARTS[n:])
auto.duty_inbox()
check("the next try starts when it is due", len(STARTS) == n + 1 and "dragon" in STARTS[-1], STARTS[-1:])
check("... told why the last try failed", "command line is too long" in STARTS[-1] and "Try 2 of 3" in STARTS[-1], STARTS[-1][-300:])
check("... the board counts it", {r["id"]: r for r in auto.board()["rows"]}[dragon]["tries"] == 2)

for attempt in (2, 3):
    clock.t += 60
    finish(auto.data["started"][dragon]["team"], False, "BLOCKED: no tool ran")
    auto.settle()
    if attempt == 2:
        clock.t += task_board.RETRY_AFTER_S + 5
        auto.duty_inbox()
row = {r["id"]: r for r in auto.board()["rows"]}[dragon]
check("after the last try it is failed - needs you (not silently dropped)", row["status"] == "failed" and row["tries"] == 3, row)
n = len(STARTS)
clock.t += task_board.RETRY_AFTER_S * 3
auto.duty_inbox()
check("... and is not started a fourth time on its own", len(STARTS) == n)
check("Try again now gives it one more", auto.retry(dragon))
auto.duty_inbox()
check("... at once", len(STARTS) == n + 1 and "dragon" in STARTS[-1])
check("Dismiss takes a row off", auto.dismiss(knight) and knight not in {r["id"] for r in auto.board()["rows"]})

path = auto.write_board()
text = Path(path).read_text(encoding="utf-8") if path else ""
check("the plain-text report is written", path.endswith("tasks.md") and "make a dragon model" in text, path)

# standing goals rest after three failures in a row
goals = {}
for i in range(3):
    task_board.note_goal(goals, "draw a sprite", False, 100.0 + i)
check("a goal that failed 3 times in a row rests", task_board.goal_resting(goals, "draw a sprite", 104.0))
task_board.note_goal(goals, "draw a sprite", True, 30000.0)
check("... and is back after one success", not task_board.goal_resting(goals, "draw a sprite", 30001.0))

# old failures: listed, not re-run
auto2 = autopilot.Autopilot(data_dir=TMP / "old", repo=REPOD, clock=clock, agent=agent, state=state, start_team=start_team)
auto2.data["started"]["oldkey"] = {"text": "make a knight picture", "t": clock.t - 5 * 86400, "team": "old1", "open": False}
TEAMS["old1"] = {"id": "old1", "status": "done", "verdict": "needs you: Builder could not finish", "finished": clock.t - 5 * 86400,
                 "jobs": {}, "workspace": str(WS)}
auto2.settle()
check("a failure from days ago is not re-run", (auto2.data["attempts"]["oldkey"] or {}).get("given_up") is True)

# OpenCode on Windows: long messages go as a file
short = opencode_engine.long_message_file("hello", str(WS), limit=100)
long_ = opencode_engine.long_message_file("x" * 500, str(WS), limit=100)
check("a short message stays on the command line", short == "")
check("a long one is written to a file in the workspace", long_ and Path(long_).read_text(encoding="utf-8") == "x" * 500, long_)
seen = {}


class FakeProc:
    def __init__(self, argv, **kw):
        seen["argv"] = argv
        import io
        self.stdout = io.StringIO("")
        self.stderr = None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


os.environ["LOKI_OC_ARGV_MAX"] = "100"
opencode_engine.ARGV_MAX = 100
opencode_engine.run_turn("y" * 400, str(WS), exe="opencode", config_path="c.json", env={}, popen=FakeProc)
argv = seen.get("argv") or []
check("run_turn attaches it with --file and a short pointer", "--file" in argv and len(argv[-1]) < 300 and "y" * 400 not in " ".join(argv), argv[-3:])
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
