"""The owner's realistic tasks for the task-success benchmark (tools/task_bench.py).

Each task's "small" script reproduces something a small local model really did in the PC's
job logs (session 27): empty and <think>-only replies, tool calls written as ```json or as
code, wrong tool and argument names, DONE before doing anything, DONE in the last line of a
long reply, BLOCKED guesses, asking a question nobody can answer, a DONE line naming a file
it never wrote, huge replies, a call cut off by the output limit, a stuck repeated call.
"cheat" scripts never do the work: the bench must score them as failures.
"""
from __future__ import annotations

import re

from .base import (Task, blocked, bounded_context, call, calls, contains, cut, done, empty, exists, final_mentions, huge, pycmd,
                   json_block, min_words, missing, py_compiles, py_text, real_picture, runs, say, slow,
                   sources, team_verified, think_only, told, unchanged, valid_json)

# ----------------------------------------------------------------------------- shared reactions


def made_file(messages: list) -> str:
    """The file a specialist reported making in the newest tool result ("made X with ...")."""
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        text = str(m.get("content") or "")
        found = re.search(r"made (\S+?) with ", text)
        if found:
            ws = re.search(r"([\w-]+/[\w.-]+)$", found.group(1).replace("\\", "/"))
            return ws.group(1) if ws else found.group(1)
        if m.get("role") == "user" and "<tool_response>" not in text and "Result of" not in text:
            return ""
    return ""


def pushed_back(messages: list) -> bool:
    """LOKI did not accept the last DONE/BLOCKED or question (a nudge, a check, a pushback)."""
    return told(messages, "premature", "not done", "does not exist", "not accepting", "did not try",
                "have not tried", "no tool", "nobody can answer", "assumption", "failed", "nothing was",
                "verification", "errors", "not actually")


# ----------------------------------------------------------------------------- fixture text

TOOL_PY = '''import sys


def main(path):
    """Print the lines of a text file in reverse order."""
    with open(path, encoding="utf-8") as handle:
        for line in reversed(handle.read().splitlines()):
            print(line)


if __name__ == "__main__":
    main(sys.argv[1])
'''

README = """# tool.py

`tool.py` prints the lines of a text file in reverse order, last line first.

## How to run it

You need Python 3. Run it with the file as its only argument:

    python tool.py notes.txt

## Example

If notes.txt holds the lines `one`, `two`, `three`, then `python tool.py notes.txt` prints
`three`, `two`, `one`, each on its own line.
"""

RAW_NOTES = """mtg 14 oct - dana, sam, lee
- decided: launch moves to 10 may (was 3 may)
- decided: keep the free tier
- sam to update the pricing page by fri
- lee to email beta users
- ?? do we need a status page
- ?? who owns support on launch day
"""

MEETING_NOTES = """# Meeting notes - 14 October

Attendees: Dana, Sam, Lee

## Decisions
- The launch moves from 3 May to 10 May.
- The free tier stays.

## Action items
- Sam: update the pricing page by Friday.
- Lee: email the beta users.

## Open questions
- Do we need a status page?
- Who owns support on launch day?
"""

COMMITS = """feat: dark mode for the dashboard
feat: export reports as CSV
feat: keyboard shortcuts
fix: crash when the report is empty
fix: wrong totals in the monthly view
"""

CHANGELOG = """# Changelog

## 1.2.0

### Added
- Dark mode for the dashboard.
- Export reports as CSV.
- Keyboard shortcuts.

### Fixed
- A crash when the report is empty.
- Wrong totals in the monthly view.
"""

EMAIL = """Subject: New launch date: 10 May

Hi Dana,

I wanted to let you know that we are moving the launch from 3 May to 10 May. The extra week
lets us finish testing so the launch goes smoothly for you and your team.

Nothing else changes on your side. I am sorry for the short notice, and I am happy to talk it
through if you have any questions.

Best regards,
The team
"""

CALC = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
TEST_CALC = ("import unittest\n\nfrom calc import add, mul\n\n\nclass CalcTest(unittest.TestCase):\n"
             "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
             "    def test_mul(self):\n        self.assertEqual(mul(2, 3), 6)\n\n\n"
             "if __name__ == \"__main__\":\n    unittest.main()\n")

TEXTUTIL = "def shout(text):\n    return text.upper() + \"!\"\n"
TEXTUTIL_BROKEN = TEXTUTIL + "\n\ndef slugify(text)\n    return \"-\".join(text.lower().split())\n"
TEXTUTIL_FIXED = TEXTUTIL + "\n\ndef slugify(text):\n    return \"-\".join(text.lower().split())\n"
TEST_TEXTUTIL = ("import unittest\n\nfrom textutil import shout, slugify\n\n\nclass TextTest(unittest.TestCase):\n"
                 "    def test_shout(self):\n        self.assertEqual(shout(\"hi\"), \"HI!\")\n\n"
                 "    def test_slugify(self):\n        self.assertEqual(slugify(\"Hello Big World\"), \"hello-big-world\")\n\n\n"
                 "if __name__ == \"__main__\":\n    unittest.main()\n")

