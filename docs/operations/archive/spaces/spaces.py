"""LOKI Spaces - a Discord you own: anyone running LOKI hosts their own spaces, peer to peer.

Owner, 2026-10-19: "make an open source discord or voip that's p2p - people make their own and host people -
seamless in LOKI World, where people can chat and create lobbies ... something that could replace discord".

    a SPACE      is a community (a Discord server). The machine that made it HOSTS it: its LOKI keeps the
                 rooms, the member list and the (encrypted) messages. No company server, no account.
    a ROOM       is text, voice, or a LOBBY: a voice + text room anyone can open for a game or a hangout,
                 that tidies itself away when the last person leaves.
    an INVITE    is one code ("loki-space:...") with where to reach the host (its LAN address and a public
                 relay address) and the space KEY. Whoever has the code can join - like an invite link.

How it travels (docs/SPACES.md has the wire format):
  * a member's window only ever talks to its OWN engine (/spaces/... on loki_bridge, bearer token);
    that engine talks to the host's spaces port (HTTP, LAN or the public bore relay: engine/relay_link.py);
  * every request a member's engine sends is signed with that member's own secret (HMAC-SHA256), which the
    host learned at join time encrypted under the space key - so the relay, which can read the hop, cannot
    act as anyone; every response is signed back and bound to its request;
  * message TEXT is end-to-end encrypted in the window (AES-GCM, WebCrypto, a key derived from the space
    key): this engine and the host store and pass on ciphertext only;
  * VOICE is WebRTC between the windows (peer to peer, DTLS-SRTP), the offers/answers relayed through the
    host as encrypted signals. No media goes through the host.

Threat model, plainly: the host machine is a member and can read everything (it is your space). Someone who
gets an invite code can join until the host locks the space or bans them; a banned member still holds the
key, so old messages they saw stay seen (rotating the key is a follow-up). The relay sees who talks to whom
and when, never the text, and cannot forge a request or an answer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = 1
PREFIX = "loki-space:"
DEFAULT_PORT = 8795
ONLINE_S = 20.0            # a member not heard from for this long is offline
SIGNAL_KEEP_S = 30.0       # a WebRTC signal nobody collected is dropped
LOBBY_EMPTY_S = 90.0       # an empty lobby goes after this long
CLOCK_SKEW_S = 300.0       # a signed request this far off the host's clock is refused
KEEP_EVENTS = 20000        # per space, in memory (the file keeps everything)
MAX_BODY = 96 * 1024
MAX_CT = 24 * 1024         # one encrypted message (base64)
NAME_MAX, TOPIC_MAX = 40, 160
COLORS = ["#7fcfc2", "#a596c4", "#e0a96d", "#8fb3d9", "#d98ca0", "#9cc98a", "#e6c76a", "#c79be0"]
ROOM_KINDS = ("text", "voice", "lobby")
ROLES = ("owner", "admin", "member")
EMOJI = re.compile(r"^[^\s<>&\"'`]{1,8}$")
ID = re.compile(r"^[a-z0-9]{6,32}$")


class SpaceError(Exception):
    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------------------------------------ small helpers
def data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    base = Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"
    return base / "spaces"


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    text = str(text or "")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_id(n: int = 10) -> str:
    return "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(n))


def clean(text: Any, limit: int) -> str:
    """Display text from anyone: no control characters, trimmed, capped."""
    out = re.sub(r"[\x00-\x1f\x7f​-‏‪-‮]", "", str(text or "")).strip()
    return out[:limit]


def _color(value: Any, default: str) -> str:
    v = str(value or "").strip()
    return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def auth_key(space_key: bytes) -> bytes:
    return hmac.new(space_key, b"loki-spaces auth v1", hashlib.sha256).digest()


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    """A keystream: HMAC-SHA256 as a PRF in counter mode (stdlib only - no AES in Python's standard library).
    Used for exactly one thing: carrying a member's secret to the host at join time."""
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def sign(secret: bytes, *parts: Any) -> str:
    msg = "\n".join(p if isinstance(p, str) else json.dumps(p, sort_keys=True, separators=(",", ":")) for p in parts)
    return hmac.new(secret, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def body_hash(raw: bytes) -> str:
    return hashlib.sha256(raw or b"").hexdigest()


def lan_addresses() -> list:
    """This machine's addresses other machines on the network can dial (no packet is sent)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out[:4]


def encode_invite(space_id: str, name: str, key: bytes, hosts: list) -> str:
    doc = {"v": VERSION, "s": space_id, "n": name, "k": b64e(key), "h": list(hosts)[:8]}
    return PREFIX + b64e(json.dumps(doc, separators=(",", ":")).encode("utf-8"))


def decode_invite(code: str) -> dict:
    code = str(code or "").strip()
    m = re.search(r"loki-space:([A-Za-z0-9_-]+)", code)
    if not m:
        raise SpaceError("that is not a LOKI Spaces invite (it starts with loki-space:)")
    try:
        doc = json.loads(b64d(m.group(1)).decode("utf-8"))
        key = b64d(doc["k"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SpaceError("the invite is damaged: %s" % exc) from exc
    if not ID.match(str(doc.get("s", ""))) or len(key) != 32:
        raise SpaceError("the invite is damaged")
    hosts = [h for h in doc.get("h", []) if isinstance(h, str) and re.fullmatch(r"[A-Za-z0-9.\-\[\]:]{3,80}", h)]
    if not hosts:
        raise SpaceError("the invite has no address to reach the host")
    return {"space": doc["s"], "name": clean(doc.get("n"), NAME_MAX) or "Space", "key": key, "hosts": hosts}


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.%s.tmp" % (path.name, secrets.token_hex(4)))   # unique: threads write at once
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:          # Windows: the other writer holds it for a moment - theirs is as fresh as ours
        tmp.unlink(missing_ok=True)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------------------------------------ the host side
class HostedSpace:
    """One space this machine hosts: members, rooms, the event stream (messages, edits, reactions ...),
    presence, voice state and the WebRTC signals waiting for each member."""

    def __init__(self, root: Path, doc: dict) -> None:
        self.root, self.doc = root, doc
        self.key = b64d(doc["key"])
        self.ka = auth_key(self.key)
        self.lock = threading.RLock()
        self.events: deque = deque(maxlen=KEEP_EVENTS)
        self.seq = int(doc.get("seq", 0))
        self.seen: dict = {}            # member -> last time heard from
        self.voice: dict = {}           # member -> {room, muted, deaf, speaking, at}
        self.typing: dict = {}          # member -> (room, until)
        self.signals: dict = {}         # member -> deque of signals
        self.replay: dict = {}          # signature -> time (a signed request is used once)
        self.empty_since: dict = {}     # lobby id -> when it became empty
        log = root / "events.jsonl"
        if log.is_file():
            with log.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    self.events.append(ev)
                    self.seq = max(self.seq, int(ev.get("seq", 0)))

    # ---- identity
    @property
    def id(self) -> str:
        return self.doc["id"]

    def save(self) -> None:
        self.doc["seq"] = self.seq
        _write(self.root / "space.json", self.doc)

    def member(self, mid: str) -> dict | None:
        m = self.doc["members"].get(mid)
        return m if m and not m.get("banned") else None

    def secret_of(self, mid: str) -> bytes | None:
        m = self.member(mid)
        return b64d(m["secret"]) if m and m.get("secret") else None

    def role(self, mid: str) -> str:
        m = self.member(mid)
        return m.get("role", "member") if m else ""

    def can_manage(self, mid: str) -> bool:
        return self.role(mid) in ("owner", "admin")

    # ---- the event stream
    def _emit(self, ev: dict) -> dict:
        self.seq += 1
        ev = {"seq": self.seq, "ts": round(time.time(), 3), **ev}
        self.events.append(ev)
        try:
            with (self.root / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
        except OSError:
            pass
        self.doc["seq"] = self.seq
        return ev

    # ---- joining
    def join(self, req: dict) -> dict:
        """A new member: they prove they hold the space key and pass their own secret, encrypted under it."""
        with self.lock:
            mid = str(req.get("member", ""))
            if not ID.match(mid):
                raise SpaceError("bad member id")
            nonce, enc = b64d(req.get("nonce", "")), b64d(req.get("secret", ""))
            if len(nonce) != 16 or len(enc) != 32:
                raise SpaceError("bad join")
            proof = sign(self.ka, "join", self.id, mid, req.get("nonce", ""), req.get("secret", ""))
            if not hmac.compare_digest(proof, str(req.get("proof", ""))):
                raise SpaceError("that invite is not for this space (wrong key)", 403)
            old = self.doc["members"].get(mid)
            if old and old.get("banned"):
                raise SpaceError("you are banned from this space", 403)
            if not old and self.doc.get("locked"):
                raise SpaceError("this space is not taking new members right now", 403)
            secret = xor(enc, _stream(self.ka, nonce, 32))
            # a re-join keeps the member's own secret (Spaces.join reuses it); anyone else naming an existing id -
            # every member can see the owner's - must not take that member over (review 2026-10-19)
            if old and not hmac.compare_digest(b64d(old.get("secret", "")), secret):
                raise SpaceError("that member id is taken", 409)
            name = clean(req.get("name"), NAME_MAX) or "guest"
            first = old is None
            self.doc["members"][mid] = {
                **(old or {"role": "member", "joined": round(time.time())}),
                "name": name, "color": _color(req.get("color"), COLORS[len(self.doc["members"]) % len(COLORS)]),
                "secret": b64e(secret),
            }
            if first:
                self._emit({"kind": "sys", "room": self.default_room(), "from": mid, "text": "joined"})
            self.seen[mid] = time.time()
            self.save()
            return {"ok": True, "space": self.public(mid)}

    def default_room(self) -> str:
        for r in self.doc["rooms"]:
            if r["kind"] == "text":
                return r["id"]
        return self.doc["rooms"][0]["id"] if self.doc["rooms"] else ""

    # ---- what a member sees
    def public(self, me: str) -> dict:
        return {"id": self.id, "name": self.doc["name"], "color": self.doc.get("color", COLORS[0]),
                "icon": self.doc.get("icon", ""), "owner": self.doc["owner"], "locked": bool(self.doc.get("locked")),
                "rooms": [dict(r) for r in self.doc["rooms"]], "me": {"id": me, "role": self.role(me)}}

    def members(self) -> list:
        now = time.time()
        out = []
        for mid, m in self.doc["members"].items():
            if m.get("banned"):
                continue
            online = now - self.seen.get(mid, 0) < ONLINE_S
            v = self.voice.get(mid) if online else None
            typing = self.typing.get(mid)
            out.append({"id": mid, "name": m.get("name", "?"), "color": m.get("color", COLORS[0]), "role": m.get("role", "member"),
                        "online": online, "voice": dict(v) if v else None,
                        "typing": typing[0] if typing and typing[1] > now else ""})
        return out

    def sync(self, me: str, since: int) -> dict:
        with self.lock:
            if not self.member(me):
                raise SpaceError("not a member", 403)
            self.seen[me] = time.time()
            self._sweep()
            evs = [e for e in self.events if e["seq"] > since]
            truncated = bool(evs) and since > 0 and evs[0]["seq"] > since + 1 and len(self.events) == KEEP_EVENTS
            if since <= 0 and len(evs) > 400:          # a first sync gets the recent history, not everything
                evs = evs[-400:]
            sig = list(self.signals.pop(me, []))
            return {"ok": True, "space": self.public(me), "members": self.members(), "events": evs[-1000:],
                    "seq": self.seq, "signals": [s for s in sig if time.time() - s["at"] < SIGNAL_KEEP_S],
                    "truncated": truncated, "now": round(time.time(), 3)}

    def _sweep(self) -> None:
        """Lobbies tidy themselves away; voice state of members who went quiet is dropped."""
        now = time.time()
        for mid in list(self.voice):
            if now - self.seen.get(mid, 0) > ONLINE_S:
                self.voice.pop(mid, None)
        changed = False
        for r in list(self.doc["rooms"]):
            if r["kind"] != "lobby":
                continue
            busy = any(v.get("room") == r["id"] for v in self.voice.values())
            if busy:
                self.empty_since.pop(r["id"], None)
            elif now - self.empty_since.setdefault(r["id"], now) > LOBBY_EMPTY_S:
                self.doc["rooms"].remove(r)
                self._emit({"kind": "room", "room": r["id"], "op": "gone", "name": r["name"]})
                changed = True
        if changed:
            self.save()

    def room(self, rid: str) -> dict | None:
        return next((r for r in self.doc["rooms"] if r["id"] == rid), None)

    # ---- what a member does
    def act(self, me: str, action: str, req: dict) -> dict:
        with self.lock:
            if not self.member(me):
                raise SpaceError("not a member", 403)
            self.seen[me] = time.time()
            fn = getattr(self, "_do_" + action, None)
            if fn is None:
                raise SpaceError("unknown action %r" % action, 404)
            out = fn(me, req) or {}
            self.save()
            return {"ok": True, "seq": self.seq, **out}

    def _ct(self, req: dict) -> dict:
        ct, iv = str(req.get("ct", "")), str(req.get("iv", ""))
        if not ct or len(ct) > MAX_CT or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", iv) or not re.fullmatch(r"[A-Za-z0-9_-]+", ct):
            raise SpaceError("a message must be encrypted text (ct, iv)")
        return {"ct": ct, "iv": iv}

    def _do_send(self, me: str, req: dict) -> dict:
        r = self.room(str(req.get("room", "")))
        if not r:
            raise SpaceError("no such room", 404)
        ev = {"kind": "msg", "room": r["id"], "from": me, **self._ct(req)}
        reply = req.get("reply")
        if isinstance(reply, int) and 0 < reply <= self.seq:
            ev["reply"] = reply
        if req.get("bot"):
            ev["bot"] = clean(req.get("bot"), 24)
        self.typing.pop(me, None)
        return {"event": self._emit(ev)}

    def _owned(self, me: str, target: int) -> dict:
        ev = next((e for e in self.events if e.get("seq") == target and e.get("kind") == "msg"), None)
        if not ev:
            raise SpaceError("no such message", 404)
        return ev

    def _do_edit(self, me: str, req: dict) -> dict:
        ev = self._owned(me, int(req.get("target", 0) or 0))
        if ev["from"] != me:
            raise SpaceError("you can only edit your own messages", 403)
        return {"event": self._emit({"kind": "edit", "room": ev["room"], "from": me, "target": ev["seq"], **self._ct(req)})}

    def _do_delete(self, me: str, req: dict) -> dict:
        ev = self._owned(me, int(req.get("target", 0) or 0))
        if ev["from"] != me and not self.can_manage(me):
            raise SpaceError("you can only delete your own messages", 403)
        return {"event": self._emit({"kind": "del", "room": ev["room"], "from": me, "target": ev["seq"]})}

    def _do_react(self, me: str, req: dict) -> dict:
        ev = self._owned(me, int(req.get("target", 0) or 0))
        emoji = str(req.get("emoji", ""))
        if not EMOJI.match(emoji):
            raise SpaceError("bad reaction")
        return {"event": self._emit({"kind": "react", "room": ev["room"], "from": me, "target": ev["seq"],
                                     "emoji": emoji, "on": bool(req.get("on", True))})}

    def _do_typing(self, me: str, req: dict) -> dict:
        r = self.room(str(req.get("room", "")))
        if r:
            self.typing[me] = (r["id"], time.time() + 6)
        return {}

    def _do_room(self, me: str, req: dict) -> dict:
        op = str(req.get("op", "add"))
        if op == "add":
            kind = str(req.get("kind", "text"))
            if kind not in ROOM_KINDS:
                raise SpaceError("a room is text, voice or a lobby")
            if kind != "lobby" and not self.can_manage(me):
                raise SpaceError("only the owner and admins add rooms (anyone can open a lobby)", 403)
            if len(self.doc["rooms"]) >= 60:
                raise SpaceError("this space has the most rooms it can hold")
            name = clean(req.get("name"), NAME_MAX) or ("lobby" if kind == "lobby" else "room")
            room = {"id": new_id(8), "name": name, "kind": kind, "topic": clean(req.get("topic"), TOPIC_MAX), "by": me}
            if kind == "lobby":
                room["activity"] = clean(req.get("activity"), NAME_MAX) or "Hanging out"
                room["cap"] = max(2, min(25, int(req.get("cap", 8) or 8)))
                room["world"] = bool(req.get("world", True))       # shows up in LOKI World
            self.doc["rooms"].append(room)
            self._emit({"kind": "room", "room": room["id"], "op": "add", "from": me, "name": name, "rkind": kind})
            return {"room": room}
        r = self.room(str(req.get("room", "")))
        if not r:
            raise SpaceError("no such room", 404)
        if not (self.can_manage(me) or (r["kind"] == "lobby" and r.get("by") == me)):
            raise SpaceError("only the owner, admins, or a lobby's opener can change it", 403)
        if op == "delete":
            if len([x for x in self.doc["rooms"] if x["kind"] == "text"]) <= 1 and r["kind"] == "text":
                raise SpaceError("a space keeps at least one text room")
            self.doc["rooms"].remove(r)
            self._emit({"kind": "room", "room": r["id"], "op": "gone", "from": me, "name": r["name"]})
        elif op == "edit":
            if req.get("name"):
                r["name"] = clean(req["name"], NAME_MAX) or r["name"]
            if "topic" in req:
                r["topic"] = clean(req.get("topic"), TOPIC_MAX)
            self._emit({"kind": "room", "room": r["id"], "op": "edit", "from": me, "name": r["name"]})
        else:
            raise SpaceError("room op is add, edit or delete")
        return {}

    def _do_voice(self, me: str, req: dict) -> dict:
        rid = req.get("room")
        if not rid:
            self.voice.pop(me, None)
            return {}
        r = self.room(str(rid))
        if not r or r["kind"] not in ("voice", "lobby"):
            raise SpaceError("that is not a voice room", 404)
        here = [m for m, v in self.voice.items() if v.get("room") == r["id"] and m != me]
        if r["kind"] == "lobby" and len(here) >= int(r.get("cap", 8)):
            raise SpaceError("that lobby is full")
        self.voice[me] = {"room": r["id"], "muted": bool(req.get("muted")), "deaf": bool(req.get("deaf")),
                          "speaking": bool(req.get("speaking")), "video": bool(req.get("video")),
                          "screen": bool(req.get("screen")), "at": round(time.time(), 3)}
        return {"peers": here}

    def _do_signal(self, me: str, req: dict) -> dict:
        to = str(req.get("to", ""))
        if not self.member(to):
            raise SpaceError("no such member", 404)
        q = self.signals.setdefault(to, deque(maxlen=200))
        q.append({"from": me, "at": round(time.time(), 3), **self._ct(req)})
        return {}

    def _do_mod(self, me: str, req: dict) -> dict:
        if not self.can_manage(me):
            raise SpaceError("only the owner and admins moderate", 403)
        target, op = str(req.get("member", "")), str(req.get("op", ""))
        if op == "lock":
            self.doc["locked"] = bool(req.get("on", True))
            return {}
        m = self.doc["members"].get(target)
        if not m or target == me:
            raise SpaceError("no such member", 404)
        if m.get("role") == "owner":
            raise SpaceError("nobody moderates the owner", 403)
        if op in ("kick", "ban"):
            if m.get("role") == "admin" and self.role(me) != "owner":
                raise SpaceError("only the owner removes an admin", 403)
            if op == "ban":
                m["banned"] = True
            else:
                self.doc["members"].pop(target, None)
            self.voice.pop(target, None)
            self._emit({"kind": "sys", "room": self.default_room(), "from": me, "member": target, "text": op + "ed " + m.get("name", "?")})
        elif op in ("admin", "member"):
            if self.role(me) != "owner":
                raise SpaceError("only the owner gives or takes admin", 403)
            m["role"] = op
            self._emit({"kind": "sys", "room": self.default_room(), "from": me, "member": target, "text": "role " + op})
        else:
            raise SpaceError("mod op is kick, ban, admin, member or lock")
        return {}

    def _do_leave(self, me: str, req: dict) -> dict:
        if self.role(me) == "owner":
            raise SpaceError("the owner deletes the space instead of leaving it")
        m = self.doc["members"].pop(me, None)
        self.voice.pop(me, None)
        self._emit({"kind": "sys", "room": self.default_room(), "from": me, "text": "left " + (m or {}).get("name", "")})
        return {}

    def _do_space(self, me: str, req: dict) -> dict:
        if not self.can_manage(me):
            raise SpaceError("only the owner and admins change the space", 403)
        if req.get("name"):
            self.doc["name"] = clean(req["name"], NAME_MAX) or self.doc["name"]
        if req.get("color"):
            self.doc["color"] = _color(req["color"], self.doc.get("color", COLORS[0]))
        if "icon" in req:
            self.doc["icon"] = clean(req.get("icon"), 4)
        self._emit({"kind": "space", "from": me, "name": self.doc["name"]})
        return {}

    # ---- a signed request from the wire
    def verify(self, mid: str, method: str, path: str, ts: str, sig: str, raw: bytes) -> bytes:
        secret = self.secret_of(mid)
        if not secret:
            raise SpaceError("not a member", 403)
        try:
            t = float(ts)
        except ValueError as exc:
            raise SpaceError("bad time", 401) from exc
        if abs(time.time() - t) > CLOCK_SKEW_S:
            raise SpaceError("your clock is %d s off the host's" % int(time.time() - t), 401)
        want = sign(secret, method, path, ts, body_hash(raw))
        if not hmac.compare_digest(want, sig):
            raise SpaceError("bad signature", 401)
        with self.lock:
            now = time.time()
            if sig in self.replay:
                raise SpaceError("that request was already used", 401)
            self.replay[sig] = now
            if len(self.replay) > 5000:
                self.replay = {k: v for k, v in self.replay.items() if now - v < CLOCK_SKEW_S * 2}
        return secret


# ------------------------------------------------------------------------------------------------ the member side
class Joined:
    """A space this machine is a member of (hosted elsewhere): the address book, the key and our secret."""

    def __init__(self, doc: dict) -> None:
        self.doc = doc
        self.key = b64d(doc["key"])
        self.secret = b64d(doc["secret"])
        self.good = doc.get("good", "")       # the host address that answered last
        self.status = {"online": False, "error": "", "at": 0.0}

    @property
    def id(self) -> str:
        return self.doc["space"]

    def hosts(self) -> list:
        hs = list(self.doc.get("hosts", []))
        if self.good in hs:
            hs.remove(self.good)
            hs.insert(0, self.good)
        return hs

    def call(self, action: str, body: dict, timeout: float = 6.0) -> dict:
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        path = "/sp/v1/%s/%s" % (self.id, action)
        last = "the host did not answer"
        for h in self.hosts():
            ts = "%.3f" % time.time()
            sig = sign(self.secret, "POST", path, ts, body_hash(raw))
            req = urllib.request.Request("http://%s%s" % (h, path), data=raw, method="POST", headers={
                "Content-Type": "application/json", "X-Sp-Member": self.doc["member"], "X-Sp-Ts": ts, "X-Sp-Sig": sig})
            try:
                with _OPENER.open(req, timeout=timeout) as resp:
                    out, rsig = resp.read(), resp.headers.get("X-Sp-Sig", "")
            except urllib.error.HTTPError as exc:
                try:
                    out = exc.read()
                    err = json.loads(out.decode("utf-8")).get("error", "")
                except (ValueError, OSError):
                    err = ""
                if exc.code in (401, 403, 404) and err:
                    self.status.update({"online": True, "error": err, "at": time.time()})
                    self.good, self.doc["good"] = h, h
                    raise SpaceError(err, exc.code) from exc
                last = "%s: HTTP %d" % (h, exc.code)
                continue
            except (OSError, ValueError) as exc:
                last = "%s: %s" % (h, getattr(exc, "reason", exc))
                continue
            if not hmac.compare_digest(sign(self.secret, "resp", sig, body_hash(out)), rsig):
                last = "%s: the answer was not signed by the host" % h
                continue
            self.good, self.doc["good"] = h, h
            self.status.update({"online": True, "error": "", "at": time.time()})
            try:
                return json.loads(out.decode("utf-8"))
            except ValueError as exc:
                raise SpaceError("the host sent something that is not JSON") from exc
        self.status.update({"online": False, "error": last, "at": time.time()})
        raise SpaceError("the host is not reachable (%s)" % last, 503)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def join_request(space_id: str, key: bytes, member: str, secret: bytes, name: str, color: str) -> dict:
    ka, nonce = auth_key(key), secrets.token_bytes(16)
    enc = xor(secret, _stream(ka, nonce, 32))
    body = {"member": member, "name": name, "color": color, "nonce": b64e(nonce), "secret": b64e(enc)}
    body["proof"] = sign(ka, "join", space_id, member, body["nonce"], body["secret"])
    return body


# ------------------------------------------------------------------------------------------------ this machine's spaces
class Spaces:
    """Everything Spaces on one machine: the spaces it hosts (and their server), the ones it joined, and its
    own name. The window's /spaces/... routes (engine/spaces_api.py) call this."""

    def __init__(self, root: Path | None = None, port: int | None = None, relay: bool | None = None) -> None:
        self.root = Path(root) if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.hosted: dict = {}
        self.joined: dict = {}
        self.server: ThreadingHTTPServer | None = None
        self.port = int(port if port is not None else os.getenv("LOKI_SPACES_PORT", DEFAULT_PORT) or DEFAULT_PORT)
        self.relay_on = (os.getenv("LOKI_SPACES_RELAY", "auto").lower() != "off") if relay is None else relay
        self.publisher = None
        self.relay_status: dict = {"publishing": False, "port": 0, "error": ""}
        self.me = _read(self.root / "me.json", {})
        if not self.me.get("secret"):
            self.me = {"name": self.me.get("name") or socket.gethostname().split(".")[0][:NAME_MAX] or "me",
                       "color": self.me.get("color") or secrets.choice(COLORS), "secret": b64e(secrets.token_bytes(32))}
            _write(self.root / "me.json", self.me)
        for d in sorted((self.root / "hosted").glob("*/space.json")) if (self.root / "hosted").is_dir() else []:
            doc = _read(d, None)
            if isinstance(doc, dict) and doc.get("id"):
                self.hosted[doc["id"]] = HostedSpace(d.parent, doc)
        for doc in _read(self.root / "joined.json", []):
            if isinstance(doc, dict) and doc.get("space"):
                self.joined[doc["space"]] = Joined(doc)

    # ---- serving
    def start(self) -> "Spaces":
        """Listen on the spaces port (all interfaces: the LAN can join) and, unless turned off, publish it
        on the public relay so members on other networks can too. Only once something is hosted."""
        with self.lock:
            if self.server is not None or not self.hosted:
                return self
            for port in [self.port] + [self.port + i for i in range(1, 6)] + [0]:
                try:
                    self.server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(self))
                    break
                except OSError:
                    continue
            if self.server is None:
                return self
            self.server.daemon_threads = True
            self.port = self.server.server_address[1]
            threading.Thread(target=self.server.serve_forever, daemon=True, name="loki-spaces").start()
            if self.relay_on:
                try:
                    import relay_link  # pylint: disable=import-outside-toplevel
                    if relay_link.mode() != "off":
                        self.publisher = relay_link.Publisher(self.port, "", "spaces", ports=self.relay_ports(),
                                                              status=self.relay_status).start()
                except Exception as exc:  # noqa: BLE001 - the relay is optional; the LAN still works
                    self.relay_status["error"] = str(exc)
        return self

    def stop(self) -> None:
        with self.lock:
            if self.publisher is not None:
                self.publisher.stop()
                self.publisher = None
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.server = None

    def relay_ports(self) -> list:
        """The public relay ports this machine asks for: derived from its own secret, so they stay the same
        across restarts and an invite keeps working."""
        seed = hashlib.sha256(b64d(self.me["secret"]) + b"spaces-relay").digest()
        return [20000 + int.from_bytes(seed[i * 4:i * 4 + 4], "big") % 40000 for i in range(3)]

    def addresses(self) -> list:
        out = ["%s:%d" % (ip, self.port) for ip in lan_addresses()]
        try:
            import relay_link  # pylint: disable=import-outside-toplevel
            relay_host = relay_link.host() if self.relay_on and relay_link.mode() != "off" else ""
        except Exception:  # noqa: BLE001
            relay_host = ""
        if relay_host:
            port = int(self.relay_status.get("port") or 0)
            ports = [port] if port else []
            out += ["%s:%d" % (relay_host, p) for p in ports + [p for p in self.relay_ports() if p not in ports]]
        out.append("127.0.0.1:%d" % self.port)       # the same machine (a second LOKI, tests)
        return out

    # ---- my identity
    def profile(self, name: Any = None, color: Any = None) -> dict:
        with self.lock:
            if name is not None:
                self.me["name"] = clean(name, NAME_MAX) or self.me["name"]
            if color is not None:
                self.me["color"] = _color(color, self.me["color"])
            _write(self.root / "me.json", self.me)
            for h in self.hosted.values():     # the spaces I host see my new name at once
                owner = h.doc["members"].get(h.doc["owner"])
                if owner:
                    owner.update({"name": self.me["name"], "color": self.me["color"]})
                    h.save()
            return {"name": self.me["name"], "color": self.me["color"]}

    # ---- making and joining
    def create(self, name: Any, color: Any = None, icon: Any = "") -> dict:
        with self.lock:
            sid, owner = new_id(12), new_id(12)
            name = clean(name, NAME_MAX) or "My space"
            doc = {"v": VERSION, "id": sid, "name": name, "color": _color(color, secrets.choice(COLORS)), "icon": clean(icon, 4),
                   "key": b64e(secrets.token_bytes(32)), "owner": owner, "created": round(time.time()), "seq": 0,
                   "members": {owner: {"name": self.me["name"], "color": self.me["color"], "role": "owner",
                                       "joined": round(time.time()), "secret": b64e(secrets.token_bytes(32))}},
                   "rooms": [{"id": new_id(8), "name": "general", "kind": "text", "topic": "Say hello."},
                             {"id": new_id(8), "name": "Hangout", "kind": "voice", "topic": ""}]}
            root = self.root / "hosted" / sid
            root.mkdir(parents=True, exist_ok=True)
            _write(root / "space.json", doc)
            h = HostedSpace(root, doc)
            h._emit({"kind": "sys", "room": doc["rooms"][0]["id"], "from": owner, "text": "made the space"})
            h.save()
            self.hosted[sid] = h
        self.start()
        return self.listing(sid)

    def invite(self, sid: str) -> dict:
        h = self.hosted.get(sid)
        if h:
            return {"ok": True, "code": encode_invite(sid, h.doc["name"], h.key, self.addresses()), "hosts": self.addresses(),
                    "relay": dict(self.relay_status), "locked": bool(h.doc.get("locked"))}
        j = self.joined.get(sid)
        if j:   # a member passes on the invite they joined with
            return {"ok": True, "code": encode_invite(sid, j.doc.get("name", "Space"), j.key, j.doc["hosts"]), "hosts": j.doc["hosts"]}
        raise SpaceError("no such space", 404)

    def join(self, code: str, name: Any = None) -> dict:
        inv = decode_invite(code)
        if inv["space"] in self.hosted:
            return self.listing(inv["space"])
        with self.lock:
            old = self.joined.get(inv["space"])
            member = old.doc["member"] if old else new_id(12)
            secret = b64d(old.doc["secret"]) if old else secrets.token_bytes(32)
            doc = {"space": inv["space"], "name": inv["name"], "key": b64e(inv["key"]), "hosts": inv["hosts"],
                   "member": member, "secret": b64e(secret), "joined": round(time.time())}
            j = Joined(doc)
        body = join_request(inv["space"], inv["key"], member, secret, clean(name, NAME_MAX) or self.me["name"], self.me["color"])
        # the join itself is not signed with our secret yet (the host does not know it) - it proves the key
        raw = json.dumps(body).encode("utf-8")
        last = "the host did not answer"
        for h in j.hosts():
            req = urllib.request.Request("http://%s/sp/v1/%s/join" % (h, inv["space"]), data=raw, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with _OPENER.open(req, timeout=8) as resp:
                    out, rsig = resp.read(), resp.headers.get("X-Sp-Sig", "")
            except urllib.error.HTTPError as exc:
                try:
                    err = json.loads(exc.read().decode("utf-8")).get("error", "")
                except (ValueError, OSError):
                    err = ""
                if err:
                    raise SpaceError(err, exc.code) from exc
                last = "%s: HTTP %d" % (h, exc.code)
                continue
            except (OSError, ValueError) as exc:
                last = "%s: %s" % (h, getattr(exc, "reason", exc))
                continue
            if not hmac.compare_digest(sign(secret, "joined", body["proof"], body_hash(out)), rsig):
                last = "%s: the answer was not from the host" % h
                continue
            j.good, j.doc["good"] = h, h
            data = json.loads(out.decode("utf-8"))
            j.doc["name"] = clean(data.get("space", {}).get("name"), NAME_MAX) or j.doc["name"]
            j.doc["color"] = _color(data.get("space", {}).get("color"), COLORS[0])
            with self.lock:
                self.joined[inv["space"]] = j
                self._save_joined()
            return self.listing(inv["space"])
        raise SpaceError("could not reach the host (%s). Is their LOKI open?" % last, 503)

    def _save_joined(self) -> None:
        with self.lock:
            _write(self.root / "joined.json", [dict(j.doc) for j in self.joined.values()])

    def forget(self, sid: str) -> dict:
        """Leave a joined space, or delete one you host."""
        with self.lock:
            if sid in self.joined:
                try:
                    self.joined[sid].call("leave", {}, timeout=3)
                except SpaceError:
                    pass
                self.joined.pop(sid)
                self._save_joined()
                return {"ok": True, "left": sid}
            h = self.hosted.pop(sid, None)
            if h:
                gone = h.root.with_name(h.root.name + ".deleted-%d" % int(time.time()))
                try:
                    h.root.rename(gone)        # kept on disk (renamed), never destroyed outright
                except OSError:
                    pass
                return {"ok": True, "deleted": sid}
        raise SpaceError("no such space", 404)

    # ---- the window's view
    def key(self, sid: str) -> str:
        h, j = self.hosted.get(sid), self.joined.get(sid)
        if h:
            return h.doc["key"]
        if j:
            return j.doc["key"]
        raise SpaceError("no such space", 404)

    def listing(self, sid: str | None = None) -> dict:
        rows = []
        for h in self.hosted.values():
            rows.append({"id": h.id, "name": h.doc["name"], "color": h.doc.get("color"), "icon": h.doc.get("icon", ""),
                         "hosted": True, "online": True, "me": h.doc["owner"],
                         "members": sum(1 for m in h.doc["members"].values() if not m.get("banned")),
                         "seq": h.seq})
        for j in self.joined.values():
            rows.append({"id": j.id, "name": j.doc.get("name", "Space"), "color": j.doc.get("color", COLORS[0]), "icon": "",
                         "hosted": False, "online": j.status["online"], "error": j.status["error"], "me": j.doc["member"]})
        out = {"ok": True, "spaces": rows, "me": {"name": self.me["name"], "color": self.me["color"]},
               "serving": {"port": self.port if self.server else 0, "relay": dict(self.relay_status)}}
        if sid:
            out["space"] = next((r for r in rows if r["id"] == sid), None)
        return out

    def _route(self, sid: str):
        """(call, member id): the same calls work for a space hosted here and one hosted elsewhere."""
        h = self.hosted.get(sid)
        if h:
            me = h.doc["owner"]
            return (lambda action, body: h.sync(me, int(body.get("since", 0) or 0)) if action == "sync"
                    else h.act(me, action, body)), me
        j = self.joined.get(sid)
        if j:
            def call(action, body):
                before = j.good
                out = j.call(action, body)
                if j.good != before:          # a different address answered: remember it
                    self._save_joined()
                return out
            return call, j.doc["member"]
        raise SpaceError("no such space", 404)

    def sync(self, sid: str, since: int) -> dict:
        call, me = self._route(sid)
        out = call("sync", {"since": int(since or 0)})
        if sid in self.joined:
            sp = out.get("space") or {}
            j = self.joined[sid]
            if sp.get("name") and (sp["name"] != j.doc.get("name") or sp.get("color") != j.doc.get("color")):
                j.doc["name"], j.doc["color"] = clean(sp["name"], NAME_MAX), _color(sp.get("color"), COLORS[0])
                self._save_joined()
        return out

    def act(self, sid: str, action: str, body: dict) -> dict:
        if action in ("sync", "join"):
            raise SpaceError("not an action", 404)
        call, _ = self._route(sid)
        return call(action, dict(body or {}))

    def world(self) -> dict:
        """For LOKI World (the Godot client, docs/SPACES.md): the lobbies open now in every space this machine
        is in, who is in each, and the spaces themselves - so the world can show them as places to walk into."""
        out = []
        for sid in list(self.hosted) + list(self.joined):
            try:
                s = self.sync(sid, 10 ** 12)          # members + rooms only (no history)
            except SpaceError:
                continue
            people = {m["id"]: m for m in s.get("members", [])}
            for r in s["space"]["rooms"]:
                if r["kind"] not in ("lobby", "voice"):
                    continue
                inside = [{"name": m["name"], "color": m["color"]} for m in people.values()
                          if m.get("voice") and m["voice"].get("room") == r["id"]]
                if r["kind"] == "lobby" and not r.get("world", True):
                    continue
                out.append({"space": sid, "space_name": s["space"]["name"], "space_color": s["space"]["color"],
                            "room": r["id"], "name": r["name"], "kind": r["kind"], "activity": r.get("activity", ""),
                            "cap": r.get("cap", 0), "people": inside})
        return {"ok": True, "lobbies": out}


# ------------------------------------------------------------------------------------------------ the wire server
def _make_handler(spaces: Spaces):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LOKI-Spaces/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, *_a) -> None:   # quiet: chatter is not news
            return

        def _out(self, status: int, data: dict, sig: str = "") -> None:
            body = json.dumps(data, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if sig:
                self.send_header("X-Sp-Sig", sig)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:   # noqa: N802
            if self.path.split("?")[0] == "/sp/v1/hello":
                self._out(200, {"ok": True, "loki": "spaces", "v": VERSION})
                return
            self._out(404, {"ok": False, "error": "not here"})

        def do_POST(self) -> None:   # noqa: N802
            m = re.fullmatch(r"/sp/v1/([a-z0-9]{6,32})/([a-z]{2,12})", self.path.split("?")[0])
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = -1
            if not m or length < 0 or length > MAX_BODY:
                self._out(404 if not m else 413, {"ok": False, "error": "not here" if not m else "too big"})
                return
            raw = self.rfile.read(length)
            sid, action = m.group(1), m.group(2)
            h = spaces.hosted.get(sid)
            if not h:
                self._out(404, {"ok": False, "error": "this machine does not host that space"})
                return
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(body, dict):
                    raise ValueError("not an object")
            except ValueError:
                self._out(400, {"ok": False, "error": "bad JSON"})
                return
            try:
                if action == "join":
                    out = h.join(body)
                    secret = h.secret_of(body["member"])
                    self._out(200, out, sign(secret, "joined", body.get("proof", ""), body_hash(
                        json.dumps(out, separators=(",", ":")).encode("utf-8"))))
                    return
                mid, ts, sig = self.headers.get("X-Sp-Member", ""), self.headers.get("X-Sp-Ts", ""), self.headers.get("X-Sp-Sig", "")
                secret = h.verify(mid, "POST", self.path.split("?")[0], ts, sig, raw)
                out = h.sync(mid, int(body.get("since", 0) or 0)) if action == "sync" else h.act(mid, action, body)
            except SpaceError as exc:
                self._out(exc.code, {"ok": False, "error": str(exc)})
                return
            except (KeyError, TypeError, ValueError) as exc:
                self._out(400, {"ok": False, "error": "bad request: %s" % exc})
                return
            payload = json.dumps(out, separators=(",", ":")).encode("utf-8")
            self._out(200, out, sign(secret, "resp", sig, body_hash(payload)))

    return Handler


_SINGLE: dict = {}


def instance() -> Spaces:
    """The one Spaces of this engine (started the first time the window asks, or at engine start when this
    machine hosts a space)."""
    if "s" not in _SINGLE:
        _SINGLE["s"] = Spaces()
    return _SINGLE["s"]
