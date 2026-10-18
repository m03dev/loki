"""The engine streams DeepSeek on NVIDIA NIM (owner's Mac, 2026-10-18: "The read operation timed out" on long turns).

    python tests/test_engine_stream.py      (< 10 s, no network)

A streamed reply is put back together in the shape the agent loop reads (content, tool calls split over chunks,
reasoning, usage, model_dump); local servers and other providers stay as they were unless LOKI_STREAM_MODELS=remote.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
os.environ["LOKI_DATA"] = tempfile.mkdtemp(prefix="loki-estream-")
import loki  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def chunk(content=None, reasoning=None, tool=None, usage=None, finish=None):
    delta = NS(content=content, tool_calls=[tool] if tool else None, model_extra={"reasoning_content": reasoning} if reasoning else {})
    return NS(choices=[NS(delta=delta, finish_reason=finish)] if not usage else [], usage=usage)


class Stream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


sent = []


class Completions:
    def __init__(self, chunks):
        self.chunks = chunks

    async def create(self, **kw):
        sent.append(kw)
        return Stream(self.chunks)


def client(chunks):
    return NS(chat=NS(completions=Completions(chunks)))


fn = lambda name=None, args=None: NS(name=name, arguments=args)  # noqa: E731
r = asyncio.run(loki._streamed_request(client([
    chunk(reasoning="hmm "),
    chunk(content="Reading "),
    chunk(tool=NS(index=0, id="c1", function=fn("read_", '{"filename": '))),
    chunk(tool=NS(index=0, id=None, function=fn("file", '"a.py"}'))),
    chunk(finish="tool_calls"),
    chunk(usage=NS(prompt_tokens=100, completion_tokens=12)),
]), {"model": "deepseek", "messages": []}))
m = r.choices[0].message
check("the request is streamed", sent[-1].get("stream") is True)
check("content is put together", m.content == "Reading ", m.content)
check("a tool call split over chunks comes back whole", m.tool_calls[0].id == "c1" and m.tool_calls[0].function.name == "read_file"
      and m.tool_calls[0].function.arguments == '{"filename": "a.py"}', m.model_dump())
check("reasoning is kept for LOKI's progress line", m.reasoning_content == "hmm ")
check("usage is kept (credit display)", r.usage.prompt_tokens == 100)
d = m.model_dump()
check("model_dump gives the dict the history needs", d["tool_calls"][0]["function"]["name"] == "read_file" and d["role"] == "assistant", d)
empty = asyncio.run(loki._streamed_request(client([]), {"model": "x"}))
check("an empty stream is an empty reply (LOKI's empty-reply retry handles it)", loki._no_choices(empty))
nim = NS(base_url="https://integrate.api.nvidia.com/v1", model="deepseek-ai/deepseek-v4.1-flash", api_key="k")
local = NS(base_url="http://localhost:11434/v1", model="qwen3:8b", api_key="ollama")
other = NS(base_url="https://api.groq.com/openai/v1", model="qwen", api_key="k")
check("DeepSeek on NVIDIA streams", loki._stream_for("nvidia", nim))
check("a local model does not", not loki._stream_for("local", local))
check("other providers keep their old path by default", not loki._stream_for("groq", other))
loki.STREAM_MODELS = "remote"
check("LOKI_STREAM_MODELS=remote streams every cloud provider", loki._stream_for("groq", other) and not loki._stream_for("local", local))
r2 = loki._take_reasoning(r, "nvidia", nim)
check("the reasoning is taken out of the reply like before", getattr(r2.choices[0].message, "reasoning_content", None) is None)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
