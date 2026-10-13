"""Loki the conductor - one agent in charge, specialists on call.

Everything starts with Loki. It plans, keeps the conversation and owns the tools; when a
step needs a specialist it calls the `conductor` tool with a ROLE, and this module routes
the call to whichever enabled capability can do it:

    research   Perplexity Sonar - a cited web answer          (capability: perplexity)
    read_web   one page as markdown: crawl4ai, scrapling or a self-hosted Firecrawl,
               first one enabled wins (LOKI_READ_ORDER)          (crawl4ai/scrapling/firecrawl)
    browse     a real browser does a task (browser-use)        (browser-use) - always asks
    remember   store a lasting fact in Hindsight               (hindsight)
    recall     ask Hindsight what it knows                     (hindsight)

Specialists that run for minutes (Claude Code, Codex, Hermes Agent) are background jobs the
USER starts (workers.py); the model cannot spawn them. Headroom (context compression) and
SkillSpector (deep skill scanning) are not roles: they sit in the loop - Headroom shrinks the
messages before each model call, SkillSpector adds findings to the skill scan.

Every role is checked by the policy engine first (capability on, permission granted,
network host allowed). Heavy libraries run in `runners/` child processes with a timeout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import policy

RUNNERS = Path(__file__).resolve().parent / "runners"
READ_BACKENDS = ("crawl4ai", "scrapling", "firecrawl")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
MAX_TEXT = 20_000

ROLES: dict[str, dict] = {
    "research": {"capabilities": ("vane", "perplexity"), "permission": "",
                 "permissions": {"vane": "network:loopback", "perplexity": "network:api.perplexity.ai"},
                 "summary": "a cited answer from the live web (Vane, private and local; or Perplexity)",
                 "ask": False},
    "read_web": {"capabilities": READ_BACKENDS, "permission": "",
                 "summary": "read one web page as markdown (url=...)", "ask": False},
    "browse": {"capabilities": ("browser-use",), "permission": "network",
               "summary": "let a real browser do a task on websites (asks you first)", "ask": True},
    "remember": {"capabilities": ("hindsight",), "permission": "",
                 "summary": "store a lasting fact in long-term memory (Hindsight)", "ask": False},
    "recall": {"capabilities": ("hindsight",), "permission": "",
               "summary": "ask long-term memory what it knows (Hindsight)", "ask": False},
}


class Conductor:
    def __init__(self, engine: policy.PolicyEngine, registry: Any, env: dict | None = None,
                 runner: Callable[..., Any] = subprocess.run, opener: Callable[..., Any] = urllib.request.urlopen,
                 python: str | list | None = None) -> None:
        self.policy = engine
        self.registry = registry
        self.env = env if env is not None else os.environ
        self.runner = runner
        self.opener = opener
        self.python = python_command() if python is None else ([python, "-I"] if isinstance(python, str) else list(python))

    # ------------------------------------------------------------- roster
    def _ready(self, capability: str, permission: str = "") -> policy.Verdict:
        return self.policy.capability(capability, permission)

    def pick(self, role: str) -> tuple[str, str]:
        """(capability to use, "") or ("", why none can)."""
        spec = ROLES.get(role)
        if spec is None:
            return "", "unknown role %r (roles: %s)" % (role, ", ".join(ROLES))
        candidates = list(spec["capabilities"])
        if role == "read_web":
            order = [c.strip() for c in str(self.env.get("LOKI_READ_ORDER", "")).split(",") if c.strip()]
            candidates = [c for c in order if c in READ_BACKENDS] + [c for c in READ_BACKENDS if c not in order]
        if role == "research":
            order = [c.strip() for c in str(self.env.get("LOKI_RESEARCH_ORDER", "")).split(",") if c.strip()]
            candidates = [c for c in order if c in spec["capabilities"]] + \
                [c for c in spec["capabilities"] if c not in order]
        reasons = []
        for capability in candidates:
            verdict = self._ready(capability, spec.get("permissions", {}).get(capability, spec["permission"]))
            if verdict.allowed:
                return capability, ""
            reasons.append(verdict.reason)
        return "", "; ".join(reasons)

    def roster(self) -> list[dict]:
        rows = []
        for role, spec in ROLES.items():
            via, why = self.pick(role)
            rows.append({"role": role, "summary": spec["summary"], "ready": bool(via), "via": via, "why": why})
        return rows

    def prompt_section(self) -> str:
        ready = [r for r in self.roster() if r["ready"]]
        if not ready:
            return ""
        lines = ["# Specialists you can call",
                 "You are the conductor. For these steps call the `conductor` tool with a role "
                 "instead of guessing:"]
        lines += ["- %s: %s (via %s)" % (r["role"], r["summary"], r["via"]) for r in ready]
        return "\n".join(lines)

    def needs_approval(self, role: str) -> bool:
        return bool(ROLES.get(role, {}).get("ask"))

    # ------------------------------------------------------------- dispatch
    def run(self, role: str, task: str = "", url: str = "") -> str:
        capability, why = self.pick(role)
        if not capability:
            return "error: no specialist for %r is ready - %s" % (role, why)
        try:
            if role == "research":
                return self.vane(task) if capability == "vane" else self.research(task)
            if role == "read_web":
                return self.read_web(capability, url or task)
            if role == "browse":
                return self.browse(task)
            if role in ("remember", "recall"):
                return self.hindsight("retain" if role == "remember" else "recall", task)
        except Exception as exc:  # noqa: BLE001 - a specialist failing must not end the turn
            return "error: %s failed: %s: %s" % (capability, type(exc).__name__, exc)
        return "error: role %r is not wired" % role

    # ------------------------------------------------------------- specialists
    def _post_json(self, url: str, body: dict, headers: dict, timeout: float) -> dict:
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", **headers})
        try:
            with self.opener(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else ""
            raise RuntimeError("HTTP %s %s" % (exc.code, detail)) from None

    def research(self, question: str) -> str:
        if not question.strip():
            return "error: research needs a question"
        key = str(self.env.get("PERPLEXITY_API_KEY", "")).strip()
        model = str(self.env.get("LOKI_PERPLEXITY_MODEL", "sonar")) or "sonar"
        data = self._post_json(PERPLEXITY_URL, {"model": model, "messages": [
            {"role": "system", "content": "Answer concisely with sources."},
            {"role": "user", "content": question}]}, {"Authorization": "Bearer " + key}, timeout=90)
        answer = ""
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            answer = json.dumps(data)[:2000]
        sources = [s.get("url", "") for s in data.get("search_results", []) if isinstance(s, dict)] \
            or [c for c in data.get("citations", []) if isinstance(c, str)]
        if sources:
            answer += "\n\nSources:\n" + "\n".join("[%d] %s" % (i + 1, u) for i, u in enumerate(sources[:12]))
        return answer

    def _get_json(self, url: str, timeout: float) -> Any:
        with self.opener(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def vane(self, question: str) -> str:
        """Vane (ItzCrazyKns/Vane, MIT): a self-hosted answering engine over SearxNG that can
        run on local Ollama models - private research with no API key.
        GET /api/providers picks the models; POST /api/search returns {message, sources}."""
        if not question.strip():
            return "error: research needs a question"
        base = str(self.env.get("VANE_URL", "http://127.0.0.1:3000")).rstrip("/")
        providers = self._get_json(base + "/api/providers", timeout=10)
        providers = providers.get("providers", providers) if isinstance(providers, dict) else providers
        chat, embed = pick_vane_models(providers if isinstance(providers, list) else [],
                                       str(self.env.get("LOKI_VANE_CHAT", "")))
        if not chat or not embed:
            return "error: Vane has no chat or embedding model set up - open it at %s and add one" % base
        data = self._post_json(base + "/api/search", {
            "chatModel": chat, "embeddingModel": embed, "sources": ["web"],
            "optimizationMode": str(self.env.get("LOKI_VANE_MODE", "speed")),
            "query": question, "history": [], "stream": False}, {}, timeout=180)
        answer = str(data.get("message", "")).strip() or "(Vane returned no answer)"
        sources = [((s.get("metadata") or {}).get("url", ""), (s.get("metadata") or {}).get("title", ""))
                   for s in data.get("sources", []) if isinstance(s, dict)]
        sources = [s for s in sources if s[0]]
        if sources:
            answer += "\n\nSources:\n" + "\n".join("[%d] %s %s" % (i + 1, t, u) for i, (u, t) in enumerate(sources[:12]))
        return answer

    def _runner(self, name: str, job: dict, timeout: int) -> dict:
        script = RUNNERS / (name + ".py")
        try:
            proc = self.runner([*self.python, str(script)], input=json.dumps(job), capture_output=True,
                               text=True, timeout=timeout, shell=False)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "%s timed out after %ds" % (name, timeout)}
        lines = [l for l in (proc.stdout or "").splitlines() if l.strip().startswith("{")]
        if not lines:
            return {"ok": False, "error": "%s produced no result: %s" % (name, (proc.stderr or "").strip()[-300:])}
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return {"ok": False, "error": "%s returned bad JSON" % name}

    def read_web(self, capability: str, url: str) -> str:
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "error: read_web needs an http(s) url"
        if capability == "firecrawl":
            base = str(self.env.get("LOKI_FIRECRAWL_URL", "http://localhost:3002")).rstrip("/")
            verdict = self.policy.network(base, "firecrawl")
            if not verdict.allowed:
                return "error: " + verdict.reason
            headers = {}
            if self.env.get("FIRECRAWL_API_KEY"):
                headers["Authorization"] = "Bearer " + self.env["FIRECRAWL_API_KEY"]
            data = self._post_json(base + "/v2/scrape", {"url": url, "formats": ["markdown"]}, headers, timeout=120)
            body = data.get("data", data) if isinstance(data, dict) else {}
            text = str(body.get("markdown", "") or "")
            return text[:MAX_TEXT] if text else "error: firecrawl returned no markdown: %s" % json.dumps(data)[:300]
        result = self._runner("web_read", {"backend": capability, "url": url, "max_chars": MAX_TEXT}, timeout=120)
        if not result.get("ok"):
            return "error: " + str(result.get("error"))
        return str(result.get("text", "")) + ("\n[truncated]" if result.get("truncated") else "")

    def browse(self, task: str) -> str:
        job = {"task": task, "model": self.env.get("LOKI_BROWSE_MODEL", ""),
               "base_url": self.env.get("LOKI_BROWSE_BASE_URL", ""),
               "api_key": self.env.get("LOKI_BROWSE_API_KEY", "") or self.env.get("OPENAI_API_KEY", ""),
               "max_steps": int(self.env.get("LOKI_BROWSE_MAX_STEPS", "25") or 25)}
        result = self._runner("browse", job, timeout=int(self.env.get("LOKI_BROWSE_TIMEOUT", "600") or 600))
        return str(result.get("text")) if result.get("ok") else "error: " + str(result.get("error"))

    def hindsight(self, op: str, text: str) -> str:
        base = str(self.env.get("HINDSIGHT_URL", "http://localhost:8888")).rstrip("/")
        verdict = self.policy.network(base, "hindsight")
        if not verdict.allowed:
            return "error: " + verdict.reason
        job = {"op": op, "base_url": base, "bank": self.env.get("LOKI_HINDSIGHT_BANK", "loki"),
               "content": text, "query": text}
        result = self._runner("hindsight", job, timeout=120)
        if not result.get("ok"):
            return "error: " + str(result.get("error"))
        return "stored in long-term memory" if op == "retain" else json.dumps(result.get("result"), default=str)[:MAX_TEXT]


def python_command() -> list:
    """How to start a runner: `python -I` from source, or the packaged app's own runner mode
    (a frozen build has no separate interpreter; see app/loki_app.py --run-script)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-script"]
    return [sys.executable, "-I"]


