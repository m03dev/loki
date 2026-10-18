"""Loopback API for the reworked Settings: Connections portal, sign-in, QR codes, general
settings, the agent builder, and Update everything. Kept out of loki_bridge.py so that file
only has to route here:

  GET  /providers                         every provider card (providers_catalog.present), with health
  GET  /models/doctor                     the routing in plain words (routing.doctor)
  GET  /providers/health                  the provider health registry (provider_health)
  POST /providers/probe      {id?}        re-check one/all providers now (free /models calls only)
  POST /providers/test       {id}         one real 1-token request
  POST /providers/models     {id}         its live model list
  POST /providers/model      {id, model}  use this model for it
  POST /providers/enable     {id, on}     switch it on/off for routing
  POST /providers/connect    {id, key, account_id?}   check + save a key
  POST /providers/disconnect {id}         forget its key
  POST /providers/default    {id}         make it the default (LOKI_MODEL)
  POST /signin/openrouter    {mode}       browser | code  -> {state, url}
  POST /signin/openrouter/code {state, code}
  POST /signin/device        {id}         RFC 8628 sign-in code
  GET  /signin/status?state=              is that sign-in done
  POST /handoff              {id}         one-time "send a key from your phone" page
  GET  /handoff/status?id=
  GET  /qr?text=                          an SVG QR code
  GET  /settings/general | POST /settings/general {key: value}
  GET  /skills                            every SKILL.md an agent can load
  GET  /agents/templates                  starting points for the builder
  POST /agents/draft         {description} a complete agent from one sentence
  POST /agents/launch        {id, task}   run it here or on the machine it lives on
  GET  /update/everywhere                 every machine's version and the last run
  POST /update/everywhere                 update all linked machines, then this one
  POST /update/apply                      update this machine now and restart

The OAuth callback (GET /oauth/openrouter/callback) is the one route without the bearer
token - the browser reaches it straight from openrouter.ai - and it only finishes a flow
this engine started (its `state`).
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import providers_catalog
import qr
import signin

# Settings > General: what may be changed from the window, with its kind and choices.
GENERAL = {
    "LOKI_AUTO_UPDATE": {"kind": "bool", "default": "1", "label": "Update automatically from GitHub when LOKI starts"},
    "LOKI_UPDATE_EVERY_S": {"kind": "int", "default": "600", "min": 300, "max": 86400,
                            "label": "Check for updates every (seconds)"},
    "LOKI_BACKGROUND": {"kind": "choice", "choices": ["auto", "on", "off"], "default": "auto",
                        "label": "Keep working in the background when the window is closed (auto: on for Windows)"},
    "LOKI_START_AT_LOGIN": {"kind": "choice", "choices": ["auto", "on", "off"], "default": "auto",
                            "label": "Start LOKI (in the background) when I log in (auto: on for Windows)"},
    "LOKI_FORCE_UPDATE": {"kind": "bool", "default": "1",
                          "label": "Apply updates by itself when idle and restart the whole app"},
    "LOKI_ALLOW_PAID": {"kind": "bool", "default": "0", "label": "Allow paid providers in automatic routing"},
    "LOKI_DAILY_USD_LIMIT": {"kind": "float", "default": "1.0", "min": 0, "max": 100,
                             "label": "Daily limit for paid use (USD)"},
    "LOKI_SELF_SHIP": {"kind": "choice", "default": "auto", "choices": ["auto", "ask", "off"],
                       "label": "LOKI may ship changes to its own code"},
    "LOKI_MAIN_DRIVER": {"kind": "choice", "default": "nvidia", "choices": ["nvidia", "off"],
                         "label": "Main driver: DeepSeek V4.1 Flash on NVIDIA first for everything (when its key is set)"},
    "LOKI_NVIDIA_THINKING": {"kind": "choice", "default": "off", "choices": ["off", "high", "max"],
                             "label": "DeepSeek on NVIDIA thinks before answering (slower, uses more of the 40/min)"},
    "LOKI_PREFER": {"kind": "choice", "default": "local", "choices": ["local", "cloud"],
                    "label": "Prefer local models or the cloud"},
    "LOKI_LOCAL_ONLY": {"kind": "bool", "default": "0",
                        "label": "Private: only models on this computer (nothing is sent to a cloud model)"},
    "LOKI_WORLD": {"kind": "choice", "default": "background", "choices": ["background", "panel", "off"],
                   "label": "LOKI World (3D): behind the home screen, only in its panel, or off"},
    "LOKI_WORLD_ENGINE": {"kind": "choice", "default": "babylon", "choices": ["babylon", "godot", "classic", "three"],
                          "label": "LOKI World engine: babylon = Babylon.js in the pixel cel-shaded look (default); godot = the Godot MMO's web build (falls back to babylon until it is exported); classic = the light hand-written one; three = smooth three.js"},
    "LOKI_PROMPTED_TOOLS": {"kind": "text", "default": "", "label": "Providers that get tools as text (comma list)"},
    "LOKI_OPENCODE_MODEL": {"kind": "text", "default": "", "label": "OpenCode model (provider/model)"},
    "LOKI_EVOLVE": {"kind": "choice", "default": "auto", "choices": ["auto", "on", "off"],
                    "label": "LOKI grows its own core by itself when idle (auto: on the Windows PC only)"},
    "LOKI_OPTIONS": {"kind": "choice", "default": "auto", "choices": ["auto", "always", "off"],
                     "label": "Offer 3-4 readings of an open request before starting (auto: only when it looks open)"},
    "HIGGSFIELD_KEY": {"kind": "secret", "default": "",
               "label": "Higgsfield key for images and video (KEY:SECRET from cloud.higgsfield.ai)"},
    "LOKI_TELEGRAM_TOKEN": {"kind": "secret", "default": "",
                            "label": "Telegram bot token: talk to LOKI from your phone (make a bot with @BotFather, paste its token, then pair below)"},
    "LOKI_TELEGRAM_POLL": {"kind": "choice", "default": "auto", "choices": ["auto", "on", "off"],
                           "label": "This machine answers Telegram (auto: only the Windows PC, so your two machines never both reply)"},
    "LOKI_CHANNEL_MODE": {"kind": "choice", "default": "ask", "choices": ["ask", "plan"],
                          "label": "Messages from Telegram run in: ask = answer only; plan = may read and look things up (never changes anything)"},
}


def _query(path: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}


def _env_path(agent: Any) -> Path:
    return Path(agent.env_file_path())


def _write_env(agent: Any):
    import peer_link  # pylint: disable=import-outside-toplevel
    return lambda updates: peer_link.write_env(_env_path(agent), updates)


def connect(agent: Any, provider: str, key: str, account_id: str = "") -> dict:
    """Check and save a key; Cloudflare also needs the account id in its URL."""
    provider = (provider or "").strip().lower()
    if provider == "cloudflare" and account_id.strip():
        aid = "".join(ch for ch in account_id.strip() if ch.isalnum())[:64]
        _write_env(agent)({"CLOUDFLARE_ACCOUNT_ID": aid})
        cfg = agent.MODELS.get("cloudflare")
        if cfg is not None and not os.environ.get("CLOUDFLARE_BASE_URL"):
            cfg.base_url = "https://api.cloudflare.com/client/v4/accounts/%s/ai/v1" % aid
    return agent.connect_provider(provider, key)


def _skills(agent: Any) -> list:
    profiles = agent.agent_profiles
    return profiles.skills_catalog(profiles.skill_roots(agent.REPO_ROOT, agent.DATA_DIR))


def handle_get(state: Any, path: str) -> tuple | None:
    route = urlparse(path).path
    agent = state.agent
    q = _query(path)
    if route == "/providers":
        return 200, {"ok": True, **providers_catalog.present(agent)}
    if route == "/models/doctor":
        import routing  # pylint: disable=import-outside-toplevel
        return 200, routing.doctor(agent)
    if route == "/providers/health":
        import provider_health  # pylint: disable=import-outside-toplevel
        return 200, {"ok": True, "providers": provider_health.registry().snapshot()}
    if route == "/signin/status":
        return 200, signin.flow_status(q.get("state", ""))
    if route == "/handoff/status":
        return 200, signin.handoff_status(q.get("id", ""))
    if route == "/qr":
        text = q.get("text", "")
        if not text or len(text) > 800:
            return 400, {"ok": False, "error": "give text= (up to 800 characters)"}
        return 200, {"ok": True, "svg": qr.svg(text)}
    if route == "/settings/general":
        # a secret is never sent back to the window - only whether one is saved
        values = {k: ("" if spec["kind"] == "secret" else os.environ.get(k, spec["default"])) for k, spec in GENERAL.items()}
        saved = {k: bool(os.environ.get(k, "").strip()) for k, spec in GENERAL.items() if spec["kind"] == "secret"}
        return 200, {"ok": True, "settings": GENERAL, "values": values, "secrets_saved": saved, "model": agent.model_name,
                     "platform": sys.platform}
    if route == "/skills":
        return 200, {"ok": True, "skills": [{k: v for k, v in s.items() if k != "path"} for s in _skills(agent)]}
    if route == "/agents/templates":
        profiles = agent.agent_profiles
        try:
            import ruflo_library  # pylint: disable=import-outside-toplevel
            library = ruflo_library.templates()
        except Exception:  # noqa: BLE001
            library = []
        return 200, {"ok": True, "templates": profiles.TEMPLATES, "library": library,
                     "engines": profiles.ENGINE_LABELS,
                     "tools": profiles.TOOL_GROUPS, "memory": list(profiles.MEMORY_SCOPES),
                     "models": [m for m in agent.MODELS if m not in ("smart", "online")]}
    if route == "/ruflo":
        import ruflo_library  # pylint: disable=import-outside-toplevel
        import reasoning_bank  # pylint: disable=import-outside-toplevel
        return 200, {"ok": True, "summary": ruflo_library.summary(), "plugins": ruflo_library.plugins(),
                     "reasoning_bank": reasoning_bank.summary(),
                     "commands": [{k: v for k, v in c.items() if k != "path"}
                                  for c in ruflo_library.commands() if not c["blocked"]]}
    if route == "/update/everywhere":
        import peers  # pylint: disable=import-outside-toplevel
        import update_all  # pylint: disable=import-outside-toplevel
        import updater  # pylint: disable=import-outside-toplevel
        statuses = peers.status_all() if peers.peers() else []
        return 200, {"ok": True, **update_all.overview(updater, statuses), "health": updater.health()}  # this checkout's record
    return None


def handle_post(state: Any, route: str, data: dict, port: int = 0, job_action=None) -> tuple | None:
    """`port` is the engine's loopback port (for the OAuth callback); `job_action` is the
    bridge's job starter (loki_bridge.job_action), passed in to avoid importing the bridge."""
    agent = state.agent
    pid = str(data.get("id") or data.get("provider") or "").strip().lower()
    write_env = _write_env(agent)
    if route == "/open":
        # Open a provider's page (sign-up, keys, docs) in the system browser. Only pages the
        # catalog names, or OpenRouter's sign-in page, so this cannot open arbitrary URLs.
        url = str(data.get("url") or "")
        known = {u for p in providers_catalog.CATALOG for k in ("signup", "keys", "docs") for u in [p.get(k)] if u}
        # ...and each add-on's homepage and its card buttons (PenEcho's "Open drawing canvas").
        registry = getattr(agent, "CAPABILITIES", None)
        try:
            for cap in (registry.present() if registry is not None else []):
                known |= {a.get("url") for a in cap.get("actions", []) if a.get("url")}
                if cap.get("homepage"):
                    known.add(cap["homepage"])
        except Exception:  # noqa: BLE001 - a broken manifest never widens what can be opened
            pass
        if url not in known and not url.startswith(signin.OPENROUTER_AUTH + "?"):
            return 400, {"ok": False, "error": "LOKI only opens the pages listed for each provider"}
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return 200, {"ok": True}
    if route == "/providers/test":
        return 200, providers_catalog.test(agent, pid)
    if route == "/providers/probe":
        import provider_health  # pylint: disable=import-outside-toplevel
        if pid:
            cfg = agent.MODELS.get(pid)
            if cfg is None or not str(cfg.base_url).startswith("https://"):
                return 400, {"ok": False, "error": "only remote providers are probed"}
            reg = provider_health.registry()
            reg.record_probe(pid, provider_health.probe(pid, cfg.base_url, str(cfg.api_key or ""), cfg.model,
                                                        clock=reg.clock), key=str(cfg.api_key or ""))
            return 200, {"ok": True, "probed": [pid], "health": reg.snapshot().get(pid)}
        return 200, {"ok": True, "probed": provider_health.refresh_once(agent, force=True)}
    if route == "/providers/models":
        return 200, providers_catalog.list_models(agent, pid)
    if route == "/providers/model":
        return 200, providers_catalog.set_model(agent, pid, str(data.get("model", "")), write_env)
    if route == "/providers/enable":
        return 200, providers_catalog.set_enabled(pid, bool(data.get("on")), write_env)
    if route == "/providers/connect":
        result = connect(agent, pid, str(data.get("key", "")), str(data.get("account_id", "")))
        return (200 if result.get("ok") else 400), result
    if route == "/providers/disconnect":
        return 200, providers_catalog.disconnect(agent, pid, write_env)
    if route == "/providers/default":
        if pid not in agent.MODELS:
            return 400, {"ok": False, "error": "unknown provider"}
        agent.model_name = pid
        write_env({"LOKI_MODEL": pid})
        return 200, {"ok": True, "default": pid}
    if route == "/signin/openrouter":
        mode = "code" if data.get("mode") == "code" else "browser"
        flow = signin.openrouter_start(port, mode)
        if mode == "browser":
            threading.Thread(target=webbrowser.open, args=(flow["url"],), daemon=True).start()
        return 200, flow
    if route == "/signin/openrouter/code":
        return 200, signin.openrouter_finish(str(data.get("state", "")), str(data.get("code", "")),
                                             lambda p, k: connect(agent, p, k))
    if route == "/signin/device":
        return 200, signin.device_start(pid, os.environ, lambda p, k: connect(agent, p, k))
    if route == "/handoff":
        import peers  # pylint: disable=import-outside-toplevel
        entry = providers_catalog.get(pid)
        if entry is None or not entry.get("env"):
            return 400, {"ok": False, "error": "this provider takes no key"}
        try:
            started = signin.handoff_start(pid, entry["name"], lambda p, k: connect(agent, p, k),
                                           peers.lan_addresses(), peers.private_client, keys_url=entry.get("keys", ""))
        except OSError as exc:
            return 500, {"ok": False, "error": "could not open the phone page: %s" % exc}
        started["svg"] = qr.svg(started["url"])
        started["svgs"] = [qr.svg(u) for u in started["urls"][:4]]
        started["keys"] = entry.get("keys", "")
        started["hint"] = signin.network_hint()
        return 200, started
    if route == "/settings/general":
        updates = {}
        for key, value in (data.get("values") or {}).items():
            spec = GENERAL.get(key)
            if spec is None:
                return 400, {"ok": False, "error": "%s cannot be changed here" % key}
            value = str(value).strip()
            if spec["kind"] == "bool":
                value = "1" if value.lower() in ("1", "true", "on", "yes") else "0"
            elif spec["kind"] in ("int", "float"):
                try:
                    number = float(value)
                except ValueError:
                    return 400, {"ok": False, "error": "%s must be a number" % spec["label"]}
                number = max(spec.get("min", number), min(spec.get("max", number), number))
                value = str(int(number)) if spec["kind"] == "int" else ("%g" % number)
            elif spec["kind"] == "choice" and value not in spec["choices"]:
                return 400, {"ok": False, "error": "%s must be one of %s" % (spec["label"], ", ".join(spec["choices"]))}
            elif len(value) > 400:
                return 400, {"ok": False, "error": "too long"}
            updates[key] = value
            if spec["kind"] == "secret":
                os.environ[key] = value          # live without a restart
        write_env(updates)
        _apply_live(agent, updates)
        return 200, {"ok": True, "saved": sorted(updates)}
    if route == "/agents/draft":
        try:
            return 200, {"ok": True, "agent": agent.agent_profiles.draft(str(data.get("description", "")), _skills(agent))}
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
    if route == "/agents/launch":
        return launch_agent(state, data, job_action)
    if route == "/update/apply":
        import update_all  # pylint: disable=import-outside-toplevel
        import updater  # pylint: disable=import-outside-toplevel
        return 200, update_all.apply_here(updater, getattr(state, "restart_engine", lambda: None))
    if route == "/update/everywhere":
        import peers  # pylint: disable=import-outside-toplevel
        import update_all  # pylint: disable=import-outside-toplevel
        import updater  # pylint: disable=import-outside-toplevel
        restart = getattr(state, "restart_engine", lambda: None)
        threading.Thread(target=update_all.run, daemon=True, name="loki-update-all",
                         args=(updater, peers.peers(), lambda p, m, path, body: peers.call(p, m, path, body, timeout=30),
                               lambda p: peers.call(p, "GET", "/peer/hello", timeout=5), restart)).start()
        return 200, {"ok": True, "started": True, "progress": update_all.PROGRESS}
    return None


