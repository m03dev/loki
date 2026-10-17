"""Calendar connector: read your calendar; creating an event asks you first.

Three ways in, pick one in Settings > Tools > Calendar:
  google  Google Calendar API with the Google sign-in (read + create).
  caldav  any CalDAV calendar - iCloud (app-specific password), Fastmail, Nextcloud, Radicale (read + create).
          CALDAV_URL is the CALENDAR's collection URL (the one that holds the .ics events).
  ics     a read-only iCal link - e.g. Google Calendar > Settings > your calendar > "Secret address in
          iCal format". It is a secret (anyone with it can read the calendar), so it is stored as one.

Actions (the `calendar` tool): list (days ahead, or start/end), create (asks the owner; never from a
background job). Times are this computer's local time. Standard library only: a small iCalendar
reader (folded lines, all-day and UTC times, RRULE DAILY/WEEKLY(+BYDAY)/MONTHLY/YEARLY with INTERVAL,
COUNT, UNTIL, EXDATE) and writer.
"""
from __future__ import annotations

import base64
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import connectors

SPEC = {
    "id": "calendar",
    "label": "Calendar (Google, CalDAV or an iCal link)",
    "about": "See what is on your calendar. Creating an event always asks you first.",
    "tool": "calendar",
    "writes": ["create"],
    "help": "google: sign in on the Google account card. caldav (iCloud): https://caldav.icloud.com + Apple ID + an "
            "app-specific password; paste your calendar's collection URL. ics: Google Calendar > Settings > the "
            "calendar > Secret address in iCal format (read-only).",
    "fields": [
        {"key": "CALENDAR_KIND", "label": "Calendar", "kind": "choice", "choices": ["google", "caldav", "ics"], "default": "google"},
        {"key": "CALENDAR_ID", "label": "Google calendar id (blank = primary)", "kind": "text"},
        {"key": "CALDAV_URL", "label": "CalDAV calendar URL", "kind": "text"},
        {"key": "CALDAV_USER", "label": "CalDAV user name", "kind": "text"},
        {"key": "CALDAV_PASSWORD", "label": "CalDAV (app) password", "kind": "secret"},
        {"key": "CALENDAR_ICS_URL", "label": "iCal link (read-only)", "kind": "secret"},
    ],
}
OPENER = urllib.request.urlopen
TIMEOUT_S = 20
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
MAX_EVENTS = 60


class CalendarError(Exception):
    pass


def kind(source: dict | None = None) -> str:
    k = connectors.get("CALENDAR_KIND", source, "google").lower()
    return k if k in ("google", "caldav", "ics") else "google"


def status(source: dict | None = None) -> dict:
    k = kind(source)
    if k == "google":
        if not connectors.get("GOOGLE_REFRESH_TOKEN", source):
            return {"configured": False, "detail": "sign in on the Google account card (or choose caldav / ics)"}
        return {"configured": True, "detail": "Google Calendar (%s)" % (connectors.get("CALENDAR_ID", source) or "primary")}
    if k == "caldav":
        if not connectors.get("CALDAV_URL", source) or not connectors.get("CALDAV_USER", source):
            return {"configured": False, "detail": "CalDAV needs the calendar URL and a user name"}
        if not connectors.get("CALDAV_PASSWORD", source):
            return {"configured": False, "detail": "CalDAV needs a password"}
        return {"configured": True, "detail": "CalDAV at %s" % urllib.parse.urlparse(connectors.get("CALDAV_URL", source)).netloc}
    if not connectors.get("CALENDAR_ICS_URL", source):
        return {"configured": False, "detail": "paste the iCal link"}
    return {"configured": True, "detail": "iCal link (read-only)"}


# ------------------------------------------------------------------ time
_LOCAL = None


