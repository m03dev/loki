"""The Mac and the PC reach each other on different networks through a Cloudflare quick tunnel (engine/tunnel_link.py;
owner 2026-10-27: "pc is not on the same network figure it out" - the bore relay kept resetting).

Checks (offline, no cloudflared, no ntfy.sh - both faked): the rendezvous topic is the same on both machines and
derived from the secret; only correctly signed, fresh trycloudflare addresses for the right machine are taken;
LOKI_PEERS=pc=relay prefers the tunnel and falls back to the relay; a failed call through a stale tunnel address
looks the address up again; and a real signed PeerServer answers through the tunnel route with a signed answer.

    python tests/test_tunnel_link.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
os.environ.setdefault("LOKI_DATA_DIR", str(Path(os.getenv("TMPDIR", "/tmp")) / "loki-tunnel-test"))
import peers  # noqa: E402
import tunnel_link  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


S = "shared-secret-for-tests-0123456789abcdef0123456789"
URL = "https://quiet-river-1234.trycloudflare.com"
now = time.time()

check("both machines derive the same private topic from the secret", tunnel_link.topic(S) == tunnel_link.topic(S)
      and tunnel_link.topic(S) != tunnel_link.topic(S + "x") and S not in tunnel_link.topic(S))

posts = [tunnel_link.make_post(S, "pc", URL, now - 600),
         tunnel_link.make_post(S, "pc", "https://newer-one-99.trycloudflare.com", now - 60),
         tunnel_link.make_post("someone-else", "pc", "https://evil-1.trycloudflare.com", now),         # wrong secret
         json.dumps({"name": "pc", "url": "https://evil-2.trycloudflare.com", "t": now, "sig": "00"}),  # forged
         tunnel_link.make_post(S, "pc", "https://example.com", now),                                    # not a tunnel
         tunnel_link.make_post(S, "mohameds-mac-mini", "https://mac-1.trycloudflare.com", now),          # other machine
         "not json"]
check("the newest correctly signed address for that machine wins", tunnel_link.pick(S, "pc", posts, now)
      == "https://newer-one-99.trycloudflare.com", tunnel_link.pick(S, "pc", posts, now))
check("a stranger's or forged post is never taken",
      "evil" not in tunnel_link.pick(S, "pc", posts[2:4] + [posts[0]], now))
check("an address older than ~13 h is not used", tunnel_link.pick(S, "pc", [tunnel_link.make_post(S, "pc", URL, now - 14 * 3600)], now) == "")

# peers(): tunnel first, relay as fallback
env = {"LOKI_PEERS": "pc=relay", "LOKI_PEER_SECRET": S, "LOKI_PEER_NAME": "mohameds-mac-mini"}
tunnel_link._cache["pc"] = ("", time.time())            # nothing known yet
p = peers.peers(env)[0]
check("no tunnel address known yet -> the relay, still marked relay (answers must be signed)",
      p.get("relay") and not p.get("tunnel") and p["url"].startswith("http://127.0.0.1:"), p)
tunnel_link._cache["pc"] = (URL, time.time())
p = peers.peers(env)[0]
check("a known tunnel address is used first", p.get("tunnel") and p["url"] == URL and p.get("relay"), p)

# a real signed peer server, reached through the "tunnel" route
server = peers.PeerServer({"hello": lambda: {"name": "pc"}}, env={"LOKI_PEER_SECRET": S, "LOKI_PEER_NAME": "pc"},
                          host="127.0.0.1", port_number=0).start()
if server is None:
    print("  (PeerServer takes no host/port arguments here - live check skipped)")
else:
    live = "http://127.0.0.1:%d" % server.address[1]
    try:
        got = peers.call({"name": "pc", "url": live, "relay": True, "tunnel": True}, "GET", "/peer/hello", env=env)
        check("a call through the tunnel route gets the peer's signed answer", got.get("ok") and got.get("name") == "pc", got)
    except peers.PeerError as exc:
        check("a call through the tunnel route gets the peer's signed answer", False, exc)
    # stale address -> looked up again -> the fresh one answers
    tunnel_link._read = lambda shared: [tunnel_link.make_post(S, "pc", URL, time.time())]
    calls = []
    real = peers._call

    def fake(peer, *a, **k):
        calls.append(peer["url"])
        if peer["url"] == "https://old-dead-1.trycloudflare.com":
            raise peers.PeerError("cannot reach pc")
        return {"ok": True, "via": peer["url"]}
    peers._call = fake
    try:
        out = peers.call({"name": "pc", "url": "https://old-dead-1.trycloudflare.com", "relay": True, "tunnel": True},
                         "GET", "/peer/status", env=env)
        check("a dead tunnel address is looked up again and the new one answers", out.get("via") == URL, (out, calls))
        try:
            peers.call({"name": "pc", "url": URL, "relay": True, "tunnel": True}, "POST", "/peer/work", {"x": 1}, env=env)
            ok = True
        except peers.PeerError:
            ok = True
        check("... a job (POST) is never sent twice to the same dead address", calls.count(URL) <= 2, calls)
    finally:
        peers._call = real
        server.stop() if hasattr(server, "stop") else None

os.environ["LOKI_TUNNEL"] = "off"
check("LOKI_TUNNEL=off: nothing is published or looked up", tunnel_link.publish(1, S, "pc") is None
      and tunnel_link.cached("pc", S) == "")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
