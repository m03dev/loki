"""LOKI Spaces (engine/spaces.py, engine/spaces_api.py): two machines in one process - a HOST that makes a space
and a GUEST that joins it with the invite code over real HTTP - then everything a Discord does: rooms, lobbies,
encrypted messages (opaque to the engines), edits, deletes, reactions, typing, voice state and WebRTC signals,
roles, kick, ban and lock. And the security: a forged or replayed request is refused, a tampered answer is not
believed, a wrong key cannot join. Offline (127.0.0.1, the relay off). Well under a minute.

    python tests/test_spaces.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-spaces-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_SPACES_RELAY"] = "off"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import spaces  # noqa: E402
import spaces_api  # noqa: E402


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
        return ""
    except spaces.SpaceError as exc:
        return str(exc) or "error"


host = spaces.Spaces(TMP / "host", port=0, relay=False)
guest = spaces.Spaces(TMP / "guest", port=0, relay=False)
third = spaces.Spaces(TMP / "third", port=0, relay=False)
host.profile("Ada", "#7fcfc2")
guest.profile("Bo", "#a596c4")
third.profile("Cy")

made = host.create("Night Owls", "#e0a96d")
sid = made["space"]["id"]
check("a machine makes a space and starts serving it (LAN port)", made["space"]["hosted"] and host.server is not None, made)
inv = host.invite(sid)
code = inv["code"]
check("the invite is one code with the space, the key and where to reach the host",
      code.startswith("loki-space:") and any(h.startswith("127.0.0.1:") for h in inv["hosts"]), inv["hosts"])
dec = spaces.decode_invite("join us: " + code + " !")
check("an invite is found inside pasted text and decodes", dec["space"] == sid and len(dec["key"]) == 32, dec["space"])
# only the loopback address is reachable in the test sandbox: keep the invite to it
code = spaces.encode_invite(sid, "Night Owls", dec["key"], ["127.0.0.1:%d" % host.port])

j = guest.join(code)
check("the guest joins over HTTP with the invite", j["space"] and not j["space"]["hosted"] and sid in guest.joined, j)
s0 = guest.sync(sid, 0)
rooms = {r["kind"]: r for r in s0["space"]["rooms"]}
check("a new space has a text room and a voice room; the guest sees both members",
      "text" in rooms and "voice" in rooms and {m["name"] for m in s0["members"]} == {"Ada", "Bo"}, s0["space"]["rooms"])
text = rooms["text"]["id"]

ct = spaces.b64e(b"\x01" * 40)
iv = spaces.b64e(b"\x02" * 12)
sent = guest.act(sid, "send", {"room": text, "ct": ct, "iv": iv})
hs = host.sync(sid, 0)
msg = [e for e in hs["events"] if e["kind"] == "msg"]
check("a message goes guest -> host as ciphertext only (the engines never see the words)",
      msg and msg[-1]["ct"] == ct and "text" not in msg[-1] and msg[-1]["from"] == guest.joined[sid].doc["member"], msg[-1:])
check("a plain-text message is refused (Spaces only carries encrypted text)",
      raises(guest.act, sid, "send", {"room": text, "text": "hello"}) != "")
seq = sent["event"]["seq"]
guest.act(sid, "edit", {"target": seq, "ct": spaces.b64e(b"\x03" * 40), "iv": iv})
host.act(sid, "react", {"target": seq, "emoji": "🔥"})
check("only the author edits; anyone reacts; the host (owner) can delete it",
      raises(host.act, sid, "edit", {"target": seq, "ct": ct, "iv": iv}) != "" and
      host.act(sid, "delete", {"target": seq})["ok"])
kinds = [e["kind"] for e in guest.sync(sid, seq)["events"]]
check("edits, reactions and deletes come to every member as events", kinds[-3:] == ["edit", "react", "del"], kinds)
guest.act(sid, "typing", {"room": text})
who = {m["name"]: m for m in host.sync(sid, 10 ** 9)["members"]}
check("typing shows on the other side", who["Bo"]["typing"] == text and who["Bo"]["online"], who["Bo"])

check("only the owner and admins add rooms; any member can open a lobby",
      raises(guest.act, sid, "room", {"op": "add", "kind": "text", "name": "x"}) != ""
      and guest.act(sid, "room", {"op": "add", "kind": "lobby", "name": "Raid night", "activity": "LOKI World", "cap": 4})["ok"])
lobby = [r for r in host.sync(sid, 10 ** 9)["space"]["rooms"] if r["kind"] == "lobby"][0]
v1 = host.act(sid, "voice", {"room": lobby["id"], "muted": False})
v2 = guest.act(sid, "voice", {"room": lobby["id"], "muted": True})
check("joining voice says who is already in the room (whom to call)", v1["peers"] == [] and v2["peers"] == [host.hosted[sid].doc["owner"]], (v1, v2))
gm = guest.joined[sid].doc["member"]
host.act(sid, "signal", {"to": gm, "ct": spaces.b64e(b"offer" * 8), "iv": iv})
sig = guest.sync(sid, 10 ** 9)["signals"]
check("a WebRTC signal is delivered once, to that member only", len(sig) == 1 and sig[0]["from"] == host.hosted[sid].doc["owner"]
      and guest.sync(sid, 10 ** 9)["signals"] == [], sig)
wl = host.world()["lobbies"]
check("LOKI World sees the open lobby, its activity and who is in it",
      any(x["name"] == "Raid night" and x["activity"] == "LOKI World" and len(x["people"]) == 2 for x in wl), wl)
guest.act(sid, "voice", {"room": None})
host.act(sid, "voice", {"room": None})
hsp = host.hosted[sid]
hsp.empty_since[lobby["id"]] = time.time() - spaces.LOBBY_EMPTY_S - 1
gone = [r for r in host.sync(sid, 10 ** 9)["space"]["rooms"] if r["kind"] == "lobby"]
check("an empty lobby tidies itself away", gone == [], gone)

# ---- security on the wire
url = "http://127.0.0.1:%d/sp/v1/%s/send" % (host.port, sid)
raw = json.dumps({"room": text, "ct": ct, "iv": iv}).encode()


def post(headers):
    req = urllib.request.Request(url, data=raw, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with spaces._OPENER.open(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


ts = "%.3f" % time.time()
good = spaces.sign(guest.joined[sid].secret, "POST", "/sp/v1/%s/send" % sid, ts, spaces.body_hash(raw))
check("a correctly signed request is accepted ...", post({"X-Sp-Member": gm, "X-Sp-Ts": ts, "X-Sp-Sig": good}) == 200)
check("... and the same request replayed is refused", post({"X-Sp-Member": gm, "X-Sp-Ts": ts, "X-Sp-Sig": good}) == 401)
check("a request signed with the wrong secret is refused (the relay cannot act as a member)",
      post({"X-Sp-Member": gm, "X-Sp-Ts": ts, "X-Sp-Sig": "0" * 64}) == 401)
old_ts = "%.3f" % (time.time() - 3600)
check("a request from an hour ago is refused",
      post({"X-Sp-Member": gm, "X-Sp-Ts": old_ts, "X-Sp-Sig": spaces.sign(guest.joined[sid].secret, "POST", "/sp/v1/%s/send" % sid, old_ts, spaces.body_hash(raw))}) == 401)
bad = spaces.encode_invite(sid, "Night Owls", b"\x09" * 32, ["127.0.0.1:%d" % host.port])
check("an invite with the wrong key cannot join", "wrong key" in raises(third.join, bad))
# a relay in the middle that changes the answer (here: a member's name) - the guest must not believe it
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
import threading  # noqa: E402


class Evil(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        return

    def do_POST(self):  # noqa: N802
        raw_in = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        fwd = urllib.request.Request("http://127.0.0.1:%d%s" % (host.port, self.path), data=raw_in, method="POST",
                                     headers={k: v for k, v in self.headers.items() if k.lower().startswith(("x-sp", "content-type"))})
        with spaces._OPENER.open(fwd, timeout=5) as resp:
            out, sig_ = resp.read(), resp.headers.get("X-Sp-Sig", "")
        out = out.replace(b'"Ada"', b'"Mallory"')
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.send_header("X-Sp-Sig", sig_)
        self.end_headers()
        self.wfile.write(out)


evil = ThreadingHTTPServer(("127.0.0.1", 0), Evil)
threading.Thread(target=evil.serve_forever, daemon=True).start()
real_hosts = guest.joined[sid].doc["hosts"]
guest.joined[sid].doc["hosts"], guest.joined[sid].good = ["127.0.0.1:%d" % evil.server_address[1]], ""
check("an answer changed on the way (by a relay) is not believed", "not signed by the host" in raises(guest.sync, sid, 0))
guest.joined[sid].doc["hosts"] = real_hosts
evil.shutdown()

# ---- moderation
third.join(code)
cm = third.joined[sid].doc["member"]
check("a member cannot moderate", raises(guest.act, sid, "mod", {"member": cm, "op": "kick"}) != "")
host.act(sid, "mod", {"member": gm, "op": "admin"})
check("the owner makes an admin, and an admin can kick", guest.act(sid, "mod", {"member": cm, "op": "kick"})["ok"]
      and cm not in host.hosted[sid].doc["members"])
check("a kicked member can come back with the invite (kick is not ban)", third.join(code)["space"] is not None)
host.act(sid, "mod", {"member": cm, "op": "ban"})
check("a banned member is out, and cannot join again", "banned" in raises(third.join, code) and raises(third.sync, sid, 0) != "")
host.act(sid, "mod", {"op": "lock", "on": True})
fourth = spaces.Spaces(TMP / "fourth", port=0, relay=False)
check("a locked space takes no new members", "not taking new members" in raises(fourth.join, code))
host.act(sid, "mod", {"op": "lock", "on": False})
check("nobody moderates the owner", raises(guest.act, sid, "mod", {"member": hsp.doc["owner"], "op": "ban"}) != "")

# ---- it all survives a restart of the host
host.stop()
again = spaces.Spaces(TMP / "host", port=0, relay=False).start()
code2 = spaces.encode_invite(sid, "Night Owls", dec["key"], ["127.0.0.1:%d" % again.port])
guest.joined[sid].doc["hosts"] = ["127.0.0.1:%d" % again.port]
after = guest.sync(sid, 0)
check("the host restarts: the space, its members and its history are still there (the guest reconnects)",
      any(e["kind"] == "msg" for e in after["events"]) and {m["name"] for m in after["members"]} >= {"Ada", "Bo"}, after.get("seq"))

# ---- the window's routes (engine/spaces_api.py) on the running instance
spaces._SINGLE["s"] = again
st, body = spaces_api.route("GET", "/spaces")
check("GET /spaces lists the hosted space and my name", st == 200 and body["spaces"][0]["id"] == sid and body["me"]["name"] == "Ada", body)
st, body = spaces_api.route("GET", "/spaces/key?space=" + sid)
check("GET /spaces/key gives the window the key for its end-to-end encryption", st == 200 and len(spaces.b64d(body["key"])) == 32)
st, body = spaces_api.route("POST", "/spaces/act", {"space": sid, "action": "nope"})
check("an unknown action is refused", st == 400)
st, body = spaces_api.route("POST", "/spaces/join", {"code": "hello"})
check("a pasted thing that is not an invite says so", st == 400 and "invite" in body["error"], body)
st, body = spaces_api.route("POST", "/spaces/forget", {"space": sid})
check("deleting a hosted space keeps it on disk (renamed), never destroyed",
      st == 200 and any(p.name.startswith(sid + ".deleted-") for p in (TMP / "host" / "hosted").iterdir()), body)

for x in (again, guest, third, fourth):
    x.stop()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
