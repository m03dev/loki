"""Image settings: ONE list of every knob a picture can be made with, which backends honour it, and how a request is
checked against it (owner 2026-10-26: "images should be very technical lots of settings to adjust what size and pixel
we want in an image everything should be modular").

    SETTINGS              [{key, label, what, type, group, default, min/max/step | options, honoured}] - the viewer's
                          Settings panel draws itself from this list (GET /image/settings), so a new knob is one row here
    normalize(raw, backend) -> (job, notes)   clean values for runners/imagegen.py; notes say what was clamped or what
                          this backend ignores (FLUX-family Turbo models ignore CFG / negative, hosted APIs ignore samplers)
    size_for(aspect, megapixels) -> (w, h)    multiples of 16, the size most models were trained around
    caps(backend)         which keys a backend honours

Ideas from Fooocus (GPL-3.0: aspect buckets, styles), InvokeAI (Apache-2.0: per-model defaults), Draw Things and
SwarmUI (seed lock, variation strength). No code taken.
"""
from __future__ import annotations

ASPECTS = {"1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4), "3:2": (3, 2), "2:3": (2, 3), "16:9": (16, 9),
           "9:16": (9, 16), "21:9": (21, 9), "4:5": (4, 5)}
BACKENDS = ("auto", "sdcpp", "mflux", "zimage", "qwen", "nvidia", "huggingface")
SAMPLERS = ("euler", "euler_a", "heun", "dpm2", "dpm++2s_a", "dpm++2m", "dpm++2mv2", "ipndm", "lcm")
ALL = set(BACKENDS)
LOCAL = {"sdcpp", "mflux", "auto"}

SETTINGS = [
    {"key": "aspect", "label": "Aspect", "group": "Size", "type": "enum", "options": list(ASPECTS), "default": "1:1",
     "what": "Shape of the picture; width and height follow from it and the megapixels", "honoured": sorted(ALL)},
    {"key": "megapixels", "label": "Megapixels", "group": "Size", "type": "float", "min": 0.25, "max": 2.0, "step": 0.05,
     "default": 1.0, "what": "Picture size in millions of pixels (1.0 = 1024x1024). Models are trained near 1.0",
     "honoured": sorted(ALL)},
    {"key": "width", "label": "Width (px)", "group": "Size", "type": "int", "min": 256, "max": 2048, "step": 16,
     "default": 1024, "what": "Exact width in pixels (a multiple of 16); overrides aspect + megapixels",
     "honoured": sorted(ALL)},
    {"key": "height", "label": "Height (px)", "group": "Size", "type": "int", "min": 256, "max": 2048, "step": 16,
     "default": 1024, "what": "Exact height in pixels (a multiple of 16)", "honoured": sorted(ALL)},
    {"key": "steps", "label": "Steps", "group": "Quality", "type": "int", "min": 1, "max": 60, "step": 1, "default": 0,
     "what": "Denoising steps; 0 = the model's own default (Turbo / klein: 4-9, others ~28). More = slower, finer",
     "honoured": ["sdcpp", "mflux", "nvidia", "auto"]},
    {"key": "guidance", "label": "Guidance (CFG)", "group": "Quality", "type": "float", "min": 0.0, "max": 20.0,
     "step": 0.5, "default": 0.0, "what": "How strictly the prompt is followed; 0 = the model's default. Turbo / "
     "distilled models want ~1 and ignore the negative prompt below 1", "honoured": ["sdcpp", "mflux", "auto"]},
    {"key": "sampler", "label": "Sampler", "group": "Quality", "type": "enum", "options": [""] + list(SAMPLERS),
     "default": "", "what": "The solver (stable-diffusion.cpp only); empty = its default", "honoured": ["sdcpp"]},
    {"key": "seed", "label": "Seed", "group": "Variation", "type": "int", "min": 0, "max": 2**31 - 1, "step": 1,
     "default": 0, "what": "Same seed + same settings = the same picture; 0 = a new random one",
     "honoured": sorted(ALL)},
    {"key": "count", "label": "Pictures", "group": "Variation", "type": "int", "min": 1, "max": 4, "step": 1, "default": 1,
     "what": "How many to make (seeds seed, seed+1, ...)", "honoured": sorted(ALL)},
    {"key": "strength", "label": "Change amount", "group": "Variation", "type": "float", "min": 0.05, "max": 1.0,
     "step": 0.05, "default": 0.6, "what": "When remaking FROM this picture: 0.1 keeps almost everything, 1.0 redraws "
     "freely", "honoured": ["sdcpp", "mflux", "nvidia", "auto"]},
    {"key": "from_picture", "label": "Start from this picture", "group": "Variation", "type": "bool", "default": False,
     "what": "Use the picture as the starting point (image-to-image / reference edit) instead of drawing from text only",
     "honoured": ["sdcpp", "mflux", "nvidia", "auto"]},
    {"key": "style", "label": "Style", "group": "Look", "type": "enum", "options": [], "default": "",
     "what": "LOKI's art direction presets (engine/art_direction.py)", "honoured": sorted(ALL)},
    {"key": "negative", "label": "Avoid", "group": "Look", "type": "text", "default": "",
     "what": "What must not be in the picture (models with guidance <= 1 ignore it)",
     "honoured": ["sdcpp", "zimage", "huggingface", "auto"]},
    {"key": "upscale", "label": "Upscale", "group": "Output", "type": "enum", "options": [1, 2, 4], "default": 1,
     "what": "Real-ESRGAN x2 / x4 after the picture is made", "honoured": sorted(ALL)},
    {"key": "pixel_size", "label": "Pixel art size", "group": "Output", "type": "int", "min": 0, "max": 256, "step": 8,
     "default": 0, "what": "Also make a pixel-art sprite this many pixels tall; 0 = no", "honoured": sorted(ALL)},
    {"key": "palette", "label": "Pixel palette", "group": "Output", "type": "enum",
     "options": ["", "pico-8", "endesga-32", "gameboy", "nes"], "default": "",
     "what": "Colour palette for the pixel-art sprite", "honoured": sorted(ALL)},
    {"key": "backend", "label": "Model", "group": "Engine", "type": "enum", "options": list(BACKENDS), "default": "auto",
     "what": "Which image engine: auto = this computer's own first, then the hosted ones", "honoured": sorted(ALL)},
]
BY_KEY = {s["key"]: s for s in SETTINGS}
JOB_KEYS = ("width", "height", "seed", "count", "negative", "backend", "steps", "guidance", "sampler", "strength",
            "reference", "style", "upscale", "pixel_size", "palette")


