"""Stuck detection: notice when the agent loops instead of making progress.

Ported from OpenHands' StuckDetector (OpenHands/software-agent-sdk,
openhands/sdk/conversation/stuck_detector.py, StuckDetectionThresholds), MIT - see
engine/licenses/OpenHands-MIT.txt. Re-written for LOKI's message list: an "action" is one tool
call (name + arguments, ids ignored), an "observation" is the tool message that answers it,
an "error" is an observation that starts with error/refused/failed.

Patterns, each looked for only AFTER the last user message (a nudge from LOKI counts as one,
so a nudged loop has to repeat in full before it is reported again):

  1. repeating action-observation: the same call got the same result `action_observation`
     times in a row (default 4)
  2. repeating action-error: the same call failed the same way more than `action_error`
     times (default 3); at exactly the threshold `nudge()` returns a precise hint, once
  3. monologue: `monologue` assistant messages in a row with no tool call and no user (3)
  4. alternating: A, B, A, B, A, B - two calls taking turns with the same results (6)

detect() returns the pattern's name (or ""); LOKI's loop nudges the model on the first hit and
stops the request on a repeat (engine/loki.py agent_turn).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

SCAN = 24       # recent messages to look at (OpenHands: 20 events, plus room for tool fan-out)


@dataclass
class Thresholds:
    action_observation: int = 4
    action_error: int = 3
    monologue: int = 3
    alternating_pattern: int = 6


_ERROR_HEADS = ("error", "refused", "not allowed", "failed", "traceback", "no such", "unknown tool")


def _is_error(text: str) -> bool:
    return str(text or "").strip()[:120].lower().startswith(_ERROR_HEADS)


def _norm_args(raw) -> str:
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
        return json.dumps(obj, sort_keys=True)[:2000]
    except (TypeError, ValueError):
        return str(raw)[:2000]


def _since_last_user(messages: list) -> list:
    window = [m for m in messages[-SCAN:] if isinstance(m, dict)]
    for i in range(len(window) - 1, -1, -1):
        if window[i].get("role") == "user":
            return window[i + 1:]
    return window


def pairs(messages: list) -> list:
    """[(action, observation, is_error)] in order, after the last user message."""
    window = _since_last_user(messages)
    pending: dict = {}
    order: list = []
    out: list = []
    for m in window:
        if m.get("role") == "assistant":
            for call in m.get("tool_calls") or []:
                if isinstance(call, dict):
                    fn = call.get("function") or {}
                    action = "%s|%s" % (fn.get("name", ""), _norm_args(fn.get("arguments", "{}")))
                    pending[call.get("id", "")] = action
                    order.append(call.get("id", ""))
        elif m.get("role") == "tool":
            action = pending.pop(m.get("tool_call_id", ""), None)
            if action is not None:
                text = str(m.get("content") or "")
                out.append((action, text[:4000], _is_error(text)))
    return out


def _repeat_ao(p: list, t: Thresholds) -> bool:
    n = t.action_observation
    if len(p) < n:
        return False
    last = p[-n:]
    return all(a == last[0][0] and o == last[0][1] for a, o, _ in last)


def error_streak(p: list) -> int:
    if not p or not p[-1][2]:
        return 0
    ref_action, ref_obs = p[-1][0], p[-1][1]
    streak = 0
    for a, o, err in reversed(p):
        if a != ref_action or not err or o != ref_obs:
            break
        streak += 1
    return streak


def _monologue(messages: list, t: Thresholds) -> bool:
    count = 0
    for m in reversed([m for m in messages[-SCAN:] if isinstance(m, dict)]):
        role = m.get("role")
        if role == "assistant" and not m.get("tool_calls"):
            count += 1
        else:
            break
    return count >= t.monologue


def _alternating(p: list, t: Thresholds) -> bool:
    n = t.alternating_pattern
    if len(p) < n:
        return False
    last = p[-n:]
    if last[-1][0] == last[-2][0]:
        return False         # that is pattern 1, not two calls taking turns
    return all(last[i][0] == last[i + 2][0] and last[i][1] == last[i + 2][1] for i in range(n - 2))


def detect(messages: list, t: Thresholds | None = None) -> str:
    t = t or Thresholds()
    p = pairs(messages)
    if _repeat_ao(p, t):
        return "repeating_action_observation"
    if error_streak(p) > t.action_error:
        return "repeating_action_error"
    if _monologue(messages, t):
        return "monologue"
    if _alternating(p, t):
        return "alternating"
    return ""


def nudge(messages: list, t: Thresholds | None = None) -> str:
    """The hint for an action-error streak that just reached the threshold ("" otherwise)."""
    t = t or Thresholds()
    p = pairs(messages)
    if error_streak(p) != t.action_error:
        return ""
    action, obs, _ = p[-1]
    name = action.split("|", 1)[0]
    return ("You've called `%s` with the same arguments %d times in a row and got the same error each time: %s. "
            "Repeating the exact same call again will not work - read the error, then correct the arguments "
            "or try a different approach." % (name, t.action_error, obs.strip().splitlines()[0][:240] if obs.strip() else ""))


MESSAGES = {
    "repeating_action_observation": "You are repeating the same tool call and getting the same result. That is a loop.",
    "repeating_action_error": "You keep making the same failing call.",
    "monologue": "You keep writing messages without doing anything.",
    "alternating": "You are alternating between the same two calls with the same results. That is a loop.",
}


def advice(pattern: str) -> str:
    return (MESSAGES.get(pattern, "You appear to be stuck.") + " Stop and reassess: say in one line what is "
            "blocking you, then take a materially different step (another tool, other arguments, a smaller "
            "piece of the task), or reply 'BLOCKED: <reason>' if you cannot continue.")
