#!/usr/bin/env python3
# MODULE: tests (carbon adapter contracts)
"""Exercises the Destiny and CarbonIO adapters against stand-in modules that mirror
the real Carbon API surface (signatures taken from carbonengine/destiny
Ballpark_Blue.cpp + its tests, and carbonengine/io's module names).

This proves the adapter wiring without a Carbon build. On a machine where
`import destiny` / `import _carbonsocket` work, run the phase tests with
--nav destiny / --transport carbonio for the real thing.
"""
import os
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))


class FakeBall:
    def __init__(self, x, y, z, max_vel):
        self.x, self.y, self.z, self.maxVelocity = x, y, z, max_vel
        self.goto = None


class FakeBallpark:
    """Mirrors destiny.Ballpark: AddBall takes exactly 17 positional args."""
    tickInterval = 100  # ms

    def __init__(self):
        self.balls, self.calls = {}, []

    def Start(self):
        self.calls.append("Start")

    def AddBall(self, ball_id, mass, radius, max_velocity, is_free, is_global, is_massive, is_interactive,
                is_space_junk, x, y, z, vx, vy, vz, agility, speed_fraction):
        assert isinstance(is_free, bool) and isinstance(is_space_junk, bool)
        self.balls[ball_id] = FakeBall(x, y, z, max_velocity)
        return self.balls[ball_id]

    def GotoPoint(self, ball_id, x, y, z):
        self.balls[ball_id].goto = (x, y, z)

    def Stop(self, ball_id):
        self.balls[ball_id].goto = None
        self.calls.append(("Stop", ball_id))

    def RemoveBall(self, ball_id):
        del self.balls[ball_id]

    def Evolve(self):
        dt = self.tickInterval / 1000.0
        for b in self.balls.values():
            if b.goto:
                d = [g - c for g, c in zip(b.goto, (b.x, b.y, b.z))]
                n = sum(v * v for v in d) ** 0.5
                s = min(1.0, b.maxVelocity * dt / n) if n else 0.0
                b.x, b.y, b.z = (b.x + d[0] * s, b.y + d[1] * s, b.z + d[2] * s)


def test_destiny_adapter():
    sys.modules["destiny"] = types.SimpleNamespace(Ballpark=FakeBallpark)
    from cmmo.mathbridge import Vector3
    from cmmo.nav import DestinyNavAdapter, create_nav, destiny_available

    nav = create_nav("destiny")
    assert isinstance(nav, DestinyNavAdapter) and "Start" in nav.park.calls
    nav.add_agent(7, Vector3(0, 0, 0), max_speed=10.0)
    assert nav.request_move(7, Vector3(3, 0, 4))
    for _ in range(20):
        nav.step(0.05)  # 1 s of real time -> 10 Destiny ticks of 100 ms
    p = nav.position(7)
    assert p.distance(Vector3(3, 0, 4)) < 0.5, p
    assert not nav.is_moving(7) and ("Stop", 7) in nav.park.calls
    nav.remove_agent(7)
    assert 7 not in nav.park.balls
    del sys.modules["destiny"]
    print("  [PASS] Destiny adapter: AddBall(17 args) / GotoPoint / Evolve per tick / Stop / RemoveBall")


def test_carbonio_injection():
    # Child process: alias the stdlib C modules under CarbonIO's names, then run the
    # full phase 2 test through the "carbonio" transport (exercises install_carbonio()).
    code = (
        "import sys, runpy, _socket, select\n"
        "sys.modules['_carbonsocket'] = _socket\n"
        "sys.modules['carbonselect'] = select\n"
        "sys.argv = ['t', '--transport', 'carbonio']\n"
        f"runpy.run_path({os.path.join(ROOT, 'tests', 'test_phase2_net.py')!r}, run_name='__main__')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=40)
    ok = r.returncode == 0 and "transport=carbonio" in r.stdout and "PHASE2 OK" in r.stdout
    if not ok:
        print(r.stdout[-2000:], r.stderr[-2000:])
    assert ok
    print("  [PASS] CarbonIO transport: module injection + full phase 2 flow over it")


if __name__ == "__main__":
    test_destiny_adapter()
    test_carbonio_injection()
    print("CONTRACTS OK")
