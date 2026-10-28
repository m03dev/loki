"""The Mac uses the PC's local model (owner 2026-10-28: "why hasnt the mac asked for the windows local to help").
End to end on this machine: a stand-in Ollama (the PC's model), the real signed peer server with the real /peer/llm
route and the real peer_link callback, and the Mac's loopback adapter that LOKI and OpenCode talk to. Under a minute.

    python tests/test_peer_llm.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-peerllm-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PEER_SECRET"] = "s" * 40
os.environ["LOKI_PEER_NAME"] = "mac"
os.environ.pop("LOKI_PEERS", None)
PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


# ----------------------------------------------------------------------------- the PC's Ollama (a stand-in)
SEEN: list = []


class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._send({"object": "list", "data": [{"id": "qwen3:8b"}]})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        SEEN.append(body)
        msg = {"role": "assistant", "content": "PC here: " + body["messages"][-1]["content"]}
        if body.get("tools"):
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "read_file", "arguments": "{\"path\": \"a.txt\"}"}}]}
        self._send({"id": "x", "object": "chat.completion", "model": body["model"],
                    "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]})


ollama = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
threading.Thread(target=ollama.serve_forever, daemon=True).start()
OLLAMA = "http://127.0.0.1:%d/v1" % ollama.server_address[1]

import peers  # noqa: E402
import peer_link  # noqa: E402
import peer_llm  # noqa: E402
import offload  # noqa: E402


class Cfg:
    def __init__(self, base_url, api_key="", model=""):
        self.base_url, self.api_key, self.model = base_url, api_key, model


PC_AGENT = type("PCAgent", (), {"MODELS": {"local": Cfg(OLLAMA, "ollama", "qwen3:8b")}, "ModelConfig": Cfg})()
check("the PC offers its model when its local model is up", peer_llm.can_serve(PC_AGENT) == (True, ""))
check("... and says why not when no model server answers",
      not peer_llm.can_serve(type("A", (), {"MODELS": {"local": Cfg("http://127.0.0.1:9/v1")}})())[0])

# the real peer server, with the real callback from peer_link
check("peer_link hands /peer/llm to peer_llm.serve", '"llm": lambda origin, data: __import__("peer_llm").serve(agent, origin, data)'
      in (REPO / "engine" / "peer_link.py").read_text(encoding="utf-8"))
HELLO = {"name": "pc", "work": ["image", "llm"]}
server = peers.PeerServer({"hello": lambda: HELLO, "llm": lambda origin, data: peer_llm.serve(PC_AGENT, origin, data)},
                          host="127.0.0.1", port_number=0).start()
os.environ["LOKI_PEERS"] = "pc=http://127.0.0.1:%d" % server.address[1]
offload._HELLO.clear()

check("the Mac finds the PC that offers its model", (peer_llm.helper_peer() or {}).get("name") == "pc")
code, ans = peer_llm.forward({"messages": [{"role": "user", "content": "hi"}], "model": "anything", "max_tokens": 99999})
check("a request goes over the signed link and the PC's model answers", code == 200
      and ans["choices"][0]["message"]["content"] == "PC here: hi", (code, ans))
check("the PC picks its own model and caps the length (the Mac never picks a model file or a URL)",
      SEEN[-1]["model"] == "qwen3:8b" and SEEN[-1]["max_tokens"] == peer_llm.MAX_TOKENS and SEEN[-1]["stream"] is False)

# the Mac's adapter: plain OpenAI for LOKI's loop and OpenCode
base = peer_llm.start_adapter()


def post(body):
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.headers.get("Content-Type"), r.read().decode()


ct, txt = post({"model": "pc-local", "messages": [{"role": "user", "content": "draw a fox"}]})
check("the Mac's loopback adapter answers OpenAI JSON", "json" in ct and json.loads(txt)["choices"][0]["message"]["content"] == "PC here: draw a fox", txt)
ct, txt = post({"model": "pc-local", "stream": True, "messages": [{"role": "user", "content": "x"}],
                "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]})
chunk = json.loads(txt.split("data: ", 1)[1].split("\n", 1)[0])
check("a streaming client (OpenCode) gets the whole answer as one SSE chunk, tool calls included",
      "event-stream" in ct and txt.rstrip().endswith("[DONE]")
      and chunk["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "read_file"
      and chunk["choices"][0]["delta"]["tool_calls"][0]["index"] == 0, txt)
with urllib.request.urlopen(base + "/models", timeout=10) as r:
    check("the adapter lists pc-local while the PC offers it", json.loads(r.read())["data"][0]["id"] == "pc-local")

# the PC stops offering it -> the route says so and LOKI fails over
HELLO["work"] = ["image"]
offload._HELLO.clear()
try:
    post({"model": "pc-local", "messages": [{"role": "user", "content": "x"}]})
    check("with the PC's model gone the adapter answers 503 (the routes fail over)", False)
except urllib.error.HTTPError as exc:
    check("with the PC's model gone the adapter answers 503 (the routes fail over)", exc.code == 503)

# register: only on a light machine with a linked machine, before this machine's own local model
fake = type("L", (), {"MODELS": {}, "ModelConfig": Cfg, "SMART_ORDER": ("nvidia", "deepseek", "local", "local-hermes"),
                      "LOCAL_PROVIDERS": ("local", "local-hermes")})()
os.environ["LOKI_MACHINE_ROLE"] = "main"
check("the PC itself never adds pc-local", not peer_llm.register(fake) and "pc-local" not in fake.MODELS)
os.environ["LOKI_MACHINE_ROLE"] = "light"
check("the Mac adds pc-local right before its own local model", peer_llm.register(fake)
      and fake.SMART_ORDER == ("nvidia", "deepseek", "pc-local", "local", "local-hermes")
      and fake.MODELS["pc-local"].base_url == base, fake.SMART_ORDER)
check("the PC's hello lists 'llm' only from its real model check (offload._serves)",
      "peer_llm.can_serve" in (REPO / "engine" / "offload.py").read_text(encoding="utf-8"))
check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
