# MODULE: net.connection
"""Connection management: peer bookkeeping, handshake state and timeouts.

Consumes TransportEvents, owns the Peer table, and reports lifecycle changes via
callbacks. It never decodes messages - the sync layer tells it when a peer has
completed the handshake and when traffic arrived.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from cmmo.net.transport import Transport, TransportEvent


@dataclass
class Peer:
    id: int
    address: Optional[Tuple[str, int]]
    connected_at: float
    last_seen: float
    name: str = ""
    ready: bool = False            # handshake completed
    rtt: Optional[float] = None    # seconds, from heartbeat
    data: Dict = field(default_factory=dict)  # free slot for higher layers


class ConnectionManager:
    def __init__(self, transport: Transport, timeout: float = 10.0, clock: Callable[[], float] = time.monotonic):
        self.transport = transport
        self.timeout = timeout
        self.clock = clock
        self.peers: Dict[int, Peer] = {}
        self.on_connect: Callable[[Peer], None] = lambda p: None
        self.on_disconnect: Callable[[Peer, str], None] = lambda p, r: None
        self.on_frame: Callable[[Peer, bytes], None] = lambda p, f: None

    def pump(self, timeout: float = 0.0) -> int:
        """Poll the transport once and dispatch. Returns number of events handled."""
        events: List[TransportEvent] = self.transport.poll(timeout)
        for ev in events:
            if ev.kind == "connected":
                now = self.clock()
                peer = Peer(ev.conn_id, self.transport.peer_address(ev.conn_id), now, now)
                self.peers[ev.conn_id] = peer
                self.on_connect(peer)
            elif ev.kind == "disconnected":
                peer = self.peers.pop(ev.conn_id, None)
                if peer is not None:
                    self.on_disconnect(peer, ev.data.decode(errors="replace"))
            elif ev.kind == "frame":
                peer = self.peers.get(ev.conn_id)
                if peer is not None:
                    peer.last_seen = self.clock()
                    self.on_frame(peer, ev.data)
        self.expire()
        return len(events)

    def expire(self) -> None:
        now = self.clock()
        for peer in [p for p in self.peers.values() if now - p.last_seen > self.timeout]:
            self.disconnect(peer.id, "timeout")

    def send(self, peer_id: int, frame: bytes) -> None:
        self.transport.send(peer_id, frame)

    def disconnect(self, peer_id: int, reason: str) -> None:
        self.transport.close(peer_id, reason)
        # the transport queues a "disconnected" event; drop now so callers see it immediately
        peer = self.peers.pop(peer_id, None)
        if peer is not None:
            self.on_disconnect(peer, reason)

    def ready_peers(self) -> List[Peer]:
        return [p for p in self.peers.values() if p.ready]
