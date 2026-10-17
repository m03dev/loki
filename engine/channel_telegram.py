"""Telegram transport for engine/channels.py: the Bot API over stdlib urllib (no SDK).

  getMe, getUpdates (long poll, offset kept in harness_data/channels/telegram.json),
  sendMessage, sendPhoto / sendDocument (multipart), sendChatAction (typing),
  setMyCommands (the / menu), getFile + the file download (voice notes).

The token is in every Bot API URL (https://api.telegram.org/bot<token>/<method>), so no URL
is ever printed or stored, and every error goes through channels.redact(). LOKI_TELEGRAM_API
points the transport at another server (tests run a fake one on 127.0.0.1); it must be https,
or plain http to this computer only, so a token is never sent anywhere in the clear.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import channels

DEFAULT_API = "https://api.telegram.org"
LONG_POLL_S = 25
MAX_PHOTO_BYTES = 10 * 1024 * 1024        # sendPhoto's limit; bigger goes as a document
MAX_DOC_BYTES = 49 * 1024 * 1024
MAX_VOICE_BYTES = 20 * 1024 * 1024        # what getFile can download
COMMANDS = [{"command": "make", "description": "make a picture: /make a fox in the snow"},
            {"command": "jobs", "description": "background jobs"},
            {"command": "stop", "description": "stop what LOKI is doing"},
            {"command": "help", "description": "what LOKI can do here"}]


def api_base(env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    base = str(env.get("LOKI_TELEGRAM_API") or DEFAULT_API).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme == "https" and parsed.hostname:
        return base
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return base
    return DEFAULT_API


def multipart(fields: dict, file_field: str, path: Path) -> tuple:
    """(body, content type) for one file and a few text fields."""
    boundary = "loki" + secrets.token_hex(12)
    parts = []
    for key, value in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, key, value)).encode("utf-8"))
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    safe_name = "".join(ch for ch in path.name if ch.isalnum() or ch in "._-")[:80] or "file"
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                  "Content-Type: %s\r\n\r\n" % (boundary, file_field, safe_name, kind)).encode("utf-8"))
    parts.append(path.read_bytes())
    parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


class TelegramChannel(channels.Channel):
    name = "telegram"
    label = "Telegram"
    limit = 4000                      # Telegram allows 4096; leave room
    send_gap_s = 1.05

    def __init__(self, *args: Any, opener=None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.opener = opener or urllib.request.urlopen
        self.long_poll = LONG_POLL_S
        try:
            self.long_poll = max(0, int(self.env.get("LOKI_TELEGRAM_LONGPOLL") or LONG_POLL_S))
        except (TypeError, ValueError):
            pass

    def token(self) -> str:
        return str(self.env.get("LOKI_TELEGRAM_TOKEN") or "").strip()

    def link(self, code: str) -> str:
        user = self.bot.get("username") if self.bot else ""
        return "https://t.me/%s?start=%s" % (user, code) if user and code else ""

    # ------------------------------------------------------------------ HTTP
    def call(self, method: str, params: dict | None = None, upload: tuple | None = None,
             timeout: float = 30.0) -> Any:
        token = self.token()
        if not token:
            raise channels.ChannelError("no bot token saved")
        url = "%s/bot%s/%s" % (api_base(self.env), token, method)
        if upload is not None:
            field, path = upload
            body, kind = multipart({k: v for k, v in (params or {}).items()}, field, Path(path))
        else:
            body, kind = json.dumps(params or {}).encode("utf-8"), "application/json"
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": kind, "User-Agent": "LOKI"})
        try:
            with self.opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
            except (ValueError, OSError):
                payload = {}
            retry = float(((payload.get("parameters") or {}).get("retry_after")) or 0)
            if exc.code == 429 and retry and retry <= 30 and method != "getUpdates":
                self.sleep(retry)
                return self.call(method, params, upload, timeout)
            hint = {401: "the bot token is not valid - paste it again from @BotFather",
                    409: "another copy of LOKI (or another program) is polling this bot - set "
                         "LOKI_TELEGRAM_POLL=off on the other machine",
                    429: "Telegram asks LOKI to slow down"}.get(exc.code, "")
            detail = str(payload.get("description") or "HTTP %d" % exc.code)
            raise channels.ChannelError(channels.redact("Telegram %s: %s%s" % (
                method, detail, (" (" + hint + ")") if hint else ""), [token]), exc.code, retry) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            raise channels.ChannelError(channels.redact("Telegram %s: cannot reach Telegram (%s)" % (
                method, reason), [token])) from None
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise channels.ChannelError(channels.redact("Telegram %s: %s" % (
                method, (payload or {}).get("description", "refused")), [token]))
        return payload.get("result")

    # ------------------------------------------------------------------ the transport
    def me(self) -> dict:
        result = self.call("getMe")
        return result if isinstance(result, dict) else {}

    def on_connected(self) -> None:
        try:
            self.call("setMyCommands", {"commands": COMMANDS})
        except channels.ChannelError:
            pass                              # the / menu is a nicety

    def fetch(self) -> list:
        offset = int(self.store.load().get("offset") or 0)
        updates = self.call("getUpdates", {"offset": offset, "timeout": self.long_poll,
                                           "allowed_updates": ["message"]},
                            timeout=self.long_poll + 15) or []
        out = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            try:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
            except (TypeError, ValueError):
                continue
            message = update.get("message")
            if not isinstance(message, dict):
                continue
            sender = message.get("from") or {}
            chat = message.get("chat") or {}
            voice = message.get("voice") or message.get("audio")
            out.append({"user_id": sender.get("id"), "chat_id": chat.get("id"),
                        "private": chat.get("type") == "private", "is_bot": bool(sender.get("is_bot")),
                        "name": sender.get("first_name") or sender.get("username") or "",
                        "text": str(message.get("text") or message.get("caption") or ""),
                        "voice": self._voice_loader(voice) if isinstance(voice, dict) and voice.get("file_id") else None})
        if updates:
            self.store.update(offset=offset)  # handled or ignored: never fetched twice
        return out

    def _voice_loader(self, voice: dict):
        def load() -> Path:
            if int(voice.get("file_size") or 0) > MAX_VOICE_BYTES:
                raise channels.ChannelError("that voice note is too long")
            info = self.call("getFile", {"file_id": str(voice["file_id"])}) or {}
            file_path = str(info.get("file_path") or "")
            if not file_path or ".." in file_path:
                raise channels.ChannelError("Telegram gave no file")
            url = "%s/file/bot%s/%s" % (api_base(self.env), self.token(), file_path)
            try:
                with self.opener(urllib.request.Request(url, headers={"User-Agent": "LOKI"}), timeout=60) as resp:
                    data = resp.read(MAX_VOICE_BYTES + 1)
            except (urllib.error.URLError, OSError) as exc:
                raise channels.ChannelError(channels.redact("could not download the voice note: %s" % (
                    getattr(exc, "reason", exc)), [self.token()])) from None
            if len(data) > MAX_VOICE_BYTES:
                raise channels.ChannelError("that voice note is too long")
            suffix = Path(file_path).suffix if Path(file_path).suffix in (".oga", ".ogg", ".mp3", ".m4a", ".wav") else ".ogg"
            handle, name = tempfile.mkstemp(suffix=suffix, prefix="loki-voice-")
            with os.fdopen(handle, "wb") as fh:
                fh.write(data)
            return Path(name)
        return load

    def send_text(self, chat_id: Any, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})

    def send_photo(self, chat_id: Any, path: Path, caption: str = "") -> None:
        size = path.stat().st_size
        if size > MAX_DOC_BYTES:
            raise channels.ChannelError("%s is too big to send (%d MB)" % (path.name, size // (1024 * 1024)))
        is_photo = size <= MAX_PHOTO_BYTES and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption[:1000]
        self.call("sendPhoto" if is_photo else "sendDocument", fields,
                  upload=("photo" if is_photo else "document", path), timeout=120)

    def send_typing(self, chat_id: Any) -> None:
        self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
