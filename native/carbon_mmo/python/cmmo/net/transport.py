# MODULE: net.transport
"""Byte transport: moves length-prefixed frames between endpoints.

Everything above this file speaks in whole frames (bytes) and connection ids.
To swap the networking backend, implement `Transport` and register it in
`create_transport()`; connection management, serialization and heartbeat don't change.

Backends
  "std"      stdlib sockets + selectors (non-blocking, single-threaded poll loop)
  "carbonio" the same loop running on CarbonIO's sockets (_carbonsocket / carbonselect),
             installed the way carbon-io's README prescribes: inject the modules into
             sys.modules under the stdlib names. Needs a Carbon Python build.
"""
from __future__ import annotations

import abc
import errno
import importlib
import os
import selectors
import socket
import struct
import sys
from typing import Dict, List, NamedTuple, Optional, Tuple

_HEADER = struct.Struct("<I")
MAX_FRAME = 1 << 20  # 1 MiB


class TransportEvent(NamedTuple):
    kind: str          # "connected" | "disconnected" | "frame"
    conn_id: int
    data: bytes = b""  # frame payload, or the disconnect reason (utf-8)


class Transport(abc.ABC):
    """Frame transport. Not thread-safe: one owner calls poll()."""

    name = "abstract"

    @abc.abstractmethod
    def listen(self, host: str, port: int) -> Tuple[str, int]: ...
    @abc.abstractmethod
    def connect(self, host: str, port: int, timeout: float = 5.0) -> int: ...
    @abc.abstractmethod
    def send(self, conn_id: int, frame: bytes) -> None: ...
    @abc.abstractmethod
    def poll(self, timeout: float = 0.0) -> List[TransportEvent]: ...
    @abc.abstractmethod
    def close(self, conn_id: int, reason: str = "closed") -> None: ...
    @abc.abstractmethod
    def shutdown(self) -> None: ...
    @abc.abstractmethod
    def peer_address(self, conn_id: int) -> Optional[Tuple[str, int]]: ...


class _Conn:
    __slots__ = ("sock", "addr", "rbuf", "wbuf")

    def __init__(self, sock, addr):
        self.sock, self.addr = sock, addr
        self.rbuf, self.wbuf = bytearray(), bytearray()


