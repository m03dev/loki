"""Session 29: DeepSeek V4.1 Flash as LOKI's main driver, the LOKI MCP API, and LOKI Studio - offline.

  1. the rate limiter (engine/ratelimit.py): the per-minute cap, shared between processes, a 429 penalty
  2. LOKI's main driver: NVIDIA's DeepSeek V4.1 Flash first in smart/online routing for chat, background
     jobs, code, teams and self-improvement whenever its key is set; pictures / local-only / a dead key
     fall back; /models doctor says so; the Connections card says how to get the key
  3. the real agent loop against a FAKE NVIDIA server: tool calls, reasoning_content and <think> taken
     out of the history, chat_template_kwargs sent, requests paced under the cap (no 429), a 429 fails over
  4. the LOKI MCP API through the mcp client in-process: every tool, the dev-worktree jail (no .env,
     no harness_data, no escaping), approvals (refused without the owner's code), and - with a fake
     running engine - status, settings (no secrets), jobs, restart
  5. LOKI Studio with the engine STOPPED: a session on a scripted model makes a real edit in its own
     worktree, runs a (fake) check, waits for the owner's approval, cannot ship, the owner's follow-up
     continues the SAME session, Ship it needs the owner, stop, discard, history kept across restarts
  6. Studio's hands on LOKI: logs from disk, start, rollback (the updater's and by hand), the pinned copy
  7. Studio's server (token, Host check, CSP), its window in headless Chromium, LOKI's Studio button

    python tests/test_studio.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "studio"))
TMP = Path(tempfile.mkdtemp(prefix="loki-studio-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(TMP / "ws")
(TMP / "ws").mkdir(parents=True, exist_ok=True)
os.environ["LOKI_HEALTH_FILE"] = str(TMP / "provider_health.json")
os.environ["LOKI_HEALTH_PROBES"] = "0"
os.environ["LOKI_RATE_FILE_DIR"] = str(TMP / "ratelimit")
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_LOCAL_ONLY", "LOKI_MODEL", "LOKI_PREFER", "LOKI_ALLOW_PAID",
           "LOKI_DISABLED_PROVIDERS", "LOKI_MAIN_DRIVER", "LOKI_NVIDIA_THINKING", "LOKI_BRIDGE_URL", "LOKI_STUDIO_MODEL",
           "LOKI_STUDIO_REPO", "LOKI_NVIDIA_RPM"):
    os.environ.pop(_k, None)
for _k in [k for k in os.environ if k.endswith("_API_KEY")]:
    os.environ.pop(_k)

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:700],)))


def section(title):
    print("\n== " + title)


def git(cwd, *args):
    p = subprocess.run(["git", "-c", "user.email=t@loki", "-c", "user.name=t", *args], cwd=str(cwd),
                       capture_output=True, text=True)
    return p.stdout.strip()


# ----------------------------------------------------------------- a fake OpenAI-compatible cloud
class FakeCloud:
    """POST /<name>/v1/chat/completions answers from a per-name script; records every request.
    `cap` (requests per `window` s) makes it answer 429 itself when a client sends too fast."""

    def __init__(self):
        self.script: dict = {}
        self.calls: list = []
        self.cap = {}
        self.window = 1.0
        self.times: dict = {}
        cloud = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def do_POST(self):  # noqa: N802
                name = self.path.strip("/").split("/")[0]
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)) or b"{}")
                cloud.calls.append((name, body))
                now = time.time()
                stamps = [t for t in cloud.times.get(name, []) if now - t < cloud.window] + [now]
                cloud.times[name] = stamps
                if name in cloud.cap and len(stamps) > cloud.cap[name]:
                    status, payload, headers = 429, {"error": {"message": "Too Many Requests"}}, {"Retry-After": "1"}
                else:
                    queue = cloud.script.get(name) or []
                    status, payload, headers = queue.pop(0) if queue else ok_text("DONE: (script ran out)")
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802  (GET /models for probes)
                data = b'{"data": []}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, name):
        return "http://127.0.0.1:%d/%s/v1" % (self.port, name)

    def bodies(self, name):
        return [b for n, b in self.calls if n == name]


def reply(message, finish="stop"):
    return (200, {"id": "x", "object": "chat.completion", "created": 1, "model": "m",
                  "choices": [{"index": 0, "finish_reason": finish, "message": dict({"role": "assistant"}, **message)}],
                  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}, {})


def ok_text(text, **extra):
    return reply(dict({"content": text}, **extra))


def ok_tool(name, args, content=None, cid="c1", **extra):
    return reply(dict({"content": content, "tool_calls": [{"id": cid, "type": "function",
                                                           "function": {"name": name, "arguments": json.dumps(args)}}]},
                      **extra), "tool_calls")


def err(status, message, headers=None):
    return (status, {"error": {"message": message, "code": status}}, headers or {})


cloud = FakeCloud()

# ================================================================= 1. the rate limiter
section("1. the rate limiter (NVIDIA NIM: ~40 requests/min)")
import ratelimit  # noqa: E402

check("NVIDIA is paced at 36/min by default (40 minus headroom)", ratelimit.rpm("nvidia") == 36, ratelimit.rpm("nvidia"))
check("other providers are not paced", ratelimit.rpm("gemini") == 0)
os.environ["LOKI_NVIDIA_RPM"] = "3"
check("LOKI_NVIDIA_RPM overrides the cap", ratelimit.rpm("nvidia") == 3)
ratelimit.reset()
t0 = 1_000_000.0
for i in range(3):
    check("request %d fits the window" % (i + 1), ratelimit.wait_s("nvidia", now=t0 + i) == 0.0)
    ratelimit.take("nvidia", now=t0 + i)
w = ratelimit.wait_s("nvidia", now=t0 + 3)
check("the 4th waits until the oldest ages out of the minute (~57 s), it is not refused", 56 < w < 58, w)
ratelimit._local.clear()   # another process: only the shared file knows
check("the window is shared between processes (the data folder's file)", ratelimit.wait_s("nvidia", now=t0 + 3) > 50)
check("...and is free again a minute later", ratelimit.wait_s("nvidia", now=t0 + 61) == 0.0)
ratelimit.reset()
ratelimit.penalize("nvidia", 10, now=t0)
pw = ratelimit.wait_s("nvidia", now=t0)
check("a 429 anyway (another program on the key) makes the next requests wait its Retry-After", 9 < pw < 11, pw)
slept = []
ratelimit.reset()
for i in range(3):
    ratelimit.take("nvidia")
waited = ratelimit.acquire("nvidia", max_wait_s=5, sleep=lambda s: slept.append(s), say=lambda m: slept.append(m))
check("acquire() queues the request (waits, says why) instead of failing", waited > 0 and any(isinstance(s, str) and "requests a minute" in s for s in slept), slept)
ratelimit.reset()
os.environ.pop("LOKI_NVIDIA_RPM", None)

# ================================================================= 2. the main driver
section("2. DeepSeek V4.1 Flash on NVIDIA is LOKI's main driver")
import loki  # noqa: E402
import routing  # noqa: E402
import provider_health  # noqa: E402
import providers_catalog  # noqa: E402

check("NVIDIA's default model is DeepSeek V4.1 Flash", loki.MODELS["nvidia"].model == "deepseek-ai/deepseek-v4.1-flash",
      loki.MODELS["nvidia"].model)
check("NVIDIA's endpoint is integrate.api.nvidia.com/v1", loki.MODELS["nvidia"].base_url == "https://integrate.api.nvidia.com/v1")
check("the main driver leads the smart AND online order", loki.SMART_ORDER[0] == "nvidia" and loki.ONLINE_ORDER[0] == "nvidia",
      (loki.SMART_ORDER[:3], loki.ONLINE_ORDER[:3]))
check("every other provider is still there as the fallback", {"openrouter", "gemini", "groq", "local"} <= set(loki.SMART_ORDER))
check("the routing layer counts it as able to call tools (native) and a 1M context",
      routing.abilities(loki, "nvidia")["tools"] == "native" and routing.abilities(loki, "nvidia")["context"] >= 1_000_000,
      routing.abilities(loki, "nvidia"))
card = providers_catalog.get("nvidia") or {}
check("Connections card: the main driver, free, one-line setup with the key page",
      card.get("main_driver") and "DeepSeek V4.1 Flash" in card.get("blurb", "") and "build.nvidia.com" in card.get("blurb", "")
      and card.get("keys") == "https://build.nvidia.com/settings/api-keys", card)

ok, why = loki.main_driver_ready({})
check("with no key it does not drive, and says where the free key is", not ok and "build.nvidia.com/settings/api-keys" in why, why)
saved = (loki.online, loki.local_ready, loki.PREFER, loki.model_name, loki.MODELS["nvidia"].api_key)
loki.online = lambda *a, **k: True
loki.local_ready = lambda: True
loki.PREFER = "local"
loki.model_name = "smart"
provider_health.set_registry(provider_health.Registry(TMP / "h-main.json"))
routing.reset_caches()
pick, why = loki._smart_pick(routing.needs_for({"kind": "question", "difficulty": 1}))
check("no key: easy chat stays on the local model as before", pick == "local", (pick, why))
loki.MODELS["nvidia"].api_key = "nvapi-test-key"
loki._SMART_FAILED.clear()
for label, needs in (("chat", routing.needs_for({"kind": "question", "difficulty": 1})),
                     ("code", routing.needs_for({"kind": "code", "difficulty": 2})),
                     ("background jobs", routing.needs_for({"kind": "code"}, background=True)),
                     ("teams", routing.needs_for({"kind": "build", "route": "team", "difficulty": 3})),
                     ("a 150k-token document", routing.needs_for({"kind": "research"}, est_tokens=150_000))):
    pick, why = loki._smart_pick(needs)
    check("key set: %s -> nvidia (even ahead of local-first)" % label, pick == "nvidia" and "main driver" in why, (pick, why))
loki.model_name = "online"
check("online mode (improve_loki / evolve jobs) -> nvidia", loki.active_model_name() == "nvidia", loki.active_model_name())
check("improve_loki's model is 'online' (= the main driver) once the key is set", loki.improve_model() == "online", loki.improve_model())
loki.model_name = "smart"
pick, why = loki._smart_pick(routing.needs_for({"kind": "question"}, vision=True))
check("pictures: DeepSeek cannot see them, so routing goes past it", pick != "nvidia", (pick, why))
os.environ["LOKI_LOCAL_ONLY"] = "1"
pick, why = loki._smart_pick(routing.needs_for({"kind": "question"}, local_only=True))
check("Local only (General > Private) still keeps everything on this computer", pick == "local", (pick, why))
os.environ.pop("LOKI_LOCAL_ONLY")
provider_health.registry().record_failure("nvidia", "HTTP 401: Authentication failed", 401, key="nvapi-test-key")
pick, why = loki._smart_pick(routing.needs_for({"kind": "code"}))
check("a rejected key: it falls back (no dead end)", pick != "nvidia", (pick, why))
doc = routing.doctor(loki)
check("/models doctor names the main driver and why it is not driving", "Main driver: deepseek-ai/deepseek-v4.1-flash on nvidia"
      in doc["text"] and "not driving" in doc["text"], doc["text"][:500])
provider_health.set_registry(provider_health.Registry(TMP / "h-main2.json"))
routing.reset_caches()
doc = routing.doctor(loki)
check("/models doctor: 'drives chat, background jobs, teams and self-improvement', paced",
      "drives chat, background jobs, teams and self-improvement" in doc["text"] and "36 requests/min" in doc["text"]
      and doc["main_driver"]["ready"], doc["text"][:500])
check("/models doctor routes chat and background jobs to nvidia",
      all(r["provider"] == "nvidia" for r in doc["routes"] if r["id"] in ("chat", "background", "code", "hard")),
      [(r["id"], r["provider"]) for r in doc["routes"]])
loki._SMART_FAILED.add("nvidia")
pick, why = loki._smart_pick(routing.needs_for({"kind": "code"}))
check("used up in this session: the next provider takes over", pick != "nvidia", (pick, why))
loki._SMART_FAILED.clear()
loki.MAIN_DRIVER = ""
pick, why = loki._smart_pick(routing.needs_for({"kind": "question", "difficulty": 1}))
check("LOKI_MAIN_DRIVER=off: the plain smart order again (local first for easy chat)", pick == "local", (pick, why))
loki.MAIN_DRIVER = "nvidia"
import portal_api  # noqa: E402
check("Settings > General has the main-driver and thinking switches",
      "LOKI_MAIN_DRIVER" in portal_api.GENERAL and "LOKI_NVIDIA_THINKING" in portal_api.GENERAL)

# ================================================================= 3. the agent loop on a fake NVIDIA
section("3. the real agent loop against a fake NVIDIA NIM")
for pid in ("nvidia", "openrouter"):
    loki.MODELS[pid] = loki.ModelConfig(base_url=cloud.url(pid), api_key="nvapi-fake" if pid == "nvidia" else "key-or",
                                        model="deepseek-ai/deepseek-v4.1-flash" if pid == "nvidia" else "deepseek/deepseek-v4.1-flash")
saved_orders = (loki.SMART_ORDER, loki.ONLINE_ORDER, loki.provider_configured)
loki.SMART_ORDER = ("nvidia", "openrouter")
loki.ONLINE_ORDER = ("nvidia", "openrouter")
loki.provider_configured = lambda n: n in ("nvidia", "openrouter")
loki.PREFER = "cloud"
loki.model_name = "smart"
loki.loki_progress_callback = lambda event, text: PROGRESS.append((event, text))
PROGRESS: list = []
loki.RETRY_BASE_S = 0.05
loki.RETRY_MAX_S = 0.2
loki.RATE_LIMIT_WAIT_S = 0
(TMP / "ws" / "notes.txt").write_text("hello\n", encoding="utf-8")


def run_turn(prompt):
    loki.messages[:] = [{"role": "system", "content": "You are LOKI."}, {"role": "user", "content": prompt}]
    loki.ROUTE_TRACE.clear()
    loki._SMART_FAILED.clear()
    cloud.calls.clear()
    provider_health.set_registry(provider_health.Registry(TMP / ("h-%s.json" % time.time_ns())))
    routing.reset_caches()
    try:
        return asyncio.run(asyncio.wait_for(loki.agent_turn(), timeout=120))
    except Exception as exc:  # noqa: BLE001
        return "EXC %s: %s" % (type(exc).__name__, exc)


ratelimit.reset()
cloud.script = {"nvidia": [ok_tool("read_file", {"filename": "notes.txt"}, reasoning_content="The user wants the file; read it."),
                           ok_text("<think>It says hello.</think>DONE: the file says hello")]}
answer = run_turn("what is in notes.txt?")
check("a turn on DeepSeek/NVIDIA: tool call, then the answer", answer.strip() == "DONE: the file says hello", answer)
bodies = cloud.bodies("nvidia")
check("NIM gets DeepSeek's thinking switch in chat_template_kwargs (off for agent work)",
      bodies and all(b.get("chat_template_kwargs") == {"thinking": False} for b in bodies), [b.get("chat_template_kwargs") for b in bodies])
check("the tools went with it (native tool calling)", bodies and bodies[0].get("tools"), list(bodies[0].keys()) if bodies else bodies)
sent_history = json.dumps(bodies[-1]["messages"]) if bodies else ""
check("reasoning_content is NOT sent back in the history", "reasoning_content" not in sent_history and
      "The user wants the file" not in sent_history, sent_history[:400])
check("...nor is it kept in LOKI's conversation", "reasoning_content" not in json.dumps(loki.messages, default=str)
      and "It says hello." not in json.dumps(loki.messages, default=str), loki.messages[-3:])
check("the reasoning is shown as progress ('thinking')", any("thought:" in t and "read it" in t for _e, t in PROGRESS), PROGRESS[-5:])
check("<think> blocks are out of the answer", "<think>" not in answer and "It says hello." not in answer, answer)

os.environ["LOKI_NVIDIA_THINKING"] = "high"
loki.NVIDIA_THINKING = "high"
cloud.script = {"nvidia": [ok_text("DONE: thought hard")]}
run_turn("think about it")
check("LOKI_NVIDIA_THINKING=high turns thinking on with reasoning_effort",
      cloud.bodies("nvidia")[-1].get("chat_template_kwargs") == {"thinking": True, "reasoning_effort": "high"},
      cloud.bodies("nvidia")[-1].get("chat_template_kwargs"))
loki.NVIDIA_THINKING = "off"
os.environ.pop("LOKI_NVIDIA_THINKING")

# pacing: the fake NVIDIA answers 429 itself above 3 requests per second; LOKI paces at 2 per window (headroom, like
# 36 of NIM's 40/min) -> 4 quick requests would get a 429 without pacing; with it, none.
# The window is 3 s, not 1: a 1 s window is shorter than one request's round-trip when the PC is loaded (ship runs
# suites in parallel), so the requests never overlapped, no wait was needed, and the "it waited" check failed at
# random - which then blocked LOKI Studio's own pin check (studio.log 14:25: "9e1f7eb failed Studio's checks").
os.environ["LOKI_NVIDIA_RPM"] = "2"
ratelimit.WINDOW_S = 3.0
cloud.cap = {"nvidia": 3}
cloud.window = 1.0
cloud.times.clear()
ratelimit.reset()
cloud.script = {"nvidia": [ok_tool("read_file", {"filename": "notes.txt"}, cid="a"), ok_tool("read_file", {"filename": "notes.txt"}, cid="b"),
                           ok_tool("read_file", {"filename": "notes.txt"}, cid="c"), ok_text("DONE: read it three times")]}
PROGRESS.clear()
started = time.monotonic()
answer = run_turn("read notes.txt three times")
elapsed = time.monotonic() - started
check("4 requests, a 3-per-second server cap, paced at 2: all answered on NVIDIA, no 429, no failover",
      "three times" in answer and not cloud.bodies("openrouter") and not loki.ROUTE_TRACE, (answer, loki.ROUTE_TRACE))
check("...because LOKI queued them (it waited, and said so)", elapsed >= 0.8 and any("requests a minute" in t for _e, t in PROGRESS),
      (elapsed, [t for _e, t in PROGRESS][-6:], dict(loki.ROUTE_TRACE)))
cloud.cap = {}
ratelimit.WINDOW_S = 60.0
os.environ.pop("LOKI_NVIDIA_RPM")
ratelimit.reset()

cloud.script = {"nvidia": [ok_tool("read_file", {"filename": "notes.txt"}), err(429, "Too Many Requests", {"Retry-After": "30"})],
                "openrouter": [ok_text("DONE: finished on openrouter")]}
answer = run_turn("read notes.txt")
check("a 429 although LOKI paces itself (the key is busy elsewhere): fail over at once, the next provider finishes",
      "finished on openrouter" in answer and [n for n, _ in cloud.calls].count("nvidia") == 2,
      (answer, [n for n, _ in cloud.calls]))
check("provider health remembers NVIDIA as rate limited", provider_health.registry().get("nvidia").get("state") == "rate_limited",
      provider_health.registry().get("nvidia"))
check("...and the pacer holds NVIDIA's next requests back", ratelimit.wait_s("nvidia") > 5, ratelimit.wait_s("nvidia"))
check("...and the main driver steps aside until it recovers", not loki.main_driver_ready({})[0], loki.main_driver_ready({}))
got = cloud.bodies("openrouter")
check("the fallback got the whole conversation (the tool result too)", got and any(m.get("role") == "tool" for m in got[0]["messages"]))
ratelimit.reset()
split = loki.split_reasoning("plan the edit</think>The answer")
check("split_reasoning: a reply whose <think> was opened by the template", split == ("The answer", "plan the edit"), split)
(loki.SMART_ORDER, loki.ONLINE_ORDER, loki.provider_configured) = saved_orders
(loki.online, loki.local_ready, loki.PREFER, loki.model_name, _key) = saved

# ================================================================= 4. the LOKI MCP API
section("4. the LOKI MCP API (engine/loki_mcp.py) through the mcp client, in-process")
import loki_mcp  # noqa: E402
from mcp import Client  # noqa: E402

FAKE = TMP / "fake-loki"
(FAKE / "tools").mkdir(parents=True)
(FAKE / "app").mkdir()
(FAKE / "studio").mkdir()
(FAKE / "engine").mkdir()
(FAKE / "README.md").write_text("LOKI\nThe clear button.\n", encoding="utf-8")
(FAKE / "HANDOFF.md").write_text("# HANDOFF\n\n## Session 28\nold\n\n## Session 29 now\nthe newest work\n", encoding="utf-8")
(FAKE / "AGENTS.md").write_text("# AGENTS\nboth platforms\n", encoding="utf-8")
(FAKE / "ZIVA_TASKS.md").write_text("# ZIVA\nW1 do a thing\n", encoding="utf-8")
(FAKE / "app" / "loki_app.py").write_text("print('fake app')\n", encoding="utf-8")
(FAKE / "studio" / "studio_app.py").write_text("print('fake studio')\n", encoding="utf-8")
(FAKE / "engine" / "loki_mcp.py").write_text("# fake\n", encoding="utf-8")
(FAKE / "tools" / "ship.py").write_text('''import sys, pathlib
args = sys.argv[1:]
repo = pathlib.Path(args[args.index("--repo") + 1]) if "--repo" in args else pathlib.Path(".")
if "--check" in args:
    only = args[args.index("--only") + 1] if "--only" in args else "all"
    if (repo / "FAIL_TESTS").exists():
        print("  %s  0 passed, 1 failed" % only); sys.exit(1)
    print("  %s  3 passed, 0 failed" % only); sys.exit(0)
msg = args[args.index("-m") + 1]
(repo.parent / ("shipped-" + repo.name + ".txt")).write_text(msg)
print("1. tests\\n  pushed abc123def456 to master\\nShipped abc123def456.")
''', encoding="utf-8")
(FAKE / ".gitignore").write_text("harness_data/\n", encoding="utf-8")
git(FAKE, "init", "-q", "-b", "master")
git(FAKE, "add", "-A")
git(FAKE, "commit", "-qm", "c1")
C1 = git(FAKE, "rev-parse", "HEAD")
DATA = TMP / "data"
(DATA / "app").mkdir(parents=True, exist_ok=True)
(DATA / "jobs").mkdir(parents=True, exist_ok=True)
(DATA / "jobs" / "job42.log").write_text("step 1\nstep 2\nNVIDIA_API_KEY=nvapi-SECRETSECRET\n", encoding="utf-8")
(DATA / "app" / "engine.out").write_text("[loki-bridge] ready\nTraceback: boom in app.js\n", encoding="utf-8")

WT = loki_mcp.ensure_worktree(FAKE, DATA / "studio" / "worktrees" / "mcp", "studio/mcp")
check("a dev worktree of the checkout on its own branch", (WT / "README.md").is_file() and git(WT, "branch", "--show-current") == "studio/mcp")
(DATA / ".env").write_text("NVIDIA_API_KEY=nvapi-SECRETSECRET\n", encoding="utf-8")
(WT / "harness_data").mkdir(exist_ok=True)
(WT / "harness_data" / ".env").write_text("NVIDIA_API_KEY=nvapi-SECRETSECRET\n", encoding="utf-8")
(WT / ".env").write_text("X=1\n", encoding="utf-8")
SECRET = "studio-secret"
api = loki_mcp.LokiAPI(worktree=WT, repo=FAKE, data=DATA, approval_secret=SECRET, python=sys.executable,
                       bridge_url="http://127.0.0.1:9", token_file=DATA / "app" / "engine.token")


async def mcp_calls(api_obj, calls):
    out = {}
    async with Client(loki_mcp.build_server(api_obj)) as c:
        listed = await c.list_tools()
        out["__tools__"] = [t.name for t in listed.tools]
        for key, name, args in calls:
            r = await c.call_tool(name, args)
            out[key] = "\n".join(getattr(x, "text", "") for x in r.content)
    return out


res = asyncio.run(mcp_calls(api, [
    ("status", "loki_status", {}),
    ("read", "read_file", {"path": "README.md"}),
    ("range", "read_file", {"path": "README.md", "start_line": 2, "end_line": 2}),
    ("env", "read_file", {"path": ".env"}),
    ("hd", "read_file", {"path": "harness_data/.env"}),
    ("escape", "read_file", {"path": "../../.env"}),
    ("abs", "read_file", {"path": str(FAKE / "README.md")}),
    ("gitdir", "read_file", {"path": ".git/config"}),
    ("list", "list_files", {"path": "."}),
    ("search", "search_files", {"pattern": "clear button"}),
    ("search_secret", "search_files", {"pattern": "SECRETSECRET"}),
    ("edit", "edit_file", {"path": "README.md", "old_text": "The clear button.", "new_text": "The clear button (tooltip)."}),
    ("edit_twice", "edit_file", {"path": "README.md", "old_text": "nothing like this", "new_text": "x"}),
    ("write", "write_file", {"path": "docs/new.md", "content": "# new\n"}),
    ("write_env", "write_file", {"path": "harness_data/.env", "content": "X"}),
    ("status_git", "git_status", {}),
    ("diff", "git_diff", {}),
    ("log", "git_log", {"count": 3}),
    ("handoff", "read_doc", {"name": "HANDOFF.md", "section": "Session 29"}),
    ("ziva", "read_doc", {"name": "ZIVA_TASKS.md"}),
    ("tests", "run_tests", {"suite": "test_fake"}),
    ("joblog", "job_logs", {"id": "job42"}),
    ("englog", "engine_logs", {"which": "engine"}),
    ("down", "jobs_list", {}),
    ("restart_noapproval", "restart_engine", {}),
    ("restart_badcode", "restart_engine", {"confirm": "0000000000000000"}),
    ("ship_noapproval", "ship", {"message": "x"}),
    ("set_noapproval", "settings_set", {"key": "LOKI_AUTO_UPDATE", "value": "0"}),
]))
tools = res["__tools__"]
for name in ("loki_status", "models_doctor", "settings_get", "settings_set", "jobs_list", "job_start", "job_stop", "job_logs",
             "engine_logs", "world_summary", "memory_search", "tools_health", "creations_list", "restart_engine", "read_file",
             "list_files", "search_files", "edit_file", "write_file", "git_status", "git_diff", "git_log", "read_doc",
             "run_tests", "ship"):
    if name not in tools:
        check("MCP tool %s exists" % name, False, tools)
check("all %d tools are served over MCP" % len(loki_mcp.TOOL_ORDER), len(tools) == len(loki_mcp.TOOL_ORDER) == 31, tools)
check("loki_status works with LOKI down (running: false + the version on disk)", '"running": false' in res["status"]
      and "commit" in res["status"], res["status"][:300])
check("read_file reads the dev worktree", "The clear button." in res["read"])
check("read_file reads a line range", res["range"].strip() == "2: The clear button.", res["range"])
for key in ("env", "hd", "escape", "abs", "gitdir"):
    check("the jail refuses %s" % key, res[key].startswith("error:"), res[key])
check("list_files hides .env, harness_data and .git", ".env" not in res["list"] and "harness_data" not in res["list"]
      and ".git" not in res["list"].split() and "README.md" in res["list"], res["list"])
check("search_files finds code (path:line)", "README.md:2:" in res["search"], res["search"])
check("search_files never reads secrets", "SECRETSECRET" not in res["search_secret"], res["search_secret"])
check("edit_file edits in the worktree", res["edit"].startswith("edited") and "(tooltip)" in (WT / "README.md").read_text())
check("...never in the owner's checkout", "(tooltip)" not in (FAKE / "README.md").read_text())
check("edit_file wants old_text exactly once", "exactly once" in res["edit_twice"], res["edit_twice"])
check("write_file makes new files (folders too)", (WT / "docs" / "new.md").is_file())
check("write_file refuses harness_data/.env", res["write_env"].startswith("error") and
      (WT / "harness_data" / ".env").read_text().startswith("NVIDIA"), res["write_env"])
check("git_status shows the branch and the changes", "studio/mcp" in res["status_git"] and "README.md" in res["status_git"], res["status_git"])
check("git_diff shows the edit and the new file", "+The clear button (tooltip)." in res["diff"] and "docs/new.md" in res["diff"], res["diff"][:500])
check("git_log", "c1" in res["log"], res["log"])
check("read_doc jumps to a HANDOFF section", res["handoff"].startswith("## Session 29") and "newest" in res["handoff"], res["handoff"])
check("read_doc reads ZIVA_TASKS", "W1 do a thing" in res["ziva"])
check("run_tests runs tools/ship.py --check --only <suite> in the worktree", res["tests"].startswith("ALL PASSED") and "test_fake" in res["tests"], res["tests"])
check("job_logs reads a job's log from disk, keys redacted", "step 2" in res["joblog"] and "SECRETSECRET" not in res["joblog"], res["joblog"])
check("engine_logs reads LOKI's log from disk (LOKI down)", "boom in app.js" in res["englog"], res["englog"])
check("engine tools say plainly that LOKI is not running", "LOKI is not running" in res["down"], res["down"])
for key in ("restart_noapproval", "restart_badcode", "ship_noapproval", "set_noapproval"):
    check("risky without the owner's code is refused (%s)" % key, "needs the owner's approval" in res[key] and
          "Nothing was done" in res[key], res[key])
check("the refusal never reveals the approval code", loki_mcp.approval_code(SECRET, "restart_engine", {}) not in res["restart_noapproval"])
check("nothing was shipped", not list(TMP.glob("**/shipped-mcp.txt")))


# ---------------------------------------------------------------- a fake RUNNING engine
class FakeBridge:
    def __init__(self, token):
        self.token = token
        self.calls = []
        bridge = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def _reply(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method):
                if self.headers.get("Authorization") != "Bearer " + bridge.token:
                    return self._reply(401, {"ok": False, "error": "Invalid local bridge token."})
                body = {}
                if method == "POST":
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)) or b"{}")
                path = self.path.split("?")[0]
                bridge.calls.append((method, self.path, body))
                table = {
                    ("GET", "/health"): {"ok": True, "mode": "smart", "provider": "nvidia", "model": "deepseek-ai/deepseek-v4.1-flash",
                                         "update": {"behind": 0}},
                    ("GET", "/models/doctor"): {"ok": True, "text": "Mode: smart.\nMain driver: deepseek-ai/deepseek-v4.1-flash on nvidia"},
                    ("GET", "/settings/general"): {"ok": True, "settings": {"LOKI_AUTO_UPDATE": {"kind": "bool"},
                                                                            "LOKI_TELEGRAM_TOKEN": {"kind": "secret"}},
                                                   "values": {"LOKI_AUTO_UPDATE": "1", "LOKI_TELEGRAM_TOKEN": ""}},
                    ("POST", "/settings/general"): {"ok": True},
                    ("GET", "/jobs"): {"ok": True, "jobs": [{"id": "j1", "title": "Improve LOKI", "status": "working", "model": "online"}]},
                    ("POST", "/jobs"): {"ok": True, "id": "j2"},
                    ("POST", "/jobs/cancel"): {"ok": True},
                    ("GET", "/memory/core"): {"ok": True, "items": [{"kind": "fact", "text": "the owner likes icons", "score": 3.2}]},
                    ("GET", "/tools/health"): {"ok": True, "tools": [{"name": "browse_page", "ok": True}]},
                    ("GET", "/creations"): {"ok": True, "creations": [{"title": "the fox", "kind": "image"}]},
                    ("GET", "/world"): {"ok": True, "players": [], "agents": []},
                    ("POST", "/engine/restart"): {"ok": True, "note": "the engine restarts in a moment"},
                }
                payload = table.get((method, path))
                return self._reply(200 if payload else 404, payload or {"ok": False, "error": "Unknown endpoint."})

            def do_GET(self):  # noqa: N802
                self._route("GET")

            def do_POST(self):  # noqa: N802
                self._route("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


TOKEN_FILE = TMP / "up" / "engine.token"
TOKEN_FILE.parent.mkdir(parents=True)
TOKEN_FILE.write_text("bridge-token-123", encoding="utf-8")
bridge = FakeBridge("bridge-token-123")
up_api = loki_mcp.LokiAPI(worktree=WT, repo=FAKE, data=DATA, approval_secret=SECRET, bridge_url=bridge.url, token_file=TOKEN_FILE)
code = lambda tool, args: loki_mcp.approval_code(SECRET, tool, args)  # noqa: E731
res = asyncio.run(mcp_calls(up_api, [
    ("status", "loki_status", {}),
    ("doctor", "models_doctor", {}),
    ("sget", "settings_get", {}),
    ("sset", "settings_set", {"key": "LOKI_AUTO_UPDATE", "value": "0", "confirm": code("settings_set", {"key": "LOKI_AUTO_UPDATE", "value": "0"})}),
    ("sset_secret", "settings_set", {"key": "LOKI_TELEGRAM_TOKEN", "value": "x", "confirm": code("settings_set", {"key": "LOKI_TELEGRAM_TOKEN", "value": "x"})}),
    ("jobs", "jobs_list", {}),
    ("jstart", "job_start", {"prompt": "write hello.txt", "confirm": code("job_start", {"prompt": "write hello.txt", "title": "", "model": ""})}),
    ("jstop", "job_stop", {"id": "j1", "confirm": code("job_stop", {"id": "j1"})}),
    ("mem", "memory_search", {"query": "icons"}),
    ("tools", "tools_health", {}),
    ("made", "creations_list", {}),
    ("world", "world_summary", {}),
    ("restart_other_args", "restart_engine", {"confirm": code("restart_engine", {"x": 1})}),
    ("restart", "restart_engine", {"confirm": code("restart_engine", {})}),
]))
check("LOKI up: loki_status is the engine's health (running, provider)", '"running": true' in res["status"] and "nvidia" in res["status"], res["status"][:300])
check("models_doctor is the engine's doctor text", "Main driver" in res["doctor"], res["doctor"])
check("settings_get lists settings and never a secret", "LOKI_AUTO_UPDATE" in res["sget"] and "LOKI_TELEGRAM_TOKEN" not in res["sget"], res["sget"])
check("settings_set with the owner's code changes a General setting",
      ("POST", "/settings/general", {"values": {"LOKI_AUTO_UPDATE": "0"}}) in bridge.calls, bridge.calls[-3:])
check("settings_set refuses a secret even with a code", res["sset_secret"].startswith("refused"), res["sset_secret"])
check("jobs_list lists the engine's jobs", "Improve LOKI" in res["jobs"], res["jobs"])
check("job_start (approved) posts a job through the engine's policy", any(c[1] == "/jobs" and c[0] == "POST" for c in bridge.calls)
      and '"id": "j2"' in res["jstart"], res["jstart"])
check("job_stop (approved) cancels it", ("POST", "/jobs/cancel", {"id": "j1"}) in bridge.calls, res["jstop"])
check("memory_search, tools_health, creations_list, world_summary answer",
      "icons" in res["mem"] and "browse_page" in res["tools"] and "the fox" in res["made"] and "players" in res["world"],
      (res["mem"], res["tools"][:80], res["made"][:80]))
check("an approval code is for THAT call only (other args -> refused)", "needs the owner's approval" in res["restart_other_args"],
      res["restart_other_args"])
check("restart_engine (approved) asks the engine to restart", ("POST", "/engine/restart", {}) in bridge.calls and "restarts" in res["restart"],
      res["restart"])
TOKEN_FILE.write_text("wrong-token", encoding="utf-8")
check("a wrong bridge token is not 'running'", not up_api.up())
TOKEN_FILE.write_text("bridge-token-123", encoding="utf-8")

# the engine's own small doors (engine/studio_api.py)
import studio_api  # noqa: E402
restarted = threading.Event()
fake_state = type("S", (), {"agent": type("A", (), {"DATA_DIR": str(DATA)})(), "restart_engine": staticmethod(restarted.set)})()
code_, out = studio_api.route(fake_state, "POST", "/engine/restart", {})
check("POST /engine/restart answers first, then restarts the engine", code_ == 200 and restarted.wait(3), out)
code_, out = studio_api.route(fake_state, "GET", "/studio", None)
check("GET /studio: not running here, and how to start it by hand", code_ == 200 and out["running"] is False and "studio" in out["how"].lower(), out)
check("the bridge routes them", "studio_api.handles(\"POST\", route)" in (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8"))

# stdio: the real server process (what Studio, Claude Code, Codex and Ziva start)
async def stdio_list():
    from mcp import StdioServerParameters  # pylint: disable=import-outside-toplevel
    env = dict(os.environ, LOKI_DATA=str(DATA))
    params = StdioServerParameters(command=sys.executable, args=[str(REPO / "engine" / "loki_mcp.py"), "--worktree", str(WT),
                                                                 "--repo", str(FAKE)], env=env)
    async with Client(params) as c:
        listed = await c.list_tools()
        r = await c.call_tool("read_file", {"path": "README.md"})
        return [t.name for t in listed.tools], r.content[0].text


try:
    names, text = asyncio.run(asyncio.wait_for(stdio_list(), 60))
    check("python engine/loki_mcp.py over stdio: 31 tools, and they work", len(names) == 31 and "(tooltip)" in text, (len(names), text[:80]))
except Exception as exc:  # noqa: BLE001
    check("python engine/loki_mcp.py over stdio", False, exc)

try:
    import uvicorn  # noqa: F401
    port = 18000 + os.getpid() % 2000
    proc = subprocess.Popen([sys.executable, str(REPO / "engine" / "loki_mcp.py"), "--http", "--port", str(port), "--worktree", str(WT),
                             "--repo", str(FAKE)], env=dict(os.environ, LOKI_DATA=str(DATA), LOKI_BRIDGE_TOKEN_FILE=str(TOKEN_FILE)),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    statuses = []
    for _ in range(60):
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/mcp" % port, data=b"{}", method="POST"), timeout=1)
            statuses.append(200)
        except urllib.error.HTTPError as exc:
            statuses.append(exc.code)
            break
        except OSError:
            time.sleep(0.25)
    good = None
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/mcp" % port, method="POST",
                                     data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                                         "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}).encode(),
                                     headers={"Authorization": "Bearer bridge-token-123", "Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            good = resp.status
    except urllib.error.HTTPError as exc:
        good = exc.code
    except OSError as exc:
        good = str(exc)
    proc.terminate()
    proc.wait(10)
    check("streamable HTTP on loopback: no bridge token -> 401", statuses[-1:] == [401], statuses)
    check("...with the bridge token it is an MCP endpoint", good not in (401, None) and not isinstance(good, str), good)
except ImportError:
    check("streamable HTTP (uvicorn missing: skipped)", True)

# ================================================================= 5. LOKI Studio, engine stopped
section("5. LOKI Studio with the engine STOPPED: a session from prompt to ship")
os.environ["LOKI_BRIDGE_URL"] = "http://127.0.0.1:9"     # nothing answers: LOKI is down
import studio_models  # noqa: E402
import studio_core  # noqa: E402

DRIVER = studio_models.Provider("nvidia", "DeepSeek V4.1 Flash on NVIDIA NIM", cloud.url("studio-nvidia"), studio_models.DRIVER_MODEL,
                                "NVIDIA_API_KEY", "nvapi-fake", extra=studio_models.thinking_fields())
FALLBACK = studio_models.Provider("openrouter", "DeepSeek on OpenRouter", cloud.url("studio-or"), "deepseek/deepseek-v4.1-flash",
                                  "OPENROUTER_API_KEY", "or-fake")
CHAIN = [DRIVER, FALLBACK]


def scripted_chat(messages, tools, _chain, say, sleep, stop=None):
    return studio_models.chat(messages, tools, CHAIN, say, sleep, stop=stop)


holder: dict = {}


def factory(session):
    return Client(loki_mcp.build_server(loki_mcp.LokiAPI(worktree=session.meta["worktree"], repo=FAKE, data=DATA,
                                                         approval_secret=holder["studio"].secret, python=sys.executable,
                                                         bridge_url="http://127.0.0.1:9", token_file=DATA / "app" / "engine.token")))


studio = studio_core.Studio(repo=FAKE, data=DATA, mcp_factory=factory, chat=scripted_chat, python=sys.executable)
holder["studio"] = studio
check("Studio says LOKI is not running (and how to still see it)", "NOT running" in studio.loki_line(), studio.loki_line())

cloud.calls.clear()
cloud.script = {"studio-nvidia": [
    err(429, "Too Many Requests", {"Retry-After": "1"}),
    ok_tool("read_file", {"path": "README.md"}, reasoning_content="Read the README first."),
    ok_tool("edit_file", {"path": "README.md", "old_text": "The clear button.",
                          "new_text": "The clear button (tooltip: removes finished jobs)."}, content="<think>now edit</think>"),
    ok_tool("run_tests", {"suite": "test_fake"}),
    ok_tool("restart_engine", {}),
    ok_tool("ship", {"message": "ship it myself"}),
    ok_tool("write_file", {"path": "harness_data/.env", "content": "NVIDIA_API_KEY=stolen"}),
    ok_text("Done: the Clear finished button has a tooltip; test_fake passes. Suggested message: 'Tooltip on Clear finished'."),
]}


def approve_when_asked(sid, yes, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        s = studio.get(sid)
        with s.lock:
            open_ = [e for e in s.events if e["type"] == "approval"]
        if open_ and s.pending:
            studio.approve(sid, open_[-1]["approval"], yes)
            return True
        time.sleep(0.05)
    return False


s1 = studio.new("Add a tooltip to the Clear finished button")
check("a session gets its own worktree and branch", Path(s1.meta["worktree"]).is_dir() and s1.meta["branch"].startswith("studio/")
      and git(Path(s1.meta["worktree"]), "branch", "--show-current") == s1.meta["branch"], s1.meta)
asked = approve_when_asked(s1.id, True)
studio.wait(s1.id, 60)
ev = s1.events
types_ = [e["type"] for e in ev]
check("the owner was asked before restart_engine (and said yes)", asked and "approval" in types_ and "approved" in types_, types_)
wt1 = Path(s1.meta["worktree"])
check("the agent made a REAL edit in its worktree", "(tooltip: removes finished jobs)" in (wt1 / "README.md").read_text())
check("...and the owner's checkout is untouched", "tooltip" not in (FAKE / "README.md").read_text())
check("it ran the (fake) check: ALL PASSED", any(e["type"] == "result" and e.get("tool") == "run_tests" and e["text"].startswith("ALL PASSED") for e in ev))
check("the 429 waited its Retry-After and went on (no failover needed)", not cloud.bodies("studio-or")
      and any(e["type"] == "progress" and "429" in e["text"] for e in ev), [e["text"] for e in ev if e["type"] == "progress"])
check("reasoning shows as 'thinking' events", any(e["type"] == "thinking" and "README first" in e["text"] for e in ev)
      and any(e["type"] == "thinking" and "now edit" in e["text"] for e in ev))
check("tool calls stream as events, with the diff after the edit", any(e["type"] == "tool" and e["text"].startswith("edit_file") for e in ev)
      and any(e["type"] == "diff" and "+The clear button (tooltip" in e["text"] for e in ev))
restart_result = [e["text"] for e in ev if e["type"] == "result" and e.get("tool") == "restart_engine"]
check("the approved restart went through MCP with Studio's code (LOKI is down, so it says so)",
      restart_result and "LOKI is not running" in restart_result[0], restart_result)
ship_res = [m for m in s1.messages if m.get("role") == "tool" and "only the owner ships" in str(m.get("content"))]
check("the agent cannot ship (the owner's button only)", ship_res and not list(TMP.glob("shipped-*.txt")), ship_res)
env_res = [e["text"] for e in ev if e["type"] == "result" and e.get("tool") == "write_file"]
check("the agent cannot touch harness_data/.env", env_res and env_res[0].startswith("error") and not (wt1 / "harness_data").exists(), env_res)
check("the agent's last word is in the thread", ev and any(e["type"] == "assistant" and "Suggested message" in e["text"] for e in ev))
check("the session waits for the owner (idle) on DeepSeek/NVIDIA", s1.meta["status"] == "idle" and s1.meta.get("provider") == "nvidia", s1.meta.get("status"))
bodies = cloud.bodies("studio-nvidia")
check("Studio's requests carry the tools (as functions, without 'ship' and without 'confirm')",
      bodies and bodies[1].get("tools") and all(t["function"]["name"] != "ship" for t in bodies[1]["tools"])
      and "confirm" not in json.dumps(bodies[1]["tools"]), [t["function"]["name"] for t in bodies[1]["tools"]][:30] if bodies else bodies)
check("Studio sends DeepSeek's thinking switch to NIM", all(b.get("chat_template_kwargs") == {"thinking": False} for b in bodies))
check("no reasoning is ever re-sent", all("reasoning_content" not in json.dumps(b["messages"]) and "README first" not in json.dumps(b["messages"])
                                          for b in bodies))
check("the model saw its tool results (the conversation goes on)", any(m.get("role") == "tool" and "The clear button." in m.get("content", "")
                                                                         for m in bodies[2]["messages"]))

# the owner follows up in the SAME session
cloud.script = {"studio-nvidia": [
    ok_tool("edit_file", {"path": "HANDOFF.md", "old_text": "the newest work", "new_text": "the newest work: tooltip on Clear finished"}),
    ok_text("Done: HANDOFF says so too."),
]}
before = len(s1.messages)
studio.send(s1.id, "also note it in HANDOFF.md")
studio.wait(s1.id, 60)
first_follow = cloud.bodies("studio-nvidia")[-2]
check("a follow-up continues the same session: same worktree, the earlier conversation is sent",
      any(m.get("content") == "Add a tooltip to the Clear finished button" for m in first_follow["messages"])
      and "tooltip on Clear finished" in (wt1 / "HANDOFF.md").read_text() and len(s1.messages) > before + 2, len(s1.messages))
diff = studio.diff(s1.id)
check("the diff shows both changes", "README.md" in diff and "HANDOFF.md" in diff, diff[:300])
check("the owner's Tests button runs the check in the worktree", studio.check(s1.id, "test_fake").startswith("ALL PASSED")
      and s1.meta["last_check"]["passed"])

out = studio.ship(s1.id, "Tooltip on Clear finished")
check("Ship refuses without the owner's approval", out.startswith("NOT shipped") and not list(TMP.glob("shipped-*.txt")), out)
(wt1 / "FAIL_TESTS").write_text("x")
studio.ship_runner = lambda tree, msg: loki_mcp.run_ship(tree, msg, sys.executable, DATA) if not (tree / "FAIL_TESTS").exists() \
    else "NOT shipped:\nTests failed - nothing was committed or pushed."
out = studio.ship(s1.id, "Tooltip on Clear finished", approved=True)
check("failing tests: not shipped, the session stays open to fix it", out.startswith("NOT shipped") and s1.meta["status"] == "idle", out)
(wt1 / "FAIL_TESTS").unlink()
out = studio.ship(s1.id, "Tooltip on Clear finished (checked: test_fake)", approved=True)
shipped = list(TMP.glob("**/shipped-%s.txt" % wt1.name))
check("the owner's Ship it runs tools/ship.py from the session's worktree", out.startswith("shipped") and shipped
      and shipped[0].read_text() == "Tooltip on Clear finished (checked: test_fake)", out)
check("the session is shipped (final)", s1.meta["status"] == "shipped")
try:
    studio.send(s1.id, "more?")
    check("a shipped session takes no more messages", False)
except ValueError:
    check("a shipped session takes no more messages", True)

# stop + discard
cloud.script = {"studio-nvidia": [ok_tool("restart_engine", {}), ok_text("never reached")]}
s2 = studio.new("Restart LOKI and look at the logs")
end = time.time() + 20
while time.time() < end and not s2.pending:
    time.sleep(0.05)
check("a risky call waits for the owner (status waiting)", bool(s2.pending) and s2.meta["status"] == "waiting", s2.meta["status"])
studio.stop(s2.id)
studio.wait(s2.id, 20)
check("Stop ends the wait as a no, and the session stops", s2.meta["status"] == "stopped" and any(e["type"] == "denied" for e in s2.events),
      (s2.meta["status"], [e["type"] for e in s2.events][-5:]))
wt2 = Path(s2.meta["worktree"])
studio.discard(s2.id)
check("Discard removes the worktree and its branch", not wt2.exists() and s2.meta["branch"] not in git(FAKE, "branch", "--list"),
      git(FAKE, "branch", "--list"))
studio2 = studio_core.Studio(repo=FAKE, data=DATA, mcp_factory=factory, chat=scripted_chat, python=sys.executable)
listed = {s["id"]: s for s in studio2.list()}
check("history is kept: a restarted Studio lists both sessions with their events",
      s1.id in listed and s2.id in listed and listed[s1.id]["status"] == "shipped" and len(studio2.get(s1.id).events) == len(s1.events),
      listed)

# no key at all
saved_env = {k: os.environ.pop(k) for k in list(os.environ) if k.endswith("_API_KEY")}
st = studio_models.driver_status(env={"LOKI_STUDIO_LOCAL_MODEL": "x"})
check("no NVIDIA key: Studio says exactly how to get one", "build.nvidia.com/settings/api-keys" in st["how"] and "nvapi-" in st["how"], st)
st = studio_models.driver_status(env={"GEMINI_API_KEY": "g"})
check("...and uses the next best free model meanwhile", st["provider"] == "gemini" and "next best free model" in st["text"], st)
st = studio_models.driver_status(env={"NVIDIA_API_KEY": "nvapi-x"})
check("with the key: 'Driving: DeepSeek V4.1 Flash on NVIDIA NIM'", st["provider"] == "nvidia" and "Driving" in st["text"] and not st["how"], st)
check("Studio's order: NVIDIA first, then OpenRouter's DeepSeek, then other free ones",
      [p.id for p in studio_models.providers({})][:3] == ["nvidia", "openrouter", "opencode-zen"])
try:
    studio_models.chat([{"role": "user", "content": "hi"}], None, [])
    check("no model at all: a clear error", False)
except studio_models.ModelError as exc:
    check("no model at all: a clear error that says how to get the free key", "build.nvidia.com" in str(exc), exc)
os.environ.update(saved_env)
cloud.script = {"studio-nvidia": [err(401, "Authentication failed")], "studio-or": [ok_text("fallback answered")]}
prov, msg, _r = studio_models.chat([{"role": "user", "content": "hi"}], None, CHAIN, sleep=lambda s: None)
check("Studio fails over from a rejected NVIDIA key to the next model", prov.id == "openrouter" and msg["content"] == "fallback answered", (prov.id, msg))

# ================================================================= 6. Studio's hands on LOKI
section("6. Studio's hands on LOKI: logs, start, rollback, the pinned copy")
import studio_control  # noqa: E402
import studio_pin  # noqa: E402
import updater  # noqa: E402

st = studio_control.status(FAKE, DATA)
check("status with LOKI down: not running, its version from git", st["running"] is False and st["commit"], st)
check("logs straight from disk", "boom in app.js" in studio_control.logs("engine", 50, DATA))
started_cmd = []


class FakePopen:
    def __init__(self, argv, **kw):
        started_cmd.append((argv, kw))


out = studio_control.start(FAKE, DATA, popen=FakePopen)
check("start: the LOKI app from the owner's checkout (not Studio's pinned copy), detached",
      out["ok"] and started_cmd and started_cmd[0][0][-1] == str(FAKE / "app" / "loki_app.py") and started_cmd[0][1]["cwd"] == str(FAKE)
      and ("start_new_session" in started_cmd[0][1] or "creationflags" in started_cmd[0][1]), started_cmd)
started_cmd.clear()
out = studio_control.restart(FAKE, DATA, popen=FakePopen)
check("restart with LOKI down = start", out["ok"] and started_cmd, out)
os.environ["LOKI_BRIDGE_URL"] = bridge.url
(DATA / "app" / "engine.token").write_text("bridge-token-123", encoding="utf-8")
bridge.calls.clear()
st = studio_control.status(FAKE, DATA)
check("status with LOKI up: running, its model", st["running"] and st["model"] == "deepseek-ai/deepseek-v4.1-flash", st)
out = studio_control.restart(FAKE, DATA, popen=FakePopen)
check("restart with LOKI up: through the engine (POST /engine/restart)", out["ok"] and ("POST", "/engine/restart", {}) in bridge.calls, out)
(DATA / "app" / "engine.token").unlink()
os.environ["LOKI_BRIDGE_URL"] = "http://127.0.0.1:9"

RB = TMP / "rollback-repo"
RB.mkdir()
(RB / "f.txt").write_text("1\n")
git(RB, "init", "-q", "-b", "master")
git(RB, "add", "-A")
git(RB, "commit", "-qm", "good")
good = git(RB, "rev-parse", "HEAD")
(RB / "f.txt").write_text("2\n")
git(RB, "commit", "-qam", "bad")
bad = git(RB, "rev-parse", "HEAD")
(RB / ".git" / "loki_update_health.json").write_text(json.dumps({"last_good": good, "pending": bad}))
out = studio_control.rollback(RB)
check("rollback of a fresh update (on trial): the updater's own rollback", out["ok"] and git(RB, "rev-parse", "HEAD") == good
      and bad in updater.health(RB).get("skip", []), out)
(RB / "f.txt").write_text("3\n")
git(RB, "commit", "-qam", "bad again, already marked good-less")
bad2 = git(RB, "rev-parse", "HEAD")
(RB / "local.txt").write_text("my own edit\n")
rec = updater.health(RB)
rec.update(pending="", last_good=good)
(RB / ".git" / "loki_update_health.json").write_text(json.dumps(rec))
out = studio_control.rollback(RB)
check("rollback when the version is not on trial: by hand to the last good one", out["ok"] and git(RB, "rev-parse", "HEAD") == good, out)
check("...the bad commit is skipped from now on, with the reason", bad2 in updater.health(RB).get("skip", [])
      and "Studio" in str(updater.health(RB).get("skip_reasons")), updater.health(RB))
check("...local edits are kept", (RB / "local.txt").read_text() == "my own edit\n")
check("...and it is in the update history", any(h.get("event") == "rolled back" for h in updater.health(RB).get("history", [])))
out = studio_control.rollback(RB)
check("nothing to roll back: says so", not out["ok"] and "already" in out["error"], out)

# the pinned copy
PIN_DATA = TMP / "pin-data"
(FAKE / ".git" / "loki_update_health.json").write_text(json.dumps({"last_good": C1}))
res = studio_pin.ensure(FAKE, PIN_DATA)
check("the pinned copy is made at the last good commit", res["ok"] and studio_pin.pinned_commit(PIN_DATA) == C1, res)
check("...and has Studio + the engine modules in it", studio_pin.usable(PIN_DATA) is not None)
(FAKE / "studio" / "studio_app.py").write_text("print('fake studio v2')\n")
git(FAKE, "commit", "-qam", "c2")
C2 = git(FAKE, "rev-parse", "HEAD")
(FAKE / ".git" / "loki_update_health.json").write_text(json.dumps({"last_good": C2}))
res = studio_pin.refresh(FAKE, PIN_DATA, checker=lambda r, c: (False, "test_studio failed"))
check("a newer good commit that fails Studio's checks is NOT pinned", not res["ok"] and studio_pin.pinned_commit(PIN_DATA) == C1, res)
res = studio_pin.refresh(FAKE, PIN_DATA, checker=lambda r, c: (True, "passed"))
check("...and not tried again", "refused before" in res["note"] and studio_pin.pinned_commit(PIN_DATA) == C1, res)
(FAKE / "README.md").write_text("LOKI v3\n")
git(FAKE, "commit", "-qam", "c3")
C3 = git(FAKE, "rev-parse", "HEAD")
(FAKE / ".git" / "loki_update_health.json").write_text(json.dumps({"last_good": C3}))
res = studio_pin.refresh(FAKE, PIN_DATA, checker=lambda r, c: (True, "passed"))
check("one that passes is pinned - on Studio's NEXT start, never under the running one",
      res["ok"] and res.get("next") == C3 and studio_pin.pinned_commit(PIN_DATA) == C1, res)
res = studio_pin.ensure(FAKE, PIN_DATA)
check("the next start moves the pin", studio_pin.pinned_commit(PIN_DATA) == C3, res)
(FAKE / ".git" / "loki_update_health.json").write_text(json.dumps({"last_good": C3, "pending": "deadbeef"}))
check("a version on trial (not yet good) is never the pin's candidate", studio_pin.candidate(FAKE) == C3)

proc = subprocess.run([sys.executable, str(REPO / "studio" / "studio_app.py"), "--self-test"], capture_output=True, text=True,
                      timeout=120, env=dict(os.environ, LOKI_DATA=str(TMP / "selftest")))
check("studio_app.py --self-test (what the pin runs before moving)", proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr)
src = (REPO / "studio" / "studio_app.py").read_text(encoding="utf-8")
check("Studio hands over to its pinned copy, and falls back to the checkout if that copy will not start",
      "hand_over_to_pin" in src and "running from the checkout instead" in src)

# ================================================================= 7. the server, the window, LOKI's button
section("7. Studio's server and window; LOKI's Studio button")
import studio_server  # noqa: E402

srv = studio_server.StudioServer(studio2, port=0)
srv.start()
base = "http://127.0.0.1:%d" % srv.port


def http(method, path, body=None, token=True, host=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + srv.token
    if host:
        headers["Host"] = host
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


code_, headers, body = http("GET", "/", token=False)
check("the window loads, with a strict CSP (script-src 'self')", code_ == 200 and "script-src 'self'" in headers.get("Content-Security-Policy", "")
      and b"studio.js" in body, headers.get("Content-Security-Policy"))
check("every file index.html loads exists", all((REPO / "studio" / "ui" / f).is_file() for f in ("studio.js", "studio.css")))
check("the API needs the token", http("GET", "/api/state", token=False)[0] == 401)
check("a foreign Host is refused (DNS rebinding)", http("GET", "/api/state", host="evil.example:%d" % srv.port)[0] == 403)
code_, _h, body = http("GET", "/api/state")
state = json.loads(body)
check("/api/state: sessions, the driver, LOKI's status", code_ == 200 and len(state["sessions"]) >= 2 and "driver" in state
      and state["loki"]["running"] is False, state.get("loki"))
code_, _h, body = http("GET", "/api/session?id=%s&after=0" % s1.id)
check("/api/session streams the events", code_ == 200 and len(json.loads(body)["events"]) == len(s1.events))
check("Ship over HTTP needs confirm:true from the owner's dialog", http("POST", "/api/session/ship", {"id": s1.id})[0] == 400)
check("rollback over HTTP needs confirm:true", http("POST", "/api/loki/rollback", {})[0] == 400)
check("an unknown session is a 404", http("GET", "/api/session?id=nope")[0] == 404)
running = json.loads((DATA / "studio" / "running.json").read_text())
check("Studio writes where it is (LOKI's button finds it)", running["port"] == srv.port and (DATA / "studio" / "studio.token").read_text() == srv.token)
up = studio_api.running(DATA)
check("the engine sees the running Studio (GET /api/ping with its token)", up.get("port") == srv.port, up)

shots = os.getenv("LOKI_SUITE_SCREENS", "")
try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None
chromium = next((p for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if p and os.path.exists(p)), "")


async def look():
    async with async_playwright() as pw:
        launch = {"headless": True}
        exe = next((str(p) for p in Path(chromium).glob("chrome-linux*/chrome")), "") if chromium and Path(chromium).is_dir() else ""
        if exe:
            launch["executable_path"] = exe
        browser = await pw.chromium.launch(**launch)
        page = await browser.new_page(viewport={"width": 1360, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await page.goto(srv.url + "&session=" + s1.id)
        await page.wait_for_selector(".ev.diff, .diff", timeout=15000)
        await page.wait_for_timeout(600)
        counts = await page.evaluate("""() => ({sessions: document.querySelectorAll('.sess').length,
            thinking: document.querySelectorAll('.ev.thinking').length, tools: document.querySelectorAll('.ev.tool').length,
            approvals: document.querySelectorAll('.ev.approval').length, icons: document.querySelectorAll('button[data-icon] svg').length,
            driver: document.getElementById('driver').textContent})""")
        await page.hover("#act-ship")
        await page.wait_for_timeout(200)
        tip = await page.evaluate("() => document.querySelector('.tip') && document.querySelector('.tip').textContent")
        await page.evaluate("() => { document.getElementById('thread').scrollTop = 0; }")
        await page.wait_for_timeout(150)
        path = Path(shots) / "studio.png" if shots else TMP / "studio.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path))

        # LOKI's own window: only the Studio icon, with its tooltip, posting /studio/open
        ui = REPO / "app" / "ui"
        posts = []

        async def route(r):
            p = r.request.url.split("8899", 1)[1].split("?")[0].split("#")[0]
            if p == "/":
                return await r.fulfill(path=str(ui / "index.html"))
            if p.startswith("/ui/") and (ui / p[4:]).is_file():
                return await r.fulfill(path=str(ui / p[4:]))
            if r.request.method == "POST":
                posts.append(p)
            if p == "/studio/open":
                return await r.fulfill(json={"ok": True, "started": True, "note": "LOKI Studio is starting in its own window."})
            return await r.fulfill(json={"ok": True})

        page2 = await browser.new_page(viewport={"width": 1240, "height": 820})
        await page2.route("http://127.0.0.1:8899/**", route)
        await page2.goto("http://127.0.0.1:8899/#token=t")
        await page2.wait_for_selector("#open-studio svg", timeout=15000, state="attached")   # it lives in the More menu (ui_tidy.js)
        if await page2.is_visible("#tidy-more") and not await page2.is_visible("#open-studio"):
            await page2.click("#tidy-more")                # open the More menu first
            await page2.wait_for_timeout(200)
        await page2.hover("#open-studio")
        await page2.wait_for_timeout(400)
        loki_tip = await page2.evaluate("() => { const t = document.querySelector('.icon-tip'); return t && !t.hidden ? t.textContent : ''; }")
        side = Path(shots) / "studio-button.png" if shots else TMP / "studio-button.png"
        await page2.screenshot(path=str(side), clip={"x": 0, "y": 640, "width": 560, "height": 180})
        await page2.evaluate("document.getElementById('open-studio').click()")
        await page2.wait_for_timeout(400)
        await browser.close()
        return errors, counts, tip, path, loki_tip, posts


if async_playwright is not None and chromium:
    try:
        errors, counts, tip, shot, loki_tip, posts = asyncio.run(look())
        check("LOKI's window: the Studio icon's tooltip says 'LOKI Studio - work on LOKI itself with DeepSeek V4.1'",
              "LOKI Studio" in loki_tip and "Work on LOKI itself with DeepSeek V4.1" in loki_tip, loki_tip)
        check("...and a click opens the Studio tab, which asks the engine for Studio (POST /studio/embed)", "/studio/embed" in posts, posts)
        check("Studio's window in headless Chromium: no script error", not errors, errors)
        check("...it shows the sessions, thinking, tool calls, the approval and icons",
              counts["sessions"] >= 2 and counts["thinking"] >= 1 and counts["tools"] >= 3 and counts["approvals"] >= 1 and counts["icons"] >= 8, counts)
        check("...hovering an icon shows its name and what it does", tip and "Ship it" in tip and "health-gated" in tip, tip)
        print("  (screenshot: %s)" % shot)
    except Exception as exc:  # noqa: BLE001
        check("Studio's window in headless Chromium", False, exc)
else:
    print("  SKIP the window check: no Playwright/Chromium here")
srv.stop()

index = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
link = (REPO / "app" / "ui" / "studio_link.js").read_text(encoding="utf-8")
icons = (REPO / "app" / "ui" / "icons.js").read_text(encoding="utf-8")
check("LOKI keeps only a small Studio button (studio_link.js, loaded by index.html)", '<script src="/ui/studio_link.js" defer></script>' in index
      and "/studio/open" in link and "dev chat" not in link)
check("the button is an icon with the hover tooltip 'LOKI Studio' - work on LOKI itself with DeepSeek V4.1",
      'dataset.icon = "studio"' in link and "Work on LOKI itself with DeepSeek V4.1" in link and "studio:" in icons)
check("launchers: Loki Studio.cmd (Windows) and studio/loki_studio.sh + make_studio_app.sh (Mac)",
      (REPO / "Loki Studio.cmd").is_file() and (REPO / "studio" / "loki_studio.sh").is_file() and (REPO / "studio" / "make_studio_app.sh").is_file())
import shutil  # noqa: E402
for sh in ("studio/loki_studio.sh", "studio/make_studio_app.sh"):
    lf = b"\r\n" not in (REPO / sh).read_bytes() or sys.platform == "win32"   # a Windows checkout may convert
    if shutil.which("bash") and sys.platform != "win32":
        p = subprocess.run(["bash", "-n", str(REPO / sh)], capture_output=True, text=True)
        check("%s parses (bash -n) and is LF" % sh, p.returncode == 0 and lf, p.stderr)
    else:
        check("%s is LF" % sh, lf)
ship_src = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("this suite runs in tools/ship.py", '"test_studio"' in ship_src)
check("docs: docs/STUDIO.md and docs/LOKI_MCP.md (with the mcp_servers snippet)",
      (REPO / "docs" / "STUDIO.md").is_file() and "mcp_servers" in (REPO / "docs" / "LOKI_MCP.md").read_text(encoding="utf-8"))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
