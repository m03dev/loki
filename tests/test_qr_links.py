"""Every QR code in LOKI leads somewhere that works (the owner: "all the QR codes go to an IP address").

    python tests/test_qr_links.py      (< 10 s, no network)

The QRs: a provider's key page (public https), OpenRouter / device sign-in (the provider's
own https page), Telegram pairing (t.me), phone pairing (read by the LOKI phone app), and the
key hand-off page - the only one that is a home-network address, so it must offer every
address a phone could use, best first, and say what to do when the phone cannot open it.
"""
from __future__ import annotations

import socket
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import peers  # noqa: E402
import providers_catalog  # noqa: E402
import signin  # noqa: E402

OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open   # never through a proxy
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


# --- addresses: home Wi-Fi first, adapters a phone cannot reach last or never
real_lan, real_gai = peers.lan_address, socket.getaddrinfo
peers.lan_address = lambda: "172.24.80.1"            # a WSL/Hyper-V adapter won the default route
socket.getaddrinfo = lambda *a, **k: [(0, 0, 0, "", (ip, 0)) for ip in ("169.254.3.4", "192.168.1.23", "10.0.0.7", "127.0.0.1")]
try:
    got = peers.lan_addresses()
finally:
    peers.lan_address, socket.getaddrinfo = real_lan, real_gai
check("home Wi-Fi address comes first, then 10.x, then the 172.x adapter", got == ["192.168.1.23", "10.0.0.7", "172.24.80.1"], got)
check("link-local and loopback are never offered", "169.254.3.4" not in got and "127.0.0.1" not in got, got)

# --- the hand-off page: every address, a link to the key page, a steady port
keys = []
ho = signin.PhoneHandoff("nvidia", "NVIDIA", lambda p, k: (keys.append(k), {"ok": True, "message": "ok"})[1],
                         ["127.0.0.1", "localhost"], lambda ip: True, ttl_s=30, bind="127.0.0.1",
                         keys_url="https://build.nvidia.com/settings/api-keys", port_number=0)
try:
    st = ho.status()
    check("the hand-off lists one link per address", len(st["urls"]) == 2 and st["url"] == st["urls"][0], st)
    page = OPEN(st["urls"][0], timeout=5).read().decode()
    check("the phone page links to the provider's key page", "build.nvidia.com/settings/api-keys" in page)
    body = urllib.parse.urlencode({"key": "  nvapi-test  "}).encode()
    OPEN(urllib.request.Request(st["urls"][0], data=body), timeout=5).read()
    check("a key sent from the phone reaches LOKI (trimmed)", keys == ["nvapi-test"], keys)
finally:
    ho.stop()
bad = signin.PhoneHandoff("x", "X", lambda p, k: {"ok": True}, "127.0.0.1", lambda ip: True, ttl_s=5,
                          bind="127.0.0.1", keys_url="javascript:alert(1)")
check("only https key pages are linked", bad.keys_url == "", bad.keys_url)
bad.stop()
probe = socket.socket()
probe.bind(("127.0.0.1", 0))
taken = probe.getsockname()[1]
probe.listen(1)
moved = signin.PhoneHandoff("x", "X", lambda p, k: {"ok": True}, "127.0.0.1", lambda ip: True, ttl_s=5,
                            bind="127.0.0.1", port_number=taken)
check("a taken hand-off port moves to a free one instead of failing", moved.port != taken)
moved.stop()
probe.close()

# --- Windows: a Public network blocks the phone; LOKI says so
Out = type("Out", (), {})
pub, priv = Out(), Out()
pub.stdout, priv.stdout = "Public\n", "Private\n"
check("a Public Wi-Fi on Windows gets a plain fix", "Private" in signin.network_hint(run=lambda *a, **k: pub))
check("a Private Wi-Fi gets no warning", signin.network_hint(run=lambda *a, **k: priv) == "")

# --- the public QRs go to real https pages
links = [(e["id"], e.get("keys", "")) for e in providers_catalog.CATALOG if e.get("keys")] \
    if hasattr(providers_catalog, "CATALOG") else []
check("every provider key page is https", links and all(u.startswith("https://") for _, u in links),
      [l for l in links if not l[1].startswith("https://")])
flow = signin.openrouter_start(8767, "code")
check("OpenRouter phone sign-in is OpenRouter's own page with no localhost callback",
      flow["url"].startswith("https://openrouter.ai/auth?") and "callback_url" not in flow["url"], flow["url"])

js = (REPO / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
check("the key QR window offers the other addresses and the key page", "Try another address" in js and "key page instead" in js)
check("the key QR window tells the user Paste works too", "use Paste next to the key box" in js)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
