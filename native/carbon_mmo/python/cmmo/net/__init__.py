# MODULE: net
"""Pluggable networking: replace any one part without touching the others.

    transport.py      bytes <-> frames over sockets (std or CarbonIO)
    connection.py     peers, handshake state, timeouts
    serialization.py  message schemas + binary/JSON codecs
    heartbeat.py      ping/pong, RTT, server clock estimate
    sync.py           SyncServer / SyncClient built from the above
"""
from cmmo.net.connection import ConnectionManager, Peer
from cmmo.net.heartbeat import HeartbeatClient, HeartbeatServer
from cmmo.net.messages import CORE_PROTOCOL, EntityRemoved, StateUpdate
from cmmo.net.serialization import (F32, F64, I32, U8, U16, U32, BinaryCodec, Bool, Bytes,
                                    JsonCodec, MessageCodec, Protocol, Str, Vec3)
from cmmo.net.sync import SyncClient, SyncServer
from cmmo.net.transport import Transport, create_transport

__all__ = [
    "ConnectionManager", "Peer", "HeartbeatClient", "HeartbeatServer", "CORE_PROTOCOL",
    "EntityRemoved", "StateUpdate", "F32", "F64", "I32", "U8", "U16", "U32", "Bool", "Bytes",
    "Str", "Vec3", "BinaryCodec", "JsonCodec", "MessageCodec", "Protocol", "SyncClient",
    "SyncServer", "Transport", "create_transport",
]
