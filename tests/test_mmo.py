"""LOKI World as an MMO - offline checks: the in-app client files, the presence hub between
machines (over a real signed peer link on loopback), the game-state API (quests from jobs,
monsters from failures, loot from creations, LOKI-action skills), the bridge routes, perf guards.

    python tests/test_mmo.py

Screenshots (not part of the suites): python tests/mmo_preview/shot.py <dir>
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import mmo_state  # noqa: E402
import peers  # noqa: E402
import presence  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


def free_port() -> int:
    """A free loopback port (port_number=0 would mean LOKI's default 8768, maybe a real listener)."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


UI = REPO / "app" / "ui"
html = (UI / "index.html").read_text(encoding="utf-8")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")

# ------------------------------------------------------------------------------------------
section("the in-app JS client is gone: the Godot game is LOKI World (2026-10-18)")
check("no app/ui/mmo, no mmo_core.js in the window", not (UI / "mmo").exists() and "mmo_core" not in html)

# ------------------------------------------------------------------------------------------
section("presence: sanitising")
p = presence.clean_player({"name": "Mo\x00ha‮med" + "x" * 50, "u": 99, "v": "nan", "lvl": 500, "hp": -3,
                           "color": "red;}", "zone": "pc", "ry": 1.5, "emote": "wave"})
check("control/bidi characters gone, lengths capped", "\x00" not in p["name"] and "‮" not in p["name"] and len(p["name"]) <= 24)
check("numbers clamped (u, lvl, hp), NaN -> 0, bad colour dropped", p["u"] == 1.5 and p["v"] == 0 and p["lvl"] == 99
      and p["hp"] == 0 and p["color"] == "")
check("not a dict -> None", presence.clean_player("x") is None and presence.clean_player(None) is None)

section("presence: two machines over the real signed peer link")
clock = {"t": 1000.0}
MAC = presence.Presence(lambda: "mac", clock=lambda: clock["t"])
PCH = presence.Presence(lambda: "pc", clock=lambda: clock["t"])
SECRET = "s" * 40
server = peers.PeerServer({"hello": lambda: {}, "presence": PCH.receive}, env={"LOKI_PEER_SECRET": SECRET},
                          host="127.0.0.1", port_number=free_port()).start()
PEER = {"name": "pc", "url": "http://127.0.0.1:%d" % server.address[1]}
mac_env = {"LOKI_PEER_SECRET": SECRET, "LOKI_PEER_NAME": "mac"}


def mac_call(peer, method, path, payload=None, timeout=4.0):
    return peers.call(peer, method, path, payload, env=mac_env, timeout=timeout)


try:
    check("nothing is pushed while the world is closed", MAC.due(["pc"]) == [])
    snap = MAC.update_local({"player": {"name": "Mohamed", "cls": "Mage", "lvl": 7, "zone": "mac", "u": 0.1, "v": -0.2, "ry": 1}})
    check("the app gets a snapshot back (players, chat, cursor)", snap["ok"] and snap["players"] == [] and "cursor" in snap)
    PCH.update_local({"player": {"name": "Mohamed", "cls": "Warrior", "lvl": 5, "zone": "pc", "u": 0.5, "v": 0.5}, "chat": "hi from the PC"})
    check("the Mac's world is open and it moved: the PC is due", MAC.due(["pc"]) == ["pc"])
    MAC.update_local({"chat": "hello from the Mac"})
    ok = MAC.push_once(PEER, mac_call)
    check("one signed exchange succeeds", ok, MAC.errors)
    pc_view = PCH.snapshot(0)
    mac_view = MAC.snapshot(0)
    check("the PC sees the Mac's avatar (keyed by the machine's own name)", [x["machine"] for x in pc_view["players"]] == ["mac"]
          and pc_view["players"][0]["cls"] == "Mage" and pc_view["players"][0]["lvl"] == 7, pc_view)
    check("...and the Mac sees the PC's in the SAME call (works when only one side can dial)",
          [x["machine"] for x in mac_view["players"]] == ["pc"] and mac_view["players"][0]["u"] == 0.5, mac_view)
    check("chat travels both ways", any(c["text"] == "hello from the Mac" and c["machine"] == "mac" for c in pc_view["chat"])
          and any(c["text"] == "hi from the PC" and c["machine"] == "pc" for c in mac_view["chat"]), (pc_view["chat"], mac_view["chat"]))
    MAC.push_once(PEER, mac_call)
    again = PCH.snapshot(0)["chat"] + MAC.snapshot(0)["chat"]
    check("lines are never delivered twice", len(again) == 4, again)
    cur = MAC.snapshot(0)["cursor"]
    MAC.update_local({"chat": "third"})
    check("the app asks only for lines after its cursor", [c["text"] for c in MAC.snapshot(cur)["chat"]] == ["third"])
    clock["t"] += max(presence.REMOTE_FRESH_S, presence.PUSH_IDLE_S) + 1
    check("an avatar not heard from for a while is gone", PCH.snapshot(0)["players"] == [] and MAC.snapshot(0)["players"] == [])
    check("and pushing stops once the app stops posting", MAC.due(["pc"]) == [])
    MAC.update_local({"player": {"name": "Mohamed", "zone": "mac"}})
    bad = {"name": "pc", "url": "http://127.0.0.1:9"}
    check("an unreachable peer: no exception, backed off", MAC.push_once(bad, mac_call) is False and "pc" in MAC.errors
          and MAC.due(["pc"]) == [])
    try:
        peers.call(PEER, "POST", "/peer/presence", {"player": {}}, env={**mac_env, "LOKI_PEER_SECRET": "x" * 40})
        check("a wrong secret is refused", False)
    except peers.PeerError as exc:
        check("a wrong secret is refused", "401" in str(exc), exc)
    no_cb = peers.PeerServer({"hello": lambda: {}}, env={"LOKI_PEER_SECRET": SECRET}, host="127.0.0.1", port_number=free_port()).start()
    try:
        peers.call({"name": "old", "url": "http://127.0.0.1:%d" % no_cb.address[1]}, "POST", "/peer/presence", {}, env=mac_env)
        check("an older LOKI without presence answers 404 (no crash)", False)
    except peers.PeerError as exc:
        check("an older LOKI without presence answers 404 (no crash)", "404" in str(exc), exc)
    no_cb.stop()
finally:
    server.stop()
check("peer_link wires /peer/presence to the hub", '"presence": _presence_receive' in (REPO / "engine" / "peer_link.py").read_text(encoding="utf-8"))

section("retry a failed job: same prompt, a new model, never new powers")
spec = presence.retry_spec({"id": "a", "status": "failed", "prompt": "do it", "backend": "local", "agent": "loki",
                            "allow_commands": True, "timeout_s": 600, "title": "do it"}, "online")
check("prompt kept, model set, allow_commands NOT copied", spec["prompt"] == "do it" and spec["model"] == "online"
      and "allow_commands" not in spec and spec["title"].startswith("Retry:"))
for job, why in ((None, "missing"), ({"status": "working", "prompt": "x"}, "still running")):
    try:
        presence.retry_spec(job)
        check("retry refuses a job that is %s" % why, False)
    except ValueError:
        check("retry refuses a job that is %s" % why, True)

# ------------------------------------------------------------------------------------------
section("game state: quests, monsters, loot, NPCs, skills")
TMP = Path(tempfile.mkdtemp(prefix="loki-mmo-"))
now = time.time()


def job(jid, status, title, prompt="", error="", agent="loki", created=None, started=None, finished=None):
    return {"id": jid, "status": status, "title": title, "prompt": prompt or title, "error": error, "agent": agent,
            "backend": "local", "created": created or now - 3000, "started": started or now - 2900,
            "finished": finished if finished is not None else (now - 100 if status in ("done", "failed") else 0)}


OLD = [job("old1", "done", "Research: old"), job("old2", "failed", "x", error="timed out", finished=now - 50),
       job("old3", "failed", "y", error="boom", finished=now - 60), job("old4", "failed", "z", finished=now - 70),
       job("old5", "failed", "w", finished=now - 80)]
CRE = [{"path": "images/fox.jpg", "title": "fox", "kind": "images", "show": "image", "t": now - 5000}]
prof = mmo_state.Profile(TMP / "mmo" / "profile.json")
st = mmo_state.build_state(prof, OLD, CRE, [{"id": "loki", "name": "LOKI", "state": "idle"}], {"name": "mac", "os": "Darwin"})
check("first run: past work counts (XP for done jobs and creations)", st.get("welcome", {}).get("xp") == 60 + 15
      and st["profile"]["xp"] == 75, st.get("welcome"))
check("...old done jobs are already turned in, old creations already in the bags",
      [q["status"] for q in st["quests"] if q["id"] == "old1"] == ["turned_in"] and not st["loot"]["items"][0]["new"])
check("...only the newest 3 failures become monsters", sorted(m["id"] for m in st["monsters"]) == ["old2", "old3", "old4"], st["monsters"])
check("a Mac player starts as a Mage", st["profile"]["cls"] == "Mage")
check("the profile is saved in the data folder (never in the repo)", (TMP / "mmo" / "profile.json").is_file())
check("welcome happens once", "welcome" not in mmo_state.build_state(prof, OLD, CRE, [], {"name": "mac"}))

mon = next(m for m in st["monsters"] if m["id"] == "old2")
check("a timeout becomes a Timeout Wraith with level, hp, damage, spawn on this island",
      mon["name"] == "Timeout Wraith" and mon["hp_max"] > 0 and mon["spawn"]["zone"] == "mac" and abs(mon["spawn"]["u"]) <= 0.83, mon)
check("monster spawn spots are stable (from the job id)", mmo_state.monster_for(OLD[1], 3, "mac")["spawn"] == mmo_state.monster_for(OLD[1], 3, "mac")["spawn"])

JOBS = OLD + [job("n1", "working", "Make an image of a cat", prompt="Make an image of a cat. Save it"),
              job("n2", "done", "Research: tea", prompt="Research: tea. Find", started=now - 400, finished=now - 30)]
CRE2 = CRE + [{"path": "images/cat.png", "title": "cat", "kind": "images", "show": "image", "t": now - 200}]
agents = [{"id": "loki", "name": "LOKI", "state": "working"}, {"id": "job-n1", "name": "Loki agent", "state": "working"}]
st = mmo_state.build_state(prof, JOBS, CRE2, agents, {"name": "mac", "os": "Darwin"})
q = {x["id"]: x for x in st["quests"]}
check("a running job is an active quest, a finished one is complete", q["n1"]["status"] == "active" and q["n1"]["kind"] == "image"
      and q["n2"]["status"] == "complete" and q["n2"]["kind"] == "research", q)
check("the new creation is new loot", [i["new"] for i in st["loot"]["items"] if i["id"] == "images/cat.png"] == [True]
      and st["loot"]["items"][0]["url"].startswith("/creations/"))
npc = {x["id"]: x for x in st["npcs"]}
check("NPCs: LOKI is the quest giver (Trickster), agents get a class from their role and a level from finished jobs",
      npc["loki"]["quest_giver"] and npc["loki"]["class"]["name"] == "Trickster" and npc["job-n1"]["class"]["name"] == "Smith"
      and npc["job-n1"]["jobs_done"] == 2 and npc["job-n1"]["energy"] == 1.0, npc)
check("skills: 9 slots, LOKI actions are real jobs", [s["slot"] for s in st["skills"]] == list(range(1, 10))
      and mmo_state.LOKI_ACTIONS == {"image", "research", "build", "video", "game"})

r = mmo_state.turn_in(prof, JOBS, CRE2, "n2")
check("turning in: XP and the picture made while the job ran", r["turned_in"] == ["n2"] and r["xp"] >= 100
      and [i["id"] for i in r["loot"] if i.get("kind") != "gear"] == ["images/cat.png"], r)
try:
    mmo_state.turn_in(prof, JOBS, CRE2, "n2")
    check("a quest cannot be turned in twice", False)
except ValueError:
    check("a quest cannot be turned in twice", True)
d = mmo_state.defeat(prof, JOBS, "old2")
check("defeating a monster: XP, a lesson scroll with the error, a retry offer", d["xp"] > 0 and "timed out" in d["loot"][0]["text"]
      and d["retry"]["id"] == "old2", d)
check("...and it is gone from the world", "old2" not in [m["id"] for m in mmo_state.build_state(prof, JOBS, CRE2, [], {"name": "mac"})["monsters"]])
for bad_id in ("old2", "n1", "nope"):
    try:
        mmo_state.defeat(prof, JOBS, bad_id)
        check("defeat refuses %s" % bad_id, False)
    except ValueError:
        check("defeat refuses %s" % bad_id, True)
check("level curve grows", mmo_state.level_of(0)["level"] == 1 and mmo_state.level_of(10000)["level"] >= 10)
check("level-up is reported", mmo_state._grant(prof, 5000)["level_up"])

section("LOKI-action skills start the same jobs as Settings > Creations")
check("picture prompt = Creations' words", mmo_state.action_prompt("image", "a fox") ==
      "Make an image of a fox. Save it in images/ and say where it is.")
spec = mmo_state.job_spec("research", "tea")
check("job spec: built-in agent, isolated worktree", spec["agent"] == "loki" and spec["isolate"] and spec["prompt"].startswith("Research: tea"))
for bad in (("image", "  "), ("strike", "x")):
    try:
        mmo_state.action_prompt(*bad)
        check("refused: %r" % (bad,), False)
    except ValueError:
        check("refused: %r" % (bad,), True)
try:
    mmo_state.set_profile(prof, {"cls": "Necromancer"})
    check("unknown class refused", False)
except ValueError:
    check("unknown class refused", True)
upd = mmo_state.set_profile(prof, {"name": "Mo", "cls": "Archer"})
check("profile update", upd["name"] == "Mo" and upd["cls"] == "Archer")

# ------------------------------------------------------------------------------------------
section("the bridge routes (a fake engine state)")


class Store:
    def __init__(self, jobs):
        self.jobs = {j["id"]: j for j in jobs}

    def all(self):
        return list(self.jobs.values())

    def get(self, jid):
        return self.jobs.get(jid)


class Agent:
    DATA_DIR = str(TMP / "engine")
    WORKSPACE = str(TMP / "ws")


class State:
    agent = Agent()
    chat_lock = None


class Jobs:
    store = Store(JOBS)


State.jobs = Jobs()
made = []


def fake_job_action(state, route, spec):
    made.append(spec)
    return 200, {"ok": True, "id": "new%d" % len(made)}


code, out = mmo_state.route(State(), "GET", "/mmo/state", {}, fake_job_action)
check("GET /mmo/state answers the whole game", code == 200 and all(k in out for k in ("profile", "quests", "monsters", "npcs", "loot", "skills", "presence", "zones")), out.keys())
check("it is JSON-serialisable", bool(json.dumps(out)))
code, out = mmo_state.route(State(), "POST", "/mmo/skill", {"skill": "image", "text": "a fox in snow"}, fake_job_action)
check("POST /mmo/skill image -> a real job through the bridge's job_action", code == 200 and out["quest"]["id"] == "new1"
      and made[-1]["prompt"].startswith("Make an image of a fox in snow"), out)
code, out = mmo_state.route(State(), "POST", "/mmo/skill", {"skill": "strike"}, fake_job_action)
check("combat skills are not jobs (400, says why)", code == 400 and "client" in out["error"])
code, out = mmo_state.route(State(), "POST", "/mmo/monster/retry", {"id": "old3", "model": "online"}, fake_job_action)
check("POST /mmo/monster/retry starts the job again on the model and beats the monster", code == 200
      and made[-1]["model"] == "online" and made[-1]["prompt"] == "y" and out.get("monster"), out)
code, out = mmo_state.route(State(), "POST", "/mmo/quest/turnin", {"all": True}, fake_job_action)
check("nothing left to turn in -> 400", code == 400)
code, out = mmo_state.route(State(), "POST", "/mmo/note", {"death": True, "seen": ["images/cat.png"]}, fake_job_action)
check("POST /mmo/note counts a death", code == 200 and out["stats"]["deaths"] == 1)
check("unknown /mmo route -> 404", mmo_state.route(State(), "POST", "/mmo/nope", {}, fake_job_action)[0] == 404)
check("loki_bridge routes /mmo/* (GET and POST) and /world/presence", bridge.count('route.startswith("/mmo/")') == 2
      and 'route == "/world/presence"' in bridge and '"/world/presence", "/world/retry"' in bridge
      and 'out["presence"] = presence.world_part()' in bridge)
check("ship.py runs this suite", '"test_mmo"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
check("the contract for clients exists", (REPO / "docs" / "MMO_API.md").is_file())

section("end to end through the real bridge HTTP server")
import http.client  # noqa: E402
import threading  # noqa: E402

import loki_bridge  # noqa: E402

loki_bridge.PORT = 0
bstate = loki_bridge.BridgeState(Agent(), "mmo-secret")
bstate.jobs = Jobs()
bserver = loki_bridge.BridgeHTTPServer(bstate)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def http_call(method, path, body=None, token="mmo-secret"):
    conn = http.client.HTTPConnection("127.0.0.1", bserver.server_address[1], timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")


try:
    code, out = http_call("GET", "/mmo/state")
    check("GET /mmo/state over HTTP", code == 200 and out.get("ok") and out["profile"]["level"] >= 1, (code, str(out)[:200]))
    check("a wrong token is refused (401)", http_call("GET", "/mmo/state", token="nope")[0] == 401)
    code, out = http_call("POST", "/mmo/profile", {"name": "Mo2"})
    check("POST /mmo/profile over HTTP", code == 200 and out["name"] == "Mo2", (code, out))
    code, out = http_call("POST", "/world/presence", {"player": {"name": "Mo2", "zone": "mac", "u": 0.1}, "chat": "e2e line"})
    check("POST /world/presence over HTTP answers players/chat/cursor", code == 200 and out["chat"][-1]["text"] == "e2e line"
          and "players" in out, (code, out))
    code, out = http_call("GET", "/world/presence?after=0")
    check("GET /world/presence?after= over HTTP", code == 200 and any(c["text"] == "e2e line" for c in out["chat"]), (code, out))
    code, out = http_call("POST", "/world/retry", {"id": "n1"})
    check("POST /world/retry refuses a job that is still running", code == 400, (code, out))
finally:
    bserver.shutdown()
    bserver.server_close()

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
