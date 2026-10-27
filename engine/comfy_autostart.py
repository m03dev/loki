"""Start this machine's ComfyUI when a 3D job needs it (owner 2026-10-26: "some of the models come out like garbage" -
on the PC ComfyUI was not running, so Forge fell all the way back to the silhouette "lift": a puffy blob).

    ensure(url, wait=150) -> {"ok", "started", "why"}

Only for a ComfyUI on THIS computer (127.0.0.1 / localhost) that LOKI installed (tools/setup_comfyui.py, under
harness_data/comfyui/): it is started hidden (no console window) with --lowvram on cards of 8 GB or less, then waited
for. A ComfyUI elsewhere (the PC seen from the Mac) is never started from here. LOKI_COMFY_AUTOSTART=0 turns it off.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def _setup():
    spec = importlib.util.spec_from_file_location("setup_comfyui", ROOT / "tools" / "setup_comfyui.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def comfy_root() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (ROOT / "harness_data")) / "comfyui"


def reachable(url: str, timeout: float = 2.0, opener=urllib.request.urlopen) -> bool:
    try:
        with opener(url.rstrip("/") + "/system_stats", timeout=timeout) as r:
            return getattr(r, "status", 200) == 200
    except Exception:  # noqa: BLE001
        return False


def vram_gb() -> float:
    try:
        import creative  # pylint: disable=import-outside-toplevel
        return float((creative.machine() or {}).get("vram_gb") or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _light() -> bool:
    try:
        import offload  # pylint: disable=import-outside-toplevel
        return offload.role() == "light"
    except Exception:  # noqa: BLE001
        return False


def ensure(url: str, wait: float = 150, opener=urllib.request.urlopen, starter=None, sleep=time.sleep,
           clock=time.time) -> dict:
    if reachable(url, opener=opener):
        return {"ok": True, "started": False}
    if os.environ.get("LOKI_COMFY_AUTOSTART", "1") == "0":
        return {"ok": False, "started": False, "why": "ComfyUI is not running (auto-start is off)"}
    host = (urlparse(url).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return {"ok": False, "started": False, "why": "ComfyUI at %s is not answering (it runs on another computer)" % url}
    root = comfy_root()
    if starter is None:
        if not (root / "ComfyUI" / "main.py").is_file():
            return {"ok": False, "started": False,
                    "why": "ComfyUI is not installed on this computer (python tools/setup_comfyui.py --install)"}
        if os.environ.get("LOKI_COMFY_AUTOSTART", "1") != "force" and _light():
            # the 16 GB Mac (2026-10-26: "you used all my vram"): 3D goes to the PC (engine/offload.py), never a local
            # ComfyUI with TRELLIS beside everything else. LOKI_COMFY_AUTOSTART=force starts it anyway.
            return {"ok": False, "started": False, "why": "ComfyUI is not started on this light machine - 3D runs on your PC "
                    "(LOKI_COMFY_AUTOSTART=force to start it here anyway)"}
        setup = _setup()
        low = 0 < vram_gb() <= 8.5

        def starter():
            argv_fn = setup.start_argv
            if low:                                    # 8 GB card: TRELLIS.2 / Pixal3D / Hunyuan only fit with offload
                setup.start_argv = lambda *a, **k: argv_fn(*a, **k) + ["--lowvram"]
            try:
                return setup.start(root, port=urlparse(url).port or 8188)
            finally:
                setup.start_argv = argv_fn
    try:
        starter()
    except SystemExit as exc:
        return {"ok": False, "started": False, "why": str(exc)}
    t_end = clock() + wait
    while clock() < t_end:
        if reachable(url, opener=opener):
            return {"ok": True, "started": True}
        sleep(3)
    return {"ok": False, "started": True, "why": "ComfyUI was started but did not answer in %ds (see %s)"
            % (wait, root / "comfyui.log")}
