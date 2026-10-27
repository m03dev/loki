"""LOKI's systems working TOGETHER: real modules wired end to end, fakes only at the edges.

    python tests/test_systems.py            (cloud sandbox: PYTHONPATH=tests/cloud_stubs)

Each scenario drives several real parts of LOKI through their real seams; only the model
servers, the network and the machine's hardware are faked:

  1. a goal: first layer -> model (smart route) -> conductor picks the image specialist ->
     policy allows it (and refuses a path outside the project) -> usage counted -> experience
     and ReasoningBank remember it -> the next similar goal gets the lesson
  2. a background agent: the jobs API (with the policy) starts the built-in agent as a real
     child process -> the event stream and the live view show it working, then done
  3. a team: plan -> build -> check -> one fix round -> verified, with fake stage agents; the
     board, the events and the world reflect every step
  4. providers die mid-run (402, 401, 429): smart routing moves on and the turn finishes; the
     System check names the dead ones with the right fix, and its safe fix switches them off
  5. the System check: all green when everything is healthy; red rows with the right fix for
     rejected keys, a changed add-on and an update problem; its engine routes over HTTP
"""
from __future__ import annotations

import asyncio
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-systems-"))
DATA = TMP / "data"
WS = TMP / "ws"
DATA.mkdir()
WS.mkdir()
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
os.environ["LOKI_PEER_NAME"] = "test-pc"
os.environ["LOKI_LAYA_LOCAL"] = "0"
os.environ["LOKI_EXPERIENCE"] = "1"
os.environ["LOKI_LEARN_ROUTING"] = "0"
os.environ["LOKI_VERIFY"] = "0"
for key in list(os.environ):
    if key.endswith(("_API_KEY", "_API_TOKEN", "_MODEL", "_BASE_URL")) or key in (
            "HF_TOKEN", "LOKI_TEAM_ID", "LOKI_DISABLED_PROVIDERS", "LOKI_PHONE_LINK", "LOKI_PEERS",
            "LOKI_ALLOW_PAID", "LOKI_PREFER", "LOKI_DAILY_USD_LIMIT", "LOKI_PAID_PROVIDERS", "LOKI_FREE_PROVIDERS",
            "LOKI_PROMPTED_TOOLS", "LOKI_IMAGE_BACKEND", "LOKI_AUTO_APPROVE", "HARNESS_AUTO_APPROVE",
            "LOKI_REASONING_BANK", "LOKI_TUNED_PROMOTED", "LOKI_MAX_TURNS", "LOKI_REQUEST_DEADLINE"):
        os.environ.pop(key, None)
sys.path.insert(0, str(REPO / "engine"))

import openai  # noqa: E402

if getattr(openai, "__version__", "") == "0-stub":
    # The background agent is a child process: give it the same stand-ins, by absolute path.
    os.environ["PYTHONPATH"] = os.pathsep.join(str(Path(p).resolve()) for p in
                                               [str(REPO / "tests" / "cloud_stubs")] +
                                               [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])

import events  # noqa: E402
import loki  # noqa: E402
import loki_bridge  # noqa: E402
import peer_link  # noqa: E402
import policy  # noqa: E402
import providers_catalog  # noqa: E402
import reasoning_bank  # noqa: E402
import system_check  # noqa: E402
import team  # noqa: E402
import workers  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:400]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


# ------------------------------------------------------------------ the edges, faked
async def _deny(*_a, **_k):
    return False


async def _no_mcp(*_a, **_k):
    return []


READY = {"nvidia", "nvidia-nemotron", "nvidia-pro", "9router", "deepseek"}
for _pid in READY:
    loki.MODELS[_pid].api_key = "test-key-" + _pid
loki.approve = _deny                          # nobody is there to click Allow
loki.refresh_mcp_tools = _no_mcp
loki.local_ready = lambda: False              # hermetic: no Ollama on the test machine counts
loki.online = lambda *a, **k: True
loki.MODEL_RETRIES = 0
loki.STREAM_MODELS = "off"                    # the fake servers answer in one piece (streaming: test_studio_stream)
loki.model_name = "smart"
loki.cli_agents.is_available = lambda name: False
loki.provider_configured = lambda name: name in READY and not loki.provider_disabled(name)
loki.messages[:] = [{"role": "system", "content": loki.system_prompt()}]


def ns(**kw):
    return types.SimpleNamespace(**kw)


def reply(content="", calls=None, tin=900, tout=40):
    tool_calls = [ns(id="call_%d" % i, type="function", function=ns(name=n, arguments=json.dumps(a)))
                  for i, (n, a) in enumerate(calls or [])] or None
    return ns(choices=[ns(message=ns(role="assistant", content=content, tool_calls=tool_calls))],
              usage=ns(prompt_tokens=tin, completion_tokens=tout))


def http_error(status, text):
    exc = openai.APIStatusError(text, response=ns(status_code=status, headers={}, request=None), body=None)
    exc.status_code = status       # the same on the real client and the stand-in
    return exc


