"""Hunyuan3D 2.1 for Forge - OWNER-INSTALLED (engine/forge_hunyuan.py). Nothing happens before the licence is accepted.

    python tools/setup_hunyuan3d.py                      the licence summary + what is ready / missing
    python tools/setup_hunyuan3d.py accept               record that the owner accepted it (LOKI_HUNYUAN_ACCEPTED=1)
    python tools/setup_hunyuan3d.py models [--comfy DIR] download the 2.1 checkpoint into ComfyUI (the PC; ~7 GB)
    python tools/setup_hunyuan3d.py server <clone dir>   use Tencent's own api_server.py instead of ComfyUI
                                                         (LOKI_HUNYUAN_MODE=server; start it yourself:
                                                          python api_server.py --port 8081 --enable_flashvdm)

The licence (read it in full: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE) is not open
source: it does not apply in the EU, the UK or South Korea; above 1M monthly users you need Tencent's permission; its
output must not be used to improve any other AI model (LOKI keeps Hunyuan models out of its own training); a product
built with it must say Tencent does not endorse it. That is why it is never part of LOKI itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import forge_hunyuan  # noqa: E402  pylint: disable=wrong-import-position

SUMMARY = __doc__.split("The licence", 1)[1].strip()


def env_path() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (ROOT / "harness_data")) / ".env"


def set_env(updates: dict, path: Path | None = None) -> Path:
    path = path or env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in updates]
    lines += ["%s=%s" % (k, v) for k, v in updates.items() if v is not None]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in updates.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    return path


def _arg(argv: list, name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def main(argv: list) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "accept":
        p = set_env({"LOKI_HUNYUAN_ACCEPTED": "1", "LOKI_HUNYUAN_MODE": os.environ.get("LOKI_HUNYUAN_MODE") or "comfy"})
        print("Accepted the Tencent Hunyuan 3D 2.1 Community License for this machine (%s).\n%s" % (p, SUMMARY))
        return 0
    if cmd == "models":
        def say(msg, frac=None):
            print("\r%s %s" % (msg, "" if frac is None else "%3d%%" % int(frac * 100)), end="", flush=True)
        try:
            res = forge_hunyuan.install_models(_arg(argv, "--comfy"), progress=say)
        except Exception as exc:  # noqa: BLE001
            print("\n%s" % exc)
            return 1
        print("\ninstalled: %s\nalready there: %s\ninto: %s" % (", ".join(res["installed"]) or "-",
                                                             ", ".join(res["already"]) or "-", res["comfy_dir"]))
        return 0
    if cmd == "server":
        if not forge_hunyuan.accepted():
            print("Accept the licence first: python tools/setup_hunyuan3d.py accept")
            return 1
        clone = Path(argv[1]) if len(argv) > 1 else None
        if not clone or not (clone / "api_server.py").is_file():
            print("Give the folder of your Hunyuan3D-2.1 clone (the one with api_server.py).")
            return 1
        set_env({"LOKI_HUNYUAN_MODE": "server", "LOKI_HUNYUAN_DIR": str(clone),
                 "LOKI_HUNYUAN_URL": os.environ.get("LOKI_HUNYUAN_URL") or forge_hunyuan.DEFAULT_URL})
        print("LOKI will use the server at %s - start it in %s:\n  python api_server.py --port 8081 --enable_flashvdm"
              % (forge_hunyuan.url(), clone))
        return 0
    print("Hunyuan3D 2.1 for Forge\n\nThe licence %s\n" % SUMMARY)
    print("accepted on this machine:", forge_hunyuan.accepted())
    print("route:", forge_hunyuan.mode())
    reason = forge_hunyuan.why_not()
    print("ready:", not reason, ("- " + reason) if reason else "")
    if not forge_hunyuan.accepted():
        print("\nTo use it: python tools/setup_hunyuan3d.py accept, then: python tools/setup_hunyuan3d.py models")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
