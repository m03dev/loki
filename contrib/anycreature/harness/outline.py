#!/usr/bin/env python3
"""Silhouettes straight from the geometry — no browser, no renderer, no images to read.

    python3 harness/outline.py <model.glb> <outdir> [--prev <dir>] [--views front,side,top,hero]

WHY. The silhouette is the single most-used measurement in this harness, and
until now getting one meant launching a headless Chromium, loading three.js,
uploading the mesh to a GPU, drawing it black-on-white, and reading the pixels
back. That is a lot of machinery to answer a question the vertices already
contain: this is low-poly, a few thousand triangles, and the outline of a solid
under a known camera is arithmetic.

So this projects the triangles and fills them. Same camera the renderer used
(perspective, 30 degrees, distance = longest dimension x 2.4, 640x640, same view
directions and up vectors), same mask convention, same metrics. The point is not
only speed — it is that the numbers stop being *estimates read off a picture*
and become the thing itself.

WHAT THIS DOES NOT REPLACE. It cannot tell you WHAT the shape looks like. "Is
this a bison" is a judgment about resemblance and it needs eyes; that is the
blind reader's job and no amount of coordinate data does it. What this removes
is everything AROUND that question — aspect, protrusions, thinnest feature,
round-to-round similarity — so the reader can be handed one picture and one
question instead of thirteen pictures and a questionnaire.
"""
import sys, os, json, struct, math

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:
    print('BLOCK: outline.py needs numpy and pillow — run setup.sh')
    sys.exit(2)

RES = 640
FOV = 30.0


# ── GLB ────────────────────────────────────────────────────────────────────
def read_glb(path):
    b = open(path, 'rb').read()
    if b[:4] != b'glTF':
        raise ValueError('not a GLB')
    jlen, = struct.unpack('<I', b[12:16])
    g = json.loads(b[20:20 + jlen])
    bin_off = 20 + jlen + 8
    return g, b, bin_off


def accessor(g, b, base, idx):
    a = g['accessors'][idx]
    bv = g['bufferViews'][a['bufferView']]
    off = base + bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    n = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
    ct = a['componentType']
    fmt, size = {5126: ('f', 4), 5125: ('I', 4), 5123: ('H', 2), 5121: ('B', 1)}[ct]
    stride = bv.get('byteStride') or size * n
    out = np.empty((a['count'], n), dtype=np.float64 if ct == 5126 else np.int64)
    for i in range(a['count']):
        out[i] = struct.unpack_from('<' + fmt * n, b, off + i * stride)
    return out


def triangles_by_material(path, want_colour=False):
    """Triangles grouped by material name, so a share can be attributed.

    With want_colour, also returns the baked albedo: per-vertex COLOR_0 and the
    per-material baseColorFactor. ALBEDO = baseColorFactor x COLOR_0, ALWAYS
    BOTH — the engine splits the baked colour, the hue into baseColorFactor and
    the shading ratio (<=1) into COLOR_0, so reading either alone measures half
    a colour. Both are linear; the sRGB encode happens at measurement time."""
    g, b, base = read_glb(path)
    mats = [m.get('name', f'mat{i}') for i, m in enumerate(g.get('materials', []))]
    basecol = np.array([(m.get('pbrMetallicRoughness', {}) or {}).get('baseColorFactor', [1, 1, 1, 1])[:3]
                        for m in g.get('materials', [])], dtype=np.float64) if g.get('materials') else np.zeros((0, 3))
    V, F, MID, C, N = [], [], [], [], []
    for mesh in g.get('meshes', []):
        for pr in mesh.get('primitives', []):
            at = pr.get('attributes', {})
            if 'POSITION' not in at:
                continue
            off = sum(len(x) for x in V)
            pos = accessor(g, b, base, at['POSITION'])
            V.append(pos)
            if want_colour:
                N.append(accessor(g, b, base, at['NORMAL']).astype(np.float64)
                         if 'NORMAL' in at else np.zeros((len(pos), 3)))
                if 'COLOR_0' in at:
                    c = accessor(g, b, base, at['COLOR_0'])[:, :3].astype(np.float64)
                    a0 = g['accessors'][at['COLOR_0']]
                    if a0['componentType'] == 5123:      # normalised ushort
                        c = c / 65535.0
                    elif a0['componentType'] == 5121:    # normalised ubyte
                        c = c / 255.0
                else:
                    c = np.ones((len(pos), 3))
                C.append(c)
            if 'indices' in pr:
                f = accessor(g, b, base, pr['indices']).reshape(-1, 3) + off
            else:
                n = len(pos) - len(pos) % 3
                f = np.arange(n).reshape(-1, 3) + off
            F.append(f)
            mi = pr.get('material', -1)
            MID.append(np.full(len(f), mi, dtype=np.int64))
    if not V:
        raise ValueError('no geometry in the file')
    if want_colour:
        return np.vstack(V), np.vstack(F), np.concatenate(MID), mats, np.vstack(C), basecol, np.vstack(N)
    return np.vstack(V), np.vstack(F), np.concatenate(MID), mats


