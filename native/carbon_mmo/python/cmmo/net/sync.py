# MODULE: net.sync
"""Server/client synchronisation layer.

Composes the four pluggable parts - Transport, ConnectionManager, MessageCodec,
Heartbeat - into a SyncServer and SyncClient. Replication is generic: the server
publishes opaque bytes per (entity_id, component); clients mirror them. Game code
decides what those bytes mean (see cmmo_game/), so this file has no game logic.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple, Type

from cmmo.net.connection import ConnectionManager, Peer
from cmmo.net.heartbeat import HeartbeatClient, HeartbeatServer
from cmmo.net.messages import (CORE_PROTOCOL, PROTOCOL_VERSION, EntityRemoved, Goodbye,
                               Hello, Ping, Pong, StateUpdate, Welcome)
from cmmo.net.serialization import CODECS, MessageCodec, Protocol
from cmmo.net.transport import Transport, create_transport

log = logging.getLogger("cmmo.net")
Handler = Callable[..., None]


def _make_codec(codec, protocol: Protocol) -> MessageCodec:
    if isinstance(codec, MessageCodec):
        return codec
    return CODECS[codec](protocol)


class SyncServer:
    def __init__(self, protocol: Protocol = CORE_PROTOCOL, codec="binary", transport: Optional[Transport] = None,
                 timeout: float = 10.0, clock: Callable[[], float] = time.monotonic, info: str = ""):
        self.clock = clock
        self.transport = transport or create_transport()
        self.codec = _make_codec(codec, protocol)
        self.conns = ConnectionManager(self.transport, timeout=timeout, clock=clock)
        self.heartbeat = HeartbeatServer(clock)
        self.info = info
        self._handlers: Dict[Type, List[Handler]] = {}
        self._state: Dict[Tuple[int, str], bytes] = {}
        self._dirty: Set[Tuple[int, str]] = set()
        self.on_join: Callable[[Peer], None] = lambda p: None
        self.on_leave: Callable[[Peer, str], None] = lambda p, r: None
        self.conns.on_frame = self._on_frame
        self.conns.on_disconnect = self._on_disconnect
        self.address: Optional[Tuple[str, int]] = None

    # -- lifecycle ----------------------------------------------------------------
    def start(self, host: str = "127.0.0.1", port: int = 0) -> Tuple[str, int]:
        self.address = self.transport.listen(host, port)
        log.info("server listening on %s:%d (%s/%s)", *self.address, self.transport.name, self.codec.name)
        return self.address

    def poll(self, timeout: float = 0.0) -> None:
        self.conns.pump(timeout)
        self.flush()

    def serve(self, stop: threading.Event, tick: float = 0.01, on_tick: Optional[Callable[[float], None]] = None):
        last = self.clock()
        while not stop.is_set():
            self.conns.pump(tick)
            now = self.clock()
            if on_tick is not None:
                on_tick(now - last)
            last = now
            self.flush()

    def stop(self) -> None:
        for p in list(self.conns.peers.values()):
            self.send(p.id, Goodbye("server shutting down"))
        self.transport.shutdown()

    # -- messaging ------------------------------------------------------------------
    def on(self, msg_cls: Type, handler: Handler) -> None:
        """handler(peer, msg) for messages of msg_cls from ready peers."""
        self._handlers.setdefault(msg_cls, []).append(handler)

    def send(self, peer_id: int, msg) -> None:
        self.conns.send(peer_id, self.codec.encode(msg))

    def broadcast(self, msg, exclude: Optional[int] = None) -> None:
        frame = self.codec.encode(msg)
        for p in self.conns.ready_peers():
            if p.id != exclude:
                self.conns.send(p.id, frame)

    # -- replication -----------------------------------------------------------------
    def set_state(self, entity_id: int, component: str, data: bytes) -> None:
        key = (entity_id, component)
        if self._state.get(key) != data:
            self._state[key] = data
            self._dirty.add(key)

    def remove_entity(self, entity_id: int) -> None:
        keys = [k for k in self._state if k[0] == entity_id]
        for k in keys:
            self._state.pop(k, None)
            self._dirty.discard(k)
        if keys:
            self.broadcast(EntityRemoved(entity_id))

    def flush(self) -> None:
        if not self._dirty:
            return
        now = self.clock()
        for key in sorted(self._dirty):
            self.broadcast(StateUpdate(key[0], key[1], self._state[key], now))
        self._dirty.clear()

    # -- internals -------------------------------------------------------------------------
    def _on_frame(self, peer: Peer, frame: bytes) -> None:
        try:
            msg = self.codec.decode(frame)
        except Exception as e:  # malformed input must never take the server down
            log.warning("peer %d sent bad frame (%s); disconnecting", peer.id, e)
            self.conns.disconnect(peer.id, "protocol error")
            return
        if isinstance(msg, Ping):
            self.send(peer.id, self.heartbeat.answer(msg))
            return
        if not peer.ready:
            if isinstance(msg, Hello) and msg.version == PROTOCOL_VERSION:
                peer.ready, peer.name = True, msg.name
                self.send(peer.id, Welcome(peer.id, self.clock(), self.info))
                now = self.clock()
                for (eid, comp), data in sorted(self._state.items()):  # snapshot for late joiners
                    self.send(peer.id, StateUpdate(eid, comp, data, now))
                self.on_join(peer)
            else:
                self.conns.disconnect(peer.id, "handshake failed")
            return
        for handler in self._handlers.get(type(msg), ()):
            try:
                handler(peer, msg)
            except Exception:
                log.exception("handler for %s failed", type(msg).__name__)

    def _on_disconnect(self, peer: Peer, reason: str) -> None:
        if peer.ready:
            self.on_leave(peer, reason)


class SyncClient:
    def __init__(self, protocol: Protocol = CORE_PROTOCOL, codec="binary", transport: Optional[Transport] = None,
                 name: str = "client", clock: Callable[[], float] = time.monotonic, ping_interval: float = 0.1):
        self.clock = clock
        self.transport = transport or create_transport()
        self.codec = _make_codec(codec, protocol)
        self.heartbeat = HeartbeatClient(interval=ping_interval, clock=clock)
        self.name = name
        self.conn_id: Optional[int] = None
        self.client_id: Optional[int] = None
        self.server_info = ""
        self.connected = False
        self.state: Dict[int, Dict[str, bytes]] = {}
        self._handlers: Dict[Type, List[Handler]] = {}
        self.on_state: Callable[[int, str, bytes, float], None] = lambda e, c, d, t: None
        self.on_removed: Callable[[int], None] = lambda e: None

    def connect(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.conn_id = self.transport.connect(host, port, timeout)
        self.transport.send(self.conn_id, self.codec.encode(Hello(self.name, PROTOCOL_VERSION)))

    def on(self, msg_cls: Type, handler: Handler) -> None:
        self._handlers.setdefault(msg_cls, []).append(handler)

    def send(self, msg) -> None:
        if self.conn_id is not None:
            self.transport.send(self.conn_id, self.codec.encode(msg))

    def poll(self, timeout: float = 0.0) -> None:
        if self.conn_id is not None and self.connected:
            ping = self.heartbeat.due()
            if ping is not None:
                self.send(ping)
        for ev in self.transport.poll(timeout):
            if ev.kind == "disconnected":
                self.connected, self.conn_id = False, None
            elif ev.kind == "frame":
                self._dispatch(self.codec.decode(ev.data))

    def wait_until(self, predicate: Callable[[], bool], timeout: float = 5.0, step: float = 0.005) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.poll(step)
            if predicate():
                return True
        return predicate()

    def server_time(self) -> float:
        return self.heartbeat.server_time()

    def close(self) -> None:
        if self.conn_id is not None:
            self.transport.close(self.conn_id, "client closed")
        self.transport.shutdown()
        self.connected = False

    def _dispatch(self, msg) -> None:
        if isinstance(msg, Welcome):
            self.client_id, self.server_info, self.connected = msg.client_id, msg.info, True
            self.heartbeat.seed(msg.server_time)
        elif isinstance(msg, Pong):
            self.heartbeat.on_pong(msg)
        elif isinstance(msg, StateUpdate):
            self.state.setdefault(msg.entity_id, {})[msg.component] = msg.data
            self.on_state(msg.entity_id, msg.component, msg.data, msg.server_time)
        elif isinstance(msg, EntityRemoved):
            self.state.pop(msg.entity_id, None)
            self.on_removed(msg.entity_id)
        elif isinstance(msg, Goodbye):
            self.connected = False
        for handler in self._handlers.get(type(msg), ()):
            handler(msg)
