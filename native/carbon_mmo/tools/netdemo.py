#!/usr/bin/env python3
# MODULE: tools
"""Run the click-to-move server and clients as separate processes / machines.

    python tools/netdemo.py server --host 0.0.0.0 --port 7777
    python tools/netdemo.py client --host <server-ip> --port 7777 --name mac --click 25,0,10

The client prints the positions it receives for ~5 s and exits.
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

from cmmo.mathbridge import BACKEND, Vector3  # noqa: E402
from cmmo_game.click_to_move import ClickToMoveClient, ClickToMoveServer  # noqa: E402


def run_server(a):
    server = ClickToMoveServer()
    host, port = server.start(a.host, a.port)
    server.net.on_join = (lambda join: lambda p: (join(p), print(f"+ {p.name} joined as {p.id}")))(server.net.on_join)
    print(f"serving on {host}:{port} nav={server.nav.name} math={BACKEND} - Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def run_client(a):
    c = ClickToMoveClient(a.name)
    if not c.connect(a.host, a.port):
        print("could not connect")
        return 1
    print(f"connected as {c.net.client_id}: {c.net.server_info}")
    if a.click:
        c.click(Vector3(*(float(v) for v in a.click.split(","))))
    end = time.monotonic() + a.seconds
    while time.monotonic() < end:
        c.net.poll(0.2)
        print("  " + "  ".join(f"{eid}:{p}" for eid, p in sorted(c.positions().items())))
    c.net.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["server", "client"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--name", default="player")
    ap.add_argument("--click", default="")
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()
    sys.exit(run_server(args) if args.mode == "server" else run_client(args))
