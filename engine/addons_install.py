"""Install the Python packages LOKI's add-ons need - from the app or the command line.

Most add-ons are plain pip packages LOKI can install into its own venv; a few are a command
you install yourself (their homepage is given instead). `plan()` says what an add-on needs,
`install()` runs only pip for that one add-on, by name, on the owner's click - never a shell
string, and never anything the owner did not ask for.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Callable

# add-on name -> the pip requirement(s) LOKI installs into harness_data/.venv
PIP: dict = {
    "browser-use": ["browser-use"],
    "crawl4ai": ["crawl4ai"],
    "headroom": ["headroom-ai"],
    "hindsight": ["hindsight-client"],
    "scrapling": ["scrapling"],
    "vision-track": ["trackers", "supervision", "rfdetr"],
    "media": ["yt-dlp[default]"],
    "mlx": ["mlx-lm"],
    "whisper": ["faster-whisper"],
}

# add-on name -> how to install what pip cannot (shown to the owner, not run)
MANUAL: dict = {
    "herdr": "Install herdr from https://herdr.dev",
    "hermes-agent": "Install hermes from https://hermes-agent.nousresearch.com",
    "agent-reach": "pipx install https://github.com/Panniantong/agent-reach/archive/main.zip",
    "skillspector": "Install SkillSpector from https://github.com/NVIDIA/SkillSpector",
    "cua": "Needs a virtual machine; see docs/ARCHITECTURE.md",
    "kyojin": "Needs an AMD Strix Halo machine (set KYOJIN_BASE_URL)",
}


def pip_specs(name: str) -> list:
    """The pip requirements for `name`, or [] when pip is not the way to install it."""
    return list(PIP.get(str(name or "").strip(), []))


def manual_hint(name: str) -> str:
    return MANUAL.get(str(name or "").strip(), "")


# Add-ons LOKI installs itself with downloads (engine/creative.py, session 28): local-image =
# stable-diffusion.cpp + Z-Image Turbo GGUF (PC) or mflux (Mac); local-video = Wan2GP (PC).
# They run in the background; Settings > Creations shows the progress.
STEPS_INSTALLERS = ("local-image", "local-video")


def plan(name: str) -> dict:
    """What installing `name` means: {"pip": [...], "manual": "..."} (one or both empty), plus
    {"steps", "installed"} for the download installers."""
    out = {"pip": pip_specs(name), "manual": manual_hint(name)}
    if str(name or "").strip() in STEPS_INSTALLERS:
        try:
            import creative  # pylint: disable=import-outside-toplevel
            steps = creative.install_plan(str(name).strip())
            out.update(steps=steps.get("steps", []), installed=bool(steps.get("installed")),
                       supported=bool(steps.get("supported")))
            if not steps.get("supported") and steps.get("why"):
                out["manual"] = steps["why"]
        except Exception as exc:  # noqa: BLE001
            out.update(steps=[], installed=False, supported=False, manual="%s: %s" % (type(exc).__name__, exc))
    return out


def installable(name: str) -> bool:
    return bool(pip_specs(name)) or str(name or "").strip() in STEPS_INSTALLERS


def install(name: str, python: str = "", run: Callable | None = None, timeout: float = 1800.0) -> dict:
    """pip-install this add-on's requirements into LOKI's venv. Returns {ok, specs, log, error}."""
    name = str(name or "").strip()
    if name in STEPS_INSTALLERS:
        import creative  # pylint: disable=import-outside-toplevel
        return creative.start_install(name)
    specs = pip_specs(name)
    if not specs:
        hint = manual_hint(name)
        return {"ok": False, "specs": [], "log": [],
                "error": ("%s is not a pip add-on. %s" % (name, hint)) if hint else
                         ("%s has nothing LOKI can install with pip." % (name or "That add-on"))}
    python = python or sys.executable
    argv = [python, "-m", "pip", "install", "--disable-pip-version-check", *specs]
    run = run or subprocess.run
    try:
        proc = run(argv, capture_output=True, text=True, timeout=timeout)   # no shell
    except Exception as exc:  # noqa: BLE001 - reported to the UI
        return {"ok": False, "specs": specs, "log": [], "error": str(exc)[:200]}
    ok = getattr(proc, "returncode", 1) == 0
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-4:]
    return {"ok": ok, "specs": specs, "log": tail,
            "error": "" if ok else "pip failed: " + (tail[-1] if tail else "no output")}
