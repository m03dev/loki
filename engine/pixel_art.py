"""Real pixel art from any picture (owner 2026-10-25: "a pixel art ai tool"): the step that turns an AI picture - or a
photo, a render, a drawing - into clean game-ready pixels.

The core is a numpy + Pillow port of PixelOE's classic pipeline (github.com/KohakuBlueleaf/PixelOE, Apache-2.0,
Copyright Shih-Ying Yeh; licence in engine/licenses/PixelOE-Apache-2.0.txt): contrast-aware OUTLINE EXPANSION (thin
dark/bright details are widened before shrinking, so eyes, edges and outlines survive), colour matching back to the
original, then a per-patch DOWNSCALE (contrast: picks the darkest / brightest / middle pixel of each patch by its
contrast; center; median; k-centroid). PixelOE's own code needs torch + OpenCV; this port needs neither, so it runs in
LOKI's engine on the Mac and the PC with no install.

On top: a fixed PALETTE (pico-8, sweetie-16, endesga-32, gameboy, or any list of #hex colours) or K colours, optional
DITHERING (Floyd-Steinberg or a 4x4 Bayer pattern), and hard-edged transparency for sprites.

    pixelize(src, out=None, size=64, patch=0, outline=2, mode="contrast", colors=0, palette="", dither="none",
             scale=0) -> {"ok", "file", "preview", "width", "height", "colors"}
        size     the sprite's longer side in pixels (16 - 512)
        patch    source pixels per sprite pixel before the shrink (0 = from size: the picture is resized so each
                 sprite pixel is `patch` source pixels, PixelOE's patch_size)
        outline  outline expansion thickness (0 = off)
        scale    the preview's enlargement (0 = to about 512 px, nearest-neighbour)
"""
from __future__ import annotations

from pathlib import Path

PALETTES = {
    "pico-8": "000000 1D2B53 7E2553 008751 AB5236 5F574F C2C3C7 FFF1E8 FF004D FFA300 FFEC27 00E436 29ADFF 83769C FF77A8 FFCCAA",
    "sweetie-16": "1A1C2C 5D275D B13E53 EF7D57 FFCD75 A7F070 38B764 257179 29366F 3B5DC9 41A6F6 73EFF7 F4F4F4 94B0C2 566C86 333C57",
    "endesga-32": ("BE4A2F D77643 EAD4AA E4A672 B86F50 733E39 3E2731 A22633 E43B44 F77622 FEAE34 FEE761 63C74D 3E8948 265C42 "
                   "193C3E 124E89 0099DB 2CE8F5 FFFFFF C0CBDC 8B9BB4 5A6988 3A4466 262B44 181425 FF0044 68386C B55088 "
                   "F6757A E8B796 C28569"),
    "gameboy": "0F380F 306230 8BAC0F 9BBC0F",
    "grayscale-4": "000000 555555 AAAAAA FFFFFF",
}
MODES = ("contrast", "center", "median", "k-centroid", "nearest")
DITHERS = ("none", "floyd", "bayer")


class PixelError(ValueError):
    pass


def _np():
    import numpy as np  # pylint: disable=import-outside-toplevel
    return np


def parse_palette(palette) -> list:
    """'pico-8' | '#ff0044, 00e436 ...' | ['#ff0044', ...] -> [(r, g, b), ...]"""
    if not palette:
        return []
    if isinstance(palette, str):
        key = palette.strip().lower().replace(" ", "-").replace("_", "-")
        text = PALETTES.get(key) or PALETTES.get(key.replace("pico8", "pico-8")) or palette
        items = text.replace(",", " ").split()
    else:
        items = list(palette)
    out = []
    for it in items:
        h = str(it).strip().lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise PixelError("not a colour: %s" % it)
        try:
            out.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        except ValueError:
            raise PixelError("not a colour: %s" % it) from None
    if not 2 <= len(out) <= 256:
        raise PixelError("a palette has 2 to 256 colours")
    return out


