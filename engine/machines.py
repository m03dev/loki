"""The agent's hands on your other machines (owner 2026-10-25 11:57: "i just asked my loki in windows to help mac and it
didn't understand me... they cant even talk to eachother").

LOKI's machines were linked for files, memory and updates, but the AGENT had no way to talk to the other one. These are
its tools - for OpenCode through engine/make_mcp.py, and for LOKI's own tool loop (loki.py "machines"):

  list_machines                       this machine and every linked one: online or not, its OS, what it is doing
  run_on_machine {machine, task}      hand a task to the other machine's LOKI: it runs there as a background job (its
                                      own agent, its own folder, bounded time) and shows in Studio > Agents on both
  machine_job    {machine, job}       how that job is going, and its result when it is done (wait= up to 120 s)
  stop_machine_job {machine, job}     stop it

Nothing linked -> every tool says so plainly and how to link (a link code from the other machine), never a guess.
The link itself is peers.py: signed requests, private network or the relay, the other machine decides HOW a task runs.
"""
from __future__ import annotations

import platform
import time
from typing import Any

import peers

HOW_TO_LINK = ("No other machine is linked to this LOKI yet, so I can't reach it. To link them: on the other machine "
               "open LOKI > Studio > Agents (or Settings > Machines) and turn on 'Let my other machines link' - it "
               "shows a link code - then paste that code here in Studio > Agents > Link a machine. After that I can "
               "hand it work and check on it.")


def _clean_id(job: str) -> str:
    return "".join(ch for ch in str(job or "") if ch.isalnum())[:16]


def _resolve(name: str) -> dict:
    """A linked machine by name; case and 'the mac'/'my pc' style words forgiven. Raises with the choices."""
    linked = peers.peers()
    if not linked:
        raise LookupError(HOW_TO_LINK)
    want = str(name or "").strip().lower()
    for word in ("the ", "my ", "machine", "computer"):
        want = want.replace(word, "")
    want = want.strip()
    if not want and len(linked) == 1:
        return linked[0]
    for p in linked:
        if p["name"].lower() == want:
            return p
    for p in linked:   # "mac" -> "mohameds-mac-mini", "windows"/"pc" -> "pc"
        n = p["name"].lower()
        if want and (want in n or n in want):
            return p
    if want in ("windows", "win", "pc", "mac", "macos", "laptop", "desktop") and len(linked) == 1:
        return linked[0]
    raise LookupError("No linked machine called '%s'. Linked: %s." % (name, ", ".join(p["name"] for p in linked)))


def list_machines(args: dict | None = None, call=None) -> dict:
    call = call or peers.call
    me = {"name": peers.my_name(), "this_machine": True, "os": platform.system(), "online": True}
    out = [me]
    for p in peers.peers():
        row = {"name": p["name"], "this_machine": False, "relay": bool(p.get("relay"))}
        try:
            hello = call(p, "GET", "/peer/hello", timeout=5.0)
            jobs = hello.get("jobs") or {}
            row.update(online=True, os=(hello.get("machine") or {}).get("os", ""),
                       version=(hello.get("version") or {}).get("label", ""),
                       working=int(jobs.get("working", 0) or 0), queued=int(jobs.get("queued", 0) or 0),
                       can=[c.get("name") if isinstance(c, dict) else c for c in (hello.get("capabilities") or [])][:12])
        except Exception as exc:  # noqa: BLE001 - one machine down never hides the others
            row.update(online=False, error=str(exc)[:200])
        out.append(row)
    res = {"ok": True, "machines": out}
    if len(out) == 1:
        res["note"] = HOW_TO_LINK
    return res


def run_on_machine(args: dict, call=None) -> dict:
    call = call or peers.call
    task = str(args.get("task") or args.get("prompt") or "").strip()
    if len(task) < 3:
        return {"ok": False, "error": "say what the other machine should do (task)"}
    try:
        p = _resolve(str(args.get("machine") or ""))
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}
    payload = {"prompt": task[:16000], "title": str(args.get("title") or task.splitlines()[0])[:60],
               "timeout_s": max(60, min(int(args.get("timeout_s") or 3600), 6 * 3600))}
    try:
        got = call(p, "POST", "/peer/jobs", payload, timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "machine": p["name"], "error": "%s did not answer: %s (is LOKI open there, and online?)"
                % (p["name"], str(exc)[:200])}
    job = got.get("job") or {}
    if not got.get("ok") or not job.get("id"):
        return {"ok": False, "machine": p["name"], "error": str(got.get("error") or "it did not take the job")[:300]}
    return {"ok": True, "machine": p["name"], "job": job.get("id"), "status": job.get("status"),
            "note": "Running on %s as job %s - it shows in Studio > Agents there and here. Check it with machine_job."
                    % (p["name"], job.get("id"))}


