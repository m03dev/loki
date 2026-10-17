"""Email connector: read, search and draft over IMAP; send over SMTP - and sending ALWAYS asks the owner.

Works with any mailbox that speaks IMAP/SMTP (Gmail, iCloud, Outlook.com, Fastmail, Yahoo, your own):
  - Gmail: an app password (Google account > Security > 2-Step Verification > App passwords), or
    the Google sign-in (Settings > Tools > Google account; EMAIL_AUTH=google, XOAUTH2);
  - iCloud: an app-specific password (appleid.apple.com > Sign-In and Security);
  - others: the account password or an app password.
Hosts are guessed from the address for the big providers; set EMAIL_IMAP_HOST / EMAIL_SMTP_HOST otherwise.

Actions (the `email` tool): list, search, read, draft (a local .eml in the workspace's drafts/,
nothing leaves the computer), send (asks the owner, every time; never from a background job).
Mailboxes are opened READ-ONLY (IMAP EXAMINE + BODY.PEEK): reading never marks mail as read.
Standard library only.
"""
from __future__ import annotations

import email
import email.header
import email.policy
import email.utils
import imaplib
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

import connectors

SPEC = {
    "id": "email",
    "label": "Email (IMAP + SMTP)",
    "about": "Read and search your mail, write drafts. Sending always asks you first, and never happens "
             "from a background job.",
    "tool": "email",
    "writes": ["send"],
    "help": "Gmail: use an app password (Google account > Security > 2-Step Verification > App passwords) or "
            "set Sign-in to google after signing in on the Google card. iCloud: an app-specific password.",
    "fields": [
        {"key": "EMAIL_ADDRESS", "label": "Email address", "kind": "text"},
        {"key": "EMAIL_PASSWORD", "label": "App password", "kind": "secret"},
        {"key": "EMAIL_AUTH", "label": "Sign-in", "kind": "choice", "choices": ["password", "google"], "default": "password"},
        {"key": "EMAIL_IMAP_HOST", "label": "IMAP server (blank = guess from the address)", "kind": "text"},
        {"key": "EMAIL_SMTP_HOST", "label": "SMTP server (blank = guess from the address)", "kind": "text"},
    ],
}

KNOWN_HOSTS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"), "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com"), "me.com": ("imap.mail.me.com", "smtp.mail.me.com"),
    "mac.com": ("imap.mail.me.com", "smtp.mail.me.com"),
    "outlook.com": ("outlook.office365.com", "smtp-mail.outlook.com"),
    "hotmail.com": ("outlook.office365.com", "smtp-mail.outlook.com"),
    "live.com": ("outlook.office365.com", "smtp-mail.outlook.com"),
    "fastmail.com": ("imap.fastmail.com", "smtp.fastmail.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "proton.me": ("127.0.0.1:1143", "127.0.0.1:1025"),   # Proton Mail Bridge
}
READ_CHARS = 6000
IMAP_FACTORY = imaplib.IMAP4_SSL
SMTP_SSL_FACTORY = smtplib.SMTP_SSL
SMTP_FACTORY = smtplib.SMTP
TIMEOUT_S = 25


class EmailError(Exception):
    pass


def hosts(source: dict | None = None) -> tuple:
    address = connectors.get("EMAIL_ADDRESS", source)
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    guess = KNOWN_HOSTS.get(domain, ("imap." + domain if domain else "", "smtp." + domain if domain else ""))
    return (connectors.get("EMAIL_IMAP_HOST", source) or guess[0], connectors.get("EMAIL_SMTP_HOST", source) or guess[1])


def _auth_mode(source: dict | None) -> str:
    return "google" if connectors.get("EMAIL_AUTH", source).lower() == "google" else "password"


def status(source: dict | None = None) -> dict:
    address = connectors.get("EMAIL_ADDRESS", source)
    if not address or "@" not in address:
        return {"configured": False, "detail": "no email address yet"}
    if _auth_mode(source) == "google":
        if not connectors.get("GOOGLE_REFRESH_TOKEN", source):
            return {"configured": False, "detail": "sign in on the Google account card first"}
    elif not connectors.get("EMAIL_PASSWORD", source):
        return {"configured": False, "detail": "no app password yet"}
    imap, _smtp = hosts(source)
    return {"configured": True, "detail": "%s via %s" % (address, imap)}


