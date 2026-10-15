"""peer_forward - reach a Loki on another network as if it were local.

Loki's peer link only serves, and only dials, PRIVATE addresses (your LAN, Tailscale
100.64/10, localhost) - see peers.private_host(). When two machines are on different
networks they cannot reach each other's port 8768 directly, so:

  1. On the machine that must be REACHABLE (the PC), publish its peer port with a public
     relay that needs no account, e.g. bore (https://github.com/ekzhang/bore):

         bore local 8768 --to bore.pub --port 28768

  2. On the OTHER machine (the Mac), run this forwarder: it listens on a loopback port and
     tunnels every connection to the relay. Loki then dials a localhost peer and the signed
     link works unchanged:

         python tools/peer_forward.py --listen 127.0.0.1:8768 --to bore.pub:28768

     and set in harness_data/.env:   LOKI_PEERS=pc=http://127.0.0.1:8768

Do it on both machines (each publishing, the other forwarding) so either can reach the
other - "Update everything" needs the PC to reach the Mac too.

Why loopback: peers.private_host() accepts a private IP, a Tailscale address, or a name, but
NOT a public hostname; a loopback listener sidesteps that without weakening the link's own
HMAC signature check, which still runs on every request.

Security: the relay endpoint is on the public internet. Requests stay signed (the shared
secret is the gate) but the TCP hop is not encrypted end to end - prefer Tailscale when you
can. See docs/operations/OFF_NETWORK.md.

Stdlib only, same code on macOS and Windows. Self-test:  python tools/peer_forward.py --check
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

BUFFER = 65536
CONNECT_TIMEOUT_S = 10.0


def parse_address(text: str, default_host: str = "127.0.0.1") -> "tuple[str, int]":
    """'host:port' or 'port' -> (host, port). Bracket an IPv6 literal: [::1]:8768."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty address")
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        return host or default_host, int(rest.lstrip(":"))
    if ":" in text:
        host, _, port = text.rpartition(":")
        return (host or default_host), int(port)
    return default_host, int(text)


def _close(sock: "socket.socket | None") -> None:
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(BUFFER)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        _close(src)
        _close(dst)


class Forwarder:
    """A loopback listener that pipes every connection to a remote host:port."""

    def __init__(self, listen_host: str, listen_port: int, target_host: str, target_port: int,
                 connect_timeout: float = CONNECT_TIMEOUT_S) -> None:
        self.listen = (listen_host, int(listen_port))
        self.target = (target_host, int(target_port))
        self.connect_timeout = connect_timeout
        self._server: "socket.socket | None" = None
        self._thread: "threading.Thread | None" = None
        self._stopped = threading.Event()

    @property
    def address(self) -> "tuple[str, int]":
        return self._server.getsockname()[:2] if self._server else self.listen

    def start(self) -> "Forwarder":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(self.listen)
        server.listen(64)
        server.settimeout(0.5)
        self._server = server
        self._stopped.clear()
        self._thread = threading.Thread(target=self._accept, name="peer-forward", daemon=True)
        self._thread.start()
        return self

    def _accept(self) -> None:
        while not self._stopped.is_set():
            try:
                client, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(self.target, timeout=self.connect_timeout)
        except OSError:
            _close(client)
            return
        threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=_pipe, args=(upstream, client), daemon=True).start()

    def stop(self) -> None:
        self._stopped.set()
        _close(self._server)
        if self._thread is not None:
            self._thread.join(timeout=2)


def self_check() -> int:
    """Prove the forwarder moves bytes both ways, using only loopback."""
    echo = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    echo.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    echo.bind(("127.0.0.1", 0))
    echo.listen(8)
    echo_port = echo.getsockname()[1]

    def echo_once() -> None:
        try:
            conn, _ = echo.accept()
        except OSError:
            return
        try:
            conn.sendall(conn.recv(BUFFER))
        except OSError:
            pass
        finally:
            _close(conn)

    threading.Thread(target=echo_once, daemon=True).start()
    forwarder = Forwarder("127.0.0.1", 0, "127.0.0.1", echo_port).start()
    ok = False
    try:
        with socket.create_connection(forwarder.address, timeout=5) as client:
            client.sendall(b"loki-forward-check")
            ok = client.recv(BUFFER) == b"loki-forward-check"
    except OSError:
        ok = False
    finally:
        forwarder.stop()
        _close(echo)
    print("peer_forward self-check: %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Forward a local port to a Loki peer reached through a relay.")
    parser.add_argument("--listen", default="127.0.0.1:8768", help="local address to listen on (host:port)")
    parser.add_argument("--to", dest="target", default="", help="remote relay address (host:port), e.g. bore.pub:28768")
    parser.add_argument("--check", action="store_true", help="run a loopback self-test and exit")
    args = parser.parse_args(argv)
    if args.check:
        return self_check()
    if not args.target:
        parser.error("--to host:port is required (e.g. --to bore.pub:28768)")
    listen_host, listen_port = parse_address(args.listen)
    target_host, target_port = parse_address(args.target)
    forwarder = Forwarder(listen_host, listen_port, target_host, target_port).start()
    print("forwarding %s:%d -> %s:%d  (Ctrl-C to stop)" % (*forwarder.address, target_host, target_port),
          flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        forwarder.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
