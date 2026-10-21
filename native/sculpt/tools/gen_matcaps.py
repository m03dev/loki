"""Generate the Sculpting matcap set (original, procedural - no third-party
images). A matcap is a lit sphere seen head-on: the viewport looks up the
pixel at (n.x, n.y) of the view-space normal. Writes matcaps/<name>.png
(256x256 RGB, background = edge colour so bilinear lookups never bleed)."""
import json
import math
import os
import sys

import numpy as np
from PIL import Image

N = 256
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "app", "ui", "vendor", "sculpt", "matcaps")


def norm(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def sphere():
    y, x = np.mgrid[0:N, 0:N]
    nx = (x + 0.5) / N * 2 - 1
    ny = 1 - (y + 0.5) / N * 2
    r2 = nx * nx + ny * ny
    inside = r2 <= 1.0
    k = np.clip(r2, 0, 0.9999)
    nz = np.sqrt(1 - k)
    # outside the disc: continue the rim (clamped normal) so lookups at the edge are clean
    s = np.where(inside, 1.0, 1.0 / np.sqrt(np.maximum(r2, 1e-9)))
    n = np.stack([nx * s, ny * s, np.where(inside, nz, 0.0)], -1)
    return n


def shade(p):
    n = sphere()
    base = np.asarray(p["base"], float)
    col = np.zeros((N, N, 3)) + np.asarray(p.get("ambient", [0.08] * 3))
    V = np.array([0, 0, 1.0])
    for L, c, wrap in p["lights"]:
        L = norm(L)
        d = (n @ L + wrap) / (1 + wrap)
        col += np.clip(d, 0, 1)[..., None] * np.asarray(c) * base
        if p.get("spec", 0) > 0:
            H = norm(L + V)
            sp = np.clip(n @ H, 0, 1) ** p["shine"]
            col += sp[..., None] * p["spec"] * np.asarray(p.get("specColor", c))
    if p.get("rim", 0) > 0:
        f = (1 - np.clip(n[..., 2], 0, 1)) ** p.get("rimPower", 3)
        col += f[..., None] * p["rim"] * np.asarray(p.get("rimColor", [1, 1, 1]))
    if p.get("bands", 0) > 0:  # chrome: a fake horizon environment
        ry = n[..., 1]
        env = 0.5 + 0.5 * np.tanh(ry * 8) * 0.9 - 0.25 * np.exp(-((ry + 0.05) * 9) ** 2)
        col = col * (1 - p["bands"]) + env[..., None] * p["bands"] * np.asarray(p.get("envColor", [1, 1, 1]))
    if p.get("sss", 0) > 0:  # soft subsurface-ish glow at grazing light
        g = np.clip(n @ norm([-0.3, 0.6, 0.5]) * 0.5 + 0.5, 0, 1) ** 2
        col += g[..., None] * p["sss"] * np.asarray(p.get("sssColor", [0.9, 0.3, 0.2]))
    col = np.clip(col, 0, 1) ** (1 / p.get("gamma", 1.0))
    return (col * 255 + 0.5).astype(np.uint8)


KEY = [-0.45, 0.55, 0.7]
FILL = [0.7, -0.15, 0.5]
BACK = [0.1, 0.9, -0.4]
SETS = {
    "Clay Gray":      dict(base=[0.66, 0.64, 0.62], lights=[(KEY, [1, 1, 1], 0.15), (FILL, [0.35, 0.37, 0.4], 0.3)], spec=0.05, shine=12, rim=0.12),
    "Red Wax":        dict(base=[0.78, 0.32, 0.24], lights=[(KEY, [1, 0.95, 0.9], 0.35), (FILL, [0.3, 0.25, 0.3], 0.4)], spec=0.18, shine=30, rim=0.10, rimColor=[1, 0.6, 0.5], sss=0.12),
    "Toy Plastic":    dict(base=[0.85, 0.2, 0.15], lights=[(KEY, [1, 1, 1], 0.1), (FILL, [0.35, 0.35, 0.45], 0.2)], spec=0.9, shine=80, specColor=[1, 1, 1], rim=0.08),
    "Chrome":         dict(base=[0.5, 0.52, 0.55], lights=[(KEY, [0.6, 0.6, 0.6], 0.0)], spec=1.0, shine=120, bands=0.75, envColor=[0.95, 0.97, 1.0], rim=0.2),
    "Skin":           dict(base=[0.86, 0.62, 0.52], lights=[(KEY, [1, 0.97, 0.92], 0.45), (FILL, [0.4, 0.35, 0.4], 0.5)], spec=0.12, shine=18, sss=0.18, rim=0.12, rimColor=[1, 0.8, 0.7]),
    "High Contrast":  dict(base=[0.8, 0.8, 0.82], lights=[(KEY, [1.1, 1.1, 1.1], -0.1)], ambient=[0.02] * 3, spec=0.25, shine=40, rim=0.35, rimPower=4),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    names = []
    for name, p in SETS.items():
        img = shade(p)
        fn = name.lower().replace(" ", "_") + ".png"
        Image.fromarray(img, "RGB").save(os.path.join(OUT, fn))
        # gallery thumbnail: the sphere on a dark round-masked tile
        t = Image.fromarray(img, "RGB").resize((72, 72), Image.LANCZOS)
        y, x = np.mgrid[0:72, 0:72]
        disc = ((x - 35.5) ** 2 + (y - 35.5) ** 2) <= 35.5 ** 2
        a = np.asarray(t).copy()
        a[~disc] = (43, 43, 46)
        Image.fromarray(a, "RGB").save(os.path.join(OUT, fn.replace(".png", "_thumb.png")))
        names.append({"name": name, "file": fn, "thumb": fn.replace(".png", "_thumb.png")})
    with open(os.path.join(OUT, "matcaps.json"), "w") as f:
        json.dump(names, f, indent=1)
    print("wrote", len(names), "matcaps to", OUT)


if __name__ == "__main__":
    main()
