"""LOKI World presence: the owner's avatar on each machine, seen live on the others.

LOKI World is an MMO now (app/ui/mmo/): you walk your own character round your island. When the
same owner has LOKI open on the Mac and on the PC, each machine should see the other's avatar
walk, emote and chat. This module is the engine side of that:

    the app  --POST /world/presence {player, chat?, after}-->  this engine (Presence.update_local)
             <-- {players, chat, cursor} ------------------------------------------------------
    this engine --signed POST /peer/presence {player, chat, since}--> each linked machine
                <-- {machine, player, chat} (its own avatar and chat, in the same call) ----

So one exchange carries both directions: even when only one side can dial the other (the
relay), both see each other. The pusher runs only while this machine's world is open (the app
posted in the last PUSH_IDLE_S), at most every PUSH_MOVE_S while the avatar moves and every
PUSH_HEARTBEAT_S while it stands still, one call in flight per peer, backing off a peer that
does not answer.

Everything a peer sends is display-only and sanitised here (lengths capped, control characters
removed, numbers clamped); the app shows it with textContent. Positions are machine-neutral:
`zone` is the name of the island (machine) the avatar stands on and `u`/`v` are its place on
that island as a fraction of the island's radius, so each machine can draw it on its own map
of the sky.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from typing import Any, Callable

REMOTE_FRESH_S = 12.0     # a remote avatar not heard from for this long is gone
PUSH_IDLE_S = 15.0        # push only while this machine's world was open this recently
PUSH_MOVE_S = 0.35        # while moving
PUSH_HEARTBEAT_S = 2.0    # while standing
BACKOFF_S = 8.0           # after a peer did not answer
CHAT_KEEP = 120
CHAT_SEND_MAX = 20
TEXT_MAX = 200

_CTRL = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁦-⁩]")


def _text(value: Any, limit: int) -> str:
    return _CTRL.sub("", str(value or "")).strip()[:limit]


def _num(value: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(x) or math.isinf(x):
        return default
    return max(lo, min(hi, x))


def clean_player(data: Any) -> dict | None:
    """A player record as it may be stored and shown. None if it is not a player at all."""
    if not isinstance(data, dict):
        return None
    color = _text(data.get("color"), 7)
    return {
        "name": _text(data.get("name"), 24) or "player",
        "cls": _text(data.get("cls"), 12),
        "lvl": int(_num(data.get("lvl"), 1, 99, 1)),
        "zone": _text(data.get("zone"), 40),
        "u": round(_num(data.get("u"), -1.5, 1.5), 4),
        "v": round(_num(data.get("v"), -1.5, 1.5), 4),
        "y": round(_num(data.get("y"), 0, 4), 3),
        "ry": round(_num(data.get("ry"), -100, 100), 3),
        "hp": round(_num(data.get("hp"), 0, 1, 1), 3),
        "en": round(_num(data.get("en"), 0, 1, 1), 3),
        "moving": bool(data.get("moving")),
        "emote": _text(data.get("emote"), 10),
        "emote_at": _num(data.get("emote_at"), 0, 1e15),
        "ts": _num(data.get("ts"), 0, 1e15),
        "color": color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "",
        "target": _text(data.get("target"), 40),
    }


class Presence:
    """One machine's presence hub. The engine uses HUB; tests make one per pretend machine."""

    def __init__(self, name_fn: Callable[[], str], clock: Callable[[], float] = time.time) -> None:
        self.name_fn = name_fn
        self.clock = clock
        self.lock = threading.Lock()
        self.local: dict | None = None
        self.local_t = 0.0
        self.dirty = False
        self.remote: dict[str, dict] = {}            # machine -> {"player", "t"}
        self.chat: deque = deque(maxlen=CHAT_KEEP)   # every line here, local seq order
        self.seq = 0                                  # local order of lines in self.chat
        self.oseq = 0                                 # this machine's own line numbers
        self.seen_ids: set = set()
        self.sent: dict[str, int] = {}                # peer -> last own oseq it has
        self.recv: dict[str, int] = {}                # machine -> last of ITS oseq we have
        self.busy: set = set()
        self.backoff: dict[str, float] = {}
        self.last_push: dict[str, float] = {}
        self.pushes = 0
        self.errors: dict[str, str] = {}
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- from the app
    def update_local(self, data: dict) -> dict:
        """POST /world/presence: the app's own avatar (and maybe a chat line). Returns the snapshot."""
        player = clean_player(data.get("player")) if isinstance(data, dict) else None
        line = _text(data.get("chat"), TEXT_MAX) if isinstance(data, dict) else ""
        with self.lock:
            now = self.clock()
            if player is not None:
                before = self.local or {}
                moved = any(before.get(k) != player.get(k) for k in ("u", "v", "y", "ry", "zone", "emote", "emote_at", "hp"))
                self.local, self.local_t = player, now
                self.dirty = self.dirty or moved
            if line:
                self.oseq += 1
                me = self.name_fn()
                self._add_line({"id": "%s:%d" % (me, self.oseq), "oseq": self.oseq, "machine": me,
                                "from": (player or self.local or {}).get("name", "player"), "text": line, "t": now,
                                "own": True})
                self.dirty = True
        try:
            after = int((data or {}).get("after") or 0)
        except (TypeError, ValueError):
            after = 0
        return self.snapshot(after)

    def _add_line(self, line: dict) -> None:
        if line["id"] in self.seen_ids:
            return
        self.seen_ids.add(line["id"])
        if len(self.seen_ids) > CHAT_KEEP * 8:
            self.seen_ids = {x["id"] for x in self.chat} | {line["id"]}
        self.seq += 1
        self.chat.append({**line, "seq": self.seq})

    def snapshot(self, after: int = 0) -> dict:
        """What the app draws: the other machines' avatars (fresh ones) and chat after `after`."""
        with self.lock:
            now = self.clock()
            players = []
            for machine, rec in sorted(self.remote.items()):
                age = now - rec["t"]
                if age <= REMOTE_FRESH_S:
                    players.append({**rec["player"], "machine": machine, "age": round(age, 2)})
            chat = [{k: v for k, v in x.items() if k != "own"} for x in self.chat if x["seq"] > after][-60:]
            return {"ok": True, "self": self.name_fn(), "players": players, "chat": chat,
                    "cursor": self.seq, "pushing": self._fresh(now)}

    def _fresh(self, now: float) -> bool:
        return self.local is not None and now - self.local_t < PUSH_IDLE_S

    # ------------------------------------------------------------- from a peer
    def receive(self, origin: str, data: dict) -> dict:
        """POST /peer/presence from a linked machine: store its avatar and chat; answer with ours."""
        origin = _text(origin, 40) or "?"
        machine = _text((data or {}).get("machine"), 40) or origin
        self._take(machine, data)
        try:
            since = int((data or {}).get("since") or 0)
        except (TypeError, ValueError):
            since = 0
        return self._outgoing(since)

    def _take(self, machine: str, data: dict) -> None:
        player = clean_player((data or {}).get("player"))
        lines = (data or {}).get("chat") or []
        with self.lock:
            now = self.clock()
            if player is not None:
                self.remote[machine] = {"player": player, "t": now}
            if isinstance(lines, list):
                for raw in lines[:CHAT_SEND_MAX]:
                    if not isinstance(raw, dict):
                        continue
                    oseq = int(_num(raw.get("oseq"), 0, 1e12))
                    text = _text(raw.get("text"), TEXT_MAX)
                    if not oseq or not text:
                        continue
                    self._add_line({"id": "%s:%d" % (machine, oseq), "oseq": oseq, "machine": machine,
                                    "from": _text(raw.get("from"), 24) or machine, "text": text, "t": now})
                    self.recv[machine] = max(self.recv.get(machine, 0), oseq)

    def _outgoing(self, since: int) -> dict:
        """Our avatar (when this machine's world is open) and our own chat lines after `since`."""
        with self.lock:
            now = self.clock()
            mine = [{"oseq": x["oseq"], "from": x["from"], "text": x["text"]}
                    for x in self.chat if x.get("own") and x["oseq"] > since][-CHAT_SEND_MAX:]
            return {"machine": self.name_fn(), "player": self.local if self._fresh(now) else None, "chat": mine}

    # ------------------------------------------------------------- to the peers
    def push_once(self, peer: dict, call: Callable[..., dict]) -> bool:
        """One exchange with one peer. call(peer, method, path, payload, timeout=) is peers.call."""
        name = str(peer.get("name") or "")
        with self.lock:
            if name in self.busy:
                return False
            self.busy.add(name)
            since = self.recv.get(name, 0)
        try:
            out = self._outgoing(self.sent.get(name, 0))
            out["since"] = since
            reply = call(peer, "POST", "/peer/presence", out, timeout=4.0)
            if out["chat"]:
                self.sent[name] = max(x["oseq"] for x in out["chat"])
            machine = _text((reply or {}).get("machine"), 40) or name
            if machine != name and name in self.recv:
                self.recv.setdefault(machine, self.recv[name])
            self._take(machine, reply or {})
            if machine != name:   # remember what we have from it under the name we dial it by, too
                self.recv[name] = self.recv.get(machine, 0)
            with self.lock:
                self.pushes += 1
                self.errors.pop(name, None)
            return True
        except Exception as exc:  # noqa: BLE001 - a peer that does not answer must never break the world
            with self.lock:
                self.backoff[name] = self.clock() + BACKOFF_S
                self.errors[name] = str(exc)[:200]
            return False
        finally:
            with self.lock:
                self.busy.discard(name)
                self.last_push[name] = self.clock()

    def due(self, peer_names: list) -> list:
        """Which peers to exchange with now (and clears the moved flag when any is due)."""
        with self.lock:
            now = self.clock()
            if not self._fresh(now):
                return []
            out = []
            for name in peer_names:
                if name in self.busy or self.backoff.get(name, 0) > now:
                    continue
                gap = now - self.last_push.get(name, 0)
                if (self.dirty and gap >= PUSH_MOVE_S) or gap >= PUSH_HEARTBEAT_S:
                    out.append(name)
            if out:
                self.dirty = False
            return out

    def ensure_pusher(self, peers_fn: Callable[[], list], call: Callable[..., dict]) -> None:
        """Start the background pusher once (daemon). It sleeps while the world is closed."""
        with self.lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, args=(peers_fn, call), daemon=True,
                                            name="loki-presence")
            self._thread.start()

    def _loop(self, peers_fn: Callable[[], list], call: Callable[..., dict]) -> None:
        while True:
            time.sleep(0.12)
            try:
                listed = {p["name"]: p for p in peers_fn()}
                for name in self.due(list(listed)):
                    threading.Thread(target=self.push_once, args=(listed[name], call), daemon=True).start()
            except Exception:  # noqa: BLE001 - never let the pusher die
                time.sleep(2)

    def status(self) -> dict:
        with self.lock:
            return {"pushes": self.pushes, "errors": dict(self.errors), "remote": sorted(self.remote),
                    "open": self._fresh(self.clock())}


