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

Owner 2026-10-25 19:36: "i thought this writing instead of call tool problem was fixed ... i dont want that to be a
thing anymore". It is not only DeepSeek: small and local models write calls as <tool_call> JSON, a bare {"name": ...}
object, a ```json fence, [TOOL_CALLS], or write_file(path=...) - and every new way LOKI ran a model (OpenCode,
DeepSeek Harness, sub-agents) had to remember the fix. So the proxy is now THE gate, for every format and every model:

    extract_calls(text, tool_names) -> (text left, [{"name", "arguments"}])  DSML, tool_harness.parse's formats
                                       (tool_call tags, JSON objects / lists / fences, [TOOL_CALLS]) and code-style
                                       calls - only names the request offered (DSML needs none)
    client_url(base_url)            -> the base URL every client in LOKI uses (loki.AsyncOpenAI goes through it):
                                       every OpenAI-compatible host, local Ollama included, except the first-party
                                       APIs that parse their own models' calls (LOKI_TOOLCALL_FIX = auto | all | off)

A request that offers no tools is passed through untouched; a reply that already has tool_calls is left alone.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler
from quiet_server import QuietHTTPServer

BAR = r"[｜|]{1,2}"
TAG = r"<\s*/?\s*" + BAR + r"\s*DSML\s*" + BAR
_ANY = re.compile(TAG + r"[^>]*>", re.I)
_BLOCK = re.compile(r"<\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*(?:tool_calls|function_calls| ?calls)\s*>(.*?)"
                    r"(?:<\s*/\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*(?:tool_calls|function_calls| ?calls)\s*>|$)", re.S | re.I)
_Q = r"[\"']"
_INVOKE = re.compile(r"<\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*invoke\s+name\s*=\s*" + _Q + r"(?P<name>[^\"']+)" + _Q +
                     r"\s*>(?P<body>.*?)"
                     r"(?:<\s*/\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*invoke\s*>|(?=<\s*" + BAR + r"\s*DSML\s*" + BAR +
                     r"\s*invoke\b)|$)", re.S | re.I)
# a parameter: double or single quotes, a string="true|false" flag or not, any other attributes ignored
_PARAM = re.compile(r"<\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*parameter\s+name\s*=\s*" + _Q + r"(?P<name>[^\"']+)" + _Q +
                    r"(?P<attrs>[^>]*)>(?P<value>.*?)<\s*/\s*" + BAR + r"\s*DSML\s*" + BAR + r"\s*parameter\s*>",
                    re.S | re.I)
_STRING_FLAG = re.compile(r"string\s*=\s*[\"'](true|false)[\"']", re.I)
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
            inner = inv.group("body")
            args = {}
            for m in _PARAM.finditer(inner):
                flag = _STRING_FLAG.search(m.group("attrs") or "")
                args[m.group("name")] = _value(m.group("value").strip("\n"), flag.group(1) if flag else None)
            if not args and inner.strip().startswith("{"):
                # the arguments written as one JSON object inside the invoke (2026-10-25: a make_3d reached the tool
                # without its image - a call LOKI read but whose arguments it lost)
                try:
                    blob = json.loads(inner.strip()[:inner.strip().rfind("}") + 1])
                    args = blob if isinstance(blob, dict) else {}
                except ValueError:
                    args = {}
            calls.append({"name": inv.group("name").strip(), "arguments": args})
    clean = _BLOCK.sub("", text)
    clean = _INVOKE.sub("", clean)
    clean = _ANY.sub("", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, calls


def _openai_calls(calls: list, start: int = 0) -> list:
    return [{"index": start + i, "id": "call_" + uuid.uuid4().hex[:20], "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for i, c in enumerate(calls)]


def extract_calls(text: str, names=None) -> tuple:
    """(text left, [{"name", "arguments"}]) for a tool call the model WROTE instead of making."""
    text = str(text or "")
    if not text.strip():
        return text, []
    if has_markup(text):
        clean, calls = parse(text)
        if calls:
            return clean, calls
        text = clean          # a bare or empty DSML tag is noise either way: it never reaches the agent
    names = [n for n in (names or []) if n]
    if not names:
        return text, []
    try:
        import tool_harness  # pylint: disable=import-outside-toplevel
        found, rest = tool_harness.parse(text, names)
    except Exception:  # noqa: BLE001
        found, rest = [], text
    if found:
        return rest, [{"name": n, "arguments": a} for n, a in found]
    try:
        import tool_guard  # pylint: disable=import-outside-toplevel
        found = tool_guard.parse_function_syntax(text, names) if "(" in text else []
    except Exception:  # noqa: BLE001
        found = []
    if found:
        rest = re.sub(r"```(?:python|py|tool_code)?\s*.*?```", "", text, flags=re.S)
        rest = "\n".join(ln for ln in rest.splitlines()
                         if not any(ln.strip().startswith(n + "(") for n, _a in found)).strip()
        return rest, [{"name": n, "arguments": a} for n, a in found]
    return text, []


KEEPALIVE_S = 8.0


def _wants_stream(body) -> bool:
    try:
        return bool(json.loads(body or b"{}").get("stream"))
    except (ValueError, AttributeError):
        return False


def request_tools(body) -> list:
    """The tool names a chat request offered (the calls a reply may make)."""
    try:
        data = json.loads(body) if isinstance(body, (bytes, str)) else (body or {})
    except ValueError:
        return []
    out = []
    for t in data.get("tools") or [] if isinstance(data, dict) else []:
        fn = (t or {}).get("function") if isinstance(t, dict) else None
        name = (fn or t or {}).get("name") if isinstance(fn or t, dict) else None
        if isinstance(name, str):
            out.append(name)
    return out


def fix_message(body: dict, names=None) -> dict:
    """A non-streamed chat completion: a call written in message.content -> message.tool_calls."""
    for ch in body.get("choices") or []:
        msg = ch.get("message") or {}
        if msg.get("tool_calls") or not isinstance(msg.get("content"), str):
            continue
        clean, calls = extract_calls(msg["content"], names)
        if not calls:
            if clean != msg["content"] and has_markup(msg["content"]):
                msg["content"] = clean or None          # a bare tag: dropped, the words kept
            continue
        msg["content"] = clean or None
        if calls:
            msg["tool_calls"] = list(msg.get("tool_calls") or []) + [
                {k: v for k, v in c.items() if k != "index"} for c in _openai_calls(calls)]
            ch["finish_reason"] = "tool_calls"
    return body


_OPENERS = ('<tool_call>', '<function_call>', '<|tool_call|>', '[tool_calls]', '<function=', '{"name"', "{'name'",
            '{"tool"', '{"function"', '{"tool_calls"', '[{"name"', '```json{"name"', '```json[{"name"', '```{"name"',
            '```json{"tool', '```tool_code', '```json{"function"')


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


class StreamFixer:
    """SSE chat-completion chunks in -> chunks out. Text is passed on live, except from a point where a written tool
    call may start (DSML, <tool_call>, {"name", a ```json fence, [TOOL_CALLS], `tool_name(` at a line start): held
    until it is clearly not a call (then let go) or the stream ends (then parsed into tool_calls)."""
    MAYBE = re.compile(r"^<\s*(?:[｜|]{1,2}\s*(?:D(?:S(?:M(?:L)?)?)?)?)?$", re.I)

    def __init__(self, names=None) -> None:
        self.names = [n for n in (names or []) if n]
        self.held = ""          # text held back (may be a call)
        self.dsml = False       # the held text IS a call: hold to the end
        self.native = 0         # tool calls the host did parse (our indexes come after them)
        self.template: dict = {}
        self.finish = None
        self.line_start = True
        self.openers = _OPENERS + tuple(n.lower() + "(" for n in self.names)

    def _verdict(self, buf: str, line_start: bool) -> str:
        """'call' (a call starts here), 'maybe' (cannot tell yet) or 'no'."""
        if _OPEN.match(buf):
            return "call"
        if self.MAYBE.match(buf):
            return "maybe"
        if not self.names:
            return "no"
        n = _norm(buf[:80])
        for op in self.openers:
            if op.endswith("(") and not line_start:
                continue
            if n.startswith(op):
                return "call"
            if op.startswith(n):
                return "maybe"
        return "no"

    def _release(self, text: str) -> str:
        """Feed text; return what can be shown now."""
        out = ""
        buf = self.held + text
        self.held = ""
        while buf:
            if self.dsml:
                self.held += buf
                return out
            i = 0
            while i < len(buf):
                c = buf[i]
                at_start = self.line_start if i == 0 else buf[i - 1] == "\n"
                if c in "<{[`" or (at_start and c.isalpha() and self.names):
                    break
                i += 1
            out += buf[:i]
            if i:
                self.line_start = buf[i - 1] == "\n"
            buf = buf[i:]
            if not buf:
                return out
            v = self._verdict(buf, self.line_start)
            if v == "call":
                self.dsml = True
                continue
            if v == "maybe":
                self.held = buf
                return out
            out += buf[0]
            self.line_start = buf[0] == "\n"
            buf = buf[1:]
            # a word at a line start that is not a tool name: let the whole word go
            if out and out[-1].isalpha():
                m = re.match(r"[\w-]*", buf)
                out += m.group(0)
                buf = buf[m.end():]
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
            clean, calls = extract_calls(held, self.names) if self.dsml else (held, [])
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
                if "chat/completions" in url and _wants_stream(body):
                    self._early_stream(req, request_tools(body))
                    return
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
                names = request_tools(body) if chat and body else []
                if chat and "text/event-stream" in ctype:
                    self._stream(resp, names)
                    return
                data = resp.read()
                if chat and "json" in ctype:
                    try:
                        data = json.dumps(fix_message(json.loads(data), names)).encode()
                    except ValueError:
                        pass
                self.send_response(getattr(resp, "status", 200) or 200)
                self.send_header("Content-Type", ctype or "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _early_stream(self, req, names) -> None:
                """A streamed chat: answer the client AT ONCE and keep the line alive while the host thinks
                (2026-10-25: NVIDIA's free DeepSeek took minutes to start; DeepSeek Harness hung up on the silent
                proxy - BrokenPipe - retried, and stalled for 15 minutes). Errors arrive as an SSE error event."""
                box: dict = {}
                done = threading.Event()

                def fetch() -> None:
                    try:
                        box["resp"] = urllib.request.urlopen(req, timeout=600)  # noqa: S310
                    except urllib.error.HTTPError as exc:
                        box["resp"] = exc
                    except Exception as exc:  # noqa: BLE001
                        box["error"] = str(exc)
                    done.set()
                threading.Thread(target=fetch, daemon=True).start()
                try:
                    self._headers()
                    while not done.wait(KEEPALIVE_S):
                        self._chunk(b": keep-alive\n\n")
                    resp = box.get("resp")
                    status = getattr(resp, "status", None) or getattr(resp, "code", 0)
                    ctype = resp.headers.get("Content-Type", "") if resp is not None else ""
                    if resp is None or status != 200 or "text/event-stream" not in ctype:
                        raw = resp.read() if resp is not None else b""
                        try:
                            err = json.loads(raw).get("error") if raw else None
                        except (ValueError, AttributeError):
                            err = None
                        if status == 200 and raw and not err:     # a host that answered whole: stream it as one
                            try:
                                whole = fix_message(json.loads(raw), names)
                                ch = (whole.get("choices") or [{}])[0]
                                msg = ch.get("message") or {}
                                delta = {k: v for k, v in msg.items() if k in ("content", "tool_calls") and v}
                                for i, tc in enumerate(delta.get("tool_calls") or []):
                                    tc["index"] = i
                                self._event({"id": whole.get("id", "x"), "object": "chat.completion.chunk",
                                             "choices": [{"index": 0, "delta": delta,
                                                          "finish_reason": ch.get("finish_reason") or "stop"}]})
                            except (ValueError, AttributeError, IndexError):
                                pass
                        else:
                            self._event({"error": err or {"message": "LOKI proxy: %s" % (
                                box.get("error") or "host answered %s: %s" % (status, raw[:300].decode("utf-8", "replace")))}})
                        self._event("[DONE]")
                        self._chunk(b"")
                        return
                    self._pump(resp, names)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _headers(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

            def _chunk(self, raw: bytes) -> None:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(raw), raw))
                self.wfile.flush()

            def _event(self, obj) -> None:
                self._chunk(("data: %s\n\n" % (obj if isinstance(obj, str) else json.dumps(obj))).encode())

            def _stream(self, resp, names=None) -> None:
                self._headers()
                self._pump(resp, names)

            def _pump(self, resp, names=None) -> None:
                def send(obj) -> None:
                    raw = ("data: %s\n\n" % (obj if isinstance(obj, str) else json.dumps(obj))).encode()
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(raw), raw))
                    self.wfile.flush()
                fx = StreamFixer(names)
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

        self.server = QuietHTTPServer(("127.0.0.1", 0), Handler)
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