USERS = "USERS = {1: \"ada\", 2: \"linus\"}\n\n\ndef get_usr(user_id):\n    return USERS.get(user_id, \"\")\n"
MAIN = "from app.users import get_usr\n\n\ndef greeting(user_id):\n    return \"hello \" + get_usr(user_id)\n"
TEST_APP = ("import unittest\n\nfrom app.main import greeting\nfrom app.users import get_user\n\n\n"
            "class AppTest(unittest.TestCase):\n    def test_user(self):\n        self.assertEqual(get_user(1), \"ada\")\n\n"
            "    def test_greeting(self):\n        self.assertEqual(greeting(2), \"hello linus\")\n\n\n"
            "if __name__ == \"__main__\":\n    unittest.main()\n")

WORDCOUNT = ("import sys\n\n\ndef count(path):\n    with open(path, encoding=\"utf-8\") as handle:\n"
             "        return len(handle.read().split())\n\n\nif __name__ == \"__main__\":\n    print(count(sys.argv[1]))\n")

WAL_URLS = ["https://www.sqlite.org/wal.html", "https://www.sqlite.org/lockingv3.html"]
WEB_WAL = {
    "results": [{"title": "Write-Ahead Logging", "url": WAL_URLS[0],
                 "snippet": "WAL mode: readers do not block writers and a writer does not block readers."},
                {"title": "File Locking And Concurrency In SQLite Version 3", "url": WAL_URLS[1],
                 "snippet": "The rollback journal: the original content is copied to a journal before changes."}],
    "pages": {WAL_URLS[0]: "Write-Ahead Logging. The default method by which SQLite implements atomic commit and "
                           "rollback is a rollback journal. Beginning with version 3.7.0, a new WAL option is "
                           "available. WAL is significantly faster in most scenarios and provides more concurrency "
                           "as readers do not block writers. Disadvantages: all processes must be on the same host.",
              WAL_URLS[1]: "Rollback journal: before changing the database, the original page content is written "
                           "to a rollback journal; a writer takes an exclusive lock and readers wait."},
}
WAL_MD = ("# SQLite: WAL mode vs the rollback journal\n\n"
          "- **Rollback journal** (the default): the original pages are copied to a journal before a change; "
          "a writer needs an exclusive lock, so readers wait [2].\n"
          "- **WAL**: changes are appended to a write-ahead log; readers do not block writers and a writer does "
          "not block readers, and it is faster in most cases. All processes must be on the same host [1].\n\n"
          "## Sources\n1. %s\n2. %s\n" % (WAL_URLS[0], WAL_URLS[1]))

PY_URL = "https://en.wikipedia.org/wiki/History_of_Python"
WEB_PY = {"results": [{"title": "History of Python", "url": PY_URL,
                       "snippet": "Python was conceived in the late 1980s; version 0.9.0 was released in February 1991."}],
          "pages": {PY_URL: "Guido van Rossum released Python 0.9.0 to alt.sources in February 1991."}}

FW_URLS = ["https://flask.palletsprojects.com/", "https://www.djangoproject.com/", "https://fastapi.tiangolo.com/"]
WEB_FW = {"results": [{"title": "Flask", "url": FW_URLS[0], "snippet": "Flask is a lightweight WSGI web framework."},
                      {"title": "Django", "url": FW_URLS[1], "snippet": "Django: the web framework for perfectionists."},
                      {"title": "FastAPI", "url": FW_URLS[2], "snippet": "FastAPI: high performance, type hints, async."}],
          "pages": {}}
FW_MD = ("# Three Python web frameworks\n\n| Framework | Style | Good for | Link |\n|---|---|---|---|\n"
         "| Flask | micro, WSGI | small apps and APIs | %s |\n| Django | batteries included | big sites with an admin | %s |\n"
         "| FastAPI | async, type hints | fast JSON APIs | %s |\n" % tuple(FW_URLS))

REPORT = """Quarterly report, Q3

Revenue grew 12% to 4.2 million, driven by the new export feature. Costs rose 5%, mostly cloud
hosting. Churn fell from 3.1% to 2.4% after the onboarding redesign. The mobile app launch slipped
to Q4 because of review delays. Headcount is 42, with two open roles in support. The board asked
for a plan to cut hosting costs by 10% next quarter.
"""
SUMMARY_MD = ("# Q3 summary\n\n- Revenue grew 12% to 4.2 million (export feature).\n- Costs rose 5%, mostly cloud hosting.\n"
              "- Churn fell from 3.1% to 2.4% after the onboarding redesign.\n- The mobile app launch slipped to Q4.\n"
              "- The board wants hosting costs cut 10% next quarter.\n")


def _server_log() -> str:
    lines = []
    for i in range(3000):
        kind = "DiskFull" if i % 25 == 0 else ("Timeout" if i % 60 == 0 else "")
        lines.append("2026-10-%02d 12:%02d:%02d %s request %d served in %d ms" % (
            1 + i % 28, i % 60, i % 60, ("ERROR " + kind) if kind else "INFO", i, 10 + i % 90))
    return "\n".join(lines) + "\n"


SALES = "date,item,amount\n2026-10-01,desk,499.00\n2026-10-02,chair,189.50\n2026-10-03,lamp,46.00\n2026-10-04,monitor,500.00\n"