def _split_host(host: str, default_port: int) -> tuple:
    if ":" in host and not host.startswith("["):
        name, port = host.rsplit(":", 1)
        if port.isdigit():
            return name, int(port)
    return host, default_port


def connect(source: dict | None = None):
    """A logged-in IMAP connection. Raises EmailError (never with the password in it)."""
    st = status(source)
    if not st["configured"]:
        raise EmailError("email is not set up: %s (Settings > Tools > Email)" % st["detail"])
    host, port = _split_host(hosts(source)[0], 993)
    address = connectors.get("EMAIL_ADDRESS", source)
    try:
        conn = IMAP_FACTORY(host, port, timeout=TIMEOUT_S) if IMAP_FACTORY is imaplib.IMAP4_SSL else IMAP_FACTORY(host, port)
    except Exception as exc:  # noqa: BLE001
        raise EmailError("cannot reach the mail server %s (%s)" % (host, exc)) from exc
    try:
        if _auth_mode(source) == "google":
            import conn_google  # pylint: disable=import-outside-toplevel
            token = conn_google.access_token(source)
            conn.authenticate("XOAUTH2", lambda _challenge: conn_google.xoauth2(address, token))
        else:
            conn.login(address, connectors.get("EMAIL_PASSWORD", source))
    except Exception as exc:  # noqa: BLE001
        raise EmailError("the mail server refused the sign-in (%s) - check the app password"
                         % connectors.redact(exc, source)[:160]) from exc
    return conn


def test(source: dict | None = None) -> dict:
    try:
        conn = connect(source)
        typ, data = conn.select("INBOX", readonly=True)
        conn.logout()
    except EmailError as exc:
        return {"ok": False, "detail": str(exc)}
    count = data[0].decode() if data and isinstance(data[0], bytes) else str(data[0] if data else "?")
    return {"ok": typ == "OK", "detail": "signed in; %s messages in the inbox" % count}


def _decode(value) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(str(value or ""))))
    except Exception:  # noqa: BLE001
        return str(value or "")


def _is_gmail(source: dict | None) -> bool:
    return "gmail" in hosts(source)[0]


def imap_query(query: str, gmail: bool) -> list:
    """IMAP SEARCH criteria for a plain query. Gmail gets its own search syntax (X-GM-RAW)."""
    q = str(query or "").strip()
    if not q:
        return ["ALL"]
    if gmail:
        return ["X-GM-RAW", '"%s"' % q.replace('"', "'")]
    crit: list = []
    m = re.match(r"^(from|to|subject):\s*(.+)$", q, re.I)
    if m:
        return [m.group(1).upper(), '"%s"' % m.group(2).replace('"', "'")]
    if q.lower() in ("unread", "is:unread"):
        return ["UNSEEN"]
    safe = q.replace('"', "'")
    crit = ["OR", "OR", "SUBJECT", '"%s"' % safe, "FROM", '"%s"' % safe, "BODY", '"%s"' % safe]
    return crit


def _folder(name: str, source: dict | None) -> str:
    name = str(name or "INBOX").strip() or "INBOX"
    if name.lower() in ("sent",) and _is_gmail(source):
        return '"[Gmail]/Sent Mail"'
    if " " in name and not name.startswith('"'):
        return '"%s"' % name
    return name