def structure(path):
    """What the file IS, from the JSON chunk: clips, skins, triangle count.

    This used to come from loading the model into three.js inside a headless
    browser and traversing the scene graph. It is written in the glTF header."""
    g, b, base = read_glb(path)
    tris = 0
    skinned = 0
    for mesh in g.get('meshes', []):
        for pr in mesh.get('primitives', []):
            at = pr.get('attributes', {})
            if 'indices' in pr:
                tris += g['accessors'][pr['indices']]['count'] // 3
            elif 'POSITION' in at:
                tris += g['accessors'][at['POSITION']]['count'] // 3
    for nd in g.get('nodes', []):
        if 'skin' in nd and 'mesh' in nd:
            skinned += 1
    return {'triangles': int(tris), 'skinnedMeshes': int(skinned),
            'animations': [a.get('name', f'anim{i}') for i, a in enumerate(g.get('animations', []))]}


def part_boxes(V, F, MID, mats):
    """Per-material bounding box, from the vertices its own triangles reference.

    Measure only the referenced vertices: glTF primitives routinely share one
    POSITION accessor, so scanning the attribute gives every material the bbox
    of the whole body."""
    whole = [float(V[:, k].max() - V[:, k].min()) for k in range(3)]
    dxz = lambda s: math.hypot(s[0], s[2])
    out = {}
    for mi in np.unique(MID):
        if mi < 0:
            continue
        idx = np.unique(F[MID == mi].reshape(-1))
        sub_v = V[idx]
        s = [float(sub_v[:, k].max() - sub_v[:, k].min()) for k in range(3)]
        name = mats[mi] if 0 <= mi < len(mats) else f'mat{mi}'
        out[name] = {'size': [round(x, 4) for x in s],
                     'span_ratio': round(dxz(s) / (dxz(whole) or 1), 4),
                     'height_ratio': round(s[1] / (whole[1] or 1), 4)}
    return out, [round(x, 4) for x in whole]


def triangles(path):
    """Every triangle in the file, as world-space vertex positions.

    Bind pose only, which is what a silhouette gate looks at: this engine writes
    inverse bind matrices that are pure translations of the joint's world
    position, so the stored POSITION values are already world-space at rest."""
    g, b, base = read_glb(path)
    V, F = [], []
    for mesh in g.get('meshes', []):
        for pr in mesh.get('primitives', []):
            at = pr.get('attributes', {})
            if 'POSITION' not in at:
                continue
            off = sum(len(x) for x in V)
            pos = accessor(g, b, base, at['POSITION'])
            V.append(pos)
            if 'indices' in pr:
                ix = accessor(g, b, base, pr['indices']).reshape(-1)
                F.append(ix.reshape(-1, 3) + off)
            else:
                n = len(pos) - len(pos) % 3
                F.append(np.arange(n).reshape(-1, 3) + off)
    if not V:
        raise ValueError('no geometry in the file')
    return np.vstack(V), np.vstack(F)