def local_tz():
    return _LOCAL or datetime.now().astimezone().tzinfo


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _clock(text: str):
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """A local datetime from ISO ('2026-10-20T15:00', '2026-10-20 15:00') or plain words
    ('today 3pm', 'tomorrow 09:30', 'friday 10am'). Raises CalendarError with an example."""
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    raw = str(text or "").strip()
    if not raw:
        raise CalendarError("give a time, e.g. '2026-10-20 15:00' or 'tomorrow 3pm'")
    iso = raw.replace("Z", "+00:00")
    for candidate in (iso, iso.replace(" ", "T", 1)):
        try:
            value = datetime.fromisoformat(candidate)
            if value.tzinfo is not None:
                value = value.astimezone(local_tz()).replace(tzinfo=None)
            return value
        except ValueError:
            pass
    low = raw.lower()
    day = None
    if low.startswith("today"):
        day = now.date()
    elif low.startswith("tomorrow"):
        day = now.date() + timedelta(days=1)
    else:
        for i, name in enumerate(WEEKDAYS):
            if low.startswith(name) or low.startswith(name[:3] + " "):
                ahead = (i - now.weekday()) % 7 or 7
                day = now.date() + timedelta(days=ahead)
                break
    if day is None:
        raise CalendarError("could not read the time %r - use '2026-10-20 15:00' or 'tomorrow 3pm'" % raw)
    clock = _clock(low.split(" ", 1)[1] if " " in low else "")
    if clock is None:
        raise CalendarError("give a clock time too, e.g. %r" % (raw + " 3pm"))
    return datetime(day.year, day.month, day.day, clock[0], clock[1])


# ------------------------------------------------------------------ iCalendar
def unfold(text: str) -> list:
    lines: list = []
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    return lines


def _prop(line: str) -> tuple:
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return parts[0].upper(), params, value


def _ics_unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _ics_time(value: str, params: dict):
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    m = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", value)
    if not m:
        raise ValueError("bad time %r" % value)
    dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    if m.group(3):
        dt = dt.replace(tzinfo=timezone.utc).astimezone(local_tz()).replace(tzinfo=None)
    return dt   # TZID times are read as local time (good enough for one owner in one zone)


