"""Phone link tests: the LOKI phone app talking to LOKI on the computer (engine/phone_link.py).

    python tests/test_phone_link.py

Pairing, signatures, expiry, revocation, rate limits, the Ask/Plan-only chat that can
never approve anything, the QR payload, the bridge wiring, real HTTP on 127.0.0.1, and the
phone app's own TypeScript protocol code (run in Node when it is installed) agreeing with
Python. Temp data folders only; nothing listens on the network.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "data")
for key in ("LOKI_PHONE_LINK", "LOKI_PHONE_PORT", "LOKI_PEER_SECRET", "LOKI_PEER_NAME"):
    os.environ.pop(key, None)
sys.path.insert(0, str(REPO / "engine"))

import peers  # noqa: E402
import phone_link  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def signed(key, phone_id, method, path, body=b"", stamp=None):
    stamp = stamp or "%.3f" % time.time()
    return {"X-Loki-Phone": phone_id, "X-Loki-Time": stamp,
            "X-Loki-Sig": phone_link.sign(key, method, path, stamp, body)}


section("pairing tokens: issue, verify, revoke")
clock = Clock()
reg = phone_link.Registry(TMP / "reg1" / "phones.json", clock=clock)
pairing = reg.pair("Mo's iPhone")
check("pairing returns an id, a name and a long random token",
      len(pairing["id"]) == 12 and pairing["name"] == "Mo's iPhone" and len(pairing["token"]) >= 40, pairing)
stored = (TMP / "reg1" / "phones.json").read_text()
check("the token itself is never stored", pairing["token"] not in stored)
check("only the derived signing key is stored", phone_link.signing_key(pairing["token"]) in stored)
check("two pairings get different tokens", reg.pair("other")["token"] != pairing["token"])
key = phone_link.signing_key(pairing["token"])
guard = peers.ReplayGuard()
h = signed(key, pairing["id"], "GET", "/phone/status", stamp="%.3f" % clock.now)
check("a correctly signed request verifies",
      phone_link.verify(reg, "GET", "/phone/status", h, b"", guard, clock.now) == (pairing["id"], ""))
check("the same request twice is a replay",
      "replayed" in phone_link.verify(reg, "GET", "/phone/status", h, b"", guard, clock.now)[1])
# The nonce (same fix as engine/peers.py): two identical requests in one millisecond must both pass.
def with_nonce(nonce, stamp, method="GET", path="/phone/status", body=b""):
    return {"X-Loki-Phone": pairing["id"], "X-Loki-Time": stamp, "X-Loki-Nonce": nonce,
            "X-Loki-Sig": phone_link.sign(key, method, path, stamp, body, nonce)}
same_ms = "%.3f" % clock.now
na, nb = with_nonce("n-aaa", same_ms), with_nonce("n-bbb", same_ms)
check("two identical same-millisecond requests get different signatures", na["X-Loki-Sig"] != nb["X-Loki-Sig"])
g2 = peers.ReplayGuard()
check("both identical same-millisecond requests are accepted",
      phone_link.verify(reg, "GET", "/phone/status", na, b"", g2, clock.now) == (pairing["id"], "") and
      phone_link.verify(reg, "GET", "/phone/status", nb, b"", g2, clock.now) == (pairing["id"], ""))
check("a nonce request replayed verbatim is still refused",
      "replayed" in phone_link.verify(reg, "GET", "/phone/status", na, b"", g2, clock.now)[1])
swapped = dict(na, **{"X-Loki-Nonce": "n-zzz"})
check("a swapped nonce breaks the signature",
      phone_link.verify(reg, "GET", "/phone/status", swapped, b"", peers.ReplayGuard(), clock.now)[1] == "bad signature")
dropped = {k: v for k, v in na.items() if k != "X-Loki-Nonce"}
check("dropping the nonce breaks the signature",
      phone_link.verify(reg, "GET", "/phone/status", dropped, b"", peers.ReplayGuard(), clock.now)[1] == "bad signature")
wrong = phone_link.signing_key("x" * 43)
h2 = signed(wrong, pairing["id"], "GET", "/phone/status", stamp="%.3f" % clock.now)
check("a wrong token is refused", phone_link.verify(reg, "GET", "/phone/status", h2, b"", peers.ReplayGuard(), clock.now)[1] == "bad signature")
h3 = signed(key, pairing["id"], "POST", "/phone/chat", b'{"message":"hi"}', stamp="%.3f" % clock.now)
check("a changed body is refused",
      phone_link.verify(reg, "POST", "/phone/chat", h3, b'{"message":"rm"}', peers.ReplayGuard(), clock.now)[1] == "bad signature")
check("another path is refused",
      phone_link.verify(reg, "POST", "/phone/unpair", h3, b'{"message":"hi"}', peers.ReplayGuard(), clock.now)[1] == "bad signature")
h4 = signed(key, pairing["id"], "GET", "/phone/status", stamp="%.3f" % (clock.now - 600))
check("an old request is refused", "too old" in phone_link.verify(reg, "GET", "/phone/status", h4, b"", peers.ReplayGuard(), clock.now)[1])
check("an unsigned request is refused", phone_link.verify(reg, "GET", "/phone/status", {}, b"", peers.ReplayGuard(), clock.now)[1] == "unsigned request")
h5 = signed(key, "nobody", "GET", "/phone/status", stamp="%.3f" % clock.now)
check("an unknown phone id is refused", "unknown phone" in phone_link.verify(reg, "GET", "/phone/status", h5, b"", peers.ReplayGuard(), clock.now)[1])
check("revoke works once", reg.revoke(pairing["id"]) and not reg.revoke(pairing["id"]))
h6 = signed(key, pairing["id"], "GET", "/phone/status", stamp="%.3f" % clock.now)
check("a revoked phone is refused", "revoked" in phone_link.verify(reg, "GET", "/phone/status", h6, b"", peers.ReplayGuard(), clock.now)[1])
check("a revoked phone has no key left on disk",
      key not in (TMP / "reg1" / "phones.json").read_text())
check("the Settings list shows no keys", all("key" not in p and "token" not in p for p in reg.present()), reg.present())

section("expiry")
clock = Clock()
reg = phone_link.Registry(TMP / "reg2" / "phones.json", clock=clock)
late = reg.pair("late")
clock.now += phone_link.PAIR_TTL_S + 1
k = phone_link.signing_key(late["token"])
check("a QR not scanned within 15 minutes has expired",
      "expired" in phone_link.verify(reg, "GET", "/phone/status", signed(k, late["id"], "GET", "/phone/status", stamp="%.3f" % clock.now),
                                     b"", peers.ReplayGuard(), clock.now)[1])
used = reg.pair("used")
ku = phone_link.signing_key(used["token"])
ok = phone_link.verify(reg, "GET", "/phone/status", signed(ku, used["id"], "GET", "/phone/status", stamp="%.3f" % clock.now), b"", peers.ReplayGuard(), clock.now)
reg.seen(used["id"])
clock.now += phone_link.PAIR_TTL_S + 60
ok2 = phone_link.verify(reg, "GET", "/phone/status", signed(ku, used["id"], "GET", "/phone/status", stamp="%.3f" % clock.now), b"", peers.ReplayGuard(), clock.now)
check("a scanned pairing keeps working after the 15 minutes", ok[1] == "" and ok2[1] == "", (ok, ok2))
clock.now += phone_link.IDLE_TTL_S + 1
check("a phone unused for 60 days has expired",
      "expired" in phone_link.verify(reg, "GET", "/phone/status", signed(ku, used["id"], "GET", "/phone/status", stamp="%.3f" % clock.now),
                                     b"", peers.ReplayGuard(), clock.now)[1])
check("states are shown", sorted(p["state"] for p in reg.present()) == ["expired", "expired"], reg.present())


# --- a fake engine for the server and chat tests ------------------------------------

class FakeAgent:
    def __init__(self):
        self.AGENT_MODE = "build"
        self.approve = self.desktop_approve
        self.modes_seen = []
        self.approvals = []
        self.env = TMP / "env" / ".env"

    async def desktop_approve(self, kind, detail, decidable=True):
        return True                        # pretend the risk gate would let it through

    def set_mode(self, mode):
        if mode in ("ask", "plan", "build"):
            self.AGENT_MODE = mode
        return self.AGENT_MODE

    def env_file_path(self):
        return self.env

    def request_cancel(self):
        pass


class FakeState:
    def __init__(self, agent):
        self.agent = agent
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.chat_request_lock = threading.Lock()
        self.task_request_lock = threading.Lock()
        self.phone_server = None

    def try_busy(self):
        got = []
        for lock in (self.chat_request_lock, self.task_request_lock):
            if lock.acquire(blocking=False):
                got.append(lock)
            else:
                for held in got:
                    held.release()
                return None
        return got

    @staticmethod
    def release_busy(locks):
        for lock in locks:
            lock.release()

    async def request_chat(self, prompt):
        # What a risky tool call does inside the agent loop: ask approve().
        self.agent.modes_seen.append(self.agent.AGENT_MODE)
        allowed = await self.agent.approve("run_command", "rm -rf ~", True)
        self.agent.approvals.append(allowed)
        return {"ok": True, "response": "echo: " + prompt}


section("phone chat can never approve")
agent = FakeAgent()
state = FakeState(agent)
code, reply = phone_link.chat_once(state, agent, "delete everything", "ask")
check("a phone chat answers", code == 200 and reply["response"] == "echo: delete everything", (code, reply))
check("the risky tool's approval was refused", agent.approvals == [False], agent.approvals)
check("it ran in Ask mode", agent.modes_seen == ["ask"], agent.modes_seen)
check("the app's mode and approval are restored", agent.AGENT_MODE == "build" and agent.approve == agent.desktop_approve)
code, reply = phone_link.chat_once(state, agent, "plan it", "plan")
check("Plan mode is allowed and still cannot approve", code == 200 and agent.modes_seen[-1] == "plan" and agent.approvals[-1] is False)
code, reply = phone_link.chat_once(state, agent, "build it", "build")
check("Build mode from the phone is refused", code == 403 and len(agent.approvals) == 2, (code, reply))
state.chat_request_lock.acquire()
code, reply = phone_link.chat_once(state, agent, "hi", "ask")
state.chat_request_lock.release()
check("busy with an app chat: 409, nothing runs", code == 409 and len(agent.approvals) == 2, (code, reply))
check("the reply says which machine answered", reply.get("error") and phone_link.machine_kind() in ("Mac", "PC"))


section("server: auth, limits, routes (direct)")
clock = Clock()
reg = phone_link.Registry(TMP / "reg3" / "phones.json", clock=clock)
calls = []


def fake_chat(message, mode):
    calls.append((message, mode))
    return 200, {"ok": True, "response": "ok"}


server = phone_link.PhoneServer({"status": lambda: {"machine": "pc", "kind": "PC"}, "chat": fake_chat},
                                reg, env={}, host="127.0.0.1", port_number=0, clock=clock)
p = reg.pair("phone")
pk = phone_link.signing_key(p["token"])


def call(method, path, payload=None, client="192.168.1.20", key_=None, pid=None, stamp_offset=0.0):
    body = json.dumps(payload).encode() if payload is not None else b""
    clock.now += 0.001                       # distinct stamps, so no false replays
    hdr = signed(key_ or pk, pid or p["id"], method, path, body, stamp="%.3f" % (clock.now + stamp_offset))
    return server.handle(method, path, client, hdr, body)


check("status works for a paired phone", call("GET", "/phone/status") == (200, {"ok": True, "machine": "pc", "kind": "PC"}))
check("a public address is refused", call("GET", "/phone/status", client="8.8.8.8")[0] == 403)
check("Build mode is refused at the door", call("POST", "/phone/chat", {"message": "x", "mode": "build"})[0] == 403 and not calls)
check("an empty message is refused", call("POST", "/phone/chat", {"message": " "})[0] == 400)
check("an over-long message is refused", call("POST", "/phone/chat", {"message": "x" * 5000})[0] == 400)
codes = [call("POST", "/phone/chat", {"message": "hi %d" % i})[0] for i in range(phone_link.CHAT_PER_MIN + 2)]
check("chat is rate limited per phone", codes[:phone_link.CHAT_PER_MIN] == [200] * phone_link.CHAT_PER_MIN and codes[-1] == 429, codes)
check("the default mode is Ask", calls and all(m == "ask" for _, m in calls), calls)
clock.now += 61
check("after a minute the phone may chat again", call("POST", "/phone/chat", {"message": "again"})[0] == 200)
bad = [call("GET", "/phone/status", key_=phone_link.signing_key("y" * 43), client="192.168.1.66")[0]
       for _ in range(phone_link.BAD_SIG_LIMIT + 1)]
check("repeated bad signatures lock that address out", bad[:phone_link.BAD_SIG_LIMIT] == [401] * phone_link.BAD_SIG_LIMIT and bad[-1] == 429, bad)
check("... even with a good signature afterwards", call("GET", "/phone/status", client="192.168.1.66")[0] == 429)
check("... but not other addresses", call("GET", "/phone/status", client="192.168.1.67")[0] == 200)
check("too large a body is refused", server.handle("POST", "/phone/chat", "192.168.1.20", {}, None)[0] == 413)
check("an unknown endpoint is 404", call("GET", "/phone/secrets")[0] == 404)
check("unpair revokes the phone itself", call("POST", "/phone/unpair", {})[0] == 200 and call("GET", "/phone/status")[0] == 401)
server.httpd.server_close()


section("server: real HTTP on 127.0.0.1")
reg = phone_link.Registry(TMP / "reg4" / "phones.json")
srv = phone_link.PhoneServer({"status": lambda: {"machine": "mac", "kind": "Mac"}, "chat": fake_chat},
                             reg, env={}, host="127.0.0.1", port_number=0).start()
p = reg.pair("http phone")
pk = phone_link.signing_key(p["token"])
base = "http://127.0.0.1:%d" % srv.address[1]


def http(method, path, payload=None, key_=pk):
    body = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(base + path, data=body if method == "POST" else None, method=method,
                                 headers={"Content-Type": "application/json", **signed(key_, p["id"], method, path, body)})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


check("signed status over HTTP", http("GET", "/phone/status")[0] == 200)
check("signed chat over HTTP", http("POST", "/phone/chat", {"message": "hello from http"}) == (200, {"ok": True, "response": "ok"}))
check("a wrong key over HTTP is 401", http("GET", "/phone/status", key_=phone_link.signing_key("z" * 43))[0] == 401)
check("the first use claims the pairing", [x["state"] for x in reg.present()] == ["paired"], reg.present())
srv.stop()


section("QR payload")
pairing = {"id": "abc123abc123", "name": "x", "token": "T" * 43}
payload = phone_link.pairing_payload(pairing, ["192.168.1.71", "100.90.1.2"], 8769, "mohameds-mac-mini", "Mac")
check("the QR holds exactly: version, machine, kind, hosts, port, id, token",
      sorted(payload) == ["hosts", "id", "kind", "machine", "port", "token", "v"], sorted(payload))
os.environ["LOKI_PEER_SECRET"] = "P" * 40
code_text = phone_link.make_pairing_code(payload)
decoded = base64.urlsafe_b64decode(code_text[len(phone_link.PAIR_PREFIX):] + "==").decode()
check("no peer secret, bridge token or key name in the QR",
      "P" * 40 not in decoded and "secret" not in decoded.lower() and "key" not in decoded.lower(), decoded)
os.environ.pop("LOKI_PEER_SECRET")
check("the only secret is the per-phone token", phone_link.parse_pairing_code(code_text)["token"] == "T" * 43)
check("a pairing code fits a QR code", __import__("qr").matrix(code_text) is not None)
for bad_code, why in (("hello", "not a code"), ("loki-phone:@@@", "damaged"),
                      (phone_link.make_pairing_code({**payload, "hosts": ["8.8.8.8"]}), "public address"),
                      (phone_link.make_pairing_code({**payload, "token": "short"}), "short token")):
    try:
        phone_link.parse_pairing_code(bad_code)
        check("a bad phone code is refused (%s)" % why, False)
    except ValueError:
        check("a bad phone code is refused (%s)" % why, True)


section("Settings routes (/phones) and the bridge wiring")
agent = FakeAgent()
state = FakeState(agent)
os.environ["LOKI_PHONE_PORT"] = "0"
os.environ["LOKI_PHONE_HOST"] = "127.0.0.1"
code, data = phone_link.ui_route(state, agent, "GET", "/phones", {})
check("GET /phones: off by default", code == 200 and data["enabled"] is False and data["listening"] is False, data)
check("pairing needs the link on", phone_link.ui_route(state, agent, "POST", "/phones/pair", {"name": "x"})[0] == 400)
code, data = phone_link.ui_route(state, agent, "POST", "/phones/enable", {"on": True})
check("turning it on starts the server and writes LOKI_PHONE_LINK=1",
      code == 200 and state.phone_server is not None and "LOKI_PHONE_LINK=1" in agent.env.read_text(), data)
code, data = phone_link.ui_route(state, agent, "POST", "/phones/pair", {"name": "Ziva's Pixel"})
check("pair returns a code and a QR svg", code == 200 and data["code"].startswith("loki-phone:") and data["svg"].startswith("<svg"), data.get("error"))
parsed = phone_link.parse_pairing_code(data["code"])
check("the code points at the running server", parsed["port"] == state.phone_server.address[1] and parsed["id"] == data["id"])
phones = phone_link.ui_route(state, agent, "GET", "/phones", {})[1]["phones"]
check("the new phone is listed, waiting", [(x["name"], x["state"]) for x in phones] == [("Ziva's Pixel", "waiting")], phones)
check("revoke from Settings", phone_link.ui_route(state, agent, "POST", "/phones/revoke", {"id": data["id"]})[0] == 200)
check("revoking an unknown phone is 404", phone_link.ui_route(state, agent, "POST", "/phones/revoke", {"id": "nope"})[0] == 404)
code, data = phone_link.ui_route(state, agent, "POST", "/phones/enable", {"on": False})
check("turning it off stops the server and removes the setting",
      state.phone_server is None and "LOKI_PHONE_LINK" not in agent.env.read_text())
check("other routes are not ours", phone_link.ui_route(state, agent, "GET", "/peers", {}) is None)
os.environ.pop("LOKI_PHONE_LINK", None)
os.environ.pop("LOKI_PHONE_PORT", None)
os.environ.pop("LOKI_PHONE_HOST", None)
check("start() does nothing unless LOKI_PHONE_LINK=1", phone_link.start(state, agent) is None)
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge routes GET and POST /phones*",
      'phone_ui(self.server.state, "GET", route, {})' in bridge and 'phone_ui(state, "POST", route, data)' in bridge)
check("the bridge starts and stops the phone server",
      "phone_link.start(state, loki)" in bridge and "state.phone_server.stop()" in bridge)
machines_js = (REPO / "app" / "ui" / "machines.js").read_text(encoding="utf-8")
check("Settings > Machines has the Phone card", "async function phoneCard()" in machines_js and "/phones/pair" in machines_js)
check("the suite is in tools/ship.py", '"test_phone_link"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))


section("the phone app's TypeScript protocol agrees with Python")
node = shutil.which("node")
script = REPO / "mobile" / "scripts" / "check_protocol.mjs"
version = ()
if node:
    try:
        version = tuple(int(x) for x in subprocess.run([node, "--version"], capture_output=True, text=True,
                                                       timeout=20).stdout.strip().lstrip("v").split(".")[:2])
    except (OSError, ValueError, subprocess.SubprocessError):
        version = ()
if not node or version < (22, 6):
    print("  SKIP node 22.6+ is not installed here (the TypeScript check runs where it is, e.g. CI)")
else:
    token = "tok-" + "Q" * 40
    vector = {"token": token, "method": "POST", "path": "/phone/chat", "stamp": "1800000000.123",
              "body": json.dumps({"message": "héllo 中 😀"}, ensure_ascii=False),
              "code": phone_link.make_pairing_code(phone_link.pairing_payload(
                  {"id": "abc123abc123", "token": token}, ["192.168.1.71"], 8769, "pc-é", "PC"))}
    run = subprocess.run([node, "--experimental-strip-types", "--no-warnings", str(script), json.dumps(vector)],
                         capture_output=True, text=True, timeout=60, encoding="utf-8")
    try:
        ts = json.loads(run.stdout)
    except ValueError:
        ts = {}
    key_py = phone_link.signing_key(token)
    check("TS derives the same signing key", ts.get("key") == key_py, run.stderr or ts)
    check("TS signs exactly like Python (UTF-8 body)",
          ts.get("sig") == phone_link.sign(key_py, "POST", "/phone/chat", vector["stamp"], vector["body"].encode("utf-8")), ts)
    check("TS SHA-256 is right", ts.get("sha_empty") == hashlib.sha256(b"").hexdigest() and
          ts.get("sha_unicode") == hashlib.sha256("LOKI é中😀".encode()).hexdigest(), ts)
    check("TS reads the pairing code", (ts.get("pairing") or {}).get("machine") == "pc-é" and
          ts["pairing"].get("token") == token and ts["pairing"].get("port") == 8769, ts.get("pairing"))
    check("TS refuses an incomplete code", ts.get("incomplete_refused") is True, ts)
    check("TS signs with a nonce exactly like Python",
          ts.get("sig_nonce") == phone_link.sign(key_py, "POST", "/phone/chat", vector["stamp"],
                                                 vector["body"].encode("utf-8"), "nonce-1"), ts)
    hd = ts.get("headers") or {}
    check("TS signedHeaders sends a fresh X-Loki-Nonce inside the signature",
          hd.get("X-Loki-Nonce") and hd.get("X-Loki-Nonce") != (ts.get("headers2") or {}).get("X-Loki-Nonce") and
          hd.get("X-Loki-Sig") == phone_link.sign(key_py, "GET", "/phone/status", hd.get("X-Loki-Time", ""), b"",
                                                  hd.get("X-Loki-Nonce", "")), ts)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
