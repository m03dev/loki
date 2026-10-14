"""Loki's decision layer: one place that asks a decision provider, with routing and fallback.

The project vision calls for Laya as the preferred LOCAL-FIRST decision provider and Jev as an
additional or fallback provider, with independent evaluation where it is worth the cost, and
with latency, errors and disagreements recorded. This module is that policy. It owns no model
itself and never grants permissions: a decision can only SKIP a prompt or NUDGE the loop, never
force an action (see jev.risk_gate and laya.risk_gate).

Routing (LOKI_DECISION_ORDER, default "laya,jev"):
  - risk_gate: ask each enabled provider; only 'allow' from all of them allows. When they
    disagree the SAFER answer wins and the disagreement is recorded.
  - loop_nudge: the first enabled provider that reports spinning above its threshold wins.

Both providers are optional and non-fatal; with none enabled every function returns its
"no decision" value and the caller keeps its own heuristic.
"""
from __future__ import annotations

import os

import jev
import laya

PROVIDERS = {"laya": laya, "jev": jev}

STATS = {"risk_calls": 0, "disagreements": 0, "loop_checks": 0, "laya_allows": 0, "jev_allows": 0}


def order():
    """Configured providers, in preference order, each as (name, module)."""
    names = [n.strip().lower() for n in
             str(os.getenv("LOKI_DECISION_ORDER", "laya,jev")).split(",") if n.strip()]
    return [(n, PROVIDERS[n]) for n in names if n in PROVIDERS]


def enabled_providers():
    return [(n, m) for n, m in order() if m.enabled()]


def risk_gate(kind: str, detail: str):
    """Return 'allow' only when every enabled provider confidently judges the action safe.

    Returns None when no provider could decide, or when they disagree - so the caller keeps
    its own human/approval path. Never returns 'block': the human path stays authoritative.
    """
    verdicts = {}
    for name, module in order():
        if not module.enabled():
            continue
        try:
            verdict = module.risk_gate(kind, detail)
        except Exception:
            verdict = None
        if verdict is not None:
            verdicts[name] = verdict
    if not verdicts:
        return None
    STATS["risk_calls"] += 1
    if len(set(verdicts.values())) > 1:
        STATS["disagreements"] += 1
        print("  [decisions] providers disagree on %s: %s - asking" % (kind, verdicts))
        return None
    if all(v == "allow" for v in verdicts.values()):
        for name in verdicts:
            STATS[name + "_allows"] = STATS.get(name + "_allows", 0) + 1
        print("  [decisions] %s judged safe to run without asking by %s"
              % (kind, ", ".join(sorted(verdicts))))
        return "allow"
    return None


def loop_nudge(state: str, threshold: float = 0.7) -> str:
    """First enabled provider that reports spinning above `threshold` wins; "" when none does."""
    STATS["loop_checks"] += 1
    question = "Is the agent repeating the same approach without making real progress?"
    for _name, module in order():
        if not module.enabled():
            continue
        try:
            value = module.noul(question, state)
        except Exception:
            value = None
        if isinstance(value, (int, float)) and value >= threshold:
            return "%.2f" % value
    return ""


def status() -> dict:
    """A JSON-safe snapshot for the doctor, the bridge and the dock."""
    return {
        "order": [n for n, _ in order()],
        "enabled": [n for n, _ in enabled_providers()],
        "laya": laya.status(),
        "jev": jev.status(),
        "stats": dict(STATS),
    }
