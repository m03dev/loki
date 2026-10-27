"""Is a real online 3D generator reachable from this computer? (owner 2026-10-26: "that golem looks so bad its just a
blob" - every Mac model had been the silhouette 'lift' because the online TRELLIS Space failed.)

    python tools/check_online_3d.py                      list each Space's endpoints (engine/forge3d.online_spaces)
    python tools/check_online_3d.py --make images/x.png  ...and make a model from that picture with backend=online

Writes <workspace>/qa/online-3d.json (workspace: LOKI_WORKSPACE, else ~/LOKI Projects/Home) and prints it.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))


def endpoints(space: str) -> dict:
    try:
        from gradio_client import Client  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        return {"ok": False, "error": "gradio_client: %s" % exc}
    import forge3d  # pylint: disable=import-outside-toplevel
    t0 = time.time()
    try:
        client = forge3d.gradio_client_for(Client, space, os.environ.get("HF_TOKEN") or None)
        info = client.view_api(return_format="dict", print_info=False) or {}
        named = info.get("named_endpoints") or {}
        steps = forge3d.space_steps(client)
        return {"ok": True, "seconds": round(time.time() - t0, 1),
                "endpoints": {n: [p.get("parameter_name") or p.get("label") for p in (v.get("parameters") or [])]
                              for n, v in named.items()},
                "loki_would_call": [s[0] for s in steps]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "seconds": round(time.time() - t0, 1), "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}


def main(argv: list) -> int:
    import forge3d  # pylint: disable=import-outside-toplevel
    ws = Path(os.environ.get("LOKI_WORKSPACE") or (Path.home() / "LOKI Projects" / "Home"))
    out = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "platform": sys.platform, "spaces": {}}
    for space in forge3d.online_spaces():
        out["spaces"][space] = endpoints(space)
    if "--make" in argv:
        pic = Path(argv[argv.index("--make") + 1])
        pic = pic if pic.is_absolute() else ws / pic
        t0 = time.time()
        res = forge3d.make_3d(str(pic), ws / "models", backend="online")
        out["make"] = {"ok": res.get("ok"), "seconds": round(time.time() - t0, 1), "glb": res.get("glb", ""),
                       "backend": res.get("backend", ""), "error": res.get("error", ""),
                       "triangles": (res.get("meta") or {}).get("triangles", 0)}
    (ws / "qa").mkdir(parents=True, exist_ok=True)
    (ws / "qa" / "online-3d.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0 if (out.get("make") or {"ok": any(v.get("ok") for v in out["spaces"].values())}).get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
