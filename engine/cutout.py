"""Background removal with a licence-safe model, always named - never rembg's default.

rembg 2.0.86 made bria-rmbg (RMBG-2.0, BRIA licence: non-commercial without a paid agreement) its DEFAULT model; calling
rembg's remove without a session downloads and uses it. LOKI is AGPL and meant to be used commercially, so every cut-out names
its model: BiRefNet (MIT) first, then U^2-Net (Apache-2.0). Found in the 2026-10-26 open-source licence review.

    remove(img) -> RGBA PIL image, or None when rembg is not installed / no allowed model loads
"""
from __future__ import annotations

import os

ALLOWED = ("birefnet-general-lite", "birefnet-general", "u2net", "isnet-general-use")   # MIT / Apache-2.0 only
FORBIDDEN = ("bria-rmbg",)
_SESSION: dict = {}


def _session():
    if "s" in _SESSION:
        return _SESSION["s"]
    import rembg  # pylint: disable=import-outside-toplevel
    wanted = [m for m in [os.environ.get("LOKI_CUTOUT_MODEL", "").strip()] + list(ALLOWED) if m and m not in FORBIDDEN]
    for name in wanted:
        try:
            _SESSION["s"] = rembg.new_session(name)
            _SESSION["name"] = name
            return _SESSION["s"]
        except Exception:  # noqa: BLE001 - not downloadable here: the next allowed one
            continue
    _SESSION["s"] = None
    return None


def remove(img):
    try:
        import rembg  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    session = _session()
    if session is None:
        return None              # never fall back to rembg's default (bria-rmbg)
    try:
        return rembg.remove(img, session=session).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
