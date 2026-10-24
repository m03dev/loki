# MODULE: nav
"""Pathfinding / movement adapters.

The game and ECS only see `NavAdapter`. Destiny (Carbon's physics + movement
simulation) is one backend; `KinematicNavAdapter` is a dependency-free fallback with
the same open-space semantics so everything runs before Carbon is built. A navmesh
backend (e.g. Recast/Detour) would be one more subclass registered in create_nav().

Coordinates in and out are cmmo.mathbridge.Vector3, never Destiny types.
"""
from __future__ import annotations

import abc
import importlib.util
import os
from typing import Dict, Optional

from cmmo.mathbridge import Vector3


class NavAdapter(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def add_agent(self, agent_id: int, position, max_speed: float, radius: float = 1.0) -> None: ...
    @abc.abstractmethod
    def remove_agent(self, agent_id: int) -> None: ...
    @abc.abstractmethod
    def request_move(self, agent_id: int, target) -> bool:
        """Start moving toward target. Returns False if the target is unreachable."""
    @abc.abstractmethod
    def step(self, dt: float) -> None: ...
    @abc.abstractmethod
    def position(self, agent_id: int): ...
    @abc.abstractmethod
    def is_moving(self, agent_id: int) -> bool: ...


class KinematicNavAdapter(NavAdapter):
    """Straight-line steering at max_speed, stopping at the target (open space)."""

    name = "kinematic"

    def __init__(self, arrive_epsilon: float = 0.05):
        self.eps = arrive_epsilon
        self._agents: Dict[int, dict] = {}

    def add_agent(self, agent_id, position, max_speed, radius=1.0):
        self._agents[agent_id] = {"pos": Vector3(*position.to_tuple()), "speed": max_speed, "target": None}

    def remove_agent(self, agent_id):
        self._agents.pop(agent_id, None)

    def request_move(self, agent_id, target):
        a = self._agents.get(agent_id)
        if a is None:
            return False
        a["target"] = Vector3(*target.to_tuple())
        return True

    def step(self, dt):
        for a in self._agents.values():
            if a["target"] is None:
                continue
            a["pos"] = a["pos"].move_towards(a["target"], a["speed"] * dt)  # Carbon math when built
            if a["pos"].distance(a["target"]) <= self.eps:
                a["pos"], a["target"] = a["target"], None

    def position(self, agent_id):
        return self._agents[agent_id]["pos"]

    def is_moving(self, agent_id):
        return self._agents[agent_id]["target"] is not None


# MODULE: nav.destiny
class DestinyNavAdapter(NavAdapter):
    """Drives Carbon Destiny: one Ballpark, one ball per agent, GotoPoint + Evolve.

    Destiny is a fixed-tick simulation (Ballpark.tickInterval, in ms). step(dt)
    accumulates real time and calls Evolve() once per elapsed tick. Requires a Carbon
    Python build where `import destiny` works (it loads _destiny through Blue).
    """

    name = "destiny"

    def __init__(self, arrive_distance: float = 0.5, mass: float = 1.0e6, agility: float = 0.05):
        import destiny  # noqa: F401  (only importable inside a Carbon/Blue build)

        self._destiny = destiny
        self.park = destiny.Ballpark()
        if hasattr(self.park, "Start"):
            self.park.Start()
        self.arrive = arrive_distance
        self.mass, self.agility = mass, agility
        self._balls: Dict[int, object] = {}
        self._targets: Dict[int, Optional[Vector3]] = {}
        self._accum = 0.0

    @property
    def tick_seconds(self) -> float:
        interval = getattr(self.park, "tickInterval", 1000)
        return (interval or 1000) / 1000.0

    def add_agent(self, agent_id, position, max_speed, radius=1.0):
        x, y, z = position.to_tuple()
        # AddBall(id, mass, radius, maxVelocity, isFree, isGlobal, isMassive, isInteractive,
        #         isSpaceJunk, x, y, z, vx, vy, vz, agility, speedFraction)
        ball = self.park.AddBall(agent_id, self.mass, radius, max_speed, True, False, False, True, False,
                                 x, y, z, 0.0, 0.0, 0.0, self.agility, 1.0)
        self._balls[agent_id] = ball
        self._targets[agent_id] = None

    def remove_agent(self, agent_id):
        if self._balls.pop(agent_id, None) is not None:
            self.park.RemoveBall(agent_id)
        self._targets.pop(agent_id, None)

    def request_move(self, agent_id, target):
        if agent_id not in self._balls:
            return False
        self.park.GotoPoint(agent_id, *target.to_tuple())
        self._targets[agent_id] = Vector3(*target.to_tuple())
        return True

    def step(self, dt):
        self._accum += dt
        tick = self.tick_seconds
        while self._accum >= tick:
            self._accum -= tick
            self.park.Evolve()
            for aid, target in self._targets.items():
                if target is not None and self.position(aid).distance(target) <= self.arrive:
                    self.park.Stop(aid)
                    self._targets[aid] = None

    def position(self, agent_id):
        b = self._balls[agent_id]
        return Vector3(b.x, b.y, b.z)

    def is_moving(self, agent_id):
        return self._targets.get(agent_id) is not None


def destiny_available() -> bool:
    return importlib.util.find_spec("destiny") is not None


def create_nav(name: Optional[str] = None, **kwargs) -> NavAdapter:
    """name: "auto" (Destiny if importable) | "destiny" | "kinematic". Env: CMMO_NAV."""
    name = (name or os.environ.get("CMMO_NAV", "auto")).lower()
    if name == "auto":
        name = "destiny" if destiny_available() else "kinematic"
    if name == "destiny":
        return DestinyNavAdapter(**kwargs)
    if name == "kinematic":
        return KinematicNavAdapter(**kwargs)
    raise ValueError(f"unknown nav backend {name!r}")
