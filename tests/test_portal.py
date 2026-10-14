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
check("an earlier tool call becomes <tool_call> text", "<tool_call>" in out[2]["content"] and "a.txt" in out[2]["content"])
check("a tool result becomes a <tool_response> user turn", out[3]["role"] == "user" and "<tool_response>" in out[3]["content"])
check("no message keeps tool_calls or role=tool", all("tool_calls" not in m and m["role"] != "tool" for m in out))
prepared = tool_harness.prepare({"model": "m", "messages": msgs, "tools": TOOLS, "tool_choice": "required"})
check("prepare() drops tools and tool_choice", "tools" not in prepared and "tool_choice" not in prepared
      and prepared["_prompted_tools"] == ["read_file", "list_files"])
calls, rest = tool_harness.parse('Sure.\n<tool_call>\n{"name": "read_file", "arguments": {"path": "b.md"}}\n</tool_call>',
                                 ["read_file"])
check("a <tool_call> block is parsed", calls == [("read_file", {"path": "b.md"})] and rest == "Sure.")
calls, _ = tool_harness.parse('```json\n{"name": "list_files", "arguments": {}}\n```', ["read_file", "list_files"])
check("a ```json fence is parsed", calls == [("list_files", {})])
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
for wanted in ("opencode-zen", "codestral", "vercel", "nebius", "mlx", "lmstudio", "kyojin", "opencode", "pollinations"):
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

handoff_keys = []
ho = signin.PhoneHandoff("gemini", "Gemini", lambda p, k: (handoff_keys.append((p, k)), {"ok": True, "message": "ok"})[1],
                         "127.0.0.1", lambda ip: True, ttl_s=30, bind="127.0.0.1")
page = urllib.request.urlopen(ho.url, timeout=5).read().decode()
check("the phone page is a form, served once to the private network", "Send a key to LOKI" in page and "<form" in page)
reply = urllib.request.urlopen(urllib.request.Request(ho.url, data=b"key=AIza-test", method="POST"), timeout=5).read().decode()
check("posting the key connects it", handoff_keys == [("gemini", "AIza-test")] and "&#10003;" in reply)
try:
    urllib.request.urlopen(ho.url, timeout=5)
    check("the page stops working after one key", False)
except urllib.error.HTTPError as exc:
    check("the page stops working after one key", exc.code == 404)
except Exception:
    check("the page stops working after one key", True)
ho.stop()
ho2 = signin.PhoneHandoff("gemini", "Gemini", lambda p, k: {"ok": True}, "127.0.0.1", lambda ip: False, ttl_s=30, bind="127.0.0.1")
try:
    urllib.request.urlopen(ho2.url, timeout=5)
    check("devices outside the private network are refused", False)
except urllib.error.HTTPError as exc:
    check("devices outside the private network are refused", exc.code == 403)
try:
    urllib.request.urlopen(ho2.url.rsplit("/", 1)[0] + "/wrong-token", timeout=5)
except urllib.error.HTTPError as exc:
    check("a wrong token is refused", exc.code in (403, 404))
ho2.stop()

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
    h = updater.health()
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
    check("a started version is marked good", updater.health()["pending"] == "" and
          updater.health()["last_good"] == updater.version(machine)["commit"])
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

# --------------------------------------------------------------------------- runners + conductor
section("new specialists: media (yt-dlp), image, reach (engine/conductor.py)")
import conductor  # noqa: E402
import policy as policy_mod  # noqa: E402

for name in ("media", "imagegen", "reach"):
    proc = subprocess.run([sys.executable, "-I", str(REPO / "engine" / "runners" / (name + ".py"))],
                          input=json.dumps({"op": "nope", "prompt": ""}), capture_output=True, text=True, timeout=60)
    line = (proc.stdout.strip().splitlines() or ["{}"])[-1]
    check("runner %s answers bad input with a JSON error" % name, json.loads(line).get("ok") is False)
check("conductor knows the media, image and reach roles", {"media", "image", "reach"} <= set(conductor.ROLES))


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

for name in ("opencode", "agent-reach", "media", "image-gen", "mlx", "kyojin"):
    data = json.loads((REPO / "capabilities" / name / "manifest.json").read_text(encoding="utf-8"))
    check("manifest %s is valid" % name, manifests.validate(data) == [], manifests.validate(data))
check("OpenCode jobs need the opencode capability", policy_mod.AGENT_CAPABILITY.get("opencode") == "opencode")
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
if shutil.which("node"):
    for name in ("app.js", "settings.js", "world.js", "setup.js", "machines.js"):
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
