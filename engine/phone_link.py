"""Phone link - the LOKI phone app (mobile/) talking to LOKI on this Mac or PC over the LAN.

The phone app chats with LOKI here when it can reach this machine, and with a small model
on the phone when it cannot (docs/PHONE.md). This module is the computer side.

    GET  /phone/status    who is this: machine name, Mac or PC, busy or free
    POST /phone/chat      {"message": "...", "mode": "ask"|"plan"} -> LOKI's answer
    POST /phone/unpair    the phone forgets this machine; its key stops working here

Threat model (it listens on your network, over plain HTTP):
  * OFF unless LOKI_PHONE_LINK=1 (Settings > Machines > Phone). Its own port
    (LOKI_PHONE_PORT, default 8769), separate from the Mac <-> PC peer link: a phone can
    never start jobs, update, or hand over training data the way a linked machine can.
  * Pairing makes a RANDOM KEY PER PHONE, shown once as a QR code on this machine's own
    screen. The QR holds this machine's addresses, the port, the phone's id and that key;
    nothing else (no API keys, no peer secret, no bridge token).
  * Only a hash-derived signing key is stored (harness_data/phone/phones.json, never
    committed), never the QR key itself. Someone who can read harness_data can already
    read your API keys in .env, so that file is protected the same way.
  * Every request is signed: HMAC-SHA256 over method, path, timestamp and body hash (as
    the peer link does). The key never crosses the network after the QR; a request older
    than 2 minutes, or replayed, is refused. Somebody on the same Wi-Fi can READ the chat
    (plain HTTP), but cannot forge or replay a request. Use Tailscale for encryption.
  * An unscanned pairing expires after 15 minutes; a phone unused for 60 days expires;
    any phone can be revoked at once from Settings.
  * Only private-network, loopback and Tailscale addresses are served.
  * Rate limits: per phone (chat and overall) and per address for failed signatures.
  * A phone message runs in Ask mode (no tools at all) or Plan mode (read-only tools),
    never Build. While it runs, every approval request is DENIED: a message from the
    phone can never approve anything, not even through the automatic risk gate.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from quiet_server import QuietHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import peers

DEFAULT_PORT = 8769
PAIR_PREFIX = "loki-phone:"
PAIR_TTL_S = 15 * 60                 # an unscanned QR stops working after this
IDLE_TTL_S = 60 * 24 * 3600          # a phone not seen for this long must pair again
MAX_SKEW_S = peers.MAX_SKEW_S
MAX_BODY = 32_000
MAX_MESSAGE = 4_000
CHAT_PER_MIN = 6
CALLS_PER_MIN = 60
BAD_SIG_LIMIT = 10                   # failed signatures per address per window ...
BAD_SIG_WINDOW_S = 300               # ... before the address is refused for the window
CHAT_TIMEOUT_S = 600
PHONE_MODES = ("ask", "plan")
KEY_LABEL = b"loki-phone-v1"
WEB_DIR = Path(__file__).resolve().parent.parent / "app" / "ui"
WEB_CSP = ("default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# --- configuration ------------------------------------------------------------------

def enabled(env: dict | None = None) -> bool:
    env = env if env is not None else os.environ
    return str(env.get("LOKI_PHONE_LINK") or "").strip() == "1"


def port(env: dict | None = None) -> int:
    env = env if env is not None else os.environ
    try:
        return int(env.get("LOKI_PHONE_PORT") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def machine_kind() -> str:
    """What the phone calls this computer in the chat: "Mac" or "PC"."""
    return "Mac" if sys.platform == "darwin" else "PC"


def lan_addresses() -> list:
    """This machine's private addresses a phone could use (home Wi-Fi first, then VPN/Tailscale)."""
    return peers.lan_addresses()[:4]


# --- keys -------------------------------------------------------------------------

def signing_key(token: str) -> str:
    """The HMAC key both sides derive from the QR token. Only this is stored here."""
    return hmac.new(token.encode("utf-8"), KEY_LABEL, hashlib.sha256).hexdigest()