class FakeModels:
    """Every provider's server: script[provider] is a function(kwargs, n) -> response, or raises."""

    def __init__(self):
        self.script = {}
        self.calls = []

    def client(self):
        provider = loki.active_model_name()
        fake = self

        class _Completions:
            async def create(self, **kwargs):
                # a copy: LOKI keeps editing its live message list after the call
                snapshot = dict(kwargs, messages=[dict(m) if isinstance(m, dict) else m for m in kwargs["messages"]])
                fake.calls.append((provider, snapshot, events.latest_seq()))
                handler = fake.script.get(provider)
                if handler is None:
                    raise http_error(503, "no such fake provider %s" % provider)
                return handler(kwargs, sum(1 for p, _, _ in fake.calls if p == provider))

        return ns(chat=ns(completions=_Completions()))


MODELS = FakeModels()
loki.make_client = MODELS.client


def has_tool_result(kwargs):
    return any(m.get("role") == "tool" for m in kwargs["messages"] if isinstance(m, dict))


def system_text(kwargs):
    return str((kwargs["messages"][0] or {}).get("content", ""))


class FakeState:
    def __init__(self, jobs=None):
        self.agent = loki
        self.jobs = jobs
        self.project = WS
        self.peer_server = None
        self.phone_server = None
        self.chat_lock = None


# ================================================================== 1. a goal, end to end
section("1. a goal flows: first layer -> model -> conductor -> policy -> usage -> ReasoningBank")
loki.CAPABILITIES.set_enabled("image-gen", True)
runner_calls = []


def fake_runner(argv, input="", **_kw):          # the image runner, without a GPU or the internet
    runner_calls.append((argv, json.loads(input)))
    out = {"ok": True, "file": str(WS / "images" / "red-fox.png"), "backend": "pollinations",
           "note": "made by a free third-party service"}
    return ns(stdout=json.dumps(out) + "\n", stderr="", returncode=0)


loki.CONDUCTOR.runner = fake_runner


def main_driver_image(kwargs, n):
    if not has_tool_result(kwargs):
        return reply(calls=[("conductor", {"role": "image", "task": "a red fox in studio light"}),
                            ("read_file", {"filename": "../../../etc/passwd"})])
    return reply("DONE: made the image images/red-fox.png with the image specialist")


MODELS.script = {"nvidia": main_driver_image}
mark = events.latest_seq()
usage_before = len(loki.USAGE.entries())
answer = asyncio.run(loki.run_agent("make an image of a red fox in studio light"))
first_call = MODELS.calls[0]
decisions = [e for e in events.read(mark) if e["type"] == "decision.made"]
check("the first layer decided before the model was asked",
      decisions and decisions[0]["seq"] <= first_call[2], (decisions, first_call[2]))
check("the decision is the full structure (intent, route, capabilities, approval)",
      all(k in decisions[0]["payload"] for k in ("intent", "route", "capabilities", "approval")) if decisions else False)
check("the smart route sent the request to the first ready free provider", first_call[0] == "nvidia", first_call[0])
check("the model was told which specialists are ready, and through what",
      "image:" in system_text(first_call[1]) and "via image-gen" in system_text(first_call[1]), system_text(first_call[1])[-600:])
check("the conductor picked the image specialist and ran its runner",
      runner_calls and runner_calls[0][0][-1].endswith("imagegen.py") and runner_calls[0][1]["prompt"] == "a red fox in studio light",
      runner_calls)
tool_msgs = [m for m in loki.messages if isinstance(m, dict) and m.get("role") == "tool"]
check("the specialist's result went back to the model",
      any("made " in str(m["content"]) and "pollinations" in str(m["content"]) for m in tool_msgs), tool_msgs)
check("the policy refused the path outside the project in the same turn",
      any("DENIED by Loki's policy" in str(m["content"]) for m in tool_msgs), tool_msgs)
check("the turn finished with the model's answer", answer.startswith("DONE: made the image"), answer)
new_usage = loki.USAGE.entries()[usage_before:]
check("both model calls were counted in the usage ledger, for the provider that answered",
      len(new_usage) == 2 and all(e["provider"] == "nvidia" and e["in"] == 900 and e["out"] == 40 for e in new_usage),
      new_usage)
check("the usage meter for the reply adds up", loki_bridge.usage_total(loki.LAST_USAGE).get("calls") == 2,
      loki_bridge.usage_total(loki.LAST_USAGE))
status_events = [e["payload"].get("state") for e in events.read(mark) if e["type"] == "agent.status"]
check("LOKI reported working, then idle (the world's conductor)", status_events[:1] == ["working"] and status_events[-1:] == ["idle"],
      status_events)
lesson = [i for i in reasoning_bank.items() if "red fox" in i.get("goal", "")]
check("ReasoningBank stored the lesson as one that WORKED (a finished request with no checkable file)",
      lesson and lesson[-1]["worked"] is True and "conductor" in lesson[-1]["steps"], lesson)
exp_log = DATA / "experience" / "log.jsonl"
check("the experience log recorded the request with its provider and decision",
      exp_log.is_file() and '"provider": "nvidia"' in exp_log.read_text(encoding="utf-8")
      and '"triage"' in exp_log.read_text(encoding="utf-8"))

MODELS.calls.clear()
MODELS.script = {"nvidia": lambda kwargs, n: reply("DONE: made a second fox image")}
asyncio.run(loki.run_agent("make an image of a red fox in the snow"))
prompt = system_text(MODELS.calls[0][1]) if MODELS.calls else ""
check("the next similar goal gets the lesson in its prompt (what worked, step by step)",
      "Lessons from similar past tasks" in prompt and "WORKED" in prompt and "conductor" in prompt, prompt[-700:])