# ── camera, matching the renderer this replaced, exactly ───────────────────
def view_dir(view, size):
    long_axis = 'x' if size[0] > size[2] else 'z'
    if view == 'top':
        return np.array([0., 1., 0.]), np.array([1., 0., 0.]) if long_axis == 'x' else np.array([0., 0., 1.])
    if view == 'hero':
        return np.array([1., 0.5, 1.]), np.array([0., 1., 0.])
    if view == 'side':
        d = [0., 0., 1.] if long_axis == 'x' else [1., 0., 0.]
    else:                                   # front
        d = [1., 0., 0.] if long_axis == 'x' else [0., 0., 1.]
    return np.array(d), np.array([0., 1., 0.])


def render_mask(V, F, view):
    lo, hi = V.min(axis=0), V.max(axis=0)
    centre, size = (lo + hi) / 2, hi - lo
    d, up = view_dir(view, size)
    rad = float(size.max())
    # NOT normalised, deliberately. three.js does
    #     cam.position = centre + new Vector3(...dir) * (rad * 2.4)
    # on the raw vector, and the hero direction [1, 0.5, 1] has length 1.5 — so
    # the hero camera really does sit 1.5x further out than the axis views. A
    # pixel-level comparison caught this: front/side/top matched at IoU 0.98+
    # because their directions are already unit, and hero came back at 0.39.
    eye = centre + d * rad * 2.4

    fwd = centre - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    if np.linalg.norm(right) < 1e-9:        # looking straight down the up axis
        right = np.cross(fwd, np.array([0., 0., 1.]))
    right /= np.linalg.norm(right)
    trueup = np.cross(right, fwd)

    rel = V - eye
    cam = np.stack([rel @ right, rel @ trueup, rel @ fwd], axis=1)
    z = np.maximum(cam[:, 2], 1e-6)
    f = 1.0 / math.tan(math.radians(FOV) / 2)
    sx = (cam[:, 0] / z) * f
    sy = (cam[:, 1] / z) * f
    px = (sx * 0.5 + 0.5) * RES
    py = (0.5 - sy * 0.5) * RES            # image y grows downward

    img = Image.new('1', (RES, RES), 0)
    drw = ImageDraw.Draw(img)
    for a, b_, c in F:
        drw.polygon([(px[a], py[a]), (px[b_], py[b_]), (px[c], py[c])], fill=1)
    return np.array(img, dtype=bool)


