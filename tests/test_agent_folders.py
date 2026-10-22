"""Agents can check other folders (owner 2026-10-22: "my agents should have the tools to check other folders").

LOKI's background agents worked in ~/LOKI Projects/Home and every file tool stopped at that folder, so they could
not read LOKI's own code, its QA results or another project - and made results up. Now the READ tools reach LOKI's
folder, its data folder, every folder under LOKI Projects and the owner's extra folders (engine/agent_folders.py);
secrets, system folders and writing outside the workspace stay refused (engine/policy.py). Offline, a few seconds.

    python tests/test_agent_folders.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-folders-")).resolve()
DATA = TMP / "data"
PROJECTS = TMP / "LOKI Projects"
WS = PROJECTS / "Home"
OTHER = PROJECTS / "Other"
EXTRA = TMP / "extra"
for d in (DATA / "qa", DATA / "phone", WS, OTHER, EXTRA):
    d.mkdir(parents=True, exist_ok=True)
(DATA / "qa" / "forge_qa.json").write_text('{"menus": {"failed": 3}}', encoding="utf-8")
(DATA / ".env").write_text("OPENROUTER_API_KEY=sk-or-SECRETSECRETSECRET\n", encoding="utf-8")
(DATA / "phone" / "phones.json").write_text('{"key": "SECRETSECRET"}', encoding="utf-8")
(OTHER / "notes.md").write_text("the other project's plan: needle-42\n", encoding="utf-8")
(OTHER / ".env").write_text("TOKEN=SECRETSECRET\n", encoding="utf-8")
(OTHER / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY----- SECRETSECRET\n", encoding="utf-8")
(OTHER / "my_token.txt").write_text("SECRETSECRET\n", encoding="utf-8")
(EXTRA / "brief.txt").write_text("extra folder text needle-42\n", encoding="utf-8")
SYSTEM_DIR = Path(os.environ.get("SystemRoot", r"C:\Windows")) if sys.platform == "win32" else Path("/etc")
SYSTEM_FILE = SYSTEM_DIR / ("win.ini" if sys.platform == "win32" else "hosts")

os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
os.environ["LOKI_PROJECTS_DIR"] = str(PROJECTS)
os.environ["LOKI_AGENT_FOLDERS"] = os.pathsep.join([str(EXTRA), str(SYSTEM_DIR), str(Path.home())])
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_AUTO_APPROVE", "HARNESS_AUTO_APPROVE"):
    os.environ.pop(_k, None)

import agent_folders  # noqa: E402
import policy  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def section(title):
    print("\n" + title)


section("the folders an agent may read (agent_folders.roots)")
ROOTS = agent_folders.roots(REPO, DATA)
labels = {label: path for label, path in ROOTS}
check("LOKI's own folder is readable", labels.get("loki") == REPO.resolve(), ROOTS)
check("LOKI's data folder is readable", labels.get("data") == DATA.resolve(), ROOTS)
check("~/LOKI Projects (LOKI_PROJECTS_DIR) is readable", labels.get("projects") == PROJECTS.resolve(), ROOTS)
extras = [p for label, p in ROOTS if label == "extra"]
check("the owner's extra folder (LOKI_AGENT_FOLDERS) is readable", extras == [EXTRA.resolve()], extras)
check("a system folder or the whole home folder never becomes an extra folder",
      SYSTEM_DIR.resolve() not in extras and Path.home().resolve() not in extras, extras)
settings = TMP / "settings.json"
settings.write_text('{"agent_folders": ["%s"]}' % str(OTHER).replace("\\", "\\\\"), encoding="utf-8")
check("settings key agent_folders adds a folder",
      OTHER.resolve() in agent_folders.extra_folders({}, settings), agent_folders.extra_folders({}, settings))


def readable(name):
    return agent_folders.resolve_readable(name, WS, ROOTS, data_dir=DATA)


def refused(name):
    try:
        readable(name)
    except ValueError as exc:
        return str(exc)
    return ""


section("reading: allowed where it should be, refused where it must be")
check("a workspace file reads as before", readable("plan.md") == (WS / "plan.md").resolve())
check("LOKI's own code reads (absolute path)", readable(str(REPO / "tools" / "forge_qa.py")).is_file())
check("LOKI's QA results read", readable(str(DATA / "qa" / "forge_qa.json")).is_file())
check("a sibling project under LOKI Projects reads", readable(str(OTHER / "notes.md")).is_file())
check("a sibling project reads by ../ from the workspace too", readable("../Other/notes.md").is_file())
check("an extra folder reads", readable(str(EXTRA / "brief.txt")).is_file())
for secret in (DATA / ".env", DATA / "phone" / "phones.json", OTHER / ".env", OTHER / "id_rsa", OTHER / "my_token.txt",
               REPO / ".git" / "config"):
    why = refused(str(secret))
    check("a secret is refused: %s" % secret.relative_to(secret.parent.parent).as_posix(), "secret" in why, why)
why = refused(str(SYSTEM_FILE))
check("a system file is refused (%s)" % SYSTEM_FILE, bool(why), why)
check("~/.ssh is refused", bool(refused(str(Path.home() / ".ssh" / "id_rsa"))))
check("a folder outside every readable folder is refused", "escapes" in refused(str(TMP / "elsewhere.txt")))

section("the policy: reads may leave the workspace, writes may not")


def ws_only(name):
    p = (WS / str(name)).resolve() if not Path(str(name)).is_absolute() else Path(str(name)).resolve()
    if p != WS.resolve() and WS.resolve() not in p.parents:
        raise ValueError("path escapes workspace: %s" % name)
    return p


engine = policy.PolicyEngine(path_check=ws_only, command_check=lambda c: (True, "ok"), parse_command=lambda c: [c.split()],
                             dangerous={"run_command", "move_file", "delete_file"}, read_check=readable)
check("read_file in LOKI's folder: ALLOW", engine.tool_call("read_file", {"filename": str(REPO / "AGENTS.md")}).allowed)
check("list_tree of a sibling project: ALLOW", engine.tool_call("list_tree", {"subdir": str(OTHER)}).allowed)
check("search_files in the data folder: ALLOW", engine.tool_call("search_files", {"pattern": "x", "subdir": str(DATA)}).allowed)
v = engine.tool_call("read_file", {"filename": str(DATA / ".env")})
check("read_file of the .env: DENY (secret)", v.decision == policy.DENY and "secret" in v.reason, v)
v = engine.tool_call("read_file", {"filename": str(SYSTEM_FILE)})
check("read_file of a system file: DENY", v.decision == policy.DENY, v)
for tool, args in (("write_file", {"filename": str(OTHER / "x.md"), "content": "x"}),
                   ("edit_file", {"filename": str(REPO / "AGENTS.md"), "old": "a", "new": "b"}),
                   ("append_file", {"filename": str(DATA / "qa" / "forge_qa.json"), "content": "x"}),
                   ("delete_file", {"path": str(OTHER / "notes.md")}),
                   ("move_file", {"src": "a.txt", "dst": str(OTHER / "a.txt")})):
    v = engine.tool_call(tool, args)
    check("%s outside the workspace: still DENY" % tool, v.decision == policy.DENY and "workspace" in v.reason, v)
v = engine.tool_call("write_file", {"filename": "ok.md", "content": "x"})
check("write_file inside the workspace: still ALLOW", v.allowed, v)
v = engine.tool_call("run_command", {"command": "python -V", "cwd": str(REPO)})
check("run_command with cwd = LOKI's folder: ASK as every command (not denied)", v.decision == policy.ASK, v)
v = engine.tool_call("run_command", {"command": "python -V", "cwd": str(SYSTEM_DIR)})
check("run_command with cwd = a system folder: DENY", v.decision == policy.DENY, v)
plain = policy.PolicyEngine(path_check=ws_only, command_check=lambda c: (True, "ok"), parse_command=lambda c: [c.split()],
                            dangerous=set())
check("without a read_check the policy is as strict as before",
      plain.tool_call("read_file", {"filename": str(REPO / "AGENTS.md")}).decision == policy.DENY)

section("LOKI's own tools (engine/loki.py)")
try:
    import loki  # noqa: E402
except ImportError as exc:   # openai is missing in a bare checkout; CI and every LOKI install have it
    loki = None
    print("  (skipped: engine/loki.py needs %s)" % exc)
if loki is not None:
    out = loki.read_file(str(OTHER / "notes.md"))
    check("read_file reads a sibling project", "needle-42" in out, out)
    out = loki.read_file(str(DATA / "qa" / "forge_qa.json"))
    check("read_file reads the QA results in LOKI's data folder", '"failed": 3' in out, out)
    out = loki.list_tree(str(OTHER))
    check("list_tree lists another project and hides its secrets",
          "notes.md" in out and ".env" not in out and "id_rsa" not in out and "token" not in out, out)
    out = loki.search_files("needle-42", str(PROJECTS))
    check("search_files searches LOKI Projects (absolute paths back)", str(OTHER / "notes.md") in out, out)
    out = loki.search_files("SECRETSECRET", str(DATA))
    check("search_files never shows a secret's text", "SECRETSECRET" not in out, out)
    out = loki.search_files("SECRETSECRET", str(OTHER))
    check("search_files skips secrets in projects too", "SECRETSECRET" not in out, out)
    res = asyncio.run(loki.call_tool("read_file", {"filename": str(DATA / ".env")}))
    check("call_tool refuses the .env without asking", res.startswith("DENIED") and "secret" in res, res)
    asked = []

    async def no(kind, detail, decidable=True):
        asked.append(kind)
        return False

    loki.approve = no
    target = OTHER / "written.md"
    res = asyncio.run(loki.call_tool("write_file", {"filename": str(target), "content": "x"}))
    check("call_tool: writing into another project is refused", res.startswith("DENIED") and not target.exists(), res)
    res = asyncio.run(loki.call_tool("read_file", {"filename": str(SYSTEM_FILE)}))
    check("call_tool: a system file is refused", res.startswith("DENIED"), res)
    res = asyncio.run(loki.call_tool("run_command", {"command": "python -V", "cwd": str(REPO)}))
    check("call_tool: run_command in LOKI's folder still asks the owner", asked == ["run_command"], (asked, res))
    exe = '"%s"' % sys.executable
    out = loki.run_command(exe + ' -c "import os; print(os.getcwd())"', timeout=30, cwd=str(REPO))
    check("run_command runs in LOKI's own folder (cwd)", out.startswith("exit 0") and str(REPO.resolve()) in out, out)
    out = loki.run_command(exe + " -V", timeout=30, cwd=str(SYSTEM_DIR))
    check("run_command refuses a system folder as cwd", out.startswith("error"), out)
    text = loki.folders_tool()
    check("the folders tool names LOKI's folder, data folder, LOKI Projects and the extra folder",
          all(str(p) in text for p in (REPO.resolve(), DATA, PROJECTS, EXTRA)) and "forge_qa.py" in text, text)
    check("folders is a tool the model is offered", "folders" in loki.LOCAL_TOOLS and "folders" in loki.MODEL_TOOL_NAMES)
    prompt = loki.system_prompt()
    check("every agent's system prompt says where the readable folders are",
          "# Folders you can read" in prompt and str(REPO.resolve()) in prompt and str(PROJECTS) in prompt)
    check("the prompt section is short", len(text) < 1200, len(text))
    res = asyncio.run(loki.read_document(str(OTHER / "notes.md")))
    check("read_document reads another project's document", "needle-42" in res, res[:200])

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
