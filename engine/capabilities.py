"""Loki's capability registry.

Everything Loki can reach - a model provider, a built-in tool, an MCP server, a vendored
skill library - is described here with the SAME fields, so the whole surface can be listed,
searched and reported on without reading the code. This is the seed of the API Vault the
project vision asks for (a searchable catalogue where every entry carries its source,
license, credential requirement and status).

The module owns no state and never talks to the network: every function is pure and takes
the data it needs, so it is unit-testable without Loki. Keep the documented statuses honest:
  ready        usable right now
  needs_key    present but credential-gated
  disabled     switched off (or gated by a missing command / env)
  unavailable  the source could not be read
"""
from __future__ import annotations

import json
from pathlib import Path

KINDS = ("provider", "cli-agent", "tool", "mcp", "skill-library")

# Where to get a key, for the ones that need one. Onboarding copy, kept here so a
# capability report can point a user at the exact page.
PROVIDER_DOCS = {
    "openrouter": "https://openrouter.ai/keys",
    "deepseek-4.1": "https://openrouter.ai/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "together": "https://api.together.ai/settings/api-keys",
    "nous": "https://portal.nousresearch.com",
    "unorouter": "https://unorouter.com",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "gpt": "https://platform.openai.com/api-keys",
    "claude": "https://console.anthropic.com/settings/keys",
    "claude-code": "install @anthropic-ai/claude-code, then run claude and /login",
    "codex": "install @openai/codex, then run codex login",
    "vireonix": "nothing to do - needs no key, no account and no card",
    "llm7": "https://token.llm7.io (optional - anonymous use works)",
    "aion": "https://www.aionlabs.ai/app/api-keys/",
    "cohere": "https://dashboard.cohere.com/api-keys",
    "zai": "https://open.bigmodel.cn/usercenter/apikeys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "kilocode": "https://app.kilo.ai/profile",
    "nvidia": "https://build.nvidia.com/explore/discover",
    "nvidia-nemotron": "the same NVIDIA key (build.nvidia.com/settings/api-keys)",
    "ollama-cloud": "https://ollama.com/settings/keys",
    "ovh": "https://www.ovhcloud.com/en/public-cloud/ai-endpoints/",
    "siliconflow": "https://cloud.siliconflow.cn/account/ak",
    "omniroute": "local gateway on http://localhost:20128 (see docs/providers.md)",
}


def provider_entries(models: dict, configured) -> list:
    """One entry per model provider. `configured(name) -> bool` decides ready vs needs_key."""
    entries = []
    for name, cfg in models.items():
        if name in ("smart", "online", "max", "fast"):
            continue                      # modes, not endpoints
        base = str(getattr(cfg, "base_url", "") or "")
        kind = "cli-agent" if base.startswith("cli-agent://") else "provider"
        try:
            ready = bool(configured(name))
        except Exception:
            ready = False
        entries.append({
            "id": name,
            "kind": kind,
            "source": base,
            "model": str(getattr(cfg, "model", "") or ""),
            "status": "ready" if ready else "needs_key",
            "doc": PROVIDER_DOCS.get(name, ""),
        })
    return entries


def tool_entries(schemas: list, offered, categories: dict) -> list:
    """One entry per built-in tool. `offered` is the set the model may call; the rest are gated."""
    offered_set = set(offered or ())
    category_of = {}
    for category, names in (categories or {}).items():
        for tool_name in names:
            category_of[tool_name] = category
    entries = []
    for entry in schemas or []:
        fn = entry.get("function", {}) if isinstance(entry, dict) else {}
        name = str(fn.get("name", ""))
        if not name:
            continue
        entries.append({
            "id": name,
            "kind": "tool",
            "source": "offered" if name in offered_set else "gated",
            "category": category_of.get(name, ""),
            "status": "ready" if name in offered_set else "disabled",
            "description": str(fn.get("description", "") or "")[:160],
        })
    return entries


def mcp_entries(config_path, skip_reason=None) -> list:
    """One entry per configured MCP server, with the reason it is skipped when it is."""
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception:
        return []
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    entries = []
    for name, spec in (servers or {}).items():
        if not isinstance(spec, dict):
            continue
        reason = ""
        if callable(skip_reason):
            try:
                reason = str(skip_reason(spec, name) or "")
            except Exception:
                reason = ""
        entries.append({
            "id": name,
            "kind": "mcp",
            "source": str(spec.get("command", "") or spec.get("url", "")),
            "status": "disabled" if reason else "ready",
            "notes": reason or str(spec.get("install", "") or "")[:160],
        })
    return entries


def skill_entries(vendor_dir) -> list:
    """One entry per vendored skill library (a folder under harness_data/vendor)."""
    base = Path(vendor_dir)
    if not base.is_dir():
        return []
    entries = []
    for child in sorted(base.iterdir()):
        if child.is_dir():
            entries.append({"id": child.name, "kind": "skill-library",
                            "source": str(child), "status": "ready"})
    return entries


def registry(**parts) -> list:
    """The combined registry. `parts` are the inputs each *_entries() needs."""
    entries = []
    entries += provider_entries(parts.get("models", {}),
                                parts.get("configured") or (lambda _n: False))
    entries += tool_entries(parts.get("schemas", []), parts.get("offered"),
                            parts.get("categories"))
    entries += mcp_entries(parts.get("mcp_path"), parts.get("skip_reason"))
    entries += skill_entries(parts.get("vendor_dir"))
    return sorted(entries, key=lambda e: (e.get("kind", ""), e.get("id", "")))


def search(entries: list, query: str) -> list:
    """Substring match over the searchable fields. An empty query returns everything."""
    q = str(query or "").strip().lower()
    if not q:
        return list(entries)
    fields = ("id", "kind", "source", "status", "category", "description", "notes", "model")
    hits = []
    for entry in entries:
        hay = " ".join(str(entry.get(k, "")) for k in fields).lower()
        if q in hay:
            hits.append(entry)
    return hits


def summary(entries: list) -> dict:
    """Counts by kind and by status, for a one-line report."""
    by_kind: dict = {}
    by_status: dict = {}
    for entry in entries:
        kind = entry.get("kind", "?")
        state = entry.get("status", "?")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_status[state] = by_status.get(state, 0) + 1
    return {"total": len(entries), "by_kind": by_kind, "by_status": by_status}


def render(entries: list, total: int = 0) -> str:
    """A compact text report: one line per capability plus a status footer."""
    if not entries:
        return "(no matching capabilities)"
    lines = []
    for entry in entries[:120]:
        detail = entry.get("model") or entry.get("category") or entry.get("notes") or ""
        doc = ("  " + str(entry.get("doc"))) if entry.get("doc") else ""
        lines.append("%-9s %-16s %-9s %s%s" % (
            entry.get("kind", ""), entry.get("id", ""), entry.get("status", ""),
            str(detail)[:60], doc))
    if len(entries) > 120:
        lines.append("... (+%d more)" % (len(entries) - 120))
    counts = summary(entries)
    lines.append("%d shown (%d total) - %s" % (
        min(len(entries), 120), total or len(entries),
        ", ".join("%s=%d" % (k, v) for k, v in sorted(counts["by_status"].items()))))
    return chr(10).join(lines)
