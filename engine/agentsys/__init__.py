"""LOKI's agent system - one runtime around every harness (owner 2026-10-28: "agent system design needs to be the
main focus here. orchestration context memory tools guardrails instruments power chassis").

LOKI can run a request on several harnesses (OpenCode, DeepSeek Harness, Codex / Claude Code CLIs, LOKI's own loop,
the local shell agent). Before this package each of them had its own idea of context, budgets and checks. Now every
request goes through the same chassis, whichever harness does the work:

    interview     before work starts the owner gets 1-4 questions with options ("is this what you want?")
    orchestrator  the delegation loop: a task ledger (facts, plan, acceptance), a progress ledger checked after every
                  step (done? progressing? looping?), specialists for each step, re-plan on a stall
    context       one assembler for the harness preamble: the brief, the ledger, playbook bullets, memory - in a
                  stable order so prompt caches keep working
    playbook      learned strategies per kind of work (ACE: bullets with helpful / harmful counts, delta updates,
                  pruning) - grown from results, the owner's send-backs and his approvals
    toolbox       every tool with what it does to the world (read-only, destructive, needs the GPU ...) and a search,
                  so a model is handed the right few tools instead of 120
    guardrails    input / tool / output / budget checks in one pipeline; a tripwire stops the run with the reason
    instruments   a trace of every run (spans for the request, each model call, tool, guardrail and hand-off) -
                  OpenTelemetry GenAI names - plus the outcome, so evals and the playbook learn from real runs
    sendback      any result (a chat reply, a job, a picture, a file) can be sent back with a note, or parked
                  ("not now"); the note becomes a revision request and teaches the playbook
    upstream      where every piece of open-source code in LOKI came from, at which commit, and a scheduled check of
                  what changed upstream since (owner: "always check where he got what hes using")

docs/AGENT_SYSTEM.md is the design; each module's docstring says what it copies from whom.
"""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """The same data folder every LOKI process shares (the app sets LOKI_DATA; LOKI_DATA_DIR is the older name)."""
    raw = os.environ.get("LOKI_DATA") or os.environ.get("LOKI_DATA_DIR") or ""
    d = Path(raw) if raw.strip() else Path(__file__).resolve().parents[2] / "harness_data"
    return d


def sub(name: str) -> Path:
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def env_on(name: str, default: str = "on") -> bool:
    return str(os.environ.get(name, default)).strip().lower() not in ("0", "off", "false", "no", "")
