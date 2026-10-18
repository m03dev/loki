"""Studio streams its model replies (owner's Mac, 2026-10-18: "nvidia did not answer (The read operation timed out)").

    python tests/test_studio_stream.py      (< 5 s, no network)

A long free-tier answer arrives chunk by chunk instead of all at the end, so it is never cut off by a timeout; tool
calls split over many chunks are put back together; a provider that went silent is not retried on that turn and is
asked last for a while, so the next turn starts on a model that answers.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "studio"))
sys.path.insert(0, str(REPO / "engine"))
os.environ["LOKI_DATA"] = tempfile.mkdtemp(prefix="loki-sstream-")
os.environ["LOKI_USER_KEYS"] = str(Path(os.environ["LOKI_DATA"]) / "keys.env")
import studio_models as sm  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def sse(*chunks):
    return [("data: " + json.dumps(c) + "\n").encode() for c in chunks] + [b"data: [DONE]\n"]


class Resp(list):
    headers = {"Content-Type": "text/event-stream"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


sent = []


def opener_with(lines):
    def opener(req, timeout=0):
        sent.append((json.loads(req.data.decode()), timeout))
        return Resp(lines)
    return opener


nim = sm.Provider("nvidia", "NIM", "https://example.invalid/v1", "deepseek", "NVIDIA_API_KEY", "k")
msg = sm.request(nim, [{"role": "user", "content": "hi"}], opener=opener_with(sse(
    {"choices": [{"delta": {"reasoning_content": "think "}}]},
    {"choices": [{"delta": {"content": "Hel"}}]},
    {"choices": [{"delta": {"content": "lo"}}]})))
check("a remote provider is asked to stream", sent[-1][0].get("stream") is True, sent[-1][0])
check("the streamed answer is put together", msg["content"] == "Hello" and msg["reasoning_content"] == "think ", msg)
check("the timeout is the wait for the first byte, not the whole answer", sent[-1][1] == sm.FIRST_BYTE_S)
msg = sm.request(nim, [], tools=[{"type": "function"}], opener=opener_with(sse(
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_", "arguments": "{\"pa"}}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": "th\": \"a\"}"}}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "c2", "function": {"name": "ls", "arguments": "{}"}}]}}]})))
calls = msg.get("tool_calls") or []
check("tool calls split over chunks come back whole", [(c["id"], c["function"]["name"], c["function"]["arguments"]) for c in calls]
      == [("c1", "read_file", '{"path": "a"}'), ("c2", "ls", "{}")], calls)
try:
    sm.request(nim, [], opener=opener_with(sse({"error": {"message": "overloaded"}})))
    check("an error inside the stream is a model error", False)
except sm.ModelError as exc:
    check("an error inside the stream is a model error", "overloaded" in str(exc))
local = sm.Provider("local", "Ollama", "http://127.0.0.1:11434/v1", "m", key="ollama", local=True)


class Plain:
    headers = {"Content-Type": "application/json"}

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


sm.request(local, [], opener=lambda req, timeout=0: (sent.append((json.loads(req.data.decode()), timeout)), Plain())[1])
check("a local server is not streamed", "stream" not in sent[-1][0])

# a provider that times out: not retried on this turn, asked last for a while
tries = []


def slow_then_ok(req, timeout=0):
    url = req.full_url
    tries.append(url)
    if "nim" in url:
        raise TimeoutError("The read operation timed out")
    return Plain()


a = sm.Provider("nvidia", "NIM", "https://nim.invalid/v1", "d", "NVIDIA_API_KEY", "k")
b = sm.Provider("groq", "Groq", "https://groq.invalid/v1", "g", "GROQ_API_KEY", "k")
said = []
prov, out, _r = sm.chat([], chain_list=[a, b], opener=slow_then_ok, sleep=lambda s: None, say=said.append)
check("a silent provider is asked once, then the next answers", prov.id == "groq" and sum("nim" in u for u in tries) == 1, (tries, said))
check("it is marked slow", sm.slow("nvidia"))
tries.clear()
prov, out, _r = sm.chat([], chain_list=[a, b], opener=slow_then_ok, sleep=lambda s: None)
check("the next turn starts on the provider that answers", tries and "groq" in tries[0] and prov.id == "groq", tries)

# a real socket: chunked SSE that trickles in slower than the old whole-answer timeout would allow per chunk
import threading  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for word in ("one ", "two ", "three"):
            data = ("data: " + json.dumps({"choices": [{"delta": {"content": word}}]}) + "\n\n").encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data)); self.wfile.flush()
            time.sleep(0.4)
        end = b"data: [DONE]\n\n"
        self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(end), end)); self.wfile.flush()


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
real = sm.Provider("nvidia", "NIM", "http://127.0.0.1:%d/v1" % srv.server_address[1], "d", "NVIDIA_API_KEY", "k")
sm.FIRST_BYTE_S, sm.STREAM_IDLE_S = 1.0, 1.0      # each chunk comes within a second; the whole answer takes 1.2 s
opener = __import__("urllib.request").request.build_opener(__import__("urllib.request").request.ProxyHandler({})).open
t0 = time.monotonic()
msg = sm.request(real, [], opener=opener)
check("a real chunked stream slower than the timeout overall still arrives whole", msg["content"] == "one two three"
      and time.monotonic() - t0 > 1.0, msg)
srv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
