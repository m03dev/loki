"""DeepSeek 4.1 tool calls, turned back into real tool calls (owner 2026-10-25: LOKI answered with "<｜DSML｜ calls>"
lines and "No shell/Bash tool is available" - its commands were never run).

The cause: DeepSeek V4.1 writes tool calls in its own markup, and 4.1 renamed the block - V4 writes
<｜DSML｜tool_calls>, V4.1 writes <｜DSML｜ calls> (vLLM tokenizers/deepseek_v41_encoding.py: tool_calls_block_name =
" calls"). A host still parsing the V4 way (NVIDIA NIM, OpenRouter's providers) does not see the 4.1 block, so the
calls come back to the agent as plain TEXT: nothing runs, and the model decides it has no shell. DeepSeek's own API
parses it right - that is why other setups "just work".

The fix, in one place, no second request: a tiny local proxy between the agent (OpenCode) and such a host. Requests
pass through untouched; in the answer, DSML markup in the text (both block names, full-width or ASCII bars, with or
without newlines) is parsed into OpenAI tool_calls - streamed or not - and the markup never reaches the agent.

    wrap(providers) -> the same providers, DeepSeek ones not on api.deepseek.com pointed at the proxy (started once)
    parse(text) -> (text without the markup, [{"name", "arguments": dict}])
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BAR = r"[｜|]{1,2}"
TAG = r"<\s*/?\s*" + BAR + r"\s*DSML\s*" + BAR
_ANY = re.compile(TAG + r"[^>]*>", re.I)
_BLOCK = re.compile(r"<\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*(?:tool_calls|function_calls| ?calls)\s*>(.*?)"
                    r"(?:<\s*/\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*(?:tool_calls|function_calls| ?calls)\s*>|$)", re.S | re.I)
_INVOKE = re.compile(r"<\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*invoke\s+name\s*=\s*\"([^\"]+)\"\s*>(.*?)"
                     r"(?:<\s*/\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*invoke\s*>|(?=<\s*" + BAR + r"\s*DSML\s*" + BAR +
                     r"\s*invoke\b)|$)", re.S | re.I)
_PARAM = re.compile(r"<\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*parameter\s+name\s*=\s*\"([^\"]+)\""
                    r"(?:\s+string\s*=\s*\"(true|false)\")?\s*>(.*?)<\s*/\s*" + BAR + r"\s*DSML\s*" + BAR +
                    r"\s*parameter\s*>", re.S | re.I)
_OPEN = re.compile(r"<\s*" + BAR + r"\s*DSML", re.I)
OFFICIAL = ("api.deepseek.com",)


def has_markup(text: str) -> bool:
    return bool(_ANY.search(str(text or "")))


def _value(raw: str, is_string: str | None):
    if (is_string or "").lower() == "true":
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse(text: str) -> tuple:
    """(the text without DSML markup, [{"name", "arguments"}]) - invokes found anywhere, block or not."""
    text = str(text or "")
    calls = []
    bodies = [m.group(1) for m in _BLOCK.finditer(text)] or ([text] if _INVOKE.search(text) else [])
    for body in bodies:
        for inv in _INVOKE.finditer(body):
            args = {m.group(1): _value(m.group(3).strip("\n"), m.group(2)) for m in _PARAM.finditer(inv.group(2))}
            calls.append({"name": inv.group(1).strip(), "arguments": args})
    clean = _BLOCK.sub("", text)
    clean = _INVOKE.sub("", clean)
    clean = _ANY.sub("", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, calls


def _openai_calls(calls: list, start: int = 0) -> list:
    return [{"index": start + i, "id": "call_" + uuid.uuid4().hex[:20], "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for i, c in enumerate(calls)]


def fix_message(body: dict) -> dict:
    """A non-streamed chat completion: DSML in message.content -> message.tool_calls."""
    for ch in body.get("choices") or []:
        msg = ch.get("message") or {}
        if not has_markup(msg.get("content") or ""):
            continue
        clean, calls = parse(msg["content"])
        msg["content"] = clean or None
        if calls:
            msg["tool_calls"] = list(msg.get("tool_calls") or []) + [
                {k: v for k, v in c.items() if k != "index"} for c in _openai_calls(calls)]
            ch["finish_reason"] = "tool_calls"
    return body


class StreamFixer:
    """SSE chat-completion chunks in -> chunks out. Text is passed on live, except from a '<' that may start DSML:
    held until it is clearly not markup (then let go) or the stream ends (then parsed into tool_calls)."""
    MAYBE = re.compile(r"^<\s*(?:[｜|]{1,2}\s*(?:D(?:S(?:M(?:L)?)?)?)?)?$", re.I)

    def __init__(self) -> None:
        self.held = ""          # text held back (may be DSML)
        self.dsml = False       # the held text IS markup: hold to the end
        self.native = 0         # tool calls the host did parse (our indexes come after them)
        self.template: dict = {}
        self.finish = None

    def _release(self, text: str) -> str:
        """Feed text; return what can be shown now."""
        out = ""
        buf = self.held + text
        self.held = ""
        while buf:
            if self.dsml:
                self.held += buf
                return out
            i = buf.find("<")
            if i < 0:
                return out + buf
            out += buf[:i]
            buf = buf[i:]
            if _OPEN.match(buf):
                self.dsml = True
                continue
            if self.MAYBE.match(buf):     # "<｜DS" so far: wait for more
                self.held = buf
                return out
            out += buf[0]
            buf = buf[1:]
        return out

    def chunk(self, data: dict) -> list:
        """One upstream chunk -> the chunks to send on (0, 1 or more)."""
        if not self.template and data.get("id"):
            self.template = {k: data.get(k) for k in ("id", "object", "created", "model") if k in data}
        out = []
        for ch in data.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("tool_calls"):
                self.native = max(self.native, 1 + max(int(t.get("index", 0) or 0) for t in delta["tool_calls"]))
            if isinstance(delta.get("content"), str):
                delta["content"] = self._release(delta["content"])
            if ch.get("finish_reason"):
                self.finish = ch["finish_reason"]
                ch["finish_reason"] = None
                if not delta.get("content") and not delta.get("tool_calls") and not delta.get("reasoning_content"):
                    ch["_drop"] = True
            if delta.get("content") == "" and not ch.get("_drop"):
                delta.pop("content")
        data["choices"] = [c for c in data.get("choices") or [] if not c.pop("_drop", False)
                           and (c.get("delta") or c.get("finish_reason"))]
        if data["choices"] or data.get("usage"):
            out.append(data)
        return out

    def end(self) -> list:
        """The stream is over: held markup -> tool_calls; then the finish."""
        base = dict(self.template or {"object": "chat.completion.chunk"})
        out = []
        held, self.held = self.held, ""
        if held:
            clean, calls = parse(held) if self.dsml else (held, [])
            if clean:
                out.append({**base, "choices": [{"index": 0, "delta": {"content": clean}, "finish_reason": None}]})
            if calls:
                out.append({**base, "choices": [{"index": 0, "delta": {"tool_calls": _openai_calls(calls, self.native)},
                                                 "finish_reason": None}]})
                self.finish = "tool_calls"
        out.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": self.finish or "stop"}]})
        return out


# ------------------------------------------------------------------ the proxy
class _Proxy:
    def __init__(self) -> None:
        self.upstreams: dict = {}
        self.lock = threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # quiet
                pass

            def _go(self, method: str) -> None:
                parts = self.path.split("/", 3)          # "", "u", "<n>", "rest"
                base = proxy.upstreams.get(parts[2]) if len(parts) > 2 and parts[1] == "u" else None
                if not base:
                    self.send_error(404)
                    return
                url = base.rstrip("/") + "/" + (parts[3] if len(parts) > 3 else "")
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else None
                headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in ("host", "content-length", "connection", "accept-encoding")}
                req = urllib.request.Request(url, data=body, method=method, headers=headers)
                try:
                    resp = urllib.request.urlopen(req, timeout=600)  # noqa: S310 - the provider's own URL
                except urllib.error.HTTPError as exc:
                    resp = exc
                except Exception as exc:  # noqa: BLE001
                    data = json.dumps({"error": {"message": "LOKI proxy: %s" % exc}}).encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                ctype = resp.headers.get("Content-Type", "")
                chat = "chat/completions" in url and getattr(resp, "status", 200) == 200
                if chat and "text/event-stream" in ctype:
                    self._stream(resp)
                    return
                data = resp.read()
                if chat and "json" in ctype:
                    try:
                        data = json.dumps(fix_message(json.loads(data))).encode()
                    except ValueError:
                        pass
                self.send_response(getattr(resp, "status", 200) or 200)
                self.send_header("Content-Type", ctype or "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, resp) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def send(obj) -> None:
                    raw = ("data: %s\n\n" % (obj if isinstance(obj, str) else json.dumps(obj))).encode()
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(raw), raw))
                    self.wfile.flush()
                fx = StreamFixer()
                ended = False
                try:
                    for line in resp:
                        line = line.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            for c in fx.end():
                                send(c)
                            ended = True
                            send("[DONE]")
                            break
                        try:
                            data = json.loads(payload)
                        except ValueError:
                            continue
                        for c in fx.chunk(data):
                            send(c)
                    if not ended:
                        for c in fx.end():
                            send(c)
                        send("[DONE]")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):  # noqa: N802
                self._go("POST")

            def do_GET(self):  # noqa: N802
                self._go("GET")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True, name="loki-dsml-proxy").start()

    def url_for(self, base: str) -> str:
        with self.lock:
            for k, v in self.upstreams.items():
                if v == base:
                    return "http://127.0.0.1:%d/u/%s" % (self.port, k)
            k = str(len(self.upstreams) + 1)
            self.upstreams[k] = base
            return "http://127.0.0.1:%d/u/%s" % (self.port, k)


_PROXY: dict = {}


def proxy() -> _Proxy:
    if "p" not in _PROXY:
        _PROXY["p"] = _Proxy()
    return _PROXY["p"]


def needs_fix(p: dict) -> bool:
    base, model = str(p.get("base_url") or "").lower(), str(p.get("model") or "").lower()
    return "deepseek" in model and base.startswith("http") and not any(h in base for h in OFFICIAL) \
        and not base.startswith("http://127.0.0.1")


def wrap(providers: dict) -> dict:
    """DeepSeek models on a host other than DeepSeek's own API go through the fixing proxy."""
    out = {}
    for name, p in providers.items():
        if needs_fix(p):
            p = {**p, "base_url": proxy().url_for(str(p["base_url"])), "dsml_fixed": True}
        out[name] = p
    return out
