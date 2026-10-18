"""Forge: a picture, a drawing or a sentence -> a 3D model (.glb + .obj) in the workspace's models/.

    make_3d(source, out_dir, prompt="", backend="auto") -> {"ok", "glb", "obj", "backend", "meta", ...}

`source` is an image path, a `data:image/...;base64,` URL (a drawing from the window's canvas), or
empty with a `prompt` (text -> image through LOKI's image specialist first, engine/runners/imagegen.py).

Pipeline: load the image -> cut the subject out (rembg when installed, else a border-colour cut-out:
the background is the colour around the edge, flood-filled in from the border) -> image-to-3D ->
<out_dir>/<stamp>-<slug>.glb and .obj + a sidecar <out_dir>/.meta/<file>.json (prompt, source,
backend, time), the same sidecar idea as images/ (engine/creations.py).

Backends, best first ("auto"):
  triposr  TripoSR (github.com/VAST-AI-Research/TripoSR, MIT; weights stabilityai/TripoSR, MIT) on
           this computer: CUDA (about 6 GB - the PC's RTX 3070 Ti), Apple MPS, or CPU slowly.
           Installed by `python tools/setup_forge3d.py` into harness_data/tools/TripoSR + LOKI's venv;
           runs in its own process (engine/runners/triposr.py), never imported here.
  online   a free Hugging Face Space through gradio_client (default TRELLIS, MIT; LOKI_FORGE_SPACE
           picks another). The picture goes to a third party - off when LOKI_LOCAL_ONLY=1.
  lift     always works, offline, pure Python: the cut-out silhouette is inflated into a rounded
           closed mesh (distance field -> round profile, front and back meeting at the outline,
           outline smoothed), vertex colours sampled from the picture. Written by write_glb below.

No model with a non-commercial or region-restricted licence is used (no Hunyuan3D, no Stable Fast 3D).
Standard library + Pillow (engine/requirements.txt). Jobs run in a thread; start_job()/job() for the API.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNERS = Path(__file__).resolve().parent / "runners"
BACKENDS = ("auto", "triposr", "online", "lift")
MODEL_EXTS = (".glb", ".obj")
META_DIR = ".meta"
DEFAULT_SPACE = "trellis-community/TRELLIS"
MAX_IMAGE_BYTES = 25_000_000
LIFT_GRID = 112          # cells along the longer side of the lift's silhouette


class ForgeError(Exception):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (ROOT / "harness_data"))


# ----------------------------------------------------------------------------- what is available
def triposr_dir() -> Path:
    return Path(os.environ.get("LOKI_TRIPOSR_DIR") or (data_dir() / "tools" / "TripoSR"))


def triposr_ready() -> bool:
    """TripoSR's code is unpacked and torch is installed (nothing is imported)."""
    return (triposr_dir() / "tsr" / "system.py").is_file() and importlib.util.find_spec("torch") is not None


def online_ready() -> bool:
    if os.environ.get("LOKI_LOCAL_ONLY", "0") == "1" or os.environ.get("LOKI_FORGE_ONLINE", "1") == "0":
        return False
    return importlib.util.find_spec("gradio_client") is not None


def status() -> dict:
    return {"triposr": triposr_ready(), "online": online_ready(), "lift": True,
            "rembg": importlib.util.find_spec("rembg") is not None,
            "space": os.environ.get("LOKI_FORGE_SPACE", DEFAULT_SPACE),
            "setup": "python tools/setup_forge3d.py"}


def plan(backend: str = "auto") -> list:
    """Backends to try, in order. A named backend is tried first; the lift always ends the list."""
    backend = (backend or "auto").lower()
    if backend not in BACKENDS:
        raise ForgeError("unknown backend %r (%s)" % (backend, ", ".join(BACKENDS)))
    if backend == "auto":
        order = [b for b, ok in (("triposr", triposr_ready()), ("online", online_ready())) if ok]
    else:
        order = [backend] if backend != "lift" else []
    return order + ["lift"]


# ----------------------------------------------------------------------------- the picture
def _pil():
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
        return Image
    except ImportError:
        raise ForgeError("Pillow is not installed (it is in engine/requirements.txt)") from None


