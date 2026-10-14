"""Offline tests for the conductor and its specialists, the brain map, and the
third-party integrations (Perplexity, crawl4ai, Scrapling, Firecrawl, Browser Use,
Hindsight, Headroom, SkillSpector, Hermes Agent, Kiln). Every outside service is faked.

    python tests/test_integrations.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "engine"))

import brain  # noqa: E402
import conductor  # noqa: E402
import manifests  # noqa: E402
import policy  # noqa: E402
import safe_exec  # noqa: E402
import skill_scan  # noqa: E402
import workers  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (detail,)))


def section(title):
    print("\n" + title)


TMP = Path(tempfile.mkdtemp(prefix="loki-integrations-"))
NEW = ("perplexity", "crawl4ai", "scrapling", "firecrawl", "browser-use", "hindsight", "headroom",
       "skillspector", "hermes-agent", "kiln")

# ------------------------------------------------------------------ manifests
section("integration manifests")
real = manifests.default_registry(REPO, TMP / "data")
rows = {r["name"]: r for r in real.present()}
check("every new integration has a valid built-in manifest",
      all(n in rows and not rows[n]["errors"] for n in NEW), {n: rows.get(n, {}).get("errors") for n in NEW})
check("all of them start disabled", all(rows[n]["status"] == "disabled" for n in NEW))
check("Firecrawl's AGPL licence is stated", "AGPL" in rows["firecrawl"]["license"])
check("browser-use declares network access as high risk",
      any(p["id"] == "network" and p["high_risk"] for p in rows["browser-use"]["permissions"]))
reg_mod = manifests.Registry([("b", TMP / "m")], manifests.Enablement(TMP / "e.json"), env={}, which=lambda c: None)
check("python requirements are checked without importing",
      manifests.missing_requirements({"requires_python": ["definitely_not_a_module_xyz", "json"]}, {},
                                     lambda c: None) == ["python package `definitely_not_a_module_xyz`"])

# ------------------------------------------------------------------ conductor
section("the conductor")


class Reg:
    def __init__(self, on):
        self.on = on

    def get(self, name):
        return {"status": "enabled" if name in self.on else "disabled"}

    def granted(self, name):
        return set(self.on.get(name, ()))


def make(on, env=None, runner=None, opener=None):
    engine = policy.PolicyEngine(lambda p: p, lambda c: (True, "ok"), safe_exec.parse, set(), Reg(on), env=env or {})
    return conductor.Conductor(engine, Reg(on), env=env or {}, runner=runner or (lambda *a, **k: None),
                               opener=opener or (lambda *a, **k: None), python="python3")


c = make({})
check("with nothing enabled no role is ready", not any(r["ready"] for r in c.roster()))
check("an unready role explains why", "not enabled" in c.run("research", "q"))
check("with nothing ready the prompt adds no specialists", c.prompt_section() == "")
check("an unknown role is refused", "unknown role" in c.run("hack", "x"))


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


sent = []


def perplexity_opener(request, timeout):
    sent.append((request.full_url, json.loads(request.data), dict(request.headers)))
    return Resp(json.dumps({"choices": [{"message": {"content": "Paris is the capital [1]."}}],
                            "search_results": [{"url": "https://example.org/paris"}]}).encode())


c = make({"perplexity": ["network:api.perplexity.ai", "secret:PERPLEXITY_API_KEY"]},
         env={"PERPLEXITY_API_KEY": "pk-test"}, opener=perplexity_opener)
answer = c.run("research", "capital of France?")
check("research calls Perplexity Sonar with the key", sent and sent[0][0] == conductor.PERPLEXITY_URL
      and sent[0][1]["model"] == "sonar" and sent[0][2].get("Authorization") == "Bearer pk-test")
check("research returns the answer with numbered sources", "Paris" in answer and "[1] https://example.org/paris" in answer, answer)
check("a ready role is advertised in the system prompt", "research" in c.prompt_section())
c2 = make({"perplexity": []}, env={"PERPLEXITY_API_KEY": "k"}, opener=perplexity_opener)
check("research without the granted host is refused", "not granted" in c2.run("research", "q"))

calls = []


def fake_runner(argv, **kw):
    calls.append((argv, json.loads(kw["input"]), kw))
    job = json.loads(kw["input"])
    if argv[-1].endswith("web_read.py"):
        out = {"ok": True, "text": "# Example\nhello from " + job["backend"], "truncated": False}
    elif argv[-1].endswith("browse.py"):
        out = {"ok": True, "text": "found 42 stars"}
    else:
        out = {"ok": True, "result": {"memories": ["likes tests"]}}
    return types.SimpleNamespace(returncode=0, stdout="noise\n" + json.dumps(out) + "\n", stderr="")


c = make({"scrapling": ["network", "process:spawn"], "crawl4ai": ["network", "process:spawn"]},
         env={"LOKI_READ_ORDER": "scrapling,crawl4ai"}, runner=fake_runner)
text = c.run("read_web", url="https://example.com")
check("read_web uses the first enabled backend in LOKI_READ_ORDER", "hello from scrapling" in text, text)
check("runners run isolated (-I) without a shell and with a timeout",
      calls[-1][0][1] == "-I" and calls[-1][2]["shell"] is False and calls[-1][2]["timeout"] > 0)
check("read_web refuses a non-http url", "http(s)" in c.run("read_web", url="file:///etc/passwd"))
c = make({"crawl4ai": ["network", "process:spawn"]}, runner=fake_runner)
check("read_web falls back to crawl4ai when it is the one enabled", "hello from crawl4ai" in c.run("read_web", url="https://e.com"))

fire = []


def firecrawl_opener(request, timeout):
    fire.append((request.full_url, json.loads(request.data)))
    return Resp(json.dumps({"success": True, "data": {"markdown": "# Fire\ncrawled"}}).encode())


c = make({"firecrawl": ["network:loopback"]}, opener=firecrawl_opener)
text = c.run("read_web", url="https://example.com")
check("Firecrawl is called at the self-hosted /v2/scrape for markdown",
      fire and fire[0][0] == "http://localhost:3002/v2/scrape" and fire[0][1]["formats"] == ["markdown"] and "crawled" in text)
c = make({"firecrawl": ["network:loopback"]}, env={"LOKI_FIRECRAWL_URL": "https://firecrawl.remote.example"}, opener=firecrawl_opener)
check("a remote Firecrawl host needs LOKI_NET_ALLOW", "not allowed" in c.run("read_web", url="https://e.com"))

c = make({"browser-use": ["network", "process:spawn"]}, env={"LOKI_BROWSE_MODEL": "m"}, runner=fake_runner)
check("browse runs Browser Use in its runner", c.run("browse", "count stars") == "found 42 stars")
check("browse is flagged as needing approval", c.needs_approval("browse") and not c.needs_approval("research"))
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(), Reg({}), env={})
v = engine.tool_call("conductor", {"role": "browse", "task": "x"})
check("the policy always asks before a browser acts (not decidable)", v.decision == policy.ASK and not v.decidable)
check("other roles are not prompted", engine.tool_call("conductor", {"role": "research"}).allowed)

c = make({"hindsight": ["network:loopback"]}, runner=fake_runner)
check("remember stores through Hindsight", c.run("remember", "likes tests") == "stored in long-term memory"
      and calls[-1][1]["op"] == "retain" and calls[-1][1]["bank"] == "loki")
check("recall queries Hindsight", "likes tests" in c.run("recall", "what do they like?") and calls[-1][1]["op"] == "recall")


def timeout_runner(argv, **kw):
    import subprocess
    raise subprocess.TimeoutExpired(argv, kw["timeout"])


c = make({"browser-use": ["network", "process:spawn"]}, runner=timeout_runner)
check("a runner that hangs times out cleanly", "timed out" in c.run("browse", "x"))
c = make({"hindsight": ["network:loopback"]}, runner=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="boom"))
check("a runner with no result reports its stderr", "boom" in c.run("recall", "x"))

for script in ("web_read", "browse", "hindsight"):
    import subprocess as sp
    proc = sp.run([sys.executable, "-I", str(conductor.RUNNERS / (script + ".py"))],
                  input=json.dumps({"backend": "crawl4ai", "url": "https://e.com", "op": "recall", "task": "x"}),
                  capture_output=True, text=True, timeout=60)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    check("runner %s reports a missing library instead of crashing" % script,
          out["ok"] is False and "not installed" in out["error"], out)

# ------------------------------------------------------------------ in-loop helpers
section("Headroom and SkillSpector")
msgs = [{"role": "user", "content": "x" * 100}]
fake_headroom = types.SimpleNamespace(compress=lambda m, model: types.SimpleNamespace(
    messages=[{"role": "user", "content": "x"}], tokens_saved=99))
out, note = conductor.compress_messages(msgs, "m", importer=lambda n: fake_headroom)
check("Headroom compresses a copy of the messages", out[0]["content"] == "x" and "99" in note and msgs[0]["content"] == "x" * 100)
out, note = conductor.compress_messages(msgs, "m", importer=lambda n: (_ for _ in ()).throw(ImportError()))
check("without Headroom the messages pass through untouched", out is msgs and note == "")
out, _ = conductor.compress_messages(msgs, "m", importer=lambda n: types.SimpleNamespace(
    compress=lambda m, model: (_ for _ in ()).throw(RuntimeError())))
check("a Headroom error never breaks the call", out is msgs)

report = {"findings": [{"severity": "HIGH", "message": "curl | sh in install step"},
                       {"severity": "low", "message": "unpinned dependency"}]}
spector = conductor.skillspector_findings(TMP, which=lambda n: "/x/skillspector",
                                          runner=lambda argv, **k: types.SimpleNamespace(stdout=json.dumps(report)))
check("SkillSpector findings are parsed", ("high", "curl | sh in install step") in spector and len(spector) == 2)
check("no SkillSpector installed means no findings", conductor.skillspector_findings(TMP, which=lambda n: None) == [])
folder = TMP / "sk" / "demo"
folder.mkdir(parents=True)
(folder / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nSteps.\n", encoding="utf-8")
skill_scan.EXTERNAL_SCANNERS[:] = [lambda root: [("high", "dangerous install step")]]
check("a high SkillSpector finding blocks the skill", skill_scan.scan(folder / "SKILL.md")["verdict"] == "blocked")
skill_scan.EXTERNAL_SCANNERS[:] = [lambda root: [("low", "minor")]]
check("a low finding only asks for review", skill_scan.scan(folder / "SKILL.md")["verdict"] == "review")
skill_scan.EXTERNAL_SCANNERS[:] = [lambda root: (_ for _ in ()).throw(RuntimeError())]
check("a crashing external scanner does not block", skill_scan.scan(folder / "SKILL.md")["verdict"] == "ok")
skill_scan.EXTERNAL_SCANNERS[:] = []

# ------------------------------------------------------------------ Hermes
section("Hermes Agent")
check("Hermes starts interactively", workers.agent_argv("hermes", "", interactive=True, env={}) == ["hermes"])
check("Hermes runs one-shot with -z (final answer only)",
      workers.agent_argv("hermes", "fix it", env={}) == ["hermes", "-z", "fix it"])
check("Hermes never gets --yolo", "--yolo" not in workers.agent_argv("hermes", "x", env={}))
check("LOKI_HERMES_MODEL / _PROVIDER become Hermes' own flags",
      workers.agent_argv("hermes", "x", env={"LOKI_HERMES_MODEL": "m1", "LOKI_HERMES_PROVIDER": "openrouter"})
      == ["hermes", "-m", "m1", "--provider", "openrouter", "-z", "x"])
sup = workers.Supervisor(workers.JobStore(TMP / "j.json"), {n: workers.Backend() for n in workers.BACKENDS}, TMP)
check("a Hermes job on the local backend is accepted",
      sup.create({"backend": "local", "agent": "hermes", "workspace": str(TMP), "prompt": "x"})["agent"] == "hermes")
check("a Hermes job on herdr is accepted",
      sup.create({"backend": "herdr", "agent": "hermes", "workspace": str(TMP), "prompt": "x"})["agent"] == "hermes")
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(),
                             Reg({"herdr": ["process:agent"]}), env={})
check("a Hermes job needs the hermes-agent capability", not engine.job("herdr", "hermes").allowed)
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(),
                             Reg({"herdr": ["process:agent"], "hermes-agent": ["process:agent"]}), env={})
check("with both on, a Hermes herdr job is allowed", engine.job("herdr", "hermes").allowed)
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(), Reg({}), env={})
check("a local Hermes job still needs the hermes-agent capability", not engine.job("local", "hermes").allowed)
check("Hermes counts as a local agent when installed",
      "hermes" in workers.LocalBackend(TMP, which=lambda n: "/bin/" + n).available()[1])

# ------------------------------------------------------------------ brain map
section("brain map")
data = TMP / "bdata"
(data / "memory").mkdir(parents=True)
(data / "memory.md").write_text("- prefers small PRs\n- uses a Mac mini\n", encoding="utf-8")
(data / "memory" / "people.md").write_text("Sam is a friend. #friends\n", encoding="utf-8")
(data / "jobs.json").write_text(json.dumps({"jobs": [{"id": "j1", "title": "add tests", "status": "done",
                                                      "backend": "herdr", "created": 1}]}), encoding="utf-8")
ws = TMP / "ws"
(ws / "docs" / "sub").mkdir(parents=True)
(ws / "docs" / "a.md").write_text("See [[b]] and [c](sub/c.md).", encoding="utf-8")
(ws / "docs" / "b.md").write_text("Back to [[a|the start]].", encoding="utf-8")
(ws / "docs" / "sub" / "c.md").write_text("leaf", encoding="utf-8")
vault = TMP / "vault"
(vault / ".obsidian").mkdir(parents=True)
(vault / ".obsidian" / "hidden.md").write_text("[[Ideas]]", encoding="utf-8")
(vault / "Ideas.md").write_text("Build Loki. [[Projects/Loki]] #ai", encoding="utf-8")
(vault / "Projects").mkdir()
(vault / "Projects" / "Loki.md").write_text("The conductor. [[Ideas#Top]] #ai", encoding="utf-8")
(vault / "Lonely.md").write_text("no links", encoding="utf-8")
outside = TMP / "secret.txt"
outside.write_text("do not leak", encoding="utf-8")
roster = [{"role": "research", "ready": True, "via": "perplexity", "why": ""}]
skills = [("Loki", "loki-testing", REPO / "skills" / "loki-testing" / "SKILL.md")]
graph = brain.build(data, ws, real, roster, skills, str(vault))
nodes = {n["id"]: n for n in graph["nodes"]}
labels = {n["label"]: n for n in graph["nodes"]}
edges = {tuple(e) for e in graph["edges"]}


def linked(a, b):
    ia, ib = labels[a]["id"], labels[b]["id"]
    return (ia, ib) in edges or (ib, ia) in edges


check("Loki is the centre", "loki" in nodes and nodes["loki"]["degree"] > 5)
def linked_ids(a, b):
    return (a, b) in edges or (b, a) in edges


check("roles hang off Loki and link their capabilities",
      linked_ids("loki", "role:research") and linked_ids("role:research", "cap:perplexity"))
check("memory facts are nodes", "prefers small PRs" in labels and linked("Memory", "prefers small PRs"))
check("viking://memory notes and their #tags are mapped", "people" in labels and linked("people", "#friends"))
check("skills group under their library", linked_ids("hub:skills", "lib:Loki")
      and any(linked_ids("lib:Loki", n["id"]) for n in graph["nodes"] if n["label"] == "loki-testing"))
check("jobs link to the backend capability", linked("add tests", "herdr"))
check("docs [[wikilinks]] become edges", linked("a", "b"))
check("relative markdown links become edges", linked("a", "c"))
check("vault notes link by [[path]] and [[name#heading]]", linked("Ideas", "Loki") or ("Ideas" in labels and "Projects/Loki.md" in str([n["detail"] for n in graph["nodes"]])))
check("shared #tags connect vault notes", linked("Ideas", "#ai"))
check("an unlinked note hangs off its vault", linked(vault.name, "Lonely"))
check(".obsidian internals are skipped", "hidden" not in labels)
check("groups are labelled for the legend", graph["groups"].get("vault") == "Your vault")
note_id = labels["Ideas"]["id"]
check("a listed note's text can be read", "Build Loki" in brain.note_text(graph, note_id))
check("anything not listed cannot be read", brain.note_text(graph, "vault:" + "0" * 12) is None)
check("the public graph does not expose file paths", "_files" not in brain.public(graph)
      and str(outside) not in json.dumps(brain.public(graph)))
try:
    brain.save_vault(data, str(TMP / "nope"))
    ok = False
except ValueError:
    ok = True
check("linking a missing vault folder is refused", ok)
check("a vault folder is remembered", brain.save_vault(data, str(vault)) == str(vault.resolve())
      and brain.load_settings(data)["vault"] == str(vault.resolve()))

import loki_bridge  # noqa: E402

agent = types.SimpleNamespace(DATA_DIR=data, WORKSPACE=ws, CAPABILITIES=real,
                              CONDUCTOR=types.SimpleNamespace(roster=lambda: roster),
                              _skill_entries=lambda: skills)
state = types.SimpleNamespace(agent=agent, brain={}, project=ws, jobs=None)
code, body = loki_bridge.brain_graph(state)
check("GET /brain returns the graph with the linked vault", code == 200 and body["vault"] == str(vault.resolve())
      and any(n["label"] == "Ideas" for n in body["nodes"]))
code, body = loki_bridge.brain_note(state, {"id": [note_id]})
check("GET /brain/note serves a mapped note", code == 200 and "Build Loki" in body["text"])
check("GET /brain/note refuses an unmapped id", loki_bridge.brain_note(state, {"id": ["../../etc"]})[0] == 404)
check("POST /brain/vault refuses a bad folder", loki_bridge.brain_vault(state, {"path": "/no/such/dir"})[0] == 400)
ui = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("the Brain tab is gone (knowledge stays reachable over the API)",
      "brain" not in ui.lower() and not (REPO / "app" / "ui" / "brain.js").exists())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