class SelectorTransport(Transport):
    """TCP with 4-byte little-endian length prefixes, non-blocking, selector-driven."""

    name = "std"

    def __init__(self, socket_module=socket, selectors_module=selectors):
        self._socket = socket_module
        self._sel = selectors_module.DefaultSelector()
        self._listener = None
        self._conns: Dict[int, _Conn] = {}
        self._next_id = 1
        self._pending: List[TransportEvent] = []

    # -- setup ------------------------------------------------------------------
    def listen(self, host="127.0.0.1", port=0):
        s = self._socket.socket(self._socket.AF_INET, self._socket.SOCK_STREAM)
        s.setsockopt(self._socket.SOL_SOCKET, self._socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(128)
        s.setblocking(False)
        self._listener = s
        self._sel.register(s, selectors.EVENT_READ, None)
        return s.getsockname()[:2]

    def connect(self, host, port, timeout=5.0):
        s = self._socket.create_connection((host, port), timeout=timeout)
        return self._add(s, (host, port))

    def _add(self, sock, addr) -> int:
        sock.setblocking(False)
        try:
            sock.setsockopt(self._socket.IPPROTO_TCP, self._socket.TCP_NODELAY, 1)
        except OSError:
            pass
        cid = self._next_id
        self._next_id += 1
        self._conns[cid] = _Conn(sock, addr)
        self._sel.register(sock, selectors.EVENT_READ, cid)
        self._pending.append(TransportEvent("connected", cid))
        return cid

    # -- io -----------------------------------------------------------------------
    def send(self, conn_id, frame):
        c = self._conns.get(conn_id)
        if c is None:
            return
        if len(frame) > MAX_FRAME:
            raise ValueError(f"frame of {len(frame)} bytes exceeds MAX_FRAME")
        c.wbuf += _HEADER.pack(len(frame)) + frame
        self._flush(conn_id, c)

    def _flush(self, cid, c):
        try:
            while c.wbuf:
                n = c.sock.send(c.wbuf)
                if n <= 0:
                    break
                del c.wbuf[:n]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as e:
            self._drop(cid, f"send failed: {e}")
            return
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if c.wbuf else 0)
        try:
            self._sel.modify(c.sock, events, cid)
        except (KeyError, ValueError):
            pass

    def poll(self, timeout=0.0):
        out, self._pending = self._pending, []
        if not self._sel.get_map():
            return out
        for key, mask in self._sel.select(0 if out else timeout):
            if key.data is None:
                self._accept()
                continue
            cid = key.data
            c = self._conns.get(cid)
            if c is None:
                continue
            if mask & selectors.EVENT_WRITE:
                self._flush(cid, c)
            if mask & selectors.EVENT_READ and cid in self._conns:
                self._read(cid, c)
        out += self._pending
        self._pending = []
        return out

    def _accept(self):
        while True:
            try:
                sock, addr = self._listener.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            self._add(sock, addr[:2])

    def _read(self, cid, c):
        try:
            while True:
                chunk = c.sock.recv(65536)
                if not chunk:
                    self._drop(cid, "peer closed")
                    return
                c.rbuf += chunk
                if len(chunk) < 65536:
                    break
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as e:
            if getattr(e, "errno", None) not in (errno.EAGAIN, errno.EWOULDBLOCK):
                self._drop(cid, f"recv failed: {e}")
                return
        while len(c.rbuf) >= 4:
            (n,) = _HEADER.unpack_from(c.rbuf)
            if n > MAX_FRAME:
                self._drop(cid, "oversized frame")
                return
            if len(c.rbuf) < 4 + n:
                break
            frame = bytes(c.rbuf[4:4 + n])
            del c.rbuf[:4 + n]
            self._pending.append(TransportEvent("frame", cid, frame))

    def _drop(self, cid, reason):
        c = self._conns.pop(cid, None)
        if c is None:
            return
        try:
            self._sel.unregister(c.sock)
        except (KeyError, ValueError):
            pass
        try:
            c.sock.close()
        except OSError:
            pass
        self._pending.append(TransportEvent("disconnected", cid, reason.encode()))

    def close(self, conn_id, reason="closed"):
        c = self._conns.get(conn_id)
        if c is not None and c.wbuf:
            self._flush(conn_id, c)  # best effort: deliver a final Goodbye
        self._drop(conn_id, reason)

    def shutdown(self):
        for cid in list(self._conns):
            self.close(cid, "shutdown")
        if self._listener is not None:
            try:
                self._sel.unregister(self._listener)
            except (KeyError, ValueError):
                pass
            self._listener.close()
            self._listener = None
        self._sel.close()

    def peer_address(self, conn_id):
        c = self._conns.get(conn_id)
        return c.addr if c else None


# MODULE: net.transport.carbonio
_CARBON_SOCKET_NAMES = ("_carbonsocket", "_carbonsocket_release", "_carbonsocket_internal")
_CARBON_SELECT_NAMES = ("carbonselect", "carbonselect_release", "carbonselect_internal")


def carbonio_available() -> bool:
    import importlib.util
    return any(importlib.util.find_spec(n) for n in _CARBON_SOCKET_NAMES)


def install_carbonio():
    """Swap the stdlib socket/select C modules for CarbonIO's (per carbon-io README).

    Returns (socket_module, selectors_module) bound to CarbonIO. Must run inside a
    Carbon Python build where carbon-scheduler is importable.
    """
    def first(names):
        for n in names:
            try:
                return importlib.import_module(n)
            except ImportError:
                continue
        raise ImportError(f"none of {names} importable - build carbonengine/io first")

    sys.modules["_socket"] = first(_CARBON_SOCKET_NAMES)
    sys.modules["select"] = first(_CARBON_SELECT_NAMES)
    import socket as std_socket
    import selectors as std_selectors
    return importlib.reload(std_socket), importlib.reload(std_selectors)


class CarbonIOTransport(SelectorTransport):
    name = "carbonio"

    def __init__(self):
        sock_mod, sel_mod = install_carbonio()
        super().__init__(sock_mod, sel_mod)


def create_transport(name: Optional[str] = None) -> Transport:
    """name: "std" | "carbonio" | "auto" (default from CMMO_TRANSPORT, else "std")."""
    name = (name or os.environ.get("CMMO_TRANSPORT", "std")).lower()
    if name == "auto":
        name = "carbonio" if carbonio_available() else "std"
    if name == "std":
        return SelectorTransport()
    if name == "carbonio":
        return CarbonIOTransport()
    raise ValueError(f"unknown transport {name!r}")
