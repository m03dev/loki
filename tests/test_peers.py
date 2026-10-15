"""Peer link tests: two Loki machines talking (harness/peers.py, harness/peer_link.py).

    python tests/test_peers.py

Everything runs over real HTTP on 127.0.0.1 with throwaway ports and temp data folders.
Nothing touches the user's harness_data or listens on the network.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "mac")          # this process plays the Mac
(TMP / "mac").mkdir()
for key in ("LOKI_PEERS", "LOKI_PEER_SECRET", "LOKI_PEER_LISTEN", "LOKI_TRAINER_PEER", "LOKI_PEER_NAME"):
    os.environ.pop(key, None)
sys.path.insert(0, str(REPO / "engine"))

import experience  # noqa: E402
import peers  # noqa: E402
import peer_link  # noqa: E402
sys.path.insert(0, str(REPO / "tools"))
import peer_forward  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:200]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


SECRET = "s" * 40
OTHER = "x" * 40

section("configuration and link codes")
env = {"LOKI_PEERS": "pc=http://192.168.1.50:8768,bad=http://8.8.8.8:8768,web=https://192.168.1.9:1",
       "LOKI_PEER_SECRET": SECRET, "LOKI_PEER_NAME": "mac"}
check("peers are read from LOKI_PEERS", [p["name"] for p in peers.peers(env)] == ["pc"], peers.peers(env))
check("a public address is never a peer", not any(p["name"] == "bad" for p in peers.peers(env)))
check("only plain http on the LAN (no https to random hosts)", not any(p["name"] == "web" for p in peers.peers(env)))
check("a short secret does not count", peers.secret({"LOKI_PEER_SECRET": "short"}) == "")
check("listening needs both the switch and a secret",
      not peers.listen_enabled({"LOKI_PEER_LISTEN": "1"}) and peers.listen_enabled({"LOKI_PEER_LISTEN": "1", "LOKI_PEER_SECRET": SECRET}))
code = peers.make_link_code("pc", "http://192.168.1.50:8768", SECRET)
check("a link code round-trips", peers.parse_link_code(code) == {"name": "pc", "url": "http://192.168.1.50:8768", "secret": SECRET})
for bad, why in ((peers.make_link_code("pc", "http://8.8.8.8:8768", SECRET), "public address"),
                 (peers.make_link_code("pc", "http://192.168.1.50:8768", "short"), "short secret"),
                 ("hello", "not a code"), ("loki-link:@@@", "damaged")):
    try:
        peers.parse_link_code(bad)
        check("a bad link code is refused (%s)" % why, False)
    except ValueError:
        check("a bad link code is refused (%s)" % why, True)
check("private clients: LAN, loopback, Tailscale", all(peers.private_client(a) for a in ("192.168.1.4", "10.0.0.2", "127.0.0.1", "100.101.1.2", "::1")))
check("public clients are refused", not any(peers.private_client(a) for a in ("8.8.8.8", "1.1.1.1", "not-an-ip")))

section("signing")
guard = peers.ReplayGuard()
now = time.time()
stamp = "%.3f" % now
sig = peers.sign(SECRET, "POST", "/peer/jobs", stamp, b'{"a":1}')
headers = {"X-Loki-Time": stamp, "X-Loki-Sig": sig}
check("a signed request verifies", peers.verify(SECRET, "POST", "/peer/jobs", headers, b'{"a":1}', guard, now) == "")
check("the same request twice is a replay", "replayed" in peers.verify(SECRET, "POST", "/peer/jobs", headers, b'{"a":1}', guard, now))
check("a changed body fails", "signature" in peers.verify(SECRET, "POST", "/peer/jobs", headers, b'{"a":2}', peers.ReplayGuard(), now))
check("another path fails", "signature" in peers.verify(SECRET, "POST", "/peer/experience", headers, b'{"a":1}', peers.ReplayGuard(), now))
check("the wrong secret fails", "signature" in peers.verify(OTHER, "POST", "/peer/jobs", headers, b'{"a":1}', peers.ReplayGuard(), now))
check("an old request fails", "too old" in peers.verify(SECRET, "POST", "/peer/jobs", headers, b'{"a":1}', peers.ReplayGuard(), now + 600))
check("an unsigned request fails", "unsigned" in peers.verify(SECRET, "GET", "/peer/hello", {}, b"", peers.ReplayGuard(), now))

section("two machines over real HTTP")
PC_ROOT = TMP / "pc"
PC_ROOT.mkdir()
pc_jobs = {}


def pc_create(spec):
    job = {"id": "j%d" % (len(pc_jobs) + 1), "title": spec["title"], "status": "queued", **spec}
    pc_jobs[job["id"]] = job
    return job


callbacks = {
    "hello": lambda: {"name": "pc", "machine": {"os": "Windows", "gpu": {"name": "RTX 3070 Ti", "total_mb": 8192, "used_mb": 300, "util": 0}},
                      "tuned_promoted": False, "experience": experience.summary(PC_ROOT)},
    "create_job": pc_create,
    "get_job": lambda job_id: pc_jobs.get(job_id),
    "cancel_job": lambda job_id: pc_jobs.get(job_id) and {**pc_jobs[job_id], "status": "cancelled"},
    "receive_experience": lambda origin, items: experience.import_trajectories(origin, items, root=PC_ROOT),
}
server = peers.PeerServer(callbacks, env={"LOKI_PEER_SECRET": SECRET}, host="127.0.0.1", port_number=0).start()
PC = {"name": "pc", "url": "http://127.0.0.1:%d" % server.address[1]}
mac_env = {"LOKI_PEER_SECRET": SECRET, "LOKI_PEER_NAME": "mac", "LOKI_PEERS": "pc=" + PC["url"]}

try:
    hello = peers.call(PC, "GET", "/peer/hello", env=mac_env)
    check("the Mac reads the PC's hello", hello.get("name") == "pc" and hello["machine"]["gpu"]["name"] == "RTX 3070 Ti", hello)
    try:
        peers.call(PC, "GET", "/peer/hello", env={**mac_env, "LOKI_PEER_SECRET": OTHER})
        check("a machine with the wrong secret is refused", False)
    except peers.PeerError as exc:
        check("a machine with the wrong secret is refused", "401" in str(exc), exc)
    raw = urllib.request.Request(PC["url"] + "/peer/hello")
    try:
        urllib.request.urlopen(raw, timeout=5)
        check("an unsigned request over HTTP is refused", False)
    except urllib.error.HTTPError as exc:
        check("an unsigned request over HTTP is refused", exc.code == 401)

    reply = peers.call(PC, "POST", "/peer/jobs", {"prompt": "run the tests", "title": "tests",
                                                 "backend": "herdr", "agent": "codex", "workspace": "/etc",
                                                 "timeout_s": 99999}, env=mac_env)
    job = reply["job"]
    check("the Mac starts a job on the PC", reply["ok"] and job["status"] == "queued", reply)
    check("a remote job is always the built-in Loki agent, locally, isolated",
          job["backend"] == "local" and job["agent"] == "loki" and job["isolate"] is True, job)
    check("a remote job cannot choose the folder", "workspace" not in job or job.get("workspace") != "/etc", job)
    check("a remote job's time is capped at 6 hours", job["timeout_s"] <= 6 * 3600, job["timeout_s"])
    check("the job title says who sent it", job["title"].startswith("[from mac]"), job["title"])
    got = peers.call(PC, "GET", "/peer/jobs/" + job["id"], env=mac_env)
    check("the Mac reads the job's status", got["job"]["id"] == job["id"])
    cancelled = peers.call(PC, "POST", "/peer/jobs/%s/cancel" % job["id"], env=mac_env)
    check("the Mac can cancel it", cancelled["job"]["status"] == "cancelled")
    try:
        peers.call(PC, "POST", "/peer/jobs", {"prompt": "  "}, env=mac_env)
        check("an empty job is refused", False)
    except peers.PeerError as exc:
        check("an empty job is refused", "400" in str(exc), exc)

    # verified work on the Mac -> the PC trains on it
    for n in range(3):
        experience.save_trajectory("m%d" % n, "goal %d sk-or-v1-abcdefabcdef0123" % n, [
            {"role": "system", "content": "the user's private memory"},
            {"role": "user", "content": "make %d" % n},
            {"role": "assistant", "content": "DONE: ok"}], [])
    os.environ.update(mac_env)
    os.environ["LOKI_TRAINER_PEER"] = "pc"
    agent = types.SimpleNamespace()
    pushed = peer_link.push_experience(agent)
    check("the Mac sends its verified work to the trainer", pushed["ok"] and pushed["sent"] == 3, pushed)
    check("the PC stored it", experience.summary(PC_ROOT)["trajectories"] == 3, experience.summary(PC_ROOT))
    again = peer_link.push_experience(agent)
    check("nothing is sent twice", again["sent"] == 0, again)
    stored = json.dumps(experience.trajectories(PC_ROOT))
    check("received work is re-cleaned (secrets masked)", "sk-or-v1-abcdefabcdef0123" not in stored)
    check("received work never carries the sender's private system prompt", "private memory" not in stored)
    check("received work is marked with where it came from", all(t.get("origin") == "mac" for t in experience.trajectories(PC_ROOT)))
    names = sorted(p.name for p in (PC_ROOT / "experience" / "trajectories").glob("*.json"))
    check("files are named by origin, so a peer cannot overwrite local work", all(n.startswith("mac-") for n in names), names)
    hostile = experience.import_trajectories("../../evil", [{"id": "../../x", "messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}], root=PC_ROOT)
    check("a hostile origin/id cannot escape the folder",
          hostile["saved"] == 1 and not (TMP / "x.json").exists() and all("/" not in p.name for p in (PC_ROOT / "experience" / "trajectories").glob("*")))

    # the app's Settings > Machines API, against the real engine module
    import loki  # noqa: E402
    loki.EXPERIENCE_ENABLED = False
    state = types.SimpleNamespace(peer_server=None, jobs=None, project=None)
    code, data = peer_link.ui_route(state, loki, "GET", "/peers", {})
    check("GET /peers lists the PC as connected", code == 200 and data["peers"][0]["ok"] and data["peers"][0]["name"] == "pc", data)
    check("the Mac does not show a link code while it is not listening", "link_code" not in data)
    os.environ.pop("LOKI_PEER_SECRET", None)
    os.environ.pop("LOKI_PEERS", None)
    os.environ.pop("LOKI_TRAINER_PEER", None)
    code, data = peer_link.ui_route(state, loki, "POST", "/peers/link", {"code": peers.make_link_code("pc", PC["url"], SECRET)})
    envtxt = loki.env_file_path().read_text(encoding="utf-8")
    check("pasting a link code links the machine", code == 200 and data.get("linked") == "pc" and data.get("hello", {}).get("name") == "pc", data)
    check("the link is saved to this machine's .env", "LOKI_PEERS=pc=" in envtxt and "LOKI_TRAINER_PEER=pc" in envtxt and SECRET in envtxt)
    check("the .env is this machine's own (temp) data folder", str(loki.env_file_path()).startswith(str(TMP)), loki.env_file_path())
    code, data = peer_link.ui_route(state, loki, "POST", "/peers/jobs", {"peer": "pc", "prompt": "build the level"})
    check("the app sends a job to the PC", code == 200 and data["ok"] and data["job"]["agent"] == "loki", data)
    code, data = peer_link.ui_route(state, loki, "POST", "/peers/link", {"code": "nonsense"})
    check("a bad code is a readable 400", code == 400 and "not a Loki link code" in data["error"], data)
    code, data = peer_link.ui_route(state, loki, "POST", "/peers/unlink", {"name": "pc"})
    check("unlinking removes it", code == 200 and peers.peers() == [], peers.peers())

    # this machine starts listening from the app (the PC's side of pairing)
    os.environ["LOKI_PEER_PORT"] = "0"
    code, data = peer_link.ui_route(state, loki, "POST", "/peers/listen", {"on": True})
    try:
        check("turning listening on creates a secret and a link code",
              code == 200 and data["listening"] and data["link_code"].startswith("loki-link:") and len(peers.secret()) >= 32, data)
        port = state.peer_server.address[1]
        parsed = peers.parse_link_code(data["link_code"])
        check("the code points at the port it really listens on", parsed["url"].endswith(":%d" % port), parsed)
        local = {"name": "self", "url": "http://127.0.0.1:%d" % port, "secret": parsed["secret"]}
        state.jobs = None
        reply = peers.call(local, "GET", "/peer/hello")
        check("a machine with the code can talk to the listener", reply["ok"] and "machine" in reply, reply)
        try:
            peers.call(local, "POST", "/peer/jobs", {"prompt": "x"})
            check("with no job runner, a remote job is refused with a reason", False)
        except peers.PeerError as exc:
            check("with no job runner, a remote job is refused with a reason", "not running" in str(exc), exc)
    finally:
        code, data = peer_link.ui_route(state, loki, "POST", "/peers/listen", {"on": False})
        check("turning listening off stops the server", code == 200 and state.peer_server is None)

    # the PC promoted a model -> the Mac uses it (through the PC's Ollama)
    tuned_state = [{"name": "pc", "url": "http://127.0.0.1:8768", "ok": True,
                    "hello": {"tuned_promoted": True, "tuned_model": "loki-tuned"}}]
    saved = (loki.federation.probe, loki.SMART_ORDER, loki.TUNED_PROMOTED, dict(loki.MODELS))
    try:
        loki.TUNED_PROMOTED = False
        loki.SMART_ORDER = tuple(p for p in loki.SMART_ORDER if p != "loki-tuned")
        loki.federation.probe = lambda base, **k: {"ok": True, "models": ["loki-tuned:latest"]}
        note = peer_link.adopt_tuned_model(loki, tuned_state)
        order = list(loki.SMART_ORDER)
        check("the Mac adopts the PC's promoted model", "using pc's promoted model" in note and loki.TUNED_PROMOTED, note)
        check("it is tried just before the stock local model", order.index("loki-tuned") == order.index("local") - 1, order)
        check("it runs on the PC's Ollama", loki.MODELS["loki-tuned"].base_url == "http://127.0.0.1:11434/v1", loki.MODELS["loki-tuned"].base_url)
        loki.TUNED_PROMOTED = False
        loki.SMART_ORDER = tuple(p for p in loki.SMART_ORDER if p != "loki-tuned")
        loki.federation.probe = lambda base, **k: {"ok": False, "models": []}
        note = peer_link.adopt_tuned_model(loki, tuned_state)
        check("an unreachable Ollama is reported, and nothing changes",
              "not reachable" in note and "loki-tuned" not in loki.SMART_ORDER, note)
    finally:
        loki.federation.probe, loki.SMART_ORDER, loki.TUNED_PROMOTED = saved[0], saved[1], saved[2]
        loki.MODELS.clear()
        loki.MODELS.update(saved[3])
finally:
    server.stop()

section("the command-line pairing tool")
import subprocess  # noqa: E402
cli_data = TMP / "cli"
cli_data.mkdir()
run = subprocess.run([sys.executable, str(REPO / "tools" / "peer_link.py"), "pair", "--name", "pc", "--address", "192.168.1.50"],
                     capture_output=True, text=True, env={**os.environ, "LOKI_DATA": str(cli_data), "LOKI_PEER_SECRET": ""}, timeout=60)
code_line = next((l for l in run.stdout.splitlines() if l.startswith("loki-link:")), "")
check("peer_link.py pair prints a link code", run.returncode == 0 and code_line, run.stdout + run.stderr)
check("its code carries the given address", code_line and peers.parse_link_code(code_line)["url"] == "http://192.168.1.50:8768")
check("pair saves listening + the secret", "LOKI_PEER_LISTEN=1" in (cli_data / ".env").read_text() and "LOKI_PEER_SECRET=" in (cli_data / ".env").read_text())

section("peer_forward: a machine reached through a relay looks local")

# The point: Loki only dials private addresses, so a relay has to sit behind a loopback
# forwarder (peers.private_host() accepts 127.0.0.1 but refuses a public hostname).
check("Loki accepts a loopback peer address", peers.private_host("127.0.0.1"))
check("Loki refuses a public hostname, so a relay is reached through the forwarder",
      not peers.private_host("bore.pub"))

import socket as _socket
import threading as _threading

_echo = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
_echo.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
_echo.bind(("127.0.0.1", 0))
_echo.listen(8)


def _echo_once():
    try:
        conn, _ = _echo.accept()
    except OSError:
        return
    try:
        conn.sendall(conn.recv(65536))
    finally:
        conn.close()


_threading.Thread(target=_echo_once, daemon=True).start()
_forwarder = peer_forward.Forwarder("127.0.0.1", 0, "127.0.0.1", _echo.getsockname()[1]).start()
_reply = b""
try:
    _client = _socket.create_connection(_forwarder.address, timeout=5)
    _client.sendall(b"loki-forward-check")
    _reply = _client.recv(65536)
    _client.close()
except OSError as exc:  # noqa: BLE001
    _reply = ("error: %s" % exc).encode()
_forwarder.stop()
_echo.close()
check("the forwarder pipes bytes to the target and back", _reply == b"loki-forward-check", _reply)
check("'host:port' and a bare port both parse",
      peer_forward.parse_address("bore.pub:28768") == ("bore.pub", 28768)
      and peer_forward.parse_address("8768") == ("127.0.0.1", 8768))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