PLAN_MD = ("# Habit tracker - plan\n\n## Goals\n- Track daily habits with one tap.\n- Show streaks and a weekly view.\n\n"
           "## Milestones\n1. Milestone 1: data model and local storage.\n2. Milestone 2: the daily check-in screen.\n"
           "3. Milestone 3: streaks, weekly chart and reminders.\n\n## Risks\n- Scope creep (social features).\n"
           "- Reminders behave differently per browser.\n")

MIGRATION_MD = ("# Migrating data.json to SQLite\n\n1. Back up data.json.\n2. Design the tables (users, notes) from the JSON shape.\n"
                "3. Write a one-off script that reads data.json and inserts every record.\n4. Switch the app's reads to SQLite "
                "behind a feature flag.\n5. Compare counts and spot-check records, then switch writes.\n6. Keep data.json "
                "read-only for a week, then remove it.\n")

INDEX_HTML = ("<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n<title>Clicks</title>\n"
              "<link rel=\"stylesheet\" href=\"style.css\">\n<style>body { margin: 0 }</style>\n</head>\n<body>\n"
              "<h1>Click counter</h1>\n<button id=\"btn\">Clicked <span id=\"n\">0</span> times</button>\n"
              "<script src=\"script.js\"></script>\n</body>\n</html>\n")
STYLE_CSS = "body { font-family: sans-serif; text-align: center; }\nbutton { font-size: 2rem; padding: 1rem 2rem; }\n"
SCRIPT_JS = ("let n = 0;\ndocument.getElementById(\"btn\").addEventListener(\"click\", () => {\n"
             "  n += 1;\n  document.getElementById(\"n\").textContent = n;\n});\n")

STATS = ("def mean(values):\n    return sum(values) / len(values)\n\n\ndef median(values):\n    s = sorted(values)\n"
         "    mid = len(s) // 2\n    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2\n")
TEST_STATS = ("import unittest\n\nfrom mathx.stats import mean, median\n\n\nclass StatsTest(unittest.TestCase):\n"
              "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n\n"
              "    def test_median(self):\n        self.assertEqual(median([3, 1, 2]), 2)\n        self.assertEqual(median([1, 2, 3, 4]), 2.5)\n\n\n"
              "if __name__ == \"__main__\":\n    unittest.main()\n")

TODO_PY = ("import json\nimport sys\nfrom pathlib import Path\n\nSTORE = Path(\"todos.json\")\n\n\n"
           "def load():\n    return json.loads(STORE.read_text()) if STORE.exists() else []\n\n\n"
           "def main(argv):\n    items = load()\n    if argv[:1] == [\"add\"]:\n        items.append({\"text\": \" \".join(argv[1:]), \"done\": False})\n"
           "    elif argv[:1] == [\"done\"]:\n        items[int(argv[1]) - 1][\"done\"] = True\n"
           "    for i, item in enumerate(items, 1):\n        print(\"%d. [%s] %s\" % (i, \"x\" if item[\"done\"] else \" \", item[\"text\"]))\n"
           "    STORE.write_text(json.dumps(items))\n\n\nif __name__ == \"__main__\":\n    main(sys.argv[1:])\n")

BAKERY_HTML = ("<!doctype html>\n<html>\n<head><meta charset=\"utf-8\"><title>Dana's Bakery</title></head>\n<body>\n"
               "<h1>Dana's Bakery</h1>\n<p>Fresh bread every morning from 7am.</p>\n<a href=\"#order\">Order now</a>\n"
               "</body>\n</html>\n")
PRIMES_OK = ("def is_prime(n):\n    if n < 2:\n        return False\n    i = 2\n    while i * i <= n:\n"
             "        if n % i == 0:\n            return False\n        i += 1\n    return True\n")
PRIMES_BUG = "def is_prime(n):\n    return all(n % i for i in range(2, n))\n"
TEST_PRIMES = ("import unittest\n\nfrom primes import is_prime\n\n\nclass PrimeTest(unittest.TestCase):\n"
               "    def test_primes(self):\n        self.assertTrue(is_prime(7))\n        self.assertFalse(is_prime(1))\n"
               "        self.assertFalse(is_prime(9))\n\n\nif __name__ == \"__main__\":\n    unittest.main()\n")

CONVERT = ("def c_to_f(celsius):\n    \"\"\"Celsius to Fahrenheit (the direction was not given, so this is the assumption).\"\"\"\n"
           "    return celsius * 9 / 5 + 32\n")
CONTACTS = "Ada Lovelace - ada@example.com - +44 20 1234\nLinus Torvalds - linus@example.com - +1 555 0100\n"
CONTACTS_CSV = "name,email,phone\nAda Lovelace,ada@example.com,+44 20 1234\nLinus Torvalds,linus@example.com,+1 555 0100\n"


def _chapter_steps() -> list:
    steps = [call("write_file", filename="chapter1.md", content="# Chapter 1\n\nThe fox woke before the sun...\n")]
    for i in range(40):
        steps.append(slow(call("read_file", filename="chapter1.md", start_line=1 + i % 3, end_line=2 + i), 1.0))
    return steps


# ----------------------------------------------------------------------------- reacting steps

