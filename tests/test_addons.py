"""Session 23 add-ons, offline: the built-in CRM, the Scrapling scrape runner (and its
fallback), the vendored marketing skills, OpenHands as a harness, Remotion videos, the
optional add-on cards (PenEcho, OpenHuman, Remotion, PersonaLive) and the Novel writer
template. Nothing is installed, downloaded or started; every outside program is faked.

    python tests/test_addons.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-addons-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(TMP / "ws")
(TMP / "ws").mkdir(parents=True, exist_ok=True)

import agents  # noqa: E402
import cli_agents  # noqa: E402
import conductor  # noqa: E402
import crm  # noqa: E402
import manifests  # noqa: E402
import policy  # noqa: E402
import workers  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def section(title):
    print("\n" + title)


def load_runner(name):
    spec = importlib.util.spec_from_file_location("_runner_" + name, REPO / "engine" / "runners" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ CRM
section("CRM: contacts, companies, deals, interactions, tasks")
store = crm.CRM(TMP / "crm" / "crm.sqlite3")
check("the database is created where it was asked (the data dir, not the repo)",
      (TMP / "crm" / "crm.sqlite3").is_file())
acme = store.add("company", {"name": "Acme", "website": "acme.test"})
ada = store.add("contact", {"name": "Ada Lovelace", "email": "ada@acme.test", "company_id": acme["id"]})
pilot = store.add("deal", {"title": "Pilot", "company_id": acme["id"], "contact_id": ada["id"],
                           "stage": "proposal", "value": "5000"})
store.add("deal", {"title": "Renewal", "stage": "won", "value": 1200, "currency": "eur"})
store.add("deal", {"title": "Lost one", "stage": "lost", "value": 300})
check("add returns the stored row with an id and defaults", pilot["id"] and pilot["currency"] == "USD"
      and pilot["value"] == 5000.0, pilot)
check("a deal's currency is upper-cased", store.list("deals", stage="won")[0]["currency"] == "EUR")
note = store.log({"contact_id": ada["id"], "kind": "call", "summary": "Intro call, wants a pilot"})
check("log records an interaction with a date", note["kind"] == "call" and note["at"], note)
try:
    store.log({"summary": "floating"})
    check("log refuses an interaction attached to nothing", False)
except crm.CRMError:
    check("log refuses an interaction attached to nothing", True)
task = store.add("task", {"title": "Send proposal", "due": "2020-01-31", "deal_id": pilot["id"]})
store.add("task", {"title": "Later", "due": "2999-01-01"})
check("find searches names, emails and notes across types",
      {r["type"] for r in store.find("acme")} == {"companies", "contacts"}, store.find("acme"))
check("find can be limited to one type", [r["type"] for r in store.find("acme", "contacts")] == ["contacts"])
moved = store.update("deal", pilot["id"], {"stage": "negotiation", "value": 6500})
check("update changes only the given fields", moved["stage"] == "negotiation" and moved["value"] == 6500.0
      and moved["title"] == "Pilot")
for bad, why in (({"stage": "maybe"}, "stage"), ({"value": "lots"}, "value"), ({"title": ""}, "empty")):
    try:
        store.update("deal", pilot["id"], bad)
        check("update refuses a bad %s" % why, False)
    except crm.CRMError:
        check("update refuses a bad %s" % why, True)
try:
    store.add("contact", {"name": "Ghost", "company_id": 999})
    check("a link to a missing record is refused", False)
except crm.CRMError:
    check("a link to a missing record is refused", True)
check("history lists a contact's interactions", [i["summary"] for i in store.history("contacts", ada["id"])]
      == ["Intro call, wants a pilot"])
store.update("task", task["id"], {"done": True})
check("a task can be marked done", store.get("tasks", task["id"])["done"] == 1)

p = store.pipeline(today="2026-10-16")
check("pipeline counts deals per stage", p["stages"]["negotiation"]["count"] == 1 and p["stages"]["won"]["count"] == 1
      and p["stages"]["lost"]["count"] == 1, p["stages"])
check("pipeline sums open and won value per currency", p["open_value"] == {"USD": 6500.0}
      and p["won_value"] == {"EUR": 1200.0}, (p["open_value"], p["won_value"]))
check("win rate is won / (won + lost)", p["win_rate"] == 0.5, p["win_rate"])
store.add("task", {"title": "Overdue call", "due": "2026-01-01"})
p = store.pipeline(today="2026-10-16")
check("overdue open tasks are listed (done ones are not)", [t["title"] for t in p["overdue_tasks"]] == ["Overdue call"],
      p["overdue_tasks"])
text = crm.render_pipeline(p)
check("the pipeline renders as readable text", "open deal" in text and "OVERDUE" in text and "win rate 50%" in text, text)
check("delete removes a record", store.delete("tasks", task["id"]) and not store.delete("tasks", task["id"]))
try:
    store.add("spaceships", {"name": "x"})
    check("an unknown record type is refused", False)
except crm.CRMError:
    check("an unknown record type is refused", True)

section("CRM: the bridge (GET /crm, POST /crm/<op>)")
code, snap = crm.handle(store, "GET", "", {})
check("GET /crm returns the pipeline and the lists", code == 200 and snap["ok"] and snap["deals"]
      and snap["contacts"] and "stages" in snap)
code, made = crm.handle(store, "POST", "add", {"type": "contacts", "fields": {"name": "Grace", "email": "g@x.test"}})
check("POST /crm/add adds", code == 200 and made["record"]["name"] == "Grace")
code, bad = crm.handle(store, "POST", "add", {"type": "deals", "fields": {"title": "x", "stage": "bogus"}})
check("a bad request is a 400 with a reason", code == 400 and "stage" in bad["error"])
code, gone = crm.handle(store, "POST", "delete", {"type": "contacts", "id": made["record"]["id"]})
check("POST /crm/delete deletes", code == 200 and gone["ok"])
check("an unknown op is a 404", crm.handle(store, "POST", "explode", {})[0] == 404)
try:
    import loki_bridge  # noqa: E402
    fake_state = types.SimpleNamespace(agent=types.SimpleNamespace(crm_store=lambda: store))
    code, payload = loki_bridge.crm_route(fake_state, "POST", "/crm/find", {"query": "ada"})
    check("loki_bridge.crm_route dispatches /crm/<op> to the engine's CRM",
          code == 200 and payload["results"] and payload["results"][0]["name"] == "Ada Lovelace", payload)
    code, payload = loki_bridge.crm_route(fake_state, "GET", "/crm", {})
    check("loki_bridge.crm_route answers GET /crm", code == 200 and "pipeline" in payload)
except ImportError as exc:
    print("  SKIP bridge: %s" % exc)

# ------------------------------------------------------------------ engine tools
section("CRM + scrape + video: agent tools")
import loki  # noqa: E402
loki._CRM_STORE = crm.CRM(TMP / "tools.sqlite3")
out = loki.crm_add("company", '{"name": "Initech"}')
check("crm_add takes fields as JSON text", out.startswith("added companies #1 Initech"), out)
out = loki.crm_add("deal", {"title": "Big", "company_id": 1, "stage": "qualified", "value": 900})
check("crm_add takes fields as an object too", "deals #1 Big" in out and "stage=qualified" in out, out)
check("crm_update moves a deal", "stage=won" in loki.crm_update("deal", 1, '{"stage": "won"}'))
check("crm_log needs a record", loki.crm_log("hello").startswith("error"))
check("crm_log logs against a company", loki.crm_log("met them", kind="meeting", company_id=1).startswith("logged"))
check("crm_find finds", "Initech" in loki.crm_find("init"))
check("crm_find with only a type lists", "Big" in loki.crm_find(type="deals"))
check("crm_pipeline summarises", "win rate 100%" in loki.crm_pipeline(), loki.crm_pipeline())
check("bad input is an error string, never an exception", loki.crm_add("deal", "{not json").startswith("error"))
names = ("crm_add", "crm_update", "crm_find", "crm_log", "crm_pipeline", "scrape", "video_project", "render_video")
schemas = {t["function"]["name"] for t in loki.TOOL_SCHEMAS}
check("every new tool is a local tool with a schema, offered to the model",
      all(n in loki.LOCAL_TOOLS and n in schemas and n in loki.MODEL_TOOL_NAMES for n in names))
check("the CRM tools are the 'business' tool category",
      set(loki.TOOL_CATEGORIES["business"]) == {"crm_add", "crm_update", "crm_find", "crm_log", "crm_pipeline"}
      and "business" in loki.CATEGORY_LABELS)
check("scrape (and the native read_web) are the web category, videos in creative",
      loki.TOOL_CATEGORIES["web"] == ["scrape", "read_web"]
      and {"video_project", "render_video"} <= set(loki.TOOL_CATEGORIES["creative"]))
check("Plan mode stays read-only: CRM writes and scrape are not offered there",
      {"crm_add", "crm_update", "crm_log", "scrape"} <= loki.NETWORK_WRITES)
check("Remotion tools ask first and need the remotion add-on",
      {"video_project", "render_video"} <= loki.DANGEROUS and policy.CAPABILITY_TOOLS["render_video"] == "remotion")
verdict = loki.POLICY.tool_call("render_video", {"project_dir": "videos/a", "composition": "Main"})
check("render_video is refused while Remotion is off", not verdict.allowed and "remotion" in verdict.reason, verdict)
check("...and is not offered to the model then",
      "render_video" not in {t["function"]["name"] for t in loki.model_tool_schemas()})
verdict = loki.POLICY.tool_call("render_video", {"project_dir": "../outside", "composition": "Main"})
check("render_video's project_dir must be inside the workspace", not verdict.allowed and "outside" in verdict.reason)

# ------------------------------------------------------------------ scrape
section("scrape: Scrapling runner, and the fallback when it is missing")


class FakeRegistry:
    def __init__(self, ready):
        self.ready = set(ready)


class FakePolicy:
    def __init__(self, ready):
        self.ready = set(ready)

    def capability(self, name, permission=""):
        if name in self.ready:
            return policy.Verdict(policy.ALLOW, "ok")
        return policy.Verdict(policy.DENY, "%s is not enabled - turn it on in Settings > Capabilities" % name)

    def network(self, url, capability=""):
        return policy.Verdict(policy.ALLOW, "ok")


def fake_runner(results, calls):
    def run(argv, input="", **kwargs):  # noqa: A002
        job = json.loads(input)
        name = Path(argv[-1]).stem
        calls.append((name, job))
        return types.SimpleNamespace(stdout=json.dumps(results[name](job)), stderr="", returncode=0)
    return run


calls: list = []
c = conductor.Conductor(FakePolicy({"scrapling", "crawl4ai"}), None, env={},
                        runner=fake_runner({"scrape": lambda j: {"ok": False, "missing": True,
                                                                 "error": "Scrapling is not installed"},
                                            "web_read": lambda j: {"ok": True, "text": "# Hello page"}}, calls),
                        python="python")
out = c.run("scrape", url="https://example.com/a")
check("Scrapling missing -> falls back to read_web (crawl4ai) and says how to install",
      out.startswith("# Hello page") and "setup_extras.py scrapling" in out and "crawl4ai" in out, out)
check("...the scrape runner was tried first", [n for n, _ in calls] == ["scrape", "web_read"], calls)
check("the fallback never uses Scrapling itself", calls[-1][1]["backend"] == "crawl4ai", calls[-1])
calls.clear()
c2 = conductor.Conductor(FakePolicy(set()), None, env={}, runner=fake_runner({}, calls), python="python")
out = c2.run("scrape", url="https://example.com")
check("nothing ready -> a clear error with the install line, no runner started",
      out.startswith("error: no scraper is ready") and "setup_extras.py scrapling" in out and not calls, out)
calls.clear()
c3 = conductor.Conductor(FakePolicy({"scrapling"}), None, env={},
                         runner=fake_runner({"scrape": lambda j: {"ok": True, "crawl": True, "pages": 7,
                                                                  "out_dir": j["out_dir"], "jsonl": "x.jsonl"}}, calls),
                         python="python")
out = c3.scrape("https://docs.example.com/start", "", crawl=True, max_pages=500, workspace=TMP / "ws")
job = calls[0][1]
check("a crawl goes into scraped/<domain>/ in the workspace",
      Path(job["out_dir"]) == TMP / "ws" / "scraped" / "docs.example.com" and job["crawl"], job)
check("max_pages is capped", job["max_pages"] == 200, job)
check("the crawl result is reported", "crawled 7 page(s) of docs.example.com" in out, out)
check("task words work too ('crawl max_pages=5 js')",
      conductor.parse_scrape_task("crawl max_pages=5 js") == {"crawl": True, "dynamic": True, "max_pages": 5})
check("a non-web url is refused", c3.scrape("file:///etc/passwd").startswith("error"))
check("scrape is a conductor role", "scrape" in conductor.ROLES and conductor.ROLES["scrape"]["capabilities"] == ("scrapling",))
runner_src = (REPO / "engine" / "runners" / "scrape.py").read_text(encoding="utf-8")
check("the runner never uses the stealth fetcher or Cloudflare solving",
      "StealthyFetcher" not in runner_src.replace("Never the stealth fetcher", "")
      and "solve_cloudflare" not in runner_src)
if importlib.util.find_spec("scrapling") is None:
    proc = subprocess.run([sys.executable, "-I", str(REPO / "engine" / "runners" / "scrape.py")],
                          input=json.dumps({"url": "https://example.com"}), capture_output=True, text=True, timeout=60)
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    check("the real runner reports 'missing' when Scrapling is not installed",
          result.get("ok") is False and result.get("missing") is True, result)
scrape_mod = load_runner("scrape")
check("the runner names output by domain", scrape_mod.domain_of("https://Docs.Example.com/x") == "docs.example.com")

# ------------------------------------------------------------------ skills
section("marketing skills (coreyhaines31/marketingskills, MIT)")
cat = agents.skills_catalog(agents.skill_roots(REPO, TMP / "data"))
marketing = [s for s in cat if s["source"] == "marketing"]
check("the marketing skills are in the skill catalog", len(marketing) >= 40, len(marketing))
check("copywriting and seo-audit are among them", {"copywriting", "seo-audit"} <= {s["id"] for s in marketing})
check("each has a description from its frontmatter", all(s["description"] for s in marketing))
mk = REPO / "skills" / "marketing"
check("their MIT licence is kept alongside", (mk / "LICENSE").is_file()
      and "MIT License" in (mk / "LICENSE").read_text(encoding="utf-8"))
size = sum(p.stat().st_size for p in mk.rglob("*") if p.is_file())
check("the vendored folder stays under 3 MB", size < 3_000_000, size)
check("no evals or scripts were vendored", not list(mk.rglob("evals")) and not [
    p for p in mk.rglob("*") if p.suffix in (".py", ".sh", ".js", ".ts", ".ps1")])
check("the skill text loads for an agent", "copy" in agents.skill_text(next(s for s in marketing if s["id"] == "copywriting")).lower())
check("THIRD_PARTY.md credits it", "marketingskills" in (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8"))
check("the model can list them too (list_ecc_skills)", "copywriting" in loki.list_ecc_skills("copywriting"))

# ------------------------------------------------------------------ OpenHands
section("OpenHands as a harness (background jobs, agents, CLI provider)")
check("OpenHands is a worker agent and an agent-builder engine",
      "openhands" in workers.AGENTS and "openhands" in agents.ENGINES and "openhands" in agents.ENGINE_LABELS)
check("headless command line", workers.agent_argv("openhands", "fix the bug") ==
      ["openhands", "--headless", "--json", "--override-with-envs", "-t", "fix the bug"])
env = workers.openhands_env({"LOKI_LOCAL_MODEL": "qwen3:8b", "PATH": "x"})
check("it uses LOKI's chosen local Ollama model by default",
      env["LLM_MODEL"] == "openai/qwen3:8b" and env["LLM_BASE_URL"] == "http://localhost:11434/v1"
      and env["LLM_API_KEY"] and env["PATH"] == "x", env)
env = workers.openhands_env({"LOKI_OPENHANDS_MODEL": "anthropic/claude-x", "LOKI_OPENHANDS_BASE_URL": "https://y",
                             "LOKI_OPENHANDS_API_KEY": "k"})
check("LOKI_OPENHANDS_* override it", (env["LLM_MODEL"], env["LLM_BASE_URL"], env["LLM_API_KEY"])
      == ("anthropic/claude-x", "https://y", "k"))
saved_state = dict(loki.LOCAL_STATE)
loki.LOCAL_STATE.update(name="llama3.2:3b", base_url="http://localhost:11434/v1")
check("...and follows the model the engine resolved when nothing is pinned",
      workers.openhands_env({})["LLM_MODEL"] == "openai/llama3.2:3b")
loki.LOCAL_STATE.clear()
loki.LOCAL_STATE.update(saved_state)
check("starting OpenHands jobs needs the openhands add-on", policy.AGENT_CAPABILITY.get("openhands") == "openhands")
spec = cli_agents.CLI_AGENTS["openhands"]
check("OpenHands is a CLI agent with install guidance", spec["install"] and spec["signin"] and spec["llm_env"])
fake_exe = TMP / "openhands-fake"
fake_exe.write_text("", encoding="utf-8")
os.environ["LOKI_OPENHANDS_EXE"] = str(fake_exe)
seen = {}


def fake_run(argv, **kwargs):
    seen["argv"], seen["env"], seen["cwd"] = argv, kwargs.get("env"), kwargs.get("cwd")
    lines = [json.dumps({"action": "run", "args": {"command": "ls"}}),
             json.dumps({"action": "finish", "args": {"final_thought": "Fixed the bug in app.py"}})]
    return types.SimpleNamespace(stdout="\n".join(lines), stderr="", returncode=0)


_real_run = cli_agents.subprocess.run
cli_agents.subprocess.run = fake_run
try:
    answer = cli_agents.run("openhands", "SYSTEM", "fix it", str(TMP / "ws"))
finally:
    cli_agents.subprocess.run = _real_run
    os.environ.pop("LOKI_OPENHANDS_EXE", None)
check("cli_agents.run builds the headless command in the workspace",
      seen["argv"][:5] == [str(fake_exe), "--headless", "--json", "--override-with-envs", "-t"]
      and seen["argv"][-1].endswith("fix it") and seen["cwd"] == str(TMP / "ws"), seen.get("argv"))
check("...with the LLM_* variables set", seen["env"]["LLM_MODEL"].startswith("openai/") and seen["env"]["LLM_BASE_URL"])
check("...and returns the agent's final message from the JSON events", answer == "Fixed the bug in app.py", answer)
check("an agent profile with the openhands engine validates",
      agents.validate({"name": "OH", "engine": "openhands"})["engine"] == "openhands")

# ------------------------------------------------------------------ Remotion
section("Remotion videos (command lines only, no npx is run)")
video = load_runner("video")
check("scaffold command", video.scaffold_argv("npx", "intro") == ["npx", "--yes", "create-video@latest", "--yes",
                                                                    "--blank", "intro"])
check("render command", video.render_argv("npx", "src/index.ts", "Main", "out.mp4", "/p/props.json") ==
      ["npx", "remotion", "render", "src/index.ts", "Main", "out.mp4", "--props=/p/props.json", "--codec=h264",
       "--overwrite"])
check("render without props has no --props", "--props" not in " ".join(video.render_argv("npx", "e", "C", "o.mp4")))
proj = TMP / "ws" / "videos" / "intro"
(proj / "src").mkdir(parents=True)
(proj / "src" / "index.tsx").write_text("// entry", encoding="utf-8")
check("the entry file is found", video.find_entry(proj) == "src/index.tsx")
jobs = []
_real = loki.CONDUCTOR._runner
loki.CONDUCTOR._runner = lambda name, job, timeout: (jobs.append((name, job)) or {"ok": True, "file": job.get("out", ""),
                                                                                  "bytes": 1234})
try:
    out = loki.render_video("videos/intro", "Main", props='{"title": "Hi"}')
    out2 = loki.video_project("teaser")
finally:
    loki.CONDUCTOR._runner = _real
name, job = jobs[0]
check("render_video sends a render job to the video runner",
      name == "video" and job["op"] == "render" and job["composition"] == "Main" and job["props"] == {"title": "Hi"}, job)
check("...defaulting the output to videos/<composition>.mp4 inside the workspace",
      Path(job["out"]) == (TMP / "ws" / "videos" / "Main.mp4").resolve() and "rendered" in out, (job, out))
check("video_project scaffolds into videos/<name>", jobs[1][1] == {"op": "scaffold", "dir": str((TMP / "ws" / "videos" / "teaser").resolve())}
      and "remotion.dev/license" in out2, jobs[1])
check("render_video refuses a path outside the workspace", loki.render_video("../x", "Main").startswith("error"))
# The real runner: with npx faked, the render step writes the props file and runs the command.
ran = {}


def fake_video_run(argv, cwd, timeout):
    ran["argv"], ran["cwd"] = argv, cwd
    Path(argv[5]).write_bytes(b"mp4")
    return 0, "ok"


(proj / "package.json").write_text("{}", encoding="utf-8")
video.find_npx = lambda: "npx"
video._run = fake_video_run
_stdin, _stdout = sys.stdin, sys.stdout
import io  # noqa: E402
sys.stdin = io.StringIO(json.dumps({"op": "render", "project_dir": str(proj), "composition": "Main",
                                    "out": str(TMP / "ws" / "videos" / "x.mp4"), "props": {"a": 1}}))
sys.stdout = io.StringIO()
try:
    video.main()
    printed = sys.stdout.getvalue()
finally:
    sys.stdin, sys.stdout = _stdin, _stdout
result = json.loads(printed.strip().splitlines()[-1])
check("the runner renders with --props pointing at a JSON file it wrote",
      result.get("ok") and ran["argv"][:4] == ["npx", "remotion", "render", "src/index.tsx"]
      and json.loads((proj / ".loki-props.json").read_text(encoding="utf-8")) == {"a": 1}
      and ran["cwd"] == str(proj), (result, ran))

# ------------------------------------------------------------------ add-on catalog
section("optional add-ons: catalog cards, MCP servers, installers")
registry = manifests.default_registry(REPO, TMP / "catalog")
rows = {r["name"]: r for r in registry.present()}
new = ("penecho", "openhuman", "remotion", "personalive", "openhands", "scrapling")
check("every add-on has a valid manifest", all(n in rows and not rows[n]["errors"] for n in new),
      {n: rows.get(n, {}).get("errors") for n in new})
check("all are off by default", all(rows[n]["status"] in ("disabled", "reference") for n in new),
      {n: rows[n]["status"] for n in new})
check("each shows how to install it", all(rows[n]["install_hint"] for n in new))
check("licences are stated: AGPL, GPL, Remotion's, academic-only",
      "AGPL-3.0" in rows["penecho"]["license"] and "GPL-3.0" in rows["openhuman"]["license"]
      and "3 employees" in rows["remotion"]["license"] and "Academic" in rows["personalive"]["license"])
check("Remotion's card carries the licence warning", "3 employees" in rows["remotion"]["notice"])
check("PenEcho has an 'Open drawing canvas' button for http://localhost:3888",
      rows["penecho"]["actions"] == [{"label": "Open drawing canvas", "url": "http://localhost:3888"}])
check("PersonaLive is a card only (Windows + NVIDIA), it cannot be turned on",
      rows["personalive"]["card_only"] and rows["personalive"]["status"] == "reference")
try:
    registry.set_enabled("personalive", True)
    check("...enabling it is refused", False)
except ValueError:
    check("...enabling it is refused", True)
pl = json.loads((REPO / "capabilities" / "personalive" / "manifest.json").read_text(encoding="utf-8"))
check("PersonaLive needs Windows: on a Mac it reports the platform",
      any("Windows" in m for m in manifests.missing_requirements(pl, {}, lambda c: "/x", platform="darwin")))
check("a reference add-on is denied by the policy engine",
      not policy.PolicyEngine(lambda n: n, lambda c: (True, ""), lambda c: c, set(), registry=registry)
      .capability("personalive").allowed)
check("card text and install hints are cosmetic: rewording them does not switch an add-on off",
      manifests.trust_fingerprint(dict(pl, install="x", notice="y", actions=[]))
      == manifests.trust_fingerprint(pl))
check("a manifest action must be an http(s) link",
      manifests.validate(dict(pl, actions=[{"label": "x", "url": "file:///etc"}])) != [])
mcp = json.loads((REPO / "engine" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
check("PenEcho's MCP server is registered, opt-in", mcp["penecho"]["command"] == "penecho"
      and mcp["penecho"]["args"] == ["mcp"] and mcp["penecho"]["enabled"] is False
      and mcp["penecho"]["capability"] == "penecho")
check("OpenHuman's MCP server is registered, opt-in, only when openhuman-core is on PATH",
      mcp["openhuman"]["command"] == "openhuman-core" and mcp["openhuman"]["args"] == ["mcp"]
      and mcp["openhuman"]["requires_cmd"] == "openhuman-core" and mcp["openhuman"]["enabled"] is False)
check("while the add-on is off, the MCP server stays off",
      "disabled" in loki._server_skip_reason(mcp["penecho"], "penecho"))
_caps = loki.CAPABILITIES
loki.CAPABILITIES = types.SimpleNamespace(is_enabled=lambda name: name == "penecho")
try:
    reason = loki._server_skip_reason(mcp["penecho"], "penecho")
finally:
    loki.CAPABILITIES = _caps
check("turning the add-on on starts it (here: then it needs penecho on PATH)",
      reason == "" if shutil.which("penecho") else "needs 'penecho' on PATH" in reason, reason)
import portal_api  # noqa: E402
opened = []
_wb = portal_api.webbrowser.open
portal_api.webbrowser.open = lambda url: opened.append(url)
try:
    fake_agent = types.SimpleNamespace(CAPABILITIES=registry, DATA_DIR=TMP / "data")
    code, res = portal_api.handle_post(types.SimpleNamespace(agent=fake_agent), "/open", {"url": "http://localhost:3888"})
    code2, _ = portal_api.handle_post(types.SimpleNamespace(agent=fake_agent), "/open", {"url": "http://evil.test"})
finally:
    portal_api.webbrowser.open = _wb
check("the app may open an add-on's card links, nothing else", code == 200 and code2 == 400, (code, res, code2))
spec_x = importlib.util.spec_from_file_location("_setup_extras", REPO / "tools" / "setup_extras.py")
extras = importlib.util.module_from_spec(spec_x)
spec_x.loader.exec_module(extras)
check("installers exist for scrapling, openhands, penecho, openhuman, remotion",
      {"scrapling", "openhands", "penecho", "openhuman", "remotion"} <= set(extras.OPT_IN))
check("...and none of them is part of `all` (never installed without being named)",
      not set(extras.OPT_IN) & set(extras.STEPS))
check("THIRD_PARTY.md lists the licences",
      all(w in (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
          for w in ("Scrapling", "OpenHands", "PenEcho", "OpenHuman", "Remotion", "PersonaLive")))

# ------------------------------------------------------------------ novel template
section("Novel writer template")
novel = next((t for t in agents.TEMPLATES if t["id"] == "novel-writer"), None)
check("the Novel Writer template exists", novel is not None)
if novel:
    text = novel["instructions"]
    check("it works in stages: idea, world, characters, outline, chapters, continuity, rewrite",
          all(w in text for w in ("Idea", "World", "Characters", "Outline", "Chapters", "Continuity", "Rewrite")))
    check("it saves into novel/ in the workspace", "novel/" in text and "novel/chapters/" in text)
    check("it validates as an agent profile", agents.validate(novel)["name"] == "Novel Writer")
check("the OpenHands template exists too", any(t.get("engine") == "openhands" for t in agents.TEMPLATES))

# ------------------------------------------------------------------ UI + ship
section("UI and shipping")
ui = REPO / "app" / "ui"
html = (ui / "index.html").read_text(encoding="utf-8")
check("Settings has a CRM tab and panel, loaded from crm.js (no inline script)",
      'data-tab="crm"' in html and 'data-panel="crm"' in html and '<script src="/ui/crm.js"' in html
      and "<script>" not in html)
crm_js = (ui / "crm.js").read_text(encoding="utf-8")
check("the CRM panel talks to /crm and /crm/add", 'api("/crm")' in crm_js and '"/crm/add"' in crm_js)
check("showTab loads the CRM", 'name === "crm"' in (ui / "app.js").read_text(encoding="utf-8"))
check("the Add-ons card shows install hints and action buttons",
      "cap.install" in (ui / "app.js").read_text(encoding="utf-8") and "cap.actions" in (ui / "app.js").read_text(encoding="utf-8"))
if shutil.which("node"):
    for js in ("crm.js", "app.js"):
        proc = subprocess.run(["node", "--check", str(ui / js)], capture_output=True, text=True)
        check("%s parses" % js, proc.returncode == 0, proc.stderr)
check("ship.py runs this suite", '"test_addons"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
check("no Godot project files were added", not [p for p in (REPO / "skills").rglob("*")
                                                if p.suffix in (".gd", ".tscn") or p.name == "project.godot"])

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