def schema() -> list:
    """SETTINGS with the live style list filled in."""
    out = [dict(s) for s in SETTINGS]
    try:
        import art_direction  # pylint: disable=import-outside-toplevel
        BY = {s["key"]: s for s in out}
        BY["style"]["options"] = [""] + sorted(art_direction.STYLES)
    except Exception:  # noqa: BLE001
        pass
    return out


def size_for(aspect: str = "1:1", megapixels: float = 1.0) -> tuple:
    a, b = ASPECTS.get(str(aspect), (1, 1))
    mp = max(0.25, min(2.0, float(megapixels or 1.0))) * 1024 * 1024
    w = (mp * a / b) ** 0.5
    h = w * b / a
    snap = lambda v: max(256, min(2048, int(round(v / 16.0)) * 16))  # noqa: E731
    return snap(w), snap(h)


def caps(backend: str) -> set:
    backend = str(backend or "auto")
    return {s["key"] for s in SETTINGS if backend in s["honoured"]}


def _num(spec, value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return spec["default"], "%s: %r is not a number - %s used" % (spec["label"], value, spec["default"])
    lo, hi = spec.get("min"), spec.get("max")
    note = ""
    if lo is not None and v < lo:
        v, note = lo, "%s raised to %s" % (spec["label"], lo)
    if hi is not None and v > hi:
        v, note = hi, "%s lowered to %s" % (spec["label"], hi)
    if spec["type"] == "int":
        step = int(spec.get("step") or 1)
        v = int(round(v / step) * step) if step > 1 else int(round(v))
    return v, note


def normalize(raw: dict, backend: str = "auto") -> tuple:
    """(job fields for runners/imagegen.py, notes). Unknown keys are dropped; numbers are clamped; a size comes from
    width/height when given, else aspect + megapixels; keys this backend does not honour are kept out and named."""
    raw = dict(raw or {})
    backend = str(raw.get("backend") or backend or "auto")
    if backend not in BACKENDS:
        backend = "auto"
    notes, job = [], {"backend": backend}
    if raw.get("width") or raw.get("height"):
        for k in ("width", "height"):
            v, n = _num(BY_KEY[k], raw.get(k) or 1024)
            job[k] = v
            notes += [n] if n else []
    else:
        job["width"], job["height"] = size_for(raw.get("aspect") or "1:1", raw.get("megapixels") or 1.0)
    for k in ("steps", "guidance", "seed", "count", "strength", "pixel_size"):
        if raw.get(k) in (None, ""):
            continue
        v, n = _num(BY_KEY[k], raw[k])
        notes += [n] if n else []
        if v or k in ("seed",):
            job[k] = v
    for k in ("sampler", "palette", "style", "negative"):
        v = str(raw.get(k) or "").strip()
        if not v:
            continue
        opts = BY_KEY[k].get("options")
        if k == "style":
            opts = schema()[[s["key"] for s in SETTINGS].index("style")]["options"]
        if opts and v not in opts:
            notes.append("%s %r is not one of %s" % (BY_KEY[k]["label"], v, ", ".join(map(str, opts[1:9]))))
            continue
        job[k] = v[:600]
    if raw.get("upscale") not in (None, "", 1, "1"):
        job["upscale"] = 4 if str(raw["upscale"]) == "4" else 2
    have = caps(backend)
    ignored = [BY_KEY[k]["label"] for k in list(job) if k in BY_KEY and k not in have and k != "backend"]
    for k in [k for k in list(job) if k in BY_KEY and k not in have and k != "backend"]:
        job.pop(k)
    if ignored:
        notes.append("%s ignores: %s" % (backend, ", ".join(ignored)))
    return job, notes