check("an unrelated goal gets no lesson", reasoning_bank.prompt_for("compose a haiku about rain") == "")

# ================================================================== 2. a background agent
section("2. a background agent: jobs API -> policy -> real child process -> events -> world")
SUP = workers.default_supervisor(DATA)
SUP.start()
STATE = FakeState(SUP)
loki.JOBS = SUP
loki.TEAMS = team.TeamRunner(SUP, policy=loki.POLICY)
code, body = loki_bridge.job_action(STATE, "/jobs", {"backend": "local", "agent": "hermes", "prompt": "x",
                                                      "workspace": str(WS)})
check("the jobs API asks the policy: an agent whose add-on is off is refused", code == 403 and "hermes" in body.get("error", ""),
      (code, body))
mark = events.latest_seq()
code, body = loki_bridge.job_action(STATE, "/jobs", {"backend": "local", "agent": "loki", "title": "System check · background job",
                                                      "prompt": "prove it", "workspace": str(WS), "isolate": False,
                                                      "timeout_s": 60, "selfcheck": True})
check("the built-in agent is accepted", code == 200 and body.get("id"), (code, body))
job_id = body.get("id", "")
seen_world = []
deadline = time.time() + 60
while time.time() < deadline:
    SUP.tick()
    job = SUP.store.get(job_id) or {}
    me = [a for a in events.world(SUP.store.all(), [], False)["agents"] if a["id"] == "job-" + job_id]
    if me and (not seen_world or seen_world[-1] != me[0]["state"]):
        seen_world.append(me[0]["state"])
    if job.get("status") in workers.FINAL:
        break
    time.sleep(0.2)
job = SUP.store.get(job_id) or {}
check("the child process ran and finished (no model, no tools)", job.get("status") == "done" and job.get("exit_code") == 0,
      {k: job.get(k) for k in ("status", "exit_code", "error", "output")})
check("its report came back through the log", "system check job ran" in (job.get("output") or ""), job.get("output"))
check("the live view showed the agent working, then done", "working" in seen_world and seen_world[-1] == "done", seen_world)
kinds = [e["type"] for e in events.read(mark) if e.get("task") == job_id]
check("the event stream has created -> started -> completed for it",
      kinds[:1] == ["task.created"] and "task.started" in kinds and kinds[-1] == "task.completed", kinds)
listed = [j for j in SUP.status()["jobs"] if j["id"] == job_id]
check("GET /jobs serves it as done", listed and listed[0]["status"] == "done", listed)
check("a check job never waits for the one local-model slot (it asks no model)",
      not workers.uses_local_model({"agent": "loki", "backend": "local", "selfcheck": True}, {"LOKI_PREFER": "local"})
      and workers.uses_local_model({"agent": "loki", "backend": "local"}, {"LOKI_PREFER": "local", "LOKI_LOCAL_ONLY": "1"}))
_idle = workers.Supervisor(workers.JobStore(TMP / "idle-jobs.json"), {"local": workers.LocalBackend(TMP)}, TMP)  # never started
check("only the built-in agent can be a check job",
      _idle.create({"backend": "local", "agent": "codex", "prompt": "x", "workspace": str(WS), "selfcheck": True})["selfcheck"] is False)

# ================================================================== 3. a team
section("3. a team: plan -> build -> check -> fix -> verified, on the board, the events and the world")


class StageAgents(workers.Backend):
    """Each team agent finishes on the next poll with what that role would say."""
    name = "local"

    def __init__(self):
        self.rounds = {}

    def available(self):
        return True, "fake stage agents"

    def start(self, job):
        return {"status": "working", "handle": {"pid": 0}}

    def poll(self, job):
        role = (job.get("profile") or {}).get("name", "")
        self.rounds[role] = self.rounds.get(role, 0) + 1
        if self.rounds[role] < 2:
            return {}
        n = sum(1 for j in TEAM_JOBS.store.all() if (j.get("profile") or {}).get("name") == role)
        out = {"Architect": "DONE: wrote TEAM_PLAN.md", "Builder": "DONE: built notes.py and test_notes.py",
               "Tester": "FAIL: adding an empty note crashes" if n == 1 else "PASS: 4 checks, 0 FAIL",
               "Reviewer": "PASS"}.get(role, "DONE")
        self.rounds[role] = 0
        return {"status": "done", "exit_code": 0, "output": out}


TEAM_JOBS = workers.Supervisor(workers.JobStore(TMP / "teamjobs.json"), {"local": StageAgents()}, TMP / "teamdata",
                               limits={"local": 4}, workspace_preparer=lambda job, d: (job["workspace"], ""))
RUNNER = team.TeamRunner(TEAM_JOBS, policy=loki.POLICY)
mark = events.latest_seq()
t = RUNNER.start("build a tiny notes app with tests", str(WS))
stages, world_states = [t["stage"]], []
for _ in range(60):
    RUNNER.tick()
    cur = RUNNER.get(t["id"])
    if cur["stage"] != stages[-1]:
        stages.append(cur["stage"])
    w = events.world(TEAM_JOBS.store.all(), RUNNER.all(), False)
    world_states.append({a["name"]: a["state"] for a in w["agents"] if a["team"] == t["id"]})
    if cur["status"] != "working":
        break
