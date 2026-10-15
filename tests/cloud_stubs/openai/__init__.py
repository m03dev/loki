# Offline stand-in for running LOKI's suites without PyPI (cloud workspace only).
#
# It used to raise "no network" on every call, which made the local-model path look
# broken (test_offline_e2e could not reach the fake Ollama at all). It now speaks the
# OpenAI chat-completions wire format over plain urllib, so a request really reaches
# an OpenAI-compatible server (the fake Ollama, a llama.cpp server, ...) and the reply
# comes back with the same attribute shape the real SDK gives: choices[0].message
# .content / .tool_calls[i].function.name / .arguments, and .usage.
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request


class OpenAIError(Exception):
    pass


class APIStatusError(OpenAIError):
    def __init__(self, message="", response=None, body=None, status_code=0):
        super().__init__(message)
        self.message = message
        # The real SDK reads the status from the response object.
        self.status_code = status_code or int(getattr(response, "status_code", 0) or 0)
        self.body = body
        self.response = response


class APIConnectionError(OpenAIError):
    def __init__(self, message="connection error", request=None):
        super().__init__(message)
        self.message = message


class APITimeoutError(APIConnectionError):
    pass


class RateLimitError(APIStatusError):
    pass


class _Obj:
    """Attribute access over a dict, plus model_dump() like a pydantic SDK object."""

    def __init__(self, data: dict):
        self._data = data
        for key, value in data.items():
            setattr(self, key, _wrap(value))

    def model_dump(self, exclude_none: bool = False, **_kw) -> dict:
        if not exclude_none:
            return json.loads(json.dumps(self._data))
        return {k: v for k, v in json.loads(json.dumps(self._data)).items() if v is not None}

    def __getattr__(self, name):  # missing optional fields read as None, like the SDK
        if name.startswith("__"):
            raise AttributeError(name)
        return None


def _wrap(value):
    if isinstance(value, dict):
        return _Obj(value)
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


_SKIP = {"extra_body", "extra_headers", "timeout"}


class _Completions:
    def __init__(self, client):
        self._client = client

    def _post(self, body: dict):
        url = str(self._client.base_url or "").rstrip("/") + "/chat/completions"
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer %s" % (self._client.api_key or "")}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._client.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            cls = RateLimitError if exc.code == 429 else APIStatusError
            raise cls(text or str(exc), body=text, status_code=exc.code) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise APIConnectionError(str(exc)) from exc
        for choice in raw.get("choices") or []:
            msg = choice.setdefault("message", {})
            msg.setdefault("content", None)
            msg.setdefault("tool_calls", None)
            msg.setdefault("role", "assistant")
        raw.setdefault("usage", None)
        return _Obj(raw)

    async def create(self, **kw):
        body = {k: v for k, v in kw.items() if k not in _SKIP}
        body.update(kw.get("extra_body") or {})
        return await asyncio.to_thread(self._post, body)


class _Chat:
    def __init__(self, client):
        self.completions = _Completions(client)


class AsyncOpenAI:
    def __init__(self, *a, base_url=None, api_key=None, timeout=60.0, **k):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = float(timeout) if isinstance(timeout, (int, float)) else 60.0
        self.chat = _Chat(self)


class OpenAI(AsyncOpenAI):
    pass


__version__ = "0-stub-http"