def sign(key: str, method: str, path: str, stamp: str, body: bytes, nonce: str = "") -> str:
    """HMAC over method, path, timestamp, an optional per-request nonce and the body's SHA-256.

    Same fix as peers.sign: without a nonce two IDENTICAL requests in the same millisecond (a retry,
    or two screens polling /phone/status) share a signature and the second is refused as a replay.
    A request without X-Loki-Nonce is still checked in the old form, so a phone app that has not
    updated yet keeps working."""
    parts = [method.upper(), path, stamp]
    if nonce:
        parts.append(nonce)
    parts.append(hashlib.sha256(body or b"").hexdigest())
    return hmac.new(key.encode("utf-8"), "\n".join(parts).encode(), hashlib.sha256).hexdigest()


class Registry:
    """Paired phones in <data>/phone/phones.json: id, name, signing key, times, revoked."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.Lock()

    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, phones: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(phones, indent=1), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.path)

    def pair(self, name: str = "") -> dict:
        """A new phone: returns {id, name, token}. The token is shown once, never stored."""
        token = secrets.token_urlsafe(32)
        entry = {"id": secrets.token_hex(6), "name": (str(name).strip() or "Phone")[:40],
                 "key": signing_key(token), "created": self.clock(), "claimed": 0.0,
                 "last_seen": 0.0, "revoked": False}
        with self.lock:
            phones = self._load()
            phones.append(entry)
            self._save(phones)
        return {"id": entry["id"], "name": entry["name"], "token": token}

    def _state(self, entry: dict, now: float) -> str:
        if entry.get("revoked"):
            return "revoked"
        if not entry.get("claimed"):
            return "expired" if now - float(entry.get("created", 0)) > PAIR_TTL_S else "waiting"
        if now - float(entry.get("last_seen") or entry.get("claimed")) > IDLE_TTL_S:
            return "expired"
        return "paired"

    def key_for(self, phone_id: str) -> tuple:
        """(key, "") for a usable phone, else ("", reason)."""
        now = self.clock()
        for entry in self._load():
            if hmac.compare_digest(str(entry.get("id", "")), str(phone_id)):
                state = self._state(entry, now)
                if state in ("paired", "waiting"):
                    return str(entry.get("key", "")), ""
                return "", "this phone's pairing is %s - pair it again in LOKI (Settings > Machines > Phone)" % state
        return "", "unknown phone - pair it in LOKI (Settings > Machines > Phone)"

    def seen(self, phone_id: str) -> None:
        now = self.clock()
        with self.lock:
            phones = self._load()
            for entry in phones:
                if entry.get("id") == phone_id:
                    if not entry.get("claimed"):
                        entry["claimed"] = now
                    entry["last_seen"] = now
            self._save(phones)

    def revoke(self, phone_id: str) -> bool:
        with self.lock:
            phones = self._load()
            hit = False
            for entry in phones:
                if entry.get("id") == phone_id and not entry.get("revoked"):
                    entry["revoked"] = True
                    entry["key"] = ""          # nothing left to sign with
                    hit = True
            if hit:
                self._save(phones)
            return hit

    def forget_dead(self) -> None:
        """Drop revoked or expired entries older than a day (keeps the list short)."""
        now = self.clock()
        with self.lock:
            phones = [p for p in self._load()
                      if self._state(p, now) in ("paired", "waiting") or now - float(p.get("created", 0)) < 86400]
            self._save(phones)

    def present(self) -> list:
        """The list Settings shows: no keys."""
        now = self.clock()
        return [{"id": p.get("id"), "name": p.get("name"), "created": p.get("created"),
                 "last_seen": p.get("last_seen") or None, "state": self._state(p, now)}
                for p in self._load()]


def _data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def default_registry() -> Registry:
    return Registry(_data_dir() / "phone" / "phones.json")


# --- pairing code (the QR) --------------------------------------------------------------

def pairing_payload(pairing: dict, addresses: list, port_number: int, machine: str, kind: str) -> dict:
    """Exactly what the QR carries. The token is the only secret in it."""
    return {"v": 1, "machine": str(machine)[:40], "kind": kind, "hosts": list(addresses)[:4],
            "port": int(port_number), "id": pairing["id"], "token": pairing["token"]}


def make_pairing_code(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return PAIR_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_pairing_code(code: str) -> dict:
    """The payload of a pairing code, or ValueError (the phone app does the same in TS)."""
    code = str(code or "").strip()
    if not code.startswith(PAIR_PREFIX) and "#" + PAIR_PREFIX in code:   # the QR is a link now: http://host:port/#code
        code = code.split("#", 1)[1]
    if not code.startswith(PAIR_PREFIX):
        raise ValueError("that is not a LOKI phone code (it starts with %s)" % PAIR_PREFIX)
    body = code[len(PAIR_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode())
    except Exception as exc:
        raise ValueError("the phone code is damaged") from exc
    if not isinstance(data, dict) or data.get("v") != 1 or not data.get("id") or len(str(data.get("token", ""))) < 32:
        raise ValueError("the phone code is incomplete")
    if not all(peers.private_host(str(h)) for h in data.get("hosts") or []):
        raise ValueError("LOKI only pairs phones on your own network")
    return data


# --- verification and limits -------------------------------------------------------------

class Limiter:
    """Sliding-window counters: per key, at most `limit` events in `window` seconds."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.events: dict = {}
        self.lock = threading.Lock()

    def count(self, key: str, window: float) -> int:
        now = self.clock()
        with self.lock:
            kept = [t for t in self.events.get(key, []) if now - t < window]
            self.events[key] = kept
            return len(kept)

    def hit(self, key: str, limit: int, window: float = 60.0) -> bool:
        """Record one event; False when it is over the limit (the event is not recorded)."""
        now = self.clock()
        with self.lock:
            kept = [t for t in self.events.get(key, []) if now - t < window]
            if len(kept) >= limit:
                self.events[key] = kept
                return False
            kept.append(now)
            self.events[key] = kept
            return True


