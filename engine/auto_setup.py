"""LOKI installs what it needs by itself, in the background (owner, 2026-10-17: "get loki to start
downloading and installing packages it needs").

Until now an add-on was only installed when the owner pressed Install on that one card. This
works through a list on its own, one add-on at a time, after the window is up, never during a
request that is running, and shows its progress in Settings > Add-ons:

  recommended  light, broadly useful add-ons that fit this machine (documents, data, OCR,
               media download, background removal, a real Chromium, speech-to-text, CADCraft,
               MLX on an Apple-silicon Mac) - the default
  everything   all of that plus the big ones that fit this machine: the local picture maker
               (several GB of weights), the local video maker on an NVIDIA PC
  off          nothing on its own (the Install buttons still work)

LOKI_AUTO_SETUP=recommended|everything|off (Settings > General). Installing a package never
turns an add-on ON: what an add-on may do still needs the owner's OK in Settings > Add-ons.
Every step goes through addons_install / cad (pip or a checksum-checked download, no shell).
An add-on that failed is retried on a later start (not in a loop); what is done is remembered
in <data>/auto_setup.json.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Callable

LIGHT = ["documents", "data-analysis", "ocr", "media", "rembg", "chromium", "whisper"]
RETRY_AFTER_S = 6 * 3600
STATE: dict = {"running": False, "level": "", "current": "", "done": [], "failed": {}, "skipped": {},
               "queue": [], "started": 0.0, "finished": 0.0}
_lock = threading.RLock()
_thread: threading.Thread | None = None


def level(env: dict | None = None) -> str:
    value = str((env if env is not None else os.environ).get("LOKI_AUTO_SETUP", "recommended")).strip().lower()
    return value if value in ("recommended", "everything", "off") else "recommended"


def _apple_silicon() -> bool:
    import platform  # pylint: disable=import-outside-toplevel
    return sys.platform == "darwin" and platform.machine() == "arm64"


def _nvidia() -> bool:
    return bool(shutil.which("nvidia-smi"))


def wanted(which: str, apple_silicon: bool | None = None, nvidia: bool | None = None) -> list:
    """The add-ons to install at this level on this machine, in order."""
    if which == "off":
        return []
    apple = _apple_silicon() if apple_silicon is None else apple_silicon
    gpu = _nvidia() if nvidia is None else nvidia
    out = list(LIGHT) + ["cadcraft"]
    if apple:
        out.append("mlx")
    if which == "everything":
        out.append("local-image")              # stable-diffusion.cpp + Z-Image (PC) / mflux (Mac)
        if gpu:
            out.append("local-video")          # Wan2GP, NVIDIA only
    return out


def _state_file(data_dir: Path) -> Path:
    return Path(data_dir) / "auto_setup.json"


def _load(data_dir: Path) -> dict:
    try:
        return json.loads(_state_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data_dir: Path, record: dict) -> None:
    try:
        _state_file(data_dir).write_text(json.dumps(record, indent=1), encoding="utf-8")
    except OSError:
        pass


def is_installed(name: str) -> bool:
    """Whether an add-on's packages are already here (no network)."""
    import importlib.util  # pylint: disable=import-outside-toplevel
    if name == "cadcraft":
        import cad  # pylint: disable=import-outside-toplevel
        return bool(cad.cli_path())
    import addons_install  # pylint: disable=import-outside-toplevel
    if name in addons_install.STEPS_INSTALLERS:
        return bool(addons_install.plan(name).get("installed"))
    specs = addons_install.pip_specs(name)
    if not specs:
        return True
    modules = {"yt-dlp[default]": "yt_dlp", "rembg[cpu]": "rembg", "faster-whisper": "faster_whisper",
               "pypdfium2": "pypdfium2", "pdfplumber": "pdfplumber", "markitdown": "markitdown", "rapidocr": "rapidocr",
               "onnxruntime": "onnxruntime", "pandas": "pandas", "matplotlib": "matplotlib", "duckdb": "duckdb",
               "pyarrow": "pyarrow", "playwright": "playwright", "mlx-lm": "mlx_lm"}
    return all(importlib.util.find_spec(modules.get(s, s.split("[")[0].replace("-", "_"))) is not None for s in specs)


def _install_one(name: str) -> dict:
    if name == "cadcraft":
        import cad  # pylint: disable=import-outside-toplevel
        return cad.install(say=lambda *_: None)
    import addons_install  # pylint: disable=import-outside-toplevel
    return addons_install.install(name)


def run(data_dir: Path, which: str = "", busy: Callable[[], bool] = lambda: False,
        install: Callable[[str], dict] = _install_one, installed: Callable[[str], bool] = is_installed,
        sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time) -> dict:
    """Install every wanted add-on that is missing, one at a time. Returns STATE."""
    which = which or level()
    record = _load(data_dir)
    failed_at = record.get("failed", {})
    queue = []
    skipped = {}
    for name in wanted(which):
        if installed(name):
            continue
        last = failed_at.get(name, {}).get("t", 0)
        if last and now() - last < RETRY_AFTER_S:
            skipped[name] = "failed recently: " + str(failed_at[name].get("error", ""))[:120]
            continue
        queue.append(name)
    with _lock:
        STATE.update(running=bool(queue), level=which, current="", done=[], failed={}, skipped=skipped,
                     queue=list(queue), started=now(), finished=0.0)
    for name in queue:
        waited = 0.0
        while busy() and waited < 1800:        # never compete with a request the owner is waiting on
            sleep(5.0)
            waited += 5.0
        with _lock:
            STATE["current"] = name
        try:
            result = install(name)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        with _lock:
            STATE["queue"] = [q for q in STATE["queue"] if q != name]
            if result.get("ok") or result.get("started"):
                STATE["done"].append(name)
                failed_at.pop(name, None)
            else:
                STATE["failed"][name] = str(result.get("error", "failed"))[:200]
                failed_at[name] = {"t": now(), "error": STATE["failed"][name]}
    record.update(failed=failed_at, last_run=now(), level=which)
    _save(data_dir, record)
    with _lock:
        STATE.update(running=False, current="", finished=now())
        return dict(STATE)


def start(data_dir: Path, which: str = "", busy: Callable[[], bool] = lambda: False, delay_s: float = 45.0) -> dict:
    """Run in the background (once at a time). `delay_s` lets the window finish opening first."""
    global _thread
    which = which or level()
    if which == "off":
        return {"ok": False, "error": "LOKI_AUTO_SETUP is off"}
    with _lock:
        if _thread is not None and _thread.is_alive():
            return {"ok": True, "already": True, **status()}

        def go():
            time.sleep(delay_s)
            run(Path(data_dir), which, busy=busy)
        _thread = threading.Thread(target=go, daemon=True, name="loki-auto-setup")
        _thread.start()
    return {"ok": True, "level": which, "wanted": wanted(which)}


def status() -> dict:
    with _lock:
        snap = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in STATE.items()}
    snap["setting"] = level()
    return snap