def _my_name() -> str:
    try:
        import peers  # pylint: disable=import-outside-toplevel
        return peers.my_name()
    except Exception:  # noqa: BLE001
        return "this computer"


HUB = Presence(_my_name)


def app_post(data: dict) -> dict:
    """The bridge's POST /world/presence: take the app's avatar, start the pusher, answer."""
    out = HUB.update_local(data if isinstance(data, dict) else {})
    try:
        import peers  # pylint: disable=import-outside-toplevel
        if peers.peers():
            HUB.ensure_pusher(peers.peers, peers.call)
    except Exception:  # noqa: BLE001
        pass
    return out


def world_part() -> dict:
    """What GET /world carries: the other machines' avatars and the newest chat lines."""
    snap = HUB.snapshot(0)
    return {"players": snap["players"], "chat": snap["chat"][-20:], "cursor": snap["cursor"]}


# ------------------------------------------------------------- retry a failed job
STRONGER = ("online", "claude", "openai", "anthropic", "gemini", "cloud", "groq", "openrouter", "smart")


def retry_spec(job: dict | None, model: str = "") -> dict:
    """A new job doing what a failed one tried, on a stronger model (the MMO's "retry" loot).

    Only the prompt and harmless options are kept; the model is the one asked for (from the
    app's model list) or left to the engine. Raises ValueError when there is nothing to retry.
    """
    if not job:
        raise ValueError("no such job")
    if str(job.get("status") or "") not in ("failed", "cancelled", "done"):
        raise ValueError("only a finished job can be retried")
    prompt = str(job.get("prompt") or "").strip()
    commands = job.get("commands") or []
    if not prompt and not commands:
        raise ValueError("that job has nothing to run again")
    spec: dict = {"backend": str(job.get("backend") or "local"), "agent": str(job.get("agent") or "loki"),
                  "isolate": bool(job.get("isolate", True)), "title": ("Retry: " + str(job.get("title") or prompt))[:80]}
    if prompt:
        spec["prompt"] = prompt
    if commands:
        spec["commands"] = list(commands)
    for key in ("timeout_s", "workspace", "color", "agent_id", "profile"):   # never allow_commands: no new powers
        if job.get(key):
            spec[key] = job[key]
    model = _text(model, 60)
    if model:
        spec["model"] = model
    return spec
