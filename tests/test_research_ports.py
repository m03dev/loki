"""Session 27 research ports, offline: what LOKI took from aider, langgraph-bigtool, instructor,
ReWOO, Reflexion, STORM, Fooocus, ACE-Step and Kokoro - all with fake models, fake servers and
fake shells; no network.

  repo map (tags, PageRank, focus, budget), SEARCH/REPLACE edit blocks (matching, failures,
  CRLF, undo), tool retrieval (BM25, unlocking for a local model), structured output (validate,
  parse, re-ask), ReWOO (plan parsing, #E substitution, run), Reflexion (prompt, memory, trial
  loop), deep research (DuckDuckGo/SearXNG parsing, the STORM pipeline, citations), image prompt
  styles and expansion, ACE-Step music client, voice (Kokoro / say / SAPI / espeak), and the
  tools as registered in loki.py.

    python tests/test_research_ports.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import types
import urllib.error
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-ports-"))
DATA = TMP / "data"
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_SEARXNG_URL", "LOKI_ACESTEP_URL", "LOKI_ACESTEP_KEY", "LOKI_TTS"):
    os.environ.pop(_k, None)

import deep_research  # noqa: E402
import edit_blocks  # noqa: E402
import file_editor  # noqa: E402
import image_prompt  # noqa: E402
import music  # noqa: E402
import reflexion  # noqa: E402
import repo_map  # noqa: E402
import rewoo  # noqa: E402
import structured  # noqa: E402
import tool_select  # noqa: E402
import voice  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title):
    print("\n== %s" % title)


def run(coro):
    return asyncio.run(coro)


# =========================================================================== repo map (aider)
section("repo map (aider)")
proj = TMP / "proj"
(proj / "pkg").mkdir(parents=True)
(proj / "node_modules" / "x").mkdir(parents=True)
(proj / "README.md").write_text("# demo\n", encoding="utf-8")
(proj / "pkg" / "store.py").write_text(
    "MAX_ITEMS = 10\n\n\nclass InventoryStore:\n    def add_item(self, name):\n        return name\n\n\n"
    "def load_inventory_file(path):\n    return InventoryStore()\n", encoding="utf-8")
(proj / "pkg" / "app.py").write_text(
    "import store\n\n\ndef main():\n    s = store.load_inventory_file('a')\n    s.add_item('x')\n"
    "    return store.MAX_ITEMS\n", encoding="utf-8")
(proj / "pkg" / "cli.py").write_text(
    "import store\n\n\ndef run_cli():\n    return store.load_inventory_file('b')\n", encoding="utf-8")
(proj / "web.js").write_text(
    "export function renderInventoryPanel(items) {\n  return items.length;\n}\n"
    "const fetchInventory = async (url) => fetch(url);\nclass PanelView {\n  draw(ctx) {\n    return 1;\n  }\n}\n"
    "const label = (x + 1);\n", encoding="utf-8")
(proj / "node_modules" / "x" / "skip.js").write_text("function shouldNotAppear() {}\n", encoding="utf-8")

py_tags = repo_map.file_tags("pkg/store.py", (proj / "pkg" / "store.py").read_text())
defs = {t.name for t in py_tags if t.kind == "def"}
check("python defs from ast (class, method, function, CONSTANT)",
      {"InventoryStore", "add_item", "load_inventory_file", "MAX_ITEMS"} <= defs, defs)
app_tags = repo_map.file_tags("pkg/app.py", (proj / "pkg" / "app.py").read_text())
check("python module.attr reference keeps its qualifier",
      any(t.name == "load_inventory_file" and t.kind == "ref" and t.text == "store" for t in app_tags))
js_tags = repo_map.file_tags("web.js", (proj / "web.js").read_text())
js_defs = {t.name for t in js_tags if t.kind == "def"}
check("js defs: function, arrow const, class, method",
      {"renderInventoryPanel", "fetchInventory", "PanelView", "draw"} <= js_defs, js_defs)
check("js: `const label = (x + 1)` is not a definition", "label" not in js_defs, js_defs)
pr = repo_map.pagerank({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0, ("d", "a"): 2.0})
check("pagerank sums to 1", abs(sum(pr.values()) - 1.0) < 1e-6, pr)
check("pagerank: a node nobody links to ranks lowest", min(pr, key=pr.get) == "d", pr)
prp = repo_map.pagerank({("a", "b"): 1.0, ("b", "a"): 1.0, ("c", "a"): 1.0}, {"c": 1.0})
check("personalization pulls rank toward its node", prp["c"] > repo_map.pagerank(
    {("a", "b"): 1.0, ("b", "a"): 1.0, ("c", "a"): 1.0})["c"], prp)
# source_files walks the RESOLVED root (so a symlinked temp dir cannot walk in circles), so the
# caller must resolve its own root too: on macOS /tmp is /private/tmp and the bare path is not a
# prefix of the paths that come back. build() does exactly this.
proj_res = proj.resolve()
files = [p.relative_to(proj_res).as_posix() for p in repo_map.source_files(proj)]
check("source files skip node_modules", not any("node_modules" in f for f in files) and "pkg/store.py" in files, files)
m = repo_map.build(proj, focus="", max_chars=2000)
check("map lists the definitions other files use", "pkg/store.py:" in m and "def load_inventory_file" in m, m)
check("map shows README (important file)", "README.md" in m, m)
check("map never shows skipped folders", "shouldNotAppear" not in m)
mf = repo_map.build(proj, focus="where is renderInventoryPanel drawn", max_chars=200)
check("focus: the named symbol comes first even in a tiny budget", "renderInventoryPanel" in mf, mf)
small = repo_map.build(proj, focus="", max_chars=120)
check("budget is respected (within aider's 15%)", len(small) <= 120 * 1.15 + 1, len(small))
chat = repo_map.build(proj, focus="", chat_files=["pkg/store.py"], max_chars=2000)
check("files already in the chat are left out of the map", "pkg/store.py" not in chat, chat)
(TMP / "empty-proj").mkdir()
check("an empty folder says so", repo_map.build(TMP / "empty-proj", max_chars=500) == "(no source files found)")

# =========================================================================== edit blocks (aider)
section("SEARCH/REPLACE edit blocks (aider)")
ews = TMP / "ews"
ews.mkdir()


def res(name):
    p = (ews / name).resolve()
    if ews.resolve() not in p.parents:
        raise ValueError("path escapes workspace: %s" % name)
    return p


(ews / "a.py").write_text("def f():\n    x = 1\n    return x\n", encoding="utf-8")
blocks = edit_blocks.parse("Here is the change:\n\na.py\n```python\n<<<<<<< SEARCH\n    x = 1\n=======\n"
                           "    x = 2\n>>>>>>> REPLACE\n```\n")
check("parse: filename above the fence", blocks == [("a.py", "    x = 1\n", "    x = 2\n")], blocks)
out = edit_blocks.apply("a.py\n<<<<<<< SEARCH\n    x = 1\n=======\n    x = 2\n>>>>>>> REPLACE\n", res)
check("exact match applied", out["applied"] == ["a.py"] and "x = 2" in (ews / "a.py").read_text(), out)
out = edit_blocks.apply("a.py\n<<<<<<< SEARCH\nx = 2\nreturn x\n=======\nx = 3\nreturn x + 1\n>>>>>>> REPLACE\n", res)
check("missing leading whitespace is restored (aider)", "    x = 3\n    return x + 1\n" in (ews / "a.py").read_text(),
      (ews / "a.py").read_text())
out = edit_blocks.apply("a.py\n<<<<<<< SEARCH\n\ndef f():\n    x = 3\n=======\ndef g():\n    x = 3\n>>>>>>> REPLACE\n",
                        res)
check("a spurious first blank SEARCH line is ignored", "def g():" in (ews / "a.py").read_text(), out)
(ews / "b.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")
out = edit_blocks.apply("b.py\n<<<<<<< SEARCH\na = 1\n...\nd = 4\n=======\na = 10\n...\nd = 40\n>>>>>>> REPLACE\n", res)
check("... elision edits both ends", (ews / "b.py").read_text() == "a = 10\nb = 2\nc = 3\nd = 40\n",
      (ews / "b.py").read_text())
out = edit_blocks.apply("new/c.txt\n<<<<<<< SEARCH\n=======\nhello\n>>>>>>> REPLACE\n", res)
check("empty SEARCH creates a new file", (ews / "new" / "c.txt").read_text() == "hello\n" and out["created"], out)
out = edit_blocks.apply("b.py\n<<<<<<< SEARCH\na = 10\nb = 2\nc = 33\n=======\nzzz\n>>>>>>> REPLACE\n\n"
                        "a.py\n<<<<<<< SEARCH\n    x = 3\n=======\n    x = 4\n>>>>>>> REPLACE\n", res)
check("failed block reported with did-you-mean; the good block still applied",
      out["failed"] and "Did you mean" in out["report"] and "do not resend" in out["report"]
      and "x = 4" in (ews / "a.py").read_text() and not out["report"].startswith("error"), out["report"])
out = edit_blocks.apply("b.py\n<<<<<<< SEARCH\nnot there at all\n=======\nq\n>>>>>>> REPLACE\n", res)
check("all blocks failing -> the report starts with error", out["report"].startswith("error"), out["report"])
out = edit_blocks.apply("../escape.py\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE\n", res)
check("a path outside the workspace is refused", out["failed"] and not (TMP / "escape.py").exists(), out)
out = edit_blocks.apply("a.py\n<<<<<<< SEARCH\nx\n>>>>>>> REPLACE\n", res)
check("malformed block -> format help", out["report"].startswith("error") and "SEARCH/REPLACE" in out["report"], out)
check("no blocks -> format help", edit_blocks.apply("just text", res)["report"].startswith("error: no SEARCH"))
(ews / "w.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
out = edit_blocks.apply("w.txt\n<<<<<<< SEARCH\ntwo\n=======\nTWO\n>>>>>>> REPLACE\n", res)
check("CRLF file stays CRLF", (ews / "w.txt").read_bytes() == b"one\r\nTWO\r\nthree\r\n", (ews / "w.txt").read_bytes())
undo = file_editor.undo(ews / "w.txt", label="w.txt")
check("undo_edit reverts an apply_edits change", (ews / "w.txt").read_bytes() == b"one\r\ntwo\r\nthree\r\n", undo)
out = edit_blocks.apply("a.py\n<<<<<<< SEARCH\n    x = 4\n=======\n    x = 5\n>>>>>>> REPLACE\n"
                        "<<<<<<< SEARCH\n    x = 5\n=======\n    x = 6\n>>>>>>> REPLACE\n", res)
check("two blocks on one file apply in order (second reuses the filename)",
      "x = 6" in (ews / "a.py").read_text() and len(out["applied"]) == 2, out)
check("REPLACE already present is pointed out",
      "already in" in edit_blocks.apply("a.py\n<<<<<<< SEARCH\nnope\n=======\n    x = 6\n>>>>>>> REPLACE\n", res)["report"])

# =========================================================================== tool retrieval (bigtool)
section("tool retrieval (langgraph-bigtool)")


def sch(name, desc, props=()):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": {p: {} for p in props}}}}


TOOLS = [sch("make_music", "Make a song or a piece of music (ACE-Step).", ["prompt", "lyrics"]),
         sch("web_search", "Search the web: titles, links and snippets.", ["query"]),
         sch("speak", "Read text aloud into an audio file with a voice.", ["text"]),
         sch("read_file", "Read one file.", ["filename"]),
         sch("generate_media", "Make an image or video from a prompt.", ["prompt", "kind"]),
         sch("repo_map", "A map of the code: files, classes and functions.", ["focus"])]
check("'make a song' finds make_music", tool_select.rank("make a song for my mum", TOOLS)[0][0] == "make_music",
      tool_select.rank("make a song for my mum", TOOLS))
check("'look something up on the internet' finds web_search",
      tool_select.rank("look something up on the internet", TOOLS)[0][0] == "web_search")
check("'read this aloud' finds speak", tool_select.rank("read this aloud please", TOOLS)[0][0] == "speak")
check("'draw a picture of a fox' finds generate_media",
      tool_select.rank("draw a picture of a fox", TOOLS)[0][0] == "generate_media")
check("'understand this codebase' finds repo_map",
      tool_select.rank("understand this codebase", TOOLS)[0][0] == "repo_map")
check("snake_case and camelCase split into words", tool_select.words("findTools make_music") ==
      ["find", "tool", "make", "music"], tool_select.words("findTools make_music"))
check("nothing matching -> empty", tool_select.rank("zzqx", TOOLS) == [])
prio = ["list_tree", "read_file", "find_tools", "run_command"]
unlocked: list = []
tool_select.promote(prio, ["make_music", "speak"], unlocked=unlocked)
check("found tools go right after find_tools", prio[:5] == ["list_tree", "read_file", "find_tools", "make_music",
                                                              "speak"], prio)
tool_select.promote(prio, ["read_file"], unlocked=unlocked)
check("a core tool is not moved", prio.index("read_file") == 1 and "read_file" not in unlocked, prio)
tool_select.promote(prio, ["a", "b", "c", "d", "e"], unlocked=unlocked, keep=6)
check("at most 6 found tools stay; the oldest goes", len(unlocked) == 6 and "make_music" not in prio, (prio, unlocked))
check("describe shows args, required marked", "make_music(prompt, lyrics)" in tool_select.describe(TOOLS, ["make_music"]))

# =========================================================================== structured (instructor)
section("structured output (instructor)")
S = {"type": "object", "properties": {"name": {"type": "string", "minLength": 1},
                                      "age": {"type": "integer", "minimum": 0},
                                      "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                                      "kind": {"enum": ["cat", "dog"]}},
     "required": ["name", "age"], "additionalProperties": False}
check("valid object -> no errors", structured.validate(S, {"name": "Rex", "age": 3, "kind": "dog"}) == [])
errs = structured.validate(S, {"name": "", "age": "3", "tags": ["a", 1, "b", "c"], "x": 1})
check("errors: minLength, type, items, maxItems, additionalProperties",
      len(errs) == 5 and any("$.age should be integer" in e for e in errs) and any("$.tags[1]" in e for e in errs)
      and any("not allowed: x" in e for e in errs), errs)
check("missing required named", structured.validate(S, {"name": "a"}) == ["$.age is required but missing"])
check("bool is not an integer", structured.validate({"type": "integer"}, True) != [])
check("anyOf: one shape matches", structured.validate({"anyOf": [{"type": "string"}, {"type": "integer"}]}, 4) == [])
check("parse: fenced JSON with trailing comma", structured.parse("ok:\n```json\n{\"a\": 1,}\n```") == {"a": 1})
check("parse: thinking removed, object found in prose",
      structured.parse("<think>{no}</think>Here: {\"b\": 2} thanks") == {"b": 2})
check("parse: array", structured.parse("[1, 2]") == [1, 2])
check("parse: no JSON -> None", structured.parse("sorry, no") is None)
check("strip_thinking: cut-off thought dropped", structured.strip_thinking("answer<think>never closed") == "answer")
rf = structured.response_format(S)
check("response_format is json_schema with the schema", rf["type"] == "json_schema" and rf["json_schema"]["schema"] == S)
replies = iter(["{\"name\": \"Rex\", \"age\": \"three\"}", "```json\n{\"name\": \"Rex\", \"age\": 3}\n```"])
seen_prompts: list = []


async def fake_struct_ask(prompt, schema=None):
    seen_prompts.append((prompt, schema))
    return next(replies)


out = run(structured.ask_structured(fake_struct_ask, "Who is the dog?", S))
check("re-ask fixes an invalid answer on the second try", out["ok"] and out["value"] == {"name": "Rex", "age": 3}
      and out["attempts"] == 2, out)
check("the re-ask carries instructor's message and the errors",
      "Recall the function correctly" in seen_prompts[1][0] and "$.age should be integer" in seen_prompts[1][0])
check("the schema is passed to the model call (constrained decoding)", seen_prompts[0][1] == S)


async def never_json(prompt, schema=None):
    return "I think the dog is Rex."


out = run(structured.ask_structured(never_json, "x", S, retries=1))
check("gives up after retries with the reason", not out["ok"] and out["attempts"] == 2
      and "not JSON" in out["errors"][0], out)

# =========================================================================== ReWOO
section("ReWOO plan-work-solve")
plan = ("Plan: find it\n#E1 = search_files[def read_web]\n**Plan:** read it\n"
        "#E2 = read_file[{\"filename\": \"engine/web_reader.py\", \"start_line\": 1}]\n"
        "Plan: answer\n#E3 = LLM[What does it remove? Given context: #E1, #E2]\n#E4: 42\n")
steps = rewoo.parse_plan(plan)
check("plan parsed: 4 steps with tools and inputs",
      [s["tool"] for s in steps] == ["search_files", "read_file", "LLM", ""] and steps[0]["input"] == "def read_web"
      and steps[1]["plan"] == "read it", steps)
check("#E10 is substituted before #E1", rewoo.substitute("#E10 and #E1", {"#E1": "one", "#E10": "ten"})
      == "[ten] and [one]")
check("JSON input -> named arguments", rewoo.arguments('{"filename": "a.py", "start_line": 2}', {"arg": "filename"})
      == {"filename": "a.py", "start_line": 2})
check("plain input -> the first argument (quotes trimmed)", rewoo.arguments('"x.py"', {"arg": "filename"})
      == {"filename": "x.py"})
check("planner prompt lists the tools and LLM", "search_files[input]" in rewoo.planner_prompt("t", {
    "search_files": {"description": "d", "arg": "pattern"}}) and "LLM[input]" in rewoo.planner_prompt("t", {}))
calls: list = []
asks: list = []


async def fake_rewoo_ask(prompt):
    asks.append(prompt)
    if prompt.startswith(rewoo.PLANNER_PREFIX):
        return ("Plan: search\n#E1 = search_files[read_web]\nPlan: read\n#E2 = read_file[#E1]\n"
                "Plan: bad tool\n#E3 = rm_rf[/]\nPlan: think\n#E4 = LLM[Summarize #E2]")
    if prompt.startswith(rewoo.SOLVER_PREFIX):
        return "It strips hidden text."
    return "summary of [" + prompt[-30:]


async def fake_rewoo_tool(name, args):
    calls.append((name, args))
    if name == "search_files":
        return "web_reader.py"
    raise RuntimeError("disk on fire")


workers = {"search_files": {"description": "search", "arg": "pattern"},
           "read_file": {"description": "read", "arg": "filename"}}
out = run(rewoo.run("What does read_web remove?", fake_rewoo_ask, workers, fake_rewoo_tool))
check("the answer comes from the solver", out["answer"] == "It strips hidden text.", out)
check("#E1's result is fed into #E2's input", calls[1] == ("read_file", {"filename": "[web_reader.py]"}), calls)
check("a failing tool becomes evidence, not a crash", out["steps"][1]["result"].startswith("error: disk on fire"))
check("a tool not offered is never run", "rm_rf" not in [c[0] for c in calls]
      and "not an available tool" in out["steps"][2]["result"])
check("the solver sees every step's evidence", "Evidence:" in asks[-1] and "web_reader.py" in asks[-1])
check("3 model calls + 1 LLM step only (no per-step re-reading)", len(asks) == 3, len(asks))


async def no_plan_ask(prompt):
    return "I would just answer: 7." if prompt.startswith(rewoo.PLANNER_PREFIX) else "7"


out = run(rewoo.run("3+4?", no_plan_ask, workers, fake_rewoo_tool))
check("no plan -> a direct answer", out["answer"] == "7" and out["steps"] == [], out)

# =========================================================================== Reflexion
section("Reflexion")
p = reflexion.reflection_prompt("fix the test", "I edited a.py" * 2, "AssertionError: 2 != 3")
check("prompt has Reflexion's instruction, the trial and the feedback",
      "self reflection" in p and "(END PREVIOUS TRIAL)" in p and "AssertionError" in p)
check("a long attempt is cut in the middle", "left out" in reflexion.truncate_attempt("x" * 20000, 1000)
      and len(reflexion.truncate_attempt("x" * 20000, 1000)) < 1200)
f = reflexion.format_reflections(["a", "b", "c", "d"])
check("at most 3 reflections, newest kept, under the header", f.startswith(reflexion.REFLECTION_HEADER)
      and "- b\n- c\n- d" in f and "- a" not in f, f)
check("no reflections -> nothing", reflexion.format_reflections([]) == "")
learned: list = []


async def reflect_ask(prompt):
    return "Reflection: I assumed the off-by-one was in the loop. Plan: read the test first, then fix the range."


out = run(reflexion.reflect("fix the test", "attempt", "2 != 3", reflect_ask,
                            lambda text, tags: (learned.append((text, tags)) or {"id": "m1"})))
check("reflection cleaned and stored with the reflexion tag", out["ok"] and out["reflection"].startswith("I assumed")
      and out["stored"] == "m1" and learned[0][1] == ["reflexion"] and "fix the test" in learned[0][0], out)
seen_reflections: list = []


async def attempt_fn(task, refl):
    seen_reflections.append(refl)
    return "good" if refl else "bad"


async def evaluate_fn(result):
    return (result == "good", "it was bad")


out = run(reflexion.trial_loop("t", attempt_fn, evaluate_fn, reflect_ask, max_trials=3))
check("trial loop: fails, reflects, succeeds on trial 2 with the reflection",
      out["ok"] and out["trials"] == 2 and seen_reflections[0] == "" and "I assumed" in seen_reflections[1], out)


async def always_bad(task, refl):
    return "bad"


out = run(reflexion.trial_loop("t", always_bad, evaluate_fn, reflect_ask, max_trials=2))
check("trial loop gives up after max_trials", not out["ok"] and out["trials"] == 2 and len(out["reflections"]) == 1)

# =========================================================================== deep research (STORM)
section("deep research (STORM) + keyless search")
DDG = """<div class="result"><h2 class="result__title"><a rel="nofollow" class="result__a"
href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ffox&amp;rut=abc">Red <b>fox</b> facts</a></h2>
<a class="result__snippet" href="x">The red fox is the <b>largest</b> true fox.</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></div>
<div class="result"><a class="result__a" href="https://other.org/a">Other</a>
<a class="result__snippet">Second.</a></div>
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ffox">dup</a></div>"""
r = deep_research.parse_ddg(DDG)
check("DuckDuckGo: uddg link decoded, title and snippet read",
      r[0] == {"title": "Red fox facts", "url": "https://example.com/fox",
               "snippet": "The red fox is the largest true fox."}, r)