cur = RUNNER.get(t["id"])
check("the team went plan -> build -> check -> fix -> re-check", stages == ["plan", "build", "check", "fix", "fix-check"], stages)
check("one fix round, then verified", cur["status"] == "done" and cur["verdict"].startswith("verified") and cur["fix_rounds"] == 1, cur)
board = [m["text"] for m in team.board(t["id"])]
check("the board tells the story (stages, each report, the failure, the verdict)",
      any("Stage plan" in b for b in board) and any("adding an empty note crashes" in b for b in board)
      and board[-1].startswith("Team finished: verified"), board)
ev = events.read(mark, limit=5000)
mine = [e for e in ev if e.get("team") == t["id"]]
assigned = [e["recipient"] for e in mine if e["type"] == "task.assigned"]
check("LOKI assigned each role through the event stream", assigned[:2] == ["Architect", "Builder"] and assigned.count("Builder") == 2,
      assigned)
check("every stage agent's job reported itself by role",
      {e["sender"] for e in mine if e["type"] == "task.completed"} >= {"Architect", "Builder", "Tester", "Reviewer"},
      {e["sender"] for e in mine if e["type"] == "task.completed"})
check("the verdict was announced", any(e["type"] == "verification.completed" and e["payload"].get("verified") for e in mine))
check("the live view showed the architect working first", world_states and world_states[0].get("Architect") == "working",
      world_states[:2])
final = events.world(TEAM_JOBS.store.all(), RUNNER.all(), False)
check("and the whole team done at the end, with the team listed",
      all(world_states[-1].get(r) == "done" for r in ("Architect", "Builder", "Tester", "Reviewer"))
      and any(x["id"] == t["id"] and x["status"] == "done" for x in final["teams"]), (world_states[-1], final["teams"]))
refusing = types.SimpleNamespace(job=lambda backend, agent: policy.Verdict(policy.DENY, "background agents are off"))
try:
    team.TeamRunner(TEAM_JOBS, policy=refusing).start("build it", str(WS))
    check("the policy can stop a team before it starts (with its reason)", False)
except ValueError as exc:
    check("the policy can stop a team before it starts (with its reason)", "background agents are off" in str(exc), exc)

# ================================================================== 4. providers die mid-run
section("4. providers die mid-run: smart routing moves on; the System check names them and switches them off")
loki._SMART_FAILED.clear()
loki.ROUTE_TRACE.clear()
MODELS.calls.clear()


def main_driver_dies(kwargs, n):
    if n == 1:
        return reply(calls=[("list_tree", {})])        # the first step works...
    raise http_error(402, "Insufficient credit: add credits to keep going")   # ...then the credit runs out


MODELS.script = {
    "nvidia": main_driver_dies,
    "nvidia-nemotron": lambda kwargs, n: (_ for _ in ()).throw(http_error(401, "Incorrect API key provided")),
    "nvidia-pro": lambda kwargs, n: reply("DONE: listed the project (answered by nvidia-pro)"),
}
answer = asyncio.run(loki.run_agent("list the files in this project and summarise them"))
tried = [p for p, _, _ in MODELS.calls]
check("the run started on nvidia, which then ran out of credit", tried[:2] == ["nvidia", "nvidia"], tried)
check("smart routing skipped nvidia-nemotron's rejected key and finished on nvidia-pro", tried[2:] == ["nvidia-nemotron", "nvidia-pro"], tried)
check("the turn still finished", "answered by nvidia-pro" in answer, answer)
check("the route records why each provider was skipped",
      [(r["provider"], r["reason"]) for r in loki.ROUTE_TRACE] == [("nvidia", "quota spent"), ("nvidia-nemotron", "key rejected")],
      loki.ROUTE_TRACE)
check("the tool call made before the failure was kept", any(m.get("role") == "tool" for m in loki.messages[-6:] if isinstance(m, dict)))
check("usage was counted for the provider that answered", loki.USAGE.entries()[-1]["provider"] == "nvidia-pro",
      loki.USAGE.entries()[-1])


