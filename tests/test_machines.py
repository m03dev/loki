"""The agent talks to the owner's other machine (engine/machines.py; owner 2026-10-25 11:57: "i just asked my loki in
windows to help mac and it didn't understand me... they cant even talk to eachother").

A real peer server on 127.0.0.1 plays the Mac (signed HTTP, as in tests/test_peers.py). From "the PC": list_machines
sees it online; run_on_machine hands it a task -> a job there; machine_job waits for and returns the result;
stop_machine_job stops one; 'mac' finds "mohameds-mac-mini"; nothing linked -> the plain how-to-link answer. The same
tools are in OpenCode's loki-make MCP server and in LOKI's own tool loop. Under a minute.

    python tests/test_machines.py
"""
from __future__ import annotations

import io
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
os.environ["LOKI_DATA"] = tempfile.mkdtemp(prefix="loki-machines-")
for k in ("LOKI_PEERS", "LOKI_PEER_SECRET", "LOKI_PEER_NAME"):
    os.environ.pop(k, None)
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import machines  # noqa: E402
import make_mcp  # noqa: E402
import peers  # noqa: E402

r = machines.list_machines()
check("nothing linked: only this machine, and how to link", len(r["machines"]) == 1 and "link code" in r.get("note", ""), r)
r = machines.run_on_machine({"machine": "mac", "task": "check the disk"})
check("... a task for the other machine says plainly it is not linked (no guess)", not r["ok"] and "No other machine is linked" in r["error"], r)

SECRET = secrets.token_hex(24)
JOBS: dict = {}


def create_job(spec):
    jid = "j%d" % (len(JOBS) + 1)
    JOBS[jid] = {"id": jid, "title": spec["title"], "status": "working", "prompt": spec["prompt"], "output": ""}

    def finish():
        time.sleep(1.0)
        if JOBS[jid]["status"] == "working":
            JOBS[jid].update(status="done", output="DONE: the Mac's disk has 212 GB free.")
    threading.Thread(target=finish, daemon=True).start()
    return {k: JOBS[jid][k] for k in ("id", "title", "status")}


def cancel(jid):
    if jid not in JOBS:
        return None
    JOBS[jid]["status"] = "cancelled"
    return JOBS[jid]


callbacks = {"hello": lambda: {"name": "mohameds-mac-mini", "machine": {"os": "Darwin"}, "jobs": {"working": 1},
                               "version": {"label": "v9"}},
             "create_job": create_job, "get_job": lambda jid: JOBS.get(jid), "cancel_job": cancel,
             "receive_experience": lambda o, i: {}}
server = peers.PeerServer(callbacks, env={"LOKI_PEER_SECRET": SECRET}, host="127.0.0.1", port_number=0).start()
os.environ["LOKI_PEERS"] = "mohameds-mac-mini=http://127.0.0.1:%d" % server.address[1]
os.environ["LOKI_PEER_SECRET"] = SECRET
os.environ["LOKI_PEER_NAME"] = "pc"
try:
    r = machines.list_machines()
    mac = [m for m in r["machines"] if not m["this_machine"]]
    check("list_machines: this PC and the linked Mac, online, its OS and work", r["machines"][0]["name"] == "pc" and mac
          and mac[0]["online"] and mac[0]["os"] == "Darwin" and mac[0]["working"] == 1 and "note" not in r, r)
    r = machines.run_on_machine({"machine": "the mac", "task": "How much disk space is free on this Mac? Report it."})
    check("run_on_machine 'the mac': a job there with the task as written", r["ok"] and r["machine"] == "mohameds-mac-mini"
          and JOBS[r["job"]]["prompt"].startswith("How much disk space"), r)
    jid = r["job"]
    r = machines.machine_job({"machine": "mac", "job": jid})
    check("machine_job right away: still working", r["ok"] and r["status"] == "working" and not r["done"], r)
    r = machines.machine_job({"machine": "mac", "job": jid, "wait": 10})
    check("machine_job wait=10: done, with the Mac's result", r["done"] and "212 GB free" in r["result"], r)
    r2 = machines.run_on_machine({"machine": "mac", "task": "render the big scene"})
    r = machines.stop_machine_job({"machine": "mac", "job": r2["job"]})
    check("stop_machine_job stops it there", r["ok"] and JOBS[r2["job"]]["status"] == "cancelled", r)
    r = machines.run_on_machine({"machine": "linux-box", "task": "anything"})
    check("an unknown machine name: the linked ones listed", not r["ok"] and "mohameds-mac-mini" in r["error"], r)

    # OpenCode's MCP server lists and runs them
    names = [t["name"] for t in make_mcp.TOOLS]
    check("loki-make MCP lists list_machines / run_on_machine / machine_job / stop_machine_job",
          all(n in names for n in ("list_machines", "run_on_machine", "machine_job", "stop_machine_job")), names)
    out = io.StringIO()
    make_mcp.serve(io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                           "params": {"name": "list_machines", "arguments": {}}}) + "\n"), out, Path("."))
    res = json.loads(out.getvalue())["result"]
    check("... a tools/call answers with the machines", not res["isError"] and "mohameds-mac-mini" in res["content"][0]["text"], res)
    check("LOKI's own tool: machines {action: run}", machines.tool({"action": "run", "machine": "mac", "task": "say hi"})["ok"])
    d = machines.describe()
    check("describe (told every turn): this machine, the linked Mac, and to call list_machines first",
          "This machine: pc" in d and "mohameds-mac-mini" in d and "list_machines FIRST" in d, d)
finally:
    server.stop()
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