check("DuckDuckGo: ads and duplicates dropped", [x["url"] for x in r] == ["https://example.com/fox",
                                                                          "https://other.org/a"], r)
sx = deep_research.parse_searxng(json.dumps({"results": [{"title": "T", "url": "https://t.io", "content": "c"},
                                                         {"title": "bad", "url": "ftp://x"}]}))
check("SearXNG JSON parsed", sx == [{"title": "T", "url": "https://t.io", "snippet": "c"}], sx)
sent: list = []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req, timeout=0):
    sent.append(req)
    if "searx" in req.full_url:
        return _Resp(json.dumps({"results": [{"title": "S", "url": "https://s.io", "content": "x"}]}).encode())
    return _Resp(DDG.encode())


check("search: DuckDuckGo by POST, no key", deep_research.search("red fox", opener=fake_open, env={})[0]["url"]
      == "https://example.com/fox" and sent[-1].full_url.startswith("https://html.duckduckgo.com/html")
      and b"q=red+fox" in sent[-1].data)
check("search: SearXNG when LOKI_SEARXNG_URL is set",
      deep_research.search("fox", opener=fake_open, env={"LOKI_SEARXNG_URL": "http://searx.lan/"})[0]["url"]
      == "https://s.io" and "format=json" in sent[-1].full_url)
