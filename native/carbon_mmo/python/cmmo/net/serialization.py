# MODULE: net.serialization
"""Message schemas + codecs.

Messages are plain dataclasses whose field types are declared with the aliases
below. A `Protocol` maps message ids <-> classes; codecs turn messages into frames.
Two codecs ship (binary and JSON) to keep the seam honest: swapping one for the
other changes nothing above this file.

    proto = CORE_PROTOCOL.extend()          # game layers extend, never edit, core
    @proto.message(100)
    @dataclass
    class MoveCommand:
        target: Vec3
"""
from __future__ import annotations

import abc
import base64
import dataclasses
import json
import struct
import typing
from typing import Annotated, Any, Dict, Tuple, Type

from cmmo.mathbridge import PACKED_SIZE, Vector3

# Field type aliases (the second Annotated arg is the wire type)
U8 = Annotated[int, "u8"]
U16 = Annotated[int, "u16"]
U32 = Annotated[int, "u32"]
I32 = Annotated[int, "i32"]
F32 = Annotated[float, "f32"]
F64 = Annotated[float, "f64"]
Bool = Annotated[bool, "bool"]
Str = Annotated[str, "str"]
Bytes = Annotated[bytes, "bytes"]
Vec3 = Annotated[Any, "vec3"]   # cmmo.mathbridge.Vector3 (Carbon when built)

_SCALARS = {"u8": "B", "u16": "H", "u32": "I", "i32": "i", "f32": "f", "f64": "d", "bool": "?"}
_LEN = struct.Struct("<I")
_ID = struct.Struct("<H")


class Protocol:
    """Registry of message ids. Ids 0-99 are reserved for the engine core."""

    def __init__(self, parent: "Protocol | None" = None):
        self._by_id: Dict[int, Type] = dict(parent._by_id) if parent else {}
        self._fields: Dict[Type, Tuple[Tuple[str, str], ...]] = dict(parent._fields) if parent else {}

    def extend(self) -> "Protocol":
        return Protocol(self)

    def message(self, msg_id: int):
        def register(cls):
            if not dataclasses.is_dataclass(cls):
                raise TypeError(f"{cls.__name__} must be a dataclass")
            if msg_id in self._by_id and self._by_id[msg_id] is not cls:
                raise ValueError(f"message id {msg_id} already used by {self._by_id[msg_id].__name__}")
            hints = typing.get_type_hints(cls, include_extras=True)
            fields = []
            for f in dataclasses.fields(cls):
                meta = getattr(hints[f.name], "__metadata__", ())
                if not meta or meta[0] not in (*_SCALARS, "str", "bytes", "vec3"):
                    raise TypeError(f"{cls.__name__}.{f.name}: use the U32/F64/Str/Vec3... aliases")
                fields.append((f.name, meta[0]))
            cls.__msg_id__ = msg_id
            self._by_id[msg_id] = cls
            self._fields[cls] = tuple(fields)
            return cls
        return register

    def cls_for(self, msg_id: int) -> Type:
        try:
            return self._by_id[msg_id]
        except KeyError:
            raise ValueError(f"unknown message id {msg_id}") from None

    def fields_of(self, cls) -> Tuple[Tuple[str, str], ...]:
        return self._fields[cls]


class MessageCodec(abc.ABC):
    name = "abstract"

    def __init__(self, protocol: Protocol):
        self.protocol = protocol

    @abc.abstractmethod
    def encode(self, msg) -> bytes: ...
    @abc.abstractmethod
    def decode(self, frame: bytes): ...


class BinaryCodec(MessageCodec):
    """Compact little-endian encoding; vec3 uses Carbon Vector3.pack (12 bytes)."""

    name = "binary"

    def encode(self, msg) -> bytes:
        cls = type(msg)
        out = bytearray(_ID.pack(cls.__msg_id__))
        for fname, ftype in self.protocol.fields_of(cls):
            v = getattr(msg, fname)
            if ftype in _SCALARS:
                out += struct.pack("<" + _SCALARS[ftype], v)
            elif ftype == "str":
                raw = v.encode("utf-8")
                out += _LEN.pack(len(raw)) + raw
            elif ftype == "bytes":
                out += _LEN.pack(len(v)) + bytes(v)
            else:  # vec3
                out += v.pack()
        return bytes(out)

    def decode(self, frame: bytes):
        (msg_id,) = _ID.unpack_from(frame)
        cls = self.protocol.cls_for(msg_id)
        off, kwargs = _ID.size, {}
        for fname, ftype in self.protocol.fields_of(cls):
            if ftype in _SCALARS:
                fmt = "<" + _SCALARS[ftype]
                (kwargs[fname],) = struct.unpack_from(fmt, frame, off)
                off += struct.calcsize(fmt)
            elif ftype in ("str", "bytes"):
                (n,) = _LEN.unpack_from(frame, off)
                off += 4
                raw = frame[off:off + n]
                if len(raw) != n:
                    raise ValueError("truncated frame")
                kwargs[fname] = raw.decode("utf-8") if ftype == "str" else bytes(raw)
                off += n
            else:
                kwargs[fname] = Vector3.unpack(frame[off:off + PACKED_SIZE])
                off += PACKED_SIZE
        if off != len(frame):
            raise ValueError(f"{len(frame) - off} trailing bytes in {cls.__name__}")
        return cls(**kwargs)


class JsonCodec(MessageCodec):
    """Human-readable alternative (debugging, web clients). Same Protocol, same messages."""

    name = "json"

    def encode(self, msg) -> bytes:
        cls = type(msg)
        body = {}
        for fname, ftype in self.protocol.fields_of(cls):
            v = getattr(msg, fname)
            if ftype == "vec3":
                v = list(v.to_tuple())
            elif ftype == "bytes":
                v = base64.b64encode(v).decode("ascii")
            body[fname] = v
        return json.dumps({"t": cls.__msg_id__, "f": body}, separators=(",", ":")).encode()

    def decode(self, frame: bytes):
        doc = json.loads(frame)
        cls = self.protocol.cls_for(doc["t"])
        kwargs = {}
        for fname, ftype in self.protocol.fields_of(cls):
            v = doc["f"][fname]
            if ftype == "vec3":
                v = Vector3(*v)
            elif ftype == "bytes":
                v = base64.b64decode(v)
            kwargs[fname] = v
        return cls(**kwargs)


CODECS = {"binary": BinaryCodec, "json": JsonCodec}
