"""The engine side of the peer link (see peers.py for the protocol and its security).

The bridge calls three things:
    start(state, agent)      start the peer server if LOKI_PEER_LISTEN=1 (else None)
    sync_forever(state, agent)  background: send verified work to the trainer peer, and
                             use the trainer's promoted model when it has one
    ui_route(state, agent, method, route, data) -> (status, payload) | None
                             the loopback API the app's Settings > Machines uses

Nothing here opens a port unless the user turned listening on, on THIS machine.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import experience
import peers

SYNC_EVERY_S = int(os.getenv("LOKI_PEER_SYNC_S", "600"))


# --- writing settings --------------------------------------------------------------

def write_env(path: Path, updates: dict) -> None:
    """Set KEY=value lines in a .env, keeping every other line (and comments) as they are.

    A value of None removes the key. os.environ is updated too, so the change is live.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in updates:
            seen.add(key)
            if updates[key] is not None:
                out.append("%s=%s" % (key, updates[key]))
            continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen and value is not None:
            out.append("%s=%s" % (key, value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)


# --- what this machine tells a peer ------------------------------------------------

def machine_capabilities(agent: Any = None, local_models: list | None = None) -> list:
    """What this machine can really do, backed by installed tools (docs/VISION.md 8)."""
    import shutil  # pylint: disable=import-outside-toplevel
    caps = ["model.chat", "repository.read", "code.edit", "tests.run", "agents.team", "approval.human"]
    if shutil.which("git"):
        caps.append("git")
    caps.append("command.run")
    if local_models:
        caps.append("model.local-inference")
    gpu = peers.describe_machine().get("gpu")
    if gpu:
        caps.append("gpu.cuda")
    try:
        import laya  # pylint: disable=import-outside-toplevel
        if laya.backend():
            caps.append("decision.laya")
    except Exception:  # noqa: BLE001
        pass
    if os.getenv("GODOT_EXE") or shutil.which("godot") or shutil.which("godot4"):
        caps.append("godot.test")
    for exe, cap in (("blender", "blender.inspect"), ("UnrealEditor", "unreal.build"),
                     ("node", "node"), ("docker", "vm.docker"), ("ollama", "ollama")):
        if shutil.which(exe):
            caps.append(cap)
    try:
        registry = getattr(agent, "CAPABILITIES", None)
        for name in ("browser-use", "cua", "crawl4ai", "firecrawl", "hindsight"):
            entry = registry.get(name) if registry is not None else None
            if entry and entry.get("status") == "enabled":
                caps.append("capability." + name)
    except Exception:  # noqa: BLE001
        pass
    return sorted(set(caps))


def hello(state: Any, agent: Any) -> dict:
    jobs = getattr(state, "jobs", None)
    counts = {}
    if jobs is not None:
        try:
            counts = jobs.status().get("counts", {})
        except Exception:
            counts = {}
    local_models = []
    try:
        probe = agent.federation.probe(agent.MODELS["local"].base_url, use_cache=False)
        local_models = probe.get("models", []) if probe.get("ok") else []
    except Exception:
        pass
    summary = {}
    try:
        summary = experience.summary()
    except Exception:
        pass
    try:
        import updater  # pylint: disable=import-outside-toplevel
        build = updater.version()
    except Exception:  # noqa: BLE001
        build = {}
    return {
        "name": peers.my_name(),
        "version": build,
        "capabilities": machine_capabilities(agent, local_models),
        "machine": peers.describe_machine(),
        "listening": peers.listen_enabled(),
        "ollama_models": local_models,
        "jobs": counts,
        "experience": summary,
        "new_examples": _safe(experience.new_examples, 0),
        "tuned_promoted": bool(getattr(agent, "TUNED_PROMOTED", False)),
        "tuned_model": str(getattr(agent, "TUNED_MODEL", "")),
        "time": time.time(),
    }


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


# --- the server ---------------------------------------------------------------------

def callbacks(state: Any, agent: Any) -> dict:
    def create_job(spec: dict) -> dict:
        jobs = state.jobs
        if jobs is None:
            raise ValueError("background jobs are not running on this machine")
        policy = getattr(agent, "POLICY", None)
        if policy is not None:
            verdict = policy.job("local", "loki")
            if not verdict.allowed:
                raise ValueError(verdict.reason)
        workspace = str(getattr(state, "project", "") or getattr(agent, "WORKSPACE", ""))
        job = jobs.create({**spec, "workspace": workspace})
        threading.Thread(target=jobs.tick, daemon=True).start()
        return _present(job)

    def get_job(job_id: str):
        job = state.jobs.store.get(job_id) if state.jobs is not None else None
        return _present(job) if job else None

    def cancel_job(job_id: str):
        job = state.jobs.cancel(job_id) if state.jobs is not None else None
        return _present(job) if job else None

    def receive(origin: str, items: list) -> dict:
        return experience.import_trajectories(origin, items)

    def check_update() -> dict:
        import updater  # pylint: disable=import-outside-toplevel
        threading.Thread(target=updater.check_now, daemon=True).start()
        return {"checking": True, "version": updater.version()}

    def apply_update() -> dict:
        import updater  # pylint: disable=import-outside-toplevel
        import update_all  # pylint: disable=import-outside-toplevel
        restart = getattr(state, "restart_engine", None) or (lambda: None)
        return update_all.apply_here(updater, restart)

    return {"hello": lambda: hello(state, agent), "create_job": create_job, "get_job": get_job,
            "cancel_job": cancel_job, "receive_experience": receive, "check_update": check_update,
            "apply_update": apply_update}


def _present(job: dict) -> dict:
    keep = ("id", "title", "status", "agent", "backend", "created", "started", "finished",
            "output", "error", "note", "exit_code")
    return {k: job.get(k) for k in keep}


def start(state: Any, agent: Any):
    """Start listening for peers when this machine is set to. Returns the server or None."""
    if not peers.listen_enabled():
        return None
    server = peers.PeerServer(callbacks(state, agent)).start()
    print("[loki-bridge] peer link listening on %s:%s as %s" % (
        peers.lan_address(), server.address[1], peers.my_name()), flush=True)
    return server


# --- the talking side ---------------------------------------------------------------

def push_experience(agent: Any, peer_name: str = "") -> dict:
    """Send verified work this machine has not sent yet to the trainer peer."""
    name = peer_name or os.getenv("LOKI_TRAINER_PEER", "").strip()
    peer = peers.find(name) if name else None
    if peer is None:
        return {"ok": False, "error": "no trainer peer is set (LOKI_TRAINER_PEER)"}
    batch = experience.unsent(peer["name"])
    if not batch:
        return {"ok": True, "sent": 0, "peer": peer["name"]}
    reply = peers.call(peer, "POST", "/peer/experience", {"trajectories": batch}, timeout=60)
    experience.mark_sent(peer["name"], [item.get("id") for item in batch])
    return {"ok": True, "sent": len(batch), "peer": peer["name"], "reply": reply}


def adopt_tuned_model(agent: Any, statuses: list) -> str:
    """Use a peer's PROMOTED fine-tuned model when this machine can reach its Ollama.

    The trainer only promotes a model that beat its baseline (self_improve.py), so using
    it here is the same decision, made once, on the machine with the GPU. Returns a note.
    """
    if getattr(agent, "TUNED_PROMOTED", False) and "loki-tuned" in agent.SMART_ORDER:
        return ""
    for status in statuses:
        hello_data = status.get("hello") or {}
        if not (status.get("ok") and hello_data.get("tuned_promoted")):
            continue
        model = str(hello_data.get("tuned_model") or "loki-tuned")
        host = urlparse(status["url"]).hostname
        base = "http://%s:11434" % host
        probe = agent.federation.probe(base, use_cache=False)
        if not (probe.get("ok") and agent.federation.has_model(probe.get("models", []), model)):
            return "%s has a promoted model, but its Ollama is not reachable from here (set OLLAMA_HOST=0.0.0.0 there)" % status["name"]
        agent.MODELS["loki-tuned"] = agent.ModelConfig(base_url=base + "/v1", api_key="ollama", model=model)
        if "loki-tuned" not in agent.SMART_ORDER:
            order = list(agent.SMART_ORDER)
            at = order.index("local") if "local" in order else len(order)
            agent.SMART_ORDER = tuple(order[:at] + ["loki-tuned"] + order[at:])
        agent.TUNED_PROMOTED = True
        return "using %s's promoted model %s" % (status["name"], model)
    return ""


LAST_SYNC: dict = {"t": 0.0, "note": "", "pushed": None, "error": ""}


def compare_versions(statuses: list) -> list:
    """Linked machines on a different LOKI commit than this one. When one differs, check
    GitHub at once: the machines must run the same version (engine/updater.py)."""
    try:
        import updater  # pylint: disable=import-outside-toplevel
        mine = updater.version().get("commit", "")
    except Exception:  # noqa: BLE001
        return []
    other = [{"name": p["name"], "commit": ((p.get("hello") or {}).get("version") or {}).get("commit", "")}
             for p in statuses if p.get("ok")]
    differ = [o for o in other if o["commit"] and mine and o["commit"] != mine]
    if differ:
        threading.Thread(target=updater.check_now, daemon=True).start()
    return differ


def ask_peers_to_check_update() -> list:
    """Tell every linked machine that a new version was pushed (tools/ship.py)."""
    told = []
    for peer in peers.peers():
        try:
            peers.call(peer, "POST", "/peer/update", {}, timeout=6.0)
            told.append(peer["name"])
        except Exception:  # noqa: BLE001 - an offline machine updates when it next starts
            pass
    return told


def sync_once(agent: Any) -> dict:
    statuses = peers.status_all()
    LAST_SYNC["version_differs"] = compare_versions(statuses)
    note = adopt_tuned_model(agent, statuses)
    pushed, error = None, ""
    if os.getenv("LOKI_TRAINER_PEER", "").strip():
        try:
            pushed = push_experience(agent)
        except peers.PeerError as exc:
            error = str(exc)
    LAST_SYNC.update({"t": time.time(), "note": note, "pushed": pushed, "error": error})
    return {"peers": statuses, **LAST_SYNC}


def sync_forever(state: Any, agent: Any) -> None:
    time.sleep(20)   # let the engine finish starting
    while True:
        if peers.peers():
            try:
                sync_once(agent)
            except Exception as exc:  # noqa: BLE001 - the link must never take the engine down
                LAST_SYNC.update({"t": time.time(), "error": "%s: %s" % (type(exc).__name__, exc)})
        time.sleep(SYNC_EVERY_S)


# --- the app's loopback API (Settings > Machines) ------------------------------------

def ui_route(state: Any, agent: Any, method: str, route: str, data: dict):
    """(status, payload) for /peers* routes, or None when the route is not ours."""
    if not route.startswith("/peers"):
        return None
    env_path = agent.env_file_path()
    if method == "GET" and route == "/peers":
        server = getattr(state, "peer_server", None)
        listening = server is not None
        info = {"ok": True, "me": peers.my_name(), "listening": listening,
                "peers": peers.status_all(), "trainer": os.getenv("LOKI_TRAINER_PEER", ""),
                "last_sync": LAST_SYNC,
                "tuned": {"promoted": bool(getattr(agent, "TUNED_PROMOTED", False)),
                          "model": agent.MODELS["loki-tuned"].model if "loki-tuned" in agent.MODELS else ""}}
        if listening:
            # Only ever shown on this machine, to this machine's own authorised app.
            info["link_code"] = peers.make_link_code(
                peers.my_name(), "http://%s:%s" % (peers.lan_address(), server.address[1]), peers.secret())
        return 200, info
    if method != "POST":
        return 404, {"ok": False, "error": "Unknown endpoint."}
    if route == "/peers/listen":
        if data.get("on", True):
            updates = {"LOKI_PEER_LISTEN": "1"}
            if not peers.secret():
                updates["LOKI_PEER_SECRET"] = peers.new_secret()
            write_env(env_path, updates)
            if getattr(state, "peer_server", None) is None:
                state.peer_server = start(state, agent)
            server = state.peer_server
            code = peers.make_link_code(peers.my_name(), "http://%s:%s" % (peers.lan_address(), server.address[1]),
                                        peers.secret())
            return 200, {"ok": True, "listening": True, "link_code": code,
                         "note": "Allow Python through the firewall if your system asks."}
        write_env(env_path, {"LOKI_PEER_LISTEN": None})
        if getattr(state, "peer_server", None) is not None:
            state.peer_server.stop()
            state.peer_server = None
        return 200, {"ok": True, "listening": False}
    if route == "/peers/link":
        try:
            link = peers.parse_link_code(str(data.get("code", "")))
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        current = [p for p in peers.peers() if p["name"] != link["name"]]
        entries = ",".join("%s=%s" % (p["name"], p["url"]) for p in current + [link])
        updates = {"LOKI_PEERS": entries, "LOKI_PEER_SECRET": link["secret"]}
        if data.get("trainer", True):
            updates["LOKI_TRAINER_PEER"] = link["name"]
        write_env(env_path, updates)
        try:
            hello_data = peers.call(link, "GET", "/peer/hello", timeout=5)
            return 200, {"ok": True, "linked": link["name"], "hello": hello_data}
        except peers.PeerError as exc:
            return 200, {"ok": True, "linked": link["name"], "warning": str(exc)}
    if route == "/peers/unlink":
        name = str(data.get("name", ""))
        rest = [p for p in peers.peers() if p["name"] != name]
        updates = {"LOKI_PEERS": ",".join("%s=%s" % (p["name"], p["url"]) for p in rest) or None}
        if os.getenv("LOKI_TRAINER_PEER", "") == name:
            updates["LOKI_TRAINER_PEER"] = None
        write_env(env_path, updates)
        return 200, {"ok": True}
    if route == "/peers/jobs":
        peer = peers.find(str(data.get("peer", "")))
        if peer is None:
            return 404, {"ok": False, "error": "no linked machine by that name"}
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            return 400, {"ok": False, "error": "a job needs a prompt"}
        try:
            return 200, peers.call(peer, "POST", "/peer/jobs", {"prompt": prompt, "title": data.get("title", "")})
        except peers.PeerError as exc:
            return 502, {"ok": False, "error": str(exc)}
    if route in ("/peers/jobs/status", "/peers/jobs/cancel"):
        peer = peers.find(str(data.get("peer", "")))
        job_id = "".join(ch for ch in str(data.get("id", "")) if ch.isalnum())[:16]
        if peer is None or not job_id:
            return 404, {"ok": False, "error": "no such machine or job"}
        try:
            if route.endswith("cancel"):
                return 200, peers.call(peer, "POST", "/peer/jobs/%s/cancel" % job_id)
            return 200, peers.call(peer, "GET", "/peer/jobs/" + job_id)
        except peers.PeerError as exc:
            return 502, {"ok": False, "error": str(exc)}
    if route == "/peers/sync":
        return 200, {"ok": True, **sync_once(agent)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