check("persona list always starts with the basic fact writer",
      deep_research.parse_personas("1. Ecologist: habitats\n2. Historian: folklore\n3. Extra: x", 3)
      == [deep_research.BASIC_PERSONA, "Ecologist: habitats", "Historian: folklore"])
check("outline: sections only, no References",
      deep_research.parse_outline("# Habitat\n## Sub\n# Diet\n# References", 5) == ["Habitat", "Diet"])
research_asks: list = []


async def r_ask(prompt):
    research_asks.append(prompt)
    if prompt.startswith("You need to select a group of editors"):
        return "1. Ecologist: where foxes live"
    if "Write 2 questions" in prompt:
        return "- Where do red foxes live?\n- What do red foxes eat?"
    if prompt.startswith("You want to answer the question using a web search"):
        return "- red fox habitat\n- red fox diet"
    if prompt.startswith("You are an expert"):
        return "Red foxes live almost everywhere [1] and eat rodents [2]."
    if prompt.startswith("Write an outline"):
        return "# Habitat\n# Diet"
    if prompt.startswith("Write a report section"):
        sec = prompt.split("The section you need to write: ")[1].split("\n")[0]
        return "# %s\n\nText about %s [1][2][9]." % (sec, sec.lower())
    return ""


async def r_search(query):
    return [{"title": "Fox " + query, "url": "https://ex.com/" + query.replace(" ", "-"), "snippet": "snip"},
            {"title": "Shared", "url": "https://ex.com/shared", "snippet": "shared"}]


