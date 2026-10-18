"""Provider health registry: what each model provider can do RIGHT NOW, remembered.

Routing used to learn that Gemini's free quota was spent, or that Mistral's key was
rejected, the hard way - mid-task, in every process (each background job is its own
Python), with retries and back-off first. This registry keeps one record per provider:

  state        ok | key_rejected | no_credit | quota | rate_limited | size_limited |
               unreachable | model_missing | error | unknown
  until        when a temporary state ends (epoch seconds; 0 = until something changes)
  reason, fix  one plain line each, for routing ("skipped gemini: free quota used up until
               00:05") and for Settings > Connections ("Fix: paste a new key ...")
  key_fp       a short hash of the key the state belongs to: a NEW key clears a rejection
  latency_ms   moving average of real answers
  models       the provider's live model list (from its free /models endpoint)
  model_info   the configured model's context window, tool calling and vision, when the
               provider says (OpenRouter, Groq, Mistral, Together do)
  max_request  the biggest request (tokens) it accepted / the limit it named when it refused
  context      the context limit it named in a "too long" error

It is persisted to <LOKI_DATA>/provider_health.json (LOKI_HEALTH_FILE overrides), so the
engine, every background job and the next start all know. Marks made by THIS process are
"session" marks: when routing revives a provider in-process (loki._SMART_FAILED.clear(),
revive_rate_limited ...) they are forgotten too, so the in-process truth wins; marks from
other processes and from probes expire on their own `until` or when the key changes.

Probes are cheap and never paid: GET /models (and OpenRouter's /key, DeepSeek's
/user/balance) - no completion is ever sent, so no token is ever bought. The background
refresher probes each configured remote provider every LOKI_HEALTH_EVERY_S (1800 s) and a
limited one again once its `until` has passed.

Standard library only; never raises into a request.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEAD_STATES = ("key_rejected", "no_credit", "quota", "rate_limited", "unreachable", "model_missing", "error")
LABELS = {
    "ok": "works", "unknown": "not checked yet", "key_rejected": "key rejected", "no_credit": "out of credit",
    "quota": "free quota used up", "rate_limited": "rate limited", "size_limited": "refuses big requests",
    "unreachable": "unreachable", "model_missing": "model not available", "error": "failing",
}
EVERY_S = float(os.getenv("LOKI_HEALTH_EVERY_S", "1800") or 1800)


# --------------------------------------------------------------------- classifying errors
_DUR = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?")


def _duration(text: str) -> float:
    """'7m12.5s' -> 432.5, '37s' -> 37, '1h' -> 3600; 0 when there is none."""
    m = _DUR.fullmatch(text.strip())
    if not m or not any(m.groups()):
        return 0.0
    h, mi, s = m.groups()
    return float(h or 0) * 3600 + float(mi or 0) * 60 + float(s or 0)


def retry_after(text: str, header: Any = None) -> float:
    """Seconds the provider asked us to wait (Retry-After header, 'try again in 7m12s',
    Gemini's "retryDelay": "37s", 'retry after 20 seconds'); 0 when it did not say."""
    if header not in (None, ""):
        try:
            return max(0.0, float(header))
        except (TypeError, ValueError):
            pass
    low = str(text or "").lower()
    m = re.search(r'retrydelay"?\s*[:=]\s*"?(\d+(?:\.\d+)?)s', low)
    if m:
        return float(m.group(1))
    m = re.search(r"try again in\s+([0-9hms.]+)", low)
    if m and _duration(m.group(1).rstrip(".")):
        return _duration(m.group(1).rstrip("."))
    m = re.search(r"retry(?:[- ]after)?\s*(?:in|after)?\s*:?\s*(\d+(?:\.\d+)?)\s*(s|sec|seconds?)\b", low)
    if m:
        return float(m.group(1))
    return 0.0


def _next_utc_midnight(now: float) -> float:
    return (int(now // 86400) + 1) * 86400 + 300


def _limit_tokens(low: str) -> int:
    """Groq: 'Request too large ... tokens per minute (TPM): Limit 6000, Requested 9133'."""
    m = re.search(r"limit\s*:?\s*(\d{3,9})\s*,?\s*requested", low)
    return int(m.group(1)) if m else 0


def _context_tokens(low: str) -> int:
    """'maximum context length is 32768 tokens' / 'context window of 8192 tokens'."""
    m = re.search(r"(?:maximum context length|context (?:length|window|limit))\D{0,30}?(\d{3,9})", low)
    return int(m.group(1)) if m else 0


def classify(text: str, status: int = 0, header_retry: Any = None, now: float | None = None) -> dict:
    """{state, until, reason, size?, context?} for one failed request. Pure: no I/O."""
    now = time.time() if now is None else now
    low = str(text or "").lower()
    if not status:
        m = re.search(r"http (\d{3})", low)
        status = int(m.group(1)) if m else 0
    wait = retry_after(low, header_retry)
    ctx = _context_tokens(low)
    if ctx or any(k in low for k in ("context length", "context_length_exceeded", "prompt is too long",
                                     "too many tokens", "maximum context", "context window")):
        return {"state": "size_limited", "until": 0, "context": ctx,
                "reason": "said the conversation is too long for it" + (" (%d tokens max)" % ctx if ctx else "")}
    if status in (401, 403) or any(k in low for k in ("invalid api key", "incorrect api key", "invalid_api_key",
                                                      "unauthorized", "api key not valid", "authentication")):
        return {"state": "key_rejected", "until": 0, "reason": "key rejected"}
    credit = ("insufficient balance", "insufficient credit", "insufficient_quota", "no credit", "payment required",
              "out of credit")
    if status == 402 or any(k in low for k in credit) or (status != 429 and "credits" in low):
        return {"state": "no_credit", "until": now + 12 * 3600, "reason": "out of credit"}
    size = _limit_tokens(low)
    if status == 413 or size or "request too large" in low or "too large" in low:
        return {"state": "size_limited", "until": now + (wait or 60), "size": size,
                "reason": "refused a request that big" + (" (limit %d tokens)" % size if size else "")}
    if "billing" in low and "quota" not in low:
        return {"state": "no_credit", "until": now + 12 * 3600, "reason": "out of credit"}
    if any(k in low for k in ("quota", "resource_exhausted", "free-models-per-day", "per day", "perday", "daily limit")):
        daily = any(k in low for k in ("per day", "perday", "free-models-per-day", "daily"))
        until = now + wait if wait else (_next_utc_midnight(now) if daily else now + 3600)
        return {"state": "quota", "until": until, "reason": "free quota used up"}
    if status == 429 or any(k in low for k in ("rate limit", "rate_limit", "too many requests")):
        return {"state": "rate_limited", "until": now + max(wait, 30.0), "reason": "rate limited"}
    if status == 404 and ("model" in low or "not found" in low):
        return {"state": "model_missing", "until": now + 3600, "reason": "the model is not available there"}
    if "[model unavailable]" in low or "timed out" in low or "timeout" in low or "connection" in low:
        return {"state": "unreachable", "until": now + 120, "reason": "did not answer (timeout/unreachable)"}
    if "empty reply" in low or "no choices" in low:
        return {"state": "error", "until": now + 60, "reason": "returned an empty reply"}
    return {"state": "error", "until": now + 60, "reason": "failed (%s)" % (("HTTP %d" % status) if status else "error")}


def key_fp(key: str) -> str:
    key = str(key or "").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:10] if key else ""


# --------------------------------------------------------------------- the registry
class Registry:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else None
        self.clock = clock
        self.lock = threading.RLock()
        self.data: dict = {}
        self.session: set = set()     # providers whose current mark was made by this process
        self._mtime = 0.0
        self._load()

    # ---------------------------------------------------------------- persistence
    def _load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            mtime = self.path.stat().st_mtime
            if mtime == self._mtime:
                return
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self._mtime = mtime
        except (OSError, ValueError):
            return
        disk = raw.get("providers") if isinstance(raw, dict) else None
        if not isinstance(disk, dict):
            return
        for pid, entry in disk.items():
            if not isinstance(entry, dict):
                continue
            mine = self.data.get(pid)
            if mine is None or float(entry.get("at") or 0) > float(mine.get("at") or 0):
                self.data[pid] = entry
                self.session.discard(pid)

    def refresh(self) -> None:
        """Pick up what other processes wrote (cheap: one stat when nothing changed)."""
        with self.lock:
            self._load()

    def save(self) -> None:
        if not self.path:
            return
        with self.lock:
            self._load()   # merge with what other processes wrote since
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp%d" % os.getpid())
                tmp.write_text(json.dumps({"version": 1, "providers": self.data}, indent=1, sort_keys=True),
                               encoding="utf-8")
                os.replace(tmp, self.path)
                self._mtime = self.path.stat().st_mtime
            except OSError:
                pass

    # ---------------------------------------------------------------- recording
    def _entry(self, pid: str) -> dict:
        return self.data.setdefault(pid, {"state": "unknown", "until": 0, "reason": "", "at": 0.0,
                                          "ok": 0, "fail": 0})

    def record_failure(self, pid: str, text: str, status: int = 0, key: str = "", header_retry: Any = None,
                       session: bool = True) -> dict:
        if not pid:
            return {}
        with self.lock:
            self._load()
            verdict = classify(text, status, header_retry, now=self.clock())
            e = self._entry(pid)
            e["fail"] = int(e.get("fail") or 0) + 1
            e["error"] = _redact(str(text))[:200]
            if verdict.get("size"):
                e["max_request"] = int(verdict["size"])
            if verdict.get("context"):
                e["context"] = int(verdict["context"])
            if verdict["state"] == "size_limited" and not verdict.get("until"):
                # a conversation too long for it is not a reason to skip it for short ones
                e["at"] = self.clock()
            else:
                e.update(state=verdict["state"], until=float(verdict.get("until") or 0), reason=verdict["reason"],
                         key_fp=key_fp(key), at=self.clock())
            if session:
                self.session.add(pid)
            else:
                self.session.discard(pid)
            out = dict(e)
        self.save()
        return out

    def record_success(self, pid: str, latency_ms: float = 0.0, key: str = "", request_tokens: int = 0) -> None:
        if not pid:
            return
        with self.lock:
            self._load()
            e = self._entry(pid)
            was = e.get("state")
            e["ok"] = int(e.get("ok") or 0) + 1
            if latency_ms:
                prev = float(e.get("latency_ms") or 0)
                e["latency_ms"] = round(latency_ms if not prev else 0.7 * prev + 0.3 * latency_ms)
            if request_tokens and request_tokens > int(e.get("largest_ok") or 0):
                e["largest_ok"] = int(request_tokens)
            changed = was != "ok"
            e.update(state="ok", until=0, reason="", key_fp=key_fp(key) or e.get("key_fp", ""))
            if changed or self.clock() - float(e.get("at") or 0) > 300:
                e["at"] = self.clock()
                save = True
            else:
                save = False
            self.session.discard(pid)
        if save:
            self.save()

    def record_probe(self, pid: str, result: dict, key: str = "") -> None:
        """A background probe's finding (never a session mark: in-process revives keep it)."""
        with self.lock:
            self._load()
            e = self._entry(pid)
            for k in ("models", "model_info", "credit", "latency_ms"):
                if result.get(k) not in (None, "", [], {}):
                    e[k] = result[k]
            e["probe_at"] = self.clock()
            state = result.get("state")
            if state == "ok":
                # A probe proves the key and the endpoint; it does not lift a spent quota or a
                # rate limit early (a /models call is not a completion).
                if e.get("state") in ("key_rejected", "unreachable", "unknown", "model_missing", "error") or \
                        (e.get("state") == "no_credit" and result.get("credit_ok")):
                    e.update(state="ok", until=0, reason="")
                e["key_fp"] = key_fp(key)
            elif state:
                e.update(state=state, until=float(result.get("until") or 0), reason=result.get("reason", ""),
                         key_fp=key_fp(key))
                self.session.discard(pid)
            e["at"] = self.clock()
        self.save()

    def forget(self, pid: str, session_only: bool = True) -> None:
        with self.lock:
            if pid in self.data and (not session_only or pid in self.session):
                e = self.data[pid]
                if e.get("state") in DEAD_STATES:
                    e.update(state="ok" if e.get("ok") else "unknown", until=0, reason="")
                    e["at"] = self.clock()
            self.session.discard(pid)

    def forget_session(self) -> None:
        for pid in list(self.session):
            self.forget(pid, session_only=True)

    # ---------------------------------------------------------------- reading
    def get(self, pid: str) -> dict:
        with self.lock:
            return dict(self.data.get(pid) or {})

    def usable(self, pid: str, key: str = "", need_tokens: int = 0) -> tuple:
        """(True, "") or (False, "free quota used up until 00:05") for routing."""
        with self.lock:
            e = self.data.get(pid)
            if not e:
                return True, ""
            now = self.clock()
            state = e.get("state")
            fp = key_fp(key)
            if state in ("key_rejected", "no_credit") and fp and e.get("key_fp") and fp != e.get("key_fp"):
                return True, ""          # a new key: try it
            if need_tokens:
                cap = int(e.get("max_request") or 0)
                if cap and need_tokens > cap and need_tokens > int(e.get("largest_ok") or 0):
                    return False, "refuses requests over ~%d tokens (this one is ~%d)" % (cap, need_tokens)
                ctx = int(e.get("context") or (e.get("model_info") or {}).get("context") or 0)
                if ctx and need_tokens > ctx:
                    return False, "its context window (%d tokens) is smaller than this request (~%d)" % (ctx, need_tokens)
            if state not in DEAD_STATES:
                return True, ""
            until = float(e.get("until") or 0)
            if state in ("key_rejected",) or (until and until > now):
                return False, describe(e, now)
            return True, ""

    def snapshot(self) -> dict:
        with self.lock:
            self._load()
            now = self.clock()
            out = {}
            for pid, e in self.data.items():
                item = {k: v for k, v in e.items() if k not in ("key_fp", "models")}
                item["models_count"] = len(e.get("models") or [])
                item["label"] = LABELS.get(e.get("state", "unknown"), e.get("state", ""))
                item["line"] = describe(e, now)
                item["live"] = e.get("state") not in DEAD_STATES or bool(
                    e.get("until") and float(e["until"]) <= now and e.get("state") != "key_rejected")
                out[pid] = item
            return out


def _hhmm(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def describe(e: dict, now: float | None = None) -> str:
    """'free quota used up until 00:05' - one plain line."""
    now = time.time() if now is None else now
    state = e.get("state", "unknown")
    reason = e.get("reason") or LABELS.get(state, state)
    until = float(e.get("until") or 0)
    if state in DEAD_STATES and until > now:
        mins = (until - now) / 60
        when = ("in %d s" % (until - now)) if mins < 1 else ("in %d min" % round(mins)) if mins < 90 else ("until %s" % _hhmm(until))
        return "%s (back %s)" % (reason, when) if when.startswith("in") else "%s %s" % (reason, when)
    if state == "ok" and e.get("latency_ms"):
        return "works (%d ms)" % int(e["latency_ms"])
    return reason


_SECRET = re.compile(r"(sk|gsk|xai|pk|rk|AIza|csk)[-_A-Za-z0-9]{12,}|Bearer\s+[-._A-Za-z0-9]{12,}")


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


# --------------------------------------------------------------------- fixes, in one line
def fix_for(pid: str, entry: dict, catalog_entry: dict | None = None) -> str:
    """What the owner can do about it, in one line ('' when nothing is needed)."""
    cat = catalog_entry or {}
    name = cat.get("name") or pid
    keys = cat.get("keys") or cat.get("signup") or ""
    env = cat.get("env") or ""
    state = entry.get("state")
    if state == "key_rejected":
        return "Paste a new %s key in Settings > Connections%s%s." % (
            name, (" (" + keys + ")") if keys else "", (" - it goes in " + env) if env else "")
    if state == "no_credit":
        return "Add credit to your %s account%s, or switch it off - LOKI uses the free ones meanwhile." % (
            name, (" (" + keys + ")") if keys else "")
    if state == "quota":
        return "Nothing to do: the free quota refills by itself; LOKI uses the next free provider meanwhile."
    if state == "rate_limited":
        return "Nothing to do: it is busy for a moment; LOKI moves on and comes back."
    if state == "size_limited":
        return "LOKI only sends it requests that fit; big jobs go elsewhere."
    if state == "model_missing":
        return "Pick another model for %s in its card (the model list shows what it offers)." % name
    if state == "unreachable":
        return "Check the connection (or that the server is running)."
    return ""


# --------------------------------------------------------------------- probes (never paid)
def _get(url: str, key: str, timeout: float, opener=urllib.request.urlopen) -> tuple:
    headers = {"User-Agent": "Loki/1.0", "Accept": "application/json"}
    if key and key not in ("none", "ollama", "local"):
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, headers=headers)
    with opener(req, timeout=timeout) as resp:
        return int(getattr(resp, "status", 200) or 200), json.loads(resp.read().decode("utf-8") or "{}")


def model_info(items: list, model: str) -> dict:
    """The configured model's context window, tool calling and vision from a /models list,
    in whichever shape the provider uses (OpenRouter, Groq, Mistral, Together...)."""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or item.get("name") or "") != model:
            continue
        info: dict = {}
        ctx = item.get("context_length") or item.get("context_window") or item.get("max_context_length") or \
            (item.get("top_provider") or {}).get("context_length")
        if isinstance(ctx, (int, float)) and ctx > 0:
            info["context"] = int(ctx)
        params = item.get("supported_parameters")
        caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        if isinstance(params, list):
            info["tools"] = "tools" in params
        elif "function_calling" in caps:
            info["tools"] = bool(caps["function_calling"])
        mods = ((item.get("architecture") or {}).get("input_modalities"))
        if isinstance(mods, list):
            info["vision"] = "image" in mods
        elif "vision" in caps:
            info["vision"] = bool(caps["vision"])
        pricing = item.get("pricing") or {}
        if isinstance(pricing, dict) and pricing:
            try:
                info["free"] = float(pricing.get("prompt") or 0) == 0 and float(pricing.get("completion") or 0) == 0
            except (TypeError, ValueError):
                pass
        return info
    return {}


def probe(pid: str, base_url: str, key: str, model: str, timeout: float = 8.0,
          opener=urllib.request.urlopen, clock: Callable[[], float] = time.time) -> dict:
    """One free check of a remote provider: its /models list (plus the credit endpoints that
    exist). Never sends a completion. {state, reason, until, models, model_info, credit, latency_ms}."""
    started = time.monotonic()
    base = base_url.rstrip("/")
    try:
        _status, data = _get(base + "/models", key, timeout, opener)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        verdict = classify(body, exc.code, (exc.headers or {}).get("Retry-After") if exc.headers else None, now=clock())
        return {**verdict, "latency_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unreachable", "until": clock() + 300, "reason": "could not reach it (%s)" % type(exc).__name__}
    items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
    ids = []
    for item in items or []:
        mid = (item.get("id") or item.get("name")) if isinstance(item, dict) else str(item)
        if mid:
            ids.append(str(mid))
    out = {"state": "ok", "models": sorted(set(ids))[:500], "model_info": model_info(items or [], model),
           "latency_ms": int((time.monotonic() - started) * 1000)}
    if ids and model and model not in ids and not any(i.endswith("/" + model) or model.endswith("/" + i) for i in ids) \
            and model not in ("auto", "default_model"):
        out.update(state="model_missing", until=clock() + 3600,
                   reason="%s is not in its model list any more" % model)
    if "openrouter.ai" in base:
        try:
            _s, info = _get(base + "/key", key, timeout, opener)
            d = info.get("data") if isinstance(info, dict) else None
            if isinstance(d, dict):
                remaining = d.get("limit_remaining")
                out["credit"] = {"usage": d.get("usage"), "limit": d.get("limit"), "remaining": remaining,
                                 "free_tier": d.get("is_free_tier")}
                if isinstance(remaining, (int, float)) and remaining < 0:
                    out.update(state="no_credit", until=clock() + 12 * 3600,
                               reason="the account balance is negative (even :free models refuse then)")
                else:
                    out["credit_ok"] = True
        except Exception:  # noqa: BLE001 - the credit check is a bonus
            pass
    if "api.deepseek.com" in base:
        try:
            _s, info = _get(base + "/user/balance", key, timeout, opener)
            if isinstance(info, dict) and info.get("is_available") is False:
                out.update(state="no_credit", until=clock() + 12 * 3600, reason="no credit left")
            elif isinstance(info, dict) and info.get("is_available"):
                out["credit_ok"] = True
        except Exception:  # noqa: BLE001
            pass
    return out


# --------------------------------------------------------------------- the module-level registry
_REG: Registry | None = None
_REG_LOCK = threading.Lock()


def default_path() -> Path:
    explicit = os.getenv("LOKI_HEALTH_FILE", "").strip()
    if explicit:
        return Path(explicit)
    data = os.getenv("LOKI_DATA", "").strip()
    return (Path(data) if data else Path(__file__).resolve().parent.parent / "harness_data") / "provider_health.json"


def registry() -> Registry:
    global _REG
    with _REG_LOCK:
        if _REG is None:
            _REG = Registry(default_path())
        return _REG


def set_registry(reg: Registry) -> None:
    global _REG
    with _REG_LOCK:
        _REG = reg


_REFRESHER: dict = {"thread": None, "stop": None}


def due(reg: Registry, pid: str, every_s: float = EVERY_S) -> bool:
    e = reg.get(pid)
    now = reg.clock()
    if not e or not e.get("probe_at"):
        return True
    if e.get("state") in DEAD_STATES and e.get("until") and float(e["until"]) <= now:
        return True
    return now - float(e.get("probe_at") or 0) >= every_s


def refresh_once(agent: Any, reg: Registry | None = None, opener=urllib.request.urlopen, force: bool = False) -> list:
    """Probe every configured remote provider that is due. Returns the ids probed."""
    reg = reg or registry()
    done = []
    for pid, cfg in list(agent.MODELS.items()):
        base = str(getattr(cfg, "base_url", "") or "")
        if pid in ("smart", "online") or base.startswith("cli-agent://") or not base.startswith("https://"):
            continue
        key = str(getattr(cfg, "api_key", "") or "").strip()
        try:
            if not key or agent.provider_disabled(pid):
                continue
        except Exception:  # noqa: BLE001
            continue
        if "ACCOUNT_ID" in base:
            continue
        if not force and not due(reg, pid):
            continue
        result = probe(pid, base, key, str(getattr(cfg, "model", "") or ""), opener=opener, clock=reg.clock)
        if result.get("state") == "model_missing":
            better = replacement(pid, str(getattr(cfg, "model", "") or ""), result.get("models") or [])
            if better:
                # the provider renamed or dropped the model (Pollinations "openai", NVIDIA's DeepSeek
                # names): use what it serves now instead of leaving the provider dead
                cfg.model = better
                result = dict(result, state="ok", until=0, reason="", switched_to=better)
        reg.record_probe(pid, result, key=key)
        done.append(pid)
    return done


# a provider whose own free model list LOKI may pick from when its usual model is gone, best first
SWAP_PREFERENCE = {"pollinations": ["openai", "openai-fast", "openai-large", "mistral", "deepseek", "qwen-coder"]}


def replacement(pid: str, model: str, served: list) -> str:
    """The model to use instead of a missing one, or "" (never a random model for a paid provider):
    the same model under another name (engine/nim_models.py), else the provider's preferred free list."""
    if not served:
        return ""
    try:
        import nim_models  # pylint: disable=import-outside-toplevel
        alias = nim_models.resolve(model, served)
        if alias != model:
            return alias
    except Exception:  # noqa: BLE001
        pass
    for name in SWAP_PREFERENCE.get(pid, []):
        if name in served:
            return name
    return served[0] if pid in SWAP_PREFERENCE else ""


def start_background(agent: Any, every_s: float = 0.0) -> bool:
    """Probe in the background (the engine calls this once). LOKI_HEALTH_PROBES=0 turns it off."""
    if str(os.getenv("LOKI_HEALTH_PROBES", "1")).strip().lower() in ("0", "off", "false", "no"):
        return False
    if _REFRESHER["thread"] is not None and _REFRESHER["thread"].is_alive():
        return False
    stop = threading.Event()
    period = max(60.0, float(every_s or min(EVERY_S, 300.0)))

    def loop() -> None:
        stop.wait(20)                 # let the engine finish starting first
        while not stop.is_set():
            try:
                refresh_once(agent)
            except Exception:  # noqa: BLE001 - a probe must never take the engine down
                pass
            stop.wait(period)

    thread = threading.Thread(target=loop, daemon=True, name="loki-provider-health")
    _REFRESHER.update(thread=thread, stop=stop)
    thread.start()
    return True
