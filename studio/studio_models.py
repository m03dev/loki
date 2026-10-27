"""The models LOKI Studio's development agent runs on: DeepSeek V4.1 Flash on NVIDIA NIM first
(free, ~40 requests/min, 1M context, tool calling), then the next best free models as fallbacks.

Self-contained on purpose (only the standard library and engine/ratelimit.py): Studio must work
when LOKI's engine is broken, so it does not import loki.py. One request = `chat(...)`: paced
under the provider's per-minute cap (shared with LOKI's own jobs through the data folder), a
429 waits a short Retry-After or fails over to the next provider, a rejected key / timeout /
5xx fails over, and the hidden reasoning (reasoning_content, <think>) comes back separately -
it is shown as "thinking" and never re-sent.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import studio_paths  # noqa: F401  (puts engine/ on sys.path)
import ratelimit
import nim_models

KEY_URL = "https://build.nvidia.com/settings/api-keys"
DRIVER = "nvidia"
DRIVER_MODEL = "deepseek-ai/deepseek-v4.1-flash"
HOW_TO_GET_KEY = ("DeepSeek V4.1 Flash runs free on NVIDIA NIM. Get a free key at %s (sign in, Generate API Key; "
                  "it starts with nvapi-), then paste it in LOKI: Settings > Connections > NVIDIA NIM. Studio picks it "
                  "up on its next session." % KEY_URL)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


@dataclass
class Provider:
    id: str
    name: str
    base_url: str
    model: str
    key_env: str = ""
    key: str = ""
    free: bool = True
    local: bool = False
    extra: dict = field(default_factory=dict)

    def ready(self) -> bool:
        if self.local:
            return _local_up(self.base_url)
        return bool(self.key.strip())


def _local_up(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=1.5) as resp:
            return resp.status == 200
    except (OSError, ValueError):
        return False


def thinking_fields() -> dict:
    mode = str(os.getenv("LOKI_NVIDIA_THINKING", "off")).strip().lower()
    on = mode not in ("off", "0", "false", "no", "")
    tmpl: dict = {"thinking": on}
    if on:
        tmpl["reasoning_effort"] = "max" if mode == "max" else "high"
    return {"chat_template_kwargs": tmpl}


def providers(env: dict | None = None) -> list:
    """Every provider Studio can drive, best first (the main driver leads)."""
    if env is None:
        studio_paths.refresh_keys()   # a key saved in LOKI's Settings since Studio started counts now
    e = os.environ if env is None else env
    allow_paid = str(e.get("LOKI_ALLOW_PAID", "0")).strip() == "1"
    nim_base, nim_key = e.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"), e.get("NVIDIA_API_KEY", "")
    # the name NVIDIA really serves (a wrong one is HTTP 404 - the owner's Mac, 2026-10-17)
    nim_model = nim_models.resolve(e.get("NVIDIA_MODEL", DRIVER_MODEL), nim_models.cached(nim_base, nim_key))
    out = [
        Provider("nvidia", "DeepSeek V4.1 Flash on NVIDIA NIM", nim_base, nim_model, "NVIDIA_API_KEY", nim_key,
                 extra=thinking_fields()),
        # Nemotron on the same NVIDIA key - free, no daily cap (Gemini / Groq free tiers removed 2026-10-27: daily caps)
        Provider("nvidia-nemotron", "Nemotron on NVIDIA NIM", nim_base,
                 nim_models.resolve(e.get("NVIDIA_NEMOTRON_MODEL", nim_models.NEMOTRON[0]), nim_models.cached(nim_base, nim_key)),
                 "NVIDIA_API_KEY", nim_key),
    ]
    if allow_paid:
        out.append(Provider("deepseek", "DeepSeek (paid)", e.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                            e.get("DEEPSEEK_MODEL", "deepseek-flash"), "DEEPSEEK_API_KEY", e.get("DEEPSEEK_API_KEY", ""), free=False))
    out.append(Provider("local", "The local model (Ollama)", "http://127.0.0.1:11434/v1", local_model(e),
                        key="ollama", local=True, extra={"think": False}))
    out.append(Provider("lmstudio", "LM Studio (local)", e.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                        e.get("LMSTUDIO_MODEL", "") or "local-model", key="lm-studio", local=True))
    pinned = str(e.get("LOKI_STUDIO_MODEL", "")).strip().lower()
    if pinned:
        out.sort(key=lambda p: p.id != pinned)
    return out


_LOCAL_PICK: dict = {"at": 0.0, "name": ""}


def local_model(env: dict | None = None) -> str:
    """The Ollama model Studio's "local" driver uses: LOKI_STUDIO_LOCAL_MODEL / LOKI_LOCAL_MODEL when
    pinned, else the one LOKI's engine picked (harness_data/app/status.json) if Ollama has it, else
    the first installed model (LOKI's own loki-* variants first). Never a model that is not installed:
    a stock "qwen3:8b" the Mac never pulled made every Studio turn a 404 (2026-10-18)."""
    e = os.environ if env is None else env
    pinned = str(e.get("LOKI_STUDIO_LOCAL_MODEL") or e.get("LOKI_LOCAL_MODEL") or "").strip()
    if pinned:
        return pinned
    if _LOCAL_PICK["name"] and time.time() - _LOCAL_PICK["at"] < 60:
        return _LOCAL_PICK["name"]
    installed = None
    try:
        import model_setup  # pylint: disable=import-outside-toplevel
        found = model_setup.ollama_models()
        if found is not None:
            installed = [m["name"] for m in found if "embed" not in m["name"].lower()]
    except Exception:  # noqa: BLE001
        installed = None
    engine_pick = ""
    try:
        status = json.loads((studio_paths.data() / "app" / "status.json").read_text(encoding="utf-8"))
        engine_pick = str(((status.get("local") or {}).get("name")) or "").strip()
    except Exception:  # noqa: BLE001
        engine_pick = ""

    def has(name: str) -> bool:
        return installed is None or name in installed or name + ":latest" in installed

    if engine_pick and has(engine_pick):
        name = engine_pick
    elif installed:
        name = ([n for n in installed if n.startswith("loki-")] or installed)[0]
    else:
        name = engine_pick or "qwen3:8b"
    _LOCAL_PICK.update(at=time.time(), name=name)
    return name


def chain(env: dict | None = None) -> list:
    """The providers that are ready right now, in order."""
    return [p for p in providers(env) if p.ready()]


CLI_DRIVERS = {"claude-code": ("claude", "Claude Code (your Claude subscription, its own tools + Studio's MCP)"),
               "codex": ("codex", "Codex CLI (your ChatGPT subscription, its own tools + Studio's MCP)")}


def choices(env: dict | None = None) -> list:
    """Every model a session can be driven by, for the pickers: [{id, name, model, ready}]."""
    import shutil  # pylint: disable=import-outside-toplevel
    rows = [{"id": "auto", "name": "Auto (DeepSeek V4.1 Flash on NVIDIA first, then the free fallbacks)", "model": "", "ready": True}]
    for p in providers(env):
        rows.append({"id": p.id, "name": p.name, "model": p.model, "ready": p.ready() if not p.local else None})
    for pid, (binary, name) in CLI_DRIVERS.items():
        rows.append({"id": pid, "name": name, "model": binary, "ready": bool(shutil.which(binary))})
    return rows


def driver_status(env: dict | None = None) -> dict:
    """What drives Studio now, and - when it is not DeepSeek on NVIDIA - exactly how to fix that."""
    allp = providers(env)
    ready = [p for p in allp if p.ready()]
    driver = next(p for p in allp if p.id == DRIVER)
    first = ready[0] if ready else None
    if first is not None and first.id == DRIVER:
        text = "Driving: %s (%s). Paced at %d requests/min." % (driver.name, driver.model, ratelimit.rpm(DRIVER))
        return {"ok": True, "provider": DRIVER, "model": driver.model, "text": text, "how": "", "fallback": ""}
    how = HOW_TO_GET_KEY if not driver.ready() else ""
    if first is None:
        return {"ok": False, "provider": "", "model": "", "how": how,
                "text": "No model is ready yet." + ("" if how else " Set up a provider in LOKI's Settings > Connections.")}
    return {"ok": True, "provider": first.id, "model": first.model, "how": how, "fallback": first.id,
            "text": "%s is not set up, so Studio uses the next best free model: %s (%s)." % (driver.name, first.name, first.model)}


class ModelError(Exception):
    def __init__(self, text: str, status: int = 0, retry_after: float = 0.0, fail_over: bool = True,
                 timed_out: bool = False):
        super().__init__(text)
        self.status, self.retry_after, self.fail_over, self.timed_out = status, retry_after, fail_over, timed_out


def split_reasoning(message: dict) -> tuple:
    """(content, reasoning) of one reply message: reasoning_content / reasoning / <think> out of the answer."""
    content = message.get("content") or ""
    if not isinstance(content, str):
        content = json.dumps(content)
    found = [str(message.get(k)) for k in ("reasoning_content", "reasoning") if message.get(k)]
    if "think>" in content.lower():
        found += [m.group(0)[7:-8].strip() for m in _THINK.finditer(content)]
        content = _THINK.sub("", content)
        low = content.lower()
        if "</think>" in low:
            at = low.rindex("</think>")
            found.append(content[:at].replace("<think>", "").strip())
            content = content[at + 8:]
        content = content.replace("<think>", "").replace("</think>", "")
    return content.strip(), "\n".join(f for f in found if f).strip()


def _retry_after(headers, body: str) -> float:
    try:
        value = float((headers or {}).get("Retry-After") or 0)
        if value:
            return value
    except (TypeError, ValueError):
        pass
    m = re.search(r"(?:try again|retry) in (\d+(?:\.\d+)?)\s*s", body or "", re.I)
    return float(m.group(1)) if m else 0.0


# Streaming (owner's Mac, 2026-10-18: "nvidia did not answer (The read operation timed out)" on every turn). Without
# stream the server says nothing until the WHOLE answer is written: up to 8192 tokens at the free tier's ~20 tok/s is
# longer than any sane timeout, so every long turn timed out after 180 s, was retried (another 180 s), and the next
# turn started over. Streamed, tokens arrive as they are made: the timeout is the silence between two chunks
# (STREAM_IDLE_S), a slow-but-working answer is never cut off, and a provider that never starts fails in
# FIRST_BYTE_S. Local servers stay unstreamed (Ollama answers fast and its streamed tool calls vary by version).
STREAM_IDLE_S = float(os.getenv("LOKI_STUDIO_STREAM_IDLE_S", "75") or 75)
FIRST_BYTE_S = float(os.getenv("LOKI_STUDIO_FIRST_BYTE_S", "90") or 90)
STREAM_MAX_S = float(os.getenv("LOKI_STUDIO_STREAM_MAX_S", "900") or 900)


def _read_stream(resp, provider_id: str, clock=time.monotonic) -> dict:
    """An OpenAI server-sent-event stream -> one reply message (content, reasoning_content, tool_calls)."""
    content, reasoning, calls = [], [], {}
    began = clock()
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if clock() - began > STREAM_MAX_S:
            raise ModelError("%s kept writing for more than %d s" % (provider_id, STREAM_MAX_S))
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if chunk.get("error"):
            err = chunk["error"]
            raise ModelError("%s: %s" % (provider_id, (err.get("message") if isinstance(err, dict) else err)), status=0)
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if delta.get("content"):
                content.append(str(delta["content"]))
            for key in ("reasoning_content", "reasoning"):
                if delta.get(key):
                    reasoning.append(str(delta[key]))
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(int(tc.get("index", len(calls))), {"id": "", "type": "function",
                                                                         "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
    message: dict = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if calls:
        message["tool_calls"] = [dict(calls[i], id=calls[i]["id"] or "call_%d" % i) for i in sorted(calls)]
    if not message["content"] and not calls and not reasoning:
        raise ModelError("%s returned an empty stream" % provider_id)
    return message


def request(provider: Provider, messages: list, tools: list | None = None, max_tokens: int = 8192,
            timeout: float = 180.0, opener=urllib.request.urlopen, stream: bool | None = None) -> dict:
    """One chat completion from one provider -> the reply message (dict). Raises ModelError."""
    stream = (not provider.local) if stream is None else stream
    body: dict = {"model": provider.model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    body.update(provider.extra or {})
    if stream:
        body["stream"] = True
    req = urllib.request.Request(provider.base_url.rstrip("/") + "/chat/completions", method="POST",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + provider.key, "Content-Type": "application/json",
                                          "Accept": "text/event-stream" if stream else "application/json",
                                          "User-Agent": "LOKI-Studio/1"})
    try:
        # streamed: the socket timeout is the wait for the first byte, then the silence allowed between chunks
        with opener(req, timeout=FIRST_BYTE_S if stream else timeout) as resp:
            kind = str(getattr(resp, "headers", {}).get("Content-Type", "") if getattr(resp, "headers", None) else "")
            if stream and "event-stream" in kind:
                try:
                    resp.fp.raw._sock.settimeout(STREAM_IDLE_S)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - not a real socket (tests): keep the first-byte timeout
                    pass
                return _read_stream(resp, provider.id)
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except ModelError:
        raise
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")[:600]
        raise ModelError("%s answered HTTP %s: %s" % (provider.id, exc.code, " ".join(text.split())[:240]),
                         status=exc.code, retry_after=_retry_after(exc.headers, text)) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ModelError("%s did not answer (%s)" % (provider.id, getattr(exc, "reason", exc)), timed_out=True) from exc
    except ValueError as exc:
        raise ModelError("%s sent something that is not JSON" % provider.id) from exc
    choices = data.get("choices") or []
    if not choices:
        raise ModelError("%s returned no choices" % provider.id)
    return dict(choices[0].get("message") or {})


# A provider that just timed out is asked LAST for a while (it was: first again on every turn, another 6 minutes).
SLOW_FOR_S = float(os.getenv("LOKI_STUDIO_SLOW_FOR_S", "600") or 600)
_SLOW: dict = {}   # provider id -> until (time.time())


def slow(provider_id: str, now: float | None = None) -> bool:
    return _SLOW.get(provider_id, 0.0) > (time.time() if now is None else now)


def chat(messages: list, tools: list | None = None, chain_list: list | None = None, say=None, sleep=time.sleep,
         opener=urllib.request.urlopen, stop=None, max_short_wait: float = 20.0) -> tuple:
    """(provider, message, reasoning): ask the first ready provider; pace, wait out a short 429, fail over."""
    order = list(chain_list if chain_list is not None else chain())
    order.sort(key=lambda p: slow(p.id))          # stable: a provider that just timed out goes to the back
    if not order:
        raise ModelError("no model is ready. " + HOW_TO_GET_KEY, fail_over=False)
    say = say or (lambda _t: None)
    last = None
    for i, provider in enumerate(order):
        tries = 0
        while True:
            if stop is not None and stop.is_set():
                raise ModelError("stopped", fail_over=False)
            if ratelimit.rpm(provider.id):
                ratelimit.acquire(provider.id, max_wait_s=75, sleep=sleep, say=say)
            try:
                message = request(provider, messages, tools, opener=opener)
                content, reasoning = split_reasoning(message)
                message = {k: v for k, v in message.items() if k not in ("reasoning_content", "reasoning")}
                message["content"] = content
                return provider, message, reasoning
            except ModelError as exc:
                last = exc
                tries += 1
                if exc.status == 429:
                    if ratelimit.rpm(provider.id):
                        ratelimit.penalize(provider.id, exc.retry_after or 20)
                    if tries <= 2 and (exc.retry_after or 0) <= max_short_wait:
                        wait = max(1.0, exc.retry_after or 5.0)
                        say("%s is busy (429); waiting %.0fs, then asking again." % (provider.id, wait))
                        sleep(wait)
                        continue
                elif exc.timed_out:
                    # it went silent: never ask it again on this turn, and ask it last for SLOW_FOR_S
                    _SLOW[provider.id] = time.time() + SLOW_FOR_S
                elif exc.status >= 500 or exc.status == 0:
                    if tries <= 1:
                        say("%s failed (%s); asking once more." % (provider.id, str(exc)[:120]))
                        sleep(1.0)
                        continue
                nxt = order[i + 1].id if i + 1 < len(order) else ""
                if nxt:
                    say("Cannot use %s (%s) - switching to %s." % (provider.id, str(exc)[:160], nxt))
                break
    raise last or ModelError("no model answered")
