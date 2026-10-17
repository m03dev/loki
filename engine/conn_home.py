"""Home connector: Home Assistant (research round 3 - the most-asked "assistant" job LOKI could not do:
"turn off the living room lights", "is the back door locked?", "how warm is it upstairs?").

Home Assistant's own REST API (developers.home-assistant.io/docs/api/rest), a long-lived access
token from your HA profile page (Security > Long-lived access tokens). Standard library only.

Read actions (no question asked): status, list (by domain or area word), find (by name, fuzzy),
state (one device), history (one device, last hours).
Write actions (each one ASKS the owner - engine/policy.py ACTION_ALWAYS_ASK, never in a background
job): turn_on, turn_off, toggle (lights/switches/fans/covers/media...; brightness, colour, temperature
when given), call (any HA service, e.g. climate.set_temperature), assist (hand a sentence to HA's own
Assist, which can act).
Names work: entity='kitchen light' is resolved to light.kitchen by its friendly name.
"""
from __future__ import annotations

import difflib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import connectors

SPEC = {
    "id": "home",
    "label": "Home (Home Assistant)",
    "about": "See and control your smart home through Home Assistant: lights, switches, thermostats, locks, "
             "sensors, media. Reading is free; every change asks you first.",
    "tool": "home",
    "writes": ["turn_on", "turn_off", "toggle", "call", "assist"],
    "help": "HA address: e.g. http://homeassistant.local:8123. Token: in Home Assistant open your profile > Security > "
            "Long-lived access tokens > Create token, and paste it here.",
    "fields": [
        {"key": "HA_URL", "label": "Home Assistant address", "kind": "text"},
        {"key": "HA_TOKEN", "label": "Long-lived access token", "kind": "secret"},
    ],
}
ACTIONS = ("status", "list", "find", "state", "history", "turn_on", "turn_off", "toggle", "call", "assist")
WRITES = set(SPEC["writes"])
OPENER = urllib.request.urlopen
TIMEOUT_S = 15
ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
SENSITIVE = ("lock.", "alarm_control_panel.", "cover.garage", "valve.")
CONTROLLABLE = ("light", "switch", "fan", "cover", "media_player", "climate", "input_boolean", "scene", "script",
                "lock", "humidifier", "vacuum", "automation", "siren", "valve", "water_heater", "button")
_CACHE: dict = {"at": 0.0, "states": []}


class HomeError(Exception):
    pass


def _base(source: dict | None = None) -> str:
    raw = connectors.get("HA_URL", source).rstrip("/")
    if raw and not re.match(r"^https?://", raw):
        raw = "http://" + raw
    return raw[:-4] if raw.endswith("/api") else raw


def status(source: dict | None = None) -> dict:
    if not _base(source):
        return {"configured": False, "detail": "set the Home Assistant address"}
    if not connectors.get("HA_TOKEN", source):
        return {"configured": False, "detail": "paste a long-lived access token"}
    return {"configured": True, "detail": "Home Assistant at %s" % urllib.parse.urlparse(_base(source)).netloc}


