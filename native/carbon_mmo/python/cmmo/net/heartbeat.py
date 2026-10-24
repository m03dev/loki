# MODULE: net.heartbeat
"""Heartbeat and clock synchronisation (NTP-style).

Client sends Ping(client_time) every `interval`; server answers Pong(client_time,
server_time). From each round trip the client gets
    rtt    = now - client_time
    offset = server_time + rtt/2 - now
and keeps the offset from the lowest-RTT samples (least queueing noise).
`server_time()` is then the client's estimate of the server clock - use it to
timestamp commands and to interpolate replicated state.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Optional

from cmmo.net.messages import Ping, Pong


class HeartbeatServer:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock

    def answer(self, ping: Ping) -> Pong:
        return Pong(client_time=ping.client_time, server_time=self.clock())


class HeartbeatClient:
    def __init__(self, interval: float = 0.25, samples: int = 16, clock: Callable[[], float] = time.monotonic):
        self.interval = interval
        self.clock = clock
        self._samples: deque = deque(maxlen=samples)  # (rtt, offset)
        self._next_ping = 0.0
        self.offset: Optional[float] = None
        self.rtt: Optional[float] = None

    def seed(self, server_time: float) -> None:
        """Rough offset from the Welcome message until real samples arrive."""
        if self.offset is None:
            self.offset = server_time - self.clock()

    def due(self) -> Optional[Ping]:
        now = self.clock()
        if now >= self._next_ping:
            self._next_ping = now + self.interval
            return Ping(client_time=now)
        return None

    def on_pong(self, pong: Pong) -> None:
        now = self.clock()
        rtt = max(0.0, now - pong.client_time)
        self._samples.append((rtt, pong.server_time + rtt / 2.0 - now))
        best = sorted(self._samples)[: max(1, len(self._samples) // 2)]
        self.offset = sum(o for _, o in best) / len(best)
        self.rtt = sum(r for r, _ in best) / len(best)

    @property
    def synced(self) -> bool:
        return len(self._samples) >= 3

    def server_time(self) -> float:
        return self.clock() + (self.offset or 0.0)