reads: list = []


async def r_read(url):
    reads.append(url)
    return "error: blocked" if url.endswith("diet") else "Page text of " + url


out = run(deep_research.run("red fox", r_ask, r_search, r_read, depth=1))
rep = out["report"]
check("report: title, sections from the outline, references", rep.startswith("# red fox") and "## Habitat" in rep
      and "## Diet" in rep and "## References" in rep, rep[:400])
check("each source read once and numbered once", len(reads) == len(set(reads)) and
      rep.count("https://ex.com/shared") == 1, reads)
check("an unreadable page falls back to its snippet", any(s["text"] == "snip" for s in out["sources"]))
check("citations: known ones listed, an invented [9] flagged", 9 in out["unknown_citations"] and 1 in out["cited"], out)
check("questions from both editors (basic fact writer + ecologist)", len(out["questions"]) == 2
      and sum(1 for a in research_asks if "Write 2 questions" in a) == 2, out["questions"])
check("depth 1 keeps to at most 6 sources", len(out["sources"]) <= 6)


async def nothing_search(query):
    return []


out = run(deep_research.run("zz", r_ask, nothing_search, r_read))
check("no sources -> no report and a reason", out["report"] == "" and "no sources" in out["error"])

# =========================================================================== image prompts (Fooocus)
section("image prompt styles + expansion (Fooocus)")
st = image_prompt.styles()
check("the Fooocus/SAI styles load", len(st) >= 20 and "pixel art" in st and "cinematic" in st, sorted(st))
pos, neg = image_prompt.apply_style("a red fox", "pixel art")
check("pixel art style wraps the prompt", pos.startswith("pixel-art a red fox") and "8-bit" in pos, pos)
check("style negative prompt returned", "photo" in neg.lower() or neg != "", neg)
check("style names are forgiving (case, dash, underscore)", image_prompt.find_style("Pixel_Art")["name"] == "pixel art")
check("unknown style -> prompt unchanged", image_prompt.apply_style("a fox ,", "nope") == ("a fox", ""))
a1, a2 = image_prompt.expand_offline("a fox", 7), image_prompt.expand_offline("a fox", 7)
check("offline expansion is seeded (same seed, same words)", a1 == a2 and a1.startswith("a fox, "), a1)
check("offline words come from Fooocus' positive vocabulary",
      all(w.strip() in image_prompt.POSITIVE_WORDS for w in a1.split(",")[1:]), a1)
