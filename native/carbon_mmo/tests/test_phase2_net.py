#!/usr/bin/env python3
# MODULE: tests (phase 2)
"""Phase 2: local server + 3 clients synchronising a player position vector.

    python tests/test_phase2_net.py                  # binary codec, std transport
    python tests/test_phase2_net.py --codec json     # same test, other codec
    python tests/test_phase2_net.py --transport carbonio   # inside a Carbon Python build

Checks: handshake, heartbeat RTT + clock sync (server clock deliberately offset by
1000 s), every client mirrors every player's Carbon Vector3, updates propagate,
and a disconnect is broadcast. Hard time limit: 30 s.
"""
import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

from cmmo.mathbridge import BACKEND, Vector3  # noqa: E402
from cmmo.net import CORE_PROTOCOL, SyncClient, SyncServer, Vec3, create_transport  # noqa: E402

# --- the only "game" bit: a test-local message. The net layer never knew it existed.
PROTO = CORE_PROTOCOL.extend()


@PROTO.message(100)
@dataclass
class PlayerPosition:
    position: Vec3


SERVER_CLOCK_OFFSET = 1000.0
TIME_LIMIT = 30.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codec", default="binary", choices=["binary", "json"])
    ap.add_argument("--transport", default="std")
    ap.add_argument("--clients", type=int, default=3)
    args = ap.parse_args()
    started = time.monotonic()
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
        return ok

    # ---------------- server (own thread, own transport) ----------------
    server = SyncServer(PROTO, codec=args.codec, transport=create_transport(args.transport),
                        clock=lambda: time.monotonic() + SERVER_CLOCK_OFFSET, timeout=5.0,
                        info="phase2-test")
    host, port = server.start("127.0.0.1", 0)
    server.on(PlayerPosition, lambda peer, msg: server.set_state(peer.id, "position", msg.position.pack()))
    server.on_leave = lambda peer, reason: server.remove_entity(peer.id)
    stop = threading.Event()
    thread = threading.Thread(target=server.serve, args=(stop,), daemon=True)
    thread.start()
    print(f"server on {host}:{port}  transport={server.transport.name} codec={args.codec} math={BACKEND}")

    clients = []
    try:
        # ---------------- connect N clients ----------------
        for i in range(args.clients):
            c = SyncClient(PROTO, codec=args.codec, transport=create_transport(args.transport),
                           name=f"player{i + 1}", ping_interval=0.05)
            c.connect(host, port)
            clients.append(c)
        ok = all(c.wait_until(lambda c=c: c.connected, 5.0) for c in clients)
        check(f"{args.clients} clients completed handshake", ok,
              "ids " + ", ".join(str(c.client_id) for c in clients))

        # ---------------- each client publishes its position ----------------
        sent = {}
        for i, c in enumerate(clients):
            pos = Vector3(10.0 * (i + 1), 0.5, -3.25 * i)
            sent[c.client_id] = pos
            c.send(PlayerPosition(pos))

        def mirrors_all(c):
            return all(eid in c.state and "position" in c.state[eid] and
                       Vector3.unpack(c.state[eid]["position"]) == pos for eid, pos in sent.items())

        ok = all(c.wait_until(lambda c=c: mirrors_all(c), 5.0) for c in clients)
        check("every client mirrors every player's position", ok)
        sample = clients[0].state
        for eid in sorted(sent):
            print(f"      client1 sees player {eid}: {Vector3.unpack(sample[eid]['position'])}")

        # ---------------- heartbeat / time sync ----------------
        for c in clients:
            c.wait_until(lambda c=c: c.heartbeat.synced, 3.0)
        errs = [abs(c.server_time() - (time.monotonic() + SERVER_CLOCK_OFFSET)) for c in clients]
        rtts = [c.heartbeat.rtt or 0.0 for c in clients]
        check("heartbeat measured RTT on all clients", all(c.heartbeat.synced for c in clients),
              "rtt " + ", ".join(f"{r * 1000:.2f}ms" for r in rtts))
        check("server clock estimate within 50 ms", max(errs) < 0.05,
              f"worst error {max(errs) * 1000:.2f} ms (server clock offset {SERVER_CLOCK_OFFSET:.0f} s)")

        # ---------------- live update propagates ----------------
        mover = clients[1]
        new_pos = sent[mover.client_id].move_towards(Vector3(0.0, 0.0, 0.0), 5.0)  # Carbon math on the client
        sent[mover.client_id] = new_pos
        mover.send(PlayerPosition(new_pos))
        ok = all(c.wait_until(lambda c=c: mirrors_all(c), 5.0) for c in clients)
        check("position update reaches all clients", ok, f"player {mover.client_id} -> {new_pos}")

        # ---------------- disconnect is broadcast ----------------
        leaver = clients.pop()
        gone = leaver.client_id
        leaver.close()
        ok = all(c.wait_until(lambda c=c: gone not in c.state, 5.0) for c in clients)
        check("disconnect removes the player everywhere", ok, f"player {gone}")
    finally:
        for c in clients:
            c.close()
        stop.set()
        thread.join(2.0)
        server.stop()

    elapsed = time.monotonic() - started
    check(f"finished under {TIME_LIMIT:.0f} s", elapsed < TIME_LIMIT, f"{elapsed:.2f} s")
    passed = all(checks)
    print("PHASE2 OK" if passed else "PHASE2 FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
