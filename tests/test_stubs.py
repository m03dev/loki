"""Contract tests: the offline stubs must satisfy the SAME contract as the real packages.

    python tests/test_stubs.py

`tests/cloud_stubs` lets a cloud agent without PyPI run LOKI's suites. That path is only used
off the Mac/PC, so a stub that drifts from the real `openai` / `pydantic` / `mcp` would make the
offline run lie and nobody would notice. These tests run ONE contract script twice - first with
the stubs on PYTHONPATH, then with the real packages - and require both to satisfy the same
checks, so the offline and online worlds stay symbiotic. The real half is skipped (not failed)
when the package is not installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STUBS = REPO / "tests" / "cloud_stubs"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


# The contract: what the engine imports and how it must behave. Runs identically against the
# stub and the real package, so a difference in names or wire shape is caught here.
CONTRACT = r'''
import asyncio, http.server, json, socketserver, threading

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))

# --- openai: the names engine/loki.py, cli_agents.py and tool_harness.py import ---
import openai
for _n in ("OpenAIError", "APIStatusError", "APIConnectionError", "APITimeoutError",
           "RateLimitError", "AsyncOpenAI", "OpenAI"):
    check("openai." + _n, hasattr(openai, _n))
import openai.types.chat as _chat
check("openai.types.chat.ChatCompletionMessageToolCall", hasattr(_chat, "ChatCompletionMessageToolCall"))
check("openai error hierarchy",
      issubclass(openai.RateLimitError, openai.APIStatusError)
      and issubclass(openai.APIStatusError, openai.OpenAIError)
      and issubclass(openai.APITimeoutError, openai.APIConnectionError))

# --- pydantic ---
import pydantic
class _M(pydantic.BaseModel):
    a: int = 0
check("pydantic BaseModel + model_dump", _M(a=3).model_dump().get("a") == 3)

# --- mcp: what engine/loki.py imports to launch MCP servers ---
import mcp
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.sse import sse_client
check("mcp names", all(callable(x) for x in (ClientSession, StdioServerParameters, stdio_client,
                                             streamable_http_client, sse_client)))

# --- behaviour: a real chat-completions request against a local OpenAI-shaped server ---
class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = {"choices": [{"message": {"role": "assistant", "content": "pong",
                   "tool_calls": [{"id": "1", "type": "function",
                                   "function": {"name": "list_files", "arguments": "{}"}}]}}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

_server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
_port = _server.server_address[1]
threading.Thread(target=_server.serve_forever, daemon=True).start()

async def _go():
    client = openai.AsyncOpenAI(base_url="http://127.0.0.1:%d/v1" % _port, api_key="test")
    resp = await client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    msg = resp.choices[0].message
    check("chat shape: choices[0].message.content", msg.content == "pong")
    check("chat shape: tool_calls[0].function.name", msg.tool_calls[0].function.name == "list_files")
    check("chat shape: usage.total_tokens", resp.usage.total_tokens == 2)

try:
    asyncio.run(_go())
finally:
    _server.shutdown()

for _name, _good, _detail in results:
    print(("PASS " if _good else "FAIL ") + _name + (("  <- " + str(_detail)) if _detail and not _good else ""))
print("CONTRACT_CHECKED=%d" % len(results))
print("CONTRACT_FAILED=%d" % sum(1 for _n, _g, _d in results if not _g))
'''


def run_contract(use_stubs):
    env = dict(os.environ)
    if use_stubs:
        env["PYTHONPATH"] = str(STUBS)
    else:
        env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run([sys.executable, "-c", CONTRACT], capture_output=True, text=True,
                              env=env, timeout=180, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse(out):
    checked = failed = None
    names = {}
    for line in out.splitlines():
        if line.startswith("CONTRACT_CHECKED="):
            checked = int(line.split("=", 1)[1])
        elif line.startswith("CONTRACT_FAILED="):
            failed = int(line.split("=", 1)[1])
        elif line.startswith("PASS ") or line.startswith("FAIL "):
            names[line[5:].split("  <-")[0].strip()] = line.startswith("PASS ")
    return checked, failed, names


section("the offline stubs satisfy LOKI's contract")
code, out = run_contract(use_stubs=True)
checked, failed, stub_names = parse(out)
check("the stub contract ran", code == 0 and checked is not None, out[-400:])
check("every stub contract check passes", failed == 0 and bool(stub_names),
      {k: v for k, v in stub_names.items() if not v} or out[-400:])

section("the real packages satisfy the SAME contract (this machine)")
code, real_out = run_contract(use_stubs=False)
missing = ("ModuleNotFoundError" in real_out or "ImportError" in real_out) and "openai" in real_out
if missing:
    print("  SKIP the real packages are not installed here (cloud sandbox?) - the stub half above still proved the contract")
else:
    r_checked, r_failed, real_names = parse(real_out)
    check("the real contract ran", code == 0 and r_checked is not None, real_out[-400:])
    check("every real contract check passes", r_failed == 0 and bool(real_names),
          {k: v for k, v in real_names.items() if not v} or real_out[-400:])
    only_stub = sorted(set(stub_names) - set(real_names))
    only_real = sorted(set(real_names) - set(stub_names))
    check("the stub and the real package expose the same contract (no drift)",
          not only_stub and not only_real, {"only_in_stub": only_stub, "only_in_real": only_real})

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