def load_image(source):
    """A path, bytes, or a data: URL -> an RGBA PIL image."""
    Image = _pil()
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif isinstance(source, str) and source.startswith("data:"):
        head, _, body = source.partition(",")
        if not head.startswith("data:image/") or ";base64" not in head:
            raise ForgeError("a drawing must be a base64 data:image URL")
        try:
            raw = base64.b64decode(body, validate=False)
        except ValueError:
            raise ForgeError("the drawing's data is not valid base64") from None
    else:
        p = Path(str(source))
        if not p.is_file():
            raise ForgeError("no such picture: %s" % source)
        raw = p.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ForgeError("the picture is too big (max 25 MB)")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001 - any decoder error
        raise ForgeError("not a picture LOKI can read: %s" % exc) from None
    return img.convert("RGBA")


def _rembg_cutout(img):
    try:
        import rembg  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    try:
        return rembg.remove(img).convert("RGBA")
    except Exception:  # noqa: BLE001 - fall back to the border-colour cut-out
        return None


def silhouette(img, grid: int = LIFT_GRID) -> tuple:
    """(mask, rgb, w, h): the subject on a small grid. mask[y][x] is True on the subject.
    Uses the alpha channel when the picture has a transparent background; else the colour
    around the border is the background, flood-filled in from the edge (so a white eye inside
    a white-background drawing stays part of the subject)."""
    Image = _pil()
    scale = grid / max(img.width, img.height)
    w, h = max(4, round(img.width * scale)), max(4, round(img.height * scale))
    small = img.resize((w, h), Image.LANCZOS)
    px = list(small.getdata())
    alpha = [p[3] for p in px]
    border = [i for i in range(w * h) if i % w in (0, w - 1) or i // w in (0, h - 1)]
    if min(alpha[i] for i in border) < 200 and max(alpha) > 127:
        mask = [a > 127 for a in alpha]
    else:
        def med(c):
            vals = sorted(px[i][c] for i in border)
            return vals[len(vals) // 2]
        bg = (med(0), med(1), med(2))
        tol = 48 ** 2

        def near(i):
            p = px[i]
            return (p[0] - bg[0]) ** 2 + (p[1] - bg[1]) ** 2 + (p[2] - bg[2]) ** 2 < tol or p[3] < 40
        outside = [False] * (w * h)
        stack = [i for i in border if near(i)]
        for i in stack:
            outside[i] = True
        while stack:
            i = stack.pop()
            x, y = i % w, i // w
            for j in ((i - 1) if x > 0 else -1, (i + 1) if x < w - 1 else -1, (i - w) if y > 0 else -1,
                      (i + w) if y < h - 1 else -1):
                if j >= 0 and not outside[j] and near(j):
                    outside[j] = True
                    stack.append(j)
        mask = [not o for o in outside]
    mask = _keep_big_parts(mask, w, h)
    if not any(mask):     # nothing stood out: use the whole picture as a slab
        mask = [True] * (w * h)
    rows = [[mask[y * w + x] for x in range(w)] for y in range(h)]
    rgb = [[px[y * w + x][:3] for x in range(w)] for y in range(h)]
    return rows, rgb, w, h


def _keep_big_parts(mask: list, w: int, h: int) -> list:
    """Drop specks: keep the connected parts at least 2% the size of the biggest."""
    label = [0] * (w * h)
    sizes = [0]
    for start in range(w * h):
        if not mask[start] or label[start]:
            continue
        n = len(sizes)
        label[start] = n
        stack, size = [start], 0
        while stack:
            i = stack.pop()
            size += 1
            x, y = i % w, i // w
            for j in ((i - 1) if x > 0 else -1, (i + 1) if x < w - 1 else -1, (i - w) if y > 0 else -1,
                      (i + w) if y < h - 1 else -1):
                if j >= 0 and mask[j] and not label[j]:
                    label[j] = n
                    stack.append(j)
        sizes.append(size)
    if len(sizes) <= 2:
        return mask
    big = max(sizes)
    return [bool(label[i]) and sizes[label[i]] >= 0.02 * big for i in range(w * h)]


# ----------------------------------------------------------------------------- the lift (offline)
def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lift_mesh(mask: list, rgb: list, w: int, h: int, puff: float = 0.85, smooth: int = 5) -> dict:
    """Inflate a silhouette into a closed rounded mesh.

    Vertices sit on the corners of the grid's cells. A corner touching the outside is on the outline
    (z = 0) and is shared by the front and the back, so the surface is closed. Inside corners get a
    height from their distance to the outline with a round (circular) profile, so a disc becomes a
    ball-like lens and a long stroke a tube. The outline's staircase is smoothed in x/y (Laplacian along
    the outline, then the inside). Colours are the picture's, per corner. Returns positions (x, y, z
    floats), normals, colours (linear RGB) and triangle indices; about unit size, centred, y up."""
    W, H = w + 1, h + 1

    def inside(x, y):
        return 0 <= x < w and 0 <= y < h and mask[y][x]
    used = [[False] * W for _ in range(H)]
    edge = [[False] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            cells = [inside(x - 1, y - 1), inside(x, y - 1), inside(x - 1, y), inside(x, y)]
            used[y][x] = any(cells)
            edge[y][x] = any(cells) and not all(cells)
    # distance to the outline (chamfer 3-4, two passes), in cell units
    INF = 10 ** 9
    dist = [[0 if (edge[y][x] or not used[y][x]) else INF for x in range(W)] for y in range(H)]
    for y in range(H):
        for x in range(W):
            if dist[y][x]:
                for dx, dy, c in ((-1, 0, 3), (0, -1, 3), (-1, -1, 4), (1, -1, 4)):
                    if 0 <= x + dx < W and 0 <= y + dy < H:
                        dist[y][x] = min(dist[y][x], dist[y + dy][x + dx] + c)
    for y in range(H - 1, -1, -1):
        for x in range(W - 1, -1, -1):
            if dist[y][x]:
                for dx, dy, c in ((1, 0, 3), (0, 1, 3), (1, 1, 4), (-1, 1, 4)):
                    if 0 <= x + dx < W and 0 <= y + dy < H:
                        dist[y][x] = min(dist[y][x], dist[y + dy][x + dx] + c)
    dmax = max(max(row) for row in dist) / 3.0 or 1.0
    # front vertices for every used corner; back vertices only for inside corners
    front, back = {}, {}
    pos, col = [], []
    for y in range(H):
        for x in range(W):
            if not used[y][x]:
                continue
            cs = [rgb[yy][xx] for xx, yy in ((x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y)) if inside(xx, yy)]
            c = [sum(p[k] for p in cs) / len(cs) for k in range(3)]
            lin = [_srgb_to_linear(v) for v in c]
            d = dist[y][x] / 3.0
            t = min(1.0, d / dmax)
            z = dmax * puff * math.sqrt(max(0.0, 1.0 - (1.0 - t) ** 2))
            front[(x, y)] = len(pos)
            pos.append([float(x), float(y), z])
            col.append(lin)
            if not edge[y][x]:
                back[(x, y)] = len(pos)
                pos.append([float(x), float(y), -z])
                col.append(lin)
    # smooth the outline (x/y only) along its own neighbours, then the inside
    keys = list(front)
    for _ in range(max(0, smooth)):
        newxy = {}
        for (x, y) in keys:
            nb = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (x + dx, y + dy) in front]
            if edge[y][x]:
                nb = [k for k in nb if edge[k[1]][k[0]]]
            if len(nb) < 2:
                continue
            p = pos[front[(x, y)]]
            ax = sum(pos[front[k]][0] for k in nb) / len(nb)
            ay = sum(pos[front[k]][1] for k in nb) / len(nb)
            newxy[(x, y)] = (p[0] * 0.5 + ax * 0.5, p[1] * 0.5 + ay * 0.5)
        for k, (nx, ny) in newxy.items():
            for table in (front, back):
                if k in table:
                    pos[table[k]][0], pos[table[k]][1] = nx, ny
    # triangles: two per subject cell on the front, the same reversed on the back
    idx = []
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            a, b, c, d = (x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)
            fa, fb, fc, fd = front[a], front[b], front[c], front[d]
            ba, bb, bc, bd = (back.get(k, front[k]) for k in (a, b, c, d))
            # image y grows downward; after flipping y below, (a, c, b) faces +z. A triangle with all
            # three corners on the outline is the same on both sides (a flat fin): leave both out.
            for f3, b3, keys in (((fa, fc, fb), (ba, bb, bc), (a, b, c)), ((fb, fc, fd), (bb, bd, bc), (b, c, d))):
                if all(edge[k[1]][k[0]] for k in keys):
                    continue
                idx += [*f3, *b3]
    # centre, unit size, y up
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    s = 1.0 / max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    pos = [[(p[0] - cx) * s, -(p[1] - cy) * s, p[2] * s] for p in pos]
    return {"positions": pos, "normals": vertex_normals(pos, idx), "colors": col, "indices": idx}


def vertex_normals(pos: list, idx: list) -> list:
    acc = [[0.0, 0.0, 0.0] for _ in pos]
    for i in range(0, len(idx), 3):
        a, b, c = pos[idx[i]], pos[idx[i + 1]], pos[idx[i + 2]]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        for j in idx[i:i + 3]:
            acc[j][0] += n[0]
            acc[j][1] += n[1]
            acc[j][2] += n[2]
    out = []
    for n in acc:
        length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
        out.append([n[0] / length, n[1] / length, n[2] / length])
    return out


# ----------------------------------------------------------------------------- glTF 2.0 binary + OBJ
def write_glb(path: Path, mesh: dict, name: str = "forge") -> Path:
    """A minimal valid binary glTF 2.0: one mesh, one primitive (POSITION, NORMAL, COLOR_0 float
    VEC3 linear, uint32 indices), one material (vertex colours x white, rough, not metallic)."""
    pos, nrm, col, idx = mesh["positions"], mesh["normals"], mesh.get("colors"), mesh["indices"]
    n = len(pos)
    chunks, views, accessors = [], [], []
    offset = 0

    def add(data: bytes, target: int, count: int, ctype: int, kind: str, extra=None):
        nonlocal offset
        pad = (-len(data)) % 4
        chunks.append(data + b"\0" * pad)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        acc = {"bufferView": len(views) - 1, "componentType": ctype, "count": count, "type": kind}
        acc.update(extra or {})
        accessors.append(acc)
        offset += len(data) + pad
        return len(accessors) - 1

    flat = [v for p in pos for v in p]
    mins = [min(p[k] for p in pos) for k in range(3)] if pos else [0, 0, 0]
    maxs = [max(p[k] for p in pos) for k in range(3)] if pos else [0, 0, 0]
    attrs = {"POSITION": add(struct.pack("<%df" % len(flat), *flat), 34962, n, 5126, "VEC3",
                             {"min": mins, "max": maxs})}
    attrs["NORMAL"] = add(struct.pack("<%df" % (3 * n), *[v for p in nrm for v in p]), 34962, n, 5126, "VEC3")
    if col:
        attrs["COLOR_0"] = add(struct.pack("<%df" % (3 * n), *[min(1.0, max(0.0, v)) for c in col for v in c]),
                               34962, n, 5126, "VEC3")
    ind = add(struct.pack("<%dI" % len(idx), *idx), 34963, len(idx), 5125, "SCALAR")
    binary = b"".join(chunks)
    doc = {"asset": {"version": "2.0", "generator": "LOKI Forge"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"mesh": 0, "name": name}],
           "meshes": [{"name": name, "primitives": [{"attributes": attrs, "indices": ind, "material": 0, "mode": 4}]}],
           "materials": [{"name": "forge", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1],
                                                                     "metallicFactor": 0.0, "roughnessFactor": 0.8}}],
           "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(binary), 0x004E4942) + binary
    path = Path(path)
    path.write_bytes(out)
    return path