FIRST_PARTY = ("api.deepseek.com", "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com")


def fix_mode(env=None) -> str:
    import os  # pylint: disable=import-outside-toplevel
    v = str((env if env is not None else os.environ).get("LOKI_TOOLCALL_FIX", "auto")).strip().lower()
    return v if v in ("auto", "all", "off") else "auto"


def _is_ours(base: str) -> bool:
    p = _PROXY.get("p")
    return bool(p) and base.startswith("http://127.0.0.1:%d/" % p.port)


def needs_fix(p: dict) -> bool:
    """Every OpenAI-compatible host goes through the fix (local Ollama included) - except the first-party APIs that
    parse their own models' calls, unless LOKI_TOOLCALL_FIX=all; never with LOKI_TOOLCALL_FIX=off."""
    base = str(p.get("base_url") or "").strip()
    low = base.lower()
    mode = fix_mode()
    if mode == "off" or not low.startswith("http") or _is_ours(base):
        return False
    return mode == "all" or not any(h in low for h in FIRST_PARTY)


def client_url(base_url):
    """The base URL a model client should use: through the fix when the host needs it."""
    if not base_url:
        return base_url
    try:
        return proxy().url_for(str(base_url)) if needs_fix({"base_url": str(base_url)}) else base_url
    except Exception:  # noqa: BLE001 - the fix must never stop a request: go direct
        return base_url


def wrap(providers: dict) -> dict:
    """The providers OpenCode / DeepSeek Harness get: every one that needs it pointed at the fix."""
    out = {}
    for name, p in providers.items():
        if needs_fix(p):
            p = {**p, "base_url": proxy().url_for(str(p["base_url"])), "dsml_fixed": True, "upstream": str(p["base_url"])}
        out[name] = p
    return out