check("safe_str (Fooocus)", image_prompt.safe_str("  a  fox,. ") == "a fox")


async def img_ask(prompt):
    return '"A small red fox curled up asleep in soft studio light, warm rim light, shallow depth of field, cozy"'


out = run(image_prompt.enhance("a sleeping fox", "cinematic", ask=img_ask))
check("model expansion used, then styled", out["source"] == "model" and out["prompt"].startswith(
    "cinematic film still A small red fox") and out["negative"], out)


async def bad_img_ask(prompt):
    return "Sorry"


out = run(image_prompt.enhance("a fox", "", ask=bad_img_ask, seed=1))
check("a useless model reply -> offline expansion", out["source"] == "offline" and out["prompt"].startswith("a fox, "))
check("no idea -> error", not run(image_prompt.enhance("", "")).get("ok"))

# =========================================================================== music (ACE-Step)
section("music (ACE-Step 1.5 client)")


class FakeAce:
    def __init__(self, fail=False, polls=1):
        self.reqs, self.fail, self.polls = [], fail, polls

    def __call__(self, req, timeout=0):
        self.reqs.append(req)
        url = req.full_url
        if url.endswith("/release_task"):
            return _Resp(json.dumps({"data": {"task_id": "t1", "status": "queued"}, "code": 200}).encode())
        if url.endswith("/query_result"):
            self.polls -= 1
            if self.polls >= 0:
                return _Resp(json.dumps({"data": [{"task_id": "t1", "status": 0, "result": "[]"}]}).encode())
            status = 2 if self.fail else 1
            return _Resp(json.dumps({"data": [{"task_id": "t1", "status": status, "result": json.dumps(
                [{"file": "/outputs/t1_0.mp3", "status": 1}])}]}).encode())
        if "/v1/audio?" in url:
            return _Resp(b"ID3fakeaudio")
        raise AssertionError(url)