# ── measures, on the mask ──────────────────────────────────────────────────
def measures(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return {'empty': True}
    w = int(xs.max() - xs.min() + 1)
    h = int(ys.max() - ys.min() + 1)
    area = int(mask.sum())
    m = {
        'W_over_H': round(w / h, 3),
        'fill': round(area / (w * h), 3),
        'px': [w, h],
    }
    # WHERE THE MASS SITS, in thirds of its own bounding box. Same definition as
    # the measure pass it replaced, on the cropped mask, to the decimal.
    #
    # This is the number that tells two DESIGNS apart, which iou_vs_prev does
    # not: iou counts overlapping pixels, so a proportion change moves it a lot
    # while the design stays put. Read off a shipped 13-round build, iou swung
    # 0.476-0.873 while thirds_cols never left [~0.23, ~0.33, ~0.44] — thirteen
    # rounds, one layout, including both rounds the log calls concept restarts.
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    m['thirds_cols'] = [round(float(crop[:, i * w // 3:(i + 1) * w // 3].sum() / area), 2)
                        for i in range(3)]
    m['thirds_rows'] = [round(float(crop[i * h // 3:(i + 1) * h // 3].sum() / area), 2)
                        for i in range(3)]
    try:
        from scipy import ndimage
    except ImportError:
        # Silence here is dangerous: thinnest_px48 gates legibility and protrusions
        # gates boldness, so a missing dependency would drop two BLOCKING measures and
        # every build would pass them by not having them. Say so, once, loudly.
        print('WARN: scipy missing — protrusions, thinnest_px48, convexity and mirror_sym '
              'are NOT computed, so the legibility and boldness gates have nothing to read. '
              'Run setup.sh.', file=sys.stderr)
        return m
    # Protrusions and thinnest_px48 keep the original definitions EXACTLY —
    # erode hard to get a core, subtract to get appendages, and measure each
    # appendage's own thickness as twice its maximum inscribed radius, scaled to
    # the 48px thumbnail the reader actually sees. Two implementations of the
    # same number must agree or one of them is lying; the first version here
    # took the global minimum of the distance transform instead, which is the
    # one-pixel boundary and therefore always ~1px, on every creature.
    H, W = mask.shape
    it = max(2, int(min(H, W) * 0.06))
    core = ndimage.binary_erosion(mask, iterations=it)
    app = mask & ~ndimage.binary_dilation(core, iterations=it)
    la, na = ndimage.label(app)
    protr = []
    for i in range(1, na + 1):
        blob = la == i
        s = int(blob.sum())
        if s < area * 0.01:
            continue
        dt = ndimage.distance_transform_edt(blob)
        protr.append(round(2 * float(dt.max()) * 48.0 / max(H, W), 1))
    m['protrusions'] = len(protr)
    m['thinnest_px48'] = min(protr) if protr else None
    return m


def project(V, view):
    """World vertices -> screen x, y and camera depth, for one view."""
    lo, hi = V.min(axis=0), V.max(axis=0)
    centre, size = (lo + hi) / 2, hi - lo
    d, up = view_dir(view, size)
    rad = float(size.max())
    eye = centre + d * rad * 2.4
    fwd = centre - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    if np.linalg.norm(right) < 1e-9:
        right = np.cross(fwd, np.array([0., 0., 1.]))
    right /= np.linalg.norm(right)
    trueup = np.cross(right, fwd)
    rel = V - eye
    cam = np.stack([rel @ right, rel @ trueup, rel @ fwd], axis=1)
    z = np.maximum(cam[:, 2], 1e-6)
    f = 1.0 / math.tan(math.radians(FOV) / 2)
    px = ((cam[:, 0] / z) * f * 0.5 + 0.5) * RES
    py = (0.5 - (cam[:, 1] / z) * f * 0.5) * RES
    return px, py, z


def material_shares(V, F, MID, mats, view, C=None, basecol=None, N=None):
    """Which material OWNS each silhouette pixel, with a depth test.

    The share of the frame a part holds is a geometry question, and it was being
    answered by a browser: render every material in a distinct colour, read the
    pixels back, count them. That needs a GPU only because of occlusion — a wing
    behind the torso must not be counted — and occlusion is a z-buffer, which is
    thirty lines. So: rasterise every triangle with a depth test, keep the
    winning material per pixel, and count."""
    px, py, z = project(V, view)
    depth = np.full((RES, RES), np.inf)
    owner = np.full((RES, RES), -1, dtype=np.int64)
    # The colour buffer rides along in the SAME rasteriser. A second pass would be
    # a second definition of "which pixel does this triangle win", and two of those
    # have to be kept in agreement by hand.
    colour = np.zeros((RES, RES, 3)) if C is not None else None
    normal = np.zeros((RES, RES, 3)) if N is not None else None
    for tri, mi in zip(F, MID):
        a, b, c = tri
        xs = np.array([px[a], px[b], px[c]])
        ys = np.array([py[a], py[b], py[c]])
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(RES - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(RES - 1, np.ceil(ys.max())))
        if x1 < x0 or y1 < y0:
            continue
        det = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(det) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                             np.arange(y0, y1 + 1) + 0.5)
        l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / det
        l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / det
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue
        # PERSPECTIVE-CORRECT interpolation, not affine. l0/l1/l2 are barycentric
        # in SCREEN space, and screen space is already divided by depth — so
        # blending a per-vertex quantity with them directly is only right for an
        # orthographic camera. This one is a pinhole at 30 degrees. The textbook
        # correction: blend 1/z, take the reciprocal for depth, and divide any
        # other attribute back out by it.
        #
        # It matters most exactly where it is hardest to see: a long triangle
        # running away from the camera, where the affine version puts the middle
        # of the surface at the wrong depth and can lose a depth test against
        # something genuinely behind it.
        iz = l0 / z[a] + l1 / z[b] + l2 / z[c]
        iz = np.where(np.abs(iz) < 1e-12, 1e-12, iz)
        zz = 1.0 / iz
        sub = depth[y0:y1 + 1, x0:x1 + 1]
        win = inside & (zz < sub)
        if win.any():
            sub[win] = zz[win]
            owner[y0:y1 + 1, x0:x1 + 1][win] = mi
            if colour is not None:
                cc = ((l0 / z[a])[..., None] * C[a] + (l1 / z[b])[..., None] * C[b]
                      + (l2 / z[c])[..., None] * C[c]) * zz[..., None]
                if basecol is not None and 0 <= mi < len(basecol):
                    cc = cc * basecol[mi]
                colour[y0:y1 + 1, x0:x1 + 1][win] = cc[win]
            if normal is not None:
                nn = ((l0 / z[a])[..., None] * N[a] + (l1 / z[b])[..., None] * N[b]
                      + (l2 / z[c])[..., None] * N[c]) * zz[..., None]
                normal[y0:y1 + 1, x0:x1 + 1][win] = nn[win]
    total = int((owner >= 0).sum())
    out = {}
    if total:
        for mi in np.unique(owner):
            if mi < 0:
                continue
            name = mats[mi] if 0 <= mi < len(mats) else f'mat{mi}'
            out[name] = round(float((owner == mi).sum()) / total, 5)
    if colour is not None and normal is not None:
        return out, owner >= 0, colour, normal
    if colour is not None:
        return out, owner >= 0, colour
    return out, owner >= 0


def hero_png(model, out_png, view='hero', res=1024):
    """The delivery's hero shot, rasterised — no browser, no renderer, no lights.

    This is the last thing Chromium was kept alive for, and it did not need to be
    alive for it: the whole L1-L8 shading stack is BAKED into COLOR_0 at build
    time, so the flat albedo already carries the gradient, the seams, the ambient
    occlusion and the rim. Rendering it again with three-point studio lighting was
    lighting a photograph. The z-buffer here decides occlusion exactly as it does
    for every other measure, and the background is alpha rather than a grey card.

    Resolution is raised for this one pass because a thumbnail is looked at by a
    person, not measured; every gate keeps reading the 640 grid."""
    global RES
    keep = RES
    try:
        RES = res
        V, F, MID, mats, C, basecol, Nv = triangles_by_material(model, want_colour=True)
        _, mask, colour, nrm = material_shares(V, F, MID, mats, view, C, basecol, Nv)
        # The same rig the retired renderer used: a warm-over-cool hemisphere, a
        # key, a cool fill and a cool rim. Lambert only — these are matte low-poly
        # surfaces with the specular story already painted into the vertex colour,
        # so a full PBR evaluation would be re-deriving what is baked.
        ln = np.linalg.norm(nrm, axis=2, keepdims=True)
        n = np.divide(nrm, np.where(ln > 1e-9, ln, 1.0))
        up = n[:, :, 1:2]
        sky, ground = np.array([1.0, 1.0, 1.0]), np.array([0.541, 0.522, 0.471])
        irr = 1.5 * (sky * (0.5 + 0.5 * up) + ground * (0.5 - 0.5 * up))
        for pos, col, amp in ((( 3.0, 4.0,  2.5), (1.0, 1.0, 1.0), 2.4),
                              ((-4.0, 1.5,  2.0), (0.812, 0.847, 1.0), 1.0),
                              ((-2.5, 2.5, -4.0), (0.667, 0.769, 1.0), 1.6)):
            d = np.array(pos, dtype=np.float64); d /= np.linalg.norm(d)
            lam = np.clip((n * d).sum(axis=2, keepdims=True), 0.0, 1.0)
            irr = irr + np.array(col) * amp * lam
        # Exposure. The Lambert sum above is not the renderer's shader, so it lands
        # near but not on the old brightness: checked against the renderer this
        # replaces, across the reference shelf, the ratio ran 0.91 median. 1.1 puts
        # it back. This constant touches the PICTURE only — no gate reads the hero.
        lin = np.clip(colour * irr * (1.1 / np.pi), 0.0, 1.0)
        srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
        rgb = np.clip(srgb * 255.0, 0, 255).astype(np.uint8)
        rgba = np.dstack([rgb, np.where(mask, 255, 0).astype(np.uint8)])
        # Frame it. The measuring camera fits the whole bounding sphere so that a
        # silhouette is comparable between rounds; a thumbnail has no such duty and
        # a creature sitting in a third of the frame reads as a small creature.
        # Crop to what is actually drawn, keep it square, leave a margin.
        ys, xs = np.nonzero(mask)
        if len(xs):
            cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
            half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 * 1.12
            x0, y0 = int(round(cx - half)), int(round(cy - half))
            side = int(round(half * 2))
            pad = np.zeros((side, side, 4), dtype=np.uint8)
            sx0, sy0 = max(0, x0), max(0, y0)
            sx1, sy1 = min(res, x0 + side), min(res, y0 + side)
            pad[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = rgba[sy0:sy1, sx0:sx1]
            rgba = pad
        Image.fromarray(rgba, 'RGBA').resize((res, res), Image.LANCZOS).save(out_png)
    finally:
        RES = keep
    return out_png


def colour_measures(body, colour):
    """The two colour numbers, off the UNLIT baked albedo.

    They used to come from a headless browser: render the model, read the pixels,
    count. Rendering was never what made them true — the baked colour IS the
    answer, and the z-buffer above already decides which surface each pixel sees.

    median_lum      how bright the creature's own colour is, 0-255 sRGB
    saturated_area  the share of it carrying a strong colour (HSV S >= 0.50)

    Unlit on purpose. Gradient, grain and AO are uniform multiplies, so they move
    a pixel's value but never its saturation; LIGHTS do move it — a white key
    washes colour out, a blue rim invents it. Measuring the lit render made the
    answer a property of the lighting rig, which nobody ships."""
    if not body.any():
        return {}
    lin = np.clip(colour[body], 0.0, 1.0)
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    d = np.clip(srgb * 255.0, 0, 255)
    lum = 0.2126 * d[:, 0] + 0.7152 * d[:, 1] + 0.0722 * d[:, 2]
    mx = d.max(axis=1)
    mn = d.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0.0)
    return {'median_lum': round(float(np.median(lum)), 1),
            'saturated_area': round(float((sat >= 0.50).mean()), 4)}


def exaggeration(mask):
    """The numbers that answer 'is this bold enough' — no reader required.

    Every one of these used to be a thing someone squinted at. They are all
    properties of a set of pixels, and the pixels are a projection of vertices,
    so they were always arithmetic."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return {}
    w = float(xs.max() - xs.min() + 1)
    h = float(ys.max() - ys.min() + 1)
    area = float(mask.sum())
    m = {
        'box_fill': round(area / (w * h), 3),         # spindly vs blobby
        'sq_fill': round(area / (max(w, h) ** 2), 3),  # volume in a 1:1 frame
        'extent': round(max(w, h) / min(w, h), 3),     # how far from square
    }
    try:
        from scipy import ndimage
        from scipy.spatial import ConvexHull
        pts = np.stack([xs, ys], axis=1).astype(float)
        if len(pts) >= 3:
            try:
                hull = ConvexHull(pts)
                # bites taken out of the outline: 1.0 = a blob, lower = real
                # negative space
                m['convexity'] = round(area / max(hull.volume, 1.0), 3)
            except Exception:
                pass
        half = mask[:, :mask.shape[1] // 2]
        other = np.fliplr(mask[:, mask.shape[1] - half.shape[1]:])
        m['mirror_sym'] = round(float((half == other).mean()), 3)
    except ImportError:
        pass
    return m


def iou(a, b):
    if a.shape != b.shape:
        return None
    u = int((a | b).sum())
    return round(int((a & b).sum()) / u, 4) if u else None


def thumb(mask, px, path):
    """Letterboxed, as the measure pass always was: the proportion the reader sees is
    the proportion the file records."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        Image.new('L', (px, px), 255).resize((240, 240), Image.NEAREST).save(path)
        return
    sub = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    im = Image.fromarray(np.where(sub, 0, 255).astype(np.uint8), 'L')
    W, H = im.size
    w = px if W >= H else max(1, round(px * W / H))
    h = px if H > W else max(1, round(px * H / W))
    box = Image.new('L', (px, px), 255)
    box.paste(im.resize((w, h), Image.LANCZOS), ((px - w) // 2, (px - h) // 2))
    box.resize((240, 240), Image.NEAREST).save(path)


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        return 2
    model, outdir = a[0], a[1]
    prev = a[a.index('--prev') + 1] if '--prev' in a else None
    hero_out = a[a.index('--hero') + 1] if '--hero' in a else None
    views = (a[a.index('--views') + 1].split(',') if '--views' in a
             else ['front', 'side', 'top', 'hero'])
    os.makedirs(outdir, exist_ok=True)

    if hero_out:
        hero_png(model, hero_out)
        print(f'hero: {hero_out}')
    V, F, MID, mats, C, basecol, _N = triangles_by_material(model, want_colour=True)
    boxes, whole = part_boxes(V, F, MID, mats)
    report = {'vertices': int(len(V)), 'triangles': int(len(F)),
              'materials': mats, 'stats': structure(model),
              'parts': boxes, 'whole': {'size': whole}, 'views': {}}
    thin_all = []
    for v in views:
        shares, mask, colour = material_shares(V, F, MID, mats, v, C, basecol)
        np.save(os.path.join(outdir, f'mask_{v}.npy'), mask)
        Image.fromarray(np.where(mask, 0, 255).astype(np.uint8), 'L').save(
            os.path.join(outdir, f'sil_{v}.png'))
        for px in (24, 48):
            thumb(mask, px, os.path.join(outdir, f'sil_{v}_thumb{px}.png'))
        mm = measures(mask)
        mm.update(exaggeration(mask))
        mm.update(colour_measures(mask, colour))
        mm['share'] = shares
        if mm.get('thinnest_px48') is not None:
            thin_all.append(mm['thinnest_px48'])
        if prev:
            p = os.path.join(prev, f'mask_{v}.npy')
            if os.path.exists(p):
                mm['iou_vs_prev'] = iou(mask, np.load(p))
        for name, sh in shares.items():
            if name in report['parts']:
                report['parts'][name].setdefault('share', {})[v] = sh
        report['views'][v] = mm

    if thin_all:
        report['thinnest_px48'] = min(thin_all)
    ious = [d['iou_vs_prev'] for d in report['views'].values()
            if d.get('iou_vs_prev') is not None]
    if ious:
        # the round moved as much as its most-changed view says it did
        report['iou_vs_prev'] = min(ious)

    mpath = os.path.join(outdir, 'metrics.json')
    merged = {}
    if os.path.exists(mpath):
        try:
            prevj = json.load(open(mpath, encoding='utf-8'))
            if isinstance(prevj, dict):
                merged = prevj
        except Exception:
            pass
    merged.update(report)
    json.dump(merged, open(mpath, 'w', encoding='utf-8'), indent=1)

    print(f"{report['triangles']} triangles, {len(views)} views, no browser")
    for v, d in report['views'].items():
        bits = [f"W/H {d.get('W_over_H')}"]
        if d.get('thinnest_px48') is not None:
            bits.append(f"thinnest {d['thinnest_px48']}px")
        if d.get('protrusions') is not None:
            bits.append(f"{d['protrusions']} protrusion(s)")
        if d.get('iou_vs_prev') is not None:
            bits.append(f"iou {d['iou_vs_prev']}")
        print(f'  {v:<6} ' + '  '.join(bits))
    return 0


if __name__ == '__main__':
    sys.exit(main())
