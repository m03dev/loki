#!/usr/bin/env python3
# MODULE: tests (phase 3)
"""Phase 3: click-to-move. A client clicks, the server moves the entity through the
NavAdapter (Destiny when importable, else kinematic), and every client receives the
position stream.

    python tests/test_phase3_click_to_move.py [--nav auto|destiny|kinematic]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

from cmmo.mathbridge import BACKEND, Vector3  # noqa: E402
from cmmo.nav import create_nav  # noqa: E402
from cmmo_game.click_to_move import ClickToMoveClient, ClickToMoveServer  # noqa: E402

TIME_LIMIT = 30.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nav", default="auto")
    ap.add_argument("--codec", default="binary")
    args = ap.parse_args()
    started = time.monotonic()
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")

    server = ClickToMoveServer(nav=create_nav(args.nav), codec=args.codec, speed=20.0)
    host, port = server.start()
    print(f"server {host}:{port}  nav={server.nav.name}  math={BACKEND}")
    clients = [ClickToMoveClient(f"player{i + 1}", codec=args.codec) for i in range(3)]
    try:
        check("3 clients connected", all(c.connect(host, port) for c in clients))
        ids = [c.net.client_id for c in clients]
        ok = all(c.net.wait_until(lambda c=c: len(c.positions()) == 3, 5.0) for c in clients)
        check("every client sees 3 spawned players", ok)
        start = {eid: p for eid, p in clients[0].positions().items()}

        mover, me = clients[0], ids[0]
        target = Vector3(25.0, 0.0, 10.0)
        mover.click(target)
        print(f"      player {me} clicks {target} from {start[me]}")

        arrived = lambda c: me in c.positions() and c.positions()[me].distance(target) < 0.1  # noqa: E731
        ok = all(c.net.wait_until(lambda c=c: arrived(c), 10.0) for c in clients)
        check("all clients see the mover arrive at the target", ok,
              ", ".join(f"{c.net.name}: {c.positions().get(me)}" for c in clients))

        trail = clients[2].history.get(me, [])  # an observer, not the clicker
        dists = [p.distance(target) for p in trail]
        steps = [a - b for a, b in zip(dists, dists[1:])]
        check("observer received a stream of intermediate positions", len(trail) >= 10, f"{len(trail)} updates")
        check("path is monotonic toward the target", all(s >= -1e-3 for s in steps))
        speed_ok = max(steps or [0]) <= 20.0 * server.tick * 3 + 1e-3  # no teleport (allow tick jitter)
        check("no teleporting (per-update step bounded by speed)", speed_ok, f"max step {max(steps or [0]):.3f} m")

        still = all(clients[1].positions()[eid] == start[eid] for eid in ids[1:])
        check("players who didn't click stayed put", still)

        far = Vector3(5000.0, 0.0, 0.0)
        mover.click(far)
        ok = mover.net.wait_until(lambda: len(mover.rejected) > 0, 3.0)
        check("server rejects out-of-bounds clicks", ok)

        agree = len({c.positions()[me].to_tuple() for c in clients}) == 1
        check("all clients agree on the final position", agree)
    finally:
        for c in clients:
            c.net.close()
        server.stop()

    elapsed = time.monotonic() - started
    check(f"finished under {TIME_LIMIT:.0f} s", elapsed < TIME_LIMIT, f"{elapsed:.2f} s")
    passed = all(checks)
    print("PHASE3 OK" if passed else "PHASE3 FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
