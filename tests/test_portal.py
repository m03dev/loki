"""The October 2026 build: Connections portal, sign-in and QR codes, the prompted tool
harness, Update everything, the agent builder, new specialists and LOKI World.

    python tests/test_portal.py

Offline: every network call is a fake, git runs against a throwaway bare repository, and
the phone hand-off server listens on 127.0.0.1 only. The last section imports the engine
itself (loki.py) and is skipped only where its packages are not installed and this is not
CI.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "data")
sys.path.insert(0, str(REPO / "engine"))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200, headers=None):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        super().__init__(raw)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------------------------- QR codes
section("QR codes (engine/qr.py)")
import qr  # noqa: E402

vectors = json.loads((REPO / "tests" / "fixtures" / "qr_vectors.json").read_text(encoding="utf-8"))["cases"]
for case in vectors:
    rows = ["".join("1" if c else "0" for c in r) for r in qr.matrix(case["text"])]
    check("QR for %r matches the decoder-verified matrix (%dx%d)" % (case["text"][:24], len(rows), len(rows)),
          rows == case["rows"])
svg = qr.svg("https://openrouter.ai/keys")
check("svg() is one self-contained <svg> with no script or style", svg.startswith("<svg") and svg.endswith("</svg>")
      and "script" not in svg and "style=" not in svg)
check("an 800-character text still fits (version 25 at most)", len(qr.matrix("x" * 800)) <= 117)
try:
    qr.matrix("x" * 2000)
    check("too-long text is refused", False)
except ValueError:
    check("too-long text is refused", True)

# --------------------------------------------------------------------------- tool harness
section("any model can use any tool (engine/tool_harness.py)")
import tool_harness  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "Read a file",
                                            "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                                           "required": ["path"]}}},
         {"type": "function", "function": {"name": "list_files", "description": "List", "parameters": {"type": "object"}}}]
msgs = [{"role": "system", "content": "You are LOKI."}, {"role": "user", "content": "read a.txt"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
                                                              "function": {"name": "read_file", "arguments": "{\"path\": \"a.txt\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "hello"}]
out = tool_harness.to_prompted(msgs, TOOLS)
check("tools are described in the system prompt", "<tools>" in out[0]["content"] and "read_file" in out[0]["content"]
      and out[0]["content"].startswith("You are LOKI."))
check("an earlier tool call becomes a fenced json block", "```json" in out[2]["content"] and "a.txt" in out[2]["content"])
check("a tool result becomes a <tool_response> user turn", out[3]["role"] == "user" and "<tool_response>" in out[3]["content"])
check("no message keeps tool_calls or role=tool", all("tool_calls" not in m and m["role"] != "tool" for m in out))
prepared = tool_harness.prepare({"model": "m", "messages": msgs, "tools": TOOLS, "tool_choice": "required"})
check("prepare() drops tools and tool_choice", "tools" not in prepared and "tool_choice" not in prepared
      and prepared["_prompted_tools"] == ["read_file", "list_files"])
check("the taught format avoids <tool_call> (Qwen3.5 crashes the runner on that tag)",
      "<tool_call>" not in out[0]["content"] and "```json" in out[0]["content"])
calls, rest = tool_harness.parse('Sure.\n<tool_call>\n{"name": "read_file", "arguments": {"path": "b.md"}}\n</tool_call>',
                                 ["read_file"])
check("a <tool_call> block is parsed", calls == [("read_file", {"path": "b.md"})] and rest == "Sure.")
calls, _ = tool_harness.parse('```json\n{"name": "list_files", "arguments": {}}\n```', ["read_file", "list_files"])
check("a ```json fence is parsed", calls == [("list_files", {})])
_braces = "body { color: red; }\n.x { margin: 0; }"
_fenced = "```json\n" + json.dumps({"name": "write_file", "arguments": {"filename": "a.css", "content": _braces}}) + "\n```"
calls, _ = tool_harness.parse(_fenced, ["write_file"])
check("a fenced call whose arguments contain braces still parses whole (CSS/JSON/code)",
      calls == [("write_file", {"filename": "a.css", "content": _braces})], calls)
calls, _ = tool_harness.parse("{'name': 'read_file', 'arguments': {'path': 'c',},}", ["read_file"])
check("small-model slips (single quotes, trailing commas) are forgiven", calls == [("read_file", {"path": "c"})])
calls, _ = tool_harness.parse('{"name": "rm_rf", "arguments": {}}', ["read_file"])
check("only real tool names are accepted", calls == [])
calls, rest = tool_harness.parse("Just an answer, no tools.", ["read_file"])
check("plain answers are left alone", calls == [] and rest == "Just an answer, no tools.")


class _Msg:
    def __init__(self, content):
        self.content, self.tool_calls, self.role = content, None, "assistant"


resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=_Msg('<tool_call>{"name":"read_file","arguments":{"path":"x"}}</tool_call>'),
                                                            finish_reason="stop")])
tool_harness.attach(resp, ["read_file"])
tc = resp.choices[0].message.tool_calls
check("attach() turns the text into real tool_calls", tc and tc[0].function.name == "read_file"
      and json.loads(tc[0].function.arguments) == {"path": "x"} and resp.choices[0].finish_reason == "tool_calls")
os.environ["LOKI_PROMPTED_TOOLS"] = "myserver"
check("LOKI_PROMPTED_TOOLS puts a provider on prompted tools", tool_harness.configured("myserver"))
check("catalog tools=false providers are prompted (MLX)", tool_harness.configured("mlx"))
check("native providers are not", not tool_harness.configured("groq"))
tool_harness.learn("weaklocal")
check("a provider that fails a forced call is moved onto prompted tools",
      tool_harness.configured("weaklocal"))
_r = tool_harness.prepare({"model": "m", "messages": msgs, "tools": TOOLS, "tool_choice": "required"})
check("its forced turn becomes text tools (no native tools/tool_choice)",
      "tools" not in _r and "tool_choice" not in _r and "<tools>" in _r["messages"][0]["content"])
tool_harness.learn("some-endpoint")
check("a provider that refused tools is learned", tool_harness.configured("some-endpoint"))

# --------------------------------------------------------------------------- catalog
section("the Connections portal (engine/providers_catalog.py)")
import providers_catalog as pc  # noqa: E402

ids = [p["id"] for p in pc.CATALOG]
check("every provider id is unique", len(ids) == len(set(ids)))
check("every card has a group, a name, a blurb and auth", all(p["group"] in dict(pc.GROUPS) and p["name"] and p["blurb"]
                                                              and p["auth"] for p in pc.CATALOG))
check("every key provider names its env var", all(p.get("env") for p in pc.CATALOG if "key" in p["auth"]))
check("every link is https (or the provider's own site)", all(str(p.get(k, "https://")).startswith("https://")
                                                              for p in pc.CATALOG for k in ("signup", "keys", "docs")))
check("GitHub Models (retired 2026-07-30) is not offered", "github-models" not in ids)
for wanted in ("opencode-zen", "codestral", "vercel", "nebius", "mlx", "lmstudio", "kyojin", "opencode", "pollinations",
               "deepinfra", "chutes", "baseten", "inference-net", "ai21", "upstage"):
    check("the portal offers %s" % wanted, wanted in ids)


class Cfg:
    def __init__(self, base, key, model):
        self.base_url, self.api_key, self.model = base, key, model


fake = types.SimpleNamespace()
fake.MODELS = {pid: Cfg("https://api.example/v1", "k-" + pid if pid in ("groq",) else "", "m-" + pid) for pid in ids}
fake.MODELS["claude-code"] = Cfg("cli-agent://claude-code", "", "claude-code")
fake.model_name, fake.SMART_ORDER = "smart", ("groq",)
fake.active_model_name = lambda: "groq"
fake.provider_configured = lambda n: n == "groq"
fake.is_metered = lambda n: n == "gpt"
env = {"GROQ_API_KEY": "secret-value-xyz", "LOKI_DISABLED_PROVIDERS": "cohere"}
view = pc.present(fake, env)
cards = {c["id"]: c for c in view["providers"]}
check("present() never contains a key value", "secret-value-xyz" not in json.dumps(view))
check("a configured provider shows as connected and in use", cards["groq"]["configured"] and cards["groq"]["active"]
      and cards["groq"]["has_key"])
check("a switched-off provider shows as off", cards["cohere"]["enabled"] is False)
check("the counter counts connected and enabled providers", view["connected"] == 1)
saved = {}
pc.set_enabled("groq", False, saved.update, env)
check("switching a provider off writes LOKI_DISABLED_PROVIDERS", set(saved["LOKI_DISABLED_PROVIDERS"].split(",")) == {"cohere", "groq"})
check("an unknown provider cannot be switched", not pc.set_enabled("nope", True, saved.update, env)["ok"])
listing = pc.list_models(fake, "groq", opener=lambda req, timeout: FakeResponse({"data": [{"id": "b"}, {"id": "a:free"}]}),
                         max_age=0)
check("the model list comes from /models, free first", listing["ok"] and listing["models"] == ["a:free", "b"])
seen = {}


def chat_opener(req, timeout):
    seen["body"] = json.loads(req.data.decode())
    seen["auth"] = req.headers.get("Authorization")
    return FakeResponse({"model": "m-groq", "choices": []})


result = pc.test(fake, "groq", opener=chat_opener)["test"]
check("Test sends one 1-token request with the key", result["ok"] and seen["body"]["max_tokens"] == 1
      and seen["auth"] == "Bearer k-groq")


def deny_opener(req, timeout):
    raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b'{"error": {"message": "bad key"}}'))


result = pc.test(fake, "groq", opener=deny_opener)["test"]
check("a rejected key is reported plainly", not result["ok"] and "rejected" in result["detail"] and "bad key" in result["detail"])
check("a CLI provider's test is whether it is installed", pc.test(fake, "claude-code")["test"]["ok"] is False)
saved.clear()
check("set_model writes <PROVIDER>_MODEL", pc.set_model(fake, "opencode-zen", "qwen3.6-plus-free", saved.update)["ok"]
      and saved == {"OPENCODE_ZEN_MODEL": "qwen3.6-plus-free"})

# --------------------------------------------------------------------------- sign-in
section("sign-in, sign-in codes and the phone (engine/signin.py)")
import base64  # noqa: E402
import hashlib  # noqa: E402
import urllib.parse  # noqa: E402

import signin  # noqa: E402

verifier, challenge = signin.pkce_pair()
check("PKCE challenge = base64url(sha256(verifier))", challenge == base64.urlsafe_b64encode(
    hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode() and 43 <= len(verifier) <= 128)
flow = signin.openrouter_start(8767, "browser")
q = urllib.parse.parse_qs(urllib.parse.urlparse(flow["url"]).query)
check("browser sign-in calls back to this engine on localhost",
      q["callback_url"] == ["http://localhost:8767/oauth/openrouter/callback"] and q["code_challenge_method"] == ["S256"])
phone = signin.openrouter_start(8767, "code")
check("phone sign-in has no callback (OpenRouter shows a code)", "callback_url" not in urllib.parse.parse_qs(
    urllib.parse.urlparse(phone["url"]).query))
got = {}


def exchange_opener(req, timeout):
    got.update(json.loads(req.data.decode()))
    return FakeResponse({"key": "sk-or-new"})


connected = []
res = signin.openrouter_finish(phone["state"], "the-code", lambda p, k: (connected.append((p, k)), {"ok": True})[1],
                               opener=exchange_opener)
check("the code is swapped for a key with the verifier", res["ok"] and got["code"] == "the-code"
      and got["code_verifier"] and connected == [("openrouter", "sk-or-new")])
check("a finished sign-in reports done", signin.flow_status(phone["state"])["done"])
check("an unknown state is refused", not signin.openrouter_finish("forged", "x", lambda p, k: {"ok": True})["ok"])
check("sign-in codes need an OAuth app id", not signin.device_start("huggingface", {}, lambda p, k: {})["ok"])

answers = iter([{"device_code": "d", "user_code": "ABCD-1234", "verification_uri": "https://huggingface.co/device",
                 "interval": 1, "expires_in": 60},
                {"error": "authorization_pending"}, {"error": "slow_down"}, {"access_token": "hf_token"}])
saved_tokens = []
started = signin.device_start("huggingface", {"LOKI_HF_CLIENT_ID": "cid"},
                              lambda p, k: (saved_tokens.append((p, k)), {"ok": True})[1],
                              opener=lambda req, timeout: FakeResponse(next(answers)), sleep=lambda s: None)
for _ in range(50):
    if signin.flow_status(started["state"]).get("done"):
        break
    time.sleep(0.05)
check("the device flow shows the user code and finishes with a token", started["user_code"] == "ABCD-1234"
      and saved_tokens == [("huggingface", "hf_token")])

def fetch(url, data=None):
    """(status, body) without raising, and without any proxy (the page is on 127.0.0.1)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, "%s: %s" % (type(exc).__name__, exc)