ace = FakeAce(polls=2)
sleeps: list = []
out = music.make("lofi hip hop, rain, piano", TMP / "music", duration=30, opener=ace, sleep=sleeps.append,
                 env={"LOKI_ACESTEP_KEY": "k"})
check("song submitted, polled until done, downloaded", out["ok"] and out["files"][0].read_bytes() == b"ID3fakeaudio"
      and len(sleeps) == 2, out)
body = json.loads(ace.reqs[0].data)
check("task body: prompt, text2music, duration", body["prompt"] == "lofi hip hop, rain, piano"
      and body["task_type"] == "text2music" and body["audio_duration"] == 30.0)
check("download uses /v1/audio?path=", "path=%2Foutputs%2Ft1_0.mp3" in ace.reqs[-1].full_url, ace.reqs[-1].full_url)
check("Bearer key sent when set", ace.reqs[0].get_header("Authorization") == "Bearer k")
check("duration clamped, seed fixed", music.task_body("x", duration=999, seed=5)["audio_duration"] == 240.0
      and music.task_body("x", seed=5)["use_random_seed"] is False)
out = music.make("x", TMP / "music", opener=FakeAce(fail=True, polls=0), sleep=lambda s: None, env={})
check("a failed task says so", not out["ok"] and "could not make it" in out["error"], out)


def refused(req, timeout=0):
    raise urllib.error.URLError("Connection refused")


out = music.make("x", TMP / "music", opener=refused, env={})
check("ACE-Step not running -> how to install and start it", not out["ok"] and "uv run acestep-api" in out["error"])
check("no prompt and no lyrics -> error", not music.make("", TMP / "music", opener=refused, env={})["ok"])
check("LOKI_ACESTEP_URL points at another machine", music.base_url({"LOKI_ACESTEP_URL": "http://pc:8001/"})
      == "http://pc:8001")
clock = iter([0, 0, 1000, 2000])
out = music.make("x", TMP / "music", opener=FakeAce(polls=99), sleep=lambda s: None, clock=lambda: next(clock),
                 env={}, timeout=10)
check("a stuck task times out", not out["ok"] and "longer than" in out["error"], out)

# =========================================================================== voice (Kokoro / OS)
section("voice (Kokoro, say, SAPI, espeak)")
written: dict = {}


class FakePipeline:
    def __init__(self, lang_code="a"):
        written["lang"] = lang_code

    def __call__(self, text, voice=""):
        written["voice"] = voice
        yield ("g", "p", [0.1, 0.2])
        yield ("g", "p", [0.3])


