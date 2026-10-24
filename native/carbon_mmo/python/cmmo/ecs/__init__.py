# MODULE: ecs
"""Minimal Entity Component System.

Entities are ints, components are any Python objects keyed by type, systems are
callables `system(world, dt)`. Nothing here knows about Destiny, networking or
rendering - those reach the world through adapters and systems defined elsewhere,
so the ECS can be lifted out (or replaced by a C++ ECS) on its own.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type, TypeVar

T = TypeVar("T")
System = Callable[["World", float], None]


class World:
    def __init__(self):
        self._next_id = 1
        self._stores: Dict[Type, Dict[int, Any]] = {}
        self._alive: set = set()
        self._systems: List[Tuple[int, str, System]] = []
        self.on_destroy: List[Callable[[int], None]] = []

    # -- entities --------------------------------------------------------------
    def create(self, *components: Any, entity_id: Optional[int] = None) -> int:
        eid = entity_id if entity_id is not None else self._next_id
        if eid in self._alive:
            raise ValueError(f"entity {eid} already exists")
        self._next_id = max(self._next_id, eid + 1)
        self._alive.add(eid)
        for c in components:
            self.add(eid, c)
        return eid

    def destroy(self, eid: int) -> None:
        if eid not in self._alive:
            return
        for hook in self.on_destroy:
            hook(eid)
        for store in self._stores.values():
            store.pop(eid, None)
        self._alive.discard(eid)

    def exists(self, eid: int) -> bool:
        return eid in self._alive

    # -- components -------------------------------------------------------------
    def add(self, eid: int, component: Any) -> None:
        if eid not in self._alive:
            raise KeyError(f"no entity {eid}")
        self._stores.setdefault(type(component), {})[eid] = component

    def get(self, eid: int, ctype: Type[T]) -> Optional[T]:
        return self._stores.get(ctype, {}).get(eid)

    def remove(self, eid: int, ctype: Type) -> None:
        self._stores.get(ctype, {}).pop(eid, None)

    def query(self, *ctypes: Type) -> Iterator[Tuple]:
        """Yields (eid, comp1, comp2, ...) for entities that have all `ctypes`."""
        if not ctypes:
            return
        stores = [self._stores.get(t, {}) for t in ctypes]
        smallest = min(stores, key=len)
        for eid in list(smallest):
            if all(eid in s for s in stores):
                yield (eid, *(s[eid] for s in stores))

    # -- systems -------------------------------------------------------------------
    def add_system(self, system: System, order: int = 0, name: str = "") -> None:
        self._systems.append((order, name or getattr(system, "__name__", "system"), system))
        self._systems.sort(key=lambda s: s[0])

    def update(self, dt: float) -> None:
        for _, _, system in self._systems:
            system(self, dt)