def verify(registry: Registry, method: str, path: str, headers: dict, body: bytes,
           guard: peers.ReplayGuard, now: float | None = None) -> tuple:
    """(phone_id, "") when authentic, else ("", reason)."""
    phone_id = str(headers.get("X-Loki-Phone") or "")[:32]
    stamp = str(headers.get("X-Loki-Time") or "")
    given = str(headers.get("X-Loki-Sig") or "")
    nonce = str(headers.get("X-Loki-Nonce") or "")[:64]
    if not phone_id or not stamp or not given:
        return "", "unsigned request"
    try:
        skew = abs((now if now is not None else time.time()) - float(stamp))
    except ValueError:
        return "", "bad timestamp"
    if skew > MAX_SKEW_S:
        return "", "request too old (check the phone's clock)"
    key, why = registry.key_for(phone_id)
    if not key:
        return "", why
    if not hmac.compare_digest(given, sign(key, method, path, stamp, body, nonce)):
        return "", "bad signature"
    if not guard.first_time(phone_id + ":" + given):
        return "", "replayed request"
    return phone_id, ""


# --- the server ---------------------------------------------------------------------

class PhoneServer:
    """HTTP + auth + limits. The bridge supplies callbacks: status() -> dict, chat(message, mode) -> (code, dict)."""

    def __init__(self, callbacks: dict, registry: Registry, env: dict | None = None,
                 host: str = "0.0.0.0", port_number: int | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.env = env if env is not None else os.environ
        self.callbacks = callbacks
        self.registry = registry
        self.guard = peers.ReplayGuard()
        self.limits = Limiter(clock)
        self.clock = clock
        self.log: list = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LokiPhone/1"

            def log_message(self, *args):
                pass

            def _send(self, code: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionError, OSError):
                    pass

            def _handle(self, method: str) -> None:
                code, payload = server.handle(method, urlparse(self.path).path, self.client_address[0],
                                              dict(self.headers.items()), self._body())
                self._send(code, payload)

            def _body(self):
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return None
                if length > MAX_BODY:
                    return None
                return self.rfile.read(length) if length else b""

            def _static(self) -> bool:
                """The phone's web page (app/ui/phone_web.*): scan the QR and chat in the phone's browser, no app
                needed. Static files with no secret in them; the code arrives in the URL #fragment, which the
                browser never sends here. Every API call after it is signed as before."""
                path = urlparse(self.path).path
                name = {"/": "phone_web.html", "/index.html": "phone_web.html", "/web.js": "phone_web.js"}.get(path)
                if name is None:
                    return False
                if not peers.private_client(self.client_address[0]):
                    self._send(403, {"ok": False, "error": "only your own network may talk to LOKI"})
                    return True
                try:
                    raw = (WEB_DIR / name).read_bytes()
                except OSError:
                    self._send(404, {"ok": False, "error": "the phone page is missing (app/ui/%s)" % name})
                    return True
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8" if name.endswith(".html")
                                     else "text/javascript; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy", WEB_CSP)
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
                return True

            def do_GET(self):  # noqa: N802
                if self._static():
                    return
                self._handle("GET")

            def do_POST(self):  # noqa: N802
                self._handle("POST")

        self.httpd = QuietHTTPServer((host, port_number if port_number is not None else port(self.env)), Handler)
        self.httpd.daemon_threads = True
        self.thread: threading.Thread | None = None

    @property
    def address(self) -> tuple:
        return self.httpd.server_address

    def handle(self, method: str, path: str, client: str, headers: dict, body) -> tuple:
        """Everything but the socket, so tests can call it directly."""
        if not peers.private_client(client):
            return 403, {"ok": False, "error": "only your own network may talk to LOKI"}
        if self.limits.count("bad:" + client, BAD_SIG_WINDOW_S) >= BAD_SIG_LIMIT:
            return 429, {"ok": False, "error": "too many refused requests from this address - wait a few minutes"}
        if body is None:
            return 413, {"ok": False, "error": "request too large"}
        phone_id, refused = verify(self.registry, method, path, headers, body, self.guard, self.clock())
        self.log.append({"t": self.clock(), "phone": phone_id, "call": "%s %s" % (method, path), "refused": refused})
        del self.log[:-50]
        if refused:
            self.limits.hit("bad:" + client, 10 ** 9, BAD_SIG_WINDOW_S)
            return 401, {"ok": False, "error": refused}
        if not self.limits.hit("all:" + phone_id, CALLS_PER_MIN):
            return 429, {"ok": False, "error": "slow down - too many requests from this phone"}
        self.registry.seen(phone_id)
        try:
            data = json.loads(body.decode("utf-8") or "{}") if body else {}
            if not isinstance(data, dict):
                raise ValueError("the body must be a JSON object")
            return self.route(method, path, data, phone_id)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never kill the listener
            return 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    def route(self, method: str, path: str, data: dict, phone_id: str) -> tuple:
        if method == "GET" and path == "/phone/status":
            return 200, {"ok": True, **self.callbacks["status"]()}
        if method == "POST" and path == "/phone/chat":
            message = str(data.get("message") or "").strip()
            if not message:
                raise ValueError("a message is needed")
            if len(message) > MAX_MESSAGE:
                raise ValueError("the message is too long (at most %d characters)" % MAX_MESSAGE)
            mode = str(data.get("mode") or "ask").strip().lower()
            if mode not in PHONE_MODES:
                return 403, {"ok": False, "error": "from the phone LOKI only answers in Ask or Plan mode; "
                                                   "use the app on the computer to build"}
            if not self.limits.hit("chat:" + phone_id, CHAT_PER_MIN):
                return 429, {"ok": False, "error": "slow down - at most %d messages a minute from a phone" % CHAT_PER_MIN}
            return self.callbacks["chat"](message, mode)
        if method == "POST" and path == "/phone/unpair":
            self.registry.revoke(phone_id)
            return 200, {"ok": True}
        return 404, {"ok": False, "error": "unknown phone endpoint"}

    def start(self) -> "PhoneServer":
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="loki-phone", daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# --- the engine side (the bridge calls these) ----------------------------------------

