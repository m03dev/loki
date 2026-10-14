"""Peers - your Loki on one machine talking to your Loki on another.

The typical pair is the Mac (where you work) and the PC with the RTX 3070 Ti (the GPU).
Each Loki can run a small PEER SERVER on the local network. Another Loki that holds the
same secret can then:

    GET  /peer/hello              who are you: name, OS, GPU, models, jobs, training state
    POST /peer/update/apply       update from GitHub now and restart (Update everything)
    POST /peer/jobs               start a background job here (the built-in Loki agent,
                                  on THIS machine's own project, under THIS machine's policy)
    GET  /peer/jobs/<id>          that job's status and output
    POST /peer/jobs/<id>/cancel   stop it
    POST /peer/experience         hand over verified work, so this machine can train on it

Security, because this listens on the network:
  * OFF unless LOKI_PEER_LISTEN=1 and a LOKI_PEER_SECRET of at least 32 characters is set.
  * Every request is signed: HMAC-SHA256 over method, path, timestamp and body hash.
    The secret itself never crosses the network. Requests older than 2 minutes, or
    replayed, are refused.
  * Only private-network and loopback addresses are served (LAN, VPN ranges, localhost).
  * A peer can never pick the program, the folder or the shell: a remote job is a prompt
    for the built-in Loki agent, in this machine's workspace, in an isolated git worktree,
    and the local policy engine still decides (dangerous tools need a person, so they
    are denied in the background).
  * Bodies are size-capped; experience is re-redacted on arrival.

Configuration (harness_data/.env on each machine):

    LOKI_PEER_NAME=pc                       this machine's name (default: the hostname)
    LOKI_PEER_SECRET=<same long secret on both>
    LOKI_PEER_LISTEN=1                      run the peer server here (the PC)
    LOKI_PEER_PORT=8768
    LOKI_PEERS=pc=http://192.168.1.50:8768  machines to talk to (the Mac)
    LOKI_TRAINER_PEER=pc                    send verified work to this peer to train on

`tools/peer_link.py pair` writes the listening side and prints a LINK CODE; pasting that
code into the other Loki (Settings > Machines) writes the talking side.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import platform
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

DEFAULT_PORT = 8768
MIN_SECRET = 32
MAX_SKEW_S = 120
MAX_BODY = 8 * 1024 * 1024
TIMEOUT_S = 10.0
LINK_PREFIX = "loki-link:"


# --- configuration ------------------------------------------------------------------

def my_name(env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    name = str(env.get("LOKI_PEER_NAME") or "").strip()
    return name or socket.gethostname().split(".")[0].lower() or "loki"


def secret(env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    value = str(env.get("LOKI_PEER_SECRET") or "").strip()
    return value if len(value) >= MIN_SECRET else ""


def listen_enabled(env: dict | None = None) -> bool:
    env = env if env is not None else os.environ
    return str(env.get("LOKI_PEER_LISTEN") or "").strip() == "1" and bool(secret(env))


def port(env: dict | None = None) -> int:
    env = env if env is not None else os.environ
    try:
        return int(env.get("LOKI_PEER_PORT") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def peers(env: dict | None = None) -> list[dict]:
    """[{name, url}] from LOKI_PEERS ("name=url,name=url"). Bad entries are skipped."""
    env = env if env is not None else os.environ
    out = []
    for index, item in enumerate(str(env.get("LOKI_PEERS") or "").split(",")):
        item = item.strip()
        if not item:
            continue
        name, _, url = item.partition("=") if "=" in item else ("peer%d" % (index + 1), "", item)
        url = url.strip().rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme == "http" and parsed.hostname and private_host(parsed.hostname):
            out.append({"name": name.strip() or "peer%d" % (index + 1), "url": url})
    return out


def find(name: str, env: dict | None = None) -> dict | None:
    for peer in peers(env):
        if peer["name"] == name:
            return peer
    return None


def private_host(host: str) -> bool:
    """True for loopback, LAN and VPN addresses (and for names, which resolve locally).

    A hostname cannot be checked without resolving it, so names are accepted here and
    the SERVER side enforces the address check on every request.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host.endswith((".local", ".lan", ".home", ".internal"))
    return address.is_private or address.is_loopback or address in ipaddress.ip_network("100.64.0.0/10")