def fake_urlopen(req, timeout=0):
    """The providers' servers as providers_catalog.test sees them (one 1-token request each)."""
    body = json.loads(req.data.decode()) if req.data else {}
    for pid in READY:
        cfg = loki.MODELS[pid]
        if req.full_url.startswith(cfg.base_url.rstrip("/")) and body.get("model") == cfg.model:
            break
    else:
        raise urllib.error.URLError("unknown host")
    errors = {"nvidia": (402, "Insufficient credit"), "nvidia-nemotron": (401, "API key not valid"),
              "9router": (401, "Unauthorized")}
    if pid in errors:
        status, text = errors[pid]
        raise urllib.error.HTTPError(req.full_url, status, text, {}, io.BytesIO(json.dumps({"error": {"message": text}}).encode()))

    class _Resp:
        status = 200

        def read(self):
            return json.dumps({"model": body.get("model"), "choices": [{"message": {"content": "OK"}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def catalog_test(agent, pid, timeout):
    return providers_catalog.test(agent, pid, timeout=timeout, opener=fake_urlopen)["test"]


ctx = system_check.Context(loki, STATE, deps={"provider_test": catalog_test})
row = system_check.check_models(ctx)
items = {i["id"]: i for i in row["items"]}
check("the System check finds a working route: nvidia-pro answered", row["status"] == "warn" and ctx.shared["answered_by"] == "nvidia-pro",
      (row["status"], row["detail"]))
check("it names each dead provider with the reason in plain words",
      "out of credit" in items["nvidia"]["detail"] and "key rejected" in items["nvidia-nemotron"]["detail"]
      and "key rejected" in items["9router"]["detail"], items)
check("each dead provider gets a safe 'Switch off' fix",
      all(items[p]["fix"]["action"] == "provider_off" and items[p]["fix"]["args"] == {"id": p} for p in ("nvidia", "nvidia-nemotron", "9router")))
check("a paid key is only checked for presence (no money spent)",
      items["deepseek"]["status"] == "skip" and "paid" in items["deepseek"]["detail"], items.get("deepseek"))
check("the row's fix switches all the dead ones off at once",
      row["fix"]["action"] == "provider_off" and sorted(row["fix"]["args"]["ids"]) == ["9router", "nvidia", "nvidia-nemotron"], row["fix"])
check("the Connections cards show the same test results", providers_catalog._TESTS["nvidia-pro"]["ok"]
      and not providers_catalog._TESTS["9router"]["ok"])
env_file = DATA / ".env"
done = system_check.apply_fix(STATE, row["fix"]["action"], row["fix"]["args"],
                              write_env=lambda updates: peer_link.write_env(env_file, updates))
check("the safe fix switched them off (saved, and live at once)",
      done["ok"] and set(os.environ["LOKI_DISABLED_PROVIDERS"].split(",")) == {"nvidia-nemotron", "9router", "nvidia"}
      and "LOKI_DISABLED_PROVIDERS" in env_file.read_text(), (done, os.environ.get("LOKI_DISABLED_PROVIDERS")))
loki._SMART_FAILED.clear()
check("routing no longer tries them: smart now picks nvidia-pro first", loki.active_model_name() == "nvidia-pro", loki.active_model_name())
row2 = system_check.check_models(system_check.Context(loki, STATE, deps={"provider_test": catalog_test}))
check("a re-check is green and lists what is switched off", row2["status"] == "ok" and "Switched off" in row2["detail"],
      (row2["status"], row2["detail"]))
check("the check never touched the live used-up marks", loki._SMART_FAILED == set(), loki._SMART_FAILED)
bad = system_check.apply_fix(STATE, "capability_enable", {"name": "image-gen"})
check("an unsafe 'fix' is refused (add-ons are only approved by you)", not bad["ok"], bad)
os.environ.pop("LOKI_DISABLED_PROVIDERS", None)

# ================================================================== 5. the System check
section("5. the System check: all green when healthy, the right red rows when not")


class FakeUpdater:
    def __init__(self, **state):
        self.state = {"git": True, "enabled": True, "label": "v0.17 · patch 512", "commit": "abc1234",
                      "problem": "", "error": "", "update_available": False, "checked": time.time() - 90, **state}

    def status(self):
        return dict(self.state)

    def restart_needed(self):
        return False

    def sign_in_hint(self):
        return "Sign in to GitHub: run gh auth login, then gh auth setup-git."


class FakeModelSetup:
    @staticmethod
    def status(info=None):
        return {"ollama": {"installed": True, "running": True, "models": [{"name": "qwen3.5:9b"}]},
                "best": {"name": "qwen3.5:9b", "tools": True}, "servers": [], "upgrade": None}


class FakeToolClient:
    """A provider that calls list_tree, then names the files it was shown."""

    def __init__(self):
        self.seen = []
        outer = self

        class _C:
            async def create(self, **kwargs):
                outer.seen.append(kwargs)
                if not has_tool_result(kwargs):
                    return reply(calls=[("list_tree", {"subdir": "."})])
                listing = [m for m in kwargs["messages"] if m.get("role") == "tool"][0]["content"]
                return reply("The files are: " + listing.replace("\n", ", "))

        self.chat = ns(completions=_C())


listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(8)
# The phone check opens a connection once per report. A listen(1) backlog that is never
# accepted fills up, and on Windows the NEXT connect then times out - so a healthy machine
# was reported as "the phone link does not answer" on the second run. Drain accepts instead.
def _drain_listener(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        try:
            conn.close()
        except OSError:
            pass
threading.Thread(target=_drain_listener, args=(listener,), daemon=True).start()
STATE.phone_server = ns(address=("0.0.0.0", listener.getsockname()[1]))
STATE.autopilot = ns(status=lambda: {"enabled": True, "idle": True, "waiting_for": "",
                                      "log": [{"duty": "health", "text": "All systems work together."}],
                                      "last": {}, "started": {}})
STATE.phone_registry = ns(present=lambda: [{"id": "p1", "name": "Mohamed's iPhone"}])
fake_peers = ns(peers=lambda: [{"name": "mac", "url": "http://192.168.1.71:8768"}],
                status_all=lambda: [{"name": "mac", "ok": True, "ms": 12, "hello": {"commit": "abc1234"}}])
fake_phone = ns(enabled=lambda: True, port=lambda: 8769)
loki.CAPABILITIES.set_enabled("ollama", False)        # its command is not on this test machine
tool_client = FakeToolClient()


def healthy(**over):
    deps = {"updater": FakeUpdater(), "provider_test": lambda a, p, t: {"ok": True, "detail": "answered", "ms": 140},
            "tool_client": lambda agent, pid: tool_client, "job_action": loki_bridge.job_action,
            "image_plan": lambda: {"order": ["zimage", "pollinations"], "skipped": {}},
            "model_setup": FakeModelSetup, "peers": fake_peers, "phone_link": fake_phone,
            "disk": lambda path: ns(free=200 * 2**30, total=500 * 2**30), "free_memory": lambda: 9.5}
    deps.update(over)
    return system_check.Context(loki, STATE, deps=deps)


steps = []
report = system_check.run(healthy(), on_progress=lambda p: steps.append(p.get("current")))
rows = {r["id"]: r for r in report["results"]}
not_ok = {k: (r["status"], r["detail"]) for k, r in rows.items() if r["status"] != "ok"}
check("every check runs, in order, with progress", [r["id"] for r in report["results"]] == [c[0] for c in system_check.CHECKS]
      and steps[0] == "Engine & updates", steps)
check("healthy machine: every system is green", not not_ok, not_ok)
check("the summary says so", report["summary"]["line"] == "All %d systems work together." % len(system_check.CHECKS),
      report["summary"])
check("the autopilot row shows it is on and what it did",
      rows["autopilot"]["status"] == "ok" and "On." in rows["autopilot"]["detail"], rows.get("autopilot"))
check("the smart route answered and the latency is reported", "answered a tiny prompt" in rows["models"]["detail"]
      and "140 ms" in rows["models"]["detail"], rows["models"]["detail"])
check("the model called the tool through the real request path and read the result back",
      "called list_tree" in rows["tools"]["detail"] and "read the result back" in rows["tools"]["detail"]
      and len(tool_client.seen) == 2 and tool_client.seen[0]["tools"][0]["function"]["name"] == "list_tree",
      rows["tools"]["detail"])
check("the background job was proven through the jobs API, the events and the world",
      "the live view" in rows["jobs"]["detail"] and "task.completed" in rows["jobs"]["detail"], rows["jobs"]["detail"])
check("the check cleaned up its test job", not [j for j in SUP.store.all() if j["title"] == "System check · background job"
                                                and j["id"] != job_id])
check("a team dry run reached the board, the events and the world - and was cleaned up",
      "appeared in the event stream and in the live view" in rows["teams"]["detail"]
      and not [x for x in loki.TEAMS.all() if x.get("dry_run")], rows["teams"]["detail"])
check("the image specialist says which backend it would use", "Z-Image Turbo" in rows["specialists"]["detail"],
      rows["specialists"]["detail"])
check("the run stays well under a minute here", report["seconds"] < 60, report["seconds"])

sys.path.insert(0, str(REPO / "tests"))
from fake_ollama import FakeOllama  # noqa: E402

fake_server = FakeOllama(models=["qwen3.5:9b"], port=0).start()
saved_pro = (loki.MODELS["nvidia-pro"].base_url, loki.MODELS["nvidia-pro"].model)
saved_ready = set(READY)
loki.MODELS["nvidia-pro"].base_url = "http://127.0.0.1:%d/v1" % fake_server.server.server_address[1]
loki.MODELS["nvidia-pro"].model = "qwen3.5:9b"
READY.clear()
READY.add("nvidia-pro")
row = system_check.check_models(system_check.Context(loki, STATE))      # the real provider test, real sockets
check("the real provider test reaches an OpenAI-compatible server and reports the latency",
      row["status"] == "ok" and row["data"]["answered"] == "nvidia-pro" and "ms" in row["detail"]
      # providers_catalog.test sends one tiny request ("Say OK", max_tokens 8) - it was 1 token
      and any(r.get("max_tokens") == 8 for r in fake_server.chat_requests()), (row["status"], row["detail"]))
loki.MODELS["nvidia-pro"].model = "not-pulled:1b"
row = system_check.check_models(system_check.Context(loki, STATE))
check("a model the server does not have is named as such, with what to do",
      row["status"] == "fail" and "model not found" in row["items"][0]["detail"]
      and "Pick another model" in row["items"][0]["fix"]["text"], row)
loki.MODELS["nvidia-pro"].base_url, loki.MODELS["nvidia-pro"].model = saved_pro
READY.update(saved_ready)
fake_server.stop()
providers_catalog._TESTS.clear()

image_out = []
report = system_check.run(healthy(image_run=lambda prompt: image_out.append(prompt) or "made images/x.png with pollinations"),
                          checks=[c for c in system_check.CHECKS if c[0] == "specialists"])
check("no image is made unless you ask for the real image test", not image_out)
ctx_img = healthy(image_run=lambda prompt: image_out.append(prompt) or "made images/x.png with pollinations")
ctx_img.image_test = True
row = system_check.check_specialists(ctx_img)
check("'Run a real image test' makes one through the specialist", image_out and "Real test: made images/x.png" in row["detail"],
      row["detail"])

# --- what the owner sees on the PC: keys rejected, a changed add-on, an update stuck
enabled_file = DATA / "capabilities_enabled.json"
record = json.loads(enabled_file.read_text(encoding="utf-8"))
record["image-gen"].update(fingerprint="0ld", trust="0ld", granted=["fs:workspace"])   # approved before it asked for network
enabled_file.write_text(json.dumps(record), encoding="utf-8")
check("a manifest that now asks for more is 'changed' and the specialist is off",
      loki.CONDUCTOR.pick("image")[0] == "" and "changed since you enabled it" in loki.CONDUCTOR.pick("image")[1])
check("the model is told the real reason even when no other specialist is ready (it used to say nothing)",
      "image: image-gen changed since you enabled it" in loki.system_prompt()
      and not any(r["ready"] for r in loki.CONDUCTOR.roster()), loki.CONDUCTOR.prompt_section())
dead_keys = lambda a, p, t: {"ok": False, "detail": "the key was rejected", "ms": 80}
report = system_check.run(healthy(provider_test=dead_keys,
                                  updater=FakeUpdater(problem="GitHub sign-in needed", error="could not read Username")))
rows = {r["id"]: r for r in report["results"]}
check("rejected keys: the models row is red and points to Connections",
      rows["models"]["status"] == "fail" and rows["models"]["fix"]["ui"] == "settings:connections"
      and "key rejected" in rows["models"]["detail"], rows["models"])
check("with no model, tool calling is skipped and says why", rows["tools"]["status"] == "skip" and "No model answered" in rows["tools"]["detail"])
check("a changed add-on is red, named, and sent to Add-ons for YOU to approve",
      rows["capabilities"]["status"] == "fail" and "image-gen changed" in rows["capabilities"]["detail"]
      and rows["capabilities"]["fix"]["ui"] == "settings:capabilities" and not rows["capabilities"]["fix"]["action"],
      rows["capabilities"])
check("the image specialist row says it is blocked and why", rows["specialists"]["status"] == "fail"
      and "blocked" in rows["specialists"]["detail"], rows["specialists"])
check("an update that cannot apply is red with the exact fix (GitHub sign-in)",
      rows["engine"]["status"] == "fail" and "GitHub sign-in needed" in rows["engine"]["detail"]
      and "gh auth login" in rows["engine"]["fix"]["text"], rows["engine"])
check("the summary counts them and names them",
      report["summary"]["line"].startswith("%d of %d systems work together. 4 need you: " % (len(system_check.CHECKS) - 5,
                                                                                            len(system_check.CHECKS) - 1))
      and "Engine & updates" in report["summary"]["line"] and "Add-ons" in report["summary"]["line"], report["summary"])
row = system_check.check_engine(healthy(updater=FakeUpdater(problem="local edits block the update",
                                                             error="update waiting: engine/loki.py has local edits")))
check("local edits blocking a Mac update: red, with what to do", row["status"] == "fail" and "ship them" in row["fix"]["text"], row)
loki.CAPABILITIES.set_enabled("image-gen", True)
check("after you re-approve it, the specialist is back", loki.CONDUCTOR.pick("image")[0] == "image-gen")

zplan = DATA / "app" / "imagegen_plan.json"
zplan.parent.mkdir(parents=True, exist_ok=True)
zplan.write_text(json.dumps({"works": None, "failed_at": time.time(), "failures": ["offload-bf16: crashed (exit 3221225477)"]}))
row = system_check.check_specialists(healthy(image_plan=lambda: {
    "order": ["nvidia"], "skipped": {"zimage": "it crashed on this machine recently: offload-bf16: crashed"}}))
check("a crashing local Z-Image is a warning: images still work through FLUX on NVIDIA",
      row["status"] == "warn" and "NVIDIA" in row["detail"] and row["fix"]["action"] == "zimage_retry", row)
system_check.apply_fix(STATE, "zimage_retry", {})
check("its safe fix lets the next image try Z-Image again", not zplan.exists())
sys.path.insert(0, str(REPO / "engine" / "runners"))
import imagegen  # noqa: E402

check("the image runner's own plan matches what auto really tries (no Pollinations)", imagegen.plan_order("nvidia")["order"] == ["nvidia"]
      and "pollinations" not in imagegen.plan_order("auto")["order"])
# Mac: a 16 GB M4 filled its swap and crashed every Z-Image plan. Gate it on memory.
ok16, why16 = imagegen.memory_gate(ram_gb=16, nvidia=False)
check("a 16 GB Mac without an NVIDIA GPU skips local Z-Image, saying why",
      not ok16 and "16 GB" in why16 and "LOKI_IMAGE_BACKEND=zimage" in why16)
check("the 16 GB PC with an NVIDIA GPU keeps local Z-Image (offload fits)", imagegen.memory_gate(ram_gb=16, nvidia=True)[0])
check("a 32 GB Mac keeps local Z-Image", imagegen.memory_gate(ram_gb=32, nvidia=False)[0])
check("unknown memory never blocks", imagegen.memory_gate(ram_gb=0, nvidia=False)[0])
check("the machine's own memory is read", imagegen.total_ram_gb() > 0)

row = system_check.check_peers(healthy(peers=ns(peers=lambda: [{"name": "mac", "url": "http://192.168.1.71:8768"}],
                                                status_all=lambda: [{"name": "mac", "ok": False, "ms": 4000,
                                                                     "error": "cannot reach mac at http://192.168.1.71:8768 (timed out)"}])))
check("a linked machine that cannot be reached is red, with the network hint", row["status"] == "fail" and "Tailscale" in row["detail"], row)
check("nothing linked / phone link off: skipped, not red",
      system_check.check_peers(healthy(peers=ns(peers=lambda: [], status_all=lambda: [])))["status"] == "skip"
      and system_check.check_phone(healthy(phone_link=ns(enabled=lambda: False)))["status"] == "skip")
saved_auto = loki.AUTO_APPROVE
loki.AUTO_APPROVE = True
check("approvals switched off is red", system_check.check_policy(healthy())["status"] == "fail")
loki.AUTO_APPROVE = saved_auto
crash = system_check.run(healthy(), checks=[("boom", "Boom", lambda c: 1 / 0)])
check("a check that crashes is a red row, not a crashed run", crash["results"][0]["status"] == "fail"
      and "ZeroDivisionError" in crash["results"][0]["detail"], crash["results"])

section("the System check over the engine's own HTTP routes")
saved_checks = list(system_check.CHECKS)
system_check.CHECKS[:] = [c for c in saved_checks if c[0] in ("policy", "capabilities", "usage")]
loki_bridge.PORT = 0
bstate = loki_bridge.BridgeState(loki, "test-secret")
bstate.jobs = SUP
server = loki_bridge.BridgeHTTPServer(bstate)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]


def call(method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")


code, data = call("POST", "/system/check", {})
check("POST /system/check starts it in the background", code == 200 and data.get("started"), (code, data))
code2, _ = call("POST", "/system/check", {})
for _ in range(100):
    code, data = call("GET", "/system/check")
    if not data.get("running"):
        break
    time.sleep(0.1)
check("GET /system/check reports progress, then the results and the summary",
      data.get("report") and len(data["report"]["results"]) == 3 and data["report"]["summary"]["line"], data)
check("a second start while one runs is refused (409) or it had already finished", code2 in (200, 409), code2)
code, data = call("POST", "/system/fix", {"action": "update_apply"})
check("POST /system/fix refuses anything that is not a safe fix", code == 400 and not data.get("ok"), (code, data))
code, data = call("POST", "/system/fix", {"action": "revive_providers"})
check("POST /system/fix does a safe one", code == 200 and data.get("ok"), (code, data))
raw = socket.create_connection(("127.0.0.1", port), timeout=5)
raw.sendall(b"GET /fleet HTTP/1.0\r\nHost: 127.0.0.1\r\nAuthorization: Bearer test-secret\r\n\r\n")
stream = b""
while True:
    chunk = raw.recv(65536)
    if not chunk:
        break
    stream += chunk
raw.close()
check("GET /fleet answers once (it used to send a second, 404 response on the same connection)",
      stream.count(b"HTTP/1.") == 1 and b'"workers"' in stream, stream[:300])
server.shutdown()
system_check.CHECKS[:] = saved_checks

section("wired into the app")
ui = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
tabs = ui.split('role="tablist"')[1]
check("System check is the first Settings tab", tabs.index('data-tab="system"') < tabs.index('data-tab="general"'))
check("'Check everything' sits next to Settings in the sidebar", 'id="check-everything"' in ui.split("sidebar-foot")[1].split("</aside>")[0])
js = (REPO / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
check("the panel polls /system/check and runs safe fixes through /system/fix",
      "/system/check" in js and "/system/fix" in js and "function loadSystemCheck" in js)
ship = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("tools/ship.py runs this suite", '"test_systems"' in ship)


section("the bridge can rebind its port at once after a restart (time-wait)")
saved_host, saved_port = loki_bridge.HOST, loki_bridge.PORT
_free = socket.socket()
_free.bind(("127.0.0.1", 0))
_free_port = _free.getsockname()[1]
_free.close()
loki_bridge.HOST, loki_bridge.PORT = "127.0.0.1", _free_port
bstate2 = loki_bridge.BridgeState(loki, "rebind-secret")
_first = loki_bridge.BridgeHTTPServer(bstate2)
threading.Thread(target=_first.serve_forever, daemon=True).start()
try:
    _conn = http.client.HTTPConnection("127.0.0.1", _free_port, timeout=5)
    _conn.request("GET", "/health", headers={"Authorization": "Bearer rebind-secret"})
    _conn.getresponse().read()
    _conn.close()
finally:
    _first.shutdown()
    _first.server_close()
check("a port left in TIME_WAIT reads as free (a live bridge still reads as answering)",
      not loki_bridge.port_is_answering("127.0.0.1", _free_port))
_rebound, _err = True, ""
try:
    _second = loki_bridge.BridgeHTTPServer(bstate2)
    _second.server_close()
except OSError as exc:  # noqa: BLE001
    _rebound, _err = False, str(exc)
check("the bridge rebinds the same port immediately (SO_REUSEADDR, so a good update is not "
      "rolled back for a port still in TIME_WAIT)", _rebound, _err)
loki_bridge.HOST, loki_bridge.PORT = saved_host, saved_port
check("SO_REUSEADDR only off Windows (there it would let a second bind share a live port)",
      loki_bridge.BridgeHTTPServer.allow_reuse_address == (sys.platform != "win32"))
check("the bridge takes a whole page load at once (backlog >= 64, not socketserver's 5)",
      loki_bridge.BridgeHTTPServer.request_queue_size >= 64
      and loki_bridge.BridgeHTTPServer.daemon_threads is True,
      str(loki_bridge.BridgeHTTPServer.request_queue_size))

SUP.stop()
listener.close()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