def _summaries(conn, uids: list) -> list:
    out = []
    for uid in uids:
        typ, data = conn.uid("FETCH", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK" or not data:
            continue
        flags, header = "", b""
        for part in data:
            if isinstance(part, tuple):
                flags = part[0].decode("utf-8", "replace") if isinstance(part[0], bytes) else str(part[0])
                header = part[1] if isinstance(part[1], bytes) else str(part[1]).encode()
        msg = email.message_from_bytes(header)
        when = msg.get("Date", "")
        try:
            when = email.utils.parsedate_to_datetime(when).strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            pass
        out.append("[%s] %s | %s | %s%s" % (uid.decode() if isinstance(uid, bytes) else uid, when,
                                            _decode(msg.get("From", ""))[:60], _decode(msg.get("Subject", ""))[:120],
                                            "" if "\\Seen" in flags else "  (unread)"))
    return out


def list_messages(folder: str = "INBOX", query: str = "", limit: int = 10, source: dict | None = None) -> str:
    limit = max(1, min(int(limit or 10), 50))
    conn = connect(source)
    try:
        typ, _ = conn.select(_folder(folder, source), readonly=True)   # EXAMINE: nothing is marked read
        if typ != "OK":
            return "error: there is no folder %r" % folder
        typ, data = conn.uid("SEARCH", None, *imap_query(query, _is_gmail(source)))
        if typ != "OK":
            return "error: the server could not search for %r" % query
        uids = (data[0] or b"").split()
        newest = list(reversed(uids[-limit:]))
        lines = _summaries(conn, newest)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    head = "%d message(s)%s in %s, newest first (read one with action='read' id=N):" % (
        len(uids), (" matching %r" % query) if query else "", folder or "INBOX")
    return head + "\n" + ("\n".join(lines) if lines else "(none)")


def _body_text(msg) -> tuple:
    text, attachments = "", []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = str(part.get("Content-Disposition", "")).lower()
        if "attachment" in disposition or part.get_filename():
            attachments.append(_decode(part.get_filename() or "attachment"))
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:  # noqa: BLE001
            payload = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if ctype == "text/plain" and not text:
            text = str(payload)
        elif ctype == "text/html" and not text:
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", str(payload), flags=re.S | re.I)
            text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"[ \t]+", " ", text)
    import html as _html  # pylint: disable=import-outside-toplevel
    return _html.unescape(text).strip(), attachments


def read_message(uid: str, folder: str = "INBOX", source: dict | None = None) -> str:
    uid = re.sub(r"[^0-9]", "", str(uid or ""))
    if not uid:
        return "error: give the message id from list or search (id=N)"
    conn = connect(source)
    try:
        conn.select(_folder(folder, source), readonly=True)
        typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    raw = next((p[1] for p in (data or []) if isinstance(p, tuple)), None)
    if typ != "OK" or not raw:
        return "error: no message %s in %s" % (uid, folder)
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    text, attachments = _body_text(msg)
    if len(text) > READ_CHARS:
        text = text[:READ_CHARS] + "\n... (%d more characters)" % (len(text) - READ_CHARS)
    head = "From: %s\nTo: %s\nDate: %s\nSubject: %s%s\n\n" % (
        msg.get("From", ""), msg.get("To", ""), msg.get("Date", ""), msg.get("Subject", ""),
        ("\nAttachments: " + ", ".join(attachments)) if attachments else "")
    return connectors.untrusted("an email", head + text)


