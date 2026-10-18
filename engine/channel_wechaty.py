"""Wechaty transport for engine/channels.py: talk to LOKI on WeChat (and the other networks
Wechaty supports through a "puppet") with a small Node sidecar, engine/wechaty_sidecar.mjs.

Wechaty (github.com/wechaty/wechaty, Apache-2.0) is a TypeScript SDK, so LOKI does not port it:
when the `wechaty` add-on is on (Settings > Add-ons) and this machine answers
(LOKI_WECHATY_POLL, like Telegram's), LOKI starts `node wechaty_sidecar.mjs` with an argument
list (no shell) and they talk JSON lines over stdin/stdout. The npm packages are installed by
`python tools/setup_extras.py wechaty` into harness_data/addons/wechaty, never into the repo.

Everything else is channels.Channel's: pairing with the one-time code (`/start <code>` sent to
the bot account), owner-only answers, Ask/Plan mode, rate limits, splitting, /jobs /make /stop.
Group chats ("rooms") and the account's own messages are never answered. Logging in is the
puppet's job: the default (wechaty-puppet-wechat4u, the web protocol) shows a QR code, which
Settings > General shows as a link; WECHATY_PUPPET_SERVICE_TOKEN (a secret setting) is only for
a paid puppet service and goes to the sidecar in its environment, never on a command line.
"""
from __future__ import annotations

import itertools
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import channels

HERE = Path(__file__).resolve().parent
SIDECAR = HERE / "wechaty_sidecar.mjs"
DEFAULT_PUPPET = "wechaty-puppet-wechat4u"
PUPPETS = ("wechaty-puppet-wechat4u", "wechaty-puppet-service", "wechaty-puppet-whatsapp", "wechaty-puppet-xp")
SECRET_ENV = "WECHATY_PUPPET_SERVICE_TOKEN"
REPLY_TIMEOUT_S = 30.0
FETCH_WAIT_S = 2.0
MAX_LINE = 64_000


def package_dir(env: dict | None = None) -> Path:
    env = env if env is not None else os.environ
    explicit = str(env.get("LOKI_WECHATY_PACKAGE_DIR") or "").strip()
    return Path(explicit) if explicit else channels.data_dir() / "addons" / "wechaty"


def node_exe(env: dict | None = None, which=shutil.which) -> str:
    env = env if env is not None else os.environ
    explicit = str(env.get("LOKI_NODE") or "").strip()
    if explicit:
        return explicit
    return which("node") or which("node.exe") or ""


