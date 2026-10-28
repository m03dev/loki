"""Phone testing for LOKI's agents: mobile-mcp (github.com/mobile-next/mobile-mcp, Apache-2.0) drives iOS simulators,
Android emulators and real phones (owner 2026-10-28: "add mobile next mcp server for testing and stuff").

engine/mcp_servers.json "mobile" starts `npx -y @mobilenext/mobile-mcp@1.0.14` (telemetry off) only when this machine
can reach a device (devices_ready below) - so its 33 tool schemas are never paid for on a machine with nothing to
test. The tools: mobile_list_available_devices, mobile_install_app, mobile_launch_app, mobile_list_elements_on_screen,
mobile_click_on_screen_at_coordinates, mobile_type_keys, mobile_swipe_on_screen, mobile_press_button, mobile_open_url,
mobile_save_screenshot, mobile_get_device_logs ... The playbook is skills/playbooks/mobile-test/PLAYBOOK.md.

Screenshots are of the PHONE or the emulator only - never of the owner's computer (owner's rule 9).
LOKI's own phone app: id dev.m03.loki on iOS and Android, links loki://.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "dev.m03.loki"
PIN = "1.0.14"


def adb() -> str:
    found = shutil.which("adb")
    if found:
        return found
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    for base in ([home] if home else []) + [str(Path.home() / "Library" / "Android" / "sdk"),
                                             str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk")]:
        p = Path(base) / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")
        if base and p.is_file():
            return str(p)
    return ""


def _out(cmd: list, timeout: int = 8, runner=subprocess.run) -> str:
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
        return proc.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def devices(runner=subprocess.run) -> list:
    """What can be tested right now: booted iOS simulators, Android emulators and phones adb sees."""
    out = []
    if sys.platform == "darwin" and shutil.which("xcrun"):
        for line in _out(["xcrun", "simctl", "list", "devices", "booted"], runner=runner).splitlines():
            line = line.strip()
            if "(Booted)" in line:
                out.append({"platform": "ios", "kind": "simulator", "name": line.split(" (")[0]})
    a = adb()
    if a:
        for line in _out([a, "devices"], runner=runner).splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                out.append({"platform": "android", "kind": "emulator" if parts[0].startswith("emulator-") else "phone",
                            "name": parts[0]})
    return out


def devices_ready() -> bool:
    """engine/mcp_servers.json's requires_check: start mobile-mcp only when there is something to test.
    LOKI_MOBILE_MCP=on starts it anyway (a device you will boot later)."""
    if str(os.environ.get("LOKI_MOBILE_MCP", "")).lower() in ("on", "1", "yes"):
        return True
    return bool(devices())


def status() -> dict:
    return {"ok": True, "devices": devices(), "adb": bool(adb()),
            "xcode": sys.platform == "darwin" and bool(shutil.which("xcrun")), "npx": bool(shutil.which("npx")),
            "app_id": APP_ID, "server": "@mobilenext/mobile-mcp@%s" % PIN}
