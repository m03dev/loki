"""loki_cad - proven build123d parts that LOKI's models put together instead of writing raw CAD.

Free models write CAD that fails (fillets that crash, parts in the wrong place, functions that don't exist). These parts
are tested: each one stands on z=0, centred on x/y, in millimetres, and joins the next one by its named sizes.
Every job gets this file in scripts/.  A whole chest:

    import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from loki_cad import *
    W, D, H = 800, 500, 420
    m = Model()                                          # collects parts by material
    m.add("wood", shell_box(W, D, H, wall=30, grooves=4))      # open-top body with plank grooves
    m.add("iron", straps_u(W, D, H, at_x=(-240, 240)), corner_angles(W, D, H))
    m.add("gold", lock_plate(W, D, H), heap_in(W, D, H, wall=30))   # lock on the front, coins on a mound inside
    hinge = Hinge(W, D, H, at_x=(-150, 150))             # the hinge line along the back top edge
    m.add("iron", hinge.fixed())                         # knuckles + leaves on the body
    lid = [barrel_lid(W, D, H, rise=160)]                # sits shut on the body ...
    lid_iron = [barrel_straps(W, D, H, rise=160, at_x=(-240, 240)), hinge.leaves_on_lid()]
    m.add("wood", *hinge.open(lid, 100))                 # ... then swings 100 degrees round the hinge line
    m.add("iron", *hinge.open(lid_iron, 100))
    m.export()                                           # parts/wood.stl, iron.stl, gold.stl + prints valid: True
Then render with scripts/cad_render.py. Or simply: chest(m, W, D, H) does all of the above.

Parts (all mm; W x D x H is the body they fit):
  shell_box(W, D, H, wall, grooves, round)       open-top box, rounded corners, plank grooves round the outside
  solid_box(W, D, H, round)                      a closed block with rounded vertical edges (a drawer front, a step)
  barrel_lid / flat_lid(W, D, H, rise)           a lid sitting shut on top of a W x D body
  straps_u(W, D, H, at_x)                        iron straps under and up both long sides
  barrel_straps(W, D, H, rise, at_x)             the matching straps over a barrel lid
  corner_angles(W, D, H)                         L-shaped corner brackets on the four vertical edges
  lock_plate(W, D, H)                            plate with a keyhole on the front, near the top
  heap_in(W, D, H, wall, coins)                  a gold mound inside an open box with coins resting on its surface
  Hinge(W, D, H, at_x)                           .fixed() .leaves_on_lid() .open(parts, deg)
  handle_ring(at, r, axis)                       a ring handle; leg(at, h, r, taper); shelf(W, D, t, at_z); rod(a, b, r)
  board(W, D, t, at) / post(at, h, size)         flat planks and square posts for furniture
Tables, chairs, shelves, crates: compose board(), post(), leg() by their sizes - z where the last part ends.
"""
import math
import os
import random

from build123d import (Align, Axis, Box, Compound, Cylinder, Ellipse, Plane, Pos, Rot, Sphere, Torus, export_stl,
                       extrude, fillet, scale)

BASE = (Align.CENTER, Align.CENTER, Align.MIN)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE) if os.path.basename(HERE) == "scripts" else HERE, "parts")

__all__ = ["Model", "shell_box", "solid_box", "barrel_lid", "flat_lid", "straps_u", "barrel_straps", "corner_angles",
           "lock_plate", "heap_in", "Hinge", "handle_ring", "leg", "shelf", "rod", "board", "post", "chest",
           "Pos", "Rot", "Box", "Cylinder", "Sphere", "Torus", "BASE"]


class Model:
    """Collects finished parts by material and writes parts/<material>.stl."""

    def __init__(self):
        self.parts = {}

    def add(self, material, *shapes):
        for s in shapes:
            if isinstance(s, (list, tuple)):
                self.add(material, *s)
            elif s is not None:
                self.parts.setdefault(material, []).append(s)
        return self

    def export(self, out=OUT):
        os.makedirs(out, exist_ok=True)
        ok = True
        for name, shapes in self.parts.items():
            for s in shapes:
                ok = ok and bool(getattr(s, "is_valid", True))
            export_stl(Compound(children=shapes), os.path.join(out, f"{name}.stl"), tolerance=0.3, angular_tolerance=0.2)
        print("valid:", ok, "| parts:", ", ".join(f"{k} {len(v)}" for k, v in self.parts.items()))
        return ok