handoff_keys = []
ho = signin.PhoneHandoff("gemini", "Gemini", lambda p, k: (handoff_keys.append((p, k)), {"ok": True, "message": "ok"})[1],
                         "127.0.0.1", lambda ip: True, ttl_s=30, bind="127.0.0.1")
code, page = fetch(ho.url)
check("the phone page is a form, served once to the private network", code == 200 and "Send a key to LOKI" in page
      and "<form" in page, ("elapsed=%.3f ttl=%r result=%r created=%r now=%r" % (time.time() - ho.created, ho.ttl_s,
                                                                                ho.result, ho.created, time.time()), code))
code, reply = fetch(ho.url, data=b"key=AIza-test")
check("posting the key connects it", code == 200 and handoff_keys == [("gemini", "AIza-test")] and "&#10003;" in reply,
      (code, reply[-260:], handoff_keys))
code, _ = fetch(ho.url)
check("the page stops working after one key", code in (0, 410), code)
ho.stop()
ho2 = signin.PhoneHandoff("gemini", "Gemini", lambda p, k: {"ok": True}, "127.0.0.1", lambda ip: False, ttl_s=30, bind="127.0.0.1")
check("devices outside the private network are refused", fetch(ho2.url)[0] == 403)
ho2.stop()
ho3 = signin.PhoneHandoff("gemini", "Gemini", lambda p, k: {"ok": True}, "127.0.0.1", lambda ip: True, ttl_s=30, bind="127.0.0.1")
check("a wrong token is refused", fetch(ho3.url.rsplit("/", 1)[0] + "/wrong-token")[0] == 404)
ho3.stop()

