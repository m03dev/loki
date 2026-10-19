"""Why LOKI's background jobs failed (session 27) and the fixes - offline, fake models only.

Seen in the PC's job logs: qwen3:8b returned empty replies (its thinking ate the answer), wrote
tool calls as text, called the image maker as a tool named "image", "saved" a picture by writing
its description into a .png that the checker accepted, small-model BLOCKED guesses ended jobs,
and Claude Code crashed on a NUL byte in a very long command line.

    python tests/test_job_fixes.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-jobfix-"))
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(WS)
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_NO_ESCALATE"):
    os.environ.pop(_k, None)

import cli_agents  # noqa: E402
import creations  # noqa: E402
import loki  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def section(title):
    print("\n" + title)


def fake_response(content, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls, role="assistant")
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])


TOOLS = [{"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": {}}}}
         for n in ("conductor", "write_file", "read_file")]

section("qwen3 on a local server answers instead of thinking itself empty")
local = types.SimpleNamespace(base_url="http://127.0.0.1:11434/v1", model="qwen3:8b", api_key="ollama")
cloud = types.SimpleNamespace(base_url="https://openrouter.ai/api/v1", model="qwen/qwen3-32b", api_key="x")
kw = {"model": "qwen3:8b", "messages": [{"role": "system", "content": "You are LOKI."}, {"role": "user", "content": "hi"}]}
sent = loki._small_model_kwargs(kw, local)
check("the /no_think switch is added to the system message", sent["messages"][0]["content"].endswith("/no_think"))
check("the conversation itself is not changed", kw["messages"][0]["content"] == "You are LOKI.")
check("not for cloud models", loki._small_model_kwargs(kw, cloud) is kw)
bonsai = types.SimpleNamespace(base_url=local.base_url, model="hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0")
check("Bonsai 2 (a Qwen3.5) gets /no_think too", loki._small_model_kwargs(kw, bonsai)["messages"][0]["content"].endswith("/no_think"))
check("not for other local models", loki._small_model_kwargs(kw, types.SimpleNamespace(base_url=local.base_url,
                                                                                       model="llama3.1:8b")) is kw)

section("a tool call written as text becomes a real call")
r = loki._salvage_reply(fake_response('I will make it.\n```json\n{"name": "conductor", "arguments": {"role": "image", '
                                      '"task": "a fox asleep in the snow"}}\n```'), {"tools": TOOLS})
calls = r.choices[0].message.tool_calls or []
check("```json block -> conductor call", len(calls) == 1 and calls[0].function.name == "conductor"
      and json.loads(calls[0].function.arguments)["task"] == "a fox asleep in the snow", calls)
r = loki._salvage_reply(fake_response('{"name": "image", "arguments": {"task": "a fox"}}'), {"tools": TOOLS})
calls = r.choices[0].message.tool_calls or []
check("a call to the role name 'image' is kept (it is routed to conductor)", calls and calls[0].function.name == "image", calls)
r = loki._salvage_reply(fake_response("<think>long musing</think>DONE: made it"), {"tools": TOOLS})
check("think tags are dropped from the answer", r.choices[0].message.content == "DONE: made it", r.choices[0].message.content)
r = loki._salvage_reply(fake_response("</think>\n\n"), {"tools": TOOLS})
check("a stray </think> alone becomes an empty answer (so the empty-reply path handles it)",
      (r.choices[0].message.content or "") == "")
r = loki._salvage_reply(fake_response("Here is a JSON example: {\"a\": 1}"), {"tools": TOOLS})
check("ordinary JSON in an answer is not mistaken for a call", not r.choices[0].message.tool_calls)

section("a specialist called by its role name still runs")
seen = {}


def fake_conductor(role, task="", url=""):
    seen.update(role=role, task=task)
    return "made %s with pollinations" % (WS / "images" / "fox.jpg")


loki.LOCAL_TOOLS["conductor"] = fake_conductor
out = asyncio.run(loki.call_tool("image", {"prompt": "a fox asleep in the snow"}))
check("image(prompt=...) -> conductor(role='image', task=...)", seen == {"role": "image", "task": "a fox asleep in the snow"}, (seen, out))
seen.clear()
asyncio.run(loki.call_tool("generate_image", {"prompt": "a rabbit"}))
check("generate_image is the image role too", seen.get("role") == "image" and seen.get("task") == "a rabbit", seen)
check("the made file counts as the task's work (DONE is accepted, the file is verified)",
      loki._specialist_made("conductor", "made %s with pollinations" % (WS / "images" / "fox.jpg")) == "images/fox.jpg")

section("no more fake pictures")
out = loki.write_file("images/fox_asleep_in_snow.png", "a fox asleep in the snow")
check("write_file refuses to put text in a .png and says how to make a picture",
      out.startswith("error") and "conductor(role='image'" in out and not (WS / "images" / "fox_asleep_in_snow.png").exists(), out)
(WS / "images").mkdir(exist_ok=True)
(WS / "images" / "fake.png").write_text("a fox asleep in the snow", encoding="utf-8")
(WS / "images" / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
(WS / "images" / "real.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
check("a text file named .png fails the check", "INVALID" in loki.media_check("images/fake.png"))
check("a real PNG and JPEG pass", "OK" in loki.media_check("images/real.png") and "OK" in loki.media_check("images/real.jpg"))
report = loki.verify_files(["images/fake.png", "images/real.png"])
check("verification fails the job's fake picture instead of 'no automatic check'",
      [p for p, _ in report["failed"]] == ["images/fake.png"] and report["ok"] == ["images/real.png"], report)
src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("the 'DONE is premature' nudge no longer tells every task to write_file (it was Godot-only)",
      "build_3d_scene for a scene, write_file for a script" not in src and "conductor(role='image'" in src)

section("a stuck job on the small local model: mix and match the local models, then the cloud")
saved = (loki.model_name, loki.active_model_name, loki.routing_order, loki.provider_configured,
         loki._local_chain_next, loki.resolve_local)
_saved_env = os.environ.get("LOKI_LOCAL_MODEL")
loki.model_name = "local"
loki.active_model_name = lambda: loki.model_name
loki.routing_order = lambda order: ["local", "groq", "openrouter"]
loki.provider_configured = lambda name: name == "groq"


def _chain(tried):
    # one other local model until we hop (LOKI_LOCAL_MODEL gets set), then nothing is left
    return {} if os.environ.get("LOKI_LOCAL_MODEL") else {"name": "qwen3:8b"}


loki._local_chain_next = _chain
loki.resolve_local = lambda force=False: {"name": "loki-qwen3-8b"}
loki.__dict__["_ESCALATED"] = False
loki.__dict__.pop("_LOCAL_TRIED", None)
check("not in the window (only background jobs)", loki._escalate_model("test") is False)
os.environ["LOKI_JOB_ID"] = "t1"
loki.messages[:] = [{"role": "system", "content": "s"}]
check("in a job: tries the NEXT local model first and stays offline",
      loki._escalate_model("empty replies") is True and loki.model_name == "local"
      and os.environ.get("LOKI_LOCAL_MODEL") == "qwen3:8b"
      and "different local model" in loki.messages[-1]["content"])
check("when no other local model fits, moves to the first free, set-up online model",
      loki._escalate_model("again") is True and loki.model_name == "groq"
      and "stronger model" in loki.messages[-1]["content"])
check("the online step happens only once per job", loki._escalate_model("again") is False)
os.environ.pop("LOKI_JOB_ID", None)
if _saved_env is None:
    os.environ.pop("LOKI_LOCAL_MODEL", None)
else:
    os.environ["LOKI_LOCAL_MODEL"] = _saved_env
(loki.model_name, loki.active_model_name, loki.routing_order, loki.provider_configured,
 loki._local_chain_next, loki.resolve_local) = saved
for word in ('_escalate_model("it kept returning empty replies")', '_escalate_model("it kept saying DONE without doing it")',
             '_escalate_model("it gave up: "', '_escalate_model("it stopped calling tools")'):
    check("the goal loop escalates when " + word.split('"')[1], word in src)

section("Claude Code no longer crashes the job on Windows")
check("NUL and control bytes are removed from command-line text",
      cli_agents._clean_arg("read\x00me\x07 ok\tyes\n") == "readme ok\tyes\n")
captured = {}


def fake_run(argv, **kw):
    captured.update(argv=argv, input=kw.get("input"), stdin=kw.get("stdin"))
    return types.SimpleNamespace(returncode=0, stdout=json.dumps({"type": "result", "result": "DONE: ok"}), stderr="")


orig_run, orig_find = cli_agents.subprocess.run, cli_agents.find_cli
cli_agents.subprocess.run = fake_run
cli_agents.find_cli = lambda name: "claude"
try:
    cli_agents.run("claude-code", "system", "x\x00" * 30000, str(WS))
    check("a long prompt goes on stdin, not the command line", captured["input"] and "\x00" not in captured["input"]
          and sum(len(a) for a in captured["argv"]) < cli_agents.ARGV_LIMIT, sum(len(a) for a in captured["argv"]))
    cli_agents.run("claude-code", "system", "short task", str(WS))
    check("a short prompt stays an argument", captured["argv"][-1] == "short task" and captured["input"] is None)
    cli_agents.run("claude-code", "S" * 30000, "task", str(WS))
    check("a huge system prompt rides along on stdin too", "--append-system-prompt" not in captured["argv"]
          and captured["input"].startswith("S"))
finally:
    cli_agents.subprocess.run, cli_agents.find_cli = orig_run, orig_find

section("Creations: a picture is made straight by the image maker (no chat model in between)")


class FakeAgent:
    def conductor_tool(self, role, task):
        return "made images/x.jpg with pollinations" if role == "image" else "error"


res = creations.make_image(FakeAgent(), "a fox asleep in the snow")
for _ in range(50):
    done = [m for m in creations.making() if m["id"] == res.get("id") and m["end"]]
    if done:
        break
    import time as _t
    _t.sleep(0.02)
check("it starts at once and finishes with the specialist's answer", res["ok"] and done and done[0]["ok"], creations.making())
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
cjs = (REPO / "app" / "ui" / "creations.js").read_text(encoding="utf-8")
check("the bridge and the wall use it", 'route == "/creations/make"' in bridge and 'api("/creations/make"' in cjs)

section("a blank window is never blank: boot.js rescue + errors in engine.out")
boot = (REPO / "app" / "ui" / "boot.js").read_text(encoding="utf-8")
idx = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
app_py = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
check("boot.js loads first, not deferred, before the stylesheets", '<script src="/ui/boot.js"></script>' in idx
      and idx.index("/ui/boot.js") < idx.index("/ui/app.css"))
check("it reports script errors to the engine and shows a rescue screen with them", "/ui/error" in boot and "rescue(" in boot
      and "Reload without the 3D world" in boot and 'route == "/ui/error"' in bridge and '"ui_errors"' in bridge)
check("app.js marks the window ready", "window.LOKI_READY = true" in (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8"))
check("the app never shows about:blank (white) when the engine fails; it shows the log", 'show_url("about:blank")' not in app_py
      and "show_problem(" in app_py and "log_tail(" in app_py)
import loki_bridge  # noqa: E402
check("tokens in a window error line are redacted", "[redacted]" in loki_bridge.redact_line("GET /#token=abcdef123 Bearer xyz.987")
      and "abcdef123" not in loki_bridge.redact_line("#token=abcdef123"))

section("TimesFM-3: the owner said yes")
import forecast  # noqa: E402
os.environ.pop("LOKI_TIMESFM_APPROVED", None)
check("the approval is recorded in the repo", forecast.approved())
os.environ["LOKI_TIMESFM_APPROVED"] = "0"
check("a machine (and every test suite) can still say no", not forecast.approved()
      and forecast.install_if_approved().get("skipped"))
check("the engine installs it once at start-up where it is missing", "forecast.install_if_approved()" in bridge)

section("Update everything restarts every machine; icons in favour of words")
import updater  # noqa: E402
calls = []
orig = (updater.time.sleep, updater.enabled, updater.is_checkout, updater.check_now)


class _Stop(Exception):
    pass


def _sleep(s):
    if calls and calls[-1] == "applied":
        raise _Stop()


updater.time.sleep = _sleep
updater.enabled = lambda: True
updater.is_checkout = lambda repo: True
updater.check_now = lambda: updater.STATE.update(update_available=True)
os.environ.pop("LOKI_FORCE_UPDATE", None)
try:
    updater.run_forever(every_s=60, idle=lambda: calls.append("idle") or True, apply=lambda: calls.append("applied"))
except _Stop:
    pass
updater.time.sleep, updater.enabled, updater.is_checkout, updater.check_now = orig
check("a waiting update is applied by itself when LOKI is idle", calls == ["idle", "applied"], calls)
check("the bridge applies it with a full restart and only when idle (no chat, no running job)",
      'kwargs={"idle": _idle, "apply": _apply}' in bridge and "update_all.apply_here(updater, restart_engine)" in bridge)
html = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
icons = (REPO / "app" / "ui" / "icons.js").read_text(encoding="utf-8")
check("icons.js is loaded and gives every main button and Settings section an icon with a name and what it does",
      "/ui/icons.js" in html and all(t in icons for t in ('"#new-chat"', '"#open-settings"', '"#send"', '"#update-banner-go"',
                                                          "creations:", "brain:", "showTip(", "data-tip-name")))
check("the words stay for screen readers and the Settings search", "aria-label" in icons and "tab-label" in icons)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