def _apply_live(agent: Any, updates: dict) -> None:
    """Make the settings that are read once at import take effect now."""
    if "LOKI_ALLOW_PAID" in updates:
        agent.ALLOW_PAID = updates["LOKI_ALLOW_PAID"] == "1"
    if "LOKI_DAILY_USD_LIMIT" in updates:
        try:
            agent.DAILY_USD_LIMIT = float(updates["LOKI_DAILY_USD_LIMIT"])
        except ValueError:
            pass
    if "LOKI_SELF_SHIP" in updates:
        agent.SELF_SHIP = updates["LOKI_SELF_SHIP"]
    if "LOKI_PREFER" in updates and hasattr(agent, "PREFER"):
        agent.PREFER = updates["LOKI_PREFER"]
    if "LOKI_MAIN_DRIVER" in updates and hasattr(agent, "MAIN_DRIVER"):
        agent.MAIN_DRIVER = "" if updates["LOKI_MAIN_DRIVER"] == "off" else updates["LOKI_MAIN_DRIVER"]
    if "LOKI_NVIDIA_THINKING" in updates and hasattr(agent, "NVIDIA_THINKING"):
        agent.NVIDIA_THINKING = updates["LOKI_NVIDIA_THINKING"]
    for key in ("LOKI_TELEGRAM_POLL", "LOKI_CHANNEL_MODE"):   # engine/channels.py reads these live
        if key in updates:
            os.environ[key] = updates[key]