# --------------------------------------------------------------------------- update everywhere
section("one click updates every machine (engine/update_all.py, updater health)")
import update_all  # noqa: E402
import updater  # noqa: E402


class FakeUpdater:
    def __init__(self, behind=True):
        self.behind = behind
        self.STATE = {"latest": "bbbbbbbbbbbb"}
        self.updated = False

    def version(self, repo=None):
        return {"commit": "bbbbbbbbbbbb" if self.updated else "aaaaaaaaaaaa", "dirty": False}

    def check(self, fetch=True):
        return {"ok": True, "current": self.version()["commit"], "latest": "bbbbbbbbbbbb"}

    def update(self):
        if self.behind and not self.updated:
            self.updated = True
            return {"updated": True, "note": "updated aaaa -> bbbb", "error": ""}
        return {"updated": False, "note": "up to date (bbbb)", "error": ""}

    def restart_needed(self):
        return False


peer_state = {"pc": "aaaaaaaaaaaa"}
calls = []


def fake_call(peer, method, path, body):
    calls.append((peer["name"], path, body))
    if peer["name"] == "offline":
        raise OSError("down")
    peer_state[peer["name"]] = "bbbbbbbbbbbb"       # it updates and restarts
    return {"ok": True, "restarting": True, "version": {"commit": "aaaaaaaaaaaa"}}


def fake_hello(peer):
    return {"version": {"commit": peer_state.get(peer["name"], "")}}


restarted = []
fu = FakeUpdater()
progress = update_all.run(fu, [{"name": "pc"}, {"name": "offline"}], fake_call, fake_hello,
                          lambda: restarted.append(True), wait_s=5, poll_s=0, sleep=lambda s: None)
steps = {s["machine"]: s for s in progress["steps"]}
check("the other machine is asked to update to GitHub's newest", calls[0] == ("pc", "/peer/update/apply", {"target": "bbbbbbbbbbbb"}))
check("it is watched until it runs the new version", steps["pc"]["status"] == "done")
check("an offline machine is noted, not fatal", steps["offline"]["status"] == "offline")
check("this machine updates last and restarts", steps["this computer"]["status"] == "restarting" and restarted == [True])
check("the run is finished", not progress["running"] and progress["finished"])
over = update_all.overview(fu, [{"name": "pc", "ok": True, "hello": {"version": {"commit": "aaaaaaaaaaaa"}}}])
check("overview says who is behind", [m["machine"] for m in over["machines"] if m["behind"]] == ["pc"])
here = update_all.apply_here(FakeUpdater(behind=False), lambda: None)
check("a machine already up to date says so and does not restart", here["ok"] and here.get("up_to_date") and not here.get("restarting"))

