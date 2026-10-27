"""The command line repeating itself (owner 2026-10-27: "why is it repeating the same thing over and over fix loki").
On the PC, OpenCode ran every command in Windows PowerShell 5.1; models wrote `cd X && python ...`, got "The token '&&'
is not a valid statement separator in this version." and sent the same command again for nine steps (jobs b9903fd0,
decb449c - context past 200k tokens). Checked here with the PC's real outputs, no Windows needed:
  - windows_bash() finds Git for Windows' bash.exe the way OpenCode does (git.exe -> ..\\..\\bin\\bash.exe), else Program Files
  - shell_note() tells a PowerShell agent that && does not work, and a bash one how to write Windows paths
  - error_signature(): two different `cd ... &&` commands with the same PowerShell error are ONE failure
  - RepeatGuard: the third same failure (or the third identical call) says stuck; different errors do not; ok calls do not
  - loki.try_number() reads "(Try N of M." so a retry starts on a different model
  - loki_folder_note() names LOKI's real folder and warns about the copies in the workspace

    python tests/test_repeat_guard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
import opencode_engine as oe  # noqa: E402

FAILED = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


# the PC's real tool outputs (harness_data/jobs/b9903fd0.log, decb449c.log)
PS_AND = ("At line:1 char:40\n+ cd \"C:\\Users\\macul\\LOKI Projects\\Home\" && harness_data\\.venv\\Scripts\\ ...\n"
          "+                                        ~~\nThe token '&&' is not a valid statement separator in this version.\n"
          "    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException")
PS_AND2 = PS_AND.replace("harness_data\\.venv\\Scripts\\ ...", ".\\harness_data\\.venv\\Script ...")
NO_MOD = "Traceback (most recent call last):\n  File \"<string>\", line 1, in <module>\nModuleNotFoundError: No module named 'loki'\n"
RULE = ("The user has specified a rule which prevents you from using this specific tool call. Here are some of the "
        "relevant rules [{\"permission\":\"*\",\"action\":\"allow\",\"pattern\":\"*\"}]")

# --- the shell
git_cmd = r"C:\Program Files\Git\cmd\git.exe"
want = str(Path(git_cmd).resolve().parent.parent / "bin" / "bash.exe")
check("windows_bash follows git.exe to Git\\bin\\bash.exe",
      oe.windows_bash(which=lambda n: git_cmd if n == "git" else None, isfile=lambda f: f == want, env={}) == want)
pf = str(Path(r"C:\Program Files") / "Git" / "bin" / "bash.exe")
check("windows_bash: no git on PATH -> Program Files\\Git",
      oe.windows_bash(which=lambda n: None, isfile=lambda f: f == pf, env={"ProgramFiles": r"C:\Program Files"}) == pf)
check("windows_bash: nothing installed -> ''", oe.windows_bash(which=lambda n: None, isfile=lambda f: False, env={}) == "")
check("PowerShell note says && does not work", "`&&`" in oe.shell_note("powershell") and "`;`" in oe.shell_note("powershell"))
check("every note says never send the same command again",
      all("never send the same command again" in oe.shell_note(s) for s in ("powershell", "bash")))

# --- signatures
a = oe.error_signature("bash", "completed", PS_AND)
b = oe.error_signature("bash", "completed", PS_AND2)
check("two `cd ... &&` variants are one failure", a and a == b)
check("a different error is a different failure", oe.error_signature("bash", "completed", NO_MOD) not in ("", a))
check("a working command is no failure", oe.error_signature("bash", "completed", "Directory: C:\\Users\\macul\n a.txt") == "")
check("a refused call (status error) is a failure", oe.error_signature("bash", "error", RULE) != "")

# --- the guard, replaying job b9903fd0's steps 3-6
g = oe.RepeatGuard(limit=3)
steps = [("bash", "completed", 'cd "C:\\X" && harness_data\\.venv\\Scripts\\python.exe -c "..."', PS_AND),
         ("bash", "completed", 'cd "C:\\X" && .\\harness_data\\.venv\\Scripts\\python.exe -c "..."', PS_AND2),
         ("bash", "completed", 'cd "C:\\X"; .\\harness_data\\.venv\\Scripts\\python.exe -c "..."', NO_MOD),
         ("bash", "completed", 'cd "C:\\X"; .\\harness_data\\.venv\\Scripts\\python.exe -c "print(dir(loki))"', NO_MOD)]
check("two same errors: not stuck yet", not any(g.see(*s) for s in steps))
check("third same error: stuck", bool(g.see("bash", "completed", 'cd "C:\\X" && dir', PS_AND)) and "&&" in g.stuck)
g = oe.RepeatGuard(limit=3)
for _ in range(2):
    g.see("bash", "error", "cd C:\\Users\\macul\\LOKI Projects\\Home\\harness_data && ls -la", RULE)
check("decb449c: the rule refusal the third time is stuck", bool(g.see("bash", "error", "cd C:\\Y && dir", RULE)))
g = oe.RepeatGuard(limit=3)
for i in range(3):
    g.see("read", "completed", "C:\\X\\harness_data", "<entries>a</entries>")
check("the same successful call three times in a row is stuck", "same call" in g.stuck)
g = oe.RepeatGuard(limit=3)
for i in range(10):
    g.see("read", "completed", "C:\\X\\file%d.py" % i, "<content>ok</content>")
check("ten different working calls: not stuck", g.stuck == "")
g = oe.RepeatGuard(limit=3)
g.see("bash", "running", "x", "")
g.see("bash", "pending", "x", "")
check("unfinished calls are not counted", g.same_calls == 0 and g.stuck == "")

# --- loki: retry number and LOKI's folder
try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001 - the cloud has no LOKI venv
    loki = None
    print("skip loki checks (%s)" % str(exc)[:80])
if loki is not None:
    check("try_number reads the retry header", loki.try_number("goal\n\n(Try 3 of 3. Earlier tries failed - x)") == 3)
    check("try_number: a first try is 1", loki.try_number("just a goal") == 1)
    note = loki.loki_folder_note()
    check("LOKI's folder note names the real folder", REPO.as_posix() in note and "old copy" in note)

print("\n%d failed" % len(FAILED) if FAILED else "\nall passed")
sys.exit(1 if FAILED else 0)
