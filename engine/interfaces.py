"""The contracts every Loki capability is written against (blueprint: the backbone).

Five small protocols. Loki's core talks to these, never to a concrete library, so a
provider can be swapped (Ollama -> OpenRouter, file memory -> OpenViking, Laya -> Jev)
without touching the agent loop. `typing.Protocol` keeps them duck-typed: an adapter
only has to have the methods, not inherit from anything.

    ModelProvider     - an OpenAI-compatible chat endpoint
    MemoryProvider    - lasting facts and documents, addressable by viking:// URIs
    DecisionProvider  - typed fast decisions (risk gate, loop check); recommends only
    Tool              - one callable action with a JSON schema and declared permissions
    Skill             - instructions (SKILL.md) the agent can load; never executes code

`check(obj, protocol)` reports which methods an object is missing, for the registry and
tests. Adapters for what Loki already has live at the bottom of this file and wrap the
existing modules - they do not re-implement them.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    def endpoint(self) -> str: ...
    def model(self) -> str: ...
    def healthy(self, timeout: float = 3.0) -> bool: ...


@runtime_checkable
class MemoryProvider(Protocol):
    name: str

    def read(self, uri: str) -> str: ...
    def write(self, uri: str, text: str) -> None: ...
    def list(self, uri: str) -> list[str]: ...


@runtime_checkable
class DecisionProvider(Protocol):
    name: str

    def enabled(self) -> bool: ...
    def risk_gate(self, kind: str, detail: str) -> str | None: ...   # "allow" or None, never "force"
    def loop_check(self, state: str) -> float | None: ...            # 0..1 "spinning", None = no opinion


@runtime_checkable
class Tool(Protocol):
    name: str
    permissions: tuple[str, ...]

    def schema(self) -> dict: ...
    def __call__(self, **kwargs: Any) -> Any: ...


@runtime_checkable
class Skill(Protocol):
    name: str
    description: str

    def instructions(self) -> str: ...


def check(obj: Any, protocol: type) -> list[str]:
    """Names of the protocol members `obj` lacks (empty list = conforms)."""
    wanted = [n for n in getattr(protocol, "__annotations__", {})]
    wanted += [n for n, v in vars(protocol).items()
               if inspect.isfunction(v) and (not n.startswith("_") or n == "__call__")]
    return sorted({n for n in wanted if not hasattr(obj, n)})


# --------------------------------------------------------------------- adapters
@dataclass
class OpenAICompatModel:
    """Wraps one entry of loki.MODELS."""
    name: str
    base_url: str
    model_id: str
    probe: Any = None   # callable(base_url, timeout) -> bool; injected (loki.endpoint_reachable)

    def endpoint(self) -> str:
        return self.base_url

    def model(self) -> str:
        return self.model_id

    def healthy(self, timeout: float = 3.0) -> bool:
        if self.probe is None:
            return False
        try:
            return bool(self.probe(self.base_url, timeout))
        except Exception:
            return False


@dataclass
class ModuleDecision:
    """Wraps jev.py / laya.py through the functions they really expose: enabled(),
    risk_gate(kind, detail) and noul(question, state). Nothing is invented."""
    name: str
    module: Any

    def enabled(self) -> bool:
        try:
            return bool(self.module.enabled())
        except Exception:
            return False

    def risk_gate(self, kind: str, detail: str) -> str | None:
        try:
            verdict = self.module.risk_gate(kind, detail)
        except Exception:
            return None
        return "allow" if verdict == "allow" else None

    LOOP_QUESTION = "Is the agent repeating the same approach without making real progress?"

    def loop_check(self, state: str) -> float | None:
        # jev.noul / laya.noul(question, state) -> float in [0, 1] or None (the real API)
        try:
            value = self.module.noul(self.LOOP_QUESTION, state)
        except Exception:
            return None
        return float(value) if isinstance(value, (int, float)) else None


@dataclass
class FileSkill:
    """A SKILL.md on disk. Reading it is the only thing a skill can do."""
    path: Path
    name: str = ""
    description: str = ""
    meta: dict = field(default_factory=dict)

    def instructions(self) -> str:
        return Path(self.path).read_text(encoding="utf-8", errors="replace")
