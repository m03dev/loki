"""Relay link tests: the Mac and the PC on DIFFERENT networks, talking through a bore relay.

    python tests/test_relay.py

A small fake bore server (the protocol of github.com/ekzhang/bore) runs on 127.0.0.1, so
nothing leaves this machine. Two "machines" share one process: the PC publishes its peer
server through the relay; the Mac reaches it as pc=relay through the loopback forwarder.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-relay-"))
for key in ("LOKI_PEERS", "LOKI_PEER_SECRET", "LOKI_PEER_LISTEN", "LOKI_TRAINER_PEER", "LOKI_PEER_NAME", "LOKI_RELAY"):
    os.environ.pop(key, None)
os.environ["LOKI_DATA"] = str(TMP)
sys.path.insert(0, str(REPO / "engine"))

import peers  # noqa: E402
import peer_link  # noqa: E402
import relay_link  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:240]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


def wait_for(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


# --------------------------------------------------------------------------- a fake bore server
class FakeBore:
    """Just enough of bore's server: Hello(port) opens a public listener, each visitor is
    announced as Connection(id), and the client's Accept(id) connection carries it."""

    def __init__(self, taken=()):
        self.ctl = socket.socket()
        self.ctl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ctl.bind(("127.0.0.1", 0))
        self.ctl.listen(32)
        self.port = self.ctl.getsockname()[1]
        self.taken, self.waiting, self.hellos = set(taken), {}, []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.ctl.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        frames = relay_link._Frames(conn)
        first = frames.recv()
        if isinstance(first, dict) and "Hello" in first:
            want = int(first["Hello"])
            self.hellos.append(want)
            if want in self.taken:
                relay_link._send(conn, {"Error": "port already in use"})
                conn.close()
                return
            pub = socket.socket()
            pub.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                pub.bind(("127.0.0.1", want))
            except OSError:
                relay_link._send(conn, {"Error": "port already in use"})
                conn.close()
                return
            pub.listen(16)
            relay_link._send(conn, {"Hello": pub.getsockname()[1]})   # Hello(0): bore picks the port
            relay_link._send(conn, "Heartbeat")

            def watch():   # like bore: when the client's control connection drops, so does its port
                try:
                    while conn.recv(1024):
                        pass
                except OSError:
                    pass
                try:
                    pub.shutdown(socket.SHUT_RDWR)      # wakes the accept() below
                except OSError:
                    pass
                pub.close()
            threading.Thread(target=watch, daemon=True).start()
            while True:
                try:
                    visitor, _ = pub.accept()
                except OSError:
                    return
                cid = str(uuid.uuid4())
                self.waiting[cid] = visitor
                try:
                    relay_link._send(conn, {"Connection": cid})
                except OSError:
                    pub.close()
                    return
        elif isinstance(first, dict) and "Accept" in first:
            visitor = self.waiting.pop(first["Accept"], None)
            if visitor is not None:
                relay_link._pipe(conn, visitor, frames.buf)


bore = FakeBore()
os.environ["LOKI_RELAY_HOST"] = "127.0.0.1"
os.environ["LOKI_RELAY_CONTROL_PORT"] = str(bore.port)
SECRET = peers.new_secret()

section("the relay ports come from the shared secret")
ports = relay_link.relay_ports(SECRET, "pc")
check("three candidate ports, stable for the same secret and name", ports == relay_link.relay_ports(SECRET, "pc") and len(ports) == 3)
check("another secret or name gives other ports", ports != relay_link.relay_ports(peers.new_secret(), "pc")
      and ports != relay_link.relay_ports(SECRET, "mac"))
check("all inside the range bore serves", all(relay_link.PORT_LOW <= p < relay_link.PORT_LOW + relay_link.PORT_SPAN for p in ports))

section("the PC publishes its peer server through the relay (its first port is taken)")
bore.taken.add(ports[0])
pc_env = {"LOKI_PEER_SECRET": SECRET, "LOKI_PEER_LISTEN": "1", "LOKI_PEER_NAME": "pc"}
seen = []
pc_server = peers.PeerServer({"hello": lambda: {"name": "pc", "gpu": "RTX 3070 Ti"},
                              "create_job": lambda spec: {"id": "j1", **spec}, "get_job": lambda i: None,
                              "cancel_job": lambda i: None, "receive_experience": lambda o, i: {},
                              "verified": lambda origin, client: seen.append((origin, client))},
                             env=pc_env, host="127.0.0.1", port_number=0).start()
pub = relay_link.Publisher(pc_server.address[1], SECRET, "pc").start()
check("it moves on from a taken port and publishes on the next one",
      wait_for(lambda: relay_link.STATUS.get("publishing")) and relay_link.STATUS["port"] == ports[1], relay_link.STATUS)

