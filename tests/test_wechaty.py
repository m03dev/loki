"""The wechaty channel (engine/channel_wechaty.py + engine/wechaty_sidecar.mjs) with a fake sidecar.

    python tests/test_wechaty.py      (< 10 s, offline: no Node, no WeChat; a fake process speaks the
                                       sidecar's JSON lines)

Covers: the sidecar starts only while the add-on is on (an argument list, the secret in its environment,
never on the command line); QR login and logged-in state in Settings; pairing with the one-time code;
the owner's message becomes a LOKI chat and the answer goes back to that chat; strangers, group chats
and the account's own messages are never answered; pictures go back as files; the sidecar stops when
the add-on is turned off; a dead sidecar is reported, not hung on; the token never shows in status.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-wechaty-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
sys.path.insert(0, str(REPO / "engine"))

import channels  # noqa: E402
import channel_wechaty  # noqa: E402

PASS, FAIL = [], []
SECRET = "puppet_service_token_ABCDEFGH12345678"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def section(title):
    print("\n" + title)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ----------------------------------------------------------------------------- a fake sidecar process
class _Out:
    """The sidecar's stdout: lines the test pushes, read by the channel's reader thread."""

    def __init__(self):
        self.q = queue.Queue()

    def __iter__(self):
        while True:
            line = self.q.get()
            if line is None:
                return
            yield line


class _In:
    def __init__(self, proc):
        self.proc = proc

    def write(self, text):
        for line in text.splitlines():
            self.proc.got(json.loads(line))

    def flush(self):
        pass


class FakeSidecar:
    """Answers say/file like wechaty_sidecar.mjs: ok for chats it has seen, "unknown chat" otherwise."""
    started = []

    def __init__(self, argv, **kw):
        self.argv, self.kw = argv, kw
        self.stdout, self.stdin = _Out(), _In(self)
        self.sent, self.code, self.known = [], None, set()
        FakeSidecar.started.append(self)

    def emit(self, obj):
        if obj.get("event") == "message":
            self.known.add(str(obj.get("chat_id")))
        self.stdout.q.put(json.dumps(obj) + "\n")

    def got(self, req):
        if req.get("op") == "stop":
            self.exit(0)
            return
        self.sent.append(req)
        ok = str(req.get("to")) in self.known
        self.emit({"reply": req["id"], "ok": ok, **({} if ok else {"error": "unknown chat"})})

    def exit(self, code):
        self.code = code
        self.stdout.q.put(None)

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def terminate(self):
        self.exit(-15)

    def texts(self, to=None):
        return [r.get("text") for r in self.sent if r.get("op") == "say" and (to is None or r.get("to") == to)]


def make_channel(on, chats, env=None):
    cb = {"chat": lambda text, mode: chats.append((text, mode)) or (200, {"ok": True, "response": "LOKI says: " + text}),
          "jobs": lambda: [], "make": lambda p: {"ok": False, "error": "no"}, "making": lambda: [],
          "pictures_since": lambda t: [], "stop": lambda: None, "machine": lambda: "test-pc (Windows)"}
    env = {"LOKI_WECHATY_POLL": "on", "LOKI_NODE": "/fake/node", channel_wechaty.SECRET_ENV: SECRET, **(env or {})}
    ch = channel_wechaty.WechatyChannel(cb, store=channels.Store(TMP / ("store-%d.json" % len(FakeSidecar.started))),
                                        env=env, sleep=lambda s: None, enabled=lambda: on["v"], spawn=FakeSidecar)
    ch.send_gap_s = 0
    return ch, cb


# ----------------------------------------------------------------------------- the command line
section("the sidecar's command line and environment")
argv = channel_wechaty.sidecar_argv({"LOKI_NODE": "/opt/node/bin/node"})
check("node + the sidecar script, an argument list", argv == ["/opt/node/bin/node", str(REPO / "engine" / "wechaty_sidecar.mjs")], argv)
check("the script exists", (REPO / "engine" / "wechaty_sidecar.mjs").is_file())
try:
    channel_wechaty.sidecar_argv({}, which=lambda e: None)
    check("no Node -> a readable error", False)
except channels.ChannelError as exc:
    check("no Node -> a readable error", "Node.js" in str(exc))
senv = channel_wechaty.sidecar_env({"LOKI_WECHATY_PUPPET": "evil-puppet", channel_wechaty.SECRET_ENV: SECRET})
check("an unknown puppet falls back to wechat4u", senv["WECHATY_PUPPET"] == "wechaty-puppet-wechat4u")
check("the package folder is in LOKI's data folder", senv["LOKI_WECHATY_PACKAGE_DIR"] == str(TMP / "data" / "addons" / "wechaty"))
check("the secret reaches the sidecar only through its environment", senv[channel_wechaty.SECRET_ENV] == SECRET
      and SECRET not in " ".join(argv))
sidecar_src = (REPO / "engine" / "wechaty_sidecar.mjs").read_text(encoding="utf-8")
check("the sidecar answers only chats that wrote to it, and only text", "known.get(" in sidecar_src
      and "msg.type() !== TEXT" in sidecar_src and "child_process" not in sidecar_src and "eval(" not in sidecar_src)

# ----------------------------------------------------------------------------- off until the add-on is on
section("off until the add-on is on")
on, chats = {"v": False}, []
ch, cb = make_channel(on, chats)
check("not configured while the add-on is off", not ch.configured() and ch.status()["token_saved"] is False)
check("Settings explains how to turn it on", "Settings > Add-ons" in ch.status()["lines"][0])
check("/channels/pair refuses with the add-on hint",
      channels.ui_route(type("S", (), {"channels": {"wechaty": ch}})(), "POST", "/channels/pair", {"channel": "wechaty"})[0] == 400)
check("nothing started", not FakeSidecar.started)

# ----------------------------------------------------------------------------- login, pairing, both ways
section("login, pairing and messages both ways")
on["v"] = True
ch.bot = ch.me() or {}
proc = FakeSidecar.started[-1]
check("turning it on starts the sidecar with the argument list", proc.argv == ["/fake/node", str(channel_wechaty.SIDECAR)]
      and proc.kw.get("cwd") == str(TMP / "data" / "channels" / "wechaty") and "shell" not in proc.kw, proc.kw)
check("the secret is in its environment, not argv", proc.kw["env"].get(channel_wechaty.SECRET_ENV) == SECRET
      and SECRET not in " ".join(proc.argv))
proc.emit({"event": "scan", "qrcode": "https://login.weixin.qq.com/l/abc", "status": 2})
ch.poll_once()
st = ch.status()
check("the QR login link shows in Settings", st["login_qr"].endswith("/l/abc") and any("scan" in l for l in st["lines"]), st["lines"])
proc.emit({"event": "login", "user": {"id": "wxid_bot", "name": "LOKI bot"}})
ch.poll_once()
check("logged in", ch.status()["logged_in"] and ch.bot.get("username") == "LOKI bot" and not ch.status()["login_qr"])
code = ch.new_code()["code"]
proc.emit({"event": "message", "user_id": "wxid_owner", "chat_id": "wxid_owner", "room": False, "self": False,
           "name": "Mohamed", "text": "/start " + code})
ch.poll_once()
check("pairing with the one-time code", ch.owner().get("user_id") == "wxid_owner"
      and any("Paired" in t for t in proc.texts("wxid_owner")), proc.texts())
proc.emit({"event": "message", "user_id": "wxid_owner", "chat_id": "wxid_owner", "room": False, "self": False,
           "name": "Mohamed", "text": "what is on my calendar?"})
ch.poll_once()
check("the owner's message becomes a LOKI chat (Ask mode)", wait_for(lambda: chats == [("what is on my calendar?", "ask")]), chats)
check("LOKI's answer goes back to that chat", wait_for(lambda: "LOKI says: what is on my calendar?" in proc.texts("wxid_owner")),
      proc.texts())
before = len(proc.sent)
proc.emit({"event": "message", "user_id": "wxid_stranger", "chat_id": "wxid_stranger", "room": False, "self": False,
           "name": "X", "text": "hi"})
proc.emit({"event": "message", "user_id": "wxid_owner", "chat_id": "123@chatroom", "room": True, "self": False,
           "name": "Mohamed", "text": "LOKI in the group?"})
proc.emit({"event": "message", "user_id": "wxid_bot", "chat_id": "wxid_owner", "room": False, "self": True,
           "name": "LOKI bot", "text": "an echo of my own"})
ch.poll_once()
time.sleep(0.2)
check("a stranger gets one 'private bot' line, nothing else", proc.texts("wxid_stranger") == ["This is a private LOKI bot."], proc.texts())
check("group chats and the account's own messages are never answered or chatted",
      len(chats) == 1 and not proc.texts("123@chatroom") and len(proc.sent) == before + 1, proc.sent[before:])
pic = TMP / "fox.png"
pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
check("a picture goes back as a file", ch.photo("wxid_owner", pic, "a fox")
      and any(r.get("op") == "file" and r.get("path") == str(pic.resolve()) for r in proc.sent)
      and "a fox" in proc.texts("wxid_owner"))
try:
    ch.send_text("wxid_nobody", "x")
    check("LOKI can only answer chats that wrote to it", False)
except channels.ChannelError as exc:
    check("LOKI can only answer chats that wrote to it", "unknown chat" in str(exc))

# ----------------------------------------------------------------------------- off again, crashes, secrets
section("turning it off, a dead sidecar, no secret anywhere")
on["v"] = False
check("turning the add-on off stops the sidecar", not ch.configured() and proc.code == 0 and ch.proc is None)
on["v"] = True
ch.start_sidecar()
proc2 = FakeSidecar.started[-1]
proc2.emit({"fatal": "wechaty is not installed (python tools/setup_extras.py wechaty): Cannot find module"})
proc2.exit(1)
try:
    for _ in range(3):
        ch.poll_once()
    check("a dead sidecar raises a readable channel error", False)
except channels.ChannelError as exc:
    check("a dead sidecar raises a readable channel error", "setup_extras.py wechaty" in str(exc), exc)
check("...and the poll loop will start it again", ch.proc is None)
ch.fail("puppet said token %s is bad" % SECRET)
blob = json.dumps(ch.status())
check("the secret never shows in status or the log", SECRET not in blob and "***" in blob)

section("wired into LOKI")
src = (REPO / "engine" / "channels.py").read_text(encoding="utf-8")
check("channels.start starts it next to Telegram, gated by the add-on", "channel_wechaty.WechatyChannel(" in src
      and 'is_enabled("wechaty")' in src)
import portal_api  # noqa: E402
check("Settings > General: poll machine, network and the secret token",
      portal_api.GENERAL["LOKI_WECHATY_POLL"]["kind"] == "choice"
      and portal_api.GENERAL[channel_wechaty.SECRET_ENV]["kind"] == "secret"
      and portal_api.GENERAL["LOKI_WECHATY_PUPPET"]["default"] == channel_wechaty.DEFAULT_PUPPET)
check("the window shows a channel's own lines", "Array.isArray(ch.lines)" in (REPO / "app" / "ui" / "channels.js").read_text(encoding="utf-8"))
gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
check("the npm packages live in harness_data (ignored), never the repo", "harness_data" in gitignore
      and not (REPO / "node_modules" / "wechaty").exists())

ch.stop()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