def read_glb(path: Path) -> tuple:
    """(gltf_json, bin_bytes) of a .glb, checking the header and chunk layout. Raises ForgeError."""
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ForgeError("too short for a .glb")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2 or length != len(data):
        raise ForgeError("not a glTF 2.0 binary (bad header)")
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if jtype != 0x4E4F534A:
        raise ForgeError("first chunk is not JSON")
    doc = json.loads(data[20:20 + jlen].decode("utf-8"))
    rest = 20 + jlen
    binary = b""
    if rest < len(data):
        blen, btype = struct.unpack_from("<II", data, rest)
        if btype != 0x004E4942:
            raise ForgeError("second chunk is not BIN")
        binary = data[rest + 8:rest + 8 + blen]
    return doc, binary


def glb_counts(path: Path) -> dict:
    """{"vertices", "triangles"} of a .glb (first primitive of each mesh)."""
    doc, _ = read_glb(path)
    verts = tris = 0
    for m in doc.get("meshes", []):
        for prim in m.get("primitives", []):
            verts += doc["accessors"][prim["attributes"]["POSITION"]]["count"]
            if "indices" in prim:
                tris += doc["accessors"][prim["indices"]]["count"] // 3
    return {"vertices": verts, "triangles": tris}


def write_obj(path: Path, mesh: dict) -> Path:
    """Wavefront OBJ with per-vertex colours (`v x y z r g b`, sRGB 0-1 - Blender, ZBrush and
    MeshLab read them)."""
    def to_srgb(c):
        c = min(1.0, max(0.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    lines = ["# LOKI Forge"]
    cols = mesh.get("colors") or []
    for i, p in enumerate(mesh["positions"]):
        if i < len(cols):
            r, g, b = (to_srgb(v) for v in cols[i])
            lines.append("v %.5f %.5f %.5f %.4f %.4f %.4f" % (p[0], p[1], p[2], r, g, b))
        else:
            lines.append("v %.5f %.5f %.5f" % tuple(p))
    for nx, ny, nz in mesh.get("normals", []):
        lines.append("vn %.4f %.4f %.4f" % (nx, ny, nz))
    idx = mesh["indices"]
    has_n = bool(mesh.get("normals"))
    for i in range(0, len(idx), 3):
        a, b, c = idx[i] + 1, idx[i + 1] + 1, idx[i + 2] + 1
        lines.append("f %d//%d %d//%d %d//%d" % (a, a, b, b, c, c) if has_n else "f %d %d %d" % (a, b, c))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)


# ----------------------------------------------------------------------------- backends
def run_lift(img, out_base: Path, puff: float = 0.85) -> dict:
    mask, rgb, w, h = silhouette(img)
    mesh = lift_mesh(mask, rgb, w, h, puff=puff)
    glb = write_glb(out_base.with_suffix(".glb"), mesh, out_base.stem[:40])
    obj = write_obj(out_base.with_suffix(".obj"), mesh)
    return {"glb": str(glb), "obj": str(obj), "vertices": len(mesh["positions"]),
            "triangles": len(mesh["indices"]) // 3}


def run_triposr(cutout_png: Path, out_base: Path, runner=None, timeout: int = 1800) -> dict:
    """TripoSR in its own process (engine/runners/triposr.py), so torch never loads into the engine."""
    job = {"image": str(cutout_png), "out": str(out_base), "repo": str(triposr_dir()),
           "resolution": int(os.environ.get("LOKI_TRIPOSR_RESOLUTION", "256") or 256)}
    run = runner or subprocess.run
    try:
        proc = run([sys.executable, str(RUNNERS / "triposr.py")], input=json.dumps(job), capture_output=True,
                   text=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        raise ForgeError("TripoSR took longer than %d s" % timeout) from None
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise ForgeError("TripoSR gave no result: %s" % (proc.stderr or "").strip()[-300:])
    out = json.loads(lines[-1])
    if not out.get("ok"):
        raise ForgeError(str(out.get("error") or "TripoSR failed"))
    return out


def run_online(cutout_png: Path, out_base: Path, client_factory=None) -> dict:
    """A Hugging Face Space through gradio_client (TRELLIS by default: /image_to_3d, then
    /extract_glb). The picture goes to that Space - a third party."""
    space = os.environ.get("LOKI_FORGE_SPACE", DEFAULT_SPACE)
    if client_factory is None:
        try:
            from gradio_client import Client, handle_file  # pylint: disable=import-outside-toplevel
        except ImportError:
            raise ForgeError("gradio_client is not installed (pip install gradio_client)") from None
        client = Client(space, hf_token=os.environ.get("HF_TOKEN") or None)
    else:
        client, handle_file = client_factory(space)
    try:
        client.predict(image=handle_file(str(cutout_png)), multiimages=[], seed=0, ss_guidance_strength=7.5,
                       ss_sampling_steps=12, slat_guidance_strength=3.0, slat_sampling_steps=12,
                       multiimage_algo="stochastic", api_name="/image_to_3d")
        res = client.predict(mesh_simplify=0.95, texture_size=1024, api_name="/extract_glb")
    except Exception as exc:  # noqa: BLE001 - Spaces change, sleep, or run out of quota
        raise ForgeError("the online Space %s failed: %s" % (space, str(exc)[:200])) from None
    found = res[1] if isinstance(res, (list, tuple)) and len(res) > 1 else res
    if isinstance(found, dict):
        found = found.get("value") or found.get("path") or ""
    src = Path(str(found or ""))
    if not src.is_file():
        raise ForgeError("the online Space returned no .glb")
    glb = out_base.with_suffix(".glb")
    glb.write_bytes(src.read_bytes())
    read_glb(glb)
    return {"glb": str(glb), "space": space, "note": "made by an online Space (the picture was sent to it)"}


# ----------------------------------------------------------------------------- make_3d
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "model"


def default_image_maker(prompt: str, workspace: Path) -> str:
    """Text -> picture with LOKI's image runner (the same backends as the image specialist)."""
    job = {"prompt": prompt + ", a single object, centered, plain white background, full view, studio light",
           "out_dir": str(Path(workspace) / "images"), "width": 1024, "height": 1024,
           "backend": os.environ.get("LOKI_IMAGE_BACKEND", "auto")}
    proc = subprocess.run([sys.executable, str(RUNNERS / "imagegen.py")], input=json.dumps(job),
                          capture_output=True, text=True, timeout=1800, shell=False)
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    out = json.loads(lines[-1]) if lines else {"ok": False, "error": (proc.stderr or "")[-300:]}
    if not out.get("ok"):
        raise ForgeError("could not make the picture: %s" % out.get("error"))
    return str(out["file"])


def make_3d(source="", out_dir="models", prompt: str = "", backend: str = "auto", *, image_maker=None,
            progress=None, puff: float = 0.85, triposr_runner=None, online_factory=None) -> dict:
    """Make a 3D model. See the module docstring. `progress(stage, fraction)` reports each step."""
    say = progress or (lambda stage, frac: None)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        order = plan(backend)
        made_image = ""
        if not source:
            if not (prompt or "").strip():
                raise ForgeError("give a picture, a drawing or a description")
            say("making the picture", 0.05)
            maker = image_maker or (lambda p: default_image_maker(p, out.parent))
            source = made_image = maker(prompt.strip())
        say("reading the picture", 0.2)
        img = load_image(source)
        base = out / ("%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), _slug(prompt or (Path(source).stem if isinstance(
            source, str) and not source.startswith("data:") else "drawing"))))
        n = 2
        while base.with_suffix(".glb").exists():
            base = base.with_name("%s-%d" % (base.name, n))
            n += 1
        say("cutting out the subject", 0.3)
        cut = _rembg_cutout(img)
        cutter = "rembg" if cut is not None else "border colour"
        if cut is None:
            mask, _, w, h = silhouette(img, grid=256)
            Image = _pil()
            m = Image.new("L", (w, h))
            m.putdata([255 if mask[y][x] else 0 for y in range(h) for x in range(w)])
            cut = img.copy()
            cut.putalpha(m.resize(img.size, Image.BILINEAR))
        cut_dir = out / META_DIR
        cut_dir.mkdir(parents=True, exist_ok=True)
        cut_png = cut_dir / (base.name + "-cutout.png")
        cut.save(cut_png)
        errors, result, used = [], None, ""
        for name in order:
            say("shaping it (%s)" % name, 0.45)
            try:
                if name == "triposr":
                    result = run_triposr(cut_png, base, runner=triposr_runner)
                elif name == "online":
                    result = run_online(cut_png, base, client_factory=online_factory)
                else:
                    result = run_lift(cut, base, puff=puff)
                used = name
                break
            except Exception as exc:  # noqa: BLE001 - try the next backend
                errors.append("%s: %s" % (name, str(exc)[:200]))
        if result is None:
            raise ForgeError("; ".join(errors) or "no backend")
        glb = Path(result["glb"])
        read_glb(glb)
        meta = {"prompt": prompt, "source": "drawing" if isinstance(source, str) and source.startswith("data:")
                else str(made_image or source), "image": made_image, "backend": used, "cutout": cutter,
                "t": time.time(), "fallbacks": errors, **glb_counts(glb)}
        if result.get("note"):
            meta["note"] = result["note"]
        (cut_dir / (glb.name + ".json")).write_text(json.dumps(meta, indent=1), encoding="utf-8")
        say("done", 1.0)
        return {"ok": True, "glb": str(glb), "obj": str(result.get("obj") or ""), "backend": used, "meta": meta,
                "name": glb.name, "image": made_image}
    except ForgeError as exc:
        return {"ok": False, "error": str(exc)}