def private_client(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")


# --- link codes ---------------------------------------------------------------------

def new_secret() -> str:
    return secrets.token_urlsafe(32)


def make_link_code(name: str, url: str, shared: str) -> str:
    raw = json.dumps({"name": name, "url": url, "secret": shared}, separators=(",", ":"))
    return LINK_PREFIX + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def parse_link_code(code: str) -> dict:
    """{name, url, secret} or ValueError with a readable reason."""
    code = str(code or "").strip()
    if not code.startswith(LINK_PREFIX):
        raise ValueError("that is not a Loki link code (it starts with %s)" % LINK_PREFIX)
    body = code[len(LINK_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode())
    except Exception as exc:
        raise ValueError("the link code is damaged - copy it again") from exc
    name, url, shared = str(data.get("name", "")), str(data.get("url", "")), str(data.get("secret", ""))
    parsed = urlparse(url)
    if not name or parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("the link code has no usable address")
    if not private_host(parsed.hostname):
        raise ValueError("Loki only links machines on your own network")
    if len(shared) < MIN_SECRET:
        raise ValueError("the link code's secret is too short")
    return {"name": name, "url": url.rstrip("/"), "secret": shared}


def lan_address() -> str:
    """This machine's address on the local network (best effort, no traffic is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


# --- signing ------------------------------------------------------------------------

def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def sign(shared: str, method: str, path: str, stamp: str, body: bytes) -> str:
    message = "\n".join([method.upper(), path, stamp, _body_hash(body)]).encode()
    return hmac.new(shared.encode(), message, hashlib.sha256).hexdigest()


class ReplayGuard:
    """Remembers recent signatures so a captured request cannot be sent twice."""

    def __init__(self, window_s: float = MAX_SKEW_S * 2) -> None:
        self.window = window_s
        self.seen: dict[str, float] = {}
        self.lock = threading.Lock()

    def first_time(self, signature: str) -> bool:
        now = time.time()
        with self.lock:
            for key, when in list(self.seen.items()):
                if now - when > self.window:
                    del self.seen[key]
            if signature in self.seen:
                return False
            self.seen[signature] = now
            return True


def verify(shared: str, method: str, path: str, headers: dict, body: bytes,
           guard: ReplayGuard, now: float | None = None) -> str:
    """"" when the request is authentic, else the reason it is refused."""
    if not shared:
        return "peer link is not configured"
    stamp = str(headers.get("X-Loki-Time") or "")
    given = str(headers.get("X-Loki-Sig") or "")
    if not stamp or not given:
        return "unsigned request"
    try:
        skew = abs((now if now is not None else time.time()) - float(stamp))
    except ValueError:
        return "bad timestamp"
    if skew > MAX_SKEW_S:
        return "request too old (check both clocks)"
    if not hmac.compare_digest(given, sign(shared, method, path, stamp, body)):
        return "bad signature (the secrets do not match)"
    if not guard.first_time(given):
        return "replayed request"
    return ""


# --- client -------------------------------------------------------------------------

class PeerError(Exception):
    pass


def call(peer: dict, method: str, path: str, payload: dict | None = None,
         env: dict | None = None, timeout: float = TIMEOUT_S, opener=urllib.request.urlopen) -> dict:
    """Signed request to a peer. Returns its JSON; raises PeerError with a plain reason."""
    shared = peer.get("secret") or secret(env)
    if not shared:
        raise PeerError("no LOKI_PEER_SECRET is set on this machine")
    body = json.dumps(payload).encode() if payload is not None else b""
    stamp = "%.3f" % time.time()
    headers = {"Content-Type": "application/json", "X-Loki-Peer": my_name(env), "X-Loki-Time": stamp,
               "X-Loki-Sig": sign(shared, method, path, stamp, body)}
    request = urllib.request.Request(peer["url"] + path, data=body if method != "GET" else None,
                                     headers=headers, method=method)
    try:
        with opener(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("error", "")
        except Exception:
            detail = ""
        raise PeerError("%s answered HTTP %s%s" % (peer["name"], exc.code, (": " + detail) if detail else "")) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PeerError("cannot reach %s at %s (%s)" % (peer["name"], peer["url"], getattr(exc, "reason", exc))) from exc


def status_all(env: dict | None = None, opener=urllib.request.urlopen) -> list[dict]:
    """Every configured peer with its hello, or the reason it could not be reached."""
    out = []
    for peer in peers(env):
        started = time.time()
        try:
            hello = call(peer, "GET", "/peer/hello", env=env, timeout=4.0, opener=opener)
            out.append({**peer, "ok": True, "ms": int((time.time() - started) * 1000), "hello": hello})
        except PeerError as exc:
            out.append({**peer, "ok": False, "ms": int((time.time() - started) * 1000), "error": str(exc)})
    return out


# --- server -------------------------------------------------------------------------

class PeerServer:
    """The network side. The bridge supplies the callbacks; this class owns only HTTP + auth.

    callbacks: hello() -> dict, create_job(spec) -> dict, get_job(id) -> dict|None,
               cancel_job(id) -> dict|None, receive_experience(origin, items) -> dict
    """

    def __init__(self, callbacks: dict[str, Callable[..., Any]], env: dict | None = None,
                 host: str = "0.0.0.0", port_number: int | None = None) -> None:
        self.env = env if env is not None else os.environ
        self.callbacks = callbacks
        self.guard = ReplayGuard()
        self.log: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LokiPeer/1"

            def log_message(self, *args):   # quiet: the bridge has its own log
                pass

            def _send(self, code: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method: str) -> None:
                client = self.client_address[0]
                if not private_client(client):
                    return self._send(403, {"ok": False, "error": "only your own network may talk to Loki"})
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"ok": False, "error": "request too large"})
                body = self.rfile.read(length) if length else b""
                path = urlparse(self.path).path
                refused = verify(secret(server.env), method, path, dict(self.headers.items()), body, server.guard)
                origin = str(self.headers.get("X-Loki-Peer") or "?")[:40]
                server._note(origin, method, path, refused)
                if refused:
                    return self._send(401, {"ok": False, "error": refused})
                try:
                    data = json.loads(body.decode("utf-8") or "{}") if body else {}
                    if not isinstance(data, dict):
                        raise ValueError("the body must be a JSON object")
                    code, payload = server.route(method, path, data, origin)
                except ValueError as exc:
                    code, payload = 400, {"ok": False, "error": str(exc)}
                except Exception as exc:  # noqa: BLE001 - never kill the listener
                    code, payload = 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
                self._send(code, payload)

            def do_GET(self):  # noqa: N802
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

        self.httpd = ThreadingHTTPServer((host, port_number or port(self.env)), Handler)
        self.httpd.daemon_threads = True
        self.thread: threading.Thread | None = None

    @property
    def address(self) -> tuple:
        return self.httpd.server_address

    def _note(self, origin: str, method: str, path: str, refused: str) -> None:
        self.log.append({"t": time.time(), "peer": origin, "call": "%s %s" % (method, path),
                         "refused": refused})
        del self.log[:-50]

    def route(self, method: str, path: str, data: dict, origin: str) -> tuple[int, dict]:
        cb = self.callbacks
        if method == "GET" and path == "/peer/hello":
            return 200, {"ok": True, **cb["hello"]()}
        if method == "POST" and path == "/peer/jobs":
            prompt = str(data.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("a remote job needs a prompt")
            # The peer chooses WHAT to do, never HOW or WHERE: the built-in agent, this
            # machine's workspace, an isolated worktree, and a bounded time.
            spec = {"prompt": prompt[:16000], "title": "[from %s] %s" % (origin, str(data.get("title") or prompt)[:60]),
                    "backend": "local", "agent": "loki", "isolate": True,
                    "timeout_s": min(int(data.get("timeout_s") or 3600), 6 * 3600)}
            return 200, {"ok": True, "job": cb["create_job"](spec)}
        if path.startswith("/peer/jobs/"):
            rest = path[len("/peer/jobs/"):].split("/")
            job_id = "".join(ch for ch in rest[0] if ch.isalnum())[:16]
            if method == "GET" and len(rest) == 1:
                job = cb["get_job"](job_id)
                return (200, {"ok": True, "job": job}) if job else (404, {"ok": False, "error": "no such job"})
            if method == "POST" and rest[1:] == ["cancel"]:
                job = cb["cancel_job"](job_id)
                return (200, {"ok": True, "job": job}) if job else (404, {"ok": False, "error": "no such job"})
        if method == "POST" and path == "/peer/update":
            if "check_update" not in cb:
                return 404, {"ok": False, "error": "updates are not handled here"}
            return 200, {"ok": True, **cb["check_update"]()}
        if method == "POST" and path == "/peer/update/apply":
            # "Update everything" on another machine: update from GitHub (fast-forward
            # only, never over local work) and restart. GitHub decides WHAT version; the
            # caller can only ask for it to happen now.
            if "apply_update" not in cb:
                return 404, {"ok": False, "error": "updates are not handled here"}
            return 200, {"ok": True, **cb["apply_update"]()}
        if method == "POST" and path == "/peer/experience":
            items = data.get("trajectories")
            if not isinstance(items, list):
                raise ValueError("trajectories must be a list")
            return 200, {"ok": True, **cb["receive_experience"](origin, items[:500])}
        return 404, {"ok": False, "error": "unknown peer endpoint"}

    def start(self) -> "PeerServer":
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="loki-peer", daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def describe_machine() -> dict:
    """OS, CPU and GPU in one small dict (no secrets, nothing identifying beyond the name)."""
    info = {"os": platform.system(), "release": platform.release(), "arch": platform.machine()}
    try:
        import shutil
        import subprocess
        exe = shutil.which("nvidia-smi")
        if exe:
            line = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                                   "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                  timeout=10).stdout.strip().splitlines()
            if line:
                name, total, used, util = [p.strip() for p in line[0].split(",")]
                info["gpu"] = {"name": name, "total_mb": int(total), "used_mb": int(used), "util": int(util)}
    except Exception:
        pass
    return info
