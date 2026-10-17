"""Everyday answers with no account and no key (research round 3: the weather/news/time cards of
Lobe Chat's and Cherry Studio's plugin stores, Leon's and OpenClaw's morning-briefing skills).

  weather(place, days)     Open-Meteo (open-meteo.com: free, no key, CC BY 4.0 data) - geocoding,
                           now + daily forecast, in the units the place uses (°F in the US).
  news(topic, limit)       headlines from public RSS: Google News search for a topic, BBC World
                           for the top stories; link + source + age. LOKI_NEWS_FEED overrides.
  clock(place)             the time now in a city (the time zone comes from Open-Meteo's geocoder).
  translate(text, to, ask) the active model translates (ask = a one-shot model call); with
                           LOKI_LIBRETRANSLATE_URL set, a LibreTranslate server does it instead.

Every reply ends with a ```loki-card block (JSON) the window draws as a small card; models and the
Telegram channel just see a readable text above it.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

OPENER = urllib.request.urlopen
TIMEOUT_S = 12
GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
TOP_FEED = "https://feeds.bbci.co.uk/news/world/rss.xml"
UA = "LOKI/1.0 (personal assistant)"
FAHRENHEIT = {"US", "LR", "MM", "BS", "BZ", "KY", "PW", "FM", "MH"}

# WMO weather codes (Open-Meteo docs) -> words + a symbol for the card
WMO = {0: ("clear sky", "sun"), 1: ("mainly clear", "sun"), 2: ("partly cloudy", "cloud-sun"), 3: ("overcast", "cloud"),
       45: ("fog", "fog"), 48: ("freezing fog", "fog"), 51: ("light drizzle", "rain"), 53: ("drizzle", "rain"),
       55: ("heavy drizzle", "rain"), 56: ("freezing drizzle", "rain"), 57: ("freezing drizzle", "rain"),
       61: ("light rain", "rain"), 63: ("rain", "rain"), 65: ("heavy rain", "rain"), 66: ("freezing rain", "rain"),
       67: ("freezing rain", "rain"), 71: ("light snow", "snow"), 73: ("snow", "snow"), 75: ("heavy snow", "snow"),
       77: ("snow grains", "snow"), 80: ("rain showers", "rain"), 81: ("rain showers", "rain"),
       82: ("violent rain showers", "rain"), 85: ("snow showers", "snow"), 86: ("heavy snow showers", "snow"),
       95: ("thunderstorm", "storm"), 96: ("thunderstorm with hail", "storm"), 99: ("thunderstorm with hail", "storm")}


class EverydayError(Exception):
    pass


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with OPENER(req, timeout=TIMEOUT_S) as resp:
            return resp.read(3_000_000)
    except urllib.error.HTTPError as exc:
        raise EverydayError("%s said %d" % (urllib.parse.urlparse(url).netloc, exc.code)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise EverydayError("cannot reach %s (%s) - is this computer online?"
                            % (urllib.parse.urlparse(url).netloc, getattr(exc, "reason", exc))) from None


def _json(url: str) -> dict:
    try:
        return json.loads(_get(url).decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise EverydayError("%s sent something that is not JSON" % urllib.parse.urlparse(url).netloc) from None


def card(kind: str, data: dict) -> str:
    return "\n\n```loki-card\n" + json.dumps({"kind": kind, **data}, ensure_ascii=False) + "\n```"


def geocode(place: str) -> dict:
    place = str(place or "").strip()
    if not place:
        place = os.getenv("LOKI_HOME_CITY", "").strip()
    if not place:
        raise EverydayError("say which place (or set LOKI_HOME_CITY in Settings > General for a default)")
    name, _, region = place.partition(",")
    data = _json(GEO + "?" + urllib.parse.urlencode({"name": name.strip(), "count": 10, "language": "en", "format": "json"}))
    hits = data.get("results") or []
    if region.strip():
        want = region.strip().lower()
        narrowed = [h for h in hits if want in " ".join(str(h.get(k, "")) for k in
                                                         ("country", "country_code", "admin1", "admin2")).lower()]
        hits = narrowed or hits
    if not hits:
        raise EverydayError("no place called %r found" % place)
    h = hits[0]
    return {"name": h.get("name", place), "region": h.get("admin1", ""), "country": h.get("country", ""),
            "country_code": str(h.get("country_code", "")).upper(), "lat": h["latitude"], "lon": h["longitude"],
            "timezone": h.get("timezone", "auto")}


def weather(place: str = "", days: int = 3, units: str = "") -> str:
    try:
        geo = geocode(place)
        days = max(1, min(int(days or 3), 7))
        f = (units or "").lower().startswith("f") or (not units and geo["country_code"] in FAHRENHEIT)
        q = {"latitude": geo["lat"], "longitude": geo["lon"], "timezone": geo["timezone"] or "auto", "forecast_days": days,
             "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
             "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
             "temperature_unit": "fahrenheit" if f else "celsius", "wind_speed_unit": "mph" if f else "kmh"}
        data = _json(FORECAST + "?" + urllib.parse.urlencode(q))
    except EverydayError as exc:
        return "error: %s" % exc
    cur, daily = data.get("current") or {}, data.get("daily") or {}
    deg, wind = ("°F", "mph") if f else ("°C", "km/h")
    where = ", ".join(x for x in (geo["name"], geo["region"], geo["country"]) if x)
    words, icon = WMO.get(int(cur.get("weather_code", -1) or 0), ("", "cloud"))
    lines = ["Weather in %s now: %s, %s%s (feels %s%s), humidity %s%%, wind %s %s." % (
        where, words, cur.get("temperature_2m"), deg, cur.get("apparent_temperature"), deg,
        cur.get("relative_humidity_2m"), cur.get("wind_speed_10m"), wind)]
    rows = []
    for i, day in enumerate(daily.get("time") or []):
        w, ic = WMO.get(int((daily.get("weather_code") or [0])[i] or 0), ("", "cloud"))
        hi, lo = (daily.get("temperature_2m_max") or [None])[i], (daily.get("temperature_2m_min") or [None])[i]
        rain = (daily.get("precipitation_probability_max") or [None] * (i + 1))[i]
        label = datetime.strptime(day, "%Y-%m-%d").strftime("%a %d %b")
        rows.append({"day": label, "hi": hi, "lo": lo, "rain": rain, "words": w, "icon": ic})
        lines.append("- %s: %s, %s%s / %s%s, rain chance %s%%" % (label, w, hi, deg, lo, deg, rain if rain is not None else "?"))
    lines.append("(Open-Meteo.com, CC BY 4.0)")
    return "\n".join(lines) + card("weather", {"place": where, "now": {"temp": cur.get("temperature_2m"),
                                                                        "feels": cur.get("apparent_temperature"),
                                                                        "words": words, "icon": icon,
                                                                        "wind": cur.get("wind_speed_10m")},
                                                "unit": deg, "wind_unit": wind, "days": rows})


def _age(stamp: str) -> str:
    try:
        when = parsedate_to_datetime(stamp)
        mins = int((datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds() // 60)
    except (TypeError, ValueError, IndexError):
        return ""
    if mins < 60:
        return "%d min ago" % max(mins, 0)
    if mins < 48 * 60:
        return "%d h ago" % (mins // 60)
    return "%d days ago" % (mins // 1440)


def news(topic: str = "", limit: int = 8) -> str:
    url = os.getenv("LOKI_NEWS_FEED", "").strip() if not topic else ""
    url = url or (GNEWS % urllib.parse.quote(str(topic)) if topic else TOP_FEED)
    try:
        root = ET.fromstring(_get(url))
    except EverydayError as exc:
        return "error: %s" % exc
    except ET.ParseError:
        return "error: the news feed was not readable"
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        source = (it.findtext("source") or "").strip()
        if not source and " - " in title and "news.google" in url:
            title, _, source = title.rpartition(" - ")
        if title and link.startswith(("http://", "https://")):
            items.append({"title": title, "link": link, "source": source or urllib.parse.urlparse(url).netloc,
                          "age": _age(it.findtext("pubDate") or "")})
        if len(items) >= max(1, min(int(limit or 8), 25)):
            break
    if not items:
        return "No headlines found%s." % (" for %r" % topic if topic else "")
    head = "Headlines%s:" % (" about %s" % topic if topic else " (BBC World)")
    body = "\n".join("%d. %s - %s%s\n   %s" % (i + 1, x["title"], x["source"], (", " + x["age"]) if x["age"] else "", x["link"])
                     for i, x in enumerate(items))
    return head + "\n" + body + card("news", {"topic": topic, "items": items})


def clock(place: str = "") -> str:
    try:
        geo = geocode(place)
    except EverydayError as exc:
        return "error: %s" % exc
    try:
        from zoneinfo import ZoneInfo  # pylint: disable=import-outside-toplevel
        now = datetime.now(ZoneInfo(geo["timezone"]))
    except Exception:  # noqa: BLE001 - no tz database (Windows without tzdata): ask Open-Meteo for the offset
        try:
            data = _json(FORECAST + "?" + urllib.parse.urlencode({"latitude": geo["lat"], "longitude": geo["lon"],
                                                                  "timezone": geo["timezone"], "current": "temperature_2m"}))
            now = datetime.fromtimestamp(time.time() + int(data.get("utc_offset_seconds", 0)), timezone.utc)
        except EverydayError as exc:
            return "error: %s" % exc
    where = ", ".join(x for x in (geo["name"], geo["country"]) if x)
    text = "It is %s in %s (%s)." % (now.strftime("%H:%M on %A %d %B"), where, geo["timezone"])
    return text + card("clock", {"place": where, "time": now.strftime("%H:%M"), "date": now.strftime("%a %d %b"),
                                 "zone": geo["timezone"]})


LANG = re.compile(r"^[A-Za-z][A-Za-z ()-]{1,30}$")


async def translate(text: str, to: str, ask=None, source_lang: str = "") -> str:
    text, to = str(text or "").strip(), str(to or "").strip()
    if not text:
        return "error: give the text to translate"
    if not LANG.match(to):
        return "error: say the language to translate into, e.g. to='Spanish' or to='es'"
    server = os.getenv("LOKI_LIBRETRANSLATE_URL", "").strip().rstrip("/")
    if server:
        body = json.dumps({"q": text[:8000], "source": source_lang or "auto", "target": to[:2].lower(),
                           "format": "text"}).encode()
        req = urllib.request.Request(server + "/translate", data=body, headers={"Content-Type": "application/json"})
        try:
            with OPENER(req, timeout=TIMEOUT_S) as resp:
                out = json.loads(resp.read().decode("utf-8", "replace"))
            if out.get("translatedText"):
                return out["translatedText"]
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            pass   # fall through to the model
    if ask is None:
        return "error: no model to translate with"
    prompt = ("Translate the text between the markers into %s%s. Keep the meaning, tone and formatting. Reply with "
              "ONLY the translation.\n<<<\n%s\n>>>" % (to, (" (from %s)" % source_lang) if source_lang else "", text[:8000]))
    out = str(await ask(prompt) or "").strip()
    return out.strip("<>").strip() or "error: the model returned nothing"
