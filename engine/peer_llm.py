"""The PC's local model, used from the Mac (owner 2026-10-28: "why hasnt the mac asked for the windows local to help or
any of the services over there? should that be a thing" - yes: the Mac is not the powerhouse, owner's rule 7).

Before this, a Mac job that fell off the cloud ran the Mac's own 9B model - on the 16 GB Mac, beside Blender and the
window - while the PC (RTX 3070 Ti, on 24/7) sat idle. Pictures, 3D, video and Blender work already went to the PC
(engine/offload.py); language models did not.

    the PC     POST /peer/llm {body}  (signed peer link, engine/peers.py): one OpenAI chat-completions request run on
               ITS local model (Ollama); the caller picks the messages, the tools and max_tokens - never the server,
               the model file or a URL. Listed in the PC's hello as the work kind "llm" when its local model is up.
    the Mac    a loopback adapter (127.0.0.1, this process only) that speaks the OpenAI API and forwards each request
               over the peer link, so LOKI's loop, OpenCode (through engine/dsml_proxy.py) and the local agent all use
               "pc-local" like any other model route. Registered as the provider "pc-local" on a light machine with a
               linked machine; it answers 503 when the PC is not reachable, and the routes fail over as usual.

Streaming: the peer link carries whole answers; a client that asked to stream gets the whole answer as one SSE chunk
(dsml_proxy already does that for OpenCode).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from typing import Any

from quiet_server import QuietHTTPServer

MAX_TOKENS = 8192
TIMEOUT_S = 900.0
_ADAPTER: dict = {}


# ----------------------------------------------------------------------------- the PC's side
def local_base(agent: Any) -> str:
    try:
        return str(agent.MODELS["local"].base_url).rstrip("/")
    except Exception:  # noqa: BLE001
        return os.environ.get("LOKI_LOCAL_BASE", "http://127.0.0.1:11434/v1").rstrip("/")


def local_model(agent: Any) -> str:
    try:
        if hasattr(agent, "resolve_local"):
            name = (agent.resolve_local() or {}).get("name") or ""
            if name:
                return str(name)
        return str(agent.MODELS["local"].model)
    except Exception:  # noqa: BLE001
        return ""


def can_serve(agent: Any = None) -> tuple:
    """(True, "") when this machine's local model can answer for another machine, else (False, why)."""
    if str(os.environ.get("LOKI_PEER_LLM_SERVE", "on")).lower() in ("off", "0", "no"):
        return False, "serving the local model is off here (LOKI_PEER_LLM_SERVE=off)"
    base = local_base(agent) if agent is not None else os.environ.get("LOKI_LOCAL_BASE", "http://127.0.0.1:11434/v1")
    try:
        with urllib.request.urlopen(urllib.request.Request(base.rstrip("/") + "/models"), timeout=1.5) as r:
            data = json.loads(r.read() or b"{}")
        return (True, "") if (data.get("data") or data.get("models")) else (False, "no local model is loaded here")
    except Exception as exc:  # noqa: BLE001
        return False, "no local model server here (%s)" % str(exc)[:80]