# ----------------------------------------------------------------------------- PixelOE, ported (Apache-2.0)
# Its current pipeline (pixeloe/torch: outline.py, minmax.py, color.py, downscale/contrast_based.py) in numpy; images
# are float RGB 0..1, LAB in real units (L 0-100).
def lab_f(img):
    np = _np()
    c = np.where(img > 0.04045, ((img + 0.055) / 1.055) ** 2.4, img / 12.92)
    x = (0.4124564 * c[..., 0] + 0.3575761 * c[..., 1] + 0.1804375 * c[..., 2]) / 0.95047
    y = 0.2126729 * c[..., 0] + 0.7151522 * c[..., 1] + 0.0721750 * c[..., 2]
    z = (0.0193339 * c[..., 0] + 0.1191920 * c[..., 1] + 0.9503041 * c[..., 2]) / 1.08883
    f = lambda t: np.where(t > 0.008856, np.cbrt(np.maximum(t, 0)), 7.787 * t + 16 / 116)  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def rgb_f(lab):
    np = _np()
    fy = (lab[..., 0] + 16) / 116
    fx = lab[..., 1] / 500 + fy
    fz = fy - lab[..., 2] / 200
    g = lambda t: np.where(t > 0.206893, t ** 3, (t - 16 / 116) / 7.787)  # noqa: E731
    x, y, z = g(fx) * 0.95047, g(fy), g(fz) * 1.08883
    r = 3.2404542 * x - 1.5371385 * y - 0.4985314 * z
    gg = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z
    b = 0.0556434 * x - 0.2040259 * y + 1.0572252 * z
    c = np.clip(np.stack([r, gg, b], axis=-1), 0, 1)
    return np.clip(np.where(c > 0.0031308, 1.055 * c ** (1 / 2.4) - 0.055, 12.92 * c), 0, 1)


def _sigmoid(x):
    np = _np()
    return 1.0 / (1.0 + np.exp(-x))


def local_stat(data, kernel: int, stride: int, stat: str):
    """PixelOE's local_stat: the statistic of every kernel window (stride apart, zero-padded by kernel//2), each pixel
    the mean of the windows that cover it."""
    np = _np()
    h, w = data.shape
    pad = kernel // 2
    p = np.pad(data, pad)
    view = np.lib.stride_tricks.sliding_window_view(p, (kernel, kernel))[::stride, ::stride]
    lh, lw = view.shape[:2]
    if stat in ("max", "min") and kernel % stride == 0:
        # a window is m x m whole stride-blocks: reduce each block once, then the windows over the blocks
        m, red = kernel // stride, (np.max if stat == "max" else np.min)
        nb, nbw = lh - 1 + m, lw - 1 + m
        blocks = red(p[:nb * stride, :nbw * stride].reshape(nb, stride, nbw, stride), axis=(1, 3))
        vals = red(np.lib.stride_tricks.sliding_window_view(blocks, (m, m)), axis=(-1, -2))
    else:
        flat = view.reshape(lh, lw, -1)
        vals = {"median": lambda v: np.median(v, axis=-1), "max": lambda v: v.max(axis=-1),
                "min": lambda v: v.min(axis=-1)}[stat](flat)
    # every window adds its value over its kernel x kernel square: put each value at its square's corner and box-sum
    # the result with a summed-area table - the same sums as adding the squares one by one, without a Python loop
    H, W = lh * stride + kernel, lw * stride + kernel
    imp = np.zeros((H, W), dtype=np.float64)
    one = np.zeros((H, W), dtype=np.float64)
    imp[0:lh * stride:stride, 0:lw * stride:stride] = vals
    one[0:lh * stride:stride, 0:lw * stride:stride] = 1.0

    def box(a):
        c = np.zeros((H + 1, W + 1))
        c[1:, 1:] = a.cumsum(0).cumsum(1)
        y = np.arange(H)[:, None]
        x = np.arange(W)[None, :]
        y0, x0 = np.maximum(y - kernel + 1, 0), np.maximum(x - kernel + 1, 0)
        return c[y + 1, x + 1] - c[y0, x + 1] - c[y + 1, x0] + c[y0, x0]

    acc, cnt = box(imp), np.rint(box(one))
    return (acc[pad:pad + h, pad:pad + w] / (cnt[pad:pad + h, pad:pad + w] + 1e-8)).astype(np.float32)


