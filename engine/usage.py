"""The credits meter: what every model call cost, in tokens, time and money.

Each model call appends one line to harness_data/usage.jsonl:

    {"t": 1791877000.1, "provider": "openrouter", "model": "deepseek/deepseek-chat",
     "in": 8123, "out": 412, "ms": 2310, "cost": 0.00265, "free": false, "chat": "..."}

Tokens come from the provider's `usage` block; when a provider sends none (some local
servers), they are estimated at ~4 characters per token and marked `est`. Cost uses
PRICES (USD per million tokens, input/output) - local models, free tiers and flat-rate
subscriptions (Claude Code, Codex) cost 0. harness_data/prices.json overrides any entry.

Pure functions plus an append-only file; summaries are computed on read.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# (provider or model substring) -> (input $/M, output $/M). First match wins; model
# substrings are checked before provider names. Approximate list prices.
PRICES: list[tuple[str, float, float]] = [
    ("claude-opus", 15.0, 75.0), ("claude-sonnet", 3.0, 15.0), ("claude-haiku", 0.8, 4.0),
    ("gpt-5", 1.25, 10.0), ("gpt-4.1-mini", 0.4, 1.6), ("gpt-4o-mini", 0.15, 0.6),
    ("gpt-4o", 2.5, 10.0), ("o4-mini", 1.1, 4.4),
    ("gemini-2.5-pro", 1.25, 10.0), ("gemini-2.5-flash", 0.3, 2.5), ("gemini", 0.3, 2.5),
    ("deepseek", 0.27, 1.1), ("sonar-pro", 3.0, 15.0), ("sonar", 1.0, 1.0),
    ("mistral-large", 2.0, 6.0), ("mistral", 0.25, 0.25), ("llama", 0.2, 0.2), ("qwen", 0.2, 0.6),
]
# Providers that never bill per token.
FREE_PROVIDERS = {"local", "local-small", "local-coder", "local-hermes", "local-reasoning",
                  "local-tools", "local-fast", "vireonix", "llm7", "claude-code", "codex",
                  "lmstudio", "llamacpp", "jan", "omniroute", "mlx", "vllm", "kyojin"}
# Providers whose default use is a free tier (cost shown as 0 but tokens still counted). gemini / groq / cerebras /
# sambanova / cloudflare / modelscope were removed as routes on 2026-10-27 (daily caps); kept here so old usage lines
# still read as free.
FREE_TIER = {"nvidia-nemotron", "nvidia-pro", "gemini", "groq", "cerebras", "sambanova", "cloudflare", "nous", "huggingface",
             "openrouter-free", "kilocode", "modelscope", "nvidia"}


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def messages_chars(messages: list) -> int:
    total = 0
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        if isinstance(content, list):
            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        total += len(str(content or ""))
    return total


def price_for(provider: str, model: str, overrides: dict | None = None) -> tuple[float, float, str]:
    """(input $/M, output $/M, why) for a call."""
    overrides = overrides or {}
    for key in (model, provider):
        if key in overrides:
            value = overrides[key]
            return float(value[0]), float(value[1]), "prices.json"
    if provider in FREE_PROVIDERS or model.endswith(":free"):
        return 0.0, 0.0, "free"
    if provider in FREE_TIER:
        return 0.0, 0.0, "free tier"
    low = model.lower()
    for needle, cin, cout in PRICES:
        if needle in low:
            return cin, cout, "list price"
    for needle, cin, cout in PRICES:
        if needle in provider.lower():
            return cin, cout, "list price"
    return 0.0, 0.0, "unknown price"


class Ledger:
    def __init__(self, path: Path, prices_path: Path | None = None) -> None:
        self.path = Path(path)
        self.prices_path = Path(prices_path) if prices_path else self.path.with_name("prices.json")
        self.lock = threading.Lock()

    def overrides(self) -> dict:
        try:
            data = json.loads(self.prices_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, provider: str, model: str, tokens_in: int | None, tokens_out: int | None,
               ms: int, prompt_chars: int = 0, output_chars: int = 0, chat: str = "", kind: str = "chat") -> dict:
        estimated = tokens_in is None or tokens_out is None
        tin = int(tokens_in if tokens_in is not None else estimate_tokens("x" * prompt_chars))
        tout = int(tokens_out if tokens_out is not None else estimate_tokens("x" * output_chars))
        cin, cout, why = price_for(provider, model, self.overrides())
        cost = round(tin / 1e6 * cin + tout / 1e6 * cout, 6)
        entry = {"t": round(time.time(), 2), "provider": provider, "model": model, "in": tin, "out": tout,
                 "ms": int(ms), "cost": cost, "free": cost == 0.0, "price": why, "est": estimated,
                 "tps": round(tout / (ms / 1000.0), 1) if ms >= 250 and tout else 0.0, "chat": chat, "kind": kind}
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry) + "\n")
            except OSError:
                pass
        return entry

    def entries(self, since: float = 0.0) -> list[dict]:
        out = []
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if entry.get("t", 0) >= since:
                        out.append(entry)
        except OSError:
            pass
        return out

    def summary(self, now: float | None = None) -> dict:
        now = now or time.time()
        day = now - 86400
        month = now - 30 * 86400
        rows = self.entries(month)
        def total(items):
            return {"calls": len(items), "in": sum(e["in"] for e in items), "out": sum(e["out"] for e in items),
                    "cost": round(sum(e["cost"] for e in items), 4)}
        by_provider: dict[str, dict] = {}
        for e in rows:
            slot = by_provider.setdefault(e["provider"], {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "model": e["model"],
                                                          "free": True, "tps": []})
            slot["calls"] += 1
            slot["in"] += e["in"]
            slot["out"] += e["out"]
            slot["cost"] = round(slot["cost"] + e["cost"], 4)
            slot["free"] = slot["free"] and e["free"]
            if e.get("tps"):
                slot["tps"].append(e["tps"])
        for slot in by_provider.values():
            tps = slot.pop("tps")
            slot["avg_tps"] = round(sum(tps) / len(tps), 1) if tps else 0.0
        return {"today": total([e for e in rows if e["t"] >= day]), "month": total(rows),
                "by_provider": dict(sorted(by_provider.items(), key=lambda kv: -kv[1]["calls"])),
                "recent": rows[-20:][::-1]}

    def reset(self) -> None:
        with self.lock:
            try:
                self.path.unlink()
            except OSError:
                pass


def line(entry: dict) -> str:
    """The one-line meter under a reply: 'qwen3.5 · 8.1k in / 412 out · 38 tok/s · free'."""
    def k(n: int) -> str:
        return "%.1fk" % (n / 1000.0) if n >= 1000 else str(n)
    cost = "free" if entry.get("free") else "$%.4f" % entry.get("cost", 0.0)
    if entry.get("price") == "unknown price":
        cost = "price unknown"
    parts = [entry.get("model", ""), "%s in / %s out%s" % (k(entry.get("in", 0)), k(entry.get("out", 0)),
                                                           " (est.)" if entry.get("est") else "")]
    if entry.get("cached") and entry.get("in"):
        parts.append("%d%% cached" % round(100 * entry["cached"] / entry["in"]))
    if entry.get("tps"):
        parts.append("%s tok/s" % entry["tps"])
    parts.append(cost)
    return " · ".join(p for p in parts if p)