async def _deny(kind: str, detail: str, decidable: bool = True) -> bool:
    """The approval function while a phone message runs: nothing is ever approved."""
    print("[phone-link] refused (a phone message cannot approve): %s %s" % (kind, str(detail)[:120]), flush=True)
    return False


def chat_once(state: Any, agent: Any, message: str, mode: str, timeout_s: float = CHAT_TIMEOUT_S) -> tuple:
    """Send one phone message through the agent the way the app's chat does, made safe.

    It holds BOTH request locks (so no app chat or task runs alongside and sees the
    phone's mode), switches to Ask/Plan, swaps the approval function for one that always
    says no, and puts everything back afterwards.
    """
    if mode not in PHONE_MODES:
        return 403, {"ok": False, "error": "phone messages run in Ask or Plan mode only"}
    if getattr(state, "loop", None) is None:
        return 503, {"ok": False, "error": "LOKI is still starting"}
    busy = state.try_busy()
    if busy is None:
        return 409, {"ok": False, "error": "LOKI is busy with another request on the computer - try again shortly"}
    previous_mode = getattr(agent, "AGENT_MODE", "build")
    previous_approve = getattr(agent, "approve", None)
    try:
        agent.set_mode(mode)
        agent.approve = _deny
        future = asyncio.run_coroutine_threadsafe(state.request_chat(message), state.loop)
        try:
            result = future.result(timeout=timeout_s)
        except Exception:  # noqa: BLE001 - a timeout: stop the run, then wait for it to end
            if hasattr(agent, "request_cancel"):
                agent.request_cancel()
            try:
                result = future.result(timeout=60)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": "LOKI did not finish in time (%s)" % type(exc).__name__}
        answer = {"ok": bool(result.get("ok")), "response": result.get("response", ""),
                  "error": result.get("error", ""), "mode": mode,
                  "machine": peers.my_name(), "kind": machine_kind()}
        return (200 if answer["ok"] else 502), answer
    finally:
        agent.approve = previous_approve
        agent.set_mode(previous_mode)
        state.release_busy(busy)