if shutil.which("git"):
    def sh(cwd, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t", GIT_TERMINAL_PROMPT="0")
        p = subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    origin = TMP / "github.git"
    sh(TMP, "git", "init", "-q", "--bare", "-b", "master", str(origin))
    seed = TMP / "seed"
    seed.mkdir()
    sh(seed, "git", "init", "-q", "-b", "master")
    (seed / "a.txt").write_text("v1\n", encoding="utf-8")
    sh(seed, "git", "add", "-A")
    sh(seed, "git", "commit", "-q", "-m", "v1")
    sh(seed, "git", "remote", "add", "origin", str(origin))
    sh(seed, "git", "push", "-q", "origin", "master")
    machine = TMP / "machine"
    sh(TMP, "git", "clone", "-q", str(origin), str(machine))
    v1 = updater.version(machine)["commit"]
    updater.mark_good(machine)
    (seed / "a.txt").write_text("v2 broken\n", encoding="utf-8")
    sh(seed, "git", "commit", "-q", "-am", "v2")
    sh(seed, "git", "push", "-q", "origin", "master")
    result = updater.update(machine)
    v2 = updater.version(machine)["commit"]
    h = updater.health(machine)
    check("an update is put on trial (pending) with the old commit as last good",
          result["updated"] and h["pending"] == v2 and h["last_good"] == v1)
    back = updater.rollback(machine)
    check("a version that does not start is rolled back to the last good one",
          back["ok"] and updater.version(machine)["commit"] == v1 and (machine / "a.txt").read_text() == "v1\n")
    again = updater.update(machine)
    check("the bad version is not applied again", not again["updated"] and "did not start" in again["note"])
    (seed / "a.txt").write_text("v3 fixed\n", encoding="utf-8")
    sh(seed, "git", "commit", "-q", "-am", "v3")
    sh(seed, "git", "push", "-q", "origin", "master")
    fixed = updater.update(machine)
    check("a newer version (the fix) is applied normally", fixed["updated"] and (machine / "a.txt").read_text() == "v3 fixed\n")
    updater.mark_good(machine)
    check("a started version is marked good", updater.health(machine)["pending"] == "" and
          updater.health(machine)["last_good"] == updater.version(machine)["commit"])
    check("the health record lives inside that checkout's .git (tests never touch the real one)",
          (machine / ".git" / "loki_update_health.json").is_file())
    check("a newer or equal commit is not 'behind'", not updater.is_behind(updater.version(machine)["commit"],
                                                                           v1, machine)
          and updater.is_behind(v1, updater.version(machine)["commit"], machine))
    check("a version that is not on trial is never rolled back", not updater.rollback(machine)["ok"])
else:
    print("  SKIP git checks: git is not installed")

# --------------------------------------------------------------------------- agents
section("the agent builder (engine/agents.py)")
import agents  # noqa: E402

skills_root = TMP / "skills"
(skills_root / "video-notes").mkdir(parents=True)
(skills_root / "video-notes" / "SKILL.md").write_text(
    "---\nname: video-notes\ndescription: Summarise videos with timestamps\n---\n\n# Video notes\nAlways add timestamps.\n",
    encoding="utf-8")
catalog = agents.skills_catalog([("yours", skills_root)])
check("skills are found from SKILL.md frontmatter", catalog and catalog[0]["id"] == "video-notes"
      and "timestamps" in catalog[0]["description"])
spec = agents.validate({"name": "Clipper", "engine": "opencode", "skills": ["video-notes"], "tools": ["media", "bogus"],
                        "machine": "pc", "memory": "agent", "max_minutes": 9999, "color": "#123456", "fallback": "local"})
check("the profile keeps skills, tools, machine, memory, colour and fallback",
      spec["skills"] == ["video-notes"] and spec["tools"] == ["media"] and spec["machine"] == "pc" and spec["memory"] == "agent"
      and spec["color"] == "#123456" and spec["fallback"] == "local" and spec["max_minutes"] == 24 * 60)
for bad, why in (({"name": ""}, "a name"), ({"name": "x", "memory": "forever"}, "memory"),
                 ({"name": "x", "machine": "a;b"}, "machine"), ({"name": "x", "skills": ["../etc"]}, "skill")):
    try:
        agents.validate(bad)
        check("validate refuses a bad %s" % why, False)
    except ValueError:
        check("validate refuses a bad %s" % why, True)
text = agents.full_instructions(dict(spec, instructions="Cut clips.", goal="clip videos", role="create"), catalog)
check("instructions include the goal, the tool rule and the skill text", "Goal: clip videos" in text
      and "media (" in text and "Always add timestamps." in text)
job = agents.job_spec(dict(spec, engine="loki"), "clip this", str(TMP), catalog=catalog)
check("a LOKI job carries the profile, its time limit and its colour", job["profile"]["instructions"] == agents.full_instructions(dict(spec, engine="loki"), catalog)
      and job["timeout_s"] == 24 * 3600 and job["color"] == "#123456" and job["agent_id"] == "clipper")
check("an agent with the commands tool may run commands", agents.job_spec(agents.validate({"name": "b", "tools": ["commands"]}),
                                                                          "t", str(TMP))["allow_commands"])
check("a remote agent's profile rides in the prompt", "You are the agent" in agents.remote_prompt(job) and "clip this" in agents.remote_prompt(job))
drafted = agents.draft("watch YouTube videos about Godot and write summaries with timestamps", catalog)
check("draft() builds a full agent from one sentence", drafted["name"] and "media" in drafted["tools"]
      and drafted["role"] in ("research", "helper", "create") and "video-notes" in drafted["skills"])
check("drafting a builder lets it run commands", agents.draft("fix bugs and run the tests")["allow_commands"])
check("every template is a valid agent", all(agents.validate(t) for t in agents.TEMPLATES))
check("the app-idea template is there (Appidea)", any(t["id"] == "app-idea" for t in agents.TEMPLATES))

section("Ruflo, built in (engine/ruflo_library.py, contrib/ruflo)")
import ruflo_library  # noqa: E402

_rs = ruflo_library.summary()
check("Ruflo's agents and skills are in the repo with its MIT licence and provenance",
      _rs["agents"] >= 90 and _rs["skills"] >= 35 and (REPO / "contrib" / "ruflo" / "LICENSE").is_file()
      and "1882006a" in (REPO / "contrib" / "ruflo" / "PROVENANCE.md").read_text(encoding="utf-8"), _rs)
_rt = ruflo_library.templates()
check("every Ruflo agent becomes a valid LOKI agent template", _rt and all(agents.validate(t) for t in _rt))
check("Ruflo's coder playbook backs LOKI's builder role", "Code Implementation" in ruflo_library.playbook("builder"))
_roots = agents.skill_roots(REPO, TMP)
_cat = agents.skills_catalog(_roots)
check("Ruflo skills are in the skill catalog", any(s["source"] == "ruflo" for s in _cat))
check("a Ruflo skill that tries to override LOKI's rules is never offered",
      not any(s["id"] == "github-project-management" for s in _cat))
check("no Ruflo file is executable code (LOKI only reads them)",
      not [p for p in (REPO / "contrib" / "ruflo").rglob("*") if p.is_file() and p.suffix not in (".md", "")
           and p.name not in ("LICENSE", "plugin.json")])
_mcp = json.loads((REPO / "engine" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
check("Ruflo's MCP server is there, opt-in", _mcp.get("ruflo", {}).get("enabled") is False
      and _mcp["ruflo"]["args"][-2:] == ["mcp", "start"])
import team as team_mod  # noqa: E402
check("team roles get Ruflo's playbook after LOKI's own brief",
      team_mod._with_playbook("builder", "BRIEF").startswith("BRIEF") and "Ruflo" in team_mod._with_playbook("builder", "BRIEF"))
check("all of Ruflo is in: core + plugin agents, skills, commands, plugins",
      _rs["agents"] >= 140 and _rs["skills"] >= 180 and _rs["commands"] >= 190 and _rs["plugins"] >= 45, _rs)
check("plugin skills are in the skill catalog too",
      any(str(s.get("path", "")).replace("\\", "/").count("/plugins/") for s in _cat if s["source"] == "ruflo"))
_sp = ruflo_library.command_prompt("sparc", "build a todo app")
check("a Ruflo command becomes a playbook for a LOKI task (task first, LOKI's rules win)",
      _sp.startswith("## Task\nbuild a todo app") and "LOKI's rules" in _sp and "SPARC" in _sp)
try:
    ruflo_library.command_prompt("no-such-command-xyz", "x")
    _bad = False
except KeyError:
    _bad = True
check("an unknown Ruflo command is reported", _bad)
_pl = {p["name"]: p for p in ruflo_library.plugins()}
check("each plugin is listed with what it brings", _pl.get("ruflo-swarm", {}).get("agents", 0) >= 2
      and "topolog" in _pl["ruflo-swarm"]["description"], _pl.get("ruflo-swarm"))
import portal_api  # noqa: E402
_code, _rf = portal_api.handle_get(types.SimpleNamespace(agent=None), "/ruflo")
check("GET /ruflo serves the commands, plugins and the ReasoningBank count",
      _code == 200 and len(_rf["commands"]) >= 190 and "reasoning_bank" in _rf and "path" not in _rf["commands"][0])

section("SPARC teams (Ruflo's method on LOKI's team stages)")
check("'sparc: <goal>' picks the SPARC method and strips the prefix",
      team_mod.team_method("SPARC: build a todo app") == ("sparc", "build a todo app"))
check("a plain goal stays standard", team_mod.team_method("build a todo app")[0] == "standard")
_spt = {"id": "t1", "goal": "build a todo app", "roles": ["researcher", "architect", "builder"], "method": "sparc"}
check("each SPARC role gets its phase", "Specification" in team_mod.agent_prompt(_spt, "researcher")
      and "TDD anchors" in team_mod.agent_prompt(_spt, "architect")
      and "test-first" in team_mod.agent_prompt(_spt, "builder"))
check("a standard team gets no SPARC text",
      "SPARC" not in team_mod.agent_prompt(dict(_spt, method="standard"), "builder"))

section("ReasoningBank (lessons from past tasks, engine/reasoning_bank.py)")
import reasoning_bank  # noqa: E402
_rb = TMP / "rb"
_bad_run = [{"role": "user", "content": "give LOKI its Nordic identity logo in the sidebar"}]
for _i in range(5):
    _bad_run.append({"role": "assistant", "content": "", "tool_calls": [
        {"id": "c%d" % _i, "function": {"name": "conductor", "arguments": "{}"}}]})
    _bad_run.append({"role": "tool", "tool_call_id": "c%d" % _i, "content": "not allowed in a background job: conductor"})
_bad_run.append({"role": "assistant", "content": "BLOCKED: every provider is out"})
reasoning_bank.remember("give LOKI its Nordic identity logo in the sidebar", "blocked", "failed", _bad_run, root=_rb)
_good = [{"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "search_files"}},
          {"id": "b", "function": {"name": "edit_file"}}, {"id": "c", "function": {"name": "check_loki"}}]},
         {"role": "tool", "tool_call_id": "a", "content": "app/ui/app.css:10"},
         {"role": "assistant", "content": "DONE: added the L mark to the sidebar CSS"}]
reasoning_bank.remember("add an L logo mark to the sidebar css", "done", "verified", _good, root=_rb)
reasoning_bank.remember("what is the weather in oslo", "done", "", [{"role": "assistant", "content": "DONE: sunny"}], root=_rb)
_rc = reasoning_bank.recall("change the sidebar logo to the Nordic L mark", root=_rb)
check("similar past tasks are recalled, an unrelated one is not",
      len(_rc) == 2 and not any("weather" in i["goal"] for i in _rc), _rc)
_note = reasoning_bank.prompt_for("change the sidebar logo to the Nordic L mark", root=_rb)
check("the lesson names the repeated error of the failure",
      "FAILED" in _note and "conductor: not allowed in a background job" in _note and "(x5)" in _note, _note)
check("and what worked, step by step", "WORKED" in _note and "search_files > edit_file > check_loki" in _note, _note)
check("nothing is recalled for a new kind of task", reasoning_bank.prompt_for("compose a haiku about rain", root=_rb) == "")
os.environ["LOKI_REASONING_BANK"] = "off"
check("LOKI_REASONING_BANK=off turns it off",
      reasoning_bank.prompt_for("change the sidebar logo to the Nordic L mark", root=_rb) == "")
os.environ.pop("LOKI_REASONING_BANK")
reasoning_bank.remember("sk-abcdefghijklmnop1234 key setup for groq", "done", "", _good, root=_rb)
check("secrets are masked in the bank", "sk-abcdefghijklmnop1234" not in (_rb / "experience" / "reasoning_bank.jsonl").read_text())

# --------------------------------------------------------------------------- runners + conductor
section("new specialists: media (yt-dlp), image, reach (engine/conductor.py)")
import conductor  # noqa: E402
import policy as policy_mod  # noqa: E402

for name in ("media", "imagegen", "reach"):
    proc = subprocess.run([sys.executable, "-I", str(REPO / "engine" / "runners" / (name + ".py"))],
                          input=json.dumps({"op": "nope", "prompt": ""}), capture_output=True, text=True, timeout=60)
    line = (proc.stdout.strip().splitlines() or ["{}"])[-1]
    check("runner %s answers bad input with a JSON error" % name, json.loads(line).get("ok") is False)
sys.path.insert(0, str(REPO / "engine" / "runners"))
import imagegen  # noqa: E402

_ms_calls = []


def _ms_request(url, key, body=None, headers=None, timeout=60):
    _ms_calls.append((url, body, headers or {}))
    if body is not None:
        return {"task_id": "t1"}
    return {"task_status": "SUCCEED" if len(_ms_calls) > 2 else "RUNNING", "output_images": ["https://img.example/a.png"]}


class _Img(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


os.environ["MODELSCOPE_API_KEY"] = "ms-test"
_saved_urlopen = imagegen.urllib.request.urlopen
imagegen.urllib.request.urlopen = lambda *a, **k: _Img(b"\x89PNG fake")
try:
    _img = imagegen.qwen("a red fox", 1024, 768, str(TMP / "images"), 0, sleep=lambda s: None, request=_ms_request)
finally:
    imagegen.urllib.request.urlopen = _saved_urlopen
    os.environ.pop("MODELSCOPE_API_KEY")
check("Qwen-Image 2.1 (ModelScope, free) submits an async task and polls it",
      _ms_calls[0][0].endswith("/v1/images/generations") and _ms_calls[0][2].get("X-ModelScope-Async-Mode") == "true"
      and _ms_calls[0][1]["model"] == "Qwen/Qwen-Image-2.1" and _ms_calls[0][1]["size"] == "1024x768"
      and _ms_calls[-1][0].endswith("/v1/tasks/t1") and _img["backend"] == "qwen" and Path(_img["file"]).read_bytes().startswith(b"\x89PNG"))
_plans_tried = []


def _fake_child(argv, input, **kw):
    plan = json.loads(input)["plan"]["name"]
    _plans_tried.append(plan)
    if plan == "offload-bf16":
        return types.SimpleNamespace(stdout="", stderr="stage: import torch\nstage: denoise\nFatal Python error: Segmentation fault\n\n"
                                     'Current thread 0x1 (most recent call first):\n'
                                     '  File "C:\\py\\diffusers\\models\\attention.py", line 88 in forward\n'
                                     '  File "C:\\py\\torch\\nn\\module.py", line 1 in _call_impl\n',
                                     returncode=-11)   # native crash
    return types.SimpleNamespace(stdout=json.dumps({"ok": True, "file": "x.png", "backend": "zimage", "plan": plan}),
                                 stderr="", returncode=0)


os.environ["LOKI_DATA"] = str(TMP / "data")
_z = imagegen.zimage("a fox", 768, 768, str(TMP / "images"), 0, run=_fake_child)
check("a Z-Image crash (segfault) falls back to the next, safer plan", _plans_tried == ["offload-bf16",
      "offload-bf16-math-attn"] and _z["plan"] == "offload-bf16-math-attn" and "crashed" in _z.get("note", ""), _z)
check("a crash says which stage it died in", "during denoise" in _z.get("note", ""), _z)
check("and the line of code it died on", "attention.py:88 in forward" in _z.get("note", ""), _z)
check("there is a plan that loads weights without mmap", any(p.get("mmap") is False for p in imagegen.ZIMAGE_PLANS))
_plans_tried.clear()
imagegen.zimage("a fox", 768, 768, str(TMP / "images"), 0, run=_fake_child)
check("the plan that worked is tried first next time", _plans_tried == ["offload-bf16-math-attn"], _plans_tried)
check("conductor knows the media, image and reach roles", {"media", "image", "reach"} <= set(conductor.ROLES))


class _OnlyMedia:
    def capability(self, name, permission=""):
        if name == "media":
            return policy_mod.Verdict(policy_mod.ALLOW, "ok")
        return policy_mod.Verdict(policy_mod.DENY, "%s changed since you enabled it - review and enable it again" % name)


_ps = conductor.Conductor(_OnlyMedia(), None, env={}).prompt_section()
check("the model is told which specialists are off and the real reason (no invented 'needs approval')",
      "- media:" in _ps and "Not available right now" in _ps and "image: image-gen changed since you enabled it" in _ps, _ps)


class AllowAll:
    def capability(self, name, permission=""):
        return policy_mod.Verdict(policy_mod.ALLOW, "ok")


runs = []


def fake_runner(argv, input, **kw):
    job = json.loads(input)
    runs.append((Path(argv[-1]).stem, job))
    out = {"media": {"ok": True, "title": "Talk", "text": "hello [00:01]"},
           "imagegen": {"ok": True, "file": "images/fox.png", "backend": "pollinations"},
           "reach": {"ok": True, "text": "page text"}}[Path(argv[-1]).stem]
    return types.SimpleNamespace(stdout=json.dumps(out), stderr="", returncode=0)


cond = conductor.Conductor(AllowAll(), None, env={"LOKI_WORKSPACE": str(TMP)}, runner=fake_runner, python="python")
check("media: a transcript by default", "hello" in cond.run("media", "", "https://youtu.be/x")
      and runs[-1][1]["op"] == "transcript")
cond.run("media", "search: godot shaders")
check("media: 'search: words' searches", runs[-1][1] == {"op": "search", "query": "godot shaders"})
check("image: the file is reported", "images/fox.png" in cond.run("image", "a fox") and runs[-1][1]["out_dir"].endswith("images"))
check("reach: a url is read as text", cond.run("reach", "", "https://example.com") == "page text" and runs[-1][1]["op"] == "read")
cond.run("reach", "github: m03dev/loki")
check("reach: github goes to gh", runs[-1][1]["op"] == "github")

section("capability manifests")
import manifests  # noqa: E402

for name in ("opencode", "agent-reach", "media", "image-gen", "mlx", "kyojin", "ruflo"):
    data = json.loads((REPO / "capabilities" / name / "manifest.json").read_text(encoding="utf-8"))
    check("manifest %s is valid" % name, manifests.validate(data) == [], manifests.validate(data))
check("OpenCode jobs need the opencode capability", policy_mod.AGENT_CAPABILITY.get("opencode") == "opencode")

import addons_install  # noqa: E402


class _Done:
    returncode = 0
    stdout = "Successfully installed scrapling"
    stderr = ""


_pip_calls = []


def _fake_pip(argv, **kw):
    _pip_calls.append((argv, kw))
    return _Done()


_res = addons_install.install("scrapling", python="/py", run=_fake_pip)
check("installing an add-on runs pip in LOKI's own venv and never a shell string",
      _res["ok"] and _pip_calls and _pip_calls[0][0][:3] == ["/py", "-m", "pip"]
      and "scrapling" in _pip_calls[0][0] and "shell" not in _pip_calls[0][1])
check("an add-on pip cannot install says so instead of running anything",
      addons_install.install("herdr")["ok"] is False and "herdr.dev" in addons_install.install("herdr")["error"])
check("the app offers Install for pip add-ons (plan + endpoint + UI wiring)",
      addons_install.pip_specs("browser-use") == ["browser-use"] and bool(addons_install.pip_specs("vision-track"))
      and "/capabilities/install" in (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
      and "capabilities/install" in (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8"))

import os as _os  # noqa: E402
_sentinel = _os.path.basename(sys.executable)
check("a console script in LOKI's own venv counts as installed (it is not on PATH)",
      manifests._which(_sentinel, which=lambda _c: None) == _os.path.join(_os.path.dirname(sys.executable), _sentinel))
check("OBLITERATUS is not integrated", not (REPO / "capabilities" / "obliteratus").exists())

# --------------------------------------------------------------------------- UI
section("the UI")
ui = REPO / "app" / "ui"
html = (ui / "index.html").read_text(encoding="utf-8")
for marker in ('data-tab="general"', 'data-tab="agents"', 'data-tab="world"', 'id="portal"', 'id="qr-modal"',
               'id="update-banner"', 'id="world-bg-canvas"', "/ui/settings.js", "/ui/world.js"):
    check("index.html has %s" % marker, marker in html)
check("still CSP-clean (no inline script or style)", "<script>" not in html and " style=" not in html and "onclick" not in html)
settings_js = (ui / "settings.js").read_text(encoding="utf-8")
world_js = (ui / "world.js").read_text(encoding="utf-8")
check("the portal tests, signs in, hands off and updates everywhere", all(s in settings_js for s in (
    "/providers/test", "/signin/openrouter", "/handoff", "/update/everywhere", "/agents/draft", "/agents/launch")))
check("the world draws with WebGL from /world only", "getContext(\"webgl\"" in world_js and 'api("/world")' in world_js
      and "fetch(" not in world_js)
check("the world pauses when it cannot be seen", "document.hidden" in world_js and "requestAnimationFrame" in world_js)
check("the world draws pixelated: a low-res framebuffer blown up with NEAREST",
      "createFramebuffer" in world_js and "gl.TEXTURE_MAG_FILTER, gl.NEAREST" in world_js
      and "checkFramebufferStatus" in world_js and "Math.ceil(w / scale)" in world_js)
check("the pixel upscale uses a whole-number scale and handles devicePixelRatio and resize",
      "devicePixelRatio" in world_js and "Math.round((World.pixel || view.opts.pixel" in world_js
      and "canvas.width !== w" in world_js)
check("without a framebuffer the world still draws (straight to the canvas)", "fbFailed = true" in world_js
      and "fb ? fb.fbo : null" in world_js)
check("the world dithers its colours (ordered Bayer dither)", "bayer4(" in world_js)
check("the world is cel-shaded: lighting quantized into bands", "const float BANDS" in world_js
      and "floor(clamp(x,0.0,1.0) * BANDS)" in world_js and "sunDir" in world_js and "rimCol" in world_js)
check("the world has ink outlines (inflated back-face hull)", "OUTLINE_VS" in world_js and "gl.cullFace(gl.FRONT)" in world_js)
check("the world has a sky, an island, props, shadows and lights", all(s in world_js for s in (
    "SKY_FS", "ISLAND", "SCENERY.trees", "SCENERY.rocks", "SCENERY.lamps", "L.shadows", "L.glows", "LP[10]")))
check("the background world is frame-capped", "fps: 30" in world_js and "1000 / fps" in world_js)
check("the world loads nothing from outside and never evals", all(s not in world_js for s in (
    "http://", "https://", "eval(", "new Function", "XMLHttpRequest", "import(")))
check("the static scene is baked once into a few buffers (land, sky, shadows)", all(s in world_js for s in (
    "function bake(", "BAKED_VS", "BAKED_OUTLINE_VS", "SHADOW_VS", "view.batches.land", "view.batches.shadows")))
check("a lost WebGL context is rebuilt, not left black", "webglcontextrestored" in world_js and "initGL(view)" in world_js)
three_js = (ui / "world_three.js").read_text(encoding="utf-8") if (ui / "world_three.js").exists() else ""
three_imports = re.findall(r'from\s+"(\./[^"]+)"', three_js)
three_missing = [m for m in three_imports if not (ui / m.lstrip("./")).exists()]
check("every import in the three.js renderer is vendored and present (add-ons committed, not git-ignored)",
      bool(three_imports) and not three_missing, "missing: %s" % three_missing)
check("the old Godot ignore rules stay anchored to the repo root (they used to swallow the three add-ons)",
      not any(l.strip() in ("addons/", "scenes/", "scripts/") for l in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()))
check("the frame-time watcher coarsens pixels only when it helps", "function watchFrames(" in world_js
      and "pf.trial" in world_js and "noGain" in world_js and "World.adaptive" in world_js)
check("lights are ranked so a blocked agent's red light is never dropped",
      ".sort((a, b) => (b.pri || 0) - (a.pri || 0)).slice(0, 10)" in world_js)
check("the world can be inspected: click to pick, a card from /world, follow, Esc, pinch",
      all(s in world_js for s in ("function pickAgent(", "function updateCard(", "view.follow", '"Escape"', "pointercancel", "view.pinch")))
check("the life-sim layer: paths round the plaza, benches, chat dots, team banners with real stages, a HUD",
      all(s in world_js for s in ("function routeTo(", "SCENERY.benches", '"···"', "tm.stages", "function updateHud(")))
check("labels never pile up (nearest first, lifted, crowded fade)", '"crowded"' in world_js)
check("ambience stops with reduced motion", world_js.count("World.reduced") >= 10)
noise_js = (ui / "world_noise.js").read_text(encoding="utf-8")
check("the water noise is the MIT webgl-noise code, credited, with its licence",
      "stegu/webgl-noise" in noise_js and "Permission is hereby granted" in noise_js and "float snoise(vec2 v)" in noise_js
      and "vec2 cellular(vec2 P)" in noise_js and noise_js.count("vec3 permute(vec3 x)") == 1)
check("index.html loads the noise before the world", html.index("/ui/world_noise.js") < html.index("/ui/world.js"))
check("water has its own shader: exact shore distance, Beer-Lambert depth, foam, caustics, fresnel, ripples, a falling sheet",
      all(x in world_js for x in ("WATER_FS", "float shore(vec2 p)", "exp(-max(s, 0.0) * beer)", "cellular(", "pow(1.0 - max(dot(N, V), 0.0), 5.0)",
                                  "rip[4]", "vec4 sheet()", "function drawWater(")))
check("without the noise (or a shader that will not compile) the world still draws", "typeof WORLD_NOISE_GLSL" in world_js
      and "if (view.water)" in world_js)
check("the water's noise time wraps, so float precision holds in a long session", "t % 600" in world_js)
three_js = (ui / "world_three.js").read_text(encoding="utf-8")
check("the world has a three.js renderer (vendored, local, MIT) with PBR, shadows, bloom and tone mapping",
      (ui / "vendor" / "three" / "three.module.js").is_file() and (ui / "vendor" / "three" / "LICENSE").is_file()
      and all(x in three_js for x in ("MeshStandardMaterial", "castShadow", "UnrealBloomPass", "ACESFilmicToneMapping", "InstancedMesh")))
check("three.js loads only from LOKI itself (no CDN), and only on demand (LOKI_WORLD_ENGINE=three)",
      "https://" not in three_js and 'src="/ui/world_three.js"' not in html and 's.src = "/ui/world_three.js"' in world_js)
vendored = [p for p in (ui / "vendor" / "three").rglob("*.js")]
check("vendored add-ons import three by a local path, never the bare 'three' specifier",
      not any(("from 'three'" in p.read_text(encoding="utf-8") or 'from "three"' in p.read_text(encoding="utf-8")) for p in vendored))
check("LOKI's own pixel cel-shaded renderer is the default look; three.js only when asked",
      'engine: "classic"' in world_js and 'World.engine === "three"' in world_js and "function initGL(" in world_js)
check("denser pixels and more colour bits than the first pixel look",
      '"const float BANDS = 4.0;"' in world_js and "view.opts.levels || 32" in world_js and "pixel: 2, fps: 0" in world_js)
check("island life: the fox and the rabbits", "function critters(" in world_js and 'kind: "fox"' in world_js)
check("the world shows your other machines, the model and today's usage",
      all(x in world_js for x in ("World.data.machines", "machineSpots", "model.local", "usage.calls")))
glass = (ui / "glass.css").read_text(encoding="utf-8")
check("the glass look without live blur over the moving world (the lag): tinted panels, gradients",
      "--blur: none;" in glass and "--grad:" in glass and "prefers-reduced-transparency" in glass
      and "backdrop-filter: blur(8px)" not in glass)
check("the world fills the window behind the glass", ".world-bg { position: fixed; inset: 0; }" in glass)
setup_js = (ui / "setup.js").read_text(encoding="utf-8")
check("setup.js no longer shares a global button() with settings.js (labels were swapped)",
      "function setupButton(" in setup_js and "function button(" not in setup_js)
check("the world keeps the functions app.js and settings.js call", all(
    ("function %s(" % f) in world_js for f in ("showWorldPanel", "hideWorldPanel", "setWorldMode")) and "window.afterStart" in world_js)
if shutil.which("node"):
    for name in ("app.js", "settings.js", "world.js", "world_noise.js", "setup.js", "machines.js", "workbench.js", "lab.js", "sketch.js"):
        proc = subprocess.run(["node", "--check", str(ui / name)], capture_output=True, text=True)
        check("%s parses" % name, proc.returncode == 0, proc.stderr)

# --------------------------------------------------------------------------- the engine
section("the engine itself (loki.py)")
try:
    import loki  # noqa: E402
except ImportError as exc:
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        check("loki.py imports", False, exc)
    else:
        print("  SKIP: %s (install engine/requirements.txt to run this part)" % exc)
    loki = None
if loki is not None:
    for pid in ("codestral", "opencode-zen", "vercel", "mlx", "lmstudio", "kyojin", "opencode", "nebius"):
        check("MODELS has %s" % pid, pid in loki.MODELS)
    check("every catalog provider exists in MODELS", all(p["id"] in loki.MODELS for p in pc.CATALOG), [p["id"] for p in pc.CATALOG if p["id"] not in loki.MODELS])
    check("every catalog key env is accepted by connect_provider",
          all(loki.PROVIDER_ENV_VARS.get(p["id"]) == p["env"] for p in pc.CATALOG if p.get("env") and p["group"] not in ("local",)),
          [p["id"] for p in pc.CATALOG if p.get("env") and loki.PROVIDER_ENV_VARS.get(p["id"]) != p["env"]])
    os.environ["LOKI_DISABLED_PROVIDERS"] = "groq"
    check("a switched-off provider is never configured", loki.provider_disabled("groq") and not loki.provider_configured("groq"))
    os.environ.pop("LOKI_DISABLED_PROVIDERS")
    check("a local server that is not running is not configured", not loki.provider_configured("vllm"))
    check("trial-credit providers count as paid", loki.is_metered("nebius") and not loki.is_metered("opencode-zen"))
    ident = loki.identity_section()
    check("LOKI's prompt says who it is and which model answers", "You are LOKI" in ident
          and loki.MODELS[loki.active_model_name()].model in ident and "Linked machines" in ident)
    check("the identity is part of the system prompt", "# Who you are right now" in loki.system_prompt())
    import first_layer  # noqa: E402
    check("a request to change LOKI's own code is recognised", first_layer.is_self_change(
        "Change your own code with improve_loki: give LOKI a logo") and first_layer.is_self_change("improve LOKI's UI")
          and not first_layer.is_self_change("change the code in my project"))
    _saved_mode, _saved_gp = loki.AGENT_MODE, loki.GAME_PROJECT
    try:
        loki.set_mode("build")
        loki.GAME_PROJECT = ""
        _offered = {t["function"]["name"] for t in loki.model_tool_schemas()}
        check("outside a Godot project the Godot tools are not offered", not (_offered & loki.GODOT_ONLY_TOOLS)
              and "write_file" in _offered, sorted(_offered & loki.GODOT_ONLY_TOOLS))
        _started = []
        _saved_imp, _saved_triage = loki.improve_loki, loki._triage
        loki.improve_loki = lambda task: (_started.append(task), "started job ab12: a LOKI agent is on it")[1]
        loki._triage = lambda text: {"self_change": True, "kind": "code", "route": "plan"}
        try:
            _reply = asyncio.run(loki.run_agent("improve LOKI's UI: add a logo"))
        finally:
            loki.improve_loki, loki._triage = _saved_imp, _saved_triage
        check("a self-change goes straight to improve_loki (no model needed)",
              _started == ["improve LOKI's UI: add a logo"] and "background LOKI agent" in _reply, _reply)
    finally:
        loki.AGENT_MODE, loki.GAME_PROJECT = _saved_mode, _saved_gp
    check("LOKI's own code changes use the best free online model by default", loki.IMPROVE_MODEL == "online")
    check("the improving agent can test with check_loki (it cannot run shell commands)",
          "check_loki" in loki.MODEL_TOOL_NAMES and "check_loki" in loki.SELF_IMPROVE_PROMPT
          and "never call improve_loki" in loki.SELF_IMPROVE_PROMPT)
    _saved_ws = loki.WORKSPACE
    _wt = TMP / "harness_data" / "worktrees" / "job1"
    (_wt / "engine").mkdir(parents=True, exist_ok=True)
    (_wt / "engine" / "loki.py").write_text("# loki\n", encoding="utf-8")
    (_wt / ".git").write_text("gitdir: x\n", encoding="utf-8")
    try:
        loki.WORKSPACE = _wt
        check("an improving agent cannot start another improving agent (no recursion)",
              loki.improve_loki("again").startswith("error: you are already the agent"))
    finally:
        loki.WORKSPACE = _saved_ws
    check("ship.py can run one suite for a quick check", "--only" in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
    import workers as _w  # noqa: E402
    check("jobs on the local model take turns (one GPU), cloud-model jobs do not",
          _w.uses_local_model({"agent": "loki", "backend": "local", "model": ""}, {"LOKI_PREFER": "local"})
          and not _w.uses_local_model({"agent": "loki", "backend": "local", "model": "online"}, {})
          and not _w.uses_local_model({"agent": "claude-code", "backend": "local"}, {}) and _w.local_model_limit({}) == 1)
    import cli_agents  # noqa: E402
    import workers  # noqa: E402
    check("OpenCode is a CLI agent and a background-job agent", "opencode" in cli_agents.CLI_AGENTS
          and workers.agent_argv("opencode", "do it", env={"LOKI_OPENCODE_MODEL": "opencode/x"}) == ["opencode", "run", "-m", "opencode/x", "do it"])

    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs
            message = types.SimpleNamespace(content='<tool_call>{"name": "list_files", "arguments": {"path": "."}}</tool_call>',
                                            tool_calls=None, role="assistant")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message, finish_reason="stop")], usage=None)

    fc = FakeCompletions()
    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=fc))
    response = asyncio.run(loki._model_request(client, {"model": "m", "messages": [{"role": "system", "content": "s"},
                                                                                    {"role": "user", "content": "list"}],
                                                        "tools": TOOLS}, loki.MODELS["mlx"], "mlx"))
    check("a prompted-tools provider gets no `tools` field", "tools" not in fc.kwargs and "<tools>" in fc.kwargs["messages"][0]["content"])
    calls_out = response.choices[0].message.tool_calls
    check("and its <tool_call> text comes back as a real tool call", calls_out and calls_out[0].function.name == "list_files")

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
