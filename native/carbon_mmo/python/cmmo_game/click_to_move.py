# MODULE: game.click_to_move
"""Server-authoritative click-to-move.

client --MoveCommand(target)--> server --NavAdapter (Destiny)--> path/steering
server --StateUpdate(entity, "pos", Vector3)--> every client

Wiring only: ECS for state, NavAdapter for movement, SyncServer for replication.
Any of the three can be swapped without touching this file's logic.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional

from cmmo.ecs import World
from cmmo.mathbridge import Vector3
from cmmo.nav import NavAdapter, create_nav
from cmmo.net import CORE_PROTOCOL, F32, SyncClient, SyncServer, Vec3, create_transport

# ---------------------------------------------------------------- protocol (ids >= 100)
PROTOCOL = CORE_PROTOCOL.extend()


@PROTOCOL.message(100)
@dataclass
class MoveCommand:
    target: Vec3


@PROTOCOL.message(101)
@dataclass
class MoveRejected:
    target: Vec3
    max_range: F32


# ---------------------------------------------------------------- components (plain data)
@dataclass
class Transform:
    position: object  # Vector3


@dataclass
class NavAgent:
    max_speed: float
    radius: float = 0.5


@dataclass
class Replicated:
    component: str = "pos"


POS = "pos"


class ClickToMoveServer:
    def __init__(self, nav: Optional[NavAdapter] = None, codec: str = "binary", transport: Optional[str] = None,
                 speed: float = 20.0, world_radius: float = 1000.0, tick_rate: float = 30.0):
        self.nav = nav or create_nav()
        self.world = World()
        self.speed, self.world_radius, self.tick = speed, world_radius, 1.0 / tick_rate
        self.net = SyncServer(PROTOCOL, codec=codec, transport=create_transport(transport),
                              info=f"click-to-move nav={self.nav.name}")
        self.net.on_join = self._spawn
        self.net.on_leave = lambda peer, reason: self.world.destroy(peer.id)
        self.net.on(MoveCommand, self._on_move)
        self.world.on_destroy.append(self._despawn)
        self.world.add_system(self._nav_system, order=10)
        self.world.add_system(self._replication_system, order=20)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------------
    def start(self, host="127.0.0.1", port=0):
        addr = self.net.start(host, port)
        self._thread = threading.Thread(target=self.net.serve, args=(self._stop, self.tick, self.world.update),
                                        daemon=True)
        self._thread.start()
        return addr

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2.0)
        self.net.stop()

    # -- gameplay ----------------------------------------------------------------
    def _spawn(self, peer):
        spawn = Vector3(5.0 * peer.id, 0.0, 0.0)
        eid = self.world.create(Transform(spawn), NavAgent(self.speed), Replicated(), entity_id=peer.id)
        self.nav.add_agent(eid, spawn, self.speed, 0.5)

    def _despawn(self, eid):
        self.nav.remove_agent(eid)
        self.net.remove_entity(eid)

    def _on_move(self, peer, msg: MoveCommand):
        if not self.world.exists(peer.id):
            return
        if msg.target.length() > self.world_radius or not self.nav.request_move(peer.id, msg.target):
            self.net.send(peer.id, MoveRejected(msg.target, self.world_radius))

    # -- systems -----------------------------------------------------------------
    def _nav_system(self, world: World, dt: float):
        self.nav.step(dt)
        for eid, transform, _agent in world.query(Transform, NavAgent):
            transform.position = self.nav.position(eid)

    def _replication_system(self, world: World, dt: float):
        for eid, transform, rep in world.query(Transform, Replicated):
            self.net.set_state(eid, rep.component, transform.position.pack())  # diffed inside


class ClickToMoveClient:
    def __init__(self, name: str, codec: str = "binary", transport: Optional[str] = None):
        self.net = SyncClient(PROTOCOL, codec=codec, transport=create_transport(transport), name=name)
        self.history: Dict[int, list] = {}
        self.rejected = []
        self.net.on_state = self._on_state
        self.net.on(MoveRejected, self.rejected.append)

    def connect(self, host, port):
        self.net.connect(host, port)
        return self.net.wait_until(lambda: self.net.connected, 5.0)

    def click(self, target) -> None:
        """What a mouse click on the ground turns into."""
        self.net.send(MoveCommand(target))

    def positions(self) -> Dict[int, object]:
        return {eid: Vector3.unpack(c[POS]) for eid, c in self.net.state.items() if POS in c}

    def _on_state(self, eid, component, data, server_time):
        if component == POS:
            self.history.setdefault(eid, []).append(Vector3.unpack(data))
