"""The tool guard: small/local models get their tool calls repaired, checked and (on a
local server) constrained, so the last inch - the call's shape - no longer stops work.

    python tests/test_tool_guard.py

Unit checks on engine/tool_guard.py, then real agent turns against a scripted fake local
model on 127.0.0.1:11434 that makes the mistakes real 3-9B models make, then a check that
a local model dropped after one failure comes back on the next request.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "tests"), str(REPO / "engine")]

PASS: list = []
FAIL: list = []


def check(name: str, ok: bool, detail: object = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title: str) -> None:
    print("\n" + title)


import tool_guard as tg  # noqa: E402

WRITE = {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}},
         "required": ["filename", "content"]}
LIST = {"type": "object", "properties": {"subdir": {"type": "string"}, "max_depth": {"type": "integer"}},
        "required": []}
SCHEMAS = {"write_file": WRITE, "list_tree": LIST,
           "read_file": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
           "run_command": {"type": "object", "properties": {"command": {"type": "string"},
                                                            "timeout": {"type": "integer"}}, "required": ["command"]}}

# ---------------------------------------------------------------------------- repair_json
section("repairing arguments a small model produced")
check("strict JSON passes through", tg.repair_json('{"a": 1}') == {"a": 1})
check("single quotes + trailing comma", tg.repair_json("{'filename': 'a.txt', 'content': 'hi',}")
      == {"filename": "a.txt", "content": "hi"})
check("a json fence is stripped", tg.repair_json('```json\n{"a": 2}\n```') == {"a": 2})
check("Python True/None literals", tg.repair_json("{'ok': True, 'x': None}") == {"ok": True, "x": None})
check("unquoted keys", tg.repair_json('{filename: "a.txt", content: "x"}') == {"filename": "a.txt", "content": "x"})
check("double-encoded JSON string", tg.repair_json(json.dumps('{"a": 3}')) == {"a": 3})
check("an object buried in prose", tg.repair_json('Sure, here: {"a": 4} - done.') == {"a": 4})
check("already a dict is returned as-is", tg.repair_json({"a": 5}) == {"a": 5})
check("empty means no arguments", tg.repair_json("") == {})
check("genuine garbage is rejected", tg.repair_json("not json at all") is None)

# ---------------------------------------------------------------------------- resolve_name
section("mapping a near-miss tool name to a real tool")
known = set(SCHEMAS)
check("exact name", tg.resolve_name("write_file", known) == "write_file")
check("camelCase", tg.resolve_name("writeFile", known) == "write_file")
check("create_file -> write_file", tg.resolve_name("create_file", known) == "write_file")
check("ls -> list_tree", tg.resolve_name("ls", known) == "list_tree")
check("cat -> read_file", tg.resolve_name("cat", known) == "read_file")
check("bash -> run_command", tg.resolve_name("bash", known) == "run_command")
check("functions. prefix is dropped", tg.resolve_name("functions.write_file", known) == "write_file")
check("a typo close to a real tool", tg.resolve_name("wirte_file", known) == "write_file")
check("a genuinely unknown tool is refused", tg.resolve_name("teleport", known) == "")

# ---------------------------------------------------------------------------- validate
section("checking and coercing arguments")
args, err = tg.validate("write_file", {"filename": "a.txt", "content": "hi"}, WRITE)
check("a good call passes", err == "" and args["filename"] == "a.txt")
args, err = tg.validate("list_tree", {"max_depth": "3"}, LIST)
check("a number sent as a string is coerced", err == "" and args["max_depth"] == 3, (args, err))
args, err = tg.validate("write_file", {"filename": "a.txt"}, WRITE)
check("a missing required argument is named", "content" in err and "missing" in err.lower(), err)
args, err = tg.validate("write_file", {"filename": "a.txt", "content": "x", "extra": 1}, WRITE)
check("an unknown extra argument is dropped", err == "" and "extra" not in args, (args, err))
check("the error shows the signature", "write_file(" in tg.signature("write_file", WRITE))

# ---------------------------------------------------------------------------- check_call
section("the whole guard on one call")
fix = tg.check_call("create_file", "{'filename': 'notes/a.txt', 'content': 'hi',}", SCHEMAS)
check("name fixed and JSON repaired together", fix.ok and fix.name == "write_file"
      and fix.args == {"filename": "notes/a.txt", "content": "hi"}, (fix.name, fix.args, fix.error))
check("the repair is noted", any("write_file" in n for n in fix.notes), fix.notes)
fix = tg.check_call("write_file", '{"filename": "a.txt"}', SCHEMAS)
check("a still-bad call is rejected with a reason", (not fix.ok) and "content" in fix.error, fix.error)
fix = tg.check_call("nonsense", "{}", SCHEMAS)
check("an unknown tool is rejected", not fix.ok and "no tool" in fix.error, fix.error)

# ---------------------------------------------------------------------------- function syntax
section("a call written as code")
calls = tg.parse_function_syntax('write_file(filename="a.txt", content="hi")', known)
check("keyword call parsed", calls == [("write_file", {"filename": "a.txt", "content": "hi"})], calls)
calls = tg.parse_function_syntax('```python\nlist_tree(max_depth=2)\n```', known)
check("call inside a code fence parsed", calls == [("list_tree", {"max_depth": 2})], calls)
check("ordinary prose with parentheses is ignored",
      tg.parse_function_syntax("I think (maybe) we should.", known) == [])

# ---------------------------------------------------------------------------- constrained
section("constrained decoding schema")
fmt = tg.constrained_format([{"function": {"name": "write_file", "parameters": WRITE}}])
check("it is a json_schema response_format", fmt["type"] == "json_schema")
variants = fmt["json_schema"]["schema"]["anyOf"]
check("a call variant and an answer variant exist", len(variants) == 2
      and {v["properties"]["action"].get("const") for v in variants} == {"call", "answer"}, variants)
calls, text = tg.decode_constrained('{"action": "call", "tool": "write_file", "arguments": {"filename": "a", "content": "b"}}', known)
check("a constrained call decodes", calls == [("write_file", {"filename": "a", "content": "b"})], calls)
calls, text = tg.decode_constrained('{"action": "answer", "text": "all done"}', known)
check("a constrained answer decodes", calls == [] and text == "all done", (calls, text))

# ---------------------------------------------------------------------------- end to end
section("a real local turn where the model gets the call shape wrong")


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


if not port_free(11434):
    print("  (port 11434 in use - skipping the live-model part)")
else:
    TMP = Path(tempfile.mkdtemp(prefix="loki-guard-"))
    (TMP / "d").mkdir()
    (TMP / "w").mkdir()
    os.environ.update(LOKI_DATA=str(TMP / "d"), LOKI_WORKSPACE=str(TMP / "w"), LOKI_PREFER="local",
                      LOKI_MODE="build", LOKI_MODEL="smart", LOKI_AUTO_APPROVE="1",
                      LOKI_CONSTRAINED_TOOLS="off")
    for key in [k for k in os.environ if k.endswith("_API_KEY")]:
        os.environ.pop(key)
    from fake_ollama import FakeOllama  # noqa: E402

    fake = FakeOllama(models=["qwen3.5:9b-q4_K_M"]).start()
    try:
        import loki  # noqa: E402
        loki.resolve_local(force=True)

        # The fake writes the tool call the way a sloppy small model does: a wrong tool
        # name (create_file), single-quoted JSON with a trailing comma, then DONE.
        def sloppy(body: dict) -> dict:
            messages = body.get("messages", [])
            # The call was already handled once it comes back as a tool result (native
            # tool role) or as the recovered-call note the agent appends as a user turn.
            handled = any(m.get("role") == "tool" or (m.get("role") == "user"
                          and "Result of" in str(m.get("content") or "")) for m in messages)
            usage = {"prompt_tokens": 1200, "completion_tokens": 20, "total_tokens": 1220}
            if not handled:
                content = ("<tool_call>\n{'name': 'create_file', 'arguments': {'filename': "
                           "'notes/hi.txt', 'content': 'hello',}}\n</tool_call>")
            else:
                content = "DONE: wrote notes/hi.txt"
            return {"id": "x", "object": "chat.completion", "created": 0, "model": body.get("model", ""),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                 "finish_reason": "stop"}], "usage": usage}

        fake.reply = sloppy
        loki.GUARD_STATS.update(repaired=0, rejected=0)
        loki.messages[:] = [{"role": "system", "content": loki.system_prompt()}]
        answer = asyncio.run(loki.run_agent("please create the file notes/hi.txt with hello"))
        wrote = (TMP / "w" / "notes" / "hi.txt")
        check("the wrong tool name + bad JSON still wrote the file",
              wrote.is_file() and wrote.read_text().strip() == "hello", (answer[:120], wrote.is_file()))
        check("the guard counted a repair", loki.GUARD_STATS["repaired"] >= 1, loki.GUARD_STATS)

        # A local model that fails once must come back on the next request, not be dropped
        # for the whole session (the bug that made local feel useless).
        loki._SMART_FAILED.clear()
        loki._mark_smart_failure("local")
        loki._FAILED_AT["local"] = time.time() - 9999   # long enough ago to revive
        back = loki.revive_local()
        check("a local model dropped after a failure comes back when its server answers",
              "local" in back and "local" not in loki._SMART_FAILED, (back, loki._SMART_FAILED))
    finally:
        fake.stop()

# --------------------------------------------------------------------------- long text calls
# From a real PC run (2026-10-15, harness_data/_engine_ziva6.log): a local model wrote a whole
# web page as a TEXT write_file call. The CSS/JS braces inside the content and one missing
# final "}" made LOKI drop the call, and a reply cut off mid-call was lost too; the task
# looped to the step limit with no file.
tool_guard = tg
print("\nlong write_file calls written as text")
page = "<style>* { box-sizing: border-box; } li { color: red; }</style><script>(function() { if (x) { go(); } })();</script>"
call = json.dumps({"name": "write_file", "arguments": {"filename": "fence2/index.html", "content": page}})
reply = "Now I'll write the page.\n\n```json\n" + call[:-1] + "\n```"     # the model forgot the last }
check("braces inside a call's strings do not break the scan",
      tool_guard.json_object_spans("x " + call + " y") == [call])
check("a call missing its final } is closed, nothing else changed",
      json.loads(tool_guard.close_truncated(call[:-1]))["arguments"]["content"] == page)
check("broken text is not guessed at (open string, wrong closer)",
      tool_guard.close_truncated('{"a": "open') is None and tool_guard.close_truncated('{"a": ]') is None)
try:
    import loki  # noqa: E402
except ImportError:
    loki = None
if loki is not None:
    got = loki._recover_text_tool_calls(reply)
    check("LOKI recovers that call and runs write_file with the whole page",
          got and got[0][0] == "write_file" and got[0][1].get("content") == page, got)
    cut = 'Writing it.\n```json\n' + call[:len(call) // 2]
    check("a reply cut off mid-call is recognised as unfinished", loki._unfinished_call(cut))
    check("...and joined with the next reply it is recovered whole",
          loki._recover_text_tool_calls(cut + call[len(call) // 2:])[0][1].get("content") == page)
    check("a finished call or a plain answer is not 'unfinished'",
          not loki._unfinished_call(call) and not loki._unfinished_call("All done, the page works."))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