# --------------------------------------------------------------------- in-loop helpers
def compress_messages(messages: list, model: str, importer=importlib.import_module) -> tuple[list, str]:
    """Headroom (Apache-2.0): shrink the context before a model call. Any failure returns the
    messages untouched - compression is an optimisation, never a requirement."""
    try:
        headroom = importer("headroom")
        result = headroom.compress(messages, model=model)
        compressed = list(getattr(result, "messages", messages))
        if not compressed:
            return messages, ""
        saved = getattr(result, "tokens_saved", 0) or 0
        return compressed, ("headroom saved %d tokens" % saved) if saved else ""
    except Exception:  # noqa: BLE001
        return messages, ""


def skillspector_findings(folder: Path, runner=subprocess.run, which=None) -> list[tuple[str, str]]:
    """NVIDIA SkillSpector static scan (`--no-llm`). [(severity, message)]. Empty on any failure."""
    import shutil
    exe = (which or shutil.which)("skillspector")
    if not exe:
        return []
    try:
        proc = runner([exe, "scan", str(folder), "--format", "json", "--no-llm"], capture_output=True,
                      text=True, timeout=120, shell=False)
        data = json.loads(proc.stdout or "{}")
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return []
    found: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            severity = node.get("severity") or node.get("level")
            message = node.get("message") or node.get("title") or node.get("description") or node.get("rule")
            if severity and message:
                found.append((str(severity).lower(), str(message)[:200]))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(data)
    return found


def python_module_present(name: str) -> bool:
    """True when a top-level module is installed - found, not imported."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def pick_vane_models(providers: list, prefer: str = "") -> tuple[dict | None, dict | None]:
    """Choose Vane's chat and embedding models: a local (Ollama) provider first, or the one
    whose model key contains `prefer`. Returns ({providerId, key}, {providerId, key})."""
    def models(p: dict, field: str) -> list:
        items = p.get(field) or []
        return [m for m in items if isinstance(m, dict) and m.get("key")]
    ordered = sorted([p for p in providers if isinstance(p, dict) and p.get("id")],
                     key=lambda p: 0 if "ollama" in str(p.get("name", "") + p.get("type", "")).lower() else 1)
    chat = embed = None
    for p in ordered:
        chats = models(p, "chatModels")
        if prefer:
            chats = sorted(chats, key=lambda m: 0 if prefer.lower() in m["key"].lower() else 1)
        if chats and chat is None:
            chat = {"providerId": p["id"], "key": chats[0]["key"]}
        embeds = models(p, "embeddingModels")
        if embeds and embed is None:
            embed = {"providerId": p["id"], "key": embeds[0]["key"]}
    return chat, embed
