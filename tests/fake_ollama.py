"""A tiny fake Ollama for offline tests: the native API Loki uses for setup, and an
OpenAI-compatible /v1/chat/completions that behaves like a small tool-calling model.

    server = FakeOllama(models=["qwen3.5:9b-q4_K_M"]); server.start(); ...; server.stop()

The chat endpoint: when the conversation has no tool result since the last user message,
it calls write_file on the path named after "file " in the request (default
notes/out.txt); once a tool result is there, it answers "DONE: wrote <path>". Every reply
carries a `usage` block. Requests are recorded in `server.calls`.
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self, models: list[str] | None = None, port: int = 11434, tools: bool = True,
                 pullable: list[str] | None = None, version: str = "") -> None:
        self.models = {name: 6.6e9 for name in (models or [])}
        self.version = version          # GET /api/version answers it when set (404 otherwise, like old servers)
        self.loaded_context: dict = {}  # model -> context_length that /api/ps reports
        self.port = port
        self.tools = tools
        self.pullable = set(pullable or [])
        self.calls: list[tuple[str, dict]] = []
        self.created: dict[str, dict] = {}
        self.server: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------------ chat logic
    def reply(self, body: dict) -> dict:
        messages = body.get("messages", [])
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        tool_after = any(m.get("role") == "tool" for m in messages[last_user + 1:])
        text = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
        match = re.findall(r"file ([\w./-]+)", text)
        path = match[-1] if match else "notes/out.txt"
        usage = {"prompt_tokens": 1200 + len(json.dumps(body.get("tools", []))) // 4, "completion_tokens": 40,
                 "total_tokens": 1240}
        if body.get("tools") and not tool_after:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_%d" % len(self.calls), "type": "function",
                "function": {"name": "write_file", "arguments": json.dumps({"filename": path, "content": "hello from the fake model\n"})}}]}
        else:
            message = {"role": "assistant", "content": "DONE: wrote %s" % path}
        return {"id": "chatcmpl-fake", "object": "chat.completion", "created": int(time.time()),
                "model": body.get("model", ""), "choices": [{"index": 0, "message": message,
                                                              "finish_reason": "stop"}], "usage": usage}

    # ------------------------------------------------------------------ server
    def start(self) -> "FakeOllama":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a) -> None:
                return

            def _json(self, status: int, payload) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    return json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return {}

            def do_GET(self) -> None:  # noqa: N802
                fake.calls.append(("GET " + self.path, {}))
                if self.path == "/api/version" and fake.version:
                    self._json(200, {"version": fake.version})
                elif self.path == "/api/ps":
                    self._json(200, {"models": [{"name": n, "context_length": c} for n, c in fake.loaded_context.items()]})
                elif self.path == "/api/tags":
                    self._json(200, {"models": [{"name": n, "size": int(s), "details": {
                        "family": n.split(":")[0], "parameter_size": "9B"}} for n, s in fake.models.items()]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                body = self._body()
                fake.calls.append(("POST " + self.path, body))
                if self.path == "/api/show":
                    name = body.get("model", "")
                    if name not in fake.models and name + ":latest" not in fake.models:
                        return self._json(404, {"error": "model '%s' not found" % name})
                    caps = ["completion"] + (["tools"] if fake.tools else [])
                    made = fake.created.get(name) or fake.created.get(name.split(":")[0]) or {}
                    params = "".join("%s %s\n" % kv for kv in (made.get("parameters") or {}).items())
                    return self._json(200, {"capabilities": caps, "parameters": params,
                                            "model_info": {"qwen3.context_length": 40960}})
                if self.path == "/api/create":
                    fake.created[body.get("model", "")] = body
                    fake.models[body.get("model", "") + ":latest"] = fake.models.get(body.get("from", ""), 1e9)
                    return self._json(200, {"status": "success"})
                if self.path == "/api/generate":
                    return self._json(200, {"done": True})
                if self.path == "/api/pull":
                    tag = body.get("model", "")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    if tag not in fake.pullable:
                        self.wfile.write(json.dumps({"error": "pull model manifest: file does not exist"}).encode() + b"\n")
                        return
                    for done in (0, 50, 100):
                        self.wfile.write(json.dumps({"status": "pulling", "total": 100, "completed": done}).encode() + b"\n")
                    fake.models[tag] = 5e9
                    self.wfile.write(json.dumps({"status": "success"}).encode() + b"\n")
                    return
                if self.path == "/v1/chat/completions":
                    model = body.get("model", "")
                    if model not in fake.models and model + ":latest" not in fake.models:
                        return self._json(404, {"error": {"message": "model '%s' not found" % model}})
                    answer = fake.reply(body)
                    # A scripted reply may ask for an HTTP error: {"__status__": 400, ...}.
                    status = int(answer.pop("__status__", 200)) if isinstance(answer, dict) else 200
                    return self._json(status, answer)
                self._json(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()

    def chat_requests(self) -> list[dict]:
        return [b for p, b in self.calls if p == "POST /v1/chat/completions"]