def build(to: str, subject: str, body: str, source: dict | None = None, reply_to_id: str = "") -> EmailMessage:
    to_list = [a.strip() for a in re.split(r"[,;]", str(to or "")) if a.strip()]
    if not to_list or not all(re.match(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$", email.utils.parseaddr(a)[1] or "") for a in to_list):
        raise EmailError("give a valid recipient address in 'to' (comma-separated for several)")
    msg = EmailMessage()
    msg["From"] = connectors.get("EMAIL_ADDRESS", source)
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = str(subject or "").strip()[:300] or "(no subject)"
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=(msg["From"].rsplit("@", 1)[-1] if "@" in msg["From"] else "loki.local"))
    msg.set_content(str(body or ""))
    return msg


def drafts_dir() -> Path:
    return connectors.workspace() / "drafts"


def draft(to: str, subject: str, body: str, source: dict | None = None) -> str:
    try:
        msg = build(to, subject, body, source)
    except EmailError as exc:
        return "error: %s" % exc
    folder = drafts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", msg["Subject"].lower()).strip("-")[:40] or "draft"
    path = folder / ("%s-%s.eml" % (time.strftime("%Y%m%d-%H%M%S"), slug))
    path.write_bytes(bytes(msg))
    return ("draft saved: drafts/%s (nothing was sent)\nTo: %s\nSubject: %s\n\n%s\n\nTo send it: action='send' draft='%s' "
            "(the owner is asked first)." % (path.name, msg["To"], msg["Subject"], str(body)[:600], path.name))


def load_draft(name: str) -> EmailMessage:
    path = (drafts_dir() / Path(str(name)).name)
    if not path.is_file() or path.suffix != ".eml":
        raise EmailError("no draft %r in drafts/" % name)
    return email.message_from_bytes(path.read_bytes(), policy=email.policy.default)


def preview(args: dict) -> str:
    """What the approval prompt shows before sending."""
    if args.get("draft"):
        try:
            msg = load_draft(args["draft"])
            return "SEND EMAIL to %s - subject %r: %s" % (msg["To"], msg["Subject"], str(msg.get_body(("plain",)).get_content())[:300])
        except Exception as exc:  # noqa: BLE001
            return "SEND EMAIL (draft %s: %s)" % (args["draft"], exc)
    return "SEND EMAIL to %s - subject %r: %s" % (args.get("to", ""), args.get("subject", ""), str(args.get("body", ""))[:300])


def send(to: str = "", subject: str = "", body: str = "", draft_name: str = "", source: dict | None = None) -> str:
    """Send over SMTP. Only reached AFTER the policy asked the owner (email action=send is ALWAYS_ASK)."""
    st = status(source)
    if not st["configured"]:
        return "error: email is not set up: %s" % st["detail"]
    try:
        msg = load_draft(draft_name) if draft_name else build(to, subject, body, source)
    except EmailError as exc:
        return "error: %s" % exc
    host, port = _split_host(hosts(source)[1], 465)
    address = connectors.get("EMAIL_ADDRESS", source)
    try:
        if port == 465:
            server = SMTP_SSL_FACTORY(host, port, timeout=TIMEOUT_S, context=ssl.create_default_context())
        else:
            server = SMTP_FACTORY(host, port, timeout=TIMEOUT_S)
            server.starttls(context=ssl.create_default_context())
        try:
            if _auth_mode(source) == "google":
                import base64  # pylint: disable=import-outside-toplevel
                import conn_google  # pylint: disable=import-outside-toplevel
                token = conn_google.access_token(source)
                server.ehlo()
                code, resp = server.docmd("AUTH", "XOAUTH2 " + base64.b64encode(conn_google.xoauth2(address, token)).decode())
                if code != 235:
                    raise EmailError("the SMTP server refused the Google sign-in (%s)" % code)
            else:
                server.login(address, connectors.get("EMAIL_PASSWORD", source))
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
    except EmailError as exc:
        return "error: %s" % exc
    except Exception as exc:  # noqa: BLE001
        return "error: sending failed (%s)" % connectors.redact(exc, source)[:200]
    return "sent to %s: %s" % (msg["To"], msg["Subject"])


ACTIONS = ("list", "search", "read", "draft", "send")


def tool(action: str = "list", query: str = "", id: str = "", folder: str = "INBOX", to: str = "",  # noqa: A002
         subject: str = "", body: str = "", draft: str = "", limit: int = 10) -> str:
    """The `email` tool."""
    action = str(action or "list").strip().lower()
    try:
        if action in ("list", "inbox", "recent"):
            return list_messages(folder, "", limit)
        if action in ("search", "find"):
            if not str(query or "").strip():
                return "error: search needs query='...' (words, from:name, subject:..., unread)"
            return list_messages(folder, query, limit)
        if action in ("read", "open", "get"):
            return read_message(id, folder)
        if action == "draft":
            return globals()["draft"](to, subject, body)
        if action == "send":
            return send(to, subject, body, draft)
    except EmailError as exc:
        return "error: %s" % exc
    except Exception as exc:  # noqa: BLE001
        return "error: %s" % connectors.redact(exc)[:200]
    return "error: unknown action %r - use one of %s" % (action, ", ".join(ACTIONS))


connectors.register(__import__(__name__))
