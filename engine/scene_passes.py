"""Forge's control passes without the window: a .glb in, depth / lineart / normal / beauty PNG frames out, from an
orbit camera (one still or a turntable). Agents and background jobs use it to feed the AI Renderer
(engine/ai_renderer.py) the same passes app/ui/forge_passes.js makes in the viewport, with the same conventions:

    depth     white = near, black = far; the background is black. Normalised over the model's bounding sphere
              (near = camera distance - radius, far = + radius), the same for every frame, so a turntable's depth
              does not pump from frame to frame
    lineart   white lines on black: silhouette, one surface in front of another, and creases (normals turning)
    normal    view-space normals as RGB (n * 0.5 + 0.5; +z towards the camera, Three's MeshNormalMaterial)
    beauty    the base colour (factor x texture x vertex colour) under a key light and an ambient term

A z-buffer rasterizer in numpy - no GPU, no browser. The speed comes from never looping over pixels or triangles
in Python: triangles are bucketed by their screen size, every bucket makes all its fragments in one go, and each
batch is resolved into the z-buffer by sorting (pixel, depth). About a second a frame for a 100k-triangle model at
832x480 on one core. glTF 2.0 binary only; Draco / meshopt compressed meshes are refused with a note (decompress
them with gltf-transform first).

    python scene_passes.py model.glb out_dir [--frames 1] [--passes depth,lineart,normal,beauty] [--size 832x480]
                           [--azimuth 30] [--elevation 15] [--fov 40] [--orbit 360] [--ss 1]
"""
from __future__ import annotations

import io
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PASSES = ("depth", "lineart", "normal", "beauty")
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_FRAGS = 4_000_000          # fragments made per batch (about 100 MB of temporaries)


class PassError(RuntimeError):
    pass


# ------------------------------------------------------------------ reading a .glb
def read_glb(path) -> tuple:
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise PassError("too short for a .glb")
    magic, version, _ = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise PassError("not a glTF 2.0 binary (.glb)")
    jlen, _ = struct.unpack_from("<II", data, 12)
    doc = json.loads(data[20:20 + jlen].decode("utf-8"))
    rest, binary = 20 + jlen, b""
    if rest + 8 <= len(data):
        blen, _ = struct.unpack_from("<II", data, rest)
        binary = data[rest + 8:rest + 8 + blen]
    return doc, binary


def _view(doc, binary, idx) -> bytes:
    bv = doc["bufferViews"][idx]
    off = bv.get("byteOffset", 0)
    return binary[off:off + bv["byteLength"]], bv.get("byteStride")


def accessor(doc, binary, idx) -> np.ndarray:
    acc = doc["accessors"][idx]
    dt, n, count = np.dtype(_CT[acc["componentType"]]), _N[acc["type"]], acc["count"]
    if "bufferView" not in acc:
        return np.zeros((count, n), np.float32)
    raw, stride = _view(doc, binary, acc["bufferView"])
    off, item = acc.get("byteOffset", 0), dt.itemsize * n
    stride = stride or item
    buf = np.frombuffer(raw, np.uint8, count=(count - 1) * stride + item, offset=off)
    rows = np.lib.stride_tricks.as_strided(buf, shape=(count, item), strides=(stride, 1))
    out = np.ascontiguousarray(rows).view(dt).reshape(count, n)
    if acc.get("normalized") and dt.kind in "iu":
        out = out.astype(np.float32) / float(np.iinfo(dt).max)
    return out


def _matrix(node) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], np.float64).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), np.float64)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = np.array(node.get("scale", [1, 1, 1]), np.float64)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def _image(doc, binary, tex_idx):
    try:
        src = doc["textures"][tex_idx]["source"]
        img = doc["images"][src]
        if "bufferView" in img:
            raw, _ = _view(doc, binary, img["bufferView"])
        elif str(img.get("uri", "")).startswith("data:"):
            import base64  # pylint: disable=import-outside-toplevel
            raw = base64.b64decode(img["uri"].split(",", 1)[1])
        else:
            return None
        return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), np.float32) / 255.0
    except Exception:  # noqa: BLE001 - a texture that will not load: the base colour alone
        return None