def parse_ics(text: str) -> list:
    """VEVENTs as dicts: uid, title, start, end, all_day, location, notes, rrule, exdates."""
    events, cur, depth = [], None, 0
    for line in unfold(text):
        name, params, value = _prop(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur, depth = {"exdates": set()}, 1
            continue
        if cur is None:
            continue
        if name == "BEGIN":
            depth += 1        # VALARM inside an event
            continue
        if name == "END":
            depth -= 1
            if value.upper() == "VEVENT" or depth <= 0:
                if cur.get("start") is not None:
                    events.append(cur)
                cur = None
            continue
        if depth > 1:
            continue
        try:
            if name == "DTSTART":
                cur["start"] = _ics_time(value, params)
                cur["all_day"] = not isinstance(cur["start"], datetime)
            elif name == "DTEND":
                cur["end"] = _ics_time(value, params)
            elif name == "DURATION":
                m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", value.strip())
                if m:
                    cur["duration"] = timedelta(days=int(m.group(1) or 0), hours=int(m.group(2) or 0), minutes=int(m.group(3) or 0))
            elif name == "SUMMARY":
                cur["title"] = _ics_unescape(value)
            elif name == "LOCATION":
                cur["location"] = _ics_unescape(value)
            elif name == "DESCRIPTION":
                cur["notes"] = _ics_unescape(value)
            elif name == "UID":
                cur["uid"] = value
            elif name == "RRULE":
                cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
            elif name == "EXDATE":
                for v in value.split(","):
                    cur["exdates"].add(_ics_time(v, params))
            elif name == "STATUS" and value.upper() == "CANCELLED":
                cur["cancelled"] = True
        except ValueError:
            continue
    return [e for e in events if not e.get("cancelled")]


def _as_dt(value) -> datetime:
    return value if isinstance(value, datetime) else datetime(value.year, value.month, value.day)


def _add_months(d: datetime, n: int) -> datetime | None:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    try:
        return d.replace(year=year, month=month)
    except ValueError:
        return None      # e.g. the 31st in a 30-day month: RFC 5545 skips it


def occurrences(event: dict, start: datetime, end: datetime, cap: int = 400) -> list:
    """Start datetimes of `event` inside [start, end)."""
    first = _as_dt(event["start"])
    rule = event.get("rrule")
    if not rule:
        return [first] if start <= first < end or (first < start < _as_dt(event_end(event, first))) else []
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        try:
            until = _as_dt(_ics_time(rule["UNTIL"], {}))
        except ValueError:
            until = None
    byday = [d.strip()[-2:].upper() for d in rule.get("BYDAY", "").split(",") if d.strip()]
    codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    excluded = {_as_dt(x) for x in event.get("exdates", set())}
    out, made, n = [], 0, 0
    while n < cap * 4:
        if freq == "DAILY":
            batch = [first + timedelta(days=n * interval)]
        elif freq == "WEEKLY":
            week_start = first - timedelta(days=first.weekday()) + timedelta(weeks=n * interval)
            days = [codes.index(c) for c in byday if c in codes] or [first.weekday()]
            batch = sorted(week_start + timedelta(days=d) for d in days)
            batch = [b.replace(hour=first.hour, minute=first.minute) for b in batch if b >= first]
        elif freq == "MONTHLY":
            nxt = _add_months(first, n * interval)
            batch = [nxt] if nxt else []
        elif freq == "YEARLY":
            nxt = _add_months(first, 12 * n * interval)
            batch = [nxt] if nxt else []
        else:
            return [first] if start <= first < end else []
        n += 1
        stop = False
        for when in batch:
            if until is not None and when > until:
                stop = True
                break
            made += 1
            if count is not None and made > count:
                stop = True
                break
            if when >= end:
                stop = True
                break
            if when >= start and when not in excluded:
                out.append(when)
        if stop or len(out) >= cap:
            break
    return out


def event_end(event: dict, when: datetime):
    if event.get("end") is not None:
        return when + (_as_dt(event["end"]) - _as_dt(event["start"]))
    if event.get("duration"):
        return when + event["duration"]
    return when + (timedelta(days=1) if event.get("all_day") else timedelta(hours=1))


def expand(events: list, start: datetime, end: datetime) -> list:
    out = []
    for ev in events:
        for when in occurrences(ev, start, end):
            out.append({"title": ev.get("title", "(no title)"), "start": when, "end": event_end(ev, when),
                        "all_day": bool(ev.get("all_day")), "location": ev.get("location", ""),
                        "uid": ev.get("uid", ""), "repeats": bool(ev.get("rrule"))})
    return sorted(out, key=lambda e: e["start"])[:MAX_EVENTS]


def _ics_escape(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(title: str, start: datetime, end: datetime, location: str = "", notes: str = "", uid: str = "") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fmt = "%Y%m%dT%H%M%S"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LOKI//Calendar connector//EN", "BEGIN:VEVENT",
             "UID:" + (uid or str(uuid.uuid4()) + "@loki"), "DTSTAMP:" + stamp,
             "DTSTART:" + start.replace(tzinfo=local_tz()).astimezone(timezone.utc).strftime(fmt) + "Z",
             "DTEND:" + end.replace(tzinfo=local_tz()).astimezone(timezone.utc).strftime(fmt) + "Z",
             "SUMMARY:" + _ics_escape(title)]
    if location:
        lines.append("LOCATION:" + _ics_escape(location))
    if notes:
        lines.append("DESCRIPTION:" + _ics_escape(notes))
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


# ------------------------------------------------------------------ transports
def _http(method: str, url: str, body: bytes | None = None, headers: dict | None = None) -> tuple:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with OPENER(req, timeout=TIMEOUT_S) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError) as exc:
        raise CalendarError("cannot reach the calendar (%s)" % getattr(exc, "reason", exc)) from exc