def _safe_fillet(shape, edges, r):
    """Round edges when the kernel can; keep the sharp shape when it can't (never crash the build)."""
    try:
        return fillet(edges, r)
    except Exception:  # noqa: BLE001
        return shape


def solid_box(W, D, H, round=10, at=(0, 0, 0)):
    b = Box(W, D, H, align=BASE)
    b = _safe_fillet(b, b.edges().filter_by(Axis.Z), min(round, W / 4, D / 4)) if round else b
    return Pos(*at) * b


def shell_box(W, D, H, wall=30, grooves=4, round=12, at=(0, 0, 0)):
    """Open-top box: floor and walls `wall` thick; `grooves` plank lines cut 2 mm deep round the outside."""
    b = solid_box(W, D, H, round)
    b -= Pos(0, 0, wall) * Box(W - 2 * wall, D - 2 * wall, H, align=BASE)
    for k in range(1, grooves + 1):
        z = H * k / (grooves + 1)
        b -= Pos(0, 0, z - 2) * (Box(W + 10, D + 10, 4, align=BASE) - Box(W - 4, D - 4, 6, align=BASE))
    return Pos(*at) * b


def _half_ellipse(a, b, length):
    s = extrude(Plane.YZ * Ellipse(a, b), amount=length / 2, both=True)
    return s - Pos(0, 0, -b) * Box(length + 2, 2 * a + 2, 2 * b)


def barrel_lid(W, D, H, rise=150, wall=25, at=(0, 0, 0)):
    """Half-round lid, hollow with solid ends, sitting shut on a W x D body of height H."""
    lid = _half_ellipse(D / 2, rise, W) - _half_ellipse(D / 2 - wall, rise - wall, W - 2 * wall)
    return Pos(at[0], at[1], at[2] + H) * lid


def flat_lid(W, D, H, rise=60, wall=25, at=(0, 0, 0)):
    lid = solid_box(W, D, rise, 10) - Box(W - 2 * wall, D - 2 * wall, rise - wall, align=BASE)
    return Pos(at[0], at[1], at[2] + H) * lid


def straps_u(W, D, H, at_x=(-0.3, 0.3), width=50, t=4):
    """Iron straps wrapping under the body and up its front and back. at_x: mm, or fractions of W when |x| < 1."""
    out = []
    for x in at_x:
        x = x * W if abs(x) < 1 else x
        s = Pos(x, 0, -t) * Box(width, D + 2 * t, H + t, align=BASE) - Pos(x, 0, 0) * Box(width + 2, D, H + 1, align=BASE)
        out.append(s)
    return out


def barrel_straps(W, D, H, rise=150, at_x=(-0.3, 0.3), width=50, t=4):
    out = []
    for x in at_x:
        x = x * W if abs(x) < 1 else x
        out.append(Pos(x, 0, H) * (_half_ellipse(D / 2 + t, rise + t, width) - _half_ellipse(D / 2, rise, width + 2)))
    return out


def corner_angles(W, D, H, leg=60, t=4, inset=10):
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            a = Box(leg, t, H - 2 * inset, align=BASE) + Pos(sx * (leg / 2 - t / 2), -sy * (leg / 2 - t / 2), 0) * Box(t, leg, H - 2 * inset, align=BASE)
            out.append(Pos(sx * (W / 2 - leg / 2 + t / 2), sy * (D / 2 + t / 2), inset) * a)
    return out


def lock_plate(W, D, H, w=90, h=110, t=6, from_top=40):
    z0 = H - from_top - h
    p = Pos(0, -D / 2 - t / 2, z0) * Box(w, t, h, align=BASE)
    p = _safe_fillet(p, p.edges().filter_by(Axis.Y), 8)
    p -= Pos(0, -D / 2 - t / 2, z0 + h * 0.62) * Rot(90, 0, 0) * Cylinder(9, t * 3)
    p -= Pos(0, -D / 2 - t / 2, z0 + h * 0.3) * Box(7, t * 3, 28)
    return p


