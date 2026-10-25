"""Research round 3, offline (docs/integrations/research-2026-10-17b.md): what the best personal-AI apps have.

  chats: export (Markdown / page / JSON) and import (ChatGPT mapping graphs with branches, Claude, Open WebUI,
  LibreChat, LOKI, Markdown); edit / regenerate (cut before a message) and branch (a new chat) on LOKI's real
  conversation store; the prompt library ({{variables}}, starters, own prompts); compare models side by side
  + an Elo arena; artifacts (sandboxed preview pages, their CSP, versions); Home Assistant (fake HA server:
  names resolved, services, locks/covers, errors, writes always ask, hidden until set up); everyday answers
  (fake Open-Meteo / RSS / LibreTranslate); picture edits with real Pillow (rembg + Real-ESRGAN faked);
  Your data (inventory, backup without secrets, restore with unsafe zips refused, clear); the loki.py tool
  block; every route over the REAL bridge server; and the window in headless Chromium (LOKI_SUITE_SHOTS=1 saves screens in
  docs/operations/screens/research3-*.png) where Playwright + Chromium are installed.

    python tests/test_research3.py
"""
from __future__ import annotations

import asyncio
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-research3-"))
DATA = TMP / "data"
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
os.environ["LOKI_BACKUP_DIR"] = str(TMP / "backups")
for _k in ("HA_URL", "HA_TOKEN", "LOKI_HOME_CITY", "LOKI_NEWS_FEED", "LOKI_LIBRETRANSLATE_URL", "LOKI_REALESRGAN", "LOKI_JOB_ID"):
    os.environ.pop(_k, None)

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:700],)))


import artifacts  # noqa: E402
import chat_io  # noqa: E402
import chat_plus  # noqa: E402
import compare  # noqa: E402
import conn_home  # noqa: E402
import connectors  # noqa: E402
import everyday  # noqa: E402
import image_tools  # noqa: E402
import policy  # noqa: E402
import prompt_library  # noqa: E402
import your_data  # noqa: E402

