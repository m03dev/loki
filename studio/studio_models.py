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
    e = os.environ if env is None else env
    allow_paid = str(e.get("LOKI_ALLOW_PAID", "0")).strip() == "1"
    nim_base, nim_key = e.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"), e.get("NVIDIA_API_KEY", "")
    # the name NVIDIA really serves (a wrong one is HTTP 404 - the owner's Mac, 2026-10-17)
    nim_model = nim_models.resolve(e.get("NVIDIA_MODEL", DRIVER_MODEL), nim_models.cached(nim_base, nim_key))
    out = [
        Provider("nvidia", "DeepSeek V4.1 Flash on NVIDIA NIM", nim_base, nim_model, "NVIDIA_API_KEY", nim_key,
                 extra=thinking_fields()),
        Provider("openrouter", "DeepSeek V4.1 Flash on OpenRouter", e.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                 e.get("DEEPSEEK_41_MODEL", "deepseek/deepseek-v4.1-flash"), "OPENROUTER_API_KEY", e.get("OPENROUTER_API_KEY", "")),
        Provider("opencode-zen", "DeepSeek V4 Flash on OpenCode Zen (free)", e.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1"),
                 e.get("OPENCODE_ZEN_MODEL", "deepseek-v4-flash-free"), "OPENCODE_API_KEY", e.get("OPENCODE_API_KEY", "")),
        Provider("gemini", "Gemini Flash (free tier)", "https://generativelanguage.googleapis.com/v1beta/openai/",
                 e.get("GEMINI_MODEL", "gemini-2.5-flash"), "GEMINI_API_KEY", e.get("GEMINI_API_KEY", "")),
        Provider("groq", "Groq (free tier)", "https://api.groq.com/openai/v1", e.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
                 "GROQ_API_KEY", e.get("GROQ_API_KEY", "")),
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
    def __init__(self, text: str, status: int = 0, retry_after: float = 0.0, fail_over: bool = True):
        super().__init__(text)
        self.status, self.retry_after, self.fail_over = status, retry_after, fail_over


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


def request(provider: Provider, messages: list, tools: list | None = None, max_tokens: int = 8192,
            timeout: float = 180.0, opener=urllib.request.urlopen) -> dict:
    """One chat completion from one provider -> the reply message (dict). Raises ModelError."""
    body: dict = {"model": provider.model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    body.update(provider.extra or {})
    req = urllib.request.Request(provider.base_url.rstrip("/") + "/chat/completions", method="POST",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + provider.key, "Content-Type": "application/json",
                                          "User-Agent": "LOKI-Studio/1"})
    try:
        with opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")[:600]
        raise ModelError("%s answered HTTP %s: %s" % (provider.id, exc.code, " ".join(text.split())[:240]),
                         status=exc.code, retry_after=_retry_after(exc.headers, text)) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ModelError("%s did not answer (%s)" % (provider.id, getattr(exc, "reason", exc))) from exc
    except ValueError as exc:
        raise ModelError("%s sent something that is not JSON" % provider.id) from exc
    choices = data.get("choices") or []
    if not choices:
        raise ModelError("%s returned no choices" % provider.id)
    return dict(choices[0].get("message") or {})


def chat(messages: list, tools: list | None = None, chain_list: list | None = None, say=None, sleep=time.sleep,
         opener=urllib.request.urlopen, stop=None, max_short_wait: float = 20.0) -> tuple:
    """(provider, message, reasoning): ask the first ready provider; pace, wait out a short 429, fail over."""
    order = list(chain_list if chain_list is not None else chain())
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