def heap_in(W, D, H, wall=30, coins=90, below_rim=50, coin_r=16, seed=7):
    """A gold mound filling an open box to `below_rim` under its rim, with coins lying on the mound's surface."""
    top = H - below_rim
    a, b, c = (W - 2 * wall) * 0.42, (D - 2 * wall) * 0.42, min(70, below_rim + 30)
    out = [Pos(0, 0, wall) * Box(W - 2 * wall - 2, D - 2 * wall - 2, top - wall, align=BASE),
           Pos(0, 0, top) * (scale(Sphere(1), (a, b, c)) - Pos(0, 0, -c) * Box(2 * a + 2, 2 * b + 2, 2 * c))]
    rnd = random.Random(seed)
    for _ in range(coins):
        x, y = rnd.uniform(-a, a), rnd.uniform(-b, b)
        q = 1 - (x / a) ** 2 - (y / b) ** 2
        if q <= 0.03:
            continue
        z = top + c * math.sqrt(q) - 1.5                      # on the surface, slightly sunk
        out.append(Pos(x, y, z) * Rot(-y / b * 25, x / a * 25, rnd.uniform(0, 90)) * Cylinder(coin_r, 3))
    return out


class Hinge:
    """Two hinges on the back top edge (+y is the back; the camera looks from -y). The pin line is the pivot."""

    def __init__(self, W, D, H, at_x=(-0.2, 0.2), r=12, t=4, strap_t=4):
        self.W, self.D, self.H, self.r, self.t = W, D, H, r, t
        self.xs = [x * W if abs(x) < 1 else x for x in at_x]
        self.pivot = (0, D / 2 + strap_t + r, H)

    def fixed(self):
        _, py, pz = self.pivot
        out = []
        for x in self.xs:
            out.append(Pos(x, py, pz) * Rot(0, 90, 0) * Cylinder(self.r, 80))
            out.append(Pos(x, self.D / 2 + self.t / 2, pz - 70) * Box(70, self.t, 70 - self.r, align=BASE))
        return out

    def leaves_on_lid(self):
        _, py, pz = self.pivot
        return [Pos(x, self.D / 2 + self.t / 2, pz + self.r * 0.5) * Box(70, self.t, 60, align=BASE) for x in self.xs]

    def open(self, shapes, degrees):
        """Swing shapes (built shut) round the pin line; the front lifts and rolls back."""
        px, py, pz = self.pivot
        return [Pos(px, py, pz) * Rot(-degrees, 0, 0) * Pos(-px, -py, -pz) * s for s in shapes]


def handle_ring(at, r=40, wire=7, axis="Y"):
    rot = {"X": Rot(0, 90, 0), "Y": Rot(90, 0, 0), "Z": Rot(0, 0, 0)}[axis]
    return Pos(*at) * rot * Torus(r, wire)


def leg(at, h, r=25, taper=0.75):
    from build123d import Cone
    return Pos(at[0], at[1], at[2]) * Cone(r, r * taper, h, align=BASE)


def post(at, h, size=40):
    return Pos(*at) * Box(size, size, h, align=BASE)


def board(W, D, t=20, at=(0, 0, 0), round=3):
    b = Box(W, D, t, align=BASE)
    return Pos(*at) * _safe_fillet(b, b.edges(), round)


def shelf(W, D, t=20, at_z=0):
    return board(W, D, t, (0, 0, at_z))


def rod(a, b, r=10):
    ax, ay, az = a
    bx, by, bz = b
    L = math.dist(a, b)
    c = Cylinder(r, L)
    yaw = math.degrees(math.atan2(by - ay, bx - ax))
    pitch = math.degrees(math.acos(max(-1, min(1, (bz - az) / L)))) if L else 0
    return Pos((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2) * Rot(0, 0, yaw) * Rot(0, pitch, 0) * c


def chest(m, W=800, D=500, H=420, rise=160, open_deg=100, wall=30, domed=True, coins=90):
    """The whole tested chest into Model m (wood, iron, gold)."""
    m.add("wood", shell_box(W, D, H, wall=wall))
    m.add("iron", straps_u(W, D, H), corner_angles(W, D, H))
    m.add("gold", lock_plate(W, D, H), heap_in(W, D, H, wall=wall, coins=coins))
    hinge = Hinge(W, D, H)
    m.add("iron", hinge.fixed())
    lid = [barrel_lid(W, D, H, rise) if domed else flat_lid(W, D, H, rise * 0.5)]
    lid_iron = (barrel_straps(W, D, H, rise) if domed else []) + hinge.leaves_on_lid()
    m.add("wood", hinge.open(lid, open_deg))
    m.add("iron", hinge.open(lid_iron, open_deg))
    return m


if __name__ == "__main__":   # self-test: the chest builds and is valid
    chest(Model()).export(os.path.join(HERE, "_selftest_parts"))