def launch_agent(state: Any, data: dict, job_action) -> tuple:
    """Run a saved agent: here, on a named linked machine, or on the best one (auto)."""
    agent = state.agent
    profiles = agent.agent_profiles
    profile = agent.AGENTS.get(str(data.get("id", "")))
    if profile is None:
        return 404, {"ok": False, "error": "No such agent."}
    workspace = str(data.get("workspace") or state.project or "")
    try:
        spec = profiles.job_spec(profile, str(data.get("task", "")), workspace,
                                 int(data.get("timeout_s") or 0), _skills(agent))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    machine = str(data.get("machine") or profile.get("machine") or "here")
    if machine not in ("", "here"):
        import peers  # pylint: disable=import-outside-toplevel
        target = None
        if machine == "auto":
            # The best linked machine: one with an NVIDIA GPU first, else any that answers.
            ranked = sorted(peers.status_all(), key=lambda p: (not p.get("ok"),
                            not ((p.get("hello") or {}).get("machine") or {}).get("gpu")))
            target = next((peers.find(p["name"]) for p in ranked if p.get("ok")), None)
        else:
            target = peers.find(machine)
            if target is None:
                return 400, {"ok": False, "error": "no linked machine called %s" % machine}
        if target is not None:
            try:
                reply = peers.call(target, "POST", "/peer/jobs", {"prompt": profiles.remote_prompt(spec),
                                                                  "title": spec["title"],
                                                                  "timeout_s": spec["timeout_s"]}, timeout=20)
                return 200, {"ok": True, "remote": target["name"], **reply}
            except Exception as exc:  # noqa: BLE001
                if machine != "auto":
                    return 502, {"ok": False, "error": "%s did not take the job: %s" % (machine, exc)}
        # auto with no machine reachable: run it here
    return job_action(state, "/jobs", spec)