def _caldav_headers(source: dict | None, extra: dict | None = None) -> dict:
    cred = "%s:%s" % (connectors.get("CALDAV_USER", source), connectors.get("CALDAV_PASSWORD", source))
    out = {"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()}
    out.update(extra or {})
    return out


def _utc(dt: datetime) -> str:
    return dt.replace(tzinfo=local_tz()).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def caldav_events(start: datetime, end: datetime, source: dict | None = None) -> list:
    body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            '<c:time-range start="%s" end="%s"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'
            % (_utc(start), _utc(end))).encode()
    code, text = _http("REPORT", connectors.get("CALDAV_URL", source), body,
                       _caldav_headers(source, {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}))
    if code == 401:
        raise CalendarError("the CalDAV server refused the user name or password")
    if code not in (200, 207):
        raise CalendarError("the CalDAV server answered HTTP %s (is CALDAV_URL the calendar itself?)" % code)
    events = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise CalendarError("the CalDAV answer was not XML") from exc
    for node in root.iter("{urn:ietf:params:xml:ns:caldav}calendar-data"):
        events += parse_ics(node.text or "")
    return events


def google_events(start: datetime, end: datetime, source: dict | None = None) -> list:
    import conn_google  # pylint: disable=import-outside-toplevel
    cal = urllib.parse.quote(connectors.get("CALENDAR_ID", source) or "primary", safe="")
    tz = local_tz()
    q = urllib.parse.urlencode({"timeMin": start.replace(tzinfo=tz).isoformat(), "timeMax": end.replace(tzinfo=tz).isoformat(),
                                "singleEvents": "true", "orderBy": "startTime", "maxResults": str(MAX_EVENTS)})
    try:
        data = conn_google.api("GET", "%s/calendars/%s/events?%s" % (GOOGLE_API, cal, q), source=source)
    except conn_google.GoogleError as exc:
        raise CalendarError(str(exc)) from exc
    out = []
    for item in data.get("items", []):
        s, e = item.get("start", {}), item.get("end", {})
        all_day = "date" in s and "dateTime" not in s
        try:
            if all_day:
                st = datetime.fromisoformat(s["date"])
                en = datetime.fromisoformat(e.get("date", s["date"]))
            else:
                st = datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(tz).replace(tzinfo=None)
                en = datetime.fromisoformat(e["dateTime"].replace("Z", "+00:00")).astimezone(tz).replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        out.append({"title": item.get("summary", "(no title)"), "start": st, "end": en, "all_day": all_day,
                    "location": item.get("location", ""), "uid": item.get("id", ""), "repeats": bool(item.get("recurringEventId"))})
    return out


def list_events(days: int = 7, start: str = "", end: str = "", source: dict | None = None, now: datetime | None = None) -> str:
    st = status(source)
    if not st["configured"]:
        return "error: the calendar is not set up: %s (Settings > Tools > Calendar)" % st["detail"]
    now = now or datetime.now()
    try:
        begin = parse_when(start, now) if start else now.replace(hour=0, minute=0, second=0, microsecond=0)
        finish = parse_when(end, now) if end else begin + timedelta(days=max(1, min(int(days or 7), 90)))
    except CalendarError as exc:
        return "error: %s" % exc
    k = kind(source)
    try:
        if k == "google":
            items = google_events(begin, finish, source)
        elif k == "caldav":
            items = expand(caldav_events(begin, finish, source), begin, finish)
        else:
            code, text = _http("GET", connectors.get("CALENDAR_ICS_URL", source).replace("webcal://", "https://"))
            if code != 200:
                raise CalendarError("the iCal link answered HTTP %s" % code)
            items = expand(parse_ics(text), begin, finish)
    except CalendarError as exc:
        return "error: %s" % connectors.redact(exc, source)
    if not items:
        return "nothing on the calendar from %s to %s" % (begin.strftime("%a %Y-%m-%d"), finish.strftime("%a %Y-%m-%d"))
    lines = []
    for ev in items:
        when = ev["start"].strftime("%a %Y-%m-%d") + ("  all day" if ev["all_day"] else ev["start"].strftime("  %H:%M") + "-" + ev["end"].strftime("%H:%M"))
        lines.append("%s  %s%s%s" % (when, ev["title"], ("  @ " + ev["location"]) if ev.get("location") else "",
                                      "  (repeats)" if ev.get("repeats") else ""))
    return connectors.untrusted("the calendar", "%d event(s) from %s to %s:\n%s" % (
        len(items), begin.strftime("%Y-%m-%d"), finish.strftime("%Y-%m-%d"), "\n".join(lines)))


