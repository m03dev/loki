"""Channels + voice tests: talking to LOKI from Telegram (engine/channels.py, channel_telegram.py)
and the mic / spoken replies (engine/voice_input.py, app/ui/voice.js).

    python tests/test_channels.py

Offline: a fake Telegram Bot API server on 127.0.0.1 (getMe, getUpdates, sendMessage, sendPhoto,
sendDocument, sendChatAction, setMyCommands, getFile + downloads, 401/409/429). Covers pairing
with the one-time code, owner-only answers, groups and strangers ignored, wrong-code limits,
splitting long replies, pictures sent as photos, /jobs /make /stop, rate limits, the poll
offset, one machine polling, voice notes, and that the token never shows up in logs, status
or any HTTP answer. Voice: engine detection, WAV upload checks, faster-whisper and whisper.cpp
through fakes, spoken replies, the bridge routes, and the window's hooks.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "data")
for key in list(os.environ):
    if key.startswith(("LOKI_TELEGRAM", "LOKI_CHANNEL", "LOKI_WHISPER", "LOKI_STT")):
        os.environ.pop(key, None)
sys.path.insert(0, str(REPO / "engine"))

import channels  # noqa: E402
import channel_telegram  # noqa: E402
import voice_input  # noqa: E402

PASS, FAIL = [], []
TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ"
OWNER, STRANGER, GROUP = 5550001, 5550002, -100777
LOG = io.StringIO()            # everything the channel prints


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ----------------------------------------------------------------------------- fake Telegram
class FakeTelegram:
    def __init__(self):
        self.updates = []          # (update_id, message)
        self.next_id = 100
        self.sent = []             # {"method", "chat_id", "text"/"file"...}
        self.calls = []
        self.fail_once = {}        # method -> (status, payload)
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 - file downloads
                path = urlparse(self.path).path
                if path == "/file/bot%s/voice/file_7.oga" % TOKEN:
                    body = b"OggS-fake-voice"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._json(404, {"ok": False, "description": "Not Found"})

            def do_POST(self):  # noqa: N802
                path = urlparse(self.path).path
                m = re.match(r"^/bot([^/]+)/(\w+)$", path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if not m:
                    return self._json(404, {"ok": False, "description": "Not Found"})
                token, method = m.group(1), m.group(2)
                with fake.lock:
                    fake.calls.append(method)
                if token != TOKEN:
                    return self._json(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
                with fake.lock:
                    failing = fake.fail_once.pop(method, None)
                if failing:
                    return self._json(failing[0], failing[1])
                kind = self.headers.get("Content-Type", "")
                if kind.startswith("multipart/form-data"):
                    params = fake.parse_multipart(raw, kind)
                else:
                    params = json.loads(raw.decode() or "{}")
                return self._json(200, {"ok": True, "result": fake.answer(method, params)})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    @staticmethod
    def parse_multipart(raw, kind):
        boundary = kind.split("boundary=", 1)[1].encode()
        out = {}
        for part in raw.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, body = part.split(b"\r\n\r\n", 1)
            body = body[:-2] if body.endswith(b"\r\n") else body
            name = re.search(rb'name="([^"]+)"', head)
            if not name:
                continue
            if b"filename=" in head:
                out[name.group(1).decode()] = {"bytes": body, "filename": re.search(rb'filename="([^"]*)"', head).group(1).decode()}
            else:
                out[name.group(1).decode()] = body.decode()
        return out

    def answer(self, method, params):
        if method == "getMe":
            return {"id": 42, "is_bot": True, "first_name": "Loki", "username": "my_loki_bot"}
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            with self.lock:
                return [{"update_id": uid, "message": msg} for uid, msg in self.updates if uid >= offset]
        if method == "getFile":
            return {"file_id": params.get("file_id"), "file_path": "voice/file_7.oga"}
        if method in ("sendMessage", "sendPhoto", "sendDocument", "sendChatAction"):
            with self.lock:
                self.sent.append({"method": method, **params})
            return {"message_id": len(self.sent)}
        return True

    def push(self, user, chat, text="", chat_type="private", is_bot=False, voice=None):
        msg = {"message_id": self.next_id, "from": {"id": user, "is_bot": is_bot, "first_name": "Mo"},
               "chat": {"id": chat, "type": chat_type}, "date": int(time.time())}
        if text:
            msg["text"] = text
        if voice:
            msg["voice"] = voice
        with self.lock:
            self.updates.append((self.next_id, msg))
            self.next_id += 1

    def texts(self, chat=None, method="sendMessage"):
        with self.lock:
            return [s.get("text", "") for s in self.sent if s["method"] == method and (chat is None or str(s.get("chat_id")) == str(chat))]

    def clear(self):
        with self.lock:
            self.sent.clear()


fake = FakeTelegram()


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0
        self.slept = []
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.now

    def sleep(self, seconds):
        with self.lock:
            self.slept.append(seconds)
            self.now += seconds

    def advance(self, seconds):
        with self.lock:
            self.now += seconds


# ----------------------------------------------------------------------------- the channel
WORKSPACE = TMP / "ws"
(WORKSPACE / "images").mkdir(parents=True)
chat_calls, make_calls, stops = [], [], []
making_state = []
chat_reply = {"code": 200, "payload": {"ok": True, "response": "hello from LOKI"}}
chat_gate = threading.Event()
chat_gate.set()
transcribed = []
voice_paths = []


def fake_chat(text, mode):
    chat_calls.append((text, mode))
    chat_gate.wait(10)
    return chat_reply["code"], dict(chat_reply["payload"])


def fake_pictures_since(since):
    # the channel's clock is fake here, so "new" pictures are the ones named with PICTURE_PREFIX
    return [(p, "a picture") for p in sorted((WORKSPACE / "images").glob("*.png")) if p.name.startswith(PICTURE_PREFIX[0])]


PICTURE_PREFIX = ["none"]


def fake_make(prompt):
    make_calls.append(prompt)
    making_state[:] = [{"id": "k1", "prompt": prompt, "start": 1, "end": 0}]
    return {"ok": True, "id": "k1"}


CALLBACKS = {"chat": fake_chat, "jobs": lambda: [
                 {"id": "j1", "title": "Write the report", "status": "running", "created": 3, "machine": "pc"},
                 {"id": "j2", "title": "Fox picture", "status": "failed", "error": "no model", "created": 2},
                 {"id": "j3", "title": "Old thing", "status": "done", "created": 1}],
             "make": fake_make, "making": lambda: list(making_state), "pictures_since": fake_pictures_since,
             "stop": lambda: stops.append(1), "machine": lambda: "testpc (PC)",
             "transcribe": lambda path: (transcribed.append(Path(path).read_bytes()), voice_paths.append(Path(path)),
                                         {"ok": True, "text": "what is on today"})[-1]}

ENV = {"LOKI_TELEGRAM_TOKEN": TOKEN, "LOKI_TELEGRAM_API": fake.base, "LOKI_TELEGRAM_POLL": "on",
       "LOKI_TELEGRAM_LONGPOLL": "0"}
clock = Clock()
store = channels.Store(TMP / "data" / "channels" / "telegram.json")
tg = channel_telegram.TelegramChannel(CALLBACKS, store=store, env=ENV, clock=clock, sleep=clock.sleep, platform="darwin")
tg.make_poll_s = 0.05


def poll():
    with contextlib.redirect_stdout(LOG):
        return tg.poll_once()


section("helpers")
pieces = channels.split_text(("para one. " * 300) + "\n\n" + ("x" * 5000), 4000)
check("split_text keeps every piece under the limit", pieces and all(len(p) <= 4000 for p in pieces), [len(p) for p in pieces])
check("split_text loses nothing (short of the cap)", "".join(p.replace(" ", "").replace("\n", "") for p in pieces)
      == (("para one. " * 300) + ("x" * 5000)).replace(" ", ""))
check("split_text breaks at a paragraph first", pieces[0].endswith("para one."), pieces[0][-20:])
many = channels.split_text("word " * 20000, 1000)
check("split_text caps the number of pieces and says the rest is on the computer",
      len(many) == channels.MAX_CHUNKS and "on the computer" in many[-1] and len(many[-1]) <= 1000)
check("split_text of nothing is nothing", channels.split_text("   ", 100) == [])
check("redact removes the token and Telegram URLs", "AAHdq" not in channels.redact(
      "GET https://api.telegram.org/bot%s/getMe failed; token %s" % (TOKEN, TOKEN)))
check("redact removes a bare token it was not told about", "AAHdq" not in channels.redact("x " + TOKEN))
check("poll_here auto: the Windows PC polls", channels.poll_here("telegram", {}, "win32")[0] is True)
check("poll_here auto: the Mac does not (and says how to change it)", channels.poll_here("telegram", {}, "darwin")[0] is False
      and "LOKI_TELEGRAM_POLL=on" in channels.poll_here("telegram", {}, "darwin")[1])
check("poll_here on / off override", channels.poll_here("telegram", {"LOKI_TELEGRAM_POLL": "on"}, "darwin")[0] is True
      and channels.poll_here("telegram", {"LOKI_TELEGRAM_POLL": "off"}, "win32")[0] is False)
check("channel mode is ask or plan only", channels.channel_mode({"LOKI_CHANNEL_MODE": "build"}) == "ask"
      and channels.channel_mode({"LOKI_CHANNEL_MODE": "plan"}) == "plan")
check("the API base must be https or this computer", channel_telegram.api_base({"LOKI_TELEGRAM_API": "http://evil.example"})
      == channel_telegram.DEFAULT_API and channel_telegram.api_base({"LOKI_TELEGRAM_API": fake.base}) == fake.base)

section("connect, strangers and pairing")
poll()
check("getMe on the first poll; the bot's name is known", tg.bot.get("username") == "my_loki_bot")
check("the / menu is set (setMyCommands)", "setMyCommands" in fake.calls)
fake.push(STRANGER, STRANGER, "hi there")
poll()
check("a stranger gets one short 'private bot' reply", fake.texts(STRANGER) == ["This is a private LOKI bot."], fake.texts(STRANGER))
fake.push(STRANGER, STRANGER, "hello again")
poll()
check("... and nothing more within the hour", len(fake.texts(STRANGER)) == 1)
fake.push(STRANGER, GROUP, "/start", chat_type="group")
fake.push(STRANGER, GROUP, "anyone?", chat_type="group")
poll()
check("group chats are ignored", fake.texts(GROUP) == [])
check("the poll offset is saved (nothing is fetched twice)", store.load().get("offset") == fake.next_id)
check("no pairing without a code from Settings: /start does nothing for a stranger",
      poll() == 0 and not store.load().get("owner"))
fake.push(STRANGER, STRANGER, "/start ABCDEFGH")
poll()
check("/start with a code when no code is live pairs nobody", not store.load().get("owner"))

pairing = tg.new_code()
check("a pairing code: 8 letters, 15 minutes, with the t.me link", len(pairing["code"]) == 8
      and pairing["expires_in"] == 900 and pairing["link"] == "https://t.me/my_loki_bot?start=" + pairing["code"])
fake.clear()
for i in range(channels.BAD_CODE_PER_CHAT):
    fake.push(STRANGER, STRANGER, "/start WRONG%03d" % i)
fake.push(STRANGER, STRANGER, "/start " + pairing["code"])
poll()
check("wrong codes are refused", fake.texts(STRANGER).count("That code is not right.") == channels.BAD_CODE_PER_CHAT)
check("after %d wrong codes that chat cannot pair even with the right one" % channels.BAD_CODE_PER_CHAT,
      not store.load().get("owner"))
fake.push(OWNER, OWNER, "/start " + pairing["code"].lower())
poll()
owner = store.load().get("owner") or {}
check("the right code (any case) pairs the owner's private chat", owner.get("user_id") == str(OWNER) and owner.get("chat_id") == str(OWNER), owner)
check("pairing says hello and lists the commands", any("Paired" in t and "/make" in t for t in fake.texts(OWNER)))
check("the store holds no token", TOKEN not in (TMP / "data" / "channels" / "telegram.json").read_text())
fake.push(STRANGER, 99999, "/start " + pairing["code"])
poll()
check("the code is single-use", (store.load().get("owner") or {}).get("user_id") == str(OWNER))
check("status: paired, owner's name, no live code", tg.status()["paired"] and tg.status()["owner"]["name"] == "Mo"
      and tg.status()["pairing"] is None)

section("burned codes")
code2 = tg.new_code()["code"]
for i in range(channels.BAD_CODE_TOTAL):
    fake.push(700000 + i, 700000 + i, "/start BAD%05d" % i)
    clock.advance(0)
poll()
check("after %d wrong codes in total the code is burned" % channels.BAD_CODE_TOTAL, tg._code == "")
fake.push(800001, 800001, "/start " + code2)
poll()
check("... so even the right one no longer pairs", (store.load().get("owner") or {}).get("user_id") == str(OWNER))
clock.advance(channels.BAD_CODE_WINDOW_S + 1)
clock.advance(channels.STRANGER_REPLY_EVERY_S + 1)
expired = tg.new_code()["code"]
clock.advance(channels.PAIR_TTL_S + 1)
fake.push(800002, 800002, "/start " + expired)
poll()
check("an expired code pairs nobody", (store.load().get("owner") or {}).get("user_id") == str(OWNER))

section("the owner talks to LOKI")
fake.clear()
fake.push(OWNER, OWNER, "what can you do?")
poll()
check("a message becomes a LOKI chat, in ask mode", wait_for(lambda: chat_calls and chat_calls[-1] == ("what can you do?", "ask")), chat_calls)
check("the answer goes back", wait_for(lambda: "hello from LOKI" in fake.texts(OWNER)), fake.texts(OWNER))
check("'typing...' is shown while LOKI works", wait_for(lambda: any(s["method"] == "sendChatAction" for s in fake.sent)))
fake.push(OWNER, GROUP, "from a group", chat_type="group")
poll()
check("the owner in a group is not answered (private chat only)", fake.texts(GROUP) == [] and chat_calls[-1][0] != "from a group")
fake.push(OWNER, OWNER + 1, "other private chat")
poll()
check("the owner's user id from another chat id is not answered", chat_calls[-1][0] != "other private chat")
fake.push(OWNER, OWNER, "I am a bot", is_bot=True)
poll()
check("a bot account is never the owner", chat_calls[-1][0] != "I am a bot")

fake.clear()
ENV["LOKI_CHANNEL_MODE"] = "plan"
long_answer = ("A long answer paragraph. " * 200 + "\n\n") * 3
chat_reply["payload"] = {"ok": True, "response": long_answer}
PICTURE_PREFIX[0] = "made-"
(WORKSPACE / "images" / "made-fox.png").write_bytes(PNG)
before = len(fake.texts(OWNER))
clock.advance(61)
fake.push(OWNER, OWNER, "write me a lot")
poll()
check("LOKI_CHANNEL_MODE=plan is used", wait_for(lambda: chat_calls[-1] == ("write me a lot", "plan")))
check("a long reply is split into pieces under 4096", wait_for(lambda: len(fake.texts(OWNER)) >= before + 4)
      and all(len(t) <= 4096 for t in fake.texts(OWNER)), [len(t) for t in fake.texts(OWNER)])
check("... in order, nothing lost", "".join(fake.texts(OWNER)).replace(" ", "").replace("\n", "")
      == long_answer.replace(" ", "").replace("\n", ""))
check("messages into one chat are spaced (about 1 s apart, as Telegram asks)", any(1.0 <= s <= 1.06 for s in clock.slept), clock.slept[:5])
check("a picture LOKI made while answering is sent as a photo", wait_for(lambda: any(
      s["method"] == "sendPhoto" and s.get("photo", {}).get("bytes") == PNG for s in fake.sent)))
check("... to the owner's chat", any(s["method"] == "sendPhoto" and s.get("chat_id") == str(OWNER) for s in fake.sent))
ENV.pop("LOKI_CHANNEL_MODE")
PICTURE_PREFIX[0] = "none"

section("busy, errors and limits")
chat_reply["payload"] = {"ok": True, "response": "slow answer"}
chat_gate.clear()
fake.clear()
clock.advance(61)
fake.push(OWNER, OWNER, "first")
poll()
wait_for(lambda: chat_calls[-1][0] == "first")
fake.push(OWNER, OWNER, "second")
poll()
check("one chat at a time: a second message is told to wait (/stop)", wait_for(lambda: any("still on your last message" in t for t in fake.texts(OWNER))))
chat_gate.set()
wait_for(lambda: "slow answer" in fake.texts(OWNER))
wait_for(lambda: not tg._busy.locked())
chat_reply.update(code=409, payload={"ok": False, "error": "busy"})
fake.clear()
fake.push(OWNER, OWNER, "are you there")
poll()
check("LOKI busy on the computer (409) -> a friendly 'try again'", wait_for(lambda: any("busy with something" in t for t in fake.texts(OWNER))))
wait_for(lambda: not tg._busy.locked())
chat_reply.update(code=502, payload={"ok": False, "error": "model failed with key %s" % TOKEN})
fake.clear()
fake.push(OWNER, OWNER, "break please")
poll()
check("an error goes back redacted", wait_for(lambda: any("could not answer" in t for t in fake.texts(OWNER)))
      and not any(TOKEN in t for t in fake.texts(OWNER)))
wait_for(lambda: not tg._busy.locked())
chat_reply.update(code=200, payload={"ok": True, "response": "ok"})
fake.clear()
clock.advance(61)
for i in range(channels.CHAT_PER_MIN + 1):
    wait_for(lambda: not tg._busy.locked())
    fake.push(OWNER, OWNER, "msg %d" % i)
    poll()
check("at most %d messages a minute" % channels.CHAT_PER_MIN, wait_for(lambda: any("Slow down" in t for t in fake.texts(OWNER))))
wait_for(lambda: not tg._busy.locked())
clock.advance(61)
fake.push(OWNER, OWNER, "x" * (channels.MAX_INCOMING + 1))
poll()
check("a too-long message is refused", wait_for(lambda: any("too long" in t for t in fake.texts(OWNER))))

section("commands")
fake.clear()
clock.advance(61)
fake.push(OWNER, OWNER, "/jobs")
poll()
jobs_text = (fake.texts(OWNER) or [""])[-1]
check("/jobs lists background jobs, running first", jobs_text.startswith("Background jobs (3)") and
      jobs_text.index("Write the report") < jobs_text.index("Fox picture") and "(on pc)" in jobs_text and "no model" in jobs_text, jobs_text)
fake.push(OWNER, OWNER, "/stop")
poll()
check("/stop stops what LOKI is doing", stops == [1] and any("Stopping" in t for t in fake.texts(OWNER)))
fake.push(OWNER, OWNER, "/help@my_loki_bot")
poll()
check("/help (also /cmd@botname) lists the commands", any("/jobs" in t and "/stop" in t for t in fake.texts(OWNER)))
fake.push(OWNER, OWNER, "/rm -rf")
poll()
check("an unknown command is refused politely", any("I do not know /rm" in t for t in fake.texts(OWNER)))
fake.push(OWNER, OWNER, "/make")
poll()
check("/make without a prompt says how", any("Say what to make" in t for t in fake.texts(OWNER)))
fake.clear()
PICTURE_PREFIX[0] = "fox-"
fake.push(OWNER, OWNER, "/make a fox asleep in the snow")
poll()
check("/make starts the image specialist directly", make_calls == ["a fox asleep in the snow"])
check("... and says it is making it", wait_for(lambda: any("Making it" in t for t in fake.texts(OWNER))))
(WORKSPACE / "images" / "fox-asleep.png").write_bytes(PNG + b"fox")
making_state[0].update(end=time.time(), ok=True, result="made images/fox-asleep.png with zimage")
check("the picture is sent as a photo when it is done", wait_for(lambda: any(
      s["method"] == "sendPhoto" and s.get("photo", {}).get("bytes") == PNG + b"fox" and "fox asleep" in s.get("caption", "")
      for s in fake.sent)))
fake.clear()
making_state[:] = []
fake_make_fail = {"n": 0}


def failing_make(prompt):
    making_state[:] = [{"id": "k2", "prompt": prompt, "start": 1, "end": time.time(), "ok": False, "result": "error: no image model"}]
    return {"ok": True, "id": "k2"}


CALLBACKS["make"] = failing_make
fake.push(OWNER, OWNER, "/make a broken thing")
poll()
check("a failed picture says why", wait_for(lambda: any("picture failed: error: no image model" in t for t in fake.texts(OWNER))))
CALLBACKS["make"] = fake_make
PICTURE_PREFIX[0] = "none"
fake.clear()
clock.advance(61)
for i in range(channels.COMMANDS_PER_MIN + 1):
    fake.push(OWNER, OWNER, "/help")
poll()
check("at most %d commands a minute" % channels.COMMANDS_PER_MIN, any("at most %d commands" % channels.COMMANDS_PER_MIN in t for t in fake.texts(OWNER)))

section("voice notes")
fake.clear()
clock.advance(61)
fake.push(OWNER, OWNER, voice={"file_id": "F7", "file_unique_id": "u", "duration": 2, "file_size": 15})
poll()
check("a voice note is downloaded and transcribed", wait_for(lambda: transcribed == [b"OggS-fake-voice"]), transcribed)
check("... the owner sees what LOKI heard", wait_for(lambda: any(t == "Heard: what is on today" for t in fake.texts(OWNER))))
check("... and it becomes a chat", wait_for(lambda: chat_calls[-1][0] == "what is on today"))
check("the downloaded voice note is deleted", wait_for(lambda: voice_paths and not voice_paths[0].exists()), voice_paths)
no_stt = dict(CALLBACKS)
no_stt.pop("transcribe")
tg.callbacks = no_stt
wait_for(lambda: not tg._busy.locked())
fake.push(OWNER, OWNER, voice={"file_id": "F7", "duration": 2})
poll()
check("without Whisper a voice note says how to install it", wait_for(lambda: any("Add-ons > whisper" in t for t in fake.texts(OWNER))))
tg.callbacks = CALLBACKS

section("Telegram errors: 429, 401, 409 - never the token")
fake.clear()
clock.slept.clear()
fake.fail_once["sendMessage"] = (429, {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 3",
                                       "parameters": {"retry_after": 3}})
tg.say(OWNER, "after a 429")
check("a 429 is retried after Telegram's retry_after", fake.texts(OWNER) == ["after a 429"] and 3 in clock.slept, clock.slept)
fake.fail_once["getUpdates"] = (409, {"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"})
try:
    poll()
    conflict = None
except channels.ChannelError as exc:
    conflict = exc
check("a second poller (409) is reported as such", conflict is not None and conflict.code == 409
      and "other machine" in str(conflict), conflict)
bad_env = dict(ENV, LOKI_TELEGRAM_TOKEN="999999:WRONGWRONGWRONGWRONGWRONGWRONGWRONG")
bad = channel_telegram.TelegramChannel(CALLBACKS, store=channels.Store(TMP / "bad.json"), env=bad_env, clock=clock, sleep=clock.sleep)
try:
    with contextlib.redirect_stdout(LOG):
        bad.poll_once()
    err = None
except channels.ChannelError as exc:
    err = exc
    with contextlib.redirect_stdout(LOG):
        bad.fail(exc)
check("a wrong token -> 401 with a hint", err is not None and err.code == 401 and "@BotFather" in str(err), err)
check("... and the error does not contain it", "WRONGWRONG" not in str(err) and "WRONGWRONG" not in bad.last_error)
unreachable = channel_telegram.TelegramChannel(CALLBACKS, store=channels.Store(TMP / "u.json"),
                                               env=dict(ENV, LOKI_TELEGRAM_API="http://127.0.0.1:9"), clock=clock, sleep=clock.sleep)
try:
    unreachable.me()
    err = None
except channels.ChannelError as exc:
    err = exc
check("Telegram unreachable -> a clear error without the URL", err is not None and "cannot reach" in str(err)
      and TOKEN not in str(err) and "/bot" not in str(err), err)

section("the loop: one machine polls")
loop_env = dict(ENV, LOKI_TELEGRAM_POLL="auto")
looped = channel_telegram.TelegramChannel(CALLBACKS, store=channels.Store(TMP / "loop.json"), env=loop_env, platform="darwin")
looped.idle_s = 0.1
looped.store.update(offset=fake.next_id)     # only new messages
looped.start()
time.sleep(0.3)
check("auto on the Mac: the loop idles (does not poll)", not looped.polling and looped.status()["poll_here"] is False)
loop_env["LOKI_TELEGRAM_POLL"] = "on"            # Settings > General changes it live
check("switching it on starts polling without a restart", wait_for(lambda: looped.polling and looped.last_poll, 10))
loop_env["LOKI_TELEGRAM_TOKEN"] = ""
check("no token: the loop stops polling", wait_for(lambda: not looped.polling, 10))
looped.stop()
check("status of an unconfigured channel says no token", looped.status()["token_saved"] is False)

section("the token never leaks")
status_json = json.dumps(tg.status())
check("status() has no token", TOKEN not in status_json and "AAHdq" not in status_json)
check("the channel log has no token and no message text", TOKEN not in json.dumps(tg.log)
      and "what can you do" not in json.dumps(tg.log))
check("nothing printed contains the token", TOKEN not in LOG.getvalue() and "WRONGWRONG" not in LOG.getvalue(), LOG.getvalue()[-300:])

section("Settings: the secret setting and the /channels routes")
import portal_api  # noqa: E402

check("LOKI_TELEGRAM_TOKEN is a secret setting", portal_api.GENERAL["LOKI_TELEGRAM_TOKEN"]["kind"] == "secret")
check("LOKI_TELEGRAM_POLL is auto/on/off (default auto)", portal_api.GENERAL["LOKI_TELEGRAM_POLL"]["choices"] == ["auto", "on", "off"]
      and portal_api.GENERAL["LOKI_TELEGRAM_POLL"]["default"] == "auto")
check("LOKI_CHANNEL_MODE offers ask and plan only", portal_api.GENERAL["LOKI_CHANNEL_MODE"]["choices"] == ["ask", "plan"])


class FakeState:
    pass


fs = FakeState()
fs.channels = {"telegram": tg}
code, out = channels.ui_route(fs, "GET", "/channels", {})
check("GET /channels lists the channel", code == 200 and out["channels"][0]["name"] == "telegram" and out["channels"][0]["token_saved"])
code, out = channels.ui_route(fs, "POST", "/channels/pair", {"channel": "telegram"})
check("POST /channels/pair makes a code", code == 200 and len(out["code"]) == 8 and out["status"]["pairing"]["code"] == out["code"])
code, out = channels.ui_route(fs, "POST", "/channels/test", {"channel": "telegram"})
check("POST /channels/test checks the bot", code == 200 and out["status"]["bot"]["username"] == "my_loki_bot")
check("none of them return the token", TOKEN not in json.dumps([channels.ui_route(fs, "GET", "/channels", {})[1], out]))
check("POST /channels/nope -> 404", channels.ui_route(fs, "POST", "/channels/nope", {})[0] == 404)
check("an unknown channel -> 404", channels.ui_route(fs, "POST", "/channels/pair", {"channel": "irc"})[0] == 404)
check("not our route -> None", channels.ui_route(fs, "GET", "/phones", {}) is None)

section("the engine side: callbacks")
import phone_link  # noqa: E402

seen = {}


def fake_chat_once(state, agent, message, mode, timeout_s=0):
    seen.update(message=message, mode=mode)
    return 200, {"ok": True, "response": "via chat_once"}


real_chat_once = phone_link.chat_once
phone_link.chat_once = fake_chat_once


class EngineState:
    jobs = None
    noted = 0

    def note_request(self):
        EngineState.noted += 1


class EngineAgent:
    WORKSPACE = WORKSPACE
    cancelled = 0

    def request_cancel(self):
        EngineAgent.cancelled += 1


cbs = channels.callbacks(EngineState(), EngineAgent())
phone_link.chat_once = real_chat_once
check("a channel chat goes through phone_link.chat_once (Ask/Plan, approvals denied)",
      cbs["chat"].__code__.co_names.count("chat_once") == 1)
phone_link.chat_once = fake_chat_once
check("... and counts as the owner's request (the autopilot waits)", cbs["chat"]("hi", "ask") == (200, {"ok": True, "response": "via chat_once"})
      and seen == {"message": "hi", "mode": "ask"} and EngineState.noted == 1)
phone_link.chat_once = real_chat_once
check("no job supervisor -> no jobs", cbs["jobs"]() == [])
cbs["stop"]()
check("stop cancels the agent's request", EngineAgent.cancelled == 1)
pics = cbs["pictures_since"](time.time() - 60)
check("pictures_since finds images made since then", any(p.name == "fox-asleep.png" for p, _ in pics), pics)
check("... and only images", all(p.suffix == ".png" for p, _ in pics))
os.environ["LOKI_STT"] = "off"
heard = cbs["transcribe"](TMP / "nothing.oga")
os.environ.pop("LOKI_STT")
check("voice notes look for Whisper each time (no restart after installing it)", heard["ok"] is False
      and "Add-ons > whisper" in heard["error"], heard)
check("chat_once really denies approvals (the safety this relies on)", "agent.approve = _deny" in (REPO / "engine" / "phone_link.py").read_text())

section("voice: speech to text")
check("no engine -> nothing, with an install hint", voice_input.detect({}, which=lambda n: None, importer=lambda n: None)["engine"] == ""
      and "Add-ons > whisper" in voice_input.detect({}, which=lambda n: None, importer=lambda n: None)["install"])
check("faster-whisper when the package is there", voice_input.detect({}, which=lambda n: None,
      importer=lambda n: object() if n == "faster_whisper" else None)["engine"] == "faster-whisper")
models = TMP / "data" / "models" / "whisper"
models.mkdir(parents=True)
check("whisper.cpp without a model is not enough", voice_input.detect({}, which=lambda n: "/usr/bin/" + n if n == "whisper-cli" else None,
      importer=lambda n: None)["engine"] == "")
(models / "ggml-base.bin").write_bytes(b"ggml")
cpp = voice_input.detect({}, which=lambda n: "/usr/bin/" + n if n == "whisper-cli" else None, importer=lambda n: None)
check("whisper.cpp with a ggml model in harness_data/models/whisper", cpp["engine"] == "whisper.cpp" and "ggml-base.bin" in cpp["detail"], cpp)
check("LOKI_STT=off turns it off", voice_input.detect({"LOKI_STT": "off"}, importer=lambda n: object())["engine"] == "")


def wav(seconds=0.5):
    n = int(16000 * seconds)
    data = b"\x00\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


good = "data:audio/wav;base64," + base64.b64encode(wav()).decode()
check("a WAV data URL is accepted", voice_input.decode_wav_upload(good)[:4] == b"RIFF")
for name, bad_url in [("not a data URL", "hello"), ("another type", "data:audio/webm;base64,AAAA"),
                      ("not base64", "data:audio/wav;base64,!!!"), ("not a WAV", "data:audio/wav;base64," + base64.b64encode(b"x" * 60).decode())]:
    try:
        voice_input.decode_wav_upload(bad_url)
        check("refused: " + name, False)
    except ValueError:
        check("refused: " + name, True)
huge = "data:audio/wav;base64," + "A" * (voice_input.MAX_UPLOAD_BYTES * 2)
try:
    voice_input.decode_wav_upload(huge)
    check("refused: too long", False)
except ValueError as exc:
    check("refused: too long", "too long" in str(exc))


class Seg:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, size, device="", compute_type=""):
        self.args = (size, device, compute_type)

    def transcribe(self, path, language=None, vad_filter=False):
        assert Path(path).read_bytes()[:4] == b"RIFF"
        return iter([Seg(" hello"), Seg(" LOKI ")]), {"language": "en"}


voice_input._MODEL.clear()
res = voice_input.transcribe_upload(good, env={}, which=lambda n: None, importer=lambda n: object() if n == "faster_whisper" else None,
                                     loader=FakeModel)
check("faster-whisper: the recording becomes text", res == {"ok": True, "text": "hello LOKI", "engine": "faster-whisper"}, res)
check("... int8 on the best device, model 'base' by default", voice_input._MODEL["base"].args == ("base", "auto", "int8"))
check("the upload is not kept on disk", not list(Path(tempfile.gettempdir()).glob("loki-mic-*")))
runs = []


class Proc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def runner(argv, **kw):
    runs.append(argv)
    if Path(argv[0]).name == "ffmpeg":
        Path(argv[-1]).write_bytes(wav())
        return Proc()
    return Proc(0, " hello from cpp \n second line\n")


cpp_which = lambda n: ("/usr/bin/" + n) if n in ("whisper-cli", "ffmpeg") else None  # noqa: E731
res = voice_input.transcribe_upload(good, env={}, which=cpp_which, importer=lambda n: None, runner=runner)
check("whisper.cpp: argv without a shell, -nt -np, language auto", res.get("text") == "hello from cpp second line"
      and runs[-1][:2] == ["/usr/bin/whisper-cli", "-m"] and "-nt" in runs[-1] and runs[-1][-2:] == ["-l", "auto"], (res, runs))
ogg = TMP / "note.oga"
ogg.write_bytes(b"OggS")
runs.clear()
res = voice_input.transcribe(ogg, env={}, which=cpp_which, importer=lambda n: None, runner=runner)
check("whisper.cpp + a voice note: ffmpeg converts to 16 kHz mono WAV first", res.get("ok") and Path(runs[0][0]).name == "ffmpeg"
      and runs[0][runs[0].index("-ar") + 1] == "16000" and runs[1][0].endswith("whisper-cli"), runs)
res = voice_input.transcribe(ogg, env={}, which=lambda n: "/usr/bin/whisper-cli" if n == "whisper-cli" else None,
                             importer=lambda n: None, runner=runner)
check("... and says ffmpeg is needed when it is missing", not res["ok"] and "ffmpeg" in res["error"])
res = voice_input.transcribe(ogg, env={}, which=cpp_which, importer=lambda n: None,
                             runner=lambda argv, **k: Proc(1, "", "boom") if "whisper-cli" in argv[0] else runner(argv))
check("a failing whisper.cpp is reported", not res["ok"] and "boom" in res["error"])
res = voice_input.transcribe(ogg, env={}, which=lambda n: None, importer=lambda n: None)
check("no engine: transcribe says how to install one", not res["ok"] and "Add-ons > whisper" in res["error"])

section("voice: spoken replies")
said = voice_input.speakable("# Title\n**Bold** and `code` and [a link](http://x).\n```py\nprint(1)\n```\n- item")
check("speakable drops Markdown and code blocks", "**" not in said and "print(1)" not in said and "a link" in said and "http" not in said, said)
check("speakable caps long replies", len(voice_input.speakable("Sentence here. " * 400)) <= voice_input.MAX_SPOKEN_CHARS)
spoken = []


def fake_speaker(text, folder, voice_name):
    spoken.append(text)
    out = Path(folder) / "x.wav"
    out.write_bytes(wav(0.1))
    return {"ok": True, "file": out, "engine": "kokoro"}


res = voice_input.speak_reply("**Hello** there", speaker=fake_speaker)
check("speak_reply returns a WAV data URL", res["ok"] and res["audio"].startswith("data:audio/wav;base64,") and spoken == ["Hello there"], res.get("error"))
check("... and keeps no file", not list(Path(tempfile.gettempdir()).glob("loki-say-*")))
check("speak_reply reports a missing voice", voice_input.speak_reply("hi", speaker=lambda *a: {"ok": False, "error": "no voice"})["ok"] is False)
code, out = voice_input.ui_route(None, "GET", "/voice", {})
check("GET /voice: stt + tts status", code == 200 and "engine" in out["stt"] and "engine" in out["tts"])
code, out = voice_input.ui_route(None, "POST", "/voice/transcribe", {"audio": "nope"})
check("POST /voice/transcribe with a bad upload -> 400", code == 400 and not out["ok"])
check("POST /voice/speak with no text -> 400", voice_input.ui_route(None, "POST", "/voice/speak", {})[0] == 400)
check("not a voice route -> None", voice_input.ui_route(None, "GET", "/voicemail", {}) is None)

section("over the real bridge HTTP server")
import http.client  # noqa: E402

import loki_bridge  # noqa: E402


class BridgeAgent:
    model_name = "local"
    WORKSPACE = WORKSPACE

    def env_file_path(self):
        return str(TMP / "data" / ".env")


loki_bridge.PORT = 0
bstate = loki_bridge.BridgeState(BridgeAgent(), "chan-secret")
bstate.channels = {"telegram": tg}
bserver = loki_bridge.BridgeHTTPServer(bstate)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def http_call(method, path, body=None, token="chan-secret"):
    conn = http.client.HTTPConnection("127.0.0.1", bserver.server_address[1], timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read()
    return resp.status, raw


os.environ["LOKI_TELEGRAM_TOKEN"] = TOKEN
try:
    replies = []
    for method, path, body in [("GET", "/channels", None), ("POST", "/channels/pair", {"channel": "telegram"}),
                               ("POST", "/channels/test", {"channel": "telegram"}), ("GET", "/settings/general", None),
                               ("GET", "/voice", None), ("POST", "/voice/transcribe", {"audio": "x"})]:
        replies.append((path,) + http_call(method, path, body))
    codes = {p: c for p, c, _ in replies}
    check("the bridge serves /channels, /channels/pair, /channels/test", codes["/channels"] == 200 and codes["/channels/pair"] == 200
          and codes["/channels/test"] == 200, codes)
    check("the bridge serves /voice and /voice/transcribe", codes["/voice"] == 200 and codes["/voice/transcribe"] == 400, codes)
    general = json.loads(dict((p, r) for p, _, r in replies)["/settings/general"])
    check("Settings > General says the token is saved", general["secrets_saved"].get("LOKI_TELEGRAM_TOKEN") is True
          and general["values"]["LOKI_TELEGRAM_TOKEN"] == "")
    check("no HTTP answer carries the token", not any(TOKEN.encode() in raw or b"AAHdq" in raw for _, _, raw in replies))
    check("a wrong bearer token is refused", http_call("GET", "/channels", token="nope")[0] == 401)
finally:
    os.environ.pop("LOKI_TELEGRAM_TOKEN", None)
    bserver.shutdown()
    bserver.server_close()

section("wiring: bridge, Settings, add-on, window")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge starts the channels at boot (optional, never blocks chat)", "channels.start(state, loki)" in bridge)
check("... and stops them on exit", "channel.stop()" in bridge)
check("the window may play audio data (CSP media-src)", "media-src 'self' data: blob:" in loki_bridge.UI_CSP
      and "script-src 'self'" in loki_bridge.UI_CSP)
import addons_install  # noqa: E402
import manifests  # noqa: E402

check("Add-ons: whisper installs faster-whisper", addons_install.pip_specs("whisper") == ["faster-whisper"])
manifest = json.loads((REPO / "capabilities" / "whisper" / "manifest.json").read_text(encoding="utf-8"))
check("the whisper add-on manifest is valid", manifests.validate(manifest) == [] and manifest["requires_python"] == ["faster_whisper"])
ui = REPO / "app" / "ui"
index = (ui / "index.html").read_text(encoding="utf-8")
voice_js = (ui / "voice.js").read_text(encoding="utf-8")
icons = (ui / "icons.js").read_text(encoding="utf-8")
check("index.html loads voice.js and channels.js", '<script src="/ui/voice.js" defer></script>' in index
      and '<script src="/ui/channels.js" defer></script>' in index)
check("icons.js has mic, speaker and speakerOff icons", all(("  %s: '" % n) in icons for n in ("mic", "speaker", "speakerOff")))
check("the mic button uses the data-icon pattern with a tooltip", 'button("mic", "mic", "Talk"' in voice_js
      and "b.dataset.icon = icon" in voice_js and "b.dataset.tipWhat = what" in voice_js)
check("voice.js: Whisper first, then the webview's recognition, else an install hint",
      "hasWhisper() && canRecord" in voice_js and "else if (SR)" in voice_js and "Settings > Add-ons > whisper" in voice_js)
check("voice.js handles a missing SpeechRecognition (WKWebView) and getUserMedia", "window.webkitSpeechRecognition || null" in voice_js
      and "navigator.mediaDevices && navigator.mediaDevices.getUserMedia" in voice_js)
check("voice.js explains mic permission on both systems", "Privacy & Security > Microphone > Loki" in voice_js
      and "Let desktop apps access your microphone" in voice_js)
check("voice.js records 16 kHz WAV and posts it to /voice/transcribe", "RATE = 16000" in voice_js and '"/voice/transcribe"' in voice_js)
check("spoken replies: a speaker toggle, kept per window", '"speak-replies"' in voice_js and "loki.speakReplies" in voice_js)
check("app.js hands each reply to Voice.afterReply", "Voice.afterReply(reply)" in (ui / "app.js").read_text(encoding="utf-8"))
check("Settings > General shows the Telegram pairing card", "Channels.render(box)" in (ui / "settings.js").read_text(encoding="utf-8")
      and '"/channels/pair"' in (ui / "channels.js").read_text(encoding="utf-8"))
plist = (REPO / "tools" / "macos" / "make_loki_app.sh").read_text(encoding="utf-8")
check("Loki.app asks for the microphone (NSMicrophoneUsageDescription)", "NSMicrophoneUsageDescription" in plist
      and "NSSpeechRecognitionUsageDescription" in plist)
check("ship.py runs this suite", '"test_channels"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
check("docs: E10 and E7 ticked in EVOLVE.md", "- [x] E10" in (REPO / "docs" / "EVOLVE.md").read_text(encoding="utf-8")
      and "- [x] E7" in (REPO / "docs" / "EVOLVE.md").read_text(encoding="utf-8"))
check("docs/PHONE.md points to Telegram", "Telegram" in (REPO / "docs" / "PHONE.md").read_text(encoding="utf-8"))

tg.stop()
fake.httpd.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
