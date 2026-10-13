"""Offline tests for background jobs (addons/loki/harness/workers.py).

No herdr, Docker, cua or coding CLI needed: herdr and cua are faked at their boundary,
and the local backend runs a tiny fake agent script for real.

    python tests/test_workers.py
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "loki" / "harness"))
sys.path.insert(0, str(REPO / "addons" / "loki"))

import workers  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (detail,)))


def section(title: str) -> None:
    print("\n" + title)


TMP = Path(tempfile.mkdtemp(prefix="loki-jobs-test-"))


class FakeBackend(workers.Backend):
    name = "fake"

    def __init__(self, ok=True, script=None):
        self.ok = ok
        self.script = script or ["working", "done"]
        self.started, self.stopped, self.polls = [], [], {}

    def available(self):
        return self.ok, "fake"

    def start(self, job):
        self.started.append(job["id"])
        return {"status": "working", "handle": {"x": 1}}

    def poll(self, job):
        n = self.polls.get(job["id"], 0)
        self.polls[job["id"]] = n + 1
        return {"status": self.script[min(n, len(self.script) - 1)], "output": "tick %d" % n}

    def stop(self, job):
        self.stopped.append(job["id"])


def make_sup(backends, **kw):
    d = Path(tempfile.mkdtemp(dir=TMP))
    store = workers.JobStore(d / "jobs.json")
    prep = kw.pop("prep", lambda job, data: (job["workspace"], "direct"))
    return workers.Supervisor(store, backends, d, workspace_preparer=prep, **kw), d


# ------------------------------------------------------------------ validation
section("job validation")
sup, _ = make_sup({"local": FakeBackend(), "herdr": FakeBackend(), "cua": FakeBackend()})
ws = str(TMP)


def rejects(spec, text):
    try:
        sup.create(spec)
        return False
    except ValueError as exc:
        return text in str(exc)


check("an empty job is refused", rejects({"backend": "local", "workspace": ws}, "needs a prompt"))
check("raw commands are refused on the host", rejects(
    {"backend": "local", "workspace": ws, "commands": ["rm -rf /"]}, "virtual computer"))
check("raw commands are refused on herdr", rejects(
    {"backend": "herdr", "workspace": ws, "prompt": "x", "commands": "ls"}, "virtual computer"))
check("an unknown agent is refused", rejects(
    {"backend": "local", "workspace": ws, "prompt": "x", "agent": "bash"}, "agent must be"))
check("an unknown backend is refused", rejects({"backend": "ssh", "prompt": "x"}, "unknown backend"))
check("a missing workspace is refused", rejects(
    {"backend": "local", "workspace": str(TMP / "nope"), "prompt": "x"}, "existing folder"))
check("an oversized prompt is refused", rejects(
    {"backend": "local", "workspace": ws, "prompt": "x" * 20000}, "longer than"))
job = sup.create({"backend": "cua", "commands": "echo hi\n\nuname -a"})
check("commands are accepted on cua and split by line", job["commands"] == ["echo hi", "uname -a"])
job = sup.create({"backend": "local", "workspace": ws, "prompt": "fix it", "timeout_s": 5})
check("timeouts are clamped to at least 30s", job["timeout_s"] == 30)
check("a new job is queued", job["status"] == "queued")
check("the job store persists to disk",
      any(j["id"] == job["id"] for j in json.loads((Path(sup.store.path)).read_text())["jobs"]))

# ------------------------------------------------------------------ supervisor
section("supervisor")
fake = FakeBackend(script=["working", "working", "done"])
sup, _ = make_sup({"local": fake}, limits={"local": 1})
a = sup.create({"backend": "local", "workspace": ws, "prompt": "a"})
b = sup.create({"backend": "local", "workspace": ws, "prompt": "b"})
sup.tick()
check("the limit starts only one job per backend", fake.started == [a["id"]])
check("the second job waits in the queue", sup.store.get(b["id"])["status"] == "queued")
for _ in range(4):
    sup.tick()
check("a finished job is marked done", sup.store.get(a["id"])["status"] == "done")
check("the queued job starts when a slot frees", b["id"] in fake.started)
check("output tails are recorded", sup.store.get(a["id"])["output"].startswith("tick"))
check("finish time is recorded", sup.store.get(a["id"])["finished"] > 0)

fake = FakeBackend(script=["working"])
sup, _ = make_sup({"local": fake})
c = sup.create({"backend": "local", "workspace": ws, "prompt": "c"})
sup.tick()
sup.cancel(c["id"])
check("cancel stops the backend and marks it cancelled",
      fake.stopped == [c["id"]] and sup.store.get(c["id"])["status"] == "cancelled")
check("cancelling twice is harmless", sup.cancel(c["id"])["status"] == "cancelled")

fake = FakeBackend(script=["working"])
sup, _ = make_sup({"local": fake})
t = sup.create({"backend": "local", "workspace": ws, "prompt": "t"})
sup.tick()
sup.store.update(t["id"], started=time.time() - 9999)
sup.tick()
job = sup.store.get(t["id"])
check("a job past its time limit is stopped and failed",
      job["status"] == "failed" and "timed out" in job["error"] and t["id"] in fake.stopped)

sup, _ = make_sup({"local": FakeBackend(ok=False)})
u = sup.create({"backend": "local", "workspace": ws, "prompt": "u"})
sup.tick()
check("an unavailable backend fails the job with the reason",
      "unavailable" in sup.store.get(u["id"])["error"])


class Exploding(FakeBackend):
    def poll(self, job):
        raise RuntimeError("boom")


sup, _ = make_sup({"local": Exploding()})
e = sup.create({"backend": "local", "workspace": ws, "prompt": "e"})
sup.tick(); sup.tick()
check("a crashing backend fails the job, not the supervisor",
      sup.store.get(e["id"])["status"] == "failed" and "boom" in sup.store.get(e["id"])["error"])

status = sup.status()
check("status lists backends, jobs and counts",
      "local" in status["backends"] and status["jobs"] and status["counts"]["failed"] == 1)
check("presented jobs hide the raw handle", "handle" not in status["jobs"][0])
sup.start()
check("the supervisor runs on a background thread", sup.running())
sup.stop()

store = workers.JobStore(Path(tempfile.mkdtemp(dir=TMP)) / "j.json")
for i in range(5):
    store.add({"id": "f%d" % i, "status": "done", "created": i})
store.add({"id": "live", "status": "working", "created": 9})
store.remove_finished(keep=2)
ids = [j["id"] for j in store.all()]
check("clearing keeps the newest finished jobs and every live one", ids == ["f3", "f4", "live"])

# ------------------------------------------------------------------ agent argv
section("agent command lines")
argv = workers.agent_argv("claude-code", "do it", env={})
check("Claude Code runs headless with acceptEdits, never bypass",
      argv[:3] == ["claude", "--permission-mode", "acceptEdits"] and argv[-2:] == ["-p", "do it"])
check("LOKI_JOB_CLAUDE_MODE overrides the mode",
      workers.agent_argv("claude-code", "x", env={"LOKI_JOB_CLAUDE_MODE": "plan"})[2] == "plan")
check("Codex runs in its workspace-write sandbox",
      workers.agent_argv("codex", "x")[:4] == ["codex", "exec", "--sandbox", "workspace-write"])
check("interactive argv has no prompt", "x" not in workers.agent_argv("claude-code", "x", interactive=True))

# ------------------------------------------------------------------ local backend (real process)
section("local backend")
bin_dir = TMP / "bin"
bin_dir.mkdir()
if sys.platform == "win32":
    fake_claude = bin_dir / "claude.cmd"
    fake_claude.write_text("@echo fake agent %*\r\n@echo done > made.txt\r\n", encoding="utf-8")
else:
    fake_claude = bin_dir / "claude"
    fake_claude.write_text('#!/bin/sh\necho "fake agent $*"\necho done > made.txt\n', encoding="utf-8")
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC)
which = lambda name: str(fake_claude) if name == "claude" else None  # noqa: E731
local = workers.LocalBackend(TMP / "localdata", which=which)
check("local is available when an agent CLI is installed", local.available()[0])
work = TMP / "work"
work.mkdir()
sup, _ = make_sup({"local": local})
j = sup.create({"backend": "local", "workspace": str(work), "prompt": "hello there", "isolate": False})
sup.tick()
for _ in range(50):
    sup.tick()
    if sup.store.get(j["id"])["status"] in workers.FINAL:
        break
    time.sleep(0.1)
job = sup.store.get(j["id"])
check("the agent process ran to completion", job["status"] == "done" and job["exit_code"] == 0, job)
check("its output was captured", "fake agent" in job["output"] and "hello there" in job["output"], job["output"])
check("it ran in the job's folder", (work / "made.txt").is_file())
check("local is unavailable with no agent installed",
      not workers.LocalBackend(TMP, which=lambda n: None).available()[0])

# ------------------------------------------------------------------ worktree isolation
section("worktree isolation")
repo = TMP / "repo"
repo.mkdir()
git_ok = subprocess.run(["git", "--version"], capture_output=True).returncode == 0
if git_ok:
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    (repo / "a.txt").write_text("my uncommitted edit")
    run_dir, note = workers.prepare_workspace({"id": "abc12345", "workspace": str(repo), "isolate": True},
                                              TMP / "wtdata")
    check("an isolated job gets its own worktree", Path(run_dir, "a.txt").read_text() == "a", note)
    check("on its own branch", "loki/job-abc12345" in subprocess.run(
        ["git", "branch"], cwd=repo, capture_output=True, text=True).stdout)
    check("the user's uncommitted work is untouched", (repo / "a.txt").read_text() == "my uncommitted edit")
plain, note = workers.prepare_workspace({"id": "x", "workspace": str(work), "isolate": True}, TMP)
check("a non-git folder is used directly (and says so)", plain == str(work) and "not a git" in note)

# ------------------------------------------------------------------ herdr backend
section("herdr backend")


class FakeHerdr:
    def __init__(self):
        self.calls = []
        self.states = ["idle", "idle", "working", "working", "idle"]
        self.n = 0

    def __call__(self, argv, **kw):
        args = argv[1:]
        self.calls.append(args)
        out = ""
        if args[:2] == ["workspace", "create"]:
            out = json.dumps({"result": {"workspace": {"workspace_id": "w7"},
                                         "tab": {"tab_id": "t1"}, "root_pane": {"pane_id": "w7:p1"}}})
        elif args[:2] == ["agent", "get"]:
            state = self.states[min(self.n, len(self.states) - 1)]
            self.n += 1
            out = json.dumps({"result": {"agent": {"name": "claude", "status": state}}})
        elif args[:2] == ["pane", "read"]:
            out = "claude> working on it"
        elif args[:2] == ["status", "server"]:
            out = json.dumps({"result": {"running": True}})
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")


fh = FakeHerdr()
herdr = workers.HerdrBackend(runner=fh, which=lambda n: "/usr/bin/herdr")
check("herdr is available when its server answers", herdr.available()[0])
check("herdr reports how to install it when missing",
      "herdr.dev" in workers.HerdrBackend(which=lambda n: None).available()[1])
sup, _ = make_sup({"herdr": herdr})
h = sup.create({"backend": "herdr", "workspace": str(work), "prompt": "add tests", "isolate": False})
sup.tick()
job = sup.store.get(h["id"])
check("a herdr job opens its own workspace and pane",
      job["handle"]["pane"] == "w7:p1" and job["handle"]["workspace"] == "w7")
check("the agent starts interactively in the pane",
      any(c[:3] == ["pane", "run", "w7:p1"] and "claude" in c[3] for c in fh.calls))
check("the workspace cwd is the job folder",
      any(c[:2] == ["workspace", "create"] and str(work) in c for c in fh.calls))
sup.tick()
check("once the agent is idle the task is prompted",
      ["agent", "prompt", "w7:p1", "add tests"] in fh.calls and sup.store.get(h["id"])["status"] == "working")
for _ in range(4):
    sup.tick()
job = sup.store.get(h["id"])
check("working then idle means done", job["status"] == "done", job)
check("the pane output is captured", "working on it" in job["output"])

fh2 = FakeHerdr()
fh2.states = ["idle", "blocked"]
sup, _ = make_sup({"herdr": workers.HerdrBackend(runner=fh2, which=lambda n: "herdr")})
h2 = sup.create({"backend": "herdr", "workspace": str(work), "prompt": "x", "isolate": False})
sup.tick(); sup.tick(); sup.tick()
job = sup.store.get(h2["id"])
check("a blocked agent shows as blocked and says how to answer",
      job["status"] == "blocked" and "attach" in job["note"], job)
sup.cancel(h2["id"])
check("cancel interrupts the agent and closes its herdr workspace",
      ["pane", "send-keys", "w7:p1", "ctrl+c"] in fh2.calls and ["workspace", "close", "w7"] in fh2.calls)
check("status parsing tolerates nesting and junk",
      workers.herdr_agent_state({"a": [{"status": "WORKING"}]}) == "working"
      and workers.herdr_agent_state({"status": "weird"}) == "unknown")

# ------------------------------------------------------------------ cua backend
section("cua backend (virtual computer)")
PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeInterface:
    def __init__(self):
        self.ran = []

    async def run_command(self, cmd):
        self.ran.append(cmd)
        code = 3 if "fail" in cmd else 0
        return types.SimpleNamespace(stdout="out:" + cmd + "\n", stderr="", returncode=code)

    async def screenshot(self):
        return PNG


class FakeComputer:
    made = []

    def __init__(self, **kw):
        self.kw = kw
        self.interface = FakeInterface()
        self.disconnected = False
        FakeComputer.made.append(self)

    async def run(self):
        return None

    async def disconnect(self):
        self.disconnected = True


fake_mod = types.SimpleNamespace(Computer=FakeComputer)


def importer(name, fromlist=()):
    if name == "computer":
        return fake_mod
    raise ImportError(name)


cua_dir = TMP / "cuadata"
cua = workers.CuaBackend(cua_dir, env={"LOKI_CUA_PROVIDER": "lume"}, importer=importer)
check("lume uses the macOS VM image", cua.computer_kwargs()["provider_type"] == "lume"
      and cua.computer_kwargs()["os_type"] == "macos")
check("docker is the default provider",
      workers.CuaBackend(cua_dir, env={}, importer=importer).computer_kwargs()["image"].startswith("trycua/"))
check("cua reports how to install it when missing",
      "cua-computer" in workers.CuaBackend(cua_dir, env={}, importer=lambda *a, **k: (_ for _ in ()).throw(ImportError())).available()[1])


class ReadyCua(workers.CuaBackend):
    def available(self):
        return True, "fake"


sup, _ = make_sup({"cua": ReadyCua(cua_dir, env={}, importer=importer)})
v = sup.create({"backend": "cua", "commands": ["echo hi", "uname -a"]})
sup.tick()
for _ in range(50):
    time.sleep(0.05)
    sup.tick()
    if sup.store.get(v["id"])["status"] in workers.FINAL:
        break
job = sup.store.get(v["id"])
vm = FakeComputer.made[-1]
check("commands run inside the virtual computer in order", vm.interface.ran == ["echo hi", "uname -a"])
check("the VM job finishes done with output", job["status"] == "done" and "out:uname -a" in job["output"], job)
check("a final screenshot is saved", Path(job["handle"]["screenshot"]).read_bytes() == PNG)
check("the VM is disconnected afterwards", vm.disconnected)
w = sup.create({"backend": "cua", "commands": ["make fail", "never"]})
for _ in range(60):
    time.sleep(0.05)
    sup.tick()
    if sup.store.get(w["id"])["status"] in workers.FINAL:
        break
job = sup.store.get(w["id"])
check("a failing command fails the job and stops the rest",
      job["status"] == "failed" and "exited 3" in job["error"] and "never" not in FakeComputer.made[-1].interface.ran, job)
a2 = sup.create({"backend": "cua", "prompt": "open the browser"})
for _ in range(60):
    time.sleep(0.05)
    sup.tick()
    if sup.store.get(a2["id"])["status"] in workers.FINAL:
        break
check("an agent job without the agent package fails with a reason",
      sup.store.get(a2["id"])["status"] == "failed")

# ------------------------------------------------------------------ bridge endpoints
section("engine endpoints")
import loki_bridge  # noqa: E402

state = types.SimpleNamespace(jobs=None, project=work)
code, body = loki_bridge.job_action(state, "/jobs", {"prompt": "x"})
check("endpoints answer 503 when jobs are not running", code == 503)
state.jobs, _ = make_sup({"local": FakeBackend(script=["working"]), "herdr": FakeBackend(), "cua": FakeBackend()})
code, body = loki_bridge.job_action(state, "/jobs", {"backend": "local", "prompt": "hi"})
check("POST /jobs creates a job in the engine's workspace",
      code == 200 and state.jobs.store.get(body["id"])["workspace"] == str(work), body)
code, body2 = loki_bridge.job_action(state, "/jobs", {"backend": "local", "prompt": "x", "commands": "ls"})
check("POST /jobs rejects host shell commands with 400", code == 400)
code, _ = loki_bridge.job_action(state, "/jobs/cancel", {"id": body["id"]})
check("POST /jobs/cancel works", code == 200 and state.jobs.store.get(body["id"])["status"] == "cancelled")
check("cancel of an unknown job is 404", loki_bridge.job_action(state, "/jobs/cancel", {"id": "zz"})[0] == 404)
code, body3 = loki_bridge.job_action(state, "/jobs/clear", {})
check("POST /jobs/clear removes finished jobs", code == 200 and body3["removed"] >= 1)
check("no screenshot is a 404", loki_bridge.job_screenshot(state, {"id": ["nope"]})[0] == 404)

bridge_src = (REPO / "addons" / "loki" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine starts the job supervisor", "workers.default_supervisor" in bridge_src and "state.jobs.start()" in bridge_src)
ui = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("the app has a Background jobs panel", 'id="jobs"' in ui and 'id="job-form"' in ui)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
