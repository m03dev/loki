"""Chat quality of life (session 29; engine/qol.py + app/ui/qol.js; docs/integrations/ZIVA_QOL.md).

Offline, well under a minute: the error classifier on LOKI's real error texts, recovery choices, interrupted
turns, steering into the real agent loop's _trim_context, allow-for-this-session (and what it refuses), the
context meter + Summarize now, search, pins, notifications, the real BridgeHTTPServer's /qol routes with the
real loki module, and the window in headless Chromium against a scripted engine: recovery card, queue +
steer, connection lost + reconnect, interrupted banner, allow for session, shortcuts (and rebinding one),
search, find, context bar, draft kept over a reload, pinned chats.

    python tests/test_qol.py
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-qol-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(TMP / "ws")
(TMP / "ws").mkdir(parents=True, exist_ok=True)
os.environ.pop("LOKI_JOB_ID", None)

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


import qol  # noqa: E402

# =============================================================================== classify
print("recovery: LOKI's real error texts -> choices")
CASES = [
    ("[model error] llama-3.3 answered HTTP 429: Rate limit reached for model. Please try again in 7.5s.", "rate_limit"),
    ("[model error] gemini answered HTTP 429: RESOURCE_EXHAUSTED quota per minute exceeded, retryDelay\": \"37s\"", "rate_limit"),
    ("[model error] openrouter answered HTTP 402: Insufficient credits. Add more using https://openrouter.ai", "quota"),
    ("You exceeded your current quota, please check your plan and billing details.", "quota"),
    ("[model error] groq answered HTTP 401: Invalid API Key", "auth"),
    ("[model unavailable] groq needs an API key and none is set. Add GROQ_API_KEY in Settings > Connections", "auth"),
    ("[model error] x answered HTTP 400: This model's maximum context length is 131072 tokens", "context"),
    ("[model unavailable] I cannot reach the model at localhost:11434.\n  Ollama does not look like it is running.", "local_down"),
    ("[model missing] Ollama does not have qwen3:8b yet. Run `ollama pull qwen3:8b` in Terminal", "model_missing"),
    ("[model unavailable] nvidia timed out (no answer in 120s).", "timeout"),
    ("[model unavailable] I cannot reach the model at api.groq.com (llama).", "network"),
    ("Loki could not reach the model. Check your connection and retry.", "network"),
    ("[model error] x returned an empty reply (no choices)", "empty"),
    ("Loki is already handling a request.", "busy"),
    ("Stopped early: cancelled by the user.", "stopped"),
    ("Stopped early: hit the 900s time budget.", "stopped"),
    ("Something odd", "unknown"),
]
bad = [(t, k, qol.classify(t)["kind"]) for t, k in CASES if qol.classify(t)["kind"] != k]
check("every error text gets the right kind (%d cases)" % len(CASES), not bad, bad)
r = qol.classify(CASES[0][0])
check("a rate limit waits the time the provider asked for, then retries; offers another model",
      r["wait_s"] == 8 and r["actions"][0] == "wait" and "switch" in r["actions"] and r["labels"]["wait"], r)
check("Gemini's retryDelay is read", qol.classify(CASES[1][0])["wait_s"] == 37)
check("a context error offers Summarize and try again first", qol.classify(CASES[6][0])["actions"][0] == "compact")
check("a bad key offers Connections first", qol.classify(CASES[4][0])["actions"][0] == "connections")
check("HTTP status alone decides when given", qol.classify("whatever", 429)["kind"] == "rate_limit" and qol.classify("x", 401)["kind"] == "auth")
check("a dropped connection waits and retries by itself (15 s) and offers a local model",
      qol.classify(CASES[10][0])["wait_s"] == 15 and "local" in qol.classify(CASES[10][0])["actions"])


class FakeAgent:
    def __init__(self, data):
        self.DATA_DIR = str(data)
        self.MODELS = {"smart": 0, "online": 0, "groq": 0, "gemini": 0, "local": 0, "claude": 0}
        self.model_name = "groq"
        self.messages = [{"role": "system", "content": "sys"}]
        self._CONDENSE_CACHE = {}
        self.convos = {"a": {"title": "Tides and the moon", "messages": [{"role": "user", "content": "why are there tides"},
                                                                          {"role": "assistant", "content": "The moon pulls the sea."}]},
                       "b": {"title": "Budget", "messages": [{"role": "user", "content": "make a budget"}]}}

    def provider_configured(self, n):
        return n in ("groq", "gemini", "local")

    def provider_tier(self, n):
        return "local" if n == "local" else "free"

    def active_model_name(self):
        return self.model_name

    def active_conversation_id(self):
        return "a"

    def list_conversations(self):
        return [{"id": k, "title": v["title"]} for k, v in self.convos.items()]

    def conversation_messages(self, cid):
        return self.convos.get(cid, {}).get("messages", [])

    def _is_local_model(self):
        return False

    def smart_report(self):
        return "groq: ok\ngemini: rate limited"


agent = FakeAgent(TMP / "fake")
rec = qol.recovery(agent, CASES[0][0])
check("alternatives: ready models only, the failing one left out, on-this-computer first",
      [a["name"] for a in rec["alternatives"]] == ["local", "gemini"] and rec["alternatives"][0]["local"] and rec["has_local"], rec["alternatives"])
agent2 = FakeAgent(TMP / "fake2")
agent2.provider_configured = lambda n: n == "groq"
rec2 = qol.recovery(agent2, CASES[10][0])
check("no other model ready: no 'another model' / 'local' buttons, Connections offered instead",
      "switch" not in rec2["actions"] and "local" not in rec2["actions"] and "connections" in rec2["actions"], rec2["actions"])

# =============================================================================== interrupted turns
print("interrupted turns")
inf = qol.Inflight(qol.data_dir(agent))
inf.start("write my essay", "a", "groq")
check("this engine's own turn in flight is not 'interrupted'", inf.interrupted() is None)
raw = json.loads(inf.path.read_text())
raw["pid"] = raw["pid"] + 99999
inf.path.write_text(json.dumps(raw))
it = inf.interrupted()
check("a turn a previous engine never finished is offered again", it and it["prompt"] == "write my essay" and it["convo"] == "a", it)
inf.dismiss()
check("dismiss forgets it", inf.interrupted() is None and not inf.path.exists())

# =============================================================================== steering
print("steering")
qol.STEERS.clear()
qol.add_steer("also add a test")
pushed = []


class FakeState:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = None
        self.progress_chat_id = "c1"
        self.progress = []
        self.agent = agent
        self.chat_request_lock = threading.Lock()
        self.loop = None

    def push_progress(self, cid, ev, text):
        pushed.append((ev, text))
        self.progress.append({"id": len(self.progress) + 1, "event": ev, "text": text})

    def try_busy(self):
        return [] if not self.chat_request_lock.locked() else None

    def release_busy(self, x):
        pass


fs = FakeState()
agent.messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]})
check("a steer waits while tool results are still due (never splits a tool call)", qol.inject_steers(agent, fs) == 0 and len(qol.STEERS) == 1)
agent.messages.append({"role": "tool", "tool_call_id": "1", "content": "ok"})
n = qol.inject_steers(agent, fs)
check("at the next step the steer joins the conversation as the user's words",
      n == 1 and agent.messages[-1]["role"] == "user" and "also add a test" in agent.messages[-1]["content"]
      and agent.messages[-1]["content"].startswith(qol.STEER_PREFIX), agent.messages[-1])
check("the window is told it was read (a 'steer' progress event with its id)",
      pushed and pushed[-1][0] == "steer" and json.loads(pushed[-1][1])["text"] == "also add a test", pushed)
s = qol.add_steer("drop me")
check("a waiting steer can be taken back", qol.cancel_steer(s["id"]) and not qol.STEERS)

# =============================================================================== approvals for this session
print("allow for this session")
ev = threading.Event()
fs.pending = {"id": "t1", "tool": "run_command", "details": "pytest -q", "event": ev, "approved": False}
code, out = qol.allow_for_session(fs, "t1")
check("Allow for this session approves the waiting action", code == 200 and ev.is_set() and fs.pending["approved"])
check("the same exact action is allowed without asking again", qol.session_allows("run_command", "pytest  -q"))
check("a different action still asks", not qol.session_allows("run_command", "rm -rf build"))
fs.pending = {"id": "t2", "tool": "delete_file", "details": "a.txt", "event": threading.Event(), "approved": False}
code, out = qol.allow_for_session(fs, "t2")
check("never for policy's always-ask actions (delete_file)", code == 400 and out.get("never") and not fs.pending["approved"])
check("connector writes are never allowed for a session either", "email" in qol.never_for_session() or len(qol.never_for_session()) > 4,
      sorted(qol.never_for_session()))
code, out = qol.allow_for_session(fs, "wrong")
check("a stale approval id is refused", code == 404)

# =============================================================================== install (wrapping)
print("install into the bridge state")


class WrapState(FakeState):
    async def request_chat(self, prompt):
        it_now = json.loads((Path(agent.DATA_DIR) / "qol" / "inflight.json").read_text())
        self.seen_inflight = it_now["prompt"]
        agent._trim_context()     # one agent step
        if prompt == "fail":
            return {"ok": False, "error": CASES[2][0]}
        return {"ok": True, "response": "done"}

    async def request_approval(self, tool, details):
        return False


trimmed = []
agent._trim_context = lambda: trimmed.append(1)
ws = WrapState()
qol.install(ws, agent)
check("install is idempotent", qol.install(ws, agent) is False)
qol.add_steer("late steer")
agent.messages[:] = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]
res = asyncio.run(ws.request_chat("hello"))
check("the turn is on disk while it runs, and gone after", ws.seen_inflight == "hello" and not (Path(agent.DATA_DIR) / "qol" / "inflight.json").exists())
check("the agent's _trim_context is wrapped: a steer sent mid-turn reached the model", trimmed and "late steer" in agent.messages[-1]["content"])
qol.add_steer("never read")
agent._trim_context = lambda: None   # this turn takes no further step
res = asyncio.run(ws.request_chat("hello again"))
check("a steer the agent never read comes back to the window (steers_left)", res.get("steers_left") == ["never read"], res)
res = asyncio.run(ws.request_chat("fail"))
check("a failed turn carries its recovery choices", res["recovery"]["kind"] == "quota" and "switch" in res["recovery"]["actions"], res)
check("a session-allowed action is not asked again (request_approval wrapped)",
      asyncio.run(ws.request_approval("run_command", "pytest -q")) is True and asyncio.run(ws.request_approval("run_command", "ls")) is False)

# =============================================================================== context + compact
print("context meter + summarize now")
import condenser  # noqa: E402

agent.messages[:] = [{"role": "system", "content": "s"}] + [{"role": "user", "content": "x" * 30000}] * 8
c = qol.context(agent)
check("the context meter compares the chat with the condenser's limit", c["percent"] >= 75 and c["level"] in ("long", "full")
      and c["max_chars"] == condenser.limits()[1], c)
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()


async def fake_view(requested=False):
    agent._CONDENSE_CACHE.update({"start": 1, "end": 7, "note": {"role": "user", "content": "[LOKI context summary] short"}})
    return []


agent._model_view = fake_view
fs.loop = loop
code, out = qol.compact(fs)
check("Summarize now condenses through the agent's own condenser and reports before/after",
      code == 200 and out["condensed"] and out["after"]["percent"] < out["before"]["percent"], out)
fs.chat_request_lock.acquire()
code, out = qol.compact(fs)
fs.chat_request_lock.release()
check("Summarize now waits while LOKI is busy (409)", code == 409)

# =============================================================================== search, pins, notify, diagnose
print("search, pins, notifications, what happened")
s = qol.search(agent, "moon pulls")
check("search finds words inside messages, with a snippet", s["results"] and s["results"][0]["id"] == "a" and "moon" in s["results"][0]["snippet"].lower(), s)
check("search finds chat names", any(r["where"] == "title" and r["id"] == "b" for r in qol.search(agent, "budget")["results"]))
check("an empty search finds nothing", qol.search(agent, "  ")["results"] == [])
check("pin + unpin", qol.set_pin(agent, "b", True)["pins"] == ["b"] and qol.set_pin(agent, "a", True)["pins"] == ["a", "b"]
      and qol.set_pin(agent, "b", False)["pins"] == ["a"])
n = qol.notify("LOKI finished", "your essay", run=False)
check("a notification never puts the text inside a script (argv / env only)", n["ok"] and ("argv" not in n or "your essay" in n["argv"]), n)
fs.progress = [{"event": "tool", "text": "read_file a.txt"}, {"event": "error", "text": CASES[0][0]}]
d = qol.diagnose(fs)
check("What happened lists the errors, steps, model and a recovery", d["errors"] and d["recovery"]["kind"] == "rate_limit"
      and d["using"] == "groq" and "rate limited" in d["providers"], d)

# =============================================================================== the real bridge
print("the real BridgeHTTPServer + the real loki module")
import loki  # noqa: E402
import loki_bridge  # noqa: E402

loki_bridge.PORT = 0
loki_bridge.UI_DIR = REPO / "app" / "ui"
bstate = loki_bridge.BridgeState(loki, "qol-secret")
bstate.loop = loop
bstate.chat_lock = asyncio.run_coroutine_threadsafe(asyncio.sleep(0, result=asyncio.Lock()), loop).result()
gate = threading.Event()


async def fake_run_agent(prompt):
    loki._trim_context()                         # the real one, wrapped by qol.install
    await asyncio.to_thread(gate.wait, 10)
    loki._trim_context()
    return "answer to " + prompt


loki.run_agent = fake_run_agent
qol.STEERS.clear()
qol.install(bstate, loki)
bserver = loki_bridge.BridgeHTTPServer(bstate)
PORT = bserver.server_address[1]
loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def call(method, path, body=None, token="qol-secret"):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")


code, body = call("GET", "/qol/state", token="nope")
check("/qol routes need LOKI's token", code == 401)
code, body = call("GET", "/qol/state")
check("GET /qol/state", code == 200 and body["ok"] and "delete_file" in body["never_session"] and body["busy"] is False, body)
code, body = call("POST", "/qol/steer", {"text": "x"})
check("steering while idle says: send it normally", code == 409 and body.get("idle"))
code, body = call("POST", "/qol/classify", {"error": CASES[4][0]})
check("POST /qol/classify", code == 200 and body["kind"] == "auth", body)
result = {}
t = threading.Thread(target=lambda: result.update(call("POST", "/chat", {"message": "build the page"})[1]))
t.start()
for _ in range(100):
    if bstate.chat_request_lock.locked():
        break
    time.sleep(0.02)
time.sleep(0.2)
code, st = call("GET", "/qol/state")
code2, sbody = call("POST", "/qol/steer", {"text": "make it blue"})
gate.set()
t.join(15)
check("while LOKI answers: /qol/state says busy and a steer is accepted", st["busy"] and code2 == 200 and sbody["ok"], (st, sbody))
check("the steer reached the real conversation at the agent's next step",
      any(qol.STEER_PREFIX in str(m.get("content")) and "make it blue" in str(m.get("content")) for m in loki.messages[-4:]), loki.messages[-3:])
check("the /chat answer came back through the wrapped request_chat", result.get("ok") and result.get("response") == "answer to build the page", result)
code, prog = call("GET", "/progress?after=0")
check("the window can see the steer was read (progress event)", any(e["event"] == "steer" for e in prog["progress"]), prog)
code, body = call("GET", "/qol/context")
check("GET /qol/context on the real agent", code == 200 and body["ok"] and body["max_chars"] > 0, body)
code, body = call("GET", "/qol/search?q=build")
check("GET /qol/search", code == 200 and body["ok"])
code, body = call("POST", "/qol/pin", {"id": "x1", "pinned": True})
check("POST /qol/pin", code == 200 and body["pins"][0] == "x1")
code, body = call("GET", "/qol/diagnose")
check("GET /qol/diagnose", code == 200 and body["ok"] and "steps" in body)

# =============================================================================== LOKI Studio (small)
print("LOKI Studio")
studio_js = (REPO / "studio" / "ui" / "studio.js").read_text(encoding="utf-8")
check("Studio: a failed send puts the message back in the box, and the draft is kept",
      "Your message is back in the box" in studio_js and 'localStorage.getItem("studio-draft")' in studio_js)
check("Studio: says when its own server stops answering (and keeps retrying)", "server-down" in studio_js
      and "server-down" in (REPO / "studio" / "ui" / "studio.css").read_text(encoding="utf-8"))
check("ship.py runs this suite", '"test_qol"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
check("index.html loads qol.js + qol.css (the health gate needs every window file committed)",
      all(x in (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8") for x in ("/ui/qol.js", "/ui/qol.css"))
      and (REPO / "app" / "ui" / "qol.js").is_file() and (REPO / "app" / "ui" / "qol.css").is_file())

# =============================================================================== the window
print("the window (headless Chromium, scripted engine)")
try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None

UI = REPO / "app" / "ui"
ENG = {"chat_mode": "ok", "posts": [], "chats": [], "down": False, "ticket": None, "progress": [], "interrupted": True,
       "slow_s": 2.5, "steer_id": 0}


def fake(path, method, body):
    if path == "/health":
        return {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "", "route": [],
                "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []}
    if path == "/conversations":
        return {"ok": True, "active": "a", "conversations": [{"id": "a", "title": "First chat", "count": 2}, {"id": "b", "title": "Pinned chat", "count": 2}]}
    if path == "/conversations/switch":
        return {"ok": True, "active": body.get("id"), "messages": [{"role": "user", "content": "a question about tides"},
                {"role": "assistant", "content": "the moon"}], "conversations": fake("/conversations", "GET", {})["conversations"]}
    if path == "/conversations/messages":
        return {"ok": True, "messages": [{"role": "user", "content": "old question about tides"}, {"role": "assistant", "content": "old answer"}]}
    if path == "/models":
        return {"ok": True, "current": "groq", "entries": [{"name": "groq", "label": "Groq", "group": "free", "ready": True},
                                                          {"name": "local", "label": "Qwen here", "group": "local", "ready": True}],
                "groups": [{"id": "local", "label": "On this computer"}, {"id": "free", "label": "Free"}], "resolved": "groq", "resolved_label": "Groq"}
    if path == "/model":
        return {"ok": True, "current": body.get("model"), "resolved": body.get("model")}
    if path == "/qol/state":
        it = {"prompt": "the essay I asked for", "convo": "a", "t": time.time() - 60} if ENG["interrupted"] else None
        return {"ok": True, "interrupted": it, "pins": ["b"], "never_session": ["delete_file"], "busy": False, "session_rules": []}
    if path == "/qol/context":
        return {"ok": True, "level": "long", "percent": 82, "enabled": True}
    if path == "/qol/search":
        return {"ok": True, "results": [{"id": "b", "title": "Pinned chat", "where": "message", "role": "user", "snippet": "about tides", "index": 0}]}
    if path == "/qol/alternatives":
        return {"ok": True, "alternatives": [{"name": "local", "label": "Qwen here", "local": True}]}
    if path == "/qol/steer":
        ENG["steer_id"] += 1
        ENG["progress"].append({"id": 50 + ENG["steer_id"], "event": "steer", "text": json.dumps({"id": ENG["steer_id"], "text": body.get("text")})})
        return {"ok": True, "id": ENG["steer_id"]}
    if path == "/progress":
        return {"ok": True, "chat_id": "c1", "progress": list(ENG["progress"])}
    if path == "/approval" and method == "GET":
        return {"ok": True, "approval": ENG["ticket"]}
    if path == "/qol/classify":
        return {"ok": True, **qol.recovery(agent, body.get("error", ""))}
    return {"ok": True}


SHOTS = os.getenv("LOKI_SUITE_SCREENS", "")


async def shot(page, name):
    if SHOTS:
        await page.screenshot(path=str(Path(SHOTS) / ("qol-%s.png" % name)))


async def browser_part():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP the window part: no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1240, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        async def route(r):
            url = r.request.url.split("8898", 1)[1]
            path = url.split("?")[0].split("#")[0]
            method = r.request.method
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/"):
                f = UI / path[4:]
                return await (r.fulfill(path=str(f)) if f.is_file() else r.fulfill(json={"ok": True}))
            body = {}
            if r.request.post_data:
                try:
                    body = json.loads(r.request.post_data)
                except ValueError:
                    body = {}
            if method == "POST":
                ENG["posts"].append((path, body))
            if ENG["down"]:                       # the engine is gone: every call fails
                return await r.abort("connectionreset")
            if path == "/chat":
                ENG["chats"].append(body.get("message"))
                mode = ENG["chat_mode"]
                if mode == "error":
                    err = "[model error] groq answered HTTP 429: Rate limit reached. Please try again in 30s."
                    return await r.fulfill(json={"ok": False, "error": err, "recovery": qol.recovery(agent, err)})
                if mode == "abort":
                    ENG["down"] = True
                    return await r.abort("connectionreset")
                if mode == "slow":
                    await asyncio.sleep(ENG["slow_s"])
                return await r.fulfill(json={"ok": True, "response": "answer to " + str(body.get("message"))})
            return await r.fulfill(json=fake(path, method, body))

        await page.route("http://127.0.0.1:8898/**", route)
        await page.goto("http://127.0.0.1:8898/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_selector("#qol-interrupted", timeout=5000)
        check("start: a message LOKI was answering when it closed is offered again",
              "the essay I asked for" in await page.inner_text("#qol-interrupted"))
        rows = await page.eval_on_selector_all("#conversations .convo .open", "ns => ns.map(n => n.textContent)")
        check("start: the pinned chat is at the top, with its pin icon", rows[:1] == ["Pinned chat"]
              and await page.query_selector("#conversations .convo.pinned .qol-pin[data-tip-name]") is not None, rows)
        check("icons with tooltips: Search chats (sidebar) and Shortcuts (top bar)",
              await page.get_attribute("#qol-search-btn", "data-tip-name") == "Search chats"
              and await page.query_selector("#qol-search-btn svg") is not None
              and await page.query_selector("#qol-prefs-btn svg") is not None)
        await page.dblclick("#conversations .convo:nth-child(2) .open")
        await page.fill("#conversations .qol-rename", "Renamed chat")
        await page.press("#conversations .qol-rename", "Enter")
        await page.wait_for_timeout(200)
        check("double-click a chat to rename it", any(pth == "/conversations/rename" and b.get("title") == "Renamed chat" for pth, b in ENG["posts"]))
        await shot(page, "start")
        await page.click("#qol-interrupted button:has-text('Dismiss')")
        ENG["interrupted"] = False
        check("Dismiss tells the engine", any(pth == "/qol/interrupted/dismiss" for pth, _ in ENG["posts"]))

        # ---- a failed answer: a card with choices, the message back in the box
        ENG["chat_mode"] = "error"
        if await page.is_visible("#summon"):
            await page.click("#summon")
        await page.fill("#prompt", "hello there")
        await page.press("#prompt", "Enter")
        await page.wait_for_selector(".qol-card.recovery.kind-rate_limit", timeout=5000)
        card = await page.inner_text(".qol-card.recovery.kind-rate_limit")
        check("a rate limit shows a card with choices instead of a dead end", "slow down" in card and "Use another model" in card, card)
        wait_text = await page.inner_text(".qol-card.recovery [data-action='wait']")
        check("it counts down and tries again by itself", "Trying again in" in wait_text, wait_text)
        await shot(page, "recovery")
        await page.click(".qol-card.recovery [data-action='wait']")     # cancel the countdown
        check("the countdown can be cancelled", "Trying again" not in await page.inner_text(".qol-card.recovery [data-action='wait']"))
        check("the failed message is back in the box", await page.input_value("#prompt") == "hello there")
        await page.click(".qol-card.recovery [data-action='switch']")
        check("'Use another model' lists the ready ones", await page.is_visible(".qol-card.recovery .qol-alts") and
              len(await page.query_selector_all(".qol-card.recovery .qol-alts button")) == 2)
        await page.click(".qol-card.recovery .qol-alts button")
        await page.wait_for_timeout(300)
        check("picking one switches model and sends it again", any(pth == "/model" and b.get("model") == "local" for pth, b in ENG["posts"])
              and ENG["chats"][-1] == "hello there", ENG["chats"])
        await page.wait_for_timeout(300)

        # ---- queue + steer while LOKI works
        ENG["chat_mode"] = "slow"
        ENG["progress"] = []
        await page.fill("#prompt", "first job")
        await page.press("#prompt", "Enter")
        await page.wait_for_timeout(300)
        await page.fill("#prompt", "second job")
        await page.press("#prompt", "Enter")
        await page.wait_for_selector("#qol-queue .qol-q.queued", timeout=3000)
        check("Enter while LOKI works queues the message (nothing lost)", "second job" in await page.inner_text("#qol-queue")
              and await page.input_value("#prompt") == "")
        check("a queued message has Steer / Send now / Edit / Remove icons with tooltips",
              len(await page.query_selector_all("#qol-queue .qol-q.queued button[data-tip-name] svg")) == 4)
        await page.fill("#prompt", "make it blue")
        await page.press("#prompt", "Control+Enter")
        await shot(page, "queue")
        await page.wait_for_selector(".turn.user.steered", timeout=4000)
        check("Ctrl/Cmd+Enter steers: sent to the engine, shown as Steered once read",
              any(pth == "/qol/steer" and b.get("text") == "make it blue" for pth, b in ENG["posts"])
              and "make it blue" in await page.inner_text(".turn.user.steered"))
        for _ in range(60):
            if "second job" in ENG["chats"]:
                break
            await page.wait_for_timeout(150)
        check("when LOKI is free the queued message goes out by itself", ENG["chats"][-1] == "second job", ENG["chats"])
        await page.wait_for_selector("#qol-context:not([hidden])", timeout=5000)
        check("a long chat shows the context bar with Summarize now", "82%" in await page.inner_text("#qol-context")
              and "Summarize now" in await page.inner_text("#qol-context"))
        for _ in range(40):
            if not await page.evaluate("state.busy"):
                break
            await page.wait_for_timeout(150)

        # ---- the engine drops the connection
        ENG["chat_mode"] = "abort"
        ENG["progress"] = []
        await page.fill("#prompt", "a message in flight")
        await page.press("#prompt", "Enter")
        await page.wait_for_selector("#qol-conn:not([hidden])", timeout=5000)
        await page.wait_for_timeout(300)
        await shot(page, "disconnected")
        txt = await page.inner_text("#qol-conn")
        check("connection lost: a banner with Reconnect now, Copy my message, What happened",
              "not answering" in txt and "Reconnect now" in txt and "What happened" in txt, txt)
        check("connection lost: it retries by itself with a countdown", "Trying again in" in txt, txt)
        check("connection lost: the cut-off message gets a card and goes back in the box",
              await page.query_selector(".qol-card.recovery.kind-engine") is not None and await page.input_value("#prompt") == "a message in flight")
        ENG["down"] = False
        ENG["chat_mode"] = "ok"
        btn = await page.query_selector("#qol-conn button.send:not([hidden])")
        if btn:                                   # LOKI may already have reconnected by itself
            await btn.click(timeout=3000)
        await page.wait_for_selector("#qol-conn.good", timeout=5000)
        check("reconnect: the banner says it is back", "again" in await page.inner_text("#qol-conn"))
        await page.wait_for_timeout(400)

        # ---- approvals
        ENG["ticket"] = {"id": "tk1", "tool": "run_command", "details": "pytest -q"}
        await page.wait_for_selector(".approval .qol-allow-session", timeout=5000)
        await page.click(".approval .qol-allow-session")
        await page.wait_for_timeout(300)
        check("approvals: Allow for this session", any(pth == "/qol/approval" and b.get("id") == "tk1" for pth, b in ENG["posts"])
              and "until it restarts" in await page.inner_text(".approval"))
        ENG["ticket"] = None

        # ---- shortcuts, search, find, prefs
        await page.click("#transcript")
        await page.keyboard.press("Control+K")
        await page.wait_for_selector("#qol-search:not([hidden])", timeout=3000)
        await page.fill("#qol-search input", "tides")
        await page.wait_for_selector("#qol-search .qol-hit-row", timeout=3000)
        check("Ctrl/Cmd+K searches every chat's messages", "about tides" in await page.inner_text("#qol-search .qol-results"))
        await page.press("#qol-search input", "Enter")
        await page.wait_for_selector(".qol-find:not([hidden])", timeout=3000)
        check("opening a hit finds the words in that chat", await page.query_selector(".turn.qol-hit") is not None
              and "/" in await page.inner_text(".qol-find-count"))
        await page.press(".qol-find input", "Escape")
        await page.keyboard.press("Control+/")
        await page.wait_for_selector("#qol-prefs:not([hidden])", timeout=3000)
        await shot(page, "shortcuts")
        n_rows = len(await page.query_selector_all("#qol-prefs .qol-key-row"))
        check("Ctrl/Cmd+/ opens Shortcuts and chat comfort (%d shortcuts)" % n_rows, n_rows >= 12)
        await page.click("#qol-prefs .qol-key-row:first-child .qol-combo")
        await page.keyboard.press("Control+Shift+Y")
        saved = await page.evaluate("JSON.parse(localStorage.getItem('loki-qol-prefs')||'{}').shortcuts")
        check("a shortcut can be changed (New chat -> Ctrl+Shift+Y)", saved.get("newChat") == "Mod+Shift+Y", saved)
        await page.click("#qol-prefs .qol-key-row:nth-child(2) .qol-combo")
        await page.keyboard.press("Control+Shift+Y")
        clash = await page.inner_text("#qol-prefs .qol-key-row:nth-child(2) .qol-combo")
        check("the same keys cannot belong to two actions", "already" in clash, clash)
        await page.keyboard.press("Escape")
        await page.keyboard.press("Escape")
        md = await page.evaluate("LokiQol.chatMarkdown()")
        check("copy chat as Markdown", "**You:**" in md and "**LOKI:**" in md, md[:200])

        # ---- draft kept over a reload
        await page.click("#summon") if await page.is_visible("#summon") else None
        await page.fill("#prompt", "an unsent draft")
        await page.dispatch_event("#prompt", "input")
        await page.wait_for_timeout(500)
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_timeout(800)
        check("an unsent draft survives a reload", await page.input_value("#prompt") == "an unsent draft")
        check("no script errors in the whole run", not errors, errors[:5])
        await browser.close()


if async_playwright is None:
    print("SKIP the window part: no Playwright here")
else:
    asyncio.run(browser_part())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
