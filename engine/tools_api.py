"""Loopback API for Settings > Tools: the tool health map, the connectors' cards, computer use.

  GET  /tools/health                    every tool / MCP server / add-on / connector / computer / browser
  POST /tools/health/fix {id, action, arg, confirm}   the one-click fix (reset, enable_category, enable_addon,
                                         install, enable_mcp, arm_computer, recheck)
  POST /tools/health/recheck            re-run the cheap checks now
  GET  /connectors                      the connector cards (secrets only as saved / not saved)
  POST /connectors/save {id, values}    save settings (a blank secret keeps the saved one)
  POST /connectors/test {id}            one cheap real request
  POST /connectors/forget {id}          remove that connector's secrets
  POST /connectors/signin {id: google}  start "Sign in with Google" (opens the browser) -> {state, url}
  GET  /connectors/signin/status?state=
  GET  /computer                        computer use: armed?, backend, approved apps, recent log
  POST /computer/stop | /computer/arm | /computer/forget

Kept out of loki_bridge.py so the bridge only routes here. No secret ever leaves through these routes.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from typing import Any
from urllib.parse import parse_qs, urlparse

import connectors
import tool_health

INSTALLS: dict = {}       # add-on name -> {"running", "ok", "log", "error"}


def _write_env(agent: Any):
    import peer_link  # pylint: disable=import-outside-toplevel
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    return lambda updates: peer_link.write_env(Path(agent.env_file_path()), updates)


def _computer(agent: Any):
    return getattr(agent, "COMPUTER", None)


def extra_items(agent: Any) -> list:
    """The connectors, computer use and the Chromium browser as health-map rows."""
    items = []
    tool_of = {spec.get("tool"): cid for cid, spec in connectors.SPECS.items()}
    for card in connectors.present():
        if card["id"] in ("computer", "browser"):      # settings-only cards; their rows come below
            continue
        name = card.get("tool") or card["id"]
        st = "ok" if card["configured"] else "needs_setup"
        item = tool_health._item("connector:" + card["id"], "connector", card["label"], True, card["configured"], st,  # noqa: SLF001
                                 card["detail"], {} if card["configured"] else {"action": "configure", "arg": card["id"],
                                                                                "label": "Set up"},
                                 tool=card.get("tool", ""), writes=card.get("writes", []))
        items.append(tool_health._with_stats(item, tool_health.HEALTH, name) if name in tool_of else item)  # noqa: SLF001
    comp = _computer(agent)
    registry = getattr(agent, "CAPABILITIES", None)
    try:
        on = bool(registry and registry.is_enabled("computer-use"))
    except Exception:  # noqa: BLE001
        on = False
    if comp is not None:
        try:
            state = comp.state()
        except Exception as exc:  # noqa: BLE001
            state = {"available": False, "detail": str(exc), "armed": True, "tripped": ""}
        if not state.get("available"):
            st, detail, fix = "missing", state.get("detail", ""), {"action": "hint", "label": "Why", "arg": state.get("detail", "")}
        elif not on:
            st, detail, fix = "off", "the computer-use add-on is off", {"action": "enable_addon", "arg": "computer-use",
                                                                        "label": "Turn on computer use"}
        elif not state.get("armed"):
            st, detail, fix = "stopped", "kill switch: " + (state.get("tripped") or "stopped"), {"action": "arm_computer",
                                                                                               "label": "Re-arm"}
        else:
            st, detail, fix = "ok", state.get("detail", ""), {}
        items.append(tool_health._with_stats(tool_health._item("computer", "computer", "Computer use (this desktop)",  # noqa: SLF001
                                                               bool(state.get("available")), on, st, detail, fix),
                                             tool_health.HEALTH, "computer"))
    browser = getattr(agent, "CHROMIUM", None)
    if browser is not None:
        try:
            chromium_on = bool(registry and registry.is_enabled("chromium"))
        except Exception:  # noqa: BLE001
            chromium_on = False
        if chromium_on:
            ok, detail = browser.available()
            st, fix = ("ok", {}) if ok else ("missing", {"action": "install", "arg": "chromium", "label": "Install Chromium"})
        else:
            ok, detail = False, "off - pages that need JavaScript are read without it (text browser)"
            st, fix = "off", {"action": "enable_addon", "arg": "chromium", "label": "Turn on Chromium"}
        items.append(tool_health._with_stats(tool_health._item("browser", "browser", "Browser (text + Chromium)", ok, chromium_on,
                                                               st, detail, fix), tool_health.HEALTH, "browse_page"))
    return items


def health(agent: Any) -> dict:
    out = tool_health.build(agent, tool_health.HEALTH, extra=extra_items(agent))
    covered = {spec.get("tool") for spec in connectors.SPECS.values() if spec.get("tool")} | {"computer"}
    out["items"] = [it for it in out["items"] if not (it["kind"] == "tool" and it["id"] in covered)]   # one row each
    order = {"connector": 0, "computer": 1, "browser": 2, "tool": 3, "mcp": 4, "addon": 5}
    out["items"].sort(key=lambda it: (order.get(it["kind"], 9), it["status"] == "ok", it["label"].lower()))
    out["installs"] = {k: dict(v) for k, v in INSTALLS.items()}
    return out


def _install(agent: Any, name: str) -> dict:
    import addons_install  # pylint: disable=import-outside-toplevel
    if INSTALLS.get(name, {}).get("running"):
        return {"ok": True, "started": False, "note": "already installing"}
    if not addons_install.installable(name):
        return {"ok": False, "error": addons_install.manual_hint(name) or "%s cannot be installed from here" % name}
    INSTALLS[name] = {"running": True, "ok": False, "log": [], "error": ""}

    def run() -> None:
        result = addons_install.install(name, python=sys.executable)
        INSTALLS[name].update(running=False, ok=bool(result.get("ok")), log=result.get("log", []), error=result.get("error", ""))
        tool_health.clear_probes()
        if name == "chromium" and getattr(agent, "CHROMIUM", None) is not None:
            agent.CHROMIUM._available = None   # noqa: SLF001 - check again
    threading.Thread(target=run, daemon=True, name="loki-install-" + name).start()
    return {"ok": True, "started": True}


def fix(agent: Any, data: dict) -> tuple:
    action = str(data.get("action") or "")
    arg = str(data.get("arg") or "")
    item = str(data.get("id") or "")
    if action == "reset":
        name = arg or item.split(":", 1)[-1]
        if tool_health.HEALTH is not None:
            tool_health.HEALTH.reset(name)
        tool_health.clear_probes()
        return 200, {"ok": True, "note": "%s is offered to the model again" % name}
    if action == "recheck":
        tool_health.clear_probes()
        return 200, {"ok": True}
    if action == "enable_category":
        ok = bool(agent.set_category(arg, True))
        return (200 if ok else 400), {"ok": ok}
    if action == "enable_addon":
        registry = getattr(agent, "CAPABILITIES", None)
        if registry is None:
            return 400, {"ok": False, "error": "no add-on registry"}
        entry = registry.get(arg)
        if entry is None:
            return 404, {"ok": False, "error": "no add-on %r" % arg}
        import manifests  # pylint: disable=import-outside-toplevel
        risky = [manifests.describe_permission(p) for p in entry["manifest"].get("permissions", []) if p in manifests.HIGH_RISK]
        if risky and not data.get("confirm"):
            return 200, {"ok": False, "confirm": "Turn on %s? It will be allowed to: %s" % (arg, "; ".join(risky))}
        try:
            registry.set_enabled(arg, True)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        tool_health.clear_probes()
        return 200, {"ok": True}
    if action == "install":
        return 200, _install(agent, arg)
    if action == "enable_mcp":
        current = [s.strip() for s in os.getenv("LOKI_MCP_ENABLE", "").split(",") if s.strip()]
        if arg and arg not in current:
            current.append(arg)
        _write_env(agent)({"LOKI_MCP_ENABLE": ",".join(current)})
        return 200, {"ok": True, "note": "%s starts the next time LOKI starts" % arg}
    if action == "arm_computer":
        comp = _computer(agent)
        if comp is None:
            return 400, {"ok": False, "error": "computer use is not loaded"}
        comp.arm()
        return 200, {"ok": True}
    if action in ("configure", "hint"):
        return 200, {"ok": True}
    return 400, {"ok": False, "error": "unknown fix %r" % action}


def handle(state: Any, method: str, path: str, data: dict) -> tuple:
    agent = state.agent
    route = urlparse(path).path
    query = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    if route == "/tools/health":
        return 200, {"ok": True, **health(agent)}
    if route == "/tools/health/fix" and method == "POST":
        return fix(agent, data)
    if route == "/tools/health/recheck" and method == "POST":
        tool_health.clear_probes()
        return 200, {"ok": True, **health(agent)}
    if route == "/connectors":
        return 200, {"ok": True, "connectors": connectors.present()}
    if route == "/connectors/save" and method == "POST":
        result = connectors.save(str(data.get("id", "")), data.get("values") or {}, _write_env(agent))
        tool_health.clear_probes()
        return (200 if result.get("ok") else 400), result
    if route == "/connectors/test" and method == "POST":
        result = connectors.test(str(data.get("id", "")))
        if result.get("ok") and tool_health.HEALTH is not None:
            tool = connectors.SPECS.get(str(data.get("id", "")), {}).get("tool")
            if tool:
                tool_health.HEALTH.reset(tool)
        return 200, {"ok": True, "result": result}
    if route == "/connectors/forget" and method == "POST":
        result = connectors.forget(str(data.get("id", "")), _write_env(agent))
        tool_health.clear_probes()
        return (200 if result.get("ok") else 400), result
    if route == "/connectors/signin" and method == "POST":
        import conn_google  # pylint: disable=import-outside-toplevel
        opener = (lambda url: threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start())
        return 200, conn_google.start_signin(_write_env(agent), open_browser=opener)
    if route == "/connectors/signin/status":
        import conn_google  # pylint: disable=import-outside-toplevel
        if conn_google.signin_status(query.get("state", "")).get("signed_in"):
            tool_health.clear_probes()
        return 200, conn_google.signin_status(query.get("state", ""))
    if route.startswith("/computer"):
        import computer_use  # pylint: disable=import-outside-toplevel
        if method == "GET" and route != "/computer":
            return 404, {"ok": False, "error": "unknown endpoint"}
        return computer_use.handle(_computer(agent), route, data)
    return 404, {"ok": False, "error": "unknown endpoint"}


def owns(route: str) -> bool:
    return route.startswith(("/tools/health", "/connectors", "/computer"))
