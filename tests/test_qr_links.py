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
check("a Public Wi-Fi on Windows gets a plain fix", "Private" in signin.network_hint(run=lambda *a, **k: pub, platform="win32"))
check("a Private Wi-Fi gets no warning", signin.network_hint(run=lambda *a, **k: priv, platform="win32") == "")

calls = []
Done = type("Done", (), {"returncode": 0})
fw = signin.allow_phone_port(8770, run=lambda argv, **k: (calls.append(argv), Done())[1])
check("'Let phones in' asks Windows once for this one port, home networks only",
      fw["ok"] and "RunAs" in calls[0][-1] and "localport=8770" in calls[0][-1] and "profile=private,domain" in calls[0][-1],
      (fw, calls))
Declined = type("Declined", (), {"returncode": 1})
check("a declined prompt says so", not signin.allow_phone_port(8770, run=lambda *a, **k: Declined())["ok"])

# --- the public QRs go to real https pages
links = [(e["id"], e.get("keys", "")) for e in providers_catalog.CATALOG if e.get("keys")] \
    if hasattr(providers_catalog, "CATALOG") else []
check("every provider key page is https", links and all(u.startswith("https://") for _, u in links),
      [l for l in links if not l[1].startswith("https://")])
js = (REPO / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
# OpenRouter was removed with the other daily-capped providers (2026-10-27): its browser sign-in went with it
check("OpenRouter's browser sign-in is gone (no flow, no button code)",
      not hasattr(signin, "openrouter_start") and "signInOpenRouter" not in js and "openrouter.ai/auth" not in js)
check("the key QR window offers the other addresses and the key page", "Try another address" in js and "key page instead" in js)
check("the key QR window tells the user Paste works too", "use Paste next to the key box" in js)
check("the key QR window offers the internet link and the Windows allow", "internet link" in js and "/handoff/firewall" in js)

# --- the provider Test button (owner: "I added the key but I don't think it's working")
import io  # noqa: E402
import json  # noqa: E402
import types  # noqa: E402
cfg = types.SimpleNamespace(base_url="https://integrate.api.nvidia.com/v1", api_key="nvapi-x",
                            model="deepseek-ai/deepseek-v4.1-flash")
agent = types.SimpleNamespace(MODELS={"nvidia": cfg})
sent = []


class _Resp:
    def __init__(self, data):
        self.status, self.data = 200, data

    def read(self):
        return json.dumps(self.data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def nim(models=None, slow=False, down=False):
    def opener(req, timeout=0):
        sent.append((req.full_url, json.loads(req.data.decode()) if req.data else None))
        if down:
            raise urllib.error.URLError(TimeoutError("timed out"))
        if req.full_url.endswith("/models"):
            return _Resp({"data": [{"id": m} for m in (models or [])]})
        if slow:
            raise TimeoutError("timed out")
        return _Resp({"model": cfg.model})
    return opener


import urllib.error  # noqa: E402
r = providers_catalog.test(agent, "nvidia", timeout=1, opener=nim())["test"]
check("Test sends DeepSeek on NVIDIA the thinking-off switch the chat uses",
      r["ok"] and sent[-1][1].get("chat_template_kwargs") == {"thinking": False}, (r, sent[-1]))
r = providers_catalog.test(agent, "nvidia", timeout=1, opener=nim(models=[cfg.model], slow=True))["test"]
check("a slow answer says the key and connection work, not 'could not reach'",
      not r["ok"] and "key and the connection work" in r["detail"], r)
r = providers_catalog.test(agent, "nvidia", timeout=1,
                           opener=nim(models=["deepseek-ai/deepseek-v4-flash", "meta/llama-3.3-70b"], slow=True))["test"]
check("a model NVIDIA does not offer is named, with the ones it does",
      "not in this provider's model list" in r["detail"] and "deepseek-ai/deepseek-v4-flash" in r["detail"]
      and "llama" not in r["detail"], r)
r = providers_catalog.test(agent, "nvidia", timeout=1, opener=nim(down=True))["test"]
check("no connection at all says this computer cannot reach NVIDIA",
      "cannot reach integrate.api.nvidia.com" in r["detail"], r)

# --- NVIDIA serves DeepSeek V4.1 Flash under another name: no 404, LOKI switches (the Mac's "error 404")
import nim_models  # noqa: E402
nim_models._cache.clear()
cfg.model = "deepseek-ai/deepseek-v4.1-flash"
sent.clear()
r = providers_catalog.test(agent, "nvidia", timeout=1, opener=nim(models=["nvidia/deepseek-v4.1-flash", "meta/llama-3.3-70b"]))["test"]
check("Test asks NVIDIA for the name it really serves", r["ok"] and cfg.model == "nvidia/deepseek-v4.1-flash"
      and sent[-1][1]["model"] == "nvidia/deepseek-v4.1-flash", (r, cfg.model, sent[-1:]))
check("a model NVIDIA serves is never changed", nim_models.resolve("x/y", ["x/y"]) == "x/y"
      and nim_models.resolve("meta/llama", ["a"]) == "meta/llama" and nim_models.resolve("deepseek-ai/deepseek-v4.1-flash", []) ==
      "deepseek-ai/deepseek-v4.1-flash")
check("no key: nothing is asked of NVIDIA", nim_models.fix(type("C", (), {"base_url": nim_models.NIM_URL, "model": "m", "api_key": ""})()) == "")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