section("the Mac reaches the PC as pc=relay")
os.environ.update({"LOKI_PEER_SECRET": SECRET, "LOKI_PEER_NAME": "mac", "LOKI_PEERS": "pc=relay"})
found = peers.peers()
check("pc=relay becomes a loopback address (the link still only dials 127.0.0.1)",
      len(found) == 1 and found[0]["relay"] and found[0]["url"].startswith("http://127.0.0.1:"), found)
hello = peers.call(found[0], "GET", "/peer/hello", timeout=8)
check("a signed hello goes through the relay and comes back", hello.get("ok") and hello.get("gpu") == "RTX 3070 Ti", hello)
check("the forwarder found the PC on its second port and remembers it", relay_link.forwarder("pc").best == 1)
job = peers.call(found[0], "POST", "/peer/jobs", {"prompt": "train on today's work"}, timeout=8)
check("a job can be started through the relay", job.get("ok") and job["job"]["prompt"] == "train on today's work", job)
check("the PC saw the Mac by name, over loopback (what lets it link back)", ("mac", "127.0.0.1") in seen, seen)

section("the relay cannot forge an answer")


class Forged:
    """A stranger's service on the same relay port: answers, but cannot sign."""
    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"ok": True, "name": "pc", "gpu": "fake"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


forged = Forged()
fake_peer = {"name": "pc", "url": "http://127.0.0.1:%d" % forged.httpd.server_address[1], "relay": True}
try:
    peers.call(fake_peer, "GET", "/peer/hello", timeout=4)
    check("an unsigned answer over the relay is refused", False, "accepted")
except peers.PeerError as exc:
    check("an unsigned answer over the relay is refused", "not signed" in str(exc), exc)
try:
    peers.call({**found[0], "secret": peers.new_secret()}, "GET", "/peer/hello", timeout=8)
    check("a machine with the wrong secret is refused", False, "accepted")
except peers.PeerError as exc:
    check("a machine with the wrong secret is refused", "401" in str(exc), exc)
check("on the LAN (no relay) an unsigned answer is still accepted, as before",
      peers.call({**fake_peer, "relay": False}, "GET", "/peer/hello", timeout=4).get("gpu") == "fake")

section("one link code links both directions")
code = peers.make_link_code("pc", "http://192.168.0.101:8768", SECRET, relay=True)
link = peers.parse_link_code(code)
check("a relay link code carries the flag and still the LAN address", link["relay"] and link["url"].startswith("http://192.168."))
check("an old (LAN) link code still parses", not peers.parse_link_code(peers.make_link_code("pc", "http://192.168.0.5:8768", SECRET))["relay"])
env_file = TMP / ".env"
os.environ["LOKI_PEERS"] = ""
os.environ["LOKI_PEER_NAME"] = "pc"                 # now this process plays the PC
relay_link.STATUS["publishing"] = True
added = peer_link.link_back(env_file, "mac", "127.0.0.1")
check("the PC adds the Mac as mac=relay when it first reaches it through the relay",
      added and "LOKI_PEERS=mac=relay" in env_file.read_text(), env_file.read_text() if env_file.exists() else "")
check("...only once", not peer_link.link_back(env_file, "mac", "127.0.0.1"))
check("...never for a LAN caller, itself, or a junk name",
      not peer_link.link_back(env_file, "laptop", "192.168.0.7") and not peer_link.link_back(env_file, peers.my_name(), "127.0.0.1")
      and not peer_link.link_back(env_file, "?", "127.0.0.1"))
check("relay peers are written back as name=relay", peer_link._peer_entries(peers.peers()) == "mac=relay", peer_link._peer_entries(peers.peers()))

section("off means off")
os.environ["LOKI_RELAY"] = "off"
check("LOKI_RELAY=off publishes nothing", relay_link.publish(1, SECRET, "x") is None)
check("...and link codes stop offering the relay", not peers.parse_link_code(
      peer_link.link_code(types.SimpleNamespace(address=("0.0.0.0", 8768))))["relay"])
os.environ["LOKI_RELAY"] = "auto"

section("the publisher comes back after the relay drops it")
before = relay_link.STATUS["since"]
pub.control.shutdown(socket.SHUT_RDWR)                # the relay drops the control connection
check("it reconnects by itself", wait_for(lambda: relay_link.STATUS.get("publishing") and relay_link.STATUS["since"] > before, 12),
      relay_link.STATUS)