fake_sf = types.SimpleNamespace(write=lambda path, data, rate: (written.update(path=path, n=len(data), rate=rate),
                                                                 Path(path).write_bytes(b"RIFF")))
out = voice.speak("Hello there", TMP / "voice", "bf_emma", kokoro_loader=lambda: (FakePipeline, fake_sf))
check("Kokoro: chunks joined, 24 kHz wav, British voice -> lang b", out["ok"] and out["engine"] == "kokoro"
      and written["rate"] == 24000 and written["n"] == 3 and written["lang"] == "b"
      and str(out["file"]).endswith(".wav"), (out, written))
ran: list = []


def fake_runner(argv, **kw):
    ran.append((argv, kw))
    if kw["env"].get("LOKI_TTS_OUT"):
        out_path = kw["env"]["LOKI_TTS_OUT"]          # Windows: the path arrives by environment
    elif "-o" in argv:
        out_path = argv[argv.index("-o") + 1]         # macOS say
    else:
        out_path = argv[argv.index("-w") + 1]         # espeak
    Path(out_path).write_bytes(b"audio")
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


out = voice.speak("Hi Mac", TMP / "voice", "Samantha", kokoro_loader=lambda: None, runner=fake_runner,
                  platform="darwin")
argv = ran[-1][0]
check("macOS: say -v voice -o file.aiff -f textfile (text never in argv)", out["ok"] and argv[0] == "say"
      and argv[1:3] == ["-v", "Samantha"] and str(out["file"]).endswith(".aiff") and "Hi Mac" not in argv, argv)
out = voice.speak("Hi PC; rm -rf / $(x)", TMP / "voice", "", kokoro_loader=lambda: None, runner=fake_runner,
                  platform="win32", which=lambda n: "C:/ps/powershell.exe" if n == "powershell" else None)
argv, kw = ran[-1]
check("Windows: PowerShell SAPI, text and path only via env vars", out["ok"] and argv[-1] == voice.PS_SCRIPT
      and "LOKI_TTS_IN" in kw["env"] and "Hi PC" not in " ".join(argv) and str(out["file"]).endswith(".wav"), argv)
out = voice.speak("Hi Linux", TMP / "voice", "", kokoro_loader=lambda: None, runner=fake_runner, platform="linux",
                  which=lambda n: "/usr/bin/espeak-ng" if n == "espeak-ng" else None)
check("Linux: espeak-ng -w file -f textfile", out["ok"] and ran[-1][0][0] == "/usr/bin/espeak-ng")
out = voice.speak("Hi", TMP / "voice", "", kokoro_loader=lambda: None, runner=fake_runner, platform="linux",
                  which=lambda n: None)
check("no voice anywhere -> how to get one", not out["ok"] and "pip install kokoro" in out["error"])
check("no temp text files left behind", not list(Path(tempfile.gettempdir()).glob("loki-tts-*.txt")))
out = voice.speak("Hi", TMP / "voice", "", kokoro_loader=lambda: None, platform="darwin",
                  runner=lambda argv, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="no voice"))
check("a failing OS voice says why", not out["ok"] and "no voice" in out["error"])

# =========================================================================== registered in loki.py
section("the tools in LOKI (loki.py)")
import loki  # noqa: E402
import memory_core  # noqa: E402

NEW = ["repo_map", "apply_edits", "find_tools", "plan_and_solve", "reflect", "extract_structured", "web_search",
       "deep_research", "enhance_image_prompt", "make_music", "speak"]
names = {t["function"]["name"] for t in loki.TOOL_SCHEMAS}
check("every new tool: function, schema, offered to the model",
      all(n in loki.LOCAL_TOOLS and n in names and n in loki.MODEL_TOOL_NAMES for n in NEW),
      [n for n in NEW if not (n in loki.LOCAL_TOOLS and n in names and n in loki.MODEL_TOOL_NAMES)])
check("every new tool sits in a settings category",
      all(any(n in members for members in loki.TOOL_CATEGORIES.values()) for n in NEW))
check("no duplicate schemas", len([t["function"]["name"] for t in loki.TOOL_SCHEMAS]) == len(names))
check("tools that write files count as modifying (Plan mode leaves them out)",
      {"apply_edits", "deep_research", "make_music", "speak"} <= loki.MODIFYING)
check("find_tools and repo_map are in a local model's core list",
      loki.LOCAL_TOOL_PRIORITY.index("find_tools") < 10 and "repo_map" in loki.LOCAL_TOOL_PRIORITY)


async def fake_port_ask(prompt, system="", schema=None, max_tokens=0):
    if prompt.startswith(rewoo.PLANNER_PREFIX):
        return "Plan: read it\n#E1 = read_file[notes.txt]\nPlan: escape\n#E2 = read_file[../../etc/passwd]"
    if prompt.startswith(rewoo.SOLVER_PREFIX):
        return "The note says: " + ("bananas" if "bananas" in prompt else "nothing")
    if "Reflection:" in prompt:
        return "I edited the wrong file. Plan: run search_files for the function before editing."
    if "JSON Schema" in prompt:
        return '{"city": "Paris"}'
    if "image generator" in prompt:
        return "a small red fox in a snowy pine forest at dawn, soft golden light, crisp detail, cozy mood"
    return "ok"


