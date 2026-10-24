# MODULE: math
"""Single import point for vector math.

Uses Carbon's Vector3 through the compiled `cmmo_math` extension when it has been
built (build/python is searched automatically), otherwise a pure-Python Vector3
with the identical API and the identical 12-byte wire format, so the network
layer never cares which one is active.

Force a backend with CMMO_MATH=carbon|python.
"""
from __future__ import annotations

import glob
import math
import os
import struct
import sys

_PACK = struct.Struct("<3f")
PACKED_SIZE = _PACK.size


class PyVector3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        # float32 round-trip keeps results identical to the C++ backend
        self.x, self.y, self.z = _PACK.unpack(_PACK.pack(x, y, z))

    def __add__(self, o): return PyVector3(self.x + o.x, self.y + o.y, self.z + o.z)
    def __sub__(self, o): return PyVector3(self.x - o.x, self.y - o.y, self.z - o.z)
    def __mul__(self, f): return PyVector3(self.x * f, self.y * f, self.z * f)
    __rmul__ = __mul__
    def __truediv__(self, f): return PyVector3(self.x / f, self.y / f, self.z / f)
    def __neg__(self): return PyVector3(-self.x, -self.y, -self.z)
    def __eq__(self, o): return isinstance(o, PyVector3) and self.to_tuple() == o.to_tuple()
    def __hash__(self): return hash(self.to_tuple())
    def __repr__(self): return f"Vector3({self.x:g}, {self.y:g}, {self.z:g})"
    def __getstate__(self): return self.to_tuple()
    def __setstate__(self, s): self.x, self.y, self.z = s

    def length_sq(self): return self.x * self.x + self.y * self.y + self.z * self.z
    def length(self): return math.sqrt(self.length_sq())
    def dot(self, o): return self.x * o.x + self.y * o.y + self.z * o.z
    def cross(self, o):
        return PyVector3(self.y * o.z - self.z * o.y, self.z * o.x - self.x * o.z, self.x * o.y - self.y * o.x)
    def distance(self, o): return (self - o).length()
    def normalized(self):
        n = self.length()
        return PyVector3(self.x / n, self.y / n, self.z / n) if n > 0 else PyVector3()
    def lerp(self, o, s): return self + (o - self) * s
    def move_towards(self, target, max_step):
        delta = target - self
        d = delta.length()
        return PyVector3(target.x, target.y, target.z) if d <= max_step or d == 0 else self + delta * (max_step / d)
    def to_tuple(self): return (self.x, self.y, self.z)
    def pack(self) -> bytes: return _PACK.pack(self.x, self.y, self.z)

    @staticmethod
    def unpack(data: bytes) -> "PyVector3":
        if len(data) != PACKED_SIZE:
            raise ValueError("Vector3.unpack expects exactly 12 bytes")
        return PyVector3(*_PACK.unpack(data))


def _find_build_dirs():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = os.environ.get("CMMO_BUILD_DIR")
    candidates = [os.path.join(env, "python")] if env else []
    candidates += sorted(glob.glob(os.path.join(root, "build*", "python")))
    return [c for c in candidates if os.path.isdir(c)]


def _load_carbon():
    for d in _find_build_dirs():
        if d not in sys.path:
            sys.path.append(d)
    import cmmo_math  # noqa: E402  (C++ extension)
    return cmmo_math.Vector3, cmmo_math.BACKEND


_wanted = os.environ.get("CMMO_MATH", "auto").lower()
if _wanted == "python":
    Vector3, BACKEND = PyVector3, "python-fallback"
else:
    try:
        Vector3, BACKEND = _load_carbon()
    except ImportError:
        if _wanted == "carbon":
            raise ImportError("CMMO_MATH=carbon but cmmo_math is not built - run the CMake build first")
        Vector3, BACKEND = PyVector3, "python-fallback"

IS_CARBON = BACKEND.startswith("carbon")

__all__ = ["Vector3", "PyVector3", "BACKEND", "IS_CARBON", "PACKED_SIZE"]