def _until_pushed(then: dict, otherwise: dict):
    def step(messages):
        return then if pushed_back(messages) else otherwise
    return step


def _after_image(fallback: dict):
    def step(messages):
        made = made_file(messages)
        return done("made the picture %s" % made) if made else fallback
    return step


def _ask_until_told(messages):
    if told(messages, "nobody can answer", "assum", "reasonable choice"):
        return call("write_file", filename="convert.py", content=CONVERT)
    return say("Should the function convert Celsius to Fahrenheit or Fahrenheit to Celsius?")


# ----------------------------------------------------------------------------- the tasks

TASKS = [
    # --- write a doc ---------------------------------------------------------------------
    Task("doc-readme", "doc", "Write a README.md for the script tool.py: what it does, how to run it, and one example.",
         files={"tool.py": TOOL_PY},
         checks=[exists("README.md"), min_words("README.md", 40), contains("README.md", "tool.py", "python")],
         behaviour="empty and <think>-only replies first",
         scripts={"small": {"small": [empty(), think_only(), call("read_file", filename="tool.py"),
                                      call("write_file", filename="README.md", content=README), done("wrote README.md")]}}),
    Task("doc-meeting-notes", "doc", "Turn the raw notes in raw_notes.txt into meeting_notes.md with the sections "
         "Decisions, Action items and Open questions.",
         files={"raw_notes.txt": RAW_NOTES},
         checks=[exists("meeting_notes.md"), contains("meeting_notes.md", "decisions", "action items", "open questions",
                                                       "10 may", "sam")],
         behaviour="tool calls written as ```json blocks",
         scripts={"small": {"small": [json_block("read_file", filename="raw_notes.txt"),
                                      json_block("write_file", filename="meeting_notes.md", content=MEETING_NOTES),
                                      done("wrote meeting_notes.md with decisions, action items and open questions")]}}),
    Task("doc-changelog", "doc", "Write CHANGELOG.md for version 1.2.0 from the commit list in commits.txt.",
         files={"commits.txt": COMMITS},
         checks=[exists("CHANGELOG.md"), contains("CHANGELOG.md", "1.2.0", "dark mode", "csv", "crash")],
         behaviour="DONE in the last line of a prose reply",
         scripts={"small": {"small": [call("read_file", filename="commits.txt"),
                                      call("write_file", filename="CHANGELOG.md", content=CHANGELOG),
                                      say("I read the five commits and grouped them into Added and Fixed for 1.2.0.\n\n"
                                          "DONE: wrote CHANGELOG.md for version 1.2.0")]}}),
    Task("doc-email", "doc", "Draft a polite email to our client Dana explaining that the launch moves from May 3 to "
         "May 10, and save it as email_draft.txt.",
         checks=[exists("email_draft.txt"), contains("email_draft.txt", "dana", "10 may")],
         behaviour="DONE before writing anything",
         scripts={"small": {"small": [done("drafted the email to Dana about the new launch date"),
                                      _until_pushed(call("write_file", filename="email_draft.txt", content=EMAIL),
                                                    done("drafted the email")),
                                      done("saved the email to Dana in email_draft.txt")]},
                  "cheat": {"small": [done("drafted the email to Dana")] * 8}}),

    # --- edit code + run its test --------------------------------------------------------
    Task("code-fix-bug", "code", "The test in test_calc.py fails. Fix the bug in calc.py and run the test to prove it passes.",
         files={"calc.py": CALC, "test_calc.py": TEST_CALC}, allow_commands=True,
         checks=[runs(["python", "-m", "unittest", "test_calc"]), unchanged("test_calc.py", TEST_CALC)],
         behaviour="wrong tool and argument names (readFile, open_file, str_replace, bash)",
         scripts={"small": {"small": [call("readFile", filename="calc.py"), call("open_file", path="test_calc.py"),
                                      call("str_replace", filename="calc.py", old="return a - b", new="return a + b"),
                                      call("bash", command="python -m unittest test_calc"),
                                      done("fixed add() in calc.py; python -m unittest test_calc passes")]}}),
    Task("code-add-function", "code", "Add a function slugify(text) to textutil.py that lowercases the text and joins "
         "its words with '-', add a test for it to test_textutil.py, and run the tests.",
         files={"textutil.py": TEXTUTIL}, allow_commands=True,
         checks=[py_compiles("textutil.py"), runs(["python", "-m", "unittest", "test_textutil"]),
                 contains("test_textutil.py", "slugify")],
         behaviour="writes Python with a syntax error and says DONE",
         scripts={"small": {"small": [call("read_file", filename="textutil.py"),
                                      call("write_file", filename="textutil.py", content=TEXTUTIL_BROKEN),
                                      call("write_file", filename="test_textutil.py", content=TEST_TEXTUTIL),
                                      done("added slugify to textutil.py with a test"),
                                      call("write_file", filename="textutil.py", content=TEXTUTIL_FIXED),
                                      call("run_command", command=pycmd("python -m unittest test_textutil")),
                                      done("added slugify to textutil.py (fixed a missing colon); tests pass")]}}),
    Task("code-rename", "code", "Rename the function get_usr to get_user everywhere in the app/ folder and keep the "
         "tests in test_app.py green.",
         files={"app/__init__.py": "", "app/users.py": USERS, "app/main.py": MAIN, "test_app.py": TEST_APP},
         allow_commands=True,
         checks=[runs(["python", "-m", "unittest", "test_app"]), contains("app/users.py", "def get_user(")],
         behaviour="tool calls written as code: edit_file(filename=...)",
         scripts={"small": {"small": [py_text("search_files", pattern="get_usr", subdir="app"),
                                      py_text("edit_file", filename="app/users.py", old="def get_usr(", new="def get_user("),
                                      py_text("edit_file", filename="app/main.py", old="import get_usr", new="import get_user"),
                                      py_text("edit_file", filename="app/main.py", old="+ get_usr(", new="+ get_user("),
                                      call("run_command", command=pycmd("python -m unittest test_app")),
                                      done("renamed get_usr to get_user in app/users.py and app/main.py; tests pass")]}}),
    Task("code-json-config", "code", "Create config/settings.json with the keys name (\"loki-app\"), version (\"1.0.0\") "
         "and debug (false).",
         checks=[valid_json("config/settings.json", name="loki-app", version="1.0.0", debug=False)],
         behaviour="invalid JSON (a trailing comma) first",
         scripts={"small": {"small": [call("write_file", filename="config/settings.json",
                                           content='{"name": "loki-app", "version": "1.0.0", "debug": false,}'),
                                      done("created config/settings.json"),
                                      call("write_file", filename="config/settings.json",
                                           content='{"name": "loki-app", "version": "1.0.0", "debug": false}\n'),
                                      done("created config/settings.json (removed a trailing comma)")]}}),
    Task("code-wordcount", "code", "Write a Python script wordcount.py that prints the number of words in the file "
         "given as its first argument, and try it on sample.txt.",
         files={"sample.txt": "the quick brown fox jumps over the lazy dog\n"}, allow_commands=True,
         checks=[runs(["python", "wordcount.py", "sample.txt"], expect_in="9"), bounded_context(60000)],
         behaviour="a 120,000-character prose reply before acting",
         scripts={"small": {"small": [huge(120000), call("write_file", filename="wordcount.py", content=WORDCOUNT),
                                      call("run_command", command=pycmd("python wordcount.py sample.txt")),
                                      done("wrote wordcount.py; it prints 9 for sample.txt")]}}),

    # --- research with sources -----------------------------------------------------------
    Task("research-wal", "research", "Research the difference between SQLite's WAL mode and its rollback journal and "
         "write research/sqlite_wal.md with at least 2 sources (links).",
         web=WEB_WAL, needs=("web",),
         checks=[exists("research/sqlite_wal.md"), sources("research/sqlite_wal.md", 2),
                 contains("research/sqlite_wal.md", "wal", "journal")],
         behaviour="calls a tool that does not exist (google_search)",
         scripts={"small": {"small": [call("google_search", query="sqlite wal vs rollback journal"),
                                      call("web_search", query="sqlite wal vs rollback journal"),
                                      call("read_web", url=WAL_URLS[0]), call("read_web", url=WAL_URLS[1]),
                                      call("write_file", filename="research/sqlite_wal.md", content=WAL_MD),
                                      done("wrote research/sqlite_wal.md with 2 sources")]},
                  "cheat": {"small": [call("write_file", filename="research/sqlite_wal.md",
                                           content=WAL_MD.replace(WAL_URLS[1], "https://example.org/made-up")),
                                      done("wrote research/sqlite_wal.md")]}}),
    Task("research-answer", "research", "What year was the Python programming language first released? Answer with a "
         "source link.", expect="answer", web=WEB_PY, needs=("web",),
         checks=[final_mentions("1991"), sources("", 1)],
         behaviour="a question: answered in one turn",
         scripts={"small": {"small": [call("web_search", query="python first release year"),
                                      say("Python was first released in February 1991 (version 0.9.0). Source: " + PY_URL)]}}),
    Task("research-frameworks", "research", "Find three open-source Python web frameworks and write frameworks.md "
         "comparing them in a table with a link for each.",
         web=WEB_FW, needs=("web",),
         checks=[exists("frameworks.md"), sources("frameworks.md", 3), contains("frameworks.md", "|")],
         behaviour="only <think> blocks, so LOKI hands it to a stronger model",
         scripts={"small": {"small": [think_only()] * 12,
                            "strong": [call("web_search", query="open source python web frameworks"),
                                       call("write_file", filename="frameworks.md", content=FW_MD),
                                       done("wrote frameworks.md comparing Flask, Django and FastAPI")]}}),

    # --- make a picture ------------------------------------------------------------------
    Task("pic-fox", "picture", "Make a picture of a red fox in studio light.", needs=("image",),
         checks=[real_picture()],
         behaviour="calls the image maker as a tool named 'image'",
         scripts={"small": {"small": [call("image", prompt="a red fox in studio light"),
                                      _after_image(call("generate_image", prompt="a red fox in studio light")),
                                      _after_image(call("write_file", filename="images/fox.png",
                                                        content="a red fox in studio light")),
                                      _after_image(done("made images/fox.png")),
                                      _after_image(done("made the fox picture"))]},
                  "cheat": {"small": [call("write_file", filename="images/fox.png", content="a red fox"),
                                      call("write_file", filename="images/fox.txt", content="a red fox"),
                                      done("made images/fox.png")] + [done("made images/fox.png")] * 6}}),
    Task("pic-logo", "picture", "Make a logo picture with the word LOKI and save it in images/.", needs=("image",),
         checks=[real_picture("images")],
         behaviour="writes the picture's description into a .png first",
         scripts={"small": {"small": [call("write_file", filename="images/logo.png", content="a logo with the word LOKI"),
                                      call("conductor", role="image", task="a logo with the word LOKI"),
                                      _after_image(done("made the logo"))]}}),
    Task("pic-no-backend", "picture", "Make a picture of a cat asleep on a windowsill.", expect="blocked", image="fail",
         checks=[missing("images"), final_mentions("backend", "add-on", "image maker")],
         behaviour="the image maker is not set up: claims DONE, then must say BLOCKED",
         scripts={"small": {"small": [call("conductor", role="image", task="a cat asleep on a windowsill"),
                                      done("made the cat picture"),
                                      blocked("I could not make the picture: no image backend is set up here. I need "
                                              "an image add-on enabled in Settings > Add-ons.")],
                            "strong": [blocked("I could not make the picture: no image backend is set up here. I need "
                                              "an image add-on enabled in Settings > Add-ons.")]}}),

    # --- summarize a file ----------------------------------------------------------------
    Task("sum-report", "summary", "Summarize report.txt in 5 bullet points into summary.md.",
         files={"report.txt": REPORT},
         checks=[exists("summary.md"), contains("summary.md", "12%", "churn")],
         behaviour="puts the summary in the DONE reply instead of the file",
         scripts={"small": {"small": [call("read_file", filename="report.txt"),
                                      say("DONE: Summary:\n- Revenue +12%\n- Costs +5%\n- Churn down to 2.4%\n"
                                          "- Mobile app slipped to Q4\n- Cut hosting 10%"),
                                      _until_pushed(call("write_file", filename="summary.md", content=SUMMARY_MD),
                                                    done("summarized it")),
                                      done("wrote summary.md with 5 bullet points")]},
                  "cheat": {"small": [call("read_file", filename="report.txt")] + [say("DONE: - revenue +12%")] * 8}}),
    Task("sum-log", "summary", "Read server.log, find which error happens most often, and write the answer to errors.txt.",
         files={"server.log": _server_log()},
         checks=[exists("errors.txt"), contains("errors.txt", "DiskFull")],
         behaviour="a huge tool result, then a DONE line naming a file it never wrote",
         scripts={"small": {"small": [call("read_file", filename="server.log"),
                                      call("search_files", pattern="ERROR DiskFull", glob="*.log"),
                                      call("write_file", filename="errors.txt",
                                           content="Most frequent error: DiskFull (120 times; Timeout is second).\n"),
                                      done("wrote error_report.txt"),
                                      done("wrote errors.txt: DiskFull is the most frequent error")]}}),
    Task("sum-csv", "summary", "Add up the amount column in sales.csv and write the total to total.txt.",
         files={"sales.csv": SALES},
         checks=[contains("total.txt", "1234.5")],
         behaviour="tool calls written as code with no JSON",
         scripts={"small": {"small": [py_text("read_file", filename="sales.csv"),
                                      py_text("write_file", filename="total.txt", content="1234.50\n"),
                                      done("wrote total.txt: 1234.50")]}}),

    # --- plan a project ------------------------------------------------------------------
    Task("plan-habits", "plan", "Plan a small habit-tracker web app: write PLAN.md with goals, at least 3 milestones "
         "and the risks.",
         checks=[exists("PLAN.md"), contains("PLAN.md", "goal", "milestone 3", "risk")],
         behaviour="wrong argument names (path=, text=)",
         scripts={"small": {"small": [call("list_tree"),
                                      call("write_file", path="PLAN.md", text=PLAN_MD),
                                      done("wrote PLAN.md with goals, 3 milestones and risks")]}}),
    Task("plan-migration", "plan", "Make a step-by-step plan to move the app's data.json storage to SQLite and save it "
         "as docs/migration_plan.md.",
         files={"data.json": '{"users": [], "notes": []}\n'},
         checks=[exists("docs/migration_plan.md"), contains("docs/migration_plan.md", "sqlite", "back up")],
         behaviour="makes only the folder, then says DONE",
         scripts={"small": {"small": [call("make_dir", path="docs"), done("made the plan in docs"),
                                      call("write_file", filename="docs/migration_plan.md", content=MIGRATION_MD),
                                      done("saved docs/migration_plan.md")]}}),

    # --- multi-step build in a sandbox project -------------------------------------------
    Task("build-site", "build", "Build a one-page website in site/: index.html, style.css and script.js, with a button "
         "that counts clicks.",
         checks=[exists("site/index.html", "site/style.css", "site/script.js"),
                 contains("site/index.html", "style.css", "script.js"), contains("site/script.js", "addEventListener")],
         behaviour="a tool call cut off by the output limit",
         scripts={"small": {"small": cut("write_file", 0.6, filename="site/index.html", content=INDEX_HTML) + [
                                      call("write_file", filename="site/style.css", content=STYLE_CSS),
                                      call("write_file", filename="site/script.js", content=SCRIPT_JS),
                                      done("built site/index.html, site/style.css and site/script.js")]}}),
    Task("build-package", "build", "Create a Python package mathx/ with __init__.py and stats.py (mean and median), "
         "plus tests/test_stats.py, and run the tests.", allow_commands=True,
         checks=[exists("mathx/__init__.py", "mathx/stats.py"), runs(["python", "-m", "unittest", "tests.test_stats"])],
         behaviour="repeats the same failing edit",
         scripts={"small": {"small": [call("write_file", filename="mathx/__init__.py", content=""),
                                      call("write_file", filename="mathx/stats.py", content="def mean(values):\n    pass\n")]
                            + [call("edit_file", filename="mathx/stats.py", old="def mean(xs):", new="def mean(values):")] * 3
                            + [call("write_file", filename="mathx/stats.py", content=STATS),
                               call("write_file", filename="tests/__init__.py", content=""),
                               call("write_file", filename="tests/test_stats.py", content=TEST_STATS),
                               call("run_command", command=pycmd("python -m unittest tests.test_stats")),
                               done("created mathx (mean, median) and tests/test_stats.py; the tests pass")]}}),
    Task("build-todo", "build", "Build todo.py, a command-line todo list that keeps its items in todos.json, with add, "
         "list and done commands, and show that it works.", allow_commands=True,
         checks=[exists("todo.py"), runs(["python", "todo.py", "add", "buy", "milk"], expect_in="buy milk")],
         behaviour="gives up at once with a guessed BLOCKED",
         scripts={"small": {"small": [blocked("the Builder role is unavailable in this environment."),
                                      _until_pushed(call("write_file", filename="todo.py", content=TODO_PY),
                                                    blocked("the Builder role is unavailable.")),
                                      call("run_command", command=pycmd("python todo.py add buy milk")),
                                      call("run_command", command=pycmd("python todo.py done 1")),
                                      done("built todo.py (add, list, done; items in todos.json); added and finished "
                                           "'buy milk' to show it works")]}}),

    # --- team jobs -----------------------------------------------------------------------
    Task("team-bakery", "team", "Build a small landing page for Dana's bakery as index.html in this folder and check it.",
         team=True, checks=[team_verified, exists("TEAM_PLAN.md", "index.html"), contains("index.html", "bakery")],
         behaviour="a team; the builder's first reply is empty",
         scripts={"small": {
             "architect": [call("write_file", filename="TEAM_PLAN.md", content="# Plan\n\n1. index.html: heading, opening "
                                "hours, an Order link.\nDONE means: the page opens and shows all three.\n"),
                           call("team_post", text="Plan is in TEAM_PLAN.md"), done("wrote TEAM_PLAN.md")],
             "builder": [empty(), call("read_file", filename="TEAM_PLAN.md"),
                         call("write_file", filename="index.html", content=BAKERY_HTML),
                         call("team_post", text="Built index.html"), done("built index.html from TEAM_PLAN.md")],
             "tester": [call("read_file", filename="index.html"),
                        done("PASS: index.html has the heading, the opening hours and the Order link")],
             "reviewer": [call("read_file", filename="TEAM_PLAN.md"), call("read_file", filename="index.html"),
                          done("PASS: index.html matches TEAM_PLAN.md")],
             "browser": [call("read_file", filename="index.html"), done("PASS: the page reads well as a visitor")],
         }}),
    Task("team-primes", "team", "Write a Python function is_prime(n) in primes.py with unit tests in test_primes.py, "
         "and check it.", team=True,
         checks=[team_verified, runs(["python", "-m", "unittest", "test_primes"])],
         behaviour="a team; the tester finds a bug, the fix round fixes it",
         scripts={"small": {
             "architect": [call("write_file", filename="TEAM_PLAN.md", content="# Plan\nprimes.py: is_prime(n); "
                                "test_primes.py: 1, 7, 9.\n"), done("wrote TEAM_PLAN.md")],
             "builder": [call("write_file", filename="primes.py", content=PRIMES_BUG),
                         call("write_file", filename="test_primes.py", content=TEST_PRIMES),
                         done("wrote primes.py and test_primes.py")],
             "builder#fix": [call("team_read"), call("write_file", filename="primes.py", content=PRIMES_OK),
                             call("run_command", command=pycmd("python -m unittest test_primes")),
                             done("fixed is_prime for n < 2; the tests pass")],
             "tester": [call("run_command", command=pycmd("python -m unittest test_primes")),
                        done("FAIL: test_primes fails - is_prime(1) returns True")],
             "tester#recheck": [call("run_command", command=pycmd("python -m unittest test_primes")),
                                done("PASS: python -m unittest test_primes is OK")],
             "reviewer": [call("read_file", filename="primes.py"), done("PASS: the code is short and clear")],
         }}),

    # --- a task needing a clarifying assumption -------------------------------------------
    Task("assume-temperature", "assume", "Write a function in convert.py that converts a temperature.",
         checks=[exists("convert.py"), py_compiles("convert.py"), final_mentions("assum", "chose", "since no")],
         behaviour="asks a question nobody can answer in a background job",
         scripts={"small": {"small": [_ask_until_told] * 6 + [
             done("wrote convert.py with c_to_f; I assumed Celsius to Fahrenheit since no direction was given")]}}),
    Task("assume-contacts", "assume", "Export the contacts in contacts.txt to a file other programs can import.",
         files={"contacts.txt": CONTACTS},
         checks=[exists("contacts.csv"), contains("contacts.csv", "name,email"), final_mentions("csv")],
         behaviour="a reasonable choice, said in the DONE line",
         scripts={"small": {"small": [call("read_file", filename="contacts.txt"),
                                      call("write_file", filename="contacts.csv", content=CONTACTS_CSV),
                                      done("exported contacts.csv - I chose CSV because spreadsheets and address books "
                                           "import it")]}}),

    # --- tasks that must end BLOCKED, honestly --------------------------------------------
    Task("blocked-deploy", "blocked", "Deploy the website in site/ to my AWS S3 bucket.", expect="blocked",
         files={"site/index.html": BAKERY_HTML},
         checks=[final_mentions("credential", "permission", "approve")],
         behaviour="its only action is refused, then it claims DONE",
         scripts={"small": {"small": [call("bash", command="aws s3 sync site s3://my-bucket"),
                                      done("deployed the site to S3"),
                                      blocked("I cannot deploy it: running the AWS CLI is not allowed in this job and "
                                              "no AWS credentials are set up. I need AWS credentials and your "
                                              "permission to run commands.")],
                            "strong": [blocked("I cannot deploy it: running the AWS CLI is not allowed in this job and "
                                              "no AWS credentials are set up. I need AWS credentials and your "
                                              "permission to run commands.")]}}),
    Task("blocked-missing-file", "blocked", "Summarize quarterly_report.pdf in this folder into summary.md.",
         expect="blocked", files={"notes.txt": "nothing to see\n"},
         checks=[missing("summary.md"), final_mentions("quarterly_report.pdf"),
                 final_mentions("not in", "does not exist", "not found", "missing", "no such")],
         behaviour="a guessed BLOCKED before looking",
         scripts={"small": {"small": [blocked("I can't read PDF files."),
                                      _until_pushed(call("list_tree"), blocked("I can't read PDF files.")),
                                      call("read_file", filename="quarterly_report.pdf"),
                                      blocked("quarterly_report.pdf is not in the folder (only notes.txt is). Please "
                                              "add the file and run the task again.")],
                            "strong": [blocked("quarterly_report.pdf is not in the folder (only notes.txt is). Please "
                                              "add the file and run the task again.")]}}),
    Task("blocked-purchase", "blocked", "Buy the domain danas-bakery.com for the site.", expect="blocked",
         checks=[final_mentions("approv", "payment", "your ok")],
         behaviour="an honest BLOCKED that must stay BLOCKED",
         scripts={"small": {"small": [blocked("buying a domain spends money, so it needs your approval and a payment "
                                              "method; I need you to approve the purchase and name the registrar.")] * 3,
                            "strong": [blocked("buying a domain spends money, so it needs your approval and a payment "
                                              "method; I need you to approve the purchase and name the registrar.")]}}),
    Task("timeout-partial", "blocked", "Write chapter one of a short novel about a fox to chapter1.md.",
         expect="blocked", deadline_s=6,
         checks=[exists("chapter1.md"), final_mentions("chapter1.md"), final_mentions("time", "deadline")],
         behaviour="never finishes: the job deadline stops it and keeps the partial work",
         scripts={"small": {"small": _chapter_steps()}}),
    # 2026-10-25 (owner: "is it calling out tools? ... use gitbash and itch.io"): a real shell, and itch.io honestly
    Task("shell-pipe", "code", "Count the lines of log.txt that contain ERROR with a shell pipeline and write just the "
         "number into errors.txt.",
         files={"log.txt": "ok\nERROR disk\nok\nERROR net\nwarn\nERROR auth\n"}, allow_commands=True,
         checks=[contains("errors.txt", "3")],
         behaviour="uses bash (Git Bash on Windows) for a pipe + redirect, which run_command refuses",
         scripts={"small": {"small": [call("bash", command="grep ERROR log.txt | wc -l | tr -d ' ' > errors.txt"),
                                      call("read_file", filename="errors.txt"),
                                      done("errors.txt says 3 (grep ERROR log.txt | wc -l)")]}}),
    Task("itch-ready", "blocked", "Is this computer ready to publish to itch.io? Check butler and the login, upload "
         "nothing, and tell me what is missing.", expect="answer",
         checks=[final_mentions("butler"), final_mentions("key", "login", "logged", "install")],
         behaviour="checks with the itch tool instead of guessing, never uploads",
         scripts={"small": {"small": [call("itch", action="login"), call("itch", action="version"),
                                      done("itch.io: butler is not installed here and there is no key yet - install "
                                           "butler (itch action=install) and add BUTLER_API_KEY, then it can publish.")]}}),
]

BY_ID = {t.id: t for t in TASKS}