def preview(args: dict) -> str:
    return "CREATE CALENDAR EVENT %r at %s for %s min%s" % (args.get("title", ""), args.get("start", ""),
                                                           args.get("duration_min", 60),
                                                           (" @ " + str(args["location"])) if args.get("location") else "")


def create_event(title: str, start: str, duration_min: int = 60, location: str = "", notes: str = "",
                 source: dict | None = None, now: datetime | None = None) -> str:
    """Only reached AFTER the owner approved (calendar action=create is ALWAYS_ASK)."""
    st = status(source)
    if not st["configured"]:
        return "error: the calendar is not set up: %s" % st["detail"]
    if not str(title or "").strip():
        return "error: give the event a title"
    try:
        begin = parse_when(start, now)
    except CalendarError as exc:
        return "error: %s" % exc
    finish = begin + timedelta(minutes=max(5, min(int(duration_min or 60), 24 * 60)))
    k = kind(source)
    try:
        if k == "ics":
            return "error: an iCal link is read-only - choose google or caldav in Settings > Tools > Calendar to create events"
        if k == "google":
            import conn_google  # pylint: disable=import-outside-toplevel
            tz = local_tz()
            cal = urllib.parse.quote(connectors.get("CALENDAR_ID", source) or "primary", safe="")
            body = {"summary": title, "start": {"dateTime": begin.replace(tzinfo=tz).isoformat()},
                    "end": {"dateTime": finish.replace(tzinfo=tz).isoformat()}}
            if location:
                body["location"] = location
            if notes:
                body["description"] = notes
            try:
                made = conn_google.api("POST", "%s/calendars/%s/events" % (GOOGLE_API, cal), body, source=source)
            except conn_google.GoogleError as exc:
                raise CalendarError(str(exc)) from exc
            return "created %r on %s (Google Calendar, id %s)" % (title, begin.strftime("%a %Y-%m-%d %H:%M"), made.get("id", "?"))
        uid = str(uuid.uuid4())
        url = connectors.get("CALDAV_URL", source).rstrip("/") + "/" + uid + ".ics"
        code, _ = _http("PUT", url, to_ics(title, begin, finish, location, notes, uid + "@loki").encode(),
                        _caldav_headers(source, {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"}))
        if code not in (200, 201, 204):
            raise CalendarError("the CalDAV server answered HTTP %s" % code)
        return "created %r on %s (CalDAV)" % (title, begin.strftime("%a %Y-%m-%d %H:%M"))
    except CalendarError as exc:
        return "error: %s" % connectors.redact(exc, source)


def test(source: dict | None = None) -> dict:
    result = list_events(days=7, source=source)
    return {"ok": not result.startswith("error"), "detail": result.split("\n")[-1 if result.startswith("error") else 1][:200]
            if "\n" in result else result[:200]}


ACTIONS = ("list", "create")


def tool(action: str = "list", days: int = 7, start: str = "", end: str = "", title: str = "",
         duration_min: int = 60, location: str = "", notes: str = "") -> str:
    """The `calendar` tool."""
    action = str(action or "list").strip().lower()
    if action in ("list", "agenda", "events", "view"):
        return list_events(days, start, end)
    if action == "create":     # only the exact word: the policy asks the owner for "create"
        return create_event(title, start, duration_min, location, notes)
    return "error: unknown action %r - use list or create" % action


connectors.register(__import__(__name__))
