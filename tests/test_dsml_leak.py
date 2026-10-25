"""DeepSeek 4.1's tool calls turned back into real ones (engine/dsml_proxy.py). Owner 2026-10-25 11:55: LOKI answered
with "<｜DSML｜ calls>" lines and "No shell/Bash tool is available" - V4.1 renamed its tool-call block (V4
"tool_calls", V4.1 " calls"), the host parsed it the V4 way, so the calls came back as text and never ran.

A fake host on 127.0.0.1 answers like NVIDIA / OpenRouter did - the 4.1 markup in the TEXT - streamed and not. Through
the proxy the agent gets OpenAI tool_calls (bash {"command": "git init demo"}), the text before them live, no tags,
finish_reason tool_calls; plain answers and '<' in normal text pass through untouched; one request upstream (no
retry). wrap() sends only DeepSeek-not-on-DeepSeek's-API through it. Under a minute.

    python tests/test_dsml_leak.py
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
os.environ["LOKI_DATA"] = tempfile.mkdtemp(prefix="loki-dsml-")
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


import dsml_proxy  # noqa: E402
import opencode_engine  # noqa: E402

V41 = ("I'll make the repo.\n<｜DSML｜ calls>\n<｜DSML｜ invoke name=\"bash\">\n"
       "<｜DSML｜ parameter name=\"command\" string=\"true\">git init demo</｜DSML｜ parameter>\n"
       "<｜DSML｜ parameter name=\"timeout\" string=\"false\">30</｜DSML｜ parameter>\n</｜DSML｜ invoke>\n"
       "<｜DSML｜ invoke name=\"read\">\n<｜DSML｜ parameter name=\"filePath\" string=\"true\">README.md</｜DSML｜ parameter>\n"
       "</｜DSML｜ invoke>\n</｜DSML｜ calls>")
clean, calls = dsml_proxy.parse(V41)
check("V4.1 markup (<｜DSML｜ calls>) parses: bash {command, timeout 30} and read {filePath}",
      calls == [{"name": "bash", "arguments": {"command": "git init demo", "timeout": 30}},
                {"name": "read", "arguments": {"filePath": "README.md"}}] and clean == "I'll make the repo.", (clean, calls))
v4 = V41.replace(" calls>", "tool_calls>")
check("V4 markup (tool_calls) too", dsml_proxy.parse(v4)[1] == calls)
ascii_ = V41.replace("｜", "|").replace("\n", "")
check("ASCII bars and no newlines (the degraded form) too", dsml_proxy.parse(ascii_)[1] == calls, dsml_proxy.parse(ascii_))
check("text without markup is untouched", dsml_proxy.parse("a < b and <b>bold</b>") == ("a < b and <b>bold</b>", []))
check("opencode_engine's guard sees both forms", opencode_engine.leaked_tool_markup(V41) and opencode_engine.leaked_tool_markup(ascii_))

# ---- a fake host answering the way NVIDIA / OpenRouter did
HITS: list = []


def pieces(text, n=7):
    return [text[i:i + n] for i in range(0, len(text), n)]


class Host(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        HITS.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        text = V41 if "repo" in body["messages"][-1]["content"] else "Plain answer: 2 < 3, and <b> is a tag."
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for p in pieces(text):
                self.wfile.write(("data: %s\n\n" % json.dumps({"id": "x1", "object": "chat.completion.chunk", "model": "m",
                                  "choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]})).encode())
            self.wfile.write(("data: %s\n\n" % json.dumps({"id": "x1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})).encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        data = json.dumps({"id": "x1", "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                                    "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


host = ThreadingHTTPServer(("127.0.0.1", 0), Host)
threading.Thread(target=host.serve_forever, daemon=True).start()
UP = "http://127.0.0.1:%d/v1" % host.server_address[1]
# wrap() skips 127.0.0.1 upstreams (LOKI's own local servers), so the test registers this fake host directly
base = dsml_proxy.proxy().url_for(UP)


def ask(content, stream):
    req = urllib.request.Request(base + "/chat/completions", method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer sk-test"},
        data=json.dumps({"model": "deepseek/deepseek-v4.1-flash", "stream": stream,
                         "messages": [{"role": "user", "content": content}]}).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
    if not stream:
        return json.loads(raw)
    return [json.loads(ln[5:]) for ln in raw.splitlines() if ln.startswith("data:") and ln[5:].strip() != "[DONE]"]


chunks = ask("make a repo", True)
text = "".join((c["choices"][0]["delta"].get("content") or "") for c in chunks if c.get("choices"))
tcs = [t for c in chunks if c.get("choices") for t in (c["choices"][0]["delta"].get("tool_calls") or [])]
fins = [c["choices"][0]["finish_reason"] for c in chunks if c.get("choices") and c["choices"][0].get("finish_reason")]
check("streamed: the agent gets real tool_calls - bash {command: git init demo} and read", [t["function"]["name"] for t in tcs] == ["bash", "read"]
      and json.loads(tcs[0]["function"]["arguments"]) == {"command": "git init demo", "timeout": 30} and tcs[1]["index"] == 1, tcs)
check("... the words before them, and no DSML tags anywhere", text.strip() == "I'll make the repo." and "DSML" not in json.dumps(chunks), text)
check("... finish_reason tool_calls (once), so the agent runs them", fins == ["tool_calls"], fins)
check("... one request upstream, the key passed through as is", len(HITS) == 1 and HITS[0]["auth"] == "Bearer sk-test"
      and HITS[0]["path"] == "/v1/chat/completions", HITS)
chunks = ask("hello", True)
text = "".join((c["choices"][0]["delta"].get("content") or "") for c in chunks if c.get("choices"))
check("a plain streamed answer (with '<' in it) passes through whole, finish stop", text == "Plain answer: 2 < 3, and <b> is a tag."
      and [c["choices"][0]["finish_reason"] for c in chunks if c["choices"] and c["choices"][0].get("finish_reason")] == ["stop"], text)
r = ask("make a repo", False)
m = r["choices"][0]
check("not streamed: message.tool_calls, clean content, finish tool_calls", [t["function"]["name"] for t in m["message"].get("tool_calls", [])] == ["bash", "read"]
      and m["message"]["content"] == "I'll make the repo." and m["finish_reason"] == "tool_calls", r)

w = dsml_proxy.wrap({"nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "model": "deepseek-ai/deepseek-v4.1-flash"},
                     "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-v4.1-flash"},
                     "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
                     "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3"}})
check("wrap: DeepSeek on NVIDIA and OpenRouter go through the fix; DeepSeek's own API and other models do not",
      w["nvidia"]["base_url"].startswith("http://127.0.0.1") and w["openrouter"]["base_url"].startswith("http://127.0.0.1")
      and w["deepseek"]["base_url"] == "https://api.deepseek.com" and w["groq"]["base_url"].startswith("https://api.groq"), w)

import types  # noqa: E402
import tool_harness  # noqa: E402
msg = types.SimpleNamespace(content=V41, tool_calls=None)
resp = tool_harness.attach(types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")]), ["bash", "read"])
got = [(c.function.name, json.loads(c.function.arguments)) for c in (msg.tool_calls or [])]
check("LOKI's own tool loop: the same markup becomes real tool calls (tool_harness.attach)",
      got == [("bash", {"command": "git init demo", "timeout": 30}), ("read", {"filePath": "README.md"})]
      and msg.content == "I'll make the repo." and resp.choices[0].finish_reason == "tool_calls", (got, msg.content))

check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
