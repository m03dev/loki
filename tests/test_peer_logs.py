"""Every machine's logs on every machine (engine/peer_logs.py; owner 2026-10-28: "since loki is linked to the other
devices it should also share logs between them that way you dont need to be on all devices"). No network:
  - a snapshot has the log tails, the window errors, failed jobs, the version - with keys masked
  - pull() saves this machine's and every linked machine's snapshot as plain files in <data>/machine_logs/<name>/
  - a machine that does not answer (or runs an older LOKI) is reported, the others still come in
  - the peer server answers GET /peer/logs through the callback

    python tests/test_peer_logs.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
DATA = Path(tempfile.mkdtemp(prefix="loki-peerlogs-"))
os.environ["LOKI_DATA"] = str(DATA)
import peer_logs  # noqa: E402
import peers  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  <- %s" % (detail,)))
    if not ok:
        FAILED.append(name)


app = DATA / "app"
app.mkdir(parents=True)
(app / "engine.out").write_text("start\nkey nvapi-abcdefghijklmnopqrstu used\n[loki-bridge] window error: TypeError: x is null\n"
                                "token=supersecretvalue99 here\nend\n", encoding="utf-8")
(app / "loki_app.log").write_text("app line\n", encoding="utf-8")
(app / "loki_bridge.log").write_text("bridge line\n", encoding="utf-8")


class Jobs:
    class store:  # noqa: N801
        @staticmethod
        def all():
            return [{"id": "j1", "status": "failed", "title": "make a golem", "error": "Bearer abcdefghijklmnopqrstuvwx refused",
                     "output": "..."}, {"id": "j2", "status": "done"}]


class State:
    jobs = Jobs()


snap = peer_logs.snapshot(State(), None)
flat = json.dumps(snap)
check("snapshot: the log tails are in it", snap["logs"]["engine.out"][0] == "start" and snap["logs"]["app.log"] == ["app line"])
check("snapshot: keys and tokens are masked", "nvapi-abc" not in flat and "supersecretvalue99" not in flat
      and "abcdefghijklmnopqrstuvwx" not in flat and "[key]" in flat)
check("snapshot: window errors picked out", snap["window_errors"] == ["[loki-bridge] window error: TypeError: x is null"])
check("snapshot: failed jobs with their reason", [j["id"] for j in snap["jobs_failed"]] == ["j1"])

calls = []


def fake_call(peer, method, path, payload=None, timeout=10):
    calls.append((peer["name"], method, path))
    if peer["name"] == "pc":
        return {"ok": True, "name": "pc", "time": 1, "logs": {"engine.out": ["pc engine line"], "app.log": [], "bridge.log": []},
                "window_errors": [], "runs": [{"trace_id": "t1"}], "jobs_failed": [], "version": {"commit": "821cf39"}}
    raise ConnectionError("asleep")

peers.peers = lambda env=None: [{"name": "pc", "url": "http://x"}, {"name": "laptop", "url": "http://y"}]
peers.call = fake_call
out = peer_logs.pull(State(), None)
pc = DATA / "machine_logs" / "pc"
check("pull: the PC's logs land in machine_logs/pc", (pc / "engine.out.txt").read_text().strip() == "pc engine line"
      and json.loads((pc / "summary.json").read_text())["commit"] == "821cf39", out)
check("pull: asked with GET /peer/logs", ("pc", "GET", "/peer/logs") in calls)
check("pull: this machine's own logs are there too", any((DATA / "machine_logs" / d / "engine.out.txt").is_file()
                                                         for d in os.listdir(DATA / "machine_logs") if d != "pc"))
check("pull: a machine that is away is reported, the rest still came in", "error" in out.get("laptop", {}) and "pc" in out)


class FakeServer:
    callbacks = {"logs": lambda: {"name": "me", "logs": {"engine.out": []}}}

code, body = peers.PeerServer.route(FakeServer(), "GET", "/peer/logs", {}, "pc")
check("peer server: GET /peer/logs answers through the callback", code == 200 and body["ok"] and body["name"] == "me")
FakeServer.callbacks = {}
code, body = peers.PeerServer.route(FakeServer(), "GET", "/peer/logs", {}, "pc")
check("peer server: without the callback it says so", code == 404)
st, data = peer_logs.ui_route(State(), None, "POST", "/logs/machines")
check("window route: pulls now and lists every machine", st == 200 and "pc" in data["machines"] and data["folder"].endswith("machine_logs"))

print("\n%d failed" % len(FAILED) if FAILED else "\nall passed")
sys.exit(1 if FAILED else 0)