def serve(agent: Any, origin: str, data: dict) -> tuple:
    """POST /peer/llm on the PC. Returns (code, the model's JSON answer)."""
    ok, why = can_serve(agent)
    if not ok:
        return 503, {"ok": False, "error": why}
    body = dict((data or {}).get("body") or {})
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return 400, {"ok": False, "error": "messages are needed"}
    req_body = {"model": local_model(agent), "messages": msgs, "stream": False,
                "max_tokens": max(16, min(int(body.get("max_tokens") or 2048), MAX_TOKENS))}
    for k in ("tools", "tool_choice", "temperature", "top_p", "stop", "response_format"):
        if k in body:
            req_body[k] = body[k]
    req = urllib.request.Request(local_base(agent) + "/chat/completions", data=json.dumps(req_body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:   # noqa: S310 - this machine's own model server
            answer = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"ok": False, "error": "the local model answered %s: %s" % (exc.code, exc.read()[:200].decode("utf-8", "replace"))}
    except Exception as exc:  # noqa: BLE001
        return 502, {"ok": False, "error": "the local model did not answer: %s" % str(exc)[:200]}
    print("[peer-llm] answered %s with %s in %.1f s" % (origin, req_body["model"], time.time() - started), flush=True)
    return 200, {"ok": True, "answer": answer, "model": req_body["model"], "machine": _me()}


def _me() -> str:
    try:
        import peers  # pylint: disable=import-outside-toplevel
        return peers.my_name()
    except Exception:  # noqa: BLE001
        return ""


# ----------------------------------------------------------------------------- the Mac's side
def helper_peer(call=None) -> dict | None:
    """The linked machine whose hello lists "llm" (engine/offload.py hello cache), or None."""
    try:
        import offload  # pylint: disable=import-outside-toplevel
        import peers  # pylint: disable=import-outside-toplevel
        for peer in peers.peers():
            hello, _err = offload.hello_of(peer, call)
            if hello and "llm" in (hello.get("work") or []):
                return peer
    except Exception:  # noqa: BLE001
        return None
    return None


def forward(body: dict, call=None, peer: dict | None = None) -> tuple:
    """One chat-completions request to the PC. Returns (code, OpenAI JSON or an error JSON)."""
    peer = peer or helper_peer(call)
    if peer is None:
        return 503, {"error": {"message": "no linked machine offers its local model right now"}}
    import peers  # pylint: disable=import-outside-toplevel
    try:
        out = (call or peers.call)(peer, "POST", "/peer/llm", {"body": body}, timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - the routes fail over
        return 503, {"error": {"message": "%s did not answer: %s" % (peer.get("name"), str(exc)[:200])}}
    if not out.get("ok"):
        return 503, {"error": {"message": str(out.get("error") or "the other machine's model failed")}}
    return 200, out.get("answer") or {}


def _sse(answer: dict) -> bytes:
    ch = (answer.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    delta = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v}
    for i, tc in enumerate(delta.get("tool_calls") or []):
        tc.setdefault("index", i)
    chunk = {"id": answer.get("id", "pc"), "object": "chat.completion.chunk", "model": answer.get("model", "pc-local"),
             "choices": [{"index": 0, "delta": delta, "finish_reason": ch.get("finish_reason") or "stop"}]}
    return ("data: %s\n\ndata: [DONE]\n\n" % json.dumps(chunk)).encode()


def start_adapter(call=None) -> str:
    """The loopback OpenAI endpoint for "pc-local" (once per process). Returns its base URL."""
    if _ADAPTER.get("url"):
        return _ADAPTER["url"]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _json(self, code: int, obj: dict) -> None:
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/").endswith("/models"):
                up = helper_peer(call) is not None
                return self._json(200, {"object": "list", "data": [{"id": "pc-local", "object": "model"}] if up else []})
            return self._json(404, {"error": {"message": "not found"}})

        def do_POST(self):  # noqa: N802
            if not self.path.rstrip("/").endswith("/chat/completions"):
                return self._json(404, {"error": {"message": "not found"}})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"error": {"message": "bad JSON"}})
            stream = bool(body.pop("stream", False))
            body.pop("stream_options", None)
            code, answer = forward(body, call)
            if code != 200 or not stream:
                return self._json(code, answer)
            data = _sse(answer)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = QuietHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="loki-pc-llm").start()
    _ADAPTER.update(url="http://127.0.0.1:%d/v1" % server.server_address[1], server=server)
    return _ADAPTER["url"]


def register(agent: Any) -> bool:
    """On a light machine (the Mac) with a linked machine: add the provider "pc-local" (the PC's local model, through
    the adapter), right before this machine's own local models in Smart's order. Returns True when added."""
    try:
        import offload  # pylint: disable=import-outside-toplevel
        import peers  # pylint: disable=import-outside-toplevel
        if offload.role() != "light" or not peers.peers() or "pc-local" in agent.MODELS:
            return False
        if str(os.environ.get("LOKI_PEER_LLM", "on")).lower() in ("off", "0", "no"):
            return False
    except Exception:  # noqa: BLE001
        return False
    url = start_adapter()
    agent.MODELS["pc-local"] = agent.ModelConfig(base_url=url, api_key="peer", model="pc-local")
    order = list(agent.SMART_ORDER)
    at = next((i for i, n in enumerate(order) if n in agent.LOCAL_PROVIDERS), len(order))
    agent.SMART_ORDER = tuple(order[:at] + ["pc-local"] + order[at:])
    return True