def load(path) -> dict:
    """Every triangle of the default scene in world space: {"v", "f", "uv", "col", "nrm", "mat", "materials"}."""
    doc, binary = read_glb(path)
    need = set(doc.get("extensionsRequired") or [])
    if need & {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}:
        raise PassError("the meshes are compressed (%s) - decompress first: npx @gltf-transform/cli copy in.glb out.glb"
                        % ", ".join(sorted(need)))
    mats = []
    for m in doc.get("materials") or []:
        pbr = m.get("pbrMetallicRoughness") or {}
        tex = pbr.get("baseColorTexture")
        mats.append({"factor": np.array((pbr.get("baseColorFactor") or [1, 1, 1, 1])[:3], np.float32),
                     "tex": _image(doc, binary, tex["index"]) if tex else None})
    default_mat = len(mats)
    mats.append({"factor": np.array([0.8, 0.8, 0.8], np.float32), "tex": None})
    vs, fs, uvs, cols, nrms, mids = [], [], [], [], [], []
    base = 0
    nodes = doc.get("nodes") or []
    scenes = doc.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    roots = scenes[doc.get("scene", 0)].get("nodes") or []
    stack = [(i, np.eye(4)) for i in roots]
    while stack:
        i, parent = stack.pop()
        node = nodes[i]
        world = parent @ _matrix(node)
        stack += [(c, world) for c in node.get("children") or []]
        if "mesh" not in node:
            continue
        nmat = np.linalg.inv(world[:3, :3]).T
        for prim in doc["meshes"][node["mesh"]].get("primitives") or []:
            if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                continue
            a = prim["attributes"]
            p = accessor(doc, binary, a["POSITION"]).astype(np.float64)
            n = len(p)
            idx = (accessor(doc, binary, prim["indices"]).reshape(-1) if "indices" in prim
                   else np.arange(n)).astype(np.int64)
            idx = idx[: len(idx) // 3 * 3].reshape(-1, 3)
            vs.append(p @ world[:3, :3].T + world[:3, 3])
            uvs.append(accessor(doc, binary, a["TEXCOORD_0"])[:, :2].astype(np.float32) if "TEXCOORD_0" in a
                       else np.zeros((n, 2), np.float32))
            cols.append(accessor(doc, binary, a["COLOR_0"])[:, :3].astype(np.float32) if "COLOR_0" in a
                        else np.ones((n, 3), np.float32))
            if "NORMAL" in a:
                nn = accessor(doc, binary, a["NORMAL"]).astype(np.float64) @ nmat.T
                nrms.append(nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12))
            else:
                nrms.append(np.full((n, 3), np.nan))
            fs.append(idx + base)
            mids.append(np.full(len(idx), prim.get("material", default_mat), np.int32))
            base += n
    if not fs:
        raise PassError("no triangles in %s" % Path(path).name)
    return {"v": np.concatenate(vs), "f": np.concatenate(fs), "uv": np.concatenate(uvs), "col": np.concatenate(cols),
            "nrm": np.concatenate(nrms), "mat": np.concatenate(mids), "materials": mats}


# ------------------------------------------------------------------ the camera
def orbit_camera(v, azimuth, elevation, fov, aspect):
    lo, hi = v.min(0), v.max(0)
    center = (lo + hi) / 2
    radius = max(float(np.sqrt(((v - center) ** 2).sum(1).max())), 1e-6)
    half = math.radians(fov) / 2
    fit = min(half, math.atan(math.tan(half) * aspect))       # the narrower of the two angles holds the sphere
    dist = radius / math.sin(fit) * 1.02
    az, el = math.radians(azimuth), math.radians(elevation)
    eye = center + dist * np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])
    fwd = (center - eye) / np.linalg.norm(center - eye)
    up = np.array([0.0, 1.0, 0.0]) if abs(fwd[1]) < 0.999 else np.array([0.0, 0.0, 1.0])
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    rot = np.stack([right, up, -fwd])                          # world -> view (camera looks down -z)
    return {"rot": rot, "eye": eye, "near": max(dist - radius, 1e-4), "far": dist + radius, "fov": fov}


