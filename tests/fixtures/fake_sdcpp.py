"""A stand-in for stable-diffusion.cpp's CLI in tests: reads -i (init), --mask, -o, -W/-H, --strength like sd.cpp and
writes a picture where the mask is white is repainted (a gold dome with a red plume) and the rest is the init image.
Proves the command line LOKI builds is the one sd.cpp reads; it is not a model."""
import sys
from PIL import Image, ImageDraw

a = sys.argv[1:]
get = lambda k: a[a.index(k) + 1]
init = Image.open(get("-i")).convert("RGB")
mask = Image.open(get("--mask")).convert("L")
w, h = int(get("-W")), int(get("-H"))
assert init.size == (w, h) == mask.size, (init.size, mask.size, w, h)
assert 0 < float(get("--strength")) < 1
paint = init.copy()
box = mask.getbbox()
d = ImageDraw.Draw(paint)
l, t, r, b = box
d.rectangle(box, fill=(30, 30, 40))
d.pieslice((l + (r - l) // 8, t + (b - t) // 4, r - (r - l) // 8, b + (b - t) // 2), 180, 360, fill=(230, 180, 40))
d.rectangle((l + (r - l) // 2 - 8, t + (b - t) // 8, l + (r - l) // 2 + 8, t + (b - t) // 2), fill=(200, 30, 30))
Image.composite(paint, init, mask).save(get("-o"))