section("one machine can see why the other is not responding")
diag = {"name": "pc", "busy": {"agent_running": True, "since_last_request_s": 900}, "logs": {"bridge": ["x"]}}
pc_server.callbacks["diagnose"] = lambda: diag
pc_server.callbacks["restart"] = lambda: {"restarting": True}
os.environ["LOKI_PEER_NAME"] = "mac"
os.environ["LOKI_PEERS"] = "pc=relay"
got = peers.call(peers.find("pc"), "GET", "/peer/diagnose", timeout=8)
check("GET /peer/diagnose comes back through the relay, signed", got.get("ok") and got["busy"]["agent_running"], got)
got = peers.call(peers.find("pc"), "POST", "/peer/restart", {}, timeout=8)
check("POST /peer/restart asks it to restart", got.get("restarting") is True, got)
try:
    peers.call({**peers.find("pc"), "secret": peers.new_secret()}, "GET", "/peer/diagnose", timeout=8)
    check("nobody without the secret can read the diagnosis", False, "accepted")
except peers.PeerError as exc:
    check("nobody without the secret can read the diagnosis", "401" in str(exc), exc)
os.environ["LOKI_PEER_NAME"] = "pc"
import peer_link as _pl  # noqa: E402
real = _pl.diagnose(types.SimpleNamespace(chat_lock=None, chat_request_lock=threading.Lock(), task_request_lock=threading.Lock(),
                                          last_request_at=0, progress=[{"kind": "assistant", "text": "hi"}]),
                    types.SimpleNamespace(MODELS={"local": types.SimpleNamespace(base_url="http://127.0.0.1:9/v1")}, model_name="local"))
check("the real diagnosis runs anywhere and says what it could not reach",
      set(real) >= {"busy", "system_check", "local_models_loaded", "memory", "logs", "update"}
      and "error" in real["local_models_loaded"][0], {k: real[k] for k in ("busy", "local_models_loaded")})

section("the self-test dials this machine's own relay port")
os.environ["LOKI_PEER_SECRET"] = SECRET
fake_agent = types.SimpleNamespace(env_file_path=lambda: TMP / ".env")
code, out = peer_link.ui_route(types.SimpleNamespace(peer_server=pc_server), fake_agent, "GET", "/peers/relay-test", {})
check("a signed hello through our own relay port comes back", code == 200 and out.get("ok") and out["hello"]["name"] == "pc", out)
stale = socket.socket()
stale.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
fw = relay_link.forwarder("pc")
dead_k = (fw.best + 1) % 3
try:
    stale.bind(("127.0.0.1", fw.ports[dead_k]))
    stale.listen(4)                                     # accepts, never answers: a dead tunnel
    fw.best = dead_k
    got = peers.call(peers.find("pc") or {"name": "pc", "relay": True, "url": relay_link.local_url("pc", SECRET)},
                     "GET", "/peer/hello", timeout=3)
    check("a relay port that accepts but never answers is skipped (moves on, tries again)", got.get("name") == "pc", got)
except OSError as exc:
    check("a relay port that accepts but never answers is skipped (moves on, tries again)", False, exc)
finally:
    stale.close()
pub.stop()
pc_server.stop()

section("the phone key page, over the relay when the phone cannot reach this computer")
sys.path.insert(0, str(REPO / "engine"))
import signin  # noqa: E402
import urllib.request  # noqa: E402
got_keys = []
page = signin.PhoneHandoff("nvidia", "NVIDIA NIM", lambda p, k: (got_keys.append(k), {"ok": True, "message": "ok"})[1],
                           ["192.168.1.23"], peers.private_client, ttl_s=30, bind="127.0.0.1", relay=True)
check("the internet link appears next to the home addresses", wait_for(lambda: bool(page.relay_url)), page.status())
check("it is the relay's address with the same one-time path",
      page.relay_url.startswith("http://127.0.0.1:") and page.relay_url.endswith("/k/" + page.token)
      and page.status()["urls"][-1] == page.relay_url and page.status()["urls"][0].startswith("http://192.168.1.23:"),
      page.status())
direct = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
try:
    html = direct(page.relay_url, timeout=5).read().decode()
    check("the phone page opens through the relay (not a black page)", "Send a key to LOKI" in html, html[:200])
    direct(urllib.request.Request(page.relay_url, data=b"key=nvapi-test-123", method="POST"), timeout=5).read()
    check("a key sent through the relay reaches LOKI", got_keys == ["nvapi-test-123"], got_keys)
except OSError as exc:
    check("the phone page opens through the relay (not a black page)", False, exc)
page.stop()
check("closing the page closes its relay tunnel too", page._relay is None)
os.environ["LOKI_RELAY"] = "off"
check("LOKI_RELAY=off: no internet link", relay_link.publish_page(1, wait_s=0.2) == (None, ""))
os.environ.pop("LOKI_RELAY", None)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
