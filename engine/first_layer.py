"""Loki's first layer: every request is triaged before the agent starts.

Laya (laya.py, local and offline once set up) answers four typed questions about the
request in ONE forward pass:

  kind        what sort of work it is (question, chat, code, research, browse, build, ops)
  route       how to handle it: answer directly / one quick step / a plan / a team of agents
  difficulty  0..3 (trivial, easy, medium, hard)
  risk        P(carrying it out deletes data, spends money, signs in, or sends/posts anything)

When Laya is not set up, still loading its model, or fails, built-in rules answer instead and
the triage says so (source "rules"), so the UI can show it. Triage is ADVICE: it shapes how the
agent starts (a question is answered in one turn, a large job is nudged towards background
agents) and is logged with the request's outcome so its accuracy can be measured
(experience.triage_stats). It can never grant a permission: policy.py and the approval path
decide that.
"""
from __future__ import annotations

import os
import re
import time

import laya

KINDS = {
    "question": "a question to answer or something to explain",
    "chat": "a greeting, thanks or small talk",
    "code": "write, change or fix code or files in a project",
    "research": "find or compare information from the web or documents",
    "browse": "operate a website: fill forms, click through pages, test a site",
    "build": "build a whole app, website, game or tool from scratch",
    "ops": "run, install, configure or repair something on the computer",
}
ROUTES = {
    "answer": "answer directly in one reply, no tools needed",
    "one_step": "one quick lookup, command or edit",
    "plan": "several steps that need a plan and checking",
    "team": "a large job worth splitting across several agents working in the background",
}
DIFFICULTY = ["trivial", "easy", "medium", "hard"]

QUESTIONS = {
    "kind": {"type": "choice", "instructions": "What kind of request is this?", "criteria": KINDS},
    "route": {"type": "choice", "instructions": "How should an AI assistant handle this request?",
              "criteria": ROUTES},
    "difficulty": {"type": "score", "instructions": "How hard is this request to do well?",
                   "criteria": DIFFICULTY},
    "risk": {"type": "noul",
             "instructions": ("Could carrying out this request delete data, spend money, sign in to "
                              "an account, or send or post anything on the user's behalf?")},
    "missing": {"type": "noul",
                "instructions": "Is information missing that the assistant must ask the user for before starting?"},
}

# What each kind of work needs from LOKI (checked against what is installed by the caller).
CAPABILITIES = {
    "question": ["model.chat"], "chat": ["model.chat"],
    "code": ["repository.read", "code.edit", "tests.run"],
    "research": ["web.search", "web.read"],
    "browse": ["browser.use", "approval.human"],
    "build": ["repository.read", "code.edit", "tests.run", "agents.team"],
    "ops": ["command.run", "approval.human"],
}

# How long the first layer may wait for Laya before the rules answer. Laya answers in well
# under a second once warm; a cold model is loading in the background meanwhile.
TIMEOUT_S = float(os.getenv("LOKI_TRIAGE_TIMEOUT", "8") or 8)

_GREETING = re.compile(r"^(hi|hello|hey|yo|thanks|thank you|good (morning|evening|night))\b", re.I)
_QUESTION = re.compile(r"^(what|who|how|why|when|where|which|can you|could you|would you|do you|are you|"
                       r"is it|does it|tell me|explain|describe|show me|list what)\b", re.I)
_BUILD = re.compile(r"\b(build|create|make|scaffold|set up|develop)\b.*\b(app|website|site|game|tool|"
                    r"landing page|api|service|dashboard|bot|extension)\b", re.I)
_BROWSE = re.compile(r"\b(sign up|log ?in|fill (in|out)|click|book|order|buy|test (the|my) (site|website|page)|"
                     r"in (a|the) browser)\b", re.I)
_RESEARCH = re.compile(r"\b(research|find|look up|search|compare|latest|news|price|sources?)\b", re.I)
_OPS = re.compile(r"\b(install|run|start|restart|configure|deploy|update|upgrade|fix my|set up)\b", re.I)
_CODE = re.compile(r"\b(code|function|bug|refactor|test|script|file|class|module|repo|commit|"
                   r"\.py|\.js|\.ts|\.gd|\.go|\.rs)\b", re.I)
