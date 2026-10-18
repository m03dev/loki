"""Relay link - the Mac and the PC talk live when they are NOT on the same network.

The peer link (peers.py) only dials private addresses. When two machines are on different
networks, each one publishes its peer port through a public bore relay (bore.pub by
default; the protocol of github.com/ekzhang/bore, MIT, spoken here in plain Python, so
nothing has to be installed), and reaches the other through a loopback forwarder, so
LOKI still dials 127.0.0.1.

Nothing has to be exchanged by hand: the public port each machine asks the relay for is
derived from the shared link secret and its name (relay_ports), so the other machine,
holding the same secret, knows where to dial. A taken port moves to the next candidate,
and the dialler tries the candidates in the same order (bore only listens on ports that
have a tunnel, so a wrong one simply refuses).

Security: the relay is on the public internet, so
  * every request is signed with the shared secret (as on the LAN) and every RESPONSE is
    signed too and bound to its request (peers.sign_response); a response that is not is
    refused - the relay or a stranger on a colliding port cannot forge an answer;
  * the hop is NOT encrypted: the relay operator could read what is sent (prompts, job
    output, versions). The owner chose this over setting up an account (2026-10-15); for
    a private, encrypted link use Tailscale instead (docs/operations/OFF_NETWORK.md).

Settings (harness_data/.env):
  LOKI_RELAY=auto|on|off    auto (default): publish while the peer server listens; dial
                            peers written as name=relay (a relay link code does that)
  LOKI_RELAY_HOST=bore.pub  the relay server (any bore server works)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import threading
import time
import uuid

CONTROL_PORT = 7835
PORT_LOW, PORT_SPAN = 20000, 40000
CANDIDATES = 3
CONNECT_TIMEOUT_S = 4.0
MAX_FRAME = 256

STATUS: dict = {"publishing": False, "host": "", "port": 0, "candidate": -1, "since": 0.0,
                "error": "", "connections": 0, "forwarders": {}}
_lock = threading.Lock()
_publisher: "Publisher | None" = None
_forwarders: dict = {}


def mode() -> str:
    value = (os.getenv("LOKI_RELAY") or "auto").strip().lower()
    return value if value in ("auto", "on", "off") else "auto"


def host() -> str:
    return (os.getenv("LOKI_RELAY_HOST") or "bore.pub").strip()


def control_port() -> int:
    try:
        return int(os.getenv("LOKI_RELAY_CONTROL_PORT") or CONTROL_PORT)
    except ValueError:
        return CONTROL_PORT


def relay_ports(shared: str, name: str) -> list:
    """The public ports a machine called `name` asks for, in order. Only holders of the
    secret can work them out."""
    out = []
    for k in range(CANDIDATES):
        digest = hmac.new(shared.encode(), ("loki-relay:%s:%d" % (name.lower(), k)).encode(), hashlib.sha256).digest()
        out.append(PORT_LOW + int.from_bytes(digest[:4], "big") % PORT_SPAN)
    return out


# --- the bore wire format: JSON frames, each ended by a NUL byte ---------------------

def _send(sock: socket.socket, message) -> None:
    sock.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\0")


class _Frames:
    def __init__(self, sock: socket.socket) -> None:
        self.sock, self.buf = sock, b""

    def recv(self):
        """The next message, or None when the connection closed."""
        while b"\0" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self.buf += chunk
            if len(self.buf) > MAX_FRAME * 4 and b"\0" not in self.buf:
                raise ValueError("relay sent an oversized frame")
        frame, _, self.buf = self.buf.partition(b"\0")
        return json.loads(frame.decode("utf-8"))


def _connect(where: str, port_number: int, timeout: float = CONNECT_TIMEOUT_S) -> socket.socket:
    sock = socket.create_connection((where, port_number), timeout=timeout)
    sock.settimeout(None)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    return sock


def _pipe(a: socket.socket, b: socket.socket, first: bytes = b"") -> None:
    """Copy both ways until either side closes."""
    def copy(src, dst, head=b""):
        try:
            if head:
                dst.sendall(head)
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    t = threading.Thread(target=copy, args=(b, a, first), daemon=True)
    t.start()
    copy(a, b)
    t.join(timeout=1)
    for s in (a, b):
        try:
            s.close()
        except OSError:
            pass


# --- publishing this machine's peer port --------------------------------------------

class Publisher:
    """Keeps a bore tunnel from <relay>:<derived port> to 127.0.0.1:<local peer port>,
    reconnecting with back-off for as long as the engine runs."""

    def __init__(self, local_port: int, shared: str, name: str, ports: list | None = None,
                 status: dict | None = None) -> None:
        self.local_port, self.stop_flag = local_port, threading.Event()
        self.ports = list(ports) if ports else relay_ports(shared, name)
        self.status = STATUS if status is None else status   # a page tunnel keeps its own
        self.control: socket.socket | None = None

    def start(self) -> "Publisher":
        threading.Thread(target=self._run, daemon=True, name="loki-relay-publish").start()
        return self

    def stop(self) -> None:
        self.stop_flag.set()
        if self.control is not None:
            for close in (lambda: self.control.shutdown(socket.SHUT_RDWR), self.control.close):
                try:
                    close()
                except OSError:
                    pass
        self.status.update({"publishing": False})

    def _run(self) -> None:
        wait, k, misses = 2.0, 0, 0
        while not self.stop_flag.is_set():
            try:
                self._session(k)
                wait = 2.0                      # it ran and then dropped: come back quickly
            except PortTaken as exc:
                misses += 1
                if misses >= 2:                 # our own old tunnel can hold it briefly; then move on
                    k, misses = (k + 1) % len(self.ports), 0
                self.status.update({"publishing": False, "error": str(exc)})
            except (OSError, ValueError) as exc:
                self.status.update({"publishing": False, "error": "relay %s unreachable (%s)" % (host(), exc)})
                wait = min(wait * 2, 60.0)
            if self.stop_flag.wait(wait):
                break

    def _session(self, k: int) -> None:
        sock = _connect(host(), control_port())
        self.control = sock
        frames = _Frames(sock)
        sock.settimeout(CONNECT_TIMEOUT_S)
        _send(sock, {"Hello": self.ports[k]})
        reply = frames.recv()
        if isinstance(reply, dict) and "Error" in reply:
            sock.close()
            raise PortTaken("relay port %d: %s" % (self.ports[k], reply["Error"]))
        if not (isinstance(reply, dict) and "Hello" in reply):
            sock.close()
            raise ValueError("unexpected relay reply %r" % (reply,))
        sock.settimeout(None)
        self.status.update({"publishing": True, "host": host(), "port": int(reply["Hello"]), "candidate": k,
                       "since": time.time(), "error": ""})
        while not self.stop_flag.is_set():
            message = frames.recv()
            if message is None:
                break
            if isinstance(message, dict) and "Connection" in message:
                threading.Thread(target=self._accept, args=(str(message["Connection"]),), daemon=True).start()
            elif isinstance(message, dict) and "Error" in message:
                self.status["error"] = str(message["Error"])
            # "Heartbeat": nothing to do
        self.status.update({"publishing": False})
        try:
            sock.close()
        except OSError:
            pass

    def _accept(self, conn_id: str) -> None:
        try:
            uuid.UUID(conn_id)
            remote = _connect(host(), control_port())
            _send(remote, {"Accept": conn_id})
            local = _connect("127.0.0.1", self.local_port)
        except (OSError, ValueError):
            return
        self.status["connections"] = self.status.get("connections", 0) + 1
        _pipe(remote, local)


class PortTaken(Exception):
    pass


def publish(local_port: int, shared: str, name: str) -> Publisher | None:
    """Start publishing (once). None when the relay is off or there is no secret."""
    global _publisher
    if mode() == "off" or not shared:
        return None
    with _lock:
        if _publisher is None:
            _publisher = Publisher(local_port, shared, name).start()
        return _publisher


def publish_page(local_port: int, wait_s: float = 5.0) -> tuple:
    """Put a one-time local page (the phone key page) on the relay, on a port the relay picks.

    For when the phone cannot reach this computer directly (Windows firewall, guest Wi-Fi, the
    phone on mobile data). Returns (publisher, "host:port") or (None, "") when the relay is off
    or did not answer in time. The caller stops the publisher when the page is done."""
    if mode() == "off":
        return None, ""
    status: dict = {"publishing": False, "port": 0, "error": ""}
    pub = Publisher(local_port, "", "page", ports=[0], status=status).start()
    end = time.time() + wait_s
    while time.time() < end:
        if status.get("publishing") and status.get("port"):
            return pub, "%s:%d" % (host(), int(status["port"]))
        time.sleep(0.05)
    pub.stop()
    return None, ""


def stop() -> None:
    global _publisher
    with _lock:
        if _publisher is not None:
            _publisher.stop()
            _publisher = None


# --- reaching another machine -------------------------------------------------------

class Forwarder:
    """127.0.0.1:<free port> -> <relay>:<that machine's derived port>, trying the candidates
    in order and remembering the one that answers."""

    def __init__(self, name: str, shared: str) -> None:
        self.name, self.ports, self.best = name, relay_ports(shared, name), 0
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(16)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True, name="loki-relay-%s" % name).start()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        order = [self.best] + [k for k in range(CANDIDATES) if k != self.best]
        for k in order:
            try:
                remote = _connect(host(), self.ports[k])
            except OSError:
                continue
            self.best = k
            STATUS["forwarders"][self.name] = {"local": self.port, "remote": "%s:%d" % (host(), self.ports[k]),
                                               "ok_at": time.time()}
            _pipe(client, remote)
            return
        STATUS["forwarders"][self.name] = {"local": self.port, "remote": "", "error": "no relay tunnel answers for %s "
                                           "(is LOKI running there with the link on?)" % self.name}
        try:
            client.close()
        except OSError:
            pass

    def rotate(self) -> None:
        """The answer on the cached port was not from our peer: try the next one next time."""
        self.best = (self.best + 1) % CANDIDATES


def local_url(name: str, shared: str) -> str:
    """http://127.0.0.1:<port> that reaches `name` through the relay (started on first use)."""
    with _lock:
        fwd = _forwarders.get(name)
        if fwd is None or fwd.ports != relay_ports(shared, name):
            fwd = _forwarders[name] = Forwarder(name, shared)
        return "http://127.0.0.1:%d" % fwd.port


def forwarder(name: str) -> Forwarder | None:
    return _forwarders.get(name)


def status() -> dict:
    return {"mode": mode(), "host": host(), **{k: v for k, v in STATUS.items()}}