def expansion_weight(img, k=16, stride=4, avg_scale=10, dist_scale=3):
    np = _np()
    lum = lab_f(img)[..., 0] / 100.0
    med = local_stat(lum, k * 2, stride, "median")
    lo = local_stat(lum, k, stride, "min")
    hi = local_stat(lum, k, stride, "max")
    weight = _sigmoid((med - 0.5) * avg_scale + ((med - lo) - (hi - med)) * dist_scale)
    return (weight - weight.min()) / (weight.max() - weight.min() + 1e-8)


def circle_kernel(r: float):
    np = _np()
    real, n = r, int(r)
    kern = np.zeros((2 * n + 1, 2 * n + 1), dtype=np.float32)
    offs = np.array([[-.5, -.5], [-.5, .5], [.5, -.5], [.5, .5], [0, .5], [0, -.5], [.5, 0], [-.5, 0]])
    for i in range(2 * n + 1):
        for j in range(2 * n + 1):
            dist = np.linalg.norm(np.array([i, j]) + offs - n, axis=1)
            if dist.max() <= real:
                kern[i, j] = 1
            elif dist.min() <= real:
                kern[i, j] = (real - dist.min()) / (dist.max() - dist.min())
    return kern


KERNELS = {1: (1,), 2: (1.5,), 3: (2, 1), 4: (2.5,), 5: (3, 1), 6: (3.5,)}


def kernel(n: int):
    spec = KERNELS[max(1, min(6, int(n)))]
    kern = circle_kernel(spec[0])
    return kern[spec[1]:-spec[1], spec[1]:-spec[1]] if len(spec) > 1 else kern


