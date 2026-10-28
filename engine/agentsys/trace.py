"""Instruments: a trace of every run, span by span.

Copied from how the big systems watch their agents (docs/AGENT_SYSTEM.md "Instruments"):
  - OpenAI Agents SDK tracing: one trace per run, spans for agent / generation / function / guardrail / handoff.
  - OpenTelemetry GenAI semantic conventions: span names `invoke_agent <agent>`, `chat <model>`,
    `execute_tool <tool>`, attributes `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
    `gen_ai.usage.output_tokens`, `gen_ai.tool.name`, `gen_ai.agent.name`, `gen_ai.conversation.id`, `error.type`.
  - Langfuse / Phoenix: traces are the data the evals and the playbook learn from, so each trace ends with an outcome.

Storage: <data>/traces/YYYY-MM-DD.jsonl, one finished span per line (every LOKI process appends; a line is written in
one call, so processes don't interleave). Kept LOKI_TRACE_DAYS (14) days. LOKI_TRACE=off switches it off.
Nothing secret is stored: strings are clipped and key-shaped text is masked.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from . import env_on, sub

KINDS = ("agent", "llm", "tool", "guardrail", "handoff", "step", "interview", "feedback")
_OP = {"agent": "invoke_agent", "llm": "chat", "tool": "execute_tool", "handoff": "invoke_agent",
       "guardrail": "guardrail", "step": "step", "interview": "interview", "feedback": "feedback"}
_CURRENT: contextvars.ContextVar = contextvars.ContextVar("loki_span", default=None)
_LOCK = threading.Lock()
_SECRET = re.compile(r"(sk|gsk|xai|pk|rk|nvapi|AIza|ghp|github_pat)[-_A-Za-z0-9]{12,}|Bearer\s+[-._A-Za-z0-9]{12,}")
CLIP = 400


def enabled() -> bool:
    return env_on("LOKI_TRACE")


def folder() -> Path:
    return sub("traces")


def _clean(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        v = _SECRET.sub("[key]", value)
        return v if len(v) <= CLIP else v[:CLIP] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth > 2:
        return str(value)[:CLIP]
    if isinstance(value, dict):
        return {str(k)[:60]: _clean(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in list(value)[:30]]
    return str(value)[:CLIP]


class Span:
    __slots__ = ("trace_id", "span_id", "parent_id", "name", "kind", "start", "end", "status", "attrs", "_token")

    def __init__(self, name: str, kind: str, parent: "Span | None", attrs: dict):
        self.trace_id = parent.trace_id if parent else uuid.uuid4().hex[:16]
        self.span_id = uuid.uuid4().hex[:12]
        self.parent_id = parent.span_id if parent else ""
        self.name = name
        self.kind = kind if kind in KINDS else "step"
        self.start = time.time()
        self.end = 0.0
        self.status = "ok"
        self.attrs = {"gen_ai.operation.name": _OP.get(self.kind, "step"), **attrs}
        self._token = None

    def set(self, **attrs: Any) -> "Span":
        self.attrs.update(attrs)
        return self

    def fail(self, error: str, kind: str = "") -> "Span":
        self.status = "error"
        self.attrs["error.type"] = kind or "error"
        self.attrs["error.message"] = str(error)
        return self

    def record(self) -> dict:
        return {"trace_id": self.trace_id, "span_id": self.span_id, "parent_id": self.parent_id, "name": self.name,
                "kind": self.kind, "start": round(self.start, 3), "end": round(self.end, 3),
                "ms": int(max(0.0, (self.end or time.time()) - self.start) * 1000), "status": self.status,
                "attrs": _clean(self.attrs)}


def current() -> Span | None:
    return _CURRENT.get()


def trace_id() -> str:
    s = current()
    return s.trace_id if s else ""


def _write(rec: dict) -> None:
    if not enabled():
        return
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    path = folder() / (time.strftime("%Y-%m-%d", time.localtime(rec["start"] or time.time())) + ".jsonl")
    with _LOCK:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


@contextlib.contextmanager
def span(name: str, kind: str = "step", **attrs: Any) -> Iterator[Span]:
    """with span("execute_tool make_image", "tool", **{"gen_ai.tool.name": "make_image"}) as s: ..."""
    s = Span(name, kind, current(), attrs)
    s._token = _CURRENT.set(s)
    try:
        yield s
    except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised
        if s.status == "ok":
            s.fail(str(exc)[:CLIP], type(exc).__name__)
        raise
    finally:
        s.end = time.time()
        try:
            _CURRENT.reset(s._token)
        except ValueError:      # reset from another context (a thread hop): just drop it
            _CURRENT.set(None)
        _write(s.record())


def event(name: str, kind: str = "step", status: str = "ok", **attrs: Any) -> dict:
    """A span with no duration - a guardrail that tripped, an owner's decision, a feedback note."""
    s = Span(name, kind, current(), attrs)
    s.end = s.start
    s.status = status
    rec = s.record()
    _write(rec)
    return rec