# ----------------------------------------------------------------------------- the window's list + jobs
def list_models(models: Path, limit: int = 120) -> list:
    folder = Path(models)
    if not folder.is_dir():
        return []
    items = []
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() == ".glb":
            try:
                meta = json.loads((folder / META_DIR / (p.name + ".json")).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            st = p.stat()
            items.append({"name": p.name, "t": st.st_mtime, "size": st.st_size,
                          "obj": p.with_suffix(".obj").name if p.with_suffix(".obj").is_file() else "",
                          **{k: meta.get(k) for k in ("prompt", "backend", "vertices", "triangles", "image", "note")
                             if k in meta}})
    items.sort(key=lambda i: i["t"], reverse=True)
    return items[:limit]


def model_file(models: Path, name: str) -> Path | None:
    """models/<name> (.glb/.obj only, no folders, no '..'); None for anything else."""
    name = str(name or "")
    if not name or "/" in name or "\\" in name or name in (".", "..") or Path(name).suffix.lower() not in MODEL_EXTS:
        return None
    root = Path(models).resolve()
    try:
        p = (root / name).resolve()
        p.relative_to(root)
    except (OSError, ValueError):
        return None
    return p if p.is_file() else None


_JOBS: dict = {}
_LOCK = threading.Lock()


def job(job_id: str) -> dict:
    with _LOCK:
        j = _JOBS.get(str(job_id))
        return dict(j) if j else {}


def jobs() -> list:
    with _LOCK:
        cutoff = time.time() - 3600
        for k in [k for k, v in _JOBS.items() if v.get("end") and v["end"] < cutoff]:
            _JOBS.pop(k, None)
        return [dict(v) for v in _JOBS.values()]


def start_job(fn, *, kind: str = "model", label: str = "", thread: bool = True) -> dict:
    """Run fn(progress) -> dict in a thread; poll job(id) for {stage, progress, done, result}."""
    with _LOCK:
        if sum(1 for v in _JOBS.values() if not v.get("end")) >= 2:
            return {"ok": False, "error": "two models are already being made - wait for one"}
        key = "f%d" % (time.time() * 1000)
        while key in _JOBS:
            key += "x"
        _JOBS[key] = {"id": key, "kind": kind, "label": label[:200], "stage": "starting", "progress": 0.0,
                      "start": time.time(), "end": 0, "done": False, "result": {}}

    def progress(stage, frac):
        with _LOCK:
            _JOBS[key].update(stage=str(stage), progress=float(frac))

    def work():
        try:
            res = fn(progress)
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        with _LOCK:
            _JOBS[key].update(done=True, end=time.time(), result=res, progress=1.0,
                              stage="done" if res.get("ok") else "failed")

    if thread:
        threading.Thread(target=work, daemon=True, name="loki-forge").start()
    else:
        work()
    return {"ok": True, "id": key}


if __name__ == "__main__":   # python engine/forge3d.py picture.png [out_dir]
    print(json.dumps(make_3d(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else "models"),
                     indent=1))