def machine_job(args: dict, call=None, sleep=time.sleep) -> dict:
    call = call or peers.call
    jid = _clean_id(args.get("job"))
    if not jid:
        return {"ok": False, "error": "which job? (the id run_on_machine gave)"}
    try:
        p = _resolve(str(args.get("machine") or ""))
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}
    deadline = time.time() + max(0, min(float(args.get("wait") or 0), 120))
    while True:
        try:
            job = (call(p, "GET", "/peer/jobs/%s" % jid, timeout=10.0) or {}).get("job") or {}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "machine": p["name"], "error": "%s did not answer: %s" % (p["name"], str(exc)[:200])}
        done = job.get("status") in ("done", "failed", "cancelled", "blocked", "timeout")
        if done or time.time() >= deadline:
            break
        sleep(3)
    return {"ok": bool(job), "machine": p["name"], "job": jid, "status": job.get("status"), "done": done,
            "result": str(job.get("output") or "")[-6000:], "error": job.get("error") or "", "note": job.get("note") or ""}


def stop_machine_job(args: dict, call=None) -> dict:
    call = call or peers.call
    jid = _clean_id(args.get("job"))
    try:
        p = _resolve(str(args.get("machine") or ""))
        got = call(p, "POST", "/peer/jobs/%s/cancel" % jid, {}, timeout=10.0)
    except LookupError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": bool(got.get("ok")), "machine": p["name"], "job": jid, "status": (got.get("job") or {}).get("status")}


TOOLS = [
    {"name": "list_machines",
     "description": "The owner's LOKI machines (this one and every linked one, e.g. the Mac and the Windows PC): "
                    "online or not, OS, what each is doing. Use it when the owner mentions another machine.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "run_on_machine",
     "description": "Hand a task to the owner's OTHER machine (machine= its name, or 'mac' / 'pc'): its own LOKI "
                    "agent does it there as a background job, with that machine's files, apps and GPU. Write the task "
                    "fully - it does not see this chat. Returns a job id; check it with machine_job.",
     "inputSchema": {"type": "object", "properties": {
         "machine": {"type": "string"}, "task": {"type": "string"}, "title": {"type": "string"},
         "timeout_s": {"type": "integer"}}, "required": ["task"]}},
    {"name": "machine_job",
     "description": "How a job on another machine is going, and its result when done. wait= seconds (up to 120) to "
                    "wait for it to finish.",
     "inputSchema": {"type": "object", "properties": {
         "machine": {"type": "string"}, "job": {"type": "string"}, "wait": {"type": "number"}}, "required": ["job"]}},
    {"name": "stop_machine_job",
     "description": "Stop a job running on another machine.",
     "inputSchema": {"type": "object", "properties": {
         "machine": {"type": "string"}, "job": {"type": "string"}}, "required": ["job"]}},
]
FUNCS = {"list_machines": list_machines, "run_on_machine": run_on_machine, "machine_job": machine_job,
         "stop_machine_job": stop_machine_job}


def tool(args: dict) -> dict:
    """LOKI's own tool loop: {"action": "list"|"run"|"status"|"stop", ...}."""
    action = str(args.get("action") or "list").lower()
    fn = {"list": list_machines, "run": run_on_machine, "send": run_on_machine, "status": machine_job,
          "result": machine_job, "stop": stop_machine_job}.get(action)
    if fn is None:
        return {"ok": False, "error": "action is list, run, status or stop"}
    return fn(args)


def describe(state: Any = None) -> str:  # noqa: ARG001
    """What every agent turn is told about the owner's machines (OpenCode's instructions file, LOKI's own prompt)."""
    me = "This machine: %s (%s)." % (peers.my_name(), platform.system() or "?")
    linked = [p["name"] for p in peers.peers()]
    rule = ("Whenever the owner means another computer or device - the Mac, the PC, Windows, 'my other machine', "
            "'help mac', 'the laptop', whatever the words - call list_machines FIRST to see what is linked and online. "
            "Never guess, and never say you can't reach it before you have looked. To do something there, "
            "run_on_machine with the full task (that machine's own LOKI does it), then machine_job to follow it and "
            "report the result.")
    if not linked:
        return me + " No other machine is linked yet - if the owner asks for one, list_machines says how to link.\n" + rule
    return me + " Linked: %s.\n%s" % (", ".join(linked), rule)