def puppet(env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    value = str(env.get("LOKI_WECHATY_PUPPET") or DEFAULT_PUPPET).strip()
    return value if value in PUPPETS else DEFAULT_PUPPET


def sidecar_argv(env: dict | None = None, which=shutil.which) -> list:
    """The sidecar's command line: node + the script. Never a shell string, never a secret."""
    node = node_exe(env, which)
    if not node:
        raise channels.ChannelError("Node.js is not installed (nodejs.org, version 18 or newer)")
    return [node, str(SIDECAR)]


def sidecar_env(env: dict | None = None) -> dict:
    """The sidecar's environment: ours, plus where wechaty is and which puppet to use."""
    env = dict(env if env is not None else os.environ)
    env["LOKI_WECHATY_PACKAGE_DIR"] = str(package_dir(env))
    env["WECHATY_PUPPET"] = puppet(env)
    env.setdefault("LOKI_WECHATY_NAME", "loki")
    env["WECHATY_LOG"] = env.get("WECHATY_LOG") or "warn"
    return env


class WechatyChannel(channels.Channel):
    name = "wechaty"
    label = "WeChat (Wechaty)"
    limit = 1800                      # WeChat cuts long texts; stay well under
    send_gap_s = 1.5                  # personal-account protocols dislike bursts
    setup_hint = "turn on wechaty in Settings > Add-ons first (python tools/setup_extras.py wechaty installs it)"

    def __init__(self, *args: Any, enabled: Callable[[], bool] | None = None,
                 spawn: Callable[..., Any] | None = None, which=shutil.which, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.enabled = enabled or (lambda: False)
        self.spawn = spawn or subprocess.Popen
        self.which = which
        self.proc: Any = None
        self.events: queue.Queue = queue.Queue()
        self.replies: dict = {}
        self._reply_ready = threading.Condition()
        self._ids = itertools.count(1)
        self._write_lock = threading.Lock()
        self.login_qr = ""
        self.logged_in = False
        self.fatal = ""
        self._reader_done = threading.Event()

    # ------------------------------------------------------------------ the sidecar
    def token(self) -> str:
        return str(self.env.get(SECRET_ENV) or "").strip()      # only used to redact it from logs

    def configured(self) -> bool:
        on = bool(self.enabled())
        if not on and self.proc is not None:
            self.stop_sidecar()                                  # turned off in Settings > Add-ons
        return on

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_sidecar(self) -> None:
        """Start the sidecar if there is none; if it died, say why once (the next poll starts it again)."""
        if self.proc is not None and not self.running():
            deadline = time.monotonic() + 1.0          # let the reader hand over its last lines
            while not self.events.empty() or (time.monotonic() < deadline and not self._reader_done.is_set()):
                try:
                    self._event(self.events.get(timeout=0.05))
                except queue.Empty:
                    pass
            reason = self.fatal or "the Wechaty sidecar stopped"
            self.proc, self.bot, self.logged_in = None, {}, False
            raise channels.ChannelError(channels.redact(reason, [self.token()]))
        self.start_sidecar()

    def start_sidecar(self) -> None:
        if self.running():
            return
        argv = sidecar_argv(self.env, self.which)
        work = channels.data_dir() / "channels" / "wechaty"     # the puppet's session file lives here
        work.mkdir(parents=True, exist_ok=True)
        self.fatal, self.login_qr, self.logged_in = "", "", False
        self.events = queue.Queue()
        self._reader_done = threading.Event()
        try:
            self.proc = self.spawn(argv, cwd=str(work), env=sidecar_env(self.env), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1)
        except OSError as exc:
            raise channels.ChannelError("could not start the Wechaty sidecar: %s" % exc) from None
        self.note("sidecar started")
        threading.Thread(target=self._read, args=(self.proc, self._reader_done), daemon=True,
                         name="loki-wechaty-read").start()

    def stop_sidecar(self) -> None:
        proc, self.proc = self.proc, None
        self.bot, self.logged_in, self.login_qr = {}, False, ""
        if proc is None:
            return
        try:
            self._write(proc, {"op": "stop"})
        except (OSError, ValueError, channels.ChannelError):
            pass
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.terminate()
        self.note("sidecar stopped")

    def stop(self) -> None:
        super().stop()
        self.stop_sidecar()

    def _read(self, proc: Any, done: threading.Event) -> None:
        try:
            self._read_lines(proc)
        finally:
            done.set()

    def _read_lines(self, proc: Any) -> None:
        for line in proc.stdout:
            line = line.strip()
            if not line or len(line) > MAX_LINE:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if not isinstance(item, dict):
                continue
            if "reply" in item:
                with self._reply_ready:
                    self.replies[str(item["reply"])] = item
                    self._reply_ready.notify_all()
            else:
                self.events.put(item)

    def _write(self, proc: Any, obj: dict) -> None:
        if proc is None or proc.poll() is not None:
            raise channels.ChannelError("the Wechaty sidecar is not running")
        with self._write_lock:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

    def request(self, op: str, timeout: float = REPLY_TIMEOUT_S, **fields: Any) -> dict:
        key = str(next(self._ids))
        try:
            self._write(self.proc, {"id": key, "op": op, **fields})
        except (OSError, ValueError) as exc:
            raise channels.ChannelError("the Wechaty sidecar stopped: %s" % exc) from None
        deadline = time.monotonic() + timeout
        with self._reply_ready:
            while key not in self.replies:
                left = deadline - time.monotonic()
                if left <= 0 or not self.running():
                    raise channels.ChannelError("the Wechaty sidecar did not answer")
                self._reply_ready.wait(min(left, 0.5))
            reply = self.replies.pop(key)
        if not reply.get("ok"):
            raise channels.ChannelError(channels.redact("Wechaty %s: %s" % (op, reply.get("error") or "failed"),
                                                        [self.token()]))
        return reply

    # ------------------------------------------------------------------ the transport
    def me(self) -> dict:
        self.ensure_sidecar()
        return dict(self.bot)

    def fetch(self) -> list:
        self.ensure_sidecar()
        out: list = []
        try:
            item = self.events.get(timeout=FETCH_WAIT_S)
        except queue.Empty:
            item = None
        while item is not None:
            msg = self._event(item)
            if msg is not None:
                out.append(msg)
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                item = None
        if not out and not self.running():
            self.ensure_sidecar()                     # raises with the reason it died
        return out

    def _event(self, item: dict) -> dict | None:
        kind = item.get("event")
        if item.get("fatal"):
            self.fatal = str(item["fatal"])[:300]
            return None
        if kind == "scan":
            self.login_qr = str(item.get("qrcode") or "")[:500]
            self.note("waiting for the QR scan")
        elif kind == "login":
            user = item.get("user") or {}
            self.bot, self.logged_in, self.login_qr = {"username": str(user.get("name") or "")[:60],
                                                       "id": str(user.get("id") or "")[:80]}, True, ""
            self.note("logged in")
        elif kind == "logout":
            self.bot, self.logged_in = {}, False
            self.note("logged out")
        elif kind == "error":
            self.fail("Wechaty: %s" % item.get("error"))
        elif kind == "message":
            room = bool(item.get("room"))
            return {"user_id": item.get("user_id"), "chat_id": item.get("chat_id"), "private": not room,
                    "is_bot": bool(item.get("self")), "name": str(item.get("name") or ""),
                    "text": str(item.get("text") or "")[:channels.MAX_INCOMING + 1], "voice": None}
        return None

    def send_text(self, chat_id: Any, text: str) -> None:
        self.request("say", to=str(chat_id), text=text)

    def send_photo(self, chat_id: Any, path: Path, caption: str = "") -> None:
        self.request("file", timeout=120, to=str(chat_id), path=str(Path(path).resolve()))
        if caption:
            self.send_text(chat_id, caption)

    def status(self) -> dict:
        out = super().status()
        out.update(sidecar=self.running(), logged_in=self.logged_in, puppet=puppet(self.env),
                   login_qr=self.login_qr, lines=self.lines(out))
        return out

    def lines(self, status: dict) -> list:
        """What Settings shows under the channel (app/ui/channels.js uses `lines` when present)."""
        if not self.configured():
            return ["Turn on wechaty in Settings > Add-ons (install: python tools/setup_extras.py wechaty).",
                    "Then LOKI starts a small Wechaty helper and shows how to log in here."]
        out = ["Network: %s" % puppet(self.env),
               "This machine answers: %s - %s" % ("yes" if status["poll_here"] else "no", status["poll_why"])]
        if self.login_qr:
            out.append("Log in: open this link on a computer and scan its QR code with the app on your phone: "
                       + self.login_qr)
        elif self.logged_in:
            out.append("Logged in as %s." % (self.bot.get("username") or "the bot account"))
        elif status["poll_here"]:
            out.append("Starting the Wechaty helper..." if not self.fatal else "Stopped: " + self.fatal)
        out.append("Paired with %s. Only that chat is answered." % (status["owner"].get("name") or "you")
                   if status["paired"] else "Not paired yet: press Pair, then send /start <code> to the bot account.")
        out.append("Messages run in %s mode; group chats are ignored; approvals and building stay on the computer."
                   % status["mode"])
        return out