# A request to change LOKI itself (its code, UI, engine, tests). These always go to
# improve_loki: its own worktree, every test suite, shipped only when green.
_SELF = re.compile(r"\b(improve_loki|(change|improve|fix|update|edit|upgrade|refactor|rework)\s+"
                   r"(your\s+own|your|loki'?s?(\s+own)?)\s+(code|ui|app|engine|settings|interface|"
                   r"tests?|source|codebase)|your\s+own\s+code|loki'?s\s+(own\s+)?(code|codebase|"
                   r"source|engine|ui))\b", re.I)
_RISKY = re.compile(r"\b(delete|remove|wipe|drop|pay|purchase|buy|order|send|email|post|publish|tweet|"
                    r"sign ?in|log ?in|password|transfer)\b", re.I)


def rules(message: str) -> dict:
    """The built-in answer when Laya is unavailable. Simple, predictable, always available."""
    text = (message or "").strip()
    words = len(text.split())
    if not text:
        kind = "chat"
    elif _GREETING.match(text) and words <= 6:
        kind = "chat"
    elif _BUILD.search(text):
        kind = "build"
    elif _BROWSE.search(text):
        kind = "browse"
    elif _QUESTION.match(text) or text.endswith("?"):
        kind = "question"
    elif _CODE.search(text):
        kind = "code"
    elif _RESEARCH.search(text):
        kind = "research"
    elif _OPS.search(text):
        kind = "ops"
    else:
        kind = "code" if words > 6 else "question"
    if kind in ("chat", "question") and len(text) <= 300:
        route, difficulty = "answer", 0 if kind == "chat" else 1
    elif kind == "build" or words > 80:
        route, difficulty = "team", 3
    elif kind in ("research", "browse") or words > 25:
        route, difficulty = "plan", 2
    else:
        route, difficulty = "one_step", 1
    return {"kind": kind, "route": route, "difficulty": difficulty,
            "risk": 0.6 if _RISKY.search(text) else 0.05, "confidence": None}


def _from_laya(answers: dict) -> dict | None:
    kind = (answers.get("kind") or {}).get("choice")
    route = (answers.get("route") or {}).get("choice")
    score = (answers.get("difficulty") or {}).get("score")
    risk = (answers.get("risk") or {}).get("noul")
    if kind not in KINDS or route not in ROUTES:
        return None
    probs = (answers.get("route") or {}).get("probabilities") or {}
    confidence = probs.get(route)
    missing = (answers.get("missing") or {}).get("noul")
    out = {"kind": kind, "route": route,
           "difficulty": int(round(float(score))) if isinstance(score, (int, float)) else 1,
           "risk": round(float(risk), 3) if isinstance(risk, (int, float)) else None,
           "confidence": round(float(confidence), 3) if isinstance(confidence, (int, float)) else None}
    if isinstance(missing, (int, float)):
        out["missing_info"] = missing >= 0.6
    return out