# ------------------------------------------------------------------ rasterizing
def rasterize(scene, cam, w, h):
    """Per pixel: view depth (inf = background), triangle id, perspective-correct barycentrics."""
    pv = (scene["v"] - cam["eye"]) @ cam["rot"].T
    z = -pv[:, 2]
    f = 0.5 * h / math.tan(math.radians(cam["fov"]) / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        sx = w / 2 + f * pv[:, 0] / z
        sy = h / 2 - f * pv[:, 1] / z
    tri = scene["f"]
    zt = z[tri]
    keep = np.all(zt > 1e-6, axis=1)
    X, Y = sx[tri], sy[tri]
    area = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
    x0 = np.floor(X.min(1) - 0.5)
    x1 = np.ceil(X.max(1) - 0.5)
    y0 = np.floor(Y.min(1) - 0.5)
    y1 = np.ceil(Y.max(1) - 0.5)
    keep &= (np.abs(area) > 1e-12) & (x1 >= 0) & (y1 >= 0) & (x0 < w) & (y0 < h) & np.isfinite(area)
    ids = np.nonzero(keep)[0]
    x0 = np.clip(x0[ids], 0, w - 1).astype(np.int64)
    y0 = np.clip(y0[ids], 0, h - 1).astype(np.int64)
    x1 = np.clip(x1[ids], 0, w - 1).astype(np.int64)
    y1 = np.clip(y1[ids], 0, h - 1).astype(np.int64)
    size = np.maximum(x1 - x0, y1 - y0) + 1
    zbuf = np.full(w * h, np.inf)
    tid = np.full(w * h, -1, np.int64)
    bary = np.zeros((w * h, 3))
    inv_z = 1.0 / zt

    def resolve(pix, depth, t, b):
        order = np.lexsort((depth, pix))
        pix, depth, t, b = pix[order], depth[order], t[order], b[order]
        first = np.ones(len(pix), bool)
        first[1:] = pix[1:] != pix[:-1]
        pix, depth, t, b = pix[first], depth[first], t[first], b[first]
        win = depth < zbuf[pix]
        p = pix[win]
        zbuf[p], tid[p], bary[p] = depth[win], t[win], b[win]

    def fragments(sel, kx, ky):
        ox, oy = np.meshgrid(np.arange(kx), np.arange(ky))
        ox, oy = ox.reshape(-1), oy.reshape(-1)
        px = x0[sel][:, None] + ox
        py = y0[sel][:, None] + oy
        inside = (px <= x1[sel][:, None]) & (py <= y1[sel][:, None])
        t = ids[sel]
        cx, cy = px + 0.5, py + 0.5
        Xt, Yt, A = X[t], Y[t], area[t][:, None]
        b0 = ((Xt[:, 1, None] - cx) * (Yt[:, 2, None] - cy) - (Xt[:, 2, None] - cx) * (Yt[:, 1, None] - cy)) / A
        b1 = ((Xt[:, 2, None] - cx) * (Yt[:, 0, None] - cy) - (Xt[:, 0, None] - cx) * (Yt[:, 2, None] - cy)) / A
        b2 = 1.0 - b0 - b1
        inside &= (b0 >= 0) & (b1 >= 0) & (b2 >= 0)
        r, c = np.nonzero(inside)
        if not len(r):
            return
        tt = t[r]
        lin = np.stack([b0[r, c], b1[r, c], b2[r, c]], 1)
        iz = lin * inv_z[tt]
        s = iz.sum(1)
        resolve(py[r, c] * w + px[r, c], 1.0 / s, tt, iz / s[:, None])

    k = 1
    while True:
        sel_all = np.nonzero((size <= k) & (size > k // 2) if k > 1 else size <= 1)[0]
        if k > 64:
            sel_all = np.nonzero(size > 64)[0]
            for s in sel_all:                               # the few big ones: one at a time, their own box
                fragments(np.array([s]), int(x1[s] - x0[s] + 1), int(y1[s] - y0[s] + 1))
            break
        step = max(1, _FRAGS // (k * k))
        for i in range(0, len(sel_all), step):
            fragments(sel_all[i:i + step], k, k)
        k *= 2
    return zbuf.reshape(h, w), tid.reshape(h, w), bary.reshape(h, w, 3), pv


def _normals(scene, cam, tid, bary, pv):
    hit = tid >= 0
    t = tid[hit]
    tri = scene["f"][t]
    p = pv[scene["f"]]
    fn = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    n = fn[t]
    vn = scene["nrm"]
    if not np.isnan(vn).all():
        vv = vn @ cam["rot"].T
        sm = np.einsum("pk,pkc->pc", bary[hit], vv[tri])
        ok = np.isfinite(sm).all(1) & (np.linalg.norm(sm, axis=1) > 1e-6)
        n[ok] = sm[ok] / np.linalg.norm(sm[ok], axis=1, keepdims=True)
    flip = n[:, 2] < 0                                      # double sided: the side facing the camera
    n[flip] *= -1
    out = np.zeros(tid.shape + (3,))
    out[hit] = n
    return out


def lineart(depth01, normal, hit, depth_edge=0.04, normal_edge=0.35, width=1):
    """forge_passes.js lineArt, vectorized: an edge where the pixel to the right or below differs."""
    edge = np.zeros(hit.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        h2 = np.pad(hit, ((0, dy), (0, dx)), mode="edge")[dy:, dx:]
        d2 = np.pad(depth01, ((0, dy), (0, dx)), mode="edge")[dy:, dx:]
        n2 = np.pad(normal, ((0, dy), (0, dx), (0, 0)), mode="edge")[dy:, dx:]
        both = hit & h2
        edge |= hit != h2
        edge |= both & (np.abs(depth01 - d2) > depth_edge)
        edge |= both & (1 - (normal * n2).sum(-1) > normal_edge)
    for _ in range(max(0, min(3, int(width) - 1))):
        e = edge.copy()
        e[1:] |= edge[:-1]
        e[:-1] |= edge[1:]
        e[:, 1:] |= edge[:, :-1]
        e[:, :-1] |= edge[:, 1:]
        edge = e
    return edge


def _beauty(scene, tid, bary, normal):
    hit = tid >= 0
    out = np.full(tid.shape + (3,), 0.16)
    t = tid[hit]
    tri = scene["f"][t]
    b = bary[hit]
    col = np.einsum("pk,pkc->pc", b, scene["col"][tri])
    uv = np.einsum("pk,pkc->pc", b, scene["uv"][tri])
    mat = scene["mat"][t]
    base = np.ones((len(t), 3))
    for mi in np.unique(mat):
        sel = mat == mi
        m = scene["materials"][mi] if mi < len(scene["materials"]) else scene["materials"][-1]
        c = np.broadcast_to(m["factor"], (int(sel.sum()), 3)).astype(np.float64)
        if m["tex"] is not None:
            th, tw = m["tex"].shape[:2]
            u = np.mod(uv[sel, 0], 1.0) * (tw - 1)
            v = np.mod(uv[sel, 1], 1.0) * (th - 1)
            c = c * m["tex"][np.rint(v).astype(np.int64), np.rint(u).astype(np.int64)]
        base[sel] = c
    n = normal[hit]
    key = np.array([-0.45, 0.65, 0.62])
    key /= np.linalg.norm(key)
    fill = np.array([0.7, 0.1, 0.7])
    fill /= np.linalg.norm(fill)
    rim = np.clip(1.0 - n[:, 2], 0, 1) ** 3                       # light around the silhouette
    shade = 0.38 + 0.62 * np.clip(n @ key, 0, 1) + 0.28 * np.clip(n @ fill, 0, 1) + 0.25 * rim
    lit = base * col * shade[:, None]
    lum = float(np.percentile(lit.max(1), 90)) if len(lit) else 1.0
    if 0 < lum < 0.55:                                            # a dark model: exposed up, not left in the shadows
        lit = lit * min(2.5, 0.75 / lum)
    out[hit] = np.clip(lit, 0, 1) ** (1 / 1.15)
    return out


def _png(arr01, path, size=None):
    img = Image.fromarray(np.clip(np.rint(arr01 * 255), 0, 255).astype(np.uint8))
    if size and img.size != size:
        img = img.resize(size, Image.LANCZOS)
    img.save(path)
    return str(path)


def render(glb, out_dir, frames: int = 1, passes=("depth", "lineart"), width: int = 832, height: int = 480,
           azimuth: float = 30.0, elevation: float = 15.0, fov: float = 40.0, orbit: float = 360.0, ss: int = 1,
           line_width: int = 1, scene=None) -> dict:
    """<out_dir>/<pass>/0000.png ... -> {"ok", "frames", "width", "height", "passes": {pass: [paths]}, "seconds"}."""
    import time  # pylint: disable=import-outside-toplevel
    t0 = time.time()
    want = [p for p in passes if p in PASSES]
    if not want:
        raise PassError("passes: any of %s" % ", ".join(PASSES))
    frames = max(1, min(int(frames), 4096))
    ss = max(1, min(int(ss), 3))
    W, H = int(width) * ss, int(height) * ss
    scene = scene or load(glb)
    out = Path(out_dir)
    made = {p: [] for p in want}
    for p in want:
        (out / p).mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        az = azimuth + orbit * i / frames
        cam = orbit_camera(scene["v"], az, elevation, fov, W / H)
        zbuf, tid, bary, pv = rasterize(scene, cam, W, H)
        hit = tid >= 0
        d01 = np.where(hit, np.clip((cam["far"] - zbuf) / (cam["far"] - cam["near"]), 0, 1), 0.0)
        need_n = {"normal", "lineart", "beauty"} & set(want)
        normal = _normals(scene, cam, tid, bary, pv) if need_n else None
        name = "%04d.png" % i
        size = (int(width), int(height))
        if "depth" in want:
            made["depth"].append(_png(np.repeat(d01[..., None], 3, -1), out / "depth" / name, size))
        if "lineart" in want:
            e = lineart(d01, normal, hit, width=line_width * ss).astype(np.float64)
            made["lineart"].append(_png(np.repeat(e[..., None], 3, -1), out / "lineart" / name, size))
        if "normal" in want:
            made["normal"].append(_png(np.where(hit[..., None], normal * 0.5 + 0.5, 0.0), out / "normal" / name, size))
        if "beauty" in want:
            made["beauty"].append(_png(_beauty(scene, tid, bary, normal), out / "beauty" / name, size))
    return {"ok": True, "frames": frames, "width": int(width), "height": int(height), "passes": made,
            "triangles": int(len(scene["f"])), "seconds": round(time.time() - t0, 2)}


def main(argv) -> int:
    import argparse  # pylint: disable=import-outside-toplevel
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("glb")
    ap.add_argument("out")
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--passes", default="depth,lineart,normal,beauty")
    ap.add_argument("--size", default="832x480")
    ap.add_argument("--azimuth", type=float, default=30.0)
    ap.add_argument("--elevation", type=float, default=15.0)
    ap.add_argument("--fov", type=float, default=40.0)
    ap.add_argument("--orbit", type=float, default=360.0)
    ap.add_argument("--ss", type=int, default=1)
    a = ap.parse_args(argv)
    w, h = (int(x) for x in a.size.lower().split("x"))
    try:
        res = render(a.glb, a.out, a.frames, a.passes.split(","), w, h, a.azimuth, a.elevation, a.fov, a.orbit, a.ss)
    except (PassError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({k: v for k, v in res.items() if k != "passes"} | {"out": str(a.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
