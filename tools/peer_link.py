"""Link your machines' Loki from the command line (the app does the same in Settings > Machines).

On the machine that LISTENS (the PC with the GPU):
    python tools/peer_link.py pair --name pc
        turns listening on in harness_data/.env, creates the shared secret if there is none,
        and prints a LINK CODE. Restart Loki there so it starts listening.

On the machine that TALKS (the Mac):
    python tools/peer_link.py link <code>
        records the other machine and the shared secret, and makes it the trainer.

Anywhere:
    python tools/peer_link.py status      who is linked, and can each be reached right now
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))

import peers  # noqa: E402
from peer_link import write_env  # noqa: E402


def env_path() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return (Path(explicit) if explicit else REPO / "harness_data") / ".env"


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def cmd_pair(args) -> int:
    path = env_path()
    updates = {"LOKI_PEER_LISTEN": "1", "LOKI_PEER_PORT": str(args.port)}
    if args.name:
        updates["LOKI_PEER_NAME"] = args.name
    if not peers.secret():
        updates["LOKI_PEER_SECRET"] = peers.new_secret()
    write_env(path, updates)
    url = "http://%s:%d" % (args.address or peers.lan_address(), args.port)
    code = peers.make_link_code(peers.my_name(), url, peers.secret())
    print("Listening is on for %s at %s (saved in %s)." % (peers.my_name(), url, path))
    print()
    print("LINK CODE - paste it into Loki on your other machine (Settings > Machines):")
    print()
    print(code)
    print()
    print("Then:")
    print("  1. Restart Loki on this machine so it starts listening.")
    print("  2. If your firewall asks, allow Python on PRIVATE networks only.")
    print("  3. To let the other machine use this GPU for models too, run Ollama with")
    print("     OLLAMA_HOST=0.0.0.0 (Windows: setx OLLAMA_HOST 0.0.0.0, then restart Ollama).")
    return 0


def cmd_link(args) -> int:
    try:
        link = peers.parse_link_code(args.code)
    except ValueError as exc:
        print("Not linked: %s" % exc)
        return 2
    current = [p for p in peers.peers() if p["name"] != link["name"]]
    entries = ",".join("%s=%s" % (p["name"], p["url"]) for p in current + [link])
    updates = {"LOKI_PEERS": entries, "LOKI_PEER_SECRET": link["secret"]}
    if not args.no_trainer:
        updates["LOKI_TRAINER_PEER"] = link["name"]
    write_env(env_path(), updates)
    print("Linked %s at %s." % (link["name"], link["url"]))
    return cmd_status(args)


def cmd_status(_args) -> int:
    print("This machine: %s  (listening: %s)" % (peers.my_name(), "yes" if peers.listen_enabled() else "no"))
    linked = peers.status_all()
    if not linked:
        print("No linked machines.")
        return 0
    worst = 0
    for peer in linked:
        if peer["ok"]:
            hello = peer["hello"]
            gpu = (hello.get("machine") or {}).get("gpu") or {}
            print("  %-10s connected in %d ms - %s%s" % (peer["name"], peer["ms"],
                  (hello.get("machine") or {}).get("os", "?"), (", " + gpu["name"]) if gpu else ""))
        else:
            worst = 1
            print("  %-10s NOT reachable: %s" % (peer["name"], peer["error"]))
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair", help="listen here and print a link code")
    pair.add_argument("--name", default="")
    pair.add_argument("--port", type=int, default=peers.DEFAULT_PORT)
    pair.add_argument("--address", default="", help="the LAN address to put in the code (auto-detected)")
    link = sub.add_parser("link", help="link to a machine using its code")
    link.add_argument("code")
    link.add_argument("--no-trainer", action="store_true", help="do not send it verified work to train on")
    sub.add_parser("status", help="show linked machines")
    args = ap.parse_args(argv)
    load_env(env_path())
    return {"pair": cmd_pair, "link": cmd_link, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