loki._port_ask = fake_port_ask
loki.AGENT_MODE = "build"
(WS / "notes.txt").write_text("buy bananas\n", encoding="utf-8")
(WS / "src").mkdir(exist_ok=True)
(WS / "src" / "game.py").write_text("def spawn_fox_family(n):\n    return n\n\n\ndef tick():\n"
                                    "    return spawn_fox_family(2)\n", encoding="utf-8")
out = run(loki.call_tool("plan_and_solve", {"task": "What do my notes say?"}))
check("plan_and_solve: runs read_file through the policy, answers from it", out.startswith("The note says: bananas")
      and "#E1 = read_file" in out, out)
check("plan_and_solve: a path outside the workspace is refused by the policy, not read",
      "DENIED by Loki's policy" in out and "root:" not in out, out)
out = run(loki.call_tool("repo_map", {"focus": "spawn_fox_family"}))
check("repo_map tool maps the workspace", "src/game.py" in out and "spawn_fox_family" in out, out)
out = run(loki.call_tool("apply_edits", {"blocks": "src/game.py\n<<<<<<< SEARCH\n    return n\n=======\n"
                                                   "    return n * 2\n>>>>>>> REPLACE\n"}))
check("apply_edits tool edits a workspace file", "applied 1 block" in out
      and "n * 2" in (WS / "src" / "game.py").read_text(), out)
out = run(loki.call_tool("undo_edit", {"filename": "src/game.py"}))
check("undo_edit reverts it", "n * 2" not in (WS / "src" / "game.py").read_text(), out)
out = run(loki.call_tool("apply_edits", {"blocks": "../outside.txt\n<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE\n"}))
check("apply_edits refuses a path outside the workspace", out.startswith("error") and
      not (WS.parent / "outside.txt").exists(), out)
out = run(loki.call_tool("reflect", {"task": "rename the fox spawner", "attempt": "edited main.py",
                                     "feedback": "NameError"}))
recalled = memory_core.recall("rename the fox spawner", root=loki.DATA_DIR)
check("reflect: lesson written and kept as an episodic memory", "edited the wrong file" in out
      and "edited the wrong file" in (recalled.get("evidence") or ""), (out, recalled))
out = run(loki.call_tool("extract_structured", {"text": "I live in Paris.", "schema": json.dumps(
    {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]})}))
check("extract_structured returns validated JSON", json.loads(out) == {"city": "Paris"}, out)
check("extract_structured without a schema explains", run(loki.call_tool("extract_structured", {"text": "x"}))
      .startswith("error"))
out = run(loki.call_tool("enhance_image_prompt", {"prompt": "a fox", "style": "pixel art"}))
check("enhance_image_prompt: model prompt in the pixel art style", out.startswith("prompt: pixel-art a small red fox")
      and "negative:" in out, out)
check("enhance_image_prompt style=list", "pixel art" in run(loki.call_tool("enhance_image_prompt",
                                                                          {"prompt": "x", "style": "list"})))
deep_research.search = lambda query, limit=8, opener=None, env=None: [
    {"title": "Fox page", "url": "https://foxes.example/" + query.replace(" ", "-")[:20], "snippet": "foxes"}]
loki.read_web = lambda url, max_chars=20000: "Foxes are small omnivores."
_orig_port = loki._port_ask
loki._port_ask = r_ask
out = run(loki.call_tool("deep_research", {"question": "red fox", "depth": 1}))
saved = list((WS / "research").glob("*.md"))
check("deep_research writes research/<date>-<slug>.md with references", saved and "## References" in
      saved[0].read_text() and out.startswith("wrote research/"), out[:300])
loki._port_ask = _orig_port
check("one web_search tool (the harvest's: SearxNG/DuckDuckGo/arXiv), not two", list(loki.LOCAL_TOOLS).count("web_search") == 1
      and "def _port_web_search" not in (REPO / "engine" / "loki.py").read_text(encoding="utf-8"))
music.make = lambda prompt, out_dir, *a, **k: {"ok": True, "files": [Path(out_dir) / "x.mp3"]}
check("make_music reports the workspace path", run(loki.call_tool("make_music", {"prompt": "jazz"}))
      == "made music/x.mp3")
voice.speak = lambda text, out_dir, v="": {"ok": True, "file": Path(out_dir) / "s.wav", "engine": "kokoro"}
check("speak reports engine and path", run(loki.call_tool("speak", {"text": "hi"})) == "spoke it with kokoro: voice/s.wav")

# find_tools: a local model does not see make_music until it asks for it
loki._is_local_model = lambda: True
before = [t["function"]["name"] for t in loki.model_tool_schemas()]
out = run(loki.call_tool("find_tools", {"query": "compose a song with lyrics"}))
after = [t["function"]["name"] for t in loki.model_tool_schemas()]
check("local model: make_music hidden at first, offered after find_tools",
      "make_music" not in before and "make_music" in after and "make_music(" in out, (before, out))
check("the local list stays within LOCAL_MAX_TOOLS", len(after) <= loki.LOCAL_MAX_TOOLS, len(after))
check("find_tools with nothing matching says so", "No tool matches" in run(loki.call_tool("find_tools",
                                                                                          {"query": "qqzzxx"})))
loki.AGENT_MODE = "plan"
plan_names = [t["function"]["name"] for t in loki.model_tool_schemas()]
check("Plan mode: apply_edits not offered, find_tools still is", "apply_edits" not in plan_names
      and "find_tools" in plan_names, plan_names)
loki.AGENT_MODE = "build"

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
