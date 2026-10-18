"""Channels - talk to LOKI from anywhere through a chat app (EVOLVE E10). Telegram first.

The owner makes a bot with @BotFather and pastes its token in Settings > General
(LOKI_TELEGRAM_TOKEN, a secret setting: saved in harness_data/.env, never sent back to the
window). LOKI then long-polls the chat app (stdlib urllib, no SDK) and:

  * answers ONLY its owner. Pairing: Settings shows a one-time code (8 letters, 15 minutes,
    single use); the owner sends `/start <code>` to the bot (or opens the t.me link Settings
    shows, which does the same). That private chat - and that Telegram user - is the owner from
    then on. Everybody else is ignored (one short "this is a private bot" an hour at most).
    Wrong codes are limited per chat and in total; too many and the code is burned.
  * turns a message into a LOKI chat through the same agent path as the window's /chat
    (phone_link.chat_once: BridgeState.request_chat), in Ask or Plan mode only
    (LOKI_CHANNEL_MODE), and a chat message can never approve anything - every approval is
    denied while it runs, exactly like the phone link. Building stays on the computer.
  * sends the answer back, split into pieces the app accepts (Telegram: 4096 characters), and
    the pictures LOKI made while answering (Creations) as photos.
  * commands: /jobs (background jobs), /make <prompt> (a picture, straight to the image
    specialist like Settings > Creations, sent back when it is done), /stop (stop what LOKI is
    doing now), /help. Nothing else is exposed: no files, no settings, no shell, no approvals.
  * rate limits: messages and commands per minute from the owner; outgoing messages are spaced
    as the chat app asks (and its 429 retry_after is honoured).
  * never logs the token: every error and log line goes through redact(); /channels (the
    Settings route) only says whether a token is saved.

Only ONE machine polls a bot (LOKI_TELEGRAM_POLL = auto | on | off; auto = the Windows PC,
which is on 24/7), so the Mac and the PC never both answer. Telegram itself refuses a second
poller (HTTP 409); LOKI then says so in Settings and backs off.

The transport (channel_telegram.py) only fetches and sends; this module owns pairing, the owner
check, commands, limits, splitting and the work. A second transport (Discord) plugs in the same
way - see HANDOFF.md "Session 28 channels + voice" for why it is not built yet.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

PAIR_TTL_S = 15 * 60
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L
CODE_LEN = 8
BAD_CODE_PER_CHAT = 5              # wrong codes per chat in BAD_CODE_WINDOW_S ...
BAD_CODE_TOTAL = 20                # ... and in total, before the code is burned
BAD_CODE_WINDOW_S = 600
CHAT_PER_MIN = 6
COMMANDS_PER_MIN = 20
STRANGER_REPLY_EVERY_S = 3600
MAX_INCOMING = 4000
MAX_CHUNKS = 8
MAX_PHOTOS = 4
MAKE_TIMEOUT_S = 45 * 60
MODES = ("ask", "plan")

HELP = ("I am LOKI, on {machine}. Send a message and I answer it ({mode} mode: I can read and "
        "answer, but changing things stays on the computer).\n\n"
        "/make <what> - make a picture and send it here\n"
        "/jobs - what is running in the background\n"
        "/stop - stop what I am doing now\n"
        "/help - this list")

_TOKEN_PATTERNS = [re.compile(r"bot\d{4,}:[A-Za-z0-9_-]{20,}"),          # in a Telegram URL
                   re.compile(r"\b\d{4,}:[A-Za-z0-9_-]{30,}\b")]           # a bare Telegram token


def redact(text: Any, secrets_: list | tuple = ()) -> str:
    """`text` with every token LOKI knows of, and anything shaped like a bot token, removed."""
    out = str(text)
    for value in secrets_:
        if value and len(str(value)) >= 8:
            out = out.replace(str(value), "***")
    for pattern in _TOKEN_PATTERNS:
        out = pattern.sub("***", out)
    return out


def split_text(text: str, limit: int, max_chunks: int = MAX_CHUNKS) -> list:
    """Pieces of at most `limit` characters, broken at a paragraph, a line, then a space."""
    text = str(text or "").strip()
    if not text:
        return []
    limit = max(16, int(limit))
    chunks: list = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        window = text[:limit]
        cut = -1
        for sep in ("\n\n", "\n", " "):
            at = window.rfind(sep)
            if at >= limit // 3:
                cut = at
                break
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if len(chunks) > max_chunks:
        note = "\n\n(... the rest is too long for here - it is in LOKI on the computer.)"
        chunks = chunks[:max_chunks]
        chunks[-1] = chunks[-1][:limit - len(note)].rstrip() + note
    return chunks


def poll_here(name: str, env: dict | None = None, platform: str = "") -> tuple:
    """(should this machine poll the `name` bot, why) from LOKI_<NAME>_POLL = auto | on | off."""
    env = env if env is not None else os.environ
    value = str(env.get("LOKI_%s_POLL" % name.upper()) or "auto").strip().lower()
    if value in ("off", "0", "no"):
        return False, "off on this machine (LOKI_%s_POLL=off)" % name.upper()
    if value in ("on", "1", "yes"):
        return True, "on (LOKI_%s_POLL=on)" % name.upper()
    if (platform or sys.platform) == "win32":
        return True, "auto: the Windows PC answers"
    return False, ("auto: only the Windows PC answers, so your two machines never both reply - "
                   "set LOKI_%s_POLL=on here (and off on the PC) to answer from this machine" % name.upper())


def channel_mode(env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    mode = str(env.get("LOKI_CHANNEL_MODE") or "ask").strip().lower()
    return mode if mode in MODES else "ask"


class Limiter:
    """Sliding-window counters (as phone_link's): at most `limit` events per `window` seconds."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.events: dict = {}
        self.lock = threading.Lock()

    def count(self, key: str, window: float) -> int:
        now = self.clock()
        with self.lock:
            kept = [t for t in self.events.get(key, []) if now - t < window]
            self.events[key] = kept
            return len(kept)

    def hit(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = self.clock()
        with self.lock:
            kept = [t for t in self.events.get(key, []) if now - t < window]
            if len(kept) >= limit:
                self.events[key] = kept
                return False
            kept.append(now)
            self.events[key] = kept
            return True


class Store:
    """<data>/channels/<name>.json: the owner (user id, chat id, name, when) and the poll offset.

    No token is ever written here (it lives in .env like every other key)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def update(self, **fields: Any) -> dict:
        with self.lock:
            data = self.load()
            for key, value in fields.items():
                if value is None:
                    data.pop(key, None)
                else:
                    data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            os.replace(temp, self.path)
            return data


def data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


class ChannelError(Exception):
    """A chat-app call failed. Its text is already redacted."""

    def __init__(self, message: str, code: int = 0, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class Channel:
    """Pairing, the owner check, commands, limits and the work; a transport subclass talks to the app.

    A transport implements: token(), fetch() -> [incoming], send_text(chat, text),
    send_photo(chat, path, caption), send_typing(chat), me() -> {"username", ...}, and sets
    `name`, `label`, `limit`. An incoming message is a dict:
      {"user_id", "chat_id", "private": bool, "is_bot": bool, "text", "name", "voice": callable|None}
    where voice() downloads a voice note and returns its local path.
    """

    name = "channel"
    label = "Channel"
    limit = 2000
    send_gap_s = 1.0               # at most one message a second into one chat
    idle_s = 5.0                   # how often an idle loop looks for a token / LOKI_<NAME>_POLL
    make_poll_s = 2.0              # how often /make looks whether the picture is done
    setup_hint = "paste the bot token in Settings > General first"

    def __init__(self, callbacks: dict, store: Store | None = None, env: dict | None = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 platform: str = "") -> None:
        self.callbacks = callbacks
        self.store = store or Store(data_dir() / "channels" / ("%s.json" % self.name))
        self.env = env if env is not None else os.environ
        self.clock = clock
        self.sleep = sleep
        self.platform = platform or sys.platform
        self.limits = Limiter(clock)
        self._code = ""                    # the one live pairing code (memory only)
        self._code_until = 0.0
        self._last_send: dict = {}
        self._send_lock = threading.Lock()
        self._busy = threading.Lock()      # one chat at a time from the app
        self._stranger_told: dict = {}
        self.log: list = []                # events only: never message text, never the token
        self.last_error = ""
        self.last_poll = 0.0
        self.polling = False
        self.bot: dict = {}
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    # ------------------------------------------------------------------ transport hooks
    def token(self) -> str:
        return ""

    def configured(self) -> bool:
        """Ready to run here. A bot-token app (Telegram) is configured once its token is saved; a
        transport that logs in another way (Wechaty: a QR scan) overrides this."""
        return bool(self.token())

    def fetch(self) -> list:
        raise NotImplementedError

    def send_text(self, chat_id: Any, text: str) -> None:
        raise NotImplementedError

    def send_photo(self, chat_id: Any, path: Path, caption: str = "") -> None:
        raise NotImplementedError

    def send_typing(self, chat_id: Any) -> None:
        pass

    def me(self) -> dict:
        return {}

    def link(self, code: str) -> str:
        return ""

    # ------------------------------------------------------------------ bookkeeping
    def note(self, event: str) -> None:
        self.log.append({"t": self.clock(), "event": redact(event, [self.token()])[:200]})
        del self.log[:-50]

    def fail(self, error: Any) -> str:
        text = redact(error, [self.token()])[:300]
        self.last_error = text
        self.note("error: " + text)
        print("[channels] %s: %s" % (self.name, text), flush=True)
        return text

    def owner(self) -> dict:
        return self.store.load().get("owner") or {}

    def is_owner(self, msg: dict) -> bool:
        owner = self.owner()
        if not owner or not msg.get("private") or msg.get("is_bot"):
            return False
        return (str(msg.get("user_id")) == str(owner.get("user_id"))
                and str(msg.get("chat_id")) == str(owner.get("chat_id")))

    def status(self) -> dict:
        here, why = poll_here(self.name, self.env, self.platform)
        owner = self.owner()
        code_live = bool(self._code) and self.clock() < self._code_until
        return {"name": self.name, "label": self.label, "token_saved": self.configured(),
                "poll_here": here, "poll_why": why, "polling": self.polling,
                "bot": {k: v for k, v in self.bot.items() if k in ("username", "first_name", "id")},
                "paired": bool(owner), "owner": {"name": owner.get("name", ""), "since": owner.get("paired_at")} if owner else {},
                "pairing": {"code": self._code, "expires_in": int(self._code_until - self.clock()),
                            "link": self.link(self._code)} if code_live else None,
                "mode": channel_mode(self.env), "last_error": self.last_error,
                "last_poll": self.last_poll or None, "log": self.log[-12:]}

    # ------------------------------------------------------------------ pairing
    def new_code(self) -> dict:
        self._code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        self._code_until = self.clock() + PAIR_TTL_S
        self.note("pairing code made")
        return {"code": self._code, "expires_in": PAIR_TTL_S, "link": self.link(self._code)}

    def unpair(self) -> None:
        self.store.update(owner=None)
        self._code = ""
        self.note("unpaired")

    def _try_pair(self, msg: dict, given: str) -> str:
        """The reply to `/start <code>` from a chat that is not the owner's ("" = say nothing)."""
        chat = str(msg.get("chat_id"))
        if not msg.get("private") or msg.get("is_bot"):
            return ""
        if not self._code or self.clock() >= self._code_until:
            return self._stranger(chat)
        if (self.limits.count("bad:" + chat, BAD_CODE_WINDOW_S) >= BAD_CODE_PER_CHAT
                or self.limits.count("bad:all", BAD_CODE_WINDOW_S) >= BAD_CODE_TOTAL):
            return ""
        if not given:
            return ("Send the pairing code from LOKI: Settings > General > Telegram, like "
                    "/start ABCD1234.")
        if not hmac.compare_digest(given.strip().upper().encode(), self._code.encode()):
            self.limits.hit("bad:" + chat, 10 ** 9, BAD_CODE_WINDOW_S)
            self.limits.hit("bad:all", 10 ** 9, BAD_CODE_WINDOW_S)
            self.note("wrong pairing code")
            if self.limits.count("bad:all", BAD_CODE_WINDOW_S) >= BAD_CODE_TOTAL:
                self._code = ""                       # burned: make a new one in Settings
                self.note("pairing code burned after too many wrong tries")
            return "That code is not right."
        self._code = ""
        self.store.update(owner={"user_id": str(msg.get("user_id")), "chat_id": str(msg.get("chat_id")),
                                 "name": str(msg.get("name") or "")[:60], "paired_at": self.clock()})
        self.note("paired")
        machine = self.callbacks.get("machine", lambda: "this computer")()
        return "Paired. This chat now talks to LOKI on %s.\n\n%s" % (
            machine, HELP.format(machine=machine, mode=channel_mode(self.env)))

    def _stranger(self, chat: str) -> str:
        last = self._stranger_told.get(chat, 0.0)
        if self.clock() - last < STRANGER_REPLY_EVERY_S:
            return ""
        self._stranger_told[chat] = self.clock()
        if len(self._stranger_told) > 500:
            self._stranger_told.clear()
        return "This is a private LOKI bot."

    # ------------------------------------------------------------------ sending
    def _gate(self, chat_id: Any) -> None:
        with self._send_lock:
            wait = self._last_send.get(str(chat_id), 0.0) + self.send_gap_s - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last_send[str(chat_id)] = self.clock()

    def say(self, chat_id: Any, text: str) -> None:
        for piece in split_text(text, self.limit):
            self._gate(chat_id)
            try:
                self.send_text(chat_id, piece)
            except ChannelError as exc:
                self.fail("send failed: %s" % exc)
                return

    def photo(self, chat_id: Any, path: Path, caption: str = "") -> bool:
        self._gate(chat_id)
        try:
            self.send_photo(chat_id, Path(path), caption[:900])
            return True
        except (ChannelError, OSError) as exc:
            self.fail("photo failed: %s" % exc)
            return False

    # ------------------------------------------------------------------ incoming
    def handle(self, msg: dict) -> None:
        """One incoming message (called on the poll thread; long work goes to a thread)."""
        text = str(msg.get("text") or "").strip()
        chat = msg.get("chat_id")
        command, _, rest = text.partition(" ")
        command = command.split("@", 1)[0].lower() if command.startswith("/") else ""
        if not self.is_owner(msg):
            if command == "/start":
                reply = self._try_pair(msg, rest.strip())
            elif msg.get("private") and not msg.get("is_bot"):
                reply = self._stranger(str(chat))
            else:
                reply = ""
            if reply:
                self.say(chat, reply)
            return
        if command:
            if not self.limits.hit("cmd", COMMANDS_PER_MIN):
                return self.say(chat, "Slow down - at most %d commands a minute." % COMMANDS_PER_MIN)
            return self._command(chat, command, rest.strip())
        if not text and msg.get("voice"):
            return self._voice(chat, msg["voice"])
        if not text:
            return self.say(chat, "I read text messages (and voice notes when Whisper is installed).")
        self._chat(chat, text)

    def _command(self, chat: Any, command: str, rest: str) -> None:
        machine = self.callbacks.get("machine", lambda: "this computer")()
        if command in ("/start", "/help"):
            return self.say(chat, HELP.format(machine=machine, mode=channel_mode(self.env)))
        if command == "/jobs":
            return self.say(chat, self._jobs_text())
        if command == "/stop":
            try:
                self.callbacks["stop"]()
                return self.say(chat, "Stopping what I am doing.")
            except Exception as exc:  # noqa: BLE001
                return self.say(chat, "Could not stop: %s" % redact(exc, [self.token()])[:200])
        if command == "/make":
            if not rest:
                return self.say(chat, "Say what to make, like: /make a red fox asleep in the snow")
            if not self.limits.hit("chat", CHAT_PER_MIN):
                return self.say(chat, "Slow down - at most %d requests a minute." % CHAT_PER_MIN)
            return self._make(chat, rest[:600])
        return self.say(chat, "I do not know %s. /help lists what I can do." % command[:40])

    def _jobs_text(self) -> str:
        try:
            jobs = list(self.callbacks["jobs"]() or [])
        except Exception as exc:  # noqa: BLE001
            return "Background jobs are not available: %s" % redact(exc, [self.token()])[:200]
        if not jobs:
            return "No background jobs."
        order = {"running": 0, "queued": 1, "waiting": 2}
        jobs.sort(key=lambda j: (order.get(str(j.get("status")), 3), -_stamp_value(j.get("created"))))
        lines = ["Background jobs (%d):" % len(jobs)]
        for job in jobs[:12]:
            line = "- %s: %s" % (job.get("status", "?"), str(job.get("title") or job.get("id") or "")[:80])
            if job.get("machine"):
                line += " (on %s)" % job["machine"]
            if job.get("status") == "failed" and job.get("error"):
                line += " - " + str(job["error"])[:80]
            lines.append(line)
        if len(jobs) > 12:
            lines.append("... and %d more in LOKI on the computer." % (len(jobs) - 12))
        return "\n".join(lines)

    def _chat(self, chat: Any, text: str) -> None:
        if len(text) > MAX_INCOMING:
            return self.say(chat, "That is too long (at most %d characters)." % MAX_INCOMING)
        if not self.limits.hit("chat", CHAT_PER_MIN):
            return self.say(chat, "Slow down - at most %d messages a minute." % CHAT_PER_MIN)
        if not self._busy.acquire(blocking=False):
            return self.say(chat, "I am still on your last message. /stop stops it.")
        threading.Thread(target=self._chat_work, args=(chat, text), daemon=True,
                         name="loki-%s-chat" % self.name).start()

    def _chat_work(self, chat: Any, text: str) -> None:
        stop_typing = threading.Event()
        started = self.clock()
        try:
            threading.Thread(target=self._typing_loop, args=(chat, stop_typing), daemon=True).start()
            self.note("chat")
            try:
                code, result = self.callbacks["chat"](text, channel_mode(self.env))
            except Exception as exc:  # noqa: BLE001
                code, result = 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            stop_typing.set()
            if result.get("ok"):
                self.say(chat, str(result.get("response") or "(no answer)"))
            elif code == 409:
                self.say(chat, "LOKI is busy with something on the computer - try again in a moment.")
            else:
                self.say(chat, "LOKI could not answer: %s" % redact(result.get("error") or "unknown error",
                                                                     [self.token()])[:600])
            self._send_new_pictures(chat, started)
        finally:
            stop_typing.set()
            self._busy.release()

    def _typing_loop(self, chat: Any, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.send_typing(chat)
            except Exception:  # noqa: BLE001 - "typing..." is a nicety
                pass
            stop.wait(4.5)

    def _send_new_pictures(self, chat: Any, since: float, caption: str = "") -> int:
        try:
            made = list(self.callbacks.get("pictures_since", lambda t: [])(since - 1))
        except Exception:  # noqa: BLE001
            made = []
        sent = 0
        for path, title in made[:MAX_PHOTOS]:
            if self.photo(chat, path, caption or title):
                sent += 1
        return sent

    def _make(self, chat: Any, prompt: str) -> None:
        try:
            started = self.callbacks["make"](prompt)
        except Exception as exc:  # noqa: BLE001
            started = {"ok": False, "error": str(exc)}
        if not started.get("ok"):
            return self.say(chat, "Could not start the picture: %s" % redact(started.get("error"), [self.token()])[:300])
        self.say(chat, "Making it - I will send it here when it is done (a few minutes on a local model).")
        threading.Thread(target=self._make_wait, args=(chat, str(started.get("id")), prompt, self.clock()),
                         daemon=True, name="loki-%s-make" % self.name).start()

    def _make_wait(self, chat: Any, key: str, prompt: str, since: float) -> None:
        deadline = time.monotonic() + MAKE_TIMEOUT_S
        done: dict = {}
        while time.monotonic() < deadline and not self._stop.is_set():
            entry = next((m for m in (self.callbacks.get("making", lambda: [])() or []) if str(m.get("id")) == key), None)
            if entry is None or entry.get("end"):
                done = entry or {}
                break
            self._stop.wait(self.make_poll_s)
        if not done:
            return self.say(chat, "The picture is taking long; it will be in Settings > Creations when it is done.")
        if done.get("ok") is False:
            return self.say(chat, "The picture failed: %s" % redact(done.get("result") or "", [self.token()])[:400])
        if not self._send_new_pictures(chat, since, prompt[:200]):
            self.say(chat, "Done: %s" % (str(done.get("result") or "made it")[:300]))

    def _voice(self, chat: Any, fetch_voice: Callable) -> None:
        transcribe = self.callbacks.get("transcribe")
        if transcribe is None:
            return self.say(chat, "Voice notes need Whisper on the computer: Settings > Add-ons > whisper.")
        if not self.limits.hit("voice", CHAT_PER_MIN):
            return self.say(chat, "Slow down - at most %d voice notes a minute." % CHAT_PER_MIN)

        def work() -> None:
            path = None
            try:
                path = fetch_voice()
                heard = transcribe(path)
            except Exception as exc:  # noqa: BLE001
                heard = {"ok": False, "error": redact(exc, [self.token()])}
            finally:
                if path is not None:
                    try:
                        Path(path).unlink()
                    except OSError:
                        pass
            if not heard.get("ok") or not str(heard.get("text") or "").strip():
                return self.say(chat, "I could not hear that: %s" % str(heard.get("error") or "no words")[:300])
            text = str(heard["text"]).strip()
            self.say(chat, "Heard: " + text[:500])
            self._chat(chat, text)

        threading.Thread(target=work, daemon=True, name="loki-%s-voice" % self.name).start()

    # ------------------------------------------------------------------ the poll loop
    def poll_once(self) -> int:
        """Fetch and handle one batch. Returns how many messages came in."""
        if not self.bot:
            self.bot = self.me() or {}
            self.on_connected()
        batch = self.fetch()
        self.last_poll = self.clock()
        self.last_error = ""
        for msg in batch:
            try:
                self.handle(msg)
            except Exception as exc:  # noqa: BLE001 - one bad message never stops the channel
                self.fail("handling a message failed: %s" % exc)
        return len(batch)

    def on_connected(self) -> None:
        pass

    def run_forever(self) -> None:
        backoff = 0.0
        seen_token = ""
        while not self._stop.is_set():
            here, _why = poll_here(self.name, self.env, self.platform)
            token = self.token()
            if token != seen_token:            # a new token pasted in Settings: start over
                self.bot, seen_token, backoff = {}, token, 0.0
            if not here or not self.configured():
                self.polling = False
                self._stop.wait(self.idle_s)
                continue
            self.polling = True
            try:
                self.poll_once()
                backoff = 0.0
            except ChannelError as exc:
                self.fail(str(exc))
                if exc.code == 401:
                    self.bot = {}
                backoff = max(exc.retry_after, min(300.0, (backoff or 2.5) * 2 if exc.code != 409 else 30.0))
                self._stop.wait(backoff)
            except Exception as exc:  # noqa: BLE001
                self.fail("%s: %s" % (type(exc).__name__, exc))
                backoff = min(300.0, (backoff or 2.5) * 2)
                self._stop.wait(backoff)
        self.polling = False

    def start(self) -> "Channel":
        self.thread = threading.Thread(target=self.run_forever, daemon=True, name="loki-%s" % self.name)
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


def _stamp_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------- the engine side
def callbacks(state: Any, agent: Any) -> dict:
    """What a channel may do inside LOKI - and nothing else."""
    import phone_link  # pylint: disable=import-outside-toplevel
    import peers  # pylint: disable=import-outside-toplevel

    def chat(text: str, mode: str) -> tuple:
        state.note_request()
        return phone_link.chat_once(state, agent, text, mode)

    def jobs() -> list:
        supervisor = getattr(state, "jobs", None)
        return (supervisor.status().get("jobs") or []) if supervisor is not None else []

    def make(prompt: str) -> dict:
        import creations  # pylint: disable=import-outside-toplevel
        return creations.make_image(agent, prompt)

    def making() -> list:
        import creations  # pylint: disable=import-outside-toplevel
        return creations.making()

    def pictures_since(since: float) -> list:
        import creations  # pylint: disable=import-outside-toplevel
        workspace = Path(getattr(agent, "WORKSPACE", "."))
        out = []
        for item in creations.list_creations(workspace, limit=20):
            if item.get("show") == "image" and item.get("kind") == "images" and float(item.get("t") or 0) >= since:
                out.append((workspace / item["path"], item.get("title", "")))
        return out

    def stop() -> None:
        if hasattr(agent, "request_cancel"):
            agent.request_cancel()

    found = {"chat": chat, "jobs": jobs, "make": make, "making": making, "pictures_since": pictures_since,
             "stop": stop, "machine": lambda: "%s (%s)" % (peers.my_name(), phone_link.machine_kind())}
    def transcribe(path: Path) -> dict:
        # looked up on every voice note, so installing the whisper add-on works without a restart
        import voice_input  # pylint: disable=import-outside-toplevel
        return voice_input.transcribe(path)

    found["transcribe"] = transcribe
    return found


def start(state: Any, agent: Any) -> dict:
    """Start every channel's loop (each one idles until a token is saved and this machine polls)."""
    import channel_telegram  # pylint: disable=import-outside-toplevel
    started = {"telegram": channel_telegram.TelegramChannel(callbacks(state, agent)).start()}
    try:   # Wechaty (WeChat and other networks through a Node sidecar): idle until its add-on is on
        import channel_wechaty  # pylint: disable=import-outside-toplevel
        registry = getattr(agent, "CAPABILITIES", None)
        enabled = (lambda: registry.is_enabled("wechaty")) if registry is not None else (lambda: False)
        started["wechaty"] = channel_wechaty.WechatyChannel(callbacks(state, agent), enabled=enabled).start()
    except Exception as exc:  # noqa: BLE001 - an optional channel never stops Telegram
        print("[channels] wechaty not started: %s" % exc, flush=True)
    state.channels = started
    return started


def ui_route(state: Any, method: str, route: str, data: dict):
    """(status, payload) for Settings' /channels routes, or None if not ours. No token ever goes out."""
    if not route.startswith("/channels"):
        return None
    found = getattr(state, "channels", None) or {}
    if method == "GET" and route == "/channels":
        return 200, {"ok": True, "channels": [c.status() for c in found.values()],
                     "mode": channel_mode()}
    if method != "POST":
        return 404, {"ok": False, "error": "Unknown endpoint."}
    channel = found.get(str(data.get("channel") or "telegram"))
    if channel is None:
        return 404, {"ok": False, "error": "no such channel (is the engine still starting?)"}
    if route == "/channels/pair":
        if not channel.configured():
            return 400, {"ok": False, "error": channel.setup_hint}
        return 200, {"ok": True, **channel.new_code(), "status": channel.status()}
    if route == "/channels/unpair":
        channel.unpair()
        return 200, {"ok": True, "status": channel.status()}
    if route == "/channels/test":
        if not channel.configured():
            return 400, {"ok": False, "error": channel.setup_hint}
        try:
            channel.bot = channel.me() or {}
            return 200, {"ok": True, "status": channel.status()}
        except ChannelError as exc:
            return 502, {"ok": False, "error": channel.fail(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
