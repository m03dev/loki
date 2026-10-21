"""The window's routes for LOKI Spaces (engine/spaces.py). Behind loki_bridge's bearer token, like every route.

    GET  /spaces                         my spaces (hosted + joined), my name, the spaces port and relay
    GET  /spaces/sync?space=&since=      rooms, members (online, voice), new events, WebRTC signals for me
    GET  /spaces/key?space=              the space key, for the window's end-to-end encryption (WebCrypto)
    GET  /spaces/invite?space=           the invite code (and where it points)
    GET  /spaces/world                   open lobbies / voice rooms for LOKI World (docs/SPACES.md)
    POST /spaces/create {name, color?, icon?}
    POST /spaces/join   {code, name?}
    POST /spaces/forget {space}           leave (joined) or delete (hosted, kept on disk renamed)
    POST /spaces/profile {name?, color?}
    POST /spaces/act    {space, action, ...}   action: send edit delete react typing room voice signal mod leave space
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import spaces

ACTIONS = {"send", "edit", "delete", "react", "typing", "room", "voice", "signal", "mod", "leave", "space"}


def owns(route: str) -> bool:
    return route == "/spaces" or route.startswith("/spaces/")


def start() -> None:
    """At engine start: serve the spaces this machine hosts (nothing listens when it hosts none)."""
    try:
        spaces.instance().start()
    except Exception as exc:  # noqa: BLE001 - Spaces is optional; the engine must start
        print("[loki-bridge] spaces unavailable: %s" % exc, flush=True)


def route(method: str, path: str, body: dict | None = None, s: "spaces.Spaces | None" = None) -> tuple:
    """s: the Spaces to act on (tests run two machines in one process); the engine's own by default."""
    url = urlparse(path)
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    r, b = url.path, body or {}
    s = s or spaces.instance()
    try:
        if method == "GET":
            if r == "/spaces":
                return 200, s.listing()
            if r == "/spaces/sync":
                return 200, s.sync(q.get("space", ""), int(q.get("since", "0") or 0))
            if r == "/spaces/key":
                return 200, {"ok": True, "key": s.key(q.get("space", ""))}
            if r == "/spaces/invite":
                return 200, s.invite(q.get("space", ""))
            if r == "/spaces/world":
                return 200, s.world()
            return 404, {"ok": False, "error": "Unknown endpoint."}
        if r == "/spaces/create":
            return 200, s.create(b.get("name"), b.get("color"), b.get("icon", ""))
        if r == "/spaces/join":
            return 200, s.join(str(b.get("code", "")), b.get("name"))
        if r == "/spaces/forget":
            return 200, s.forget(str(b.get("space", "")))
        if r == "/spaces/profile":
            return 200, {"ok": True, **s.profile(b.get("name"), b.get("color"))}
        if r == "/spaces/act":
            action = str(b.get("action", ""))
            if action not in ACTIONS:
                return 400, {"ok": False, "error": "unknown action"}
            rest = {k: v for k, v in b.items() if k not in ("action", "space")}
            return 200, s.act(str(b.get("space", "")), action, rest)
        return 404, {"ok": False, "error": "Unknown endpoint."}
    except spaces.SpaceError as exc:
        return exc.code, {"ok": False, "error": str(exc)}
    except (TypeError, ValueError) as exc:
        return 400, {"ok": False, "error": "bad request: %s" % exc}
