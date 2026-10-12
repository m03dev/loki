"""Jev (TypeSafe System One) - typed decisions for Loki's control loop.

A coding agent is mostly a loop of small judgements: which model, is this tool call
safe, are we stuck. Free-text reasoning is slow and inconsistent; Jev answers a typed
Choice / Score / Noul in a few hundred milliseconds so the loop can threshold a number
instead of parsing prose (https://thejevai.com/docs).

This module is OPTIONAL and must never break a turn. With no key - or on any network
or HTTP error - every call returns None/{} and the caller keeps its own heuristic.
It is not offered to the model; it is hard-wired where a decision is non-negotiable
(the risk gate) and advisory elsewhere (loop detection).

Config (env, read from harness_data/.env like everything else):
  JEV_API_KEY / TYPESAFE_API_KEY / JEV_KEY   the key (required to enable)
  JEV_BASE_URL   override the endpoint
  JEV_MODEL      model id (default typesafe/jev-1.13)
  LOKI_JEV=0     force Jev off even with a key
  LOKI_JEV_RISK  risk-gate threshold, 0..1 (default 0.15)
  LOKI_JEV_CACHE cache identical decisions (default on)
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.request

# A hosted key (jv_live_...) is valid ONLY at the jevtypesafeai gateway; an official
# TypeSafe key (console.typesafe.ai) talks to api.typesafe.ai. The endpoint follows
# the key unless JEV_BASE_URL says otherwise.
_GATEWAY_HOSTED = "https://thejevai.com/v1/systemone"
_GATEWAY_OFFICIAL = "https://api.typesafe.ai/v1/systemone"

DEFAULT_MODEL = "typesafe/jev-1.13"
TIMEOUT_S = float(os.getenv("LOKI_JEV_TIMEOUT", "8"))

STATS = {"calls": 0, "errors": 0, "last_ms": 0.0}
_cache: dict = {}
_lock = threading.Lock()


def api_key() -> str:
    for name in ("JEV_API_KEY", "TYPESAFE_API_KEY", "JEV_KEY"):
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def enabled() -> bool:
    """Jev is on only when a key is present AND it has not been switched off."""
    if os.getenv("LOKI_JEV", "1").strip().lower() in ("0", "false", "off", "no"):
        return False
    return bool(api_key())


def base_url() -> str:
    explicit = str(os.getenv("JEV_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    key = api_key()
    if key.startswith("jv_live_"):
        return _GATEWAY_HOSTED
    if key:
        return _GATEWAY_OFFICIAL
    return _GATEWAY_HOSTED


def model() -> str:
    return str(os.getenv("JEV_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def available() -> bool:
    return enabled()


def _post(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url(), data=data, method="POST")
    request.add_header("Authorization", "Bearer " + api_key())
    request.add_header("Content-Type", "application/json")
    # A real UA: Cloudflare-fronted gateways 403 the default python-urllib agent.
    request.add_header("User-Agent", "Loki/1.0 (+https://github.com/m03dev/loki)")
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def decide(questions: dict, state) -> dict:
    """Evaluate typed questions against ONE state. Returns the answers map.

    Never raises: on any failure this returns {} so the caller keeps its own
    heuristic. Questions are evaluated in parallel by the API, so a risk gate can
    ask 'destructive?' and 'action?' in a single round trip.
    """
    if not enabled() or not questions:
        return {}
    payload = {"model": model(), "state": state, "questions": questions}
    cache_key = ""
    if os.getenv("LOKI_JEV_CACHE", "1").strip().lower() not in ("0", "false", "off"):
        cache_key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        with _lock:
            if cache_key in _cache:
                return _cache[cache_key]
    started = time.monotonic()
    try:
        body = _post(payload)
    except Exception as exc:  # network, 401, 422, 429, 529 - all non-fatal
        with _lock:
            STATS["errors"] += 1
        print("  [jev] decision unavailable: %s" % str(exc)[:120])
        return {}
    with _lock:
        STATS["calls"] += 1
        STATS["last_ms"] = (time.monotonic() - started) * 1000.0
        if cache_key:
            _cache[cache_key] = body.get("answers") or {}
    return body.get("answers") or {}


def noul(question: str, state, criteria: dict | None = None) -> float | None:
    """Probability the answer is YES (0..1), or None when Jev is unavailable."""
    spec = {"type": "noul", "instructions": question}
    if criteria:
        spec["criteria"] = criteria
    answer = (decide({"q": spec}, state).get("q")) or {}
    value = answer.get("noul")
    return float(value) if isinstance(value, (int, float)) else None


def choice(question: str, criteria: dict, state):
    """The winning option key and its confidence, or None when unavailable."""
    answers = decide({"q": {"type": "choice", "instructions": question, "criteria": criteria}}, state)
    answer = answers.get("q") or {}
    picked = answer.get("choice")
    if not isinstance(picked, str):
        return None
    confidence = answer.get("confidence")
    return picked, (float(confidence) if isinstance(confidence, (int, float)) else 0.0)


def risk_threshold() -> float:
    try:
        return float(os.getenv("LOKI_JEV_RISK", "0.15"))
    except ValueError:
        return 0.15


def risk_gate(kind: str, detail: str):
    """Gate one risky action: 'allow' when confidently safe, else 'confirm'.

    Returns None when Jev is off, so the caller keeps its own approval path. The
    human path stays AUTHORITATIVE: 'confirm' means ask, never a silent 'block'.
    """
    if not enabled():
        return None
    state = ("The agent is about to run tool '%s' with these arguments: %s"
             % (kind, str(detail)[:600]))
    answers = decide({
        "destructive": {
            "type": "noul",
            "instructions": ("Is this action destructive, irreversible, or able to affect "
                             "anything outside the project workspace?")},
        "action": {
            "type": "choice",
            "instructions": "Should this action run without asking a human first?",
            "criteria": {"allow": "clearly safe to run now",
                         "confirm": "ask the human before running"}},
    }, state)
    destructive = (answers.get("destructive") or {}).get("noul")
    action = (answers.get("action") or {}).get("choice")
    if not isinstance(destructive, (int, float)):
        return None
    if action == "allow" and destructive < risk_threshold():
        return "allow"
    return "confirm"


def status() -> dict:
    """A JSON-safe snapshot for the doctor, the bridge and the dock."""
    return {
        "enabled": enabled(),
        "key": bool(api_key()),
        "model": model(),
        "endpoint": base_url(),
        "risk_threshold": risk_threshold(),
        "calls": STATS["calls"],
        "errors": STATS["errors"],
        "last_ms": round(STATS["last_ms"], 1),
    }