# ----------------------------------------------------------------------------- reading the traces
def _files(days: int) -> list:
    out = []
    now = time.time()
    for i in range(max(1, days)):
        p = folder() / (time.strftime("%Y-%m-%d", time.localtime(now - i * 86400)) + ".jsonl")
        if p.is_file():
            out.append(p)
    return out


def spans(days: int = 1, trace: str = "", limit: int = 5000) -> list:
    out = []
    for p in _files(days):
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    if trace and trace not in line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            continue
    out.sort(key=lambda r: r.get("start", 0))
    return out[-limit:]


def runs(days: int = 1, limit: int = 30) -> list:
    """The latest runs (root spans), newest first, each with its span count, tools and errors."""
    all_ = spans(days)
    by: dict = {}
    for r in all_:
        by.setdefault(r["trace_id"], []).append(r)
    out = []
    for tid, rs in by.items():
        root = next((r for r in rs if not r.get("parent_id")), rs[0])
        if root.get("kind") not in ("agent", "handoff"):     # interviews, feedback notes: not runs of their own
            continue
        out.append({"trace_id": tid, "name": root.get("name"), "start": root.get("start"), "ms": root.get("ms"),
                    "status": root.get("status"), "outcome": (root.get("attrs") or {}).get("loki.outcome", ""),
                    "spans": len(rs), "tools": sum(1 for r in rs if r.get("kind") == "tool"),
                    "llm": sum(1 for r in rs if r.get("kind") == "llm"),
                    "errors": sum(1 for r in rs if r.get("status") == "error"),
                    "tripped": [r["name"] for r in rs if r.get("kind") == "guardrail" and r.get("status") != "ok"][:5]})
    out.sort(key=lambda r: -(r["start"] or 0))
    return out[:limit]


def summary(days: int = 7) -> dict:
    rs = spans(days, limit=200000)
    tools = [r for r in rs if r.get("kind") == "tool"]
    llm = [r for r in rs if r.get("kind") == "llm"]
    roots = [r for r in rs if not r.get("parent_id")]
    worst: dict = {}
    for t in tools:
        n = (t.get("attrs") or {}).get("gen_ai.tool.name") or t["name"]
        w = worst.setdefault(n, [0, 0])
        w[0] += 1
        w[1] += t.get("status") == "error"
    tok_in = sum(int((r.get("attrs") or {}).get("gen_ai.usage.input_tokens") or 0) for r in llm)
    tok_out = sum(int((r.get("attrs") or {}).get("gen_ai.usage.output_tokens") or 0) for r in llm)
    outcomes: dict = {}
    for r in roots:
        o = (r.get("attrs") or {}).get("loki.outcome") or r.get("status")
        outcomes[o] = outcomes.get(o, 0) + 1
    return {"days": days, "runs": len(roots), "outcomes": outcomes, "model_calls": len(llm), "tool_calls": len(tools),
            "tool_errors": sum(1 for t in tools if t.get("status") == "error"),
            "tokens": {"input": tok_in, "output": tok_out},
            "guardrails_tripped": sum(1 for r in rs if r.get("kind") == "guardrail" and r.get("status") != "ok"),
            "failing_tools": sorted(([k, v[0], v[1]] for k, v in worst.items() if v[1]), key=lambda x: -x[2])[:10]}


def prune(days: int | None = None) -> int:
    keep = int(days if days is not None else os.environ.get("LOKI_TRACE_DAYS", "14") or 14)
    cut = time.time() - keep * 86400
    n = 0
    for p in folder().glob("*.jsonl"):
        try:
            if p.stat().st_mtime < cut:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n
