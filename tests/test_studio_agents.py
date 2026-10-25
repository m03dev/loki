"""Studio > Agents in the engine (engine/studio_agents.py, through the real bridge): Make starts a REAL job - art,
painting, 3D, comic, novel, website, game - with its own folder in LOKI Projects and a brief that says what to make
and how to check it; the view lists every agent at work with its machine and controls; Stop and Again work; a linked
machine's agents show (its GET /peer/world) and a Stop there goes to that machine; with only one machine the view
says how to link the other. A fake job backend stands in for the agent, a fake peer for the PC. Under a minute.

    python tests/test_studio_agents.py
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-studio-agents-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(TMP / "ws")
os.environ["LOKI_PROJECTS_DIR"] = str(TMP / "LOKI Projects")
os.environ["LOKI_PEERS"] = ""
(TMP / "ws").mkdir(parents=True)
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


try:
    import loki  # noqa: E402
    import loki_bridge  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP: the engine does not import here (%s)\n\n0 passed, 0 failed" % exc)
    sys.exit(0)
import peer_link  # noqa: E402
import peers  # noqa: E402
import studio_agents  # noqa: E402
import workers  # noqa: E402


class FakeBackend(workers.Backend):
    name = "local"
    started: list = []
    stopped: list = []

    def available(self):
        return True, ""

    def start(self, job):
        FakeBackend.started.append(job["id"])
        return {"status": "working", "note": "drawing the first picture"}

    def poll(self, job):
        return {}

    def stop(self, job):
        FakeBackend.stopped.append(job["id"])


loki_bridge.PORT = 0
bstate = loki_bridge.BridgeState(loki, "studio-secret")
bstate.jobs = workers.Supervisor(workers.JobStore(TMP / "data" / "jobs.json"), {"local": FakeBackend()}, TMP / "data",
                                 workspace_preparer=lambda job, d: (job["workspace"], ""))
server = loki_bridge.BridgeHTTPServer(bstate)
PORT = server.server_address[1]
loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)
threading.Thread(target=server.serve_forever, daemon=True).start()


def call(method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Authorization": "Bearer studio-secret", "Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")


# ---- Make
code, v = call("GET", "/studio/agents")
check("GET /studio/agents: the kinds to make are art, painting, 3D, comic, novel, website, game",
      code == 200 and [k["id"] for k in v["kinds"]] == ["art", "painting", "3d", "comic", "novel", "website", "game"], v)
check("only this machine: it says how to link the other one (Settings > Machines, the link code)",
      len(v["machines"]) == 1 and v["machines"][0]["self"] and "link code" in v["hint"], v)
code, made = call("POST", "/studio/make", {"kind": "comic", "brief": "a four-page comic about a robot who learns to paint",
                                           "name": "Robot Painter"})
folder = Path(made.get("folder", ""))
check("Make a comic: a job, in LOKI Projects/Comics/robot-painter, the brief saved there", code == 200 and made["ok"]
      and folder == TMP / "LOKI Projects" / "Comics" / "robot-painter" and (folder / "BRIEF.md").is_file(), made)
job = bstate.jobs.store.get(made["job"]["id"])
check("... the agent's brief: a script, every panel drawn with make_image, pages put together, checked",
      "SCRIPT.md" in job["prompt"] and "make_image" in job["prompt"] and "index.html" in job["prompt"]
      and str(folder) in job["prompt"] and "never say it is done when it is not" in job["prompt"], job["prompt"][:300])
check("... it is real work, not a throwaway: it runs in that folder (not an isolated copy), 6 h allowed",
      job["workspace"] == str(folder) and not job["isolate"] and job["timeout_s"] == 6 * 3600 and job["make_kind"] == "comic", job)
code, again = call("POST", "/studio/make", {"kind": "comic", "brief": "another one", "name": "Robot Painter"})
check("the same name twice: a second folder (robot-painter-2), never over the first", again["folder"].endswith("robot-painter-2"), again)
for kind, word in (("art", "make_image"), ("painting", "medium"), ("3d", "make_3d"), ("novel", "chapters/"), ("website", "index.html"), ("game", "GAME_PLAN.md")):
    code, r = call("POST", "/studio/make", {"kind": kind, "brief": "something good"})
    j = bstate.jobs.store.get(r["job"]["id"]) if r.get("ok") else {}
    check("Make %s: a job whose brief has %s" % (kind, word), code == 200 and word in j.get("prompt", ""), r)
code, bad = call("POST", "/studio/make", {"kind": "bakery", "brief": "x"})
check("an unknown kind is refused with the list", code == 400 and "make one of" in bad["error"], bad)
code, bad = call("POST", "/studio/make", {"kind": "art", "brief": ""})
check("no brief is refused", code == 400, bad)

# ---- the view: the agents at work, then Stop and Again
bstate.jobs.tick()
time.sleep(0.2)
code, v = call("GET", "/studio/agents")
mine = [a for a in v["agents"] if a.get("job") == made["job"]["id"]]
check("the view lists the comic job as an agent at work, with its machine, its kind and a Stop", mine
      and mine[0]["machine"] == peers.my_name() and mine[0]["kind"] == "comic" and mine[0]["can_stop"], v["agents"][:2])
code, st = call("POST", "/studio/agents/stop", {"job": made["job"]["id"]})
check("Stop: the job is cancelled here, its backend told to stop", code == 200 and st["job"]["status"] == "cancelled"
      and made["job"]["id"] in FakeBackend.stopped, st)
code, ag = call("POST", "/studio/agents/again", {"job": made["job"]["id"]})
new = bstate.jobs.store.get(ag["job"]["id"]) if ag.get("ok") else {}
check("Again: a fresh job with the same brief and folder", code == 200 and new.get("prompt") == job["prompt"]
      and new.get("workspace") == job["workspace"] and new["id"] != job["id"], ag)
code, bad = call("POST", "/studio/agents/stop", {"job": "nope"})
check("Stop on a job that is not here says so", code == 400, bad)

# ---- another machine: its agents in the view, a Stop goes there
calls = []


def fake_call(peer, method, path, payload=None, **kw):
    calls.append((peer["name"], method, path))
    if path == "/peer/world":
        return {"ok": True, "agents": [{"id": "job-p1", "name": "Builder", "state": "working", "task": "Art: castle",
                                        "job": "p1", "kind": "art", "can_stop": True}]}
    if path == "/peer/jobs/p1/cancel":
        return {"ok": True, "job": {"id": "p1", "status": "cancelled"}}
    if path == "/peer/jobs":
        return {"ok": True, "job": {"id": "p2", "status": "queued"}}
    return {"ok": True}


peers.call = fake_call
peer_link.peers.call = fake_call
os.environ["LOKI_PEERS"] = "pc=http://192.168.1.20:8770"
peer_link.peers.status_all = lambda env=None, opener=None: [{"name": "pc", "url": "http://192.168.1.20:8770", "ok": True,
                                                              "ms": 12, "hello": {"machine": {"os": "Windows"}, "jobs": {"working": 1}}}]
peer_link._MACHINES_LIVE.update(t=0, busy=False, list=[])
peer_link.machines_live()
for _ in range(50):
    if peer_link._MACHINES_LIVE["list"]:
        break
    time.sleep(0.05)
code, v = call("GET", "/studio/agents")
pc = [m for m in v["machines"] if m["name"] == "pc"]
remote = [a for a in v["agents"] if a.get("machine") == "pc"]
check("a linked PC shows as a machine (Windows, 1 working) and the hint is gone", pc and pc[0]["os"] == "Windows"
      and pc[0]["working"] == 1 and not v["hint"], v["machines"])
check("... its agents show in the view, marked as on the PC", remote and remote[0]["task"] == "Art: castle" and remote[0]["remote"], remote)
code, st = call("POST", "/studio/agents/stop", {"machine": "pc", "job": "p1"})
check("Stop on the PC's agent goes to the PC (/peer/jobs/p1/cancel)", code == 200 and st["ok"] and ("pc", "POST", "/peer/jobs/p1/cancel") in calls, (st, calls[-3:]))
code, r = call("POST", "/studio/make", {"kind": "3d", "brief": "a stone golem", "machine": "pc"})
check("Make on the PC: the job is sent there (/peer/jobs) with the 3D brief", code == 200 and r["ok"] and r["machine"] == "pc"
      and ("pc", "POST", "/peer/jobs") in calls, r)

# ---- what this machine shows a linked one
w = studio_agents.world_for_peer(bstate)
check("what a linked machine sees of us: the agents, no prompts", isinstance(w["agents"], list) and all("prompt" not in a for a in w["agents"]), w)
check("the peer server answers GET /peer/world", "/peer/world" in open(REPO / "engine" / "peers.py", encoding="utf-8").read())

server.shutdown()
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