def callbacks(state: Any, agent: Any) -> dict:
    def status() -> dict:
        lock = getattr(state, "chat_request_lock", None)
        try:
            import updater  # pylint: disable=import-outside-toplevel
            commit = updater.version().get("commit", "")
        except Exception:  # noqa: BLE001
            commit = ""
        return {"machine": peers.my_name(), "kind": machine_kind(), "busy": bool(lock is not None and lock.locked()),
                "modes": list(PHONE_MODES), "version": commit[:12], "time": time.time()}

    return {"status": status, "chat": lambda message, mode: chat_once(state, agent, message, mode)}


def start(state: Any, agent: Any, registry: Registry | None = None):
    """Start the phone server when LOKI_PHONE_LINK=1. Returns it, or None."""
    if not enabled():
        return None
    registry = registry or default_registry()
    registry.forget_dead()
    host = os.environ.get("LOKI_PHONE_HOST", "").strip() or "0.0.0.0"   # tests use 127.0.0.1
    server = PhoneServer(callbacks(state, agent), registry, host=host).start()
    state.phone_registry = registry
    print("[loki-bridge] phone link listening on %s:%s" % (", ".join(lan_addresses()), server.address[1]), flush=True)
    return server


def relay_url(state: Any, port_number: int) -> str:
    """"host:port" of the phone link on LOKI's relay (for a phone on mobile data or another Wi-Fi), started once
    and kept while LOKI runs; "" when the relay is off (LOKI_PHONE_RELAY=off) or did not answer. Through the relay a
    request arrives from loopback, so the signature is what keeps it safe - the same as on the home network."""
    if os.environ.get("LOKI_PHONE_RELAY", "on").strip().lower() in ("off", "0", "false", "no"):
        return ""
    have = getattr(state, "phone_relay", None)
    if have and have[0] == port_number:
        return have[2]
    try:
        import relay_link  # pylint: disable=import-outside-toplevel
        pub, where = relay_link.publish_page(port_number, wait_s=4.0)
    except Exception:  # noqa: BLE001 - no relay is not an error: the home link still works
        return ""
    if pub is None:
        return ""
    state.phone_relay = (port_number, pub, where)
    return where