def triage(message: str, mode: str = "build", wait: bool = True) -> dict:
    """Triage one request. Never raises; always returns a full answer.

    wait=False never blocks on a model that is still loading (the rules answer and the model
    keeps warming in the background for the next request).
    """
    started = time.monotonic()
    result, source, note = None, "rules", ""
    which = laya.backend()
    if not which:
        note = "Laya is not set up (run tools/setup_laya.py); using built-in rules"
    else:
        if which == "node" and not laya.ready():
            laya.warm()
            if wait:
                laya.SERVER.wait_ready(min(TIMEOUT_S, laya.load_timeout_s()))
        if laya.ready():
            state = {"request": (message or "")[:4000], "mode": mode}
            answers = laya.decide(QUESTIONS, state, timeout=TIMEOUT_S)
            result = _from_laya(answers) if answers else None
            if result:
                source = "laya"
            else:
                note = "Laya gave no usable answer; using built-in rules"
        else:
            note = ("Laya is loading its model; using built-in rules" if laya.SERVER.state == "loading"
                    else "Laya is unavailable (%s); using built-in rules" % (laya.SERVER.error or "not ready"))
    if result is None and which != "http":
        # Second opinion: Jev (hosted, key-gated) answers the same typed questions.
        try:
            import jev  # pylint: disable=import-outside-toplevel
            if jev.enabled():
                answers = jev.decide(QUESTIONS, {"request": (message or "")[:4000], "mode": mode})
                result = _from_laya(answers) if answers else None
                if result:
                    source = "jev"
                    note = (note + "; Jev answered instead").strip("; ")
        except Exception:  # noqa: BLE001
            pass
    if result is None:
        result = rules(message)
    result.update({"source": source, "ms": round((time.monotonic() - started) * 1000.0, 1)})
    result["self_change"] = is_self_change(message)
    _complete(result, message)
    if note:
        result["note"] = note
    if mode in ("ask", "plan") and result["route"] == "team":
        result["route"] = "plan"  # Ask and Plan never start agents
    return result


def is_self_change(message: str) -> bool:
    """True when the request asks LOKI to change its own code (see _SELF)."""
    return bool(_SELF.search(message or ""))


def _complete(t: dict, message: str) -> None:
    """Fill in the rest of the structured decision (docs/VISION.md section 5)."""
    t["intent"] = t.get("kind", "")
    t["capabilities"] = list(CAPABILITIES.get(t.get("kind", ""), ["model.chat"]))
    if t.get("route") == "team" and "agents.team" not in t["capabilities"]:
        t["capabilities"].append("agents.team")
    risk = t.get("risk")
    t["approval"] = "likely" if isinstance(risk, (int, float)) and risk >= 0.5 else "only for risky tools"
    if "missing_info" not in t:
        t["missing_info"] = len((message or "").split()) < 3 and t.get("kind") not in ("chat", "question")
    t["rationale"] = "%s says: %s request, %s, difficulty %s of 3" % (
        {"laya": "Laya", "jev": "Jev"}.get(t.get("source"), "The built-in rules"),
        t.get("kind"), str(t.get("route", "")).replace("_", " "), t.get("difficulty"))
    t["fallback"] = "built-in rules" if t.get("source") != "rules" else "none needed"


def describe(t: dict) -> str:
    """One line for the conversation trace."""
    level = DIFFICULTY[max(0, min(3, int(t.get("difficulty") or 0)))]
    who = {"laya": "Laya", "jev": "Jev"}.get(t.get("source"), "Rules")
    text = "%s: %s, %s, %s" % (who, t.get("kind"), t.get("route", "").replace("_", " "), level)
    if isinstance(t.get("risk"), (int, float)) and t["risk"] >= 0.5:
        text += ", may need your approval"
    if t.get("note"):
        text += " (%s)" % t["note"]
    return text


def guidance(t: dict) -> str:
    """What the agent is told about the triage, or "" when nothing changes."""
    route = t.get("route")
    if t.get("self_change"):
        return ("First-layer triage: this asks to change LOKI's own code. Call improve_loki with "
                "the whole request; do not edit files in this workspace yourself.")
    if t.get("missing_info") and route != "answer":
        return ("First-layer triage: important information seems to be missing. Ask the user the "
                "one or two questions you need before you start.")
    if route == "answer":
        return ("First-layer triage: this looks like a question or conversation. Answer it "
                "directly; only call a tool if the answer genuinely needs one.")
    if route == "team":
        return ("First-layer triage: this is a large job for a team. Call start_team with the "
                "whole goal: LOKI builds the team (roles, specs, stages), the agents talk on a "
                "shared board, and the result is checked. Tell the user the team is on it.")
    return ""


def actual_route(tool_calls: int, delegated: bool) -> str:
    """What the request turned out to need, for measuring the triage afterwards."""
    if delegated:
        return "team"
    if tool_calls == 0:
        return "answer"
    if tool_calls <= 2:
        return "one_step"
    return "plan"