# =============================================================================== chat import / export
print("chat import / export")
CHATGPT = [{
    "title": "Paris trip", "create_time": 1760000000.5, "current_node": "a2",
    "mapping": {
        "root": {"id": "root", "parent": None, "children": ["sys"], "message": None},
        "sys": {"id": "sys", "parent": "root", "children": ["u1"],
                "message": {"author": {"role": "system"}, "content": {"content_type": "text", "parts": ["You are ChatGPT"]}}},
        "u1": {"id": "u1", "parent": "sys", "children": ["a1", "a2"],
               "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["Plan 2 days in Paris"]}}},
        "a1": {"id": "a1", "parent": "u1", "children": [],
               "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["OLD branch answer"]}}},
        "a2": {"id": "a2", "parent": "u1", "children": [],
               "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["Day 1: Louvre. ", "Day 2: Orsay."]}}},
    }}, {"title": "Empty", "mapping": {"r": {"id": "r", "parent": None, "children": [], "message": None}}},
    {"title": "No current node", "mapping": {
        "r": {"id": "r", "parent": None, "children": ["u"], "message": None},
        "u": {"id": "u", "parent": "r", "children": ["x", "y"], "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]}}},
        "x": {"id": "x", "parent": "u", "children": [], "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["first"]}}},
        "y": {"id": "y", "parent": "u", "children": [], "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["last"]}}}}}]
out = chat_io.parse(json.dumps(CHATGPT), "conversations.json")
check("a ChatGPT export is recognised", out.get("ok") and out["source"] == "chatgpt", out)
paris = out["chats"][0]
check("ChatGPT: the visible branch (current_node) is followed, the system turn and the old branch left out",
      [m["content"] for m in paris["messages"]] == ["Plan 2 days in Paris", "Day 1: Louvre. \nDay 2: Orsay."]
      or [m["content"] for m in paris["messages"]] == ["Plan 2 days in Paris", "Day 1: Louvre. Day 2: Orsay."], paris)
check("ChatGPT: title and time kept", paris["title"] == "Paris trip" and int(paris["created"]) == 1760000000)
check("ChatGPT: an empty chat is skipped and counted", out["skipped"] == 1 and len(out["chats"]) == 2, out["skipped"])
check("ChatGPT without current_node follows the last child", out["chats"][1]["messages"][-1]["content"] == "last")
CLAUDE = [{"name": "Recipe", "created_at": "2026-05-01T10:00:00Z", "chat_messages": [
    {"sender": "human", "text": "A soup for 4?"},
    {"sender": "assistant", "text": "", "content": [{"type": "text", "text": "Leek and potato soup."}, {"type": "tool_use", "input": {}}]}]}]
out = chat_io.parse(json.dumps(CLAUDE))
check("a Claude export is recognised, content blocks read, tool blocks dropped", out.get("ok") and out["source"] == "claude"
      and out["chats"][0]["messages"] == [{"role": "user", "content": "A soup for 4?"}, {"role": "assistant", "content": "Leek and potato soup."}], out)
check("Claude: ISO time read", abs(out["chats"][0]["created"] - 1777629600) < 2, out["chats"][0]["created"])
WEBUI = [{"chat": {"title": "Webui", "history": {"currentId": "m3", "messages": {
    "m1": {"id": "m1", "parentId": None, "role": "user", "content": "q"},
    "m2": {"id": "m2", "parentId": "m1", "role": "assistant", "content": "wrong"},
    "m3": {"id": "m3", "parentId": "m1", "role": "assistant", "content": "right"}}}}},
    {"chat": {"title": "Flat", "messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}}]
out = chat_io.parse(json.dumps(WEBUI))
check("an Open WebUI export (history tree and flat) is read along currentId", out.get("ok") and out["source"] == "openwebui"
      and [m["content"] for m in out["chats"][0]["messages"]] == ["q", "right"] and len(out["chats"][1]["messages"]) == 2, out)
LIBRE = {"conversationId": "c1", "title": "Libre", "messages": [{"isCreatedByUser": True, "text": "hey"},
                                                                {"isCreatedByUser": False, "text": "hello"}]}
out = chat_io.parse(json.dumps(LIBRE))
check("a LibreChat export is read", out.get("ok") and out["source"] == "librechat" and out["chats"][0]["messages"][1]["role"] == "assistant", out)
convo = {"id": "x", "title": "Plan <b>", "created": 1760000000, "messages": [
    {"role": "user", "content": "Make a list"}, {"role": "assistant", "content": "- one\n- two\n```py\nprint('<x>')\n```"},
    {"role": "tool", "content": "ignored"}]}
md = chat_io.export_markdown(convo)
check("Markdown export has a title and You / LOKI sections, no tool turns", md.startswith("# Plan <b>") and "## You" in md
      and "## LOKI" in md and "ignored" not in md, md)
back = chat_io.parse(md, "chat.md")
check("a Markdown export imports back to the same turns", back.get("ok") and [m["content"] for m in back["chats"][0]["messages"]]
      == ["Make a list", "- one\n- two\n```py\nprint('<x>')\n```"] and back["chats"][0]["title"] == "Plan <b>", back)
page = chat_io.export_html(convo)
check("the HTML export is one escaped page with no script", "<script" not in page.lower() and "&lt;x&gt;" in page
      and "Plan &lt;b&gt;" in page, page[:300])
js = chat_io.export_json([convo])
again = chat_io.parse(js)
check("LOKI's JSON export imports back", again.get("ok") and again["source"] == "loki" and len(again["chats"][0]["messages"]) == 2, again)
check("'User:' / 'Assistant:' transcripts import", chat_io.parse("User: hi there\nAssistant: hello\nUser: bye", "t.txt")["chats"][0]["messages"][-1]
      == {"role": "user", "content": "bye"})
check("empty, broken and unknown files say why", not chat_io.parse("", "x")["ok"] and "JSON" in chat_io.parse("{bad", "x.json")["error"]
      and "not a ChatGPT" in chat_io.parse(json.dumps([{"foo": 1}]))["error"])
check("file names are safe", "/" not in chat_io.filename_for("a/b\\c: d", "md") and chat_io.filename_for("", "md").startswith("chat-"))

# =============================================================================== the loki tool block + real conversations
print("loki: conversations, tools")
import loki  # noqa: E402

loki.CONVERSATIONS.clear()
cid = loki.new_conversation("")
loki.messages.extend([{"role": "user", "content": "What is 2+2?"}, {"role": "assistant", "content": "4"},
                      {"role": "user", "content": "And 3+3?"}, {"role": "assistant", "content": "6"},
                      {"role": "user", "content": "And 3+3?"}, {"role": "assistant", "content": "six"}])
loki.save_history()
check("locate finds the n-th equal message", chat_plus.locate(loki.CONVERSATIONS[cid]["messages"], "user", " And  3+3? ", 1) == 4)
check("locate: a missing message is -1", chat_plus.locate(loki.CONVERSATIONS[cid]["messages"], "user", "never said", 0) == -1)
cut = chat_plus.cut_before(loki, cid, "And 3+3?", 1)
check("edit/regenerate cuts the chat before that message (stored and the model's view)", cut["ok"]
      and [m["content"] for m in cut["messages"]] == ["What is 2+2?", "4", "And 3+3?", "6"]
      and [m["content"] for m in loki.messages if m["role"] != "system"] == ["What is 2+2?", "4", "And 3+3?", "6"], cut)
br = chat_plus.branch(loki, cid, "assistant", "4", 0)
check("branch makes a new open chat up to that answer; the original is unchanged", br["ok"] and br["id"] != cid
      and [m["content"] for m in br["messages"]] == ["What is 2+2?", "4"] and loki.active_conversation == br["id"]
      and len(loki.CONVERSATIONS[cid]["messages"]) == 4 and loki.CONVERSATIONS[br["id"]]["branched_from"] == cid, br)
check("branch / cut of a message that is not there say so", not chat_plus.branch(loki, cid, "assistant", "nope")["ok"]
      and not chat_plus.cut_before(loki, cid, "nope")["ok"])
ids = chat_plus.add_chats(loki, chat_io.parse(json.dumps(CHATGPT))["chats"])
check("imported chats join the list with new ids and keep their source", len(ids) == 2
      and all(loki.CONVERSATIONS[i].get("imported_from") == "chatgpt" for i in ids)
      and any(c["title"] == "Paris trip" for c in loki.list_conversations()))
ex = chat_plus.export(loki, cid, "md")
check("export of one chat (md) and of all (json)", ex["ok"] and ex["name"].endswith(".md") and "What is 2+2?" in ex["text"]
      and chat_plus.export(loki, "", "json", everything=True)["count"] == len(loki.CONVERSATIONS))
for name in ("home", "weather", "news", "world_clock", "translate", "edit_image"):
    check("tool %s is registered with a schema" % name, name in loki.LOCAL_TOOLS
          and any(s["function"]["name"] == name for s in loki.TOOL_SCHEMAS) and name in loki.MODEL_TOOL_NAMES)
check("categories: everyday and home are new, edit_image is creative and modifies",
      loki.TOOL_CATEGORIES["everyday"] == ["weather", "news", "world_clock", "translate"] and loki.TOOL_CATEGORIES["home"] == ["home"]
      and "edit_image" in loki.TOOL_CATEGORIES["creative"] and "edit_image" in loki.MODIFYING)
check("Home Assistant is hidden from the model until it is set up", not loki._tool_enabled("home") and loki._tool_enabled("weather"))
check("home writes always ask (never decidable); reads are allowed",
      loki.POLICY.tool_call("home", {"action": "turn_off", "entity": "x"}).decision == policy.ASK
      and loki.POLICY.tool_call("home", {"action": "turn_off"}).decidable is False
      and loki.POLICY.tool_call("home", {"action": "status"}).decision == policy.ALLOW)
check("every connector write action is in ACTION_ALWAYS_ASK (home included)",
      all(set(w) <= policy.ACTION_ALWAYS_ASK.get(t, set()) for t, w in connectors.write_actions().items()) and "home" in connectors.write_actions())

# =============================================================================== prompt library
print("prompt library")
lib = prompt_library.Library(TMP / "p" / "prompts.json")
allp = lib.all()
check("starter prompts are there with their blanks", len(allp) >= 10 and lib.get("reply")["variables"] == [
    {"name": "tone", "default": "friendly and clear"}, {"name": "email", "default": ""}], lib.get("reply"))
f = prompt_library.fill("Hi {{name}}, {{tone|warm}} on {{weekday}} {{date}}. {{clipboard}} {{x}}", {"Name": "Ana"},
                        now=time.mktime((2026, 10, 17, 9, 0, 0, 0, 0, -1)), clipboard="CLIP")
check("fill: values (any case), defaults, date/weekday/clipboard; missing ones listed and kept",
      f["text"] == "Hi Ana, warm on Saturday 2026-10-17. CLIP {{x}}" and f["missing"] == ["x"] and not f["ok"], f)
check("variables() leaves out the self-filling ones", [v["name"] for v in prompt_library.variables("{{date}} {{a}} {{A}} {{b|1}}")] == ["a", "b"])
check("save: a name is needed, text is needed", not lib.save("", "x")["ok"] and not lib.save("n", " ")["ok"])
s = lib.save("My Standup!", "Yesterday: {{y}}", tags="work, daily")
check("save: own prompt, slugged name, tags", s["ok"] and s["prompt"]["name"] == "my-standup" and s["prompt"]["tags"] == ["work", "daily"]
      and not s["prompt"]["builtin"], s)
lib.save("reply", "My own reply prompt {{email}}")
check("editing a starter makes it the owner's copy", lib.get("reply")["builtin"] is False and lib.get("reply")["text"].startswith("My own"))
lib.delete("summary")
check("deleting a starter hides it; deleting an unknown one says so", lib.get("summary") is None and not lib.delete("nope-x")["ok"])
lib.used("my-standup"); lib.used("my-standup")
check("used prompts come first; search finds by title/tag", lib.all()[0]["name"] == "my-standup" and lib.all()[0]["uses"] == 2
      and lib.search("trip")[0]["name"] == "trip" and lib.search("daily")[0]["name"] == "my-standup")

# =============================================================================== compare + arena
print("compare models")


async def fake_ask(name, prompt):
    if name == "bad":
        raise RuntimeError("401 no key")
    if name == "slow":
        await asyncio.sleep(5)
    await asyncio.sleep(0.05)
    return "<think>hmm</think>%s says %s" % (name, prompt) if name == "a" else "%s says %s" % (name, prompt)

res = asyncio.run(compare.run("hello", ["a", "b", "bad", "slow", "extra"], fake_ask, timeout_s=0.5))
check("compare: at most 4 models, each answers at once; a failure and a timeout are reported, not fatal",
      res["ok"] and [a["model"] for a in res["answers"]] == ["a", "b", "bad", "slow"]
      and res["answers"][1]["text"] == "b says hello" and "401" in res["answers"][2]["error"] and "within" in res["answers"][3]["error"], res)
check("compare needs a prompt and two models", not asyncio.run(compare.run("", ["a", "b"], fake_ask))["ok"]
      and not asyncio.run(compare.run("x", ["a", "a"], fake_ask))["ok"])
arena = compare.Arena(TMP / "arena.json")
v = arena.vote("a", ["b", "c"], "hello")
board = {r["model"]: r for r in v["board"]}
check("arena: Elo from 1000, K=32 - 16 from the first equal opponent, a bit less from the next",
      1031 < board["a"]["rating"] < 1032 and board["b"]["rating"] == 984.0 and board["a"]["wins"] == 2 and board["c"]["losses"] == 1, board)
arena.vote("b", ["a"])
check("arena: an upset moves more than 16", next(r for r in arena.board() if r["model"] == "b")["rating"] > 1000
      and not arena.vote("a", [])["ok"])

# =============================================================================== artifacts
print("artifacts (previews)")
st = artifacts.Store(TMP / "art")
p1 = st.put("<h1>Hi</h1><script>document.body.append('x')</script>", "html")
p2 = st.put("<h1>Hi</h1><script>document.body.append('x')</script>", "html")
check("a block gets a page with a stable id (same code, same page)", p1["ok"] and p1["id"] == p2["id"] and p1["url"] == "/artifact/" + p1["id"])
check("a fragment gets a page around it; a full page stays as it is", b"<!doctype html>" in st.get(p1["id"])
      and artifacts.wrap("<!DOCTYPE html><html><body>x</body></html>", "html").startswith("<!DOCTYPE html>"))
check("svg is centred in a page", "<svg" in artifacts.wrap("<svg></svg>", "svg") and "<body>" in artifacts.wrap("<svg></svg>", "svg"))
mm = artifacts.wrap("graph TD; A-->B; B--></pre><script>alert(1)</script>", "mermaid")
check("a mermaid page escapes the diagram text (no injected script) and loads the vendored Mermaid",
      "&lt;/pre&gt;&lt;script&gt;" in mm and artifacts.ORIGIN + "/ui/vendor/mermaid/mermaid.min.js" in mm, mm[:400])
check("bad ids and missing pages give nothing", st.get("../../etc/passwd") is None and st.get("0" * 24) is None)
check("empty and huge blocks are refused", not st.put("  ", "html")["ok"] and not st.put("x" * 2_100_000, "html")["ok"])
hdr = dict(artifacts.headers("http://127.0.0.1:9"))
csp = hdr["Content-Security-Policy"]
check("the preview's policy: sandboxed, no network, no forms, framed only by LOKI, Mermaid from LOKI's own vendor folder",
      "sandbox allow-scripts" in csp and "connect-src 'none'" in csp and "form-action 'none'" in csp and "frame-ancestors 'self'" in csp
      and "http://127.0.0.1:9/ui/vendor/" in csp and "allow-same-origin" not in csp and hdr["X-Frame-Options"] == "SAMEORIGIN", csp)
check("the served page has LOKI's address in place of the placeholder",
      b"http://127.0.0.1:9/ui/vendor" in artifacts.page(mm.encode(), "http://127.0.0.1:9"))
sv1 = st.save(p1["id"], WS, "My Page!")
sv2 = st.save(p1["id"], WS, "My Page!")
p3 = st.put("<p>v2</p>", "html")
sv3 = st.save(p3["id"], WS, "My Page!")
check("saving keeps versions: same content is not saved twice, a change becomes .v2",
      sv1["path"] == "artifacts/My-Page.html" and sv2.get("same") and sv3["path"] == "artifacts/My-Page.v2.html", (sv1, sv2, sv3))
check("the vendored Mermaid and its MIT licence are in the repo", (REPO / "app/ui/vendor/mermaid/mermaid.min.js").stat().st_size > 1_000_000
      and "MIT" in (REPO / "app/ui/vendor/mermaid/LICENSE").read_text())


# =============================================================================== Home Assistant (fake HA)
print("Home Assistant")


class Resp:
    def __init__(self, body, status=200):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeHA:
    def __init__(self):
        self.calls = []
        self.states = [
            {"entity_id": "light.living_room", "state": "on", "attributes": {"friendly_name": "Living Room Lights", "brightness": 128}},
            {"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen Light"}},
            {"entity_id": "lock.front_door", "state": "unlocked", "attributes": {"friendly_name": "Front Door"}},
            {"entity_id": "cover.garage_door", "state": "closed", "attributes": {"friendly_name": "Garage Door"}},
            {"entity_id": "sensor.upstairs_temp", "state": "21.5", "attributes": {"friendly_name": "Upstairs Temperature", "unit_of_measurement": "°C"}},
            {"entity_id": "climate.hall", "state": "heat", "attributes": {"friendly_name": "Hall Thermostat", "current_temperature": 20, "temperature": 21}}]
        self.status = 200

    def __call__(self, req, timeout=0):
        url = req.full_url
        body = json.loads(req.data.decode()) if req.data else None
        self.calls.append((req.get_method(), url, body, req.headers.get("Authorization")))
        if self.status != 200:
            raise urllib.error.HTTPError(url, self.status, "Unauthorized", {}, None)
        path = urllib.parse.urlparse(url).path
        if path == "/api/":
            return Resp({"message": "API running."})
        if path == "/api/states":
            return Resp(self.states)
        if path.startswith("/api/services/"):
            dom, svc = path.split("/")[3:5]
            for s in self.states:
                if s["entity_id"] == (body or {}).get("entity_id"):
                    s["state"] = {"turn_off": "off", "turn_on": "on", "lock": "locked", "unlock": "unlocked",
                                  "open_cover": "open"}.get(svc, s["state"])
            return Resp([])
        if path.startswith("/api/history/period/"):
            return Resp([[{"state": "on", "last_changed": "2026-10-17T08:00:00"}, {"state": "off", "last_changed": "2026-10-17T09:00:00"}]])
        if path == "/api/conversation/process":
            return Resp({"response": {"speech": {"plain": {"speech": "Turned on the kitchen light"}}}})
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


ha = FakeHA()
conn_home.OPENER = ha
time_sleep = conn_home.time.sleep
conn_home.time.sleep = lambda s: None
SRC = {"HA_URL": "homeassistant.local:8123", "HA_TOKEN": "ha-secret-token-123456"}
check("status: not set up without address / token", not conn_home.status({})["configured"]
      and "token" in conn_home.status({"HA_URL": "x"})["detail"] and conn_home.status(SRC)["configured"])
check("test() reaches the API and counts devices", conn_home.test(SRC)["ok"] and "6 devices" in conn_home.test(SRC)["detail"])
check("the token goes in the Authorization header; http:// is added to a bare address",
      ha.calls[-1][3] == "Bearer ha-secret-token-123456" and ha.calls[-1][1].startswith("http://homeassistant.local:8123/api/"))
stat = conn_home.tool("status", source=SRC)
check("status says what is on and what is unlocked", "On now: Living Room Lights" in stat and "Unlocked: Front Door" in stat, stat)
check("list by domain", conn_home.tool("list", domain="light", source=SRC).count("light.") == 2)
check("find by words and a typo", "Kitchen Light" in conn_home.tool("find", entity="kitchen", source=SRC)
      and "Upstairs Temperature" in conn_home.tool("find", entity="upstairs temprature", source=SRC))
check("state shows units and climate details", "21.5 °C" in conn_home.tool("state", entity="upstairs temperature", source=SRC)
      and "current temperature 20" in conn_home.tool("state", entity="climate.hall", source=SRC))
out = conn_home.tool("turn_off", entity="living room lights", source=SRC)
check("turn_off by NAME calls light.turn_off on the right entity and reports the new state",
      ("POST", "http://homeassistant.local:8123/api/services/light/turn_off", {"entity_id": "light.living_room"}) == ha.calls[-2][:3]
      and "off" in out, (out, ha.calls[-3:]))
conn_home.tool("turn_on", entity="kitchen light", brightness=40, color="warm white", source=SRC)
check("brightness and colour go with turn_on", ha.calls[-2][2] == {"entity_id": "light.kitchen", "brightness_pct": 40, "color_name": "warm white"}, ha.calls[-2])
conn_home.tool("turn_on", entity="front door", source=SRC)
check("a lock: turn_on = lock", ha.calls[-2][1].endswith("/api/services/lock/lock"))
check("a lock does not toggle", "does not toggle" in conn_home.tool("toggle", entity="front door", source=SRC))
conn_home.tool("turn_on", entity="garage door", source=SRC)
check("a cover: turn_on = open_cover", ha.calls[-2][1].endswith("/api/services/cover/open_cover"))
conn_home.tool("call", domain="climate", service="set_temperature", entity="hall thermostat", data='{"temperature": 22}', source=SRC)
check("call: any service with JSON data", ha.calls[-2][1].endswith("/climate/set_temperature")
      and ha.calls[-2][2] == {"temperature": 22, "entity_id": "climate.hall"}, ha.calls[-2])
check("call checks domain/service and data", "needs domain" in conn_home.tool("call", domain="x y", service="s", source=SRC)
      and "must be JSON" in conn_home.tool("call", domain="light", service="turn_on", data="{bad", source=SRC))
check("ambiguous and unknown names give choices", "more than one" in conn_home.tool("state", entity="door", source=SRC)
      and "no device called" in conn_home.tool("state", entity="spaceship", source=SRC))
check("history and assist", "2 changes" in conn_home.tool("history", entity="kitchen light", source=SRC)
      and "Turned on the kitchen light" in conn_home.tool("assist", text="turn on the kitchen light", source=SRC))
check("the approval line names the device and flags security devices",
      conn_home.describe_write({"action": "turn_off", "entity": "front door"}, SRC).startswith("SECURITY DEVICE - turn off Front Door")
      and "Living Room Lights" in conn_home.describe_write({"action": "toggle", "entity": "light.living_room"}, SRC))
ha.status = 401
conn_home._CACHE["at"] = 0
err = conn_home.tool("status", source=SRC)
check("401: says the token is wrong, and never shows it", "token is wrong" in err and "ha-secret-token" not in err, err)
ha.status = 200


def down(req, timeout=0):
    raise urllib.error.URLError("Connection refused")


conn_home.OPENER = down
conn_home._CACHE["at"] = 0
check("unreachable: says how to check", "cannot reach Home Assistant" in conn_home.tool("status", source=SRC))
conn_home.OPENER = ha
check("a wrong action lists the right ones", "action must be one of" in conn_home.tool("dance", source=SRC))

# =============================================================================== everyday
print("everyday: weather, news, clock, translate")
GEO_US = {"results": [{"name": "Springfield", "latitude": 39.8, "longitude": -89.6, "country": "United States", "country_code": "US",
                       "admin1": "Illinois", "timezone": "America/Chicago"},
                      {"name": "Springfield", "latitude": 37.2, "longitude": -93.3, "country": "United States", "country_code": "US",
                       "admin1": "Missouri", "timezone": "America/Chicago"}]}
FC = {"current": {"temperature_2m": 61.2, "apparent_temperature": 59, "relative_humidity_2m": 70, "weather_code": 61,
                  "wind_speed_10m": 9, "precipitation": 0.2},
      "daily": {"time": ["2026-10-17", "2026-10-18"], "weather_code": [61, 0], "temperature_2m_max": [64, 70],
                "temperature_2m_min": [50, 52], "precipitation_probability_max": [80, 5]}, "utc_offset_seconds": -18000}
RSS = b"""<?xml version="1.0"?><rss><channel><item><title>Big story - Example News</title><link>https://example.com/a</link>
<pubDate>Sat, 17 Oct 2026 08:00:00 GMT</pubDate><source url="https://example.com">Example News</source></item>
<item><title>Second</title><link>javascript:alert(1)</link></item></channel></rss>"""
seen = []


def web(req, timeout=0):
    url = req.full_url if hasattr(req, "full_url") else req
    seen.append(url)
    if "geocoding-api" in url:
        return Resp(GEO_US if "Springfield" in url else {"results": []})
    if "api.open-meteo.com" in url:
        return Resp(FC)
    if "news.google.com" in url or "bbci" in url:
        return Resp(RSS)
    if "translate.example" in url:
        return Resp({"translatedText": "Hola"})
    raise urllib.error.URLError("no")


everyday.OPENER = web
w = everyday.weather("Springfield, Missouri", 2)
check("weather: the region narrows the place; US gets °F and mph", "Springfield, Missouri, United States" in w and "61.2°F" in w
      and "mph" in w and "temperature_unit=fahrenheit" in seen[-1] and "latitude=37.2" in seen[-1], w)
cardjson = json.loads(w.split("```loki-card\n", 1)[1].split("\n```", 1)[0])
check("weather ends with a card the window draws", cardjson["kind"] == "weather" and len(cardjson["days"]) == 2
      and cardjson["now"]["icon"] == "rain" and cardjson["unit"] == "°F", cardjson)
check("weather: no place and no home city says how; an unknown place says so",
      "LOKI_HOME_CITY" in everyday.weather("") and "no place called" in everyday.weather("Atlantis"))
os.environ["LOKI_HOME_CITY"] = "Springfield"
check("weather: the home city is the default", "Springfield, Illinois" in everyday.weather(""))
os.environ.pop("LOKI_HOME_CITY")
n = everyday.news("electric cars")
check("news: a topic searches Google News; titles split from their source; only http(s) links kept",
      "q=electric%20cars" in seen[-1] and "1. Big story - Example News" in n and "javascript:" not in n, n)
check("news: blank = top stories (BBC World)", "bbci" in (everyday.news("") and seen[-1]))
c = everyday.clock("Springfield")
check("clock: the time in that city's zone", "America/Chicago" in c and "It is" in c, c)
everyday.OPENER = down
check("offline: says so", "online" in everyday.weather("Paris"))
everyday.OPENER = web


async def fake_translate(prompt):
    return "<<<\nBonjour\n>>>" if "French" in prompt else ""

check("translate with the model (markers stripped)", asyncio.run(everyday.translate("Hello", "French", fake_translate)) == "Bonjour")
check("translate checks its input", asyncio.run(everyday.translate("", "French", fake_translate)).startswith("error")
      and asyncio.run(everyday.translate("x", "1234", fake_translate)).startswith("error"))
os.environ["LOKI_LIBRETRANSLATE_URL"] = "https://translate.example"
check("a LibreTranslate server is used when set", asyncio.run(everyday.translate("Hello", "es", None)) == "Hola")
os.environ.pop("LOKI_LIBRETRANSLATE_URL")

# =============================================================================== picture edits (real Pillow)
print("picture edits")
try:
    from PIL import Image  # noqa: E402
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
if HAVE_PIL:
    pic = WS / "photo.png"
    Image.new("RGB", (400, 200), (200, 30, 30)).save(pic)
    info = image_tools.edit(pic, "info")
    check("info", "400x200" in info["detail"], info)
    r = image_tools.edit(pic, "resize", width=100)
    check("resize keeps the shape and makes a NEW file", r["path"].name == "photo-100x50.png" and Image.open(r["path"]).size == (100, 50)
          and Image.open(pic).size == (400, 200))
    r2 = image_tools.edit(pic, "resize", width=100)
    check("never overwrites an earlier result", r2["path"].name == "photo-100x50-2.png")
    check("crop", Image.open(image_tools.edit(pic, "crop", box="10,10,110,60")["path"]).size == (100, 50))
    try:
        image_tools.edit(pic, "crop", box="0,0,999,10")
        check("a crop outside the picture is refused", False)
    except image_tools.ImageError as exc:
        check("a crop outside the picture is refused", "outside" in str(exc))
    check("rotate 90", Image.open(image_tools.edit(pic, "rotate", degrees=90)["path"]).size == (200, 400))
    check("convert to jpg + compress to webp", image_tools.edit(pic, "convert", to="jpg")["path"].suffix == ".jpg"
          and image_tools.edit(pic, "compress", to="webp", quality=50)["path"].suffix == ".webp")
    check("grayscale and thumbnail", Image.open(image_tools.edit(pic, "grayscale")["path"]).mode == "L"
          and max(Image.open(image_tools.edit(pic, "thumbnail", width=64)["path"]).size) == 64)
    image_tools.WHICH = lambda n: None
    up = image_tools.edit(pic, "upscale", scale=3)
    check("upscale without Real-ESRGAN: Lanczos x3", Image.open(up["path"]).size == (1200, 600) and "x3" in up["path"].name)
    ran = []

    def fake_run(cmd, **kw):
        ran.append(cmd)
        Image.new("RGB", (800, 400)).save(cmd[cmd.index("-o") + 1])
        return types.SimpleNamespace(returncode=0)

    image_tools.WHICH = lambda n: "/opt/realesrgan-ncnn-vulkan"
    image_tools.RUN = fake_run
    up = image_tools.edit(pic, "upscale", scale=2)
    check("upscale with Real-ESRGAN when it is installed", "Real-ESRGAN" in up["detail"] and ran and ran[0][0] == "/opt/realesrgan-ncnn-vulkan")
    real_import = image_tools.IMPORT

    def no_rembg(name):
        if name == "rembg":
            raise ImportError(name)
        return real_import(name)

    image_tools.IMPORT = no_rembg
    try:
        image_tools.edit(pic, "remove_background")
        check("remove_background without rembg says how to install it", False)
    except image_tools.ImageError as exc:
        check("remove_background without rembg says how to install it", "Add-ons > rembg" in str(exc))
    fake_rembg = types.SimpleNamespace(remove=lambda img, session=None: img.convert("RGBA"), new_session=lambda m: m)
    image_tools.IMPORT = lambda name: fake_rembg if name == "rembg" else real_import(name)
    nb = image_tools.edit(pic, "remove bg")
    check("remove_background (rembg faked) gives a transparent PNG; 'remove bg' is understood",
          nb["path"].name == "photo-nobg.png" and Image.open(nb["path"]).mode == "RGBA")
    image_tools.IMPORT = real_import
    (WS / "notapic.png").write_text("hello")
    try:
        image_tools.edit(WS / "notapic.png", "info")
        check("a file that is not a picture is refused", False)
    except image_tools.ImageError:
        check("a file that is not a picture is refused", True)
    res = asyncio.run(loki.edit_image_tool("../../etc/passwd", "info"))
    check("the edit_image tool refuses paths outside the workspace", res.startswith("error"), res)
    res = asyncio.run(loki.edit_image_tool("photo.png", "resize", width=50))
    check("the edit_image tool answers with the new file's workspace path", res.endswith("-> photo-50x25.png"), res)
else:
    print("  (Pillow not installed here: picture checks skipped)")
check("Pillow is in requirements.txt; rembg is an add-on (pip rembg[cpu]) with a manifest",
      "pillow" in (REPO / "engine/requirements.txt").read_text().lower()
      and __import__("addons_install").PIP["rembg"] == ["rembg[cpu]"]
      and json.loads((REPO / "capabilities/rembg/manifest.json").read_text())["license"] == "MIT")

# =============================================================================== your data
print("your data: inventory, backup, restore, clear")
D, W2, B = TMP / "yd" / "data", TMP / "yd" / "ws", TMP / "yd" / "backups"
for rel, text in {".env": "GROQ_API_KEY=supersecret", "usage.jsonl": "{}", "memory/notes.md": "likes tea",
                  "logs/engine.log": "log", "jobs/j1.log": "job log", "jobs/j1.json": "{}", ".venv/bin/python": "x",
                  "models/big.gguf": "x" * 100, "tools/mytool/tool.json": "{}", "tools/mytool/tool.py": "def run(a): return 1",
                  "tools/sdcpp/sd-cli": "binary", "artifacts/abc.html": "<p>", "computer_log.jsonl": "{}"}.items():
    (D / rel).parent.mkdir(parents=True, exist_ok=True)
    (D / rel).write_text(text)
(W2 / ".loki").mkdir(parents=True)
(W2 / ".loki" / "loki_conversations.json").write_text('{"conversations": []}')
now = time.time()
usage = [{"t": now, "provider": "groq", "in": 1000, "out": 200}, {"t": now, "provider": "local", "in": 50, "out": 5},
         {"t": now - 40 * 86400, "provider": "openai", "in": 1, "out": 1}]
inv = your_data.inventory(D, W2, usage, lambda p: p == "local", 3)
names = {p["name"]: p for p in inv["places"]}
check("inventory: every place with what it is; the secrets file flagged and its value never read into the answer",
      names[".env"]["secret"] and "supersecret" not in json.dumps(inv) and names["memory"]["what"].startswith("What LOKI remembers"), names)
check("inventory: who got messages in 30 days (cloud vs this computer); older calls left out",
      inv["summary"]["cloud_providers"] == ["groq"] and inv["summary"]["local_calls_30d"] == 1
      and not any(p["provider"] == "openai" for p in inv["providers"]) and inv["chats"]["count"] == 3, inv["summary"])
bk = your_data.backup(D, W2, B)
with zipfile.ZipFile(bk["path"]) as z:
    members = set(z.namelist())
check("backup: chats, memory, logs, LOKI's own tools are in", {"data/memory/notes.md", "workspace-loki/loki_conversations.json",
                                                              "data/tools/mytool/tool.py", "manifest.json"} <= members, members)
check("backup: NO secrets file, no venv, no models, no installed programs", not any(m.startswith(("data/.env", "data/.venv", "data/models",
                                                                                                 "data/tools/sdcpp")) for m in members), members)
bk2 = your_data.backup(D, W2, B, include_secrets=True, label="keys")
with zipfile.ZipFile(bk2["path"]) as z:
    check("backup with keys includes .env and says so", "data/.env" in z.namelist() and json.loads(z.read("manifest.json"))["secrets"])
lst = your_data.list_backups(B)
check("backups are listed newest first with their manifest", len(lst) == 2 and all(b["valid"] for b in lst) and lst[0]["secrets"], lst)
(D / "memory" / "notes.md").write_text("CHANGED")
(D / "memory" / "new.md").write_text("new since")
rs = your_data.restore(Path(bk["path"]), D, W2, B)
check("restore puts the files back, keeps files that were not in the backup, made a safety backup first",
      rs["ok"] and (D / "memory" / "notes.md").read_text() == "likes tea" and (D / "memory" / "new.md").exists()
      and "before-restore" in rs["safety_backup"] and (D / ".env").read_text() == "GROQ_API_KEY=supersecret", rs)
evil = B / "loki-backup-evil.zip"
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("manifest.json", json.dumps({"format": "loki-backup"}))
    z.writestr("data/../../escape.txt", "x")
r = your_data.restore(evil, D, W2, B)
check("restore refuses a zip with a path that escapes - nothing restored", not r["ok"] and "unsafe" in r["error"]
      and not (TMP / "yd" / "escape.txt").exists(), r)
plain = B / "loki-backup-plain.zip"
with zipfile.ZipFile(plain, "w") as z:
    z.writestr("data/x.txt", "x")
check("restore refuses a zip that is not a LOKI backup", "not a LOKI backup" in your_data.restore(plain, D, W2, B)["error"])
cl = your_data.clear("logs", D)
check("clear logs removes engine and job logs only", cl["ok"] and not (D / "logs" / "engine.log").exists() and not (D / "jobs" / "j1.log").exists()
      and (D / "jobs" / "j1.json").exists(), cl)
cleared = []
check("clear chats/usage go through the engine; unknown kinds are refused",
      your_data.clear("chats", D, clear_chats=lambda: cleared.append(1))["ok"] and cleared
      and your_data.clear("usage", D, reset_usage=lambda: cleared.append(2))["ok"] and cleared == [1, 2]
      and not your_data.clear("everything", D)["ok"] and (D / ".env").exists())

# =============================================================================== the real bridge
print("bridge routes (real BridgeHTTPServer)")
import loki_bridge  # noqa: E402

loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()
loki_bridge.PORT = 0
loki_bridge.UI_DIR = REPO / "app" / "ui"
bstate = loki_bridge.BridgeState(loki, "r3-secret")
bstate.loop = loop
bserver = loki_bridge.BridgeHTTPServer(bstate)
PORT = bserver.server_address[1]
loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)
loki_bridge.ALLOWED_ORIGINS = ("http://127.0.0.1", "http://localhost", "null", "http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def call(method, path, body=None, token="r3-secret", host=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if host:
        headers["Host"] = host
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    try:
        return resp.status, json.loads(raw), dict(resp.getheaders())
    except json.JSONDecodeError:
        return resp.status, raw, dict(resp.getheaders())


code, body, _ = call("GET", "/prompts", token="wrong")
check("routes need LOKI's token", code == 401)
code, body, _ = call("GET", "/prompts")
check("GET /prompts", code == 200 and any(p["name"] == "trip" for p in body["prompts"]))
code, body, _ = call("POST", "/prompts/fill", {"name": "explain", "values": {"topic": "tides"}})
check("POST /prompts/fill by name fills defaults and counts a use", code == 200 and "Explain tides as if I were 12 years old" in body["text"], body)
code, body, _ = call("POST", "/prompts/fill", {"name": "nope"})
check("filling an unknown prompt is a 404", code == 404)
big = json.dumps(CHATGPT * 200)          # ~120 KB, far past the bridge's normal 32 KB limit
code, body, _ = call("POST", "/convo/import", {"name": "conversations.json", "text": big})
check("POST /convo/import takes a big export (past the 32 KB limit) and adds the chats", code == 200 and body["imported"] == 400
      and body["source"] == "chatgpt", body if code != 200 else body["imported"])
code, body, _ = call("POST", "/convo/import", {"path": "../outside.json"})
check("import from a path outside the workspace is refused", code == 400 and "inside the workspace" in body["error"], body)
(WS / "chat.md").write_text("## You\n\nhi\n\n## LOKI\n\nhello")
code, body, _ = call("POST", "/convo/import", {"path": "chat.md"})
check("import from a workspace file", code == 200 and body["source"] == "markdown")
loki.switch_conversation(cid)
code, body, _ = call("POST", "/convo/export", {"id": cid, "format": "html"})
check("POST /convo/export saves the file in exports/ and returns it", code == 200 and (WS / body["path"]).is_file()
      and body["path"].startswith("exports/") and body["text"].startswith("<!doctype html>"), body.get("path"))
code, body, _ = call("POST", "/convo/cut", {"id": cid, "text": "And 3+3?", "occurrence": 0})
check("POST /convo/cut", code == 200 and [m["content"] for m in body["messages"]] == ["What is 2+2?", "4"], body)
code, body, _ = call("POST", "/convo/branch", {"id": cid, "role": "assistant", "text": "4"})
check("POST /convo/branch opens the new chat and lists it", code == 200 and body["active"] == body["id"]
      and any(c["id"] == body["id"] for c in body["conversations"]))
bstate.chat_request_lock.acquire()
code, body, _ = call("POST", "/convo/cut", {"id": cid, "text": "x"})
bstate.chat_request_lock.release()
check("while LOKI is answering, chat changes wait (409)", code == 409, (code, body))
code, body, _ = call("POST", "/artifact", {"code": "<div id=x>hi</div>" * 3000, "kind": "html"})
check("POST /artifact takes a page past 32 KB", code == 200 and body["url"].startswith("/artifact/"), body)
aid_url = body["url"]
code, raw, headers = call("GET", aid_url, token="none")
check("GET /artifact/<id> needs no token and carries the sandbox policy", code == 200 and b"<div id=x>hi</div>" in raw
      and "sandbox allow-scripts" in headers.get("Content-Security-Policy", "") and "connect-src 'none'" in headers["Content-Security-Policy"])
code, _raw, _h = call("GET", aid_url, host="evil.example:%d" % PORT)
check("GET /artifact/<id> under a foreign host name is refused (DNS rebinding)", code == 403)
code, body, _ = call("POST", "/artifact", {"code": "graph TD; A-->B", "kind": "mermaid"})
code2, raw, headers = call("GET", body["url"])
check("a mermaid page is served with LOKI's own address for the vendored library",
      ("http://127.0.0.1:%d/ui/vendor/mermaid/mermaid.min.js" % PORT).encode() in raw
      and ("http://127.0.0.1:%d/ui/vendor/" % PORT) in headers["Content-Security-Policy"], raw[:300])
code, body, _ = call("POST", "/artifact/save", {"id": aid_url.rsplit("/", 1)[1], "name": "demo"})
check("POST /artifact/save", code == 200 and body["path"] == "artifacts/demo.html")


async def r3_fake(name, prompt):
    return "%s: %s" % (name, prompt[::-1])

real_ask = loki._r3_model_ask
loki._r3_model_ask = r3_fake
names = [n for n in loki.MODELS if n not in ("smart", "online")][:2]
code, body, _ = call("POST", "/compare", {"prompt": "abc", "models": names + ["smart", "not-a-model"]})
check("POST /compare asks real provider names only (smart/unknown dropped), side by side", code == 200
      and [a["model"] for a in body["answers"]] == names and body["answers"][0]["text"] == names[0] + ": cba", body)
loki._r3_model_ask = real_ask
code, body, _ = call("POST", "/compare/vote", {"winner": names[0], "losers": [names[1]]})
code2, board, _ = call("GET", "/compare/board")
check("POST /compare/vote + GET /compare/board", code == 200 and board["board"][0]["model"] == names[0])
everyday.OPENER = web
code, body, _ = call("GET", "/everyday?kind=weather&q=Springfield")
check("GET /everyday weather", code == 200 and "loki-card" in body["text"])
code, body, _ = call("GET", "/everyday?kind=nope")
check("GET /everyday with a wrong kind", code == 400)
code, body, _ = call("GET", "/data")
check("GET /data: the inventory, backups and what can be cleared", code == 200 and "places" in body and "clearable" in body
      and body["backup_dir"] == str(TMP / "backups"))
code, body, _ = call("POST", "/data/backup", {})
check("POST /data/backup makes a zip in the backup folder", code == 200 and Path(body["path"]).is_file() and not body["secrets"], body)
code, body, _ = call("POST", "/data/restore", {"name": "x.zip", "confirm": True})
code2, body2, _ = call("POST", "/data/restore", {"name": "x.zip"})
check("restore needs a confirm and a backup from the list", code == 400 and code2 == 400 and "confirm" in body2["error"])
code, body, _ = call("POST", "/data/clear", {"kind": "previews"})
check("clear needs a confirm", code == 400)
code, body, _ = call("POST", "/data/clear", {"kind": "previews", "confirm": True})
check("POST /data/clear previews", code == 200 and body["ok"])
code, body, _ = call("GET", "/convo/unknown")
check("an unknown research-3 route is a 404", code == 404)


# =============================================================================== the window (headless Chromium)
def chromium_path() -> str:
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None

RICH = """Here is everything at once.

| Day | Plan |
|---|---|
| Sat | Louvre |
| Sun | Orsay |

Sources: see [1] and [the museum](https://www.louvre.fr/en).

```mermaid
graph TD
  A[Plan] --> B{Rainy?}
  B -->|yes| C[Museum]
  B -->|no| D[Park]
```

```chart
{"type": "bar", "title": "Visitors (millions)", "labels": ["Louvre", "Orsay", "Pompidou"], "data": [8.7, 3.9, 2.6]}
```

```html
<button id=b onclick="this.textContent='clicked!'">Click me</button>
```

```loki-card
{"kind": "weather", "place": "Paris, France", "unit": "°C", "now": {"temp": 14, "feels": 12, "words": "light rain", "icon": "rain"},
 "days": [{"day": "Sat 17 Oct", "hi": 15, "lo": 9, "rain": 80, "icon": "rain"}, {"day": "Sun 18 Oct", "hi": 18, "lo": 10, "rain": 10, "icon": "sun"}]}
```"""
# Screens go to docs/ only when asked (LOKI_SUITE_SHOTS=1), so a normal ship.py run leaves the tree clean.
SHOTS = REPO / "docs" / "operations" / "screens" if os.getenv("LOKI_SUITE_SHOTS") == "1" else TMP / "screens"

if async_playwright is None or not chromium_path():
    print("  (no Playwright/Chromium here: window checks skipped)")
else:
    print("the window (headless Chromium)")
    FAKES = {"/health": {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "",
                         "route": [], "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []},
             "/world": {"ok": True, "agents": [], "machines": [], "self": {"name": "test"}, "creations": {"count": 0, "latest": []}},
             "/chat": {"ok": True, "response": RICH},
             "/models": {"ok": True, "current": "smart", "models": names, "entries": [{"name": n, "label": n, "ready": True, "group": "free"} for n in names]}}
    REAL = ("/convo/", "/prompts", "/compare", "/artifact", "/everyday", "/data", "/ui/vendor/")

    async def ui():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chromium_path(), args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            page = await browser.new_page(viewport={"width": 1280, "height": 860})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            base = "http://127.0.0.1:%d" % PORT

            async def route(r):
                path = urllib.parse.urlparse(r.request.url).path
                if path == "/" or path.startswith(REAL) or (path.startswith("/ui/") and (REPO / "app" / path.lstrip("/")).is_file()):
                    return await r.continue_()
                if path.startswith("/ui/"):
                    return await r.fulfill(json={"ok": True})
                return await r.fulfill(json=FAKES.get(path, {"ok": True}))

            await page.route(base + "/**", route)
            await page.goto(base + "/#token=r3-secret")
            await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
            await page.wait_for_timeout(600)
            check("window: starts with the research-3 scripts and no script error", not errors, errors[:5])
            check("window: chat menu and prompt library buttons are icons with tooltips",
                  await page.get_attribute("#chat-menu-btn", "data-tip-name") == "Chat menu"
                  and await page.eval_on_selector("#prompt-lib-btn", "n => !!n.querySelector('svg.icon')"))
            await page.click("#prompt")
            await page.fill("#prompt", "Plan a weekend in Paris")
            await page.keyboard.press("Enter")
            await page.wait_for_selector(".turn.loki .md-table", timeout=10000)
            await page.wait_for_timeout(2500)
            got = await page.evaluate("""() => ({
                table: !!document.querySelector('.turn.loki table th'),
                chart: !!document.querySelector('figure.art-chart svg rect'),
                card: !!document.querySelector('.loki-card.weather .lc-day'),
                diagram: !!document.querySelector('iframe.art-diagram[sandbox="allow-scripts"]'),
                preview: !!document.querySelector('.code-bar [data-tip-name="Preview"]'),
                link: !!document.querySelector('a.ext-link[data-url="https://www.louvre.fr/en"]'),
                cite: !!document.querySelector('sup.cite.live'),
                actions: document.querySelectorAll('.turn .msg-actions').length,
                regen: !!document.querySelector('.turn.loki [data-tip-name="Regenerate"]'),
                edit: !!document.querySelector('.turn.user [data-tip-name="Edit"]')})""")
            check("window: a reply draws a table, a chart, a weather card, a sandboxed diagram, a Preview button, links and citations",
                  all(got[k] for k in ("table", "chart", "card", "diagram", "preview", "link", "cite")), got)
            check("window: messages get Copy / Edit / Regenerate / Branch", got["actions"] >= 2 and got["regen"] and got["edit"], got)
            dframe = next((f for f in page.frames if "/artifact/" in f.url), None)
            drawn = False
            if dframe:
                try:
                    await dframe.wait_for_selector("pre.mermaid svg", timeout=15000)
                    drawn = True
                except Exception:  # noqa: BLE001
                    drawn = False
            check("window: Mermaid really draws the diagram inside the sandboxed frame", drawn)
            leak = await dframe.evaluate("() => { try { return String(window.parent.state && window.parent.state.token); } catch (e) { return 'blocked'; } }") if dframe else ""
            check("window: the diagram frame cannot read LOKI's window (no token)", leak == "blocked", leak)
            SHOTS.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(SHOTS / "research3-rich-reply.png"), full_page=False)
            await page.click('.code-bar [data-tip-name="Preview"]')
            await page.wait_for_selector(".art-canvas iframe.art-frame", timeout=5000)
            pframe = None
            for _ in range(40):
                pframe = next((f for f in page.frames if "/artifact/" in f.url and f != dframe), None)
                if pframe:
                    break
                await page.wait_for_timeout(100)
            clicked = ""
            if pframe:
                await pframe.wait_for_load_state("load")
                for _ in range(5):          # a busy machine: the frame may still be settling
                    await pframe.wait_for_selector("#b", timeout=5000)
                    await pframe.click("#b")
                    await page.wait_for_timeout(300)
                    clicked = await pframe.text_content("#b")
                    if clicked == "clicked!":
                        break
                if clicked != "clicked!":
                    clicked += " | " + pframe.url + " | " + (await pframe.content())[:300] + " | " + str(errors[-3:])
            check("window: Preview runs the page's own script in the canvas", clicked == "clicked!", clicked)
            await page.screenshot(path=str(SHOTS / "research3-preview-canvas.png"))
            await page.click('.art-canvas [data-tip-name="Close preview"]')
            check("window: the preview closes", await page.is_hidden(".art-canvas"))
            await page.hover('.turn.loki [data-tip-name="Regenerate"]')
            await page.wait_for_timeout(450)
            check("window: hovering an action shows its tooltip", "Regenerate" in (await page.text_content(".icon-tip") or ""))
            await page.screenshot(path=str(SHOTS / "research3-message-actions.png"))
            await page.click("#prompt-lib-btn")
            await page.wait_for_selector(".prompt-pick", timeout=5000)
            await page.fill(".prompt-search", "trip")
            await page.wait_for_timeout(500)
            check("window: the prompt library opens and searches", "Plan a trip" in (await page.text_content(".prompt-list") or ""))
            await page.screenshot(path=str(SHOTS / "research3-prompt-library.png"))
            page.on("dialog", lambda d: asyncio.ensure_future(d.accept({"place": "Lisbon"}.get("x", "Lisbon"))))
            await page.click(".prompt-pick")
            await page.wait_for_timeout(1200)
            val = await page.input_value("#prompt")
            check("window: picking a prompt asks for its blanks and fills the message box", "Lisbon" in val and "{{" not in val, val)
            await page.fill("#prompt", "")
            await page.click("#chat-menu-btn")
            await page.wait_for_selector(".chat-menu", timeout=3000)
            await page.screenshot(path=str(SHOTS / "research3-chat-menu.png"))
            await page.click(".chat-menu button:has-text('Compare models')")
            await page.wait_for_selector(".compare-box textarea", timeout=5000)
            loki._r3_model_ask = r3_fake
            await page.fill(".compare-prompt", "Say hi")
            await page.click(".compare-box .send")
            await page.wait_for_selector(".compare-col", timeout=10000)
            cols = await page.eval_on_selector_all(".compare-col", "ns => ns.map(n => n.textContent)")
            check("window: compare shows each model's answer side by side", len(cols) == 2 and "ih yaS" in cols[0], cols)
            await page.click(".compare-col .vote")
            await page.wait_for_timeout(400)
            check("window: voting marks the winner", await page.query_selector(".compare-col.winner") is not None)
            await page.screenshot(path=str(SHOTS / "research3-compare.png"))
            loki._r3_model_ask = real_ask
            await page.click("#open-settings")
            await page.click('.tabs button[data-tab="data"]')
            await page.wait_for_selector(".data-tile", timeout=5000)
            await page.wait_for_timeout(300)
            check("window: Settings > Your data shows the inventory and the backups", "kept on this computer" in (await page.text_content("#data-panel") or "")
                  and await page.get_attribute('.tabs button[data-tab="data"]', "data-tip-name") == "Your data")
            await page.screenshot(path=str(SHOTS / "research3-your-data.png"))
            check("window: still no script errors", not errors, errors[:5])
            await browser.close()

    asyncio.run(ui())

bserver.shutdown()
conn_home.time.sleep = time_sleep
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