def ui_route(state: Any, agent: Any, method: str, route: str, data: dict):
    """(status, payload) for the app's /phones* loopback routes, or None if not ours."""
    if not route.startswith("/phones"):
        return None
    import peer_link  # pylint: disable=import-outside-toplevel
    registry = getattr(state, "phone_registry", None) or default_registry()
    state.phone_registry = registry
    server = getattr(state, "phone_server", None)
    if method == "GET" and route == "/phones":
        return 200, {"ok": True, "enabled": enabled(), "listening": server is not None,
                     "port": server.address[1] if server else port(), "addresses": lan_addresses(),
                     "machine": peers.my_name(), "kind": machine_kind(), "phones": registry.present()}
    if method != "POST":
        return 404, {"ok": False, "error": "Unknown endpoint."}
    if route == "/phones/enable":
        if data.get("on", True):
            peer_link.write_env(agent.env_file_path(), {"LOKI_PHONE_LINK": "1"})
            if server is None:
                state.phone_server = start(state, agent, registry)
            return 200, {"ok": True, "listening": True,
                         "note": "Allow Python through the firewall if your system asks."}
        peer_link.write_env(agent.env_file_path(), {"LOKI_PHONE_LINK": None})
        if server is not None:
            server.stop()
            state.phone_server = None
        relay = getattr(state, "phone_relay", None)
        if relay:
            try:
                relay[1].stop()
            except Exception:  # noqa: BLE001
                pass
            state.phone_relay = None
        return 200, {"ok": True, "listening": False}
    if route == "/phones/pair":
        if server is None:
            return 400, {"ok": False, "error": "turn on the phone link first"}
        pairing = registry.pair(str(data.get("name") or "Phone"))
        code = make_pairing_code(pairing_payload(pairing, lan_addresses(), server.address[1],
                                                 peers.my_name(), machine_kind()))
        import qr  # pylint: disable=import-outside-toplevel
        # The QR is a LINK (owner 2026-10-18: "qr dont show up on my phone"): a bare "loki-phone:" code means
        # nothing to a phone camera without the app. The link opens LOKI's chat page in the phone's browser; the
        # app reads the same code from its #fragment. Home addresses first, then the internet way in.
        port_number = server.address[1]
        urls = ["http://%s:%d/#%s" % (h, port_number, code) for h in (lan_addresses() or ["127.0.0.1"])]
        relay = relay_url(state, port_number)
        if relay:
            urls.append("http://%s/#%s" % (relay, code))
        return 200, {"ok": True, "id": pairing["id"], "name": pairing["name"], "code": code, "url": urls[0],
                     "urls": urls, "relay_url": urls[-1] if relay else "", "svg": qr.svg(urls[0]),
                     "svgs": [qr.svg(u) for u in urls[:5]], "expires_in": PAIR_TTL_S}
    if route == "/phones/revoke":
        if not registry.revoke(str(data.get("id") or "")):
            return 404, {"ok": False, "error": "no such phone"}
        return 200, {"ok": True, "phones": registry.present()}
    return 404, {"ok": False, "error": "Unknown endpoint."}