def _request(method: str, path: str, body=None, source: dict | None = None):
    base, token = _base(source), connectors.get("HA_TOKEN", source)
    if not base or not token:
        raise HomeError("Home Assistant is not set up (Settings > Tools > Home)")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with OPENER(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HomeError("Home Assistant said 401: the token is wrong or was deleted - make a new one") from None
        if exc.code == 404:
            raise HomeError("Home Assistant has no %s (404) - check the device or service name" % path) from None
        raise HomeError("Home Assistant said %d %s" % (exc.code, exc.reason)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise HomeError("cannot reach Home Assistant at %s (%s) - is it on, and is this computer on the same "
                        "network?" % (base, getattr(exc, "reason", exc))) from None
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {"text": raw[:500]}


def test(source: dict | None = None) -> dict:
    try:
        out = _request("GET", "/api/", source=source)
        n = len(_request("GET", "/api/states", source=source) or [])
        return {"ok": True, "detail": "%s - %d devices and sensors" % (out.get("message", "API running"), n)}
    except HomeError as exc:
        return {"ok": False, "detail": connectors.redact(exc, source)}


def states(source: dict | None = None, fresh: bool = False) -> list:
    if not fresh and time.time() - _CACHE["at"] < 10 and _CACHE["states"]:
        return _CACHE["states"]
    data = _request("GET", "/api/states", source=source)
    _CACHE.update(at=time.time(), states=data if isinstance(data, list) else [])
    return _CACHE["states"]


def _name(s: dict) -> str:
    return str((s.get("attributes") or {}).get("friendly_name") or s.get("entity_id", ""))


def _line(s: dict) -> str:
    attrs = s.get("attributes") or {}
    extra = []
    unit = attrs.get("unit_of_measurement")
    if s.get("entity_id", "").startswith("light.") and attrs.get("brightness") is not None:
        extra.append("brightness %d%%" % round(int(attrs["brightness"]) * 100 / 255))
    if s.get("entity_id", "").startswith("climate."):
        for k in ("current_temperature", "temperature", "hvac_action"):
            if attrs.get(k) is not None:
                extra.append("%s %s" % (k.replace("_", " "), attrs[k]))
    return "%s (%s): %s%s%s" % (_name(s), s.get("entity_id"), s.get("state"), (" " + unit) if unit else "",
                                (" - " + ", ".join(extra)) if extra else "")


def resolve(entity: str, source: dict | None = None, domains: tuple = ()) -> dict:
    """An entity id or a name ('kitchen light') -> the state dict. Raises HomeError with suggestions."""
    want = str(entity or "").strip()
    if not want:
        raise HomeError("say which device: entity='light.kitchen' or its name, e.g. entity='kitchen light'")
    items = states(source)
    if ENTITY.match(want.lower()):
        for s in items:
            if s.get("entity_id") == want.lower():
                return s
    pool = [s for s in items if not domains or s.get("entity_id", "").split(".")[0] in domains] or items
    low = want.lower()
    exact = [s for s in pool if _name(s).lower() == low]
    if len(exact) == 1:
        return exact[0]
    words = [w for w in re.findall(r"[a-z0-9]+", low) if w not in ("the", "light", "lights", "lamp")] or [low]
    contains = [s for s in pool if all(w in (_name(s) + " " + s.get("entity_id", "")).lower().replace("_", " ") for w in words)]
    if len(contains) == 1:
        return contains[0]
    names = {_name(s).lower(): s for s in pool}
    close = difflib.get_close_matches(low, list(names), n=4, cutoff=0.55)
    if len(contains) > 1 or len(close) > 1 or not close:
        options = (contains or [names[c] for c in close])[:6]
        hint = ("; did you mean: " + "; ".join("%s (%s)" % (_name(s), s["entity_id"]) for s in options)) if options else ""
        raise HomeError("more than one device matches %r%s" % (want, hint) if len(contains) > 1
                        else "no device called %r%s" % (want, hint))
    return names[close[0]]


def _service_data(args: dict) -> dict:
    data: dict = {}
    if args.get("brightness") not in (None, ""):
        data["brightness_pct"] = max(0, min(100, int(float(args["brightness"]))))
    if args.get("color"):
        data["color_name"] = str(args["color"]).strip().lower()
    if args.get("temperature") not in (None, ""):
        data["temperature"] = float(args["temperature"])
    extra = args.get("data")
    if isinstance(extra, str) and extra.strip():
        try:
            extra = json.loads(extra)
        except json.JSONDecodeError:
            raise HomeError("data must be JSON, e.g. data='{\"temperature\": 21}'") from None
    if isinstance(extra, dict):
        data.update(extra)
    return data


def describe_write(args: dict, source: dict | None = None) -> str:
    """The line the owner sees in the approval prompt (names, not just ids)."""
    action = str(args.get("action", "")).lower()
    if action == "assist":
        return "Home Assistant Assist: %r" % str(args.get("text", ""))[:200]
    try:
        target = _name(resolve(args.get("entity", ""), source)) if args.get("entity") else ""
    except HomeError:
        target = str(args.get("entity", ""))
    what = action.replace("_", " ") if action != "call" else "%s.%s" % (args.get("domain", "?"), args.get("service", "?"))
    data = {k: args[k] for k in ("brightness", "color", "temperature") if args.get(k) not in (None, "")}
    entity_id = str(args.get("entity", ""))
    try:
        entity_id = resolve(entity_id, source)["entity_id"] if entity_id else ""
    except HomeError:
        pass
    flag = "SECURITY DEVICE - " if entity_id.startswith(SENSITIVE) else ""
    return "%s%s %s%s" % (flag, what, target, (" " + json.dumps(data)) if data else "")


def tool(action: str = "status", entity: str = "", domain: str = "", service: str = "", text: str = "",
         brightness=None, color: str = "", temperature=None, data=None, hours: int = 24, limit: int = 40,
         source: dict | None = None) -> str:
    action = str(action or "status").strip().lower()
    if action not in ACTIONS:
        return "error: action must be one of %s" % ", ".join(ACTIONS)
    try:
        if action == "status":
            items = states(source, fresh=True)
            by: dict = {}
            for s in items:
                by.setdefault(s.get("entity_id", "?").split(".")[0], []).append(s)
            on = [s for s in items if s.get("entity_id", "").split(".")[0] in ("light", "switch", "fan", "media_player")
                  and s.get("state") in ("on", "playing")]
            lines = ["Home Assistant: %d devices and sensors (%s)." % (len(items), ", ".join(
                "%d %s" % (len(v), k) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))[:10]))]
            if on:
                lines.append("On now: " + ", ".join(_name(s) for s in on[:20]))
            unlocked = [s for s in by.get("lock", []) if s.get("state") == "unlocked"]
            if unlocked:
                lines.append("Unlocked: " + ", ".join(_name(s) for s in unlocked))
            return "\n".join(lines)
        if action in ("list", "find"):
            items = states(source)
            dom = str(domain or "").strip().lower()
            q = str(entity or text or "").strip().lower()
            hits = [s for s in items if (not dom or s.get("entity_id", "").startswith(dom + "."))
                    and (not q or all(w in (_name(s) + " " + s.get("entity_id", "")).lower().replace("_", " ")
                                      for w in q.split()))]
            if not hits and q:
                names = {_name(s).lower(): s for s in items}
                hits = [names[c] for c in difflib.get_close_matches(q, list(names), n=8, cutoff=0.5)]
            if not hits:
                return "No device matches." + (" Domains here: " + ", ".join(sorted({s.get("entity_id", "").split(".")[0]
                                                                                 for s in items})) if items else "")
            n = max(1, min(int(limit or 40), 200))
            return "\n".join(_line(s) for s in hits[:n]) + ("\n(+%d more)" % (len(hits) - n) if len(hits) > n else "")
        if action == "state":
            return _line(resolve(entity, source))
        if action == "history":
            s = resolve(entity, source)
            start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3600 * max(1, min(int(hours or 24), 168))))
            rows = _request("GET", "/api/history/period/%s+00:00?filter_entity_id=%s&minimal_response"
                            % (start, urllib.parse.quote(s["entity_id"])), source=source)
            points = rows[0] if isinstance(rows, list) and rows else []
            if not points:
                return "No history for %s in that time." % _name(s)
            tail = points[-30:]
            return "%s, last %d h (%d changes):\n%s" % (_name(s), int(hours or 24), len(points), "\n".join(
                "%s  %s" % (str(p.get("last_changed", ""))[:16].replace("T", " "), p.get("state")) for p in tail))
        if action == "assist":
            if not str(text or "").strip():
                return "error: give the sentence for Assist in text="
            out = _request("POST", "/api/conversation/process", {"text": str(text), "language": "en"}, source=source)
            speech = (((out.get("response") or {}).get("speech") or {}).get("plain") or {}).get("speech")
            return "Assist: %s" % (speech or json.dumps(out)[:400])
        # turn_on / turn_off / toggle / call
        if action == "call":
            dom, svc = str(domain or "").strip().lower(), str(service or "").strip().lower()
            if not re.match(r"^[a-z_]+$", dom) or not re.match(r"^[a-z_]+$", svc):
                return "error: call needs domain= and service=, e.g. domain='climate' service='set_temperature'"
            body = _service_data({"brightness": brightness, "color": color, "temperature": temperature, "data": data})
            target = None
            if entity:
                target = resolve(entity, source)
                body["entity_id"] = target["entity_id"]
        else:
            target = resolve(entity, source, domains=CONTROLLABLE)
            dom = target["entity_id"].split(".")[0]
            svc = action
            if dom == "lock":
                svc = {"turn_on": "lock", "turn_off": "unlock"}.get(action, "")
                if not svc:
                    return "error: a lock is locked (turn_on) or unlocked (turn_off), it does not toggle"
            if dom == "cover":
                svc = {"turn_on": "open_cover", "turn_off": "close_cover", "toggle": "toggle"}[action]
            if dom in ("scene", "script") and action == "turn_on":
                svc = "turn_on"
            body = {"entity_id": target["entity_id"],
                    **_service_data({"brightness": brightness, "color": color, "temperature": temperature, "data": data})}
        _request("POST", "/api/services/%s/%s" % (dom, svc), body, source=source)
        _CACHE["at"] = 0.0
        if target is not None:
            try:
                time.sleep(0.4)
                now = resolve(target["entity_id"], source)
                return "Done: %s.%s -> %s" % (dom, svc, _line(now))
            except HomeError:
                pass
        return "Done: %s.%s" % (dom, svc)
    except HomeError as exc:
        return "error: %s" % connectors.redact(exc, source)
    except (TypeError, ValueError) as exc:
        return "error: %s" % exc