def _morph(img, op: str, kern, iterations: int = 1):
    """PixelOE's erode_cont / dilate_cont: a soft (weighted) min / max over a circular kernel (edges repeated)."""
    np = _np()
    kh, kw = kern.shape
    out = img
    for _ in range(max(0, int(iterations))):
        p = np.pad(out, ((kh // 2, kh // 2), (kw // 2, kw // 2), (0, 0)), mode="edge")
        h, w = out.shape[:2]
        best = None
        for dy in range(kh):
            for dx in range(kw):
                v = p[dy:dy + h, dx:dx + w] + ((kern[dy, dx] - 1) if op == "dilate" else (1 - kern[dy, dx]))
                best = v if best is None else (np.maximum(best, v) if op == "dilate" else np.minimum(best, v))
        out = np.clip(best, 0, 1) if op == "dilate" else best
    return out


def outline_expansion(img, erode=2, dilate=2, k=16):
    w = expansion_weight(img, k, max(1, k // 2))[..., None]
    e = _morph(img, "erode", kernel(erode))
    d = _morph(img, "dilate", kernel(dilate))
    out = e * w + d * (1.0 - w)
    oc = kernel(max(erode - 1, dilate - 1, 1))
    out = _morph(out, "erode", oc)
    out = _morph(out, "dilate", oc, 2)
    return _morph(out, "erode", oc)


def _blur(x, radius: int):
    """PixelOE's wavelet_blur: a (2r+1)^2 Gaussian with sigma r, reflected edges."""
    np = _np()
    t = np.arange(-radius, radius + 1, dtype=np.float32)
    k1 = np.exp(-(t ** 2) / (2.0 * radius * radius))
    k1 /= k1.sum()
    h, w = x.shape[:2]
    mode = "reflect" if h > radius and w > radius else "edge"
    p = np.pad(x, ((radius, radius), (0, 0), (0, 0)), mode=mode)
    x = sum(k1[i] * p[i:i + h] for i in range(2 * radius + 1))
    p = np.pad(x, ((0, 0), (radius, radius), (0, 0)), mode=mode)
    return sum(k1[i] * p[:, i:i + w] for i in range(2 * radius + 1))


def match_color(source, target, level: int = 5):
    """LAB mean / std to the target, then the target's low frequencies under the source's detail (wavelet colour fix)."""
    np = _np()
    s_lab, t_lab = lab_f(source), lab_f(target)
    res = (s_lab - s_lab.mean()) / (s_lab.std() + 1e-8) * t_lab.std() + t_lab.mean()
    src = rgb_f(res)
    level = max(1, min(level, int(np.log2(max(2, min(src.shape[:2]) - 1)))))
    high = np.zeros_like(src)
    x = src
    for i in range(1, level + 1):
        low = _blur(x, 2 ** i)
        high = high + (x - low)
        x = low
    tl = target
    for i in range(1, level + 1):
        tl = _blur(tl, 2 ** i)
    return np.clip(high + tl, 0, 1)


def _find_pixel(v):
    np = _np()
    mid = v[..., v.shape[-1] // 2]
    med = np.median(v, axis=-1)
    mu = v.mean(axis=-1)
    maxi, mini = v.max(axis=-1), v.min(axis=-1)
    out = mid.copy()
    lo = (med < mu) & (maxi - med > med - mini)
    hi = (med > mu) & (maxi - med < med - mini)
    out[lo] = mini[lo]
    out[hi] = maxi[hi]
    return out


def downscale(img, patch: int, mode: str = "contrast"):
    """(h, w, 3) float -> one pixel per patch x patch block: contrast (darkest / brightest / middle by the block's
    contrast, colour by median), center, median, k-centroid (the commonest of 2 colours), nearest."""
    np = _np()
    h, w = img.shape[:2]
    th, tw = h // patch, w // patch
    img = img[:th * patch, :tw * patch]
    blocks = lambda a: a.reshape(th, patch, tw, patch, -1).transpose(0, 2, 1, 3, 4).reshape(th, tw, patch * patch, -1)  # noqa: E731
    if mode == "nearest":
        return img[patch // 2::patch, patch // 2::patch][:th, :tw]
    if mode == "k-centroid":
        from PIL import Image  # pylint: disable=import-outside-toplevel
        u8 = (img * 255 + 0.5).astype(np.uint8)
        out = np.zeros((th, tw, 3), dtype=np.float32)
        for yy in range(th):
            for xx in range(tw):
                tile = Image.fromarray(u8[yy * patch:(yy + 1) * patch, xx * patch:(xx + 1) * patch])
                q = tile.quantize(colors=2, method=Image.Quantize.MEDIANCUT, kmeans=2).convert("RGB")
                out[yy, xx] = np.array(max(q.getcolors(1 << 16), key=lambda c: c[0])[1]) / 255.0
        return out
    lab = blocks(lab_f(img))
    if mode == "center":
        first = lab[..., lab.shape[2] // 2, 0]
    elif mode == "median":
        first = np.median(lab[..., 0], axis=-1)
    else:
        first = _find_pixel(lab[..., 0])
    return rgb_f(np.stack([first, np.median(lab[..., 1], axis=-1), np.median(lab[..., 2], axis=-1)], axis=-1))


# ----------------------------------------------------------------------------- palette + dithering
BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def quantize(rgb, colors: int = 0, palette=None, dither: str = "none"):
    """Down to `colors` (k-means) or onto `palette`; dithering none | floyd | bayer."""
    np = _np()
    from PIL import Image  # pylint: disable=import-outside-toplevel
    img = Image.fromarray(rgb)
    if palette:
        if dither == "floyd":
            pal = Image.new("P", (1, 1))
            flat = [c for rgbt in palette for c in rgbt]
            pal.putpalette(flat + flat[-3:] * (256 - len(palette)))
            return np.asarray(img.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB"))
        src = rgb.astype(np.float32)
        if dither == "bayer":                     # ordered dither: a small, even pattern offset before the match
            h, w = rgb.shape[:2]
            m = (np.array(BAYER4, dtype=np.float32) + 0.5) / 16.0 - 0.5
            spread = 96.0 / max(2.0, len(palette) ** (1 / 3))
            src = np.clip(src + np.tile(m, (h // 4 + 1, w // 4 + 1))[:h, :w, None] * spread, 0, 255)
        pal_arr = np.array(palette, dtype=np.uint8)
        pal_lab = lab_f(pal_arr[None] / 255.0)[0]                  # nearest colour by how it LOOKS (LAB), not RGB
        lab = lab_f(src / 255.0).reshape(-1, 1, 3)
        idx = ((lab - pal_lab[None]) ** 2).sum(axis=-1).argmin(axis=1)
        return pal_arr[idx].reshape(rgb.shape)
    if colors:
        q = img.quantize(colors=max(2, min(256, int(colors))), method=Image.Quantize.MEDIANCUT,
                         kmeans=max(2, min(256, int(colors))),
                         dither=Image.Dither.FLOYDSTEINBERG if dither == "floyd" else Image.Dither.NONE)
        return np.asarray(q.convert("RGB"))
    return rgb


# ----------------------------------------------------------------------------- the whole thing
def pixelize(src, out=None, size: int = 64, patch: int = 0, outline: int = 2, mode: str = "contrast",
             colors: int = 0, palette="", dither: str = "none", scale: int = 0, keep_alpha: bool = True) -> dict:
    np = _np()
    from PIL import Image  # pylint: disable=import-outside-toplevel
    src = Path(src)
    if not src.is_file():
        raise PixelError("no picture at %s" % src)
    if mode not in MODES:
        raise PixelError("mode is one of " + ", ".join(MODES))
    if dither not in DITHERS:
        raise PixelError("dither is none, floyd or bayer")
    pal = parse_palette(palette)
    with Image.open(src) as im:
        im.load()
        rgba = im.convert("RGBA")
    size = max(8, min(512, int(size or 64)))
    w0, h0 = rgba.size
    tw, th = (size, max(1, round(size * h0 / w0))) if w0 >= h0 else (max(1, round(size * w0 / h0)), size)
    patch = max(2, min(32, int(patch or max(4, min(8, 512 // size)))))
    patch += patch % 2                                         # even: the weight's windows are patch/2 apart
    outline = max(0, min(int(outline or 0), 6, patch // 2))
    work = rgba.resize((tw * patch, th * patch), Image.LANCZOS)
    arr = np.asarray(work)
    rgb, alpha = arr[..., :3].copy(), arr[..., 3]
    if alpha.min() < 250:                       # transparent sprite: flatten on its own mean colour, not black
        solid = alpha > 127
        if solid.any():
            rgb[~solid] = rgb[solid].mean(axis=0).astype(np.uint8)
    img = rgb.astype(np.float32) / 255.0
    if outline:
        img = match_color(outline_expansion(img, int(outline), int(outline), patch), rgb.astype(np.float32) / 255.0)
    small = (downscale(img, patch, mode) * 255.0 + 0.5).astype(np.uint8)
    small = quantize(small, int(colors or 0), pal, dither)
    out_img = Image.fromarray(small.astype(np.uint8)).convert("RGBA")
    if keep_alpha and alpha.min() < 250:
        a_small = alpha.reshape(th, patch, tw, patch).mean(axis=(1, 3))
        out_img.putalpha(Image.fromarray(np.where(a_small > 127, 255, 0).astype(np.uint8)))
    dest = Path(out) if out else src.with_name("%s-pixel%d.png" % (src.stem, size))
    dest.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(dest)
    k = int(scale or max(1, 512 // max(tw, th)))
    preview = dest.with_name(dest.stem + "-x%d.png" % k)
    out_img.resize((tw * k, th * k), Image.NEAREST).save(preview)
    used = len(out_img.convert("RGB").getcolors(1 << 16) or [])
    return {"ok": True, "file": str(dest), "preview": str(preview), "width": tw, "height": th, "colors": used,
            "palette": palette if isinstance(palette, str) else ("custom" if pal else ""), "mode": mode}
