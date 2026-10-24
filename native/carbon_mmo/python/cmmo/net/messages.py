# MODULE: net.messages
"""Engine-core messages (ids 0-99). Game layers add theirs via CORE_PROTOCOL.extend()."""
from dataclasses import dataclass

from cmmo.net.serialization import F64, Bytes, Protocol, Str, U16, U32

PROTOCOL_VERSION = 1
CORE_PROTOCOL = Protocol()


@CORE_PROTOCOL.message(1)
@dataclass
class Hello:
    name: Str
    version: U16


@CORE_PROTOCOL.message(2)
@dataclass
class Welcome:
    client_id: U32
    server_time: F64
    info: Str          # free-form server description (backends in use etc.)


@CORE_PROTOCOL.message(3)
@dataclass
class Goodbye:
    reason: Str


@CORE_PROTOCOL.message(10)
@dataclass
class Ping:
    client_time: F64


@CORE_PROTOCOL.message(11)
@dataclass
class Pong:
    client_time: F64
    server_time: F64


@CORE_PROTOCOL.message(20)
@dataclass
class StateUpdate:
    """Replicated state: opaque bytes per (entity, component). The net layer never
    interprets `data` - that's what keeps it free of game logic."""
    entity_id: U32
    component: Str
    data: Bytes
    server_time: F64


@CORE_PROTOCOL.message(21)
@dataclass
class EntityRemoved:
    entity_id: U32
