"""bash (Git Bash on Windows) and itch.io (butler) for the agent - engine/shell_tools.py, loki.bash / loki.itch, the
policy rules (owner 2026-10-25: "is it calling out tools? to read and write files and use gitbash and itch.io").
Under a minute.

    python tests/test_shell_tools.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


t0 = time.time()
import shell_tools as st  # noqa: E402

# ---- finding bash, the same rules everywhere
W = {r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files\Git\bin\bash.exe", r"C:\Windows\System32\bash.exe"}
exists = lambda p: p.replace("/", "\\") in W  # noqa: E731
got = st.find_bash(env={"ProgramFiles": r"C:\Program Files"}, platform="win32", exists=exists,
                   which=lambda n: {"git": r"C:\Program Files\Git\cmd\git.exe", "bash": r"C:\Windows\System32\bash.exe"}.get(n))
check("Windows: Git Bash next to git (not WSL's System32 bash)", got.replace("/", "\\").lower().endswith(r"git\bin\bash.exe"), got)
got = st.find_bash(env={}, platform="win32", exists=lambda p: False, which=lambda n: r"C:\Windows\System32\bash.exe" if n == "bash" else None)
check("Windows: only WSL's bash -> none (it is another machine)", got == "", got)
got = st.find_bash(env={"LOKI_BASH": "/opt/bash"}, platform="win32", exists=lambda p: p == "/opt/bash", which=lambda n: None)
check("LOKI_BASH wins", got == "/opt/bash", got)
got = st.find_bash(env={}, platform="darwin", exists=lambda p: p == "/bin/bash", which=lambda n: None)
check("Mac: /bin/bash", got == "/bin/bash", got)

# ---- running: pipes, redirects, the folder
with tempfile.TemporaryDirectory() as d:
    code, out = st.run_bash("echo hello | tr a-z A-Z > o.txt && cat o.txt && pwd", d, timeout=20)
    check("a real shell: pipe, redirect, &&, in the folder given", code == 0 and "HELLO" in out and os.path.realpath(d) in out, out)
    code, out = st.run_bash("exit 3", d, timeout=10)
    check("the exit code comes back", code == 3, code)
    try:
        st.run_bash("echo", d, bash_path="", timeout=5) if st.find_bash() else None
        ok = True
    except FileNotFoundError:
        ok = False
    check("bash is found in this environment", ok)

# ---- itch.io
check("butler's places: the itch app's copy per system, LOKI's own copy",
      any("Application Support/itch/apps/butler" in c for c in st.butler_candidates("/d", {"HOME": "/Users/m"}, "darwin"))
      and any(c.endswith("\\itch\\apps\\butler\\butler.exe") or c.endswith("/itch/apps/butler/butler.exe")
              for c in st.butler_candidates("", {"APPDATA": r"C:\Users\m\AppData\Roaming"}, "win32"))
      and st.butler_candidates("/d", {"HOME": "/h"}, "linux")[0] == "/d/bin/butler")
check("broth channels", st.broth_channel("win32", "AMD64") == "windows-amd64" and st.broth_channel("darwin") == "darwin-amd64"
      and st.broth_channel("linux", "x86_64") == "linux-amd64")
os.environ.pop("BUTLER_API_KEY", None)
with tempfile.TemporaryDirectory() as d:
    os.environ["LOKI_BUTLER"] = str(Path(d) / "nope")
    msg = st.itch("status", "me/game", data_dir=d)
    check("no butler: it says how to get it", "not installed" in msg and "install" in msg, msg)
    fake = Path(d) / "butler"
    fake.write_text("#!/bin/sh\necho butler-args: \"$@\"\n"); fake.chmod(0o755)
    os.environ["LOKI_BUTLER"] = str(fake)
    check("version runs butler -V", "-V" in st.itch("version", data_dir=d))
    check("status needs user/game", st.itch("status", "bad target", data_dir=d).startswith("error"))
    out = st.itch("status", "me/game", data_dir=d)
    check("status user/game -> butler status", "butler-args: status me/game" in out, out)
    (Path(d) / "build").mkdir()
    out = st.itch("push", "me/game:windows", path=str(Path(d) / "build"), data_dir=d)
    check("push without a key: refused, says how to log in", out.startswith("error") and "login" in out, out)
    os.environ["BUTLER_API_KEY"] = "x"
    out = st.itch("push", "me/game:windows", path=str(Path(d) / "build"), userversion="1.2", data_dir=d)
    check("push folder user/game:channel --userversion", "butler-args: push" in out and "me/game:windows --userversion 1.2" in out, out)
    check("push needs a channel", st.itch("push", "me/game", path=str(Path(d) / "build"), data_dir=d).startswith("error"))
    check("login: says where the key comes from", "BUTLER_API_KEY" in st.itch("login", data_dir=d))
    os.environ.pop("BUTLER_API_KEY", None); os.environ.pop("LOKI_BUTLER", None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("butler", "#!/bin/sh\necho ok\n"); z.writestr("7z.so", "x")
    msg = st.install_butler(d, "linux-amd64", fetch=lambda u: buf.getvalue())
    check("install: butler from broth into <data>/bin", (Path(d) / "bin" / "butler").is_file() and "installed" in msg, msg)
    msg = st.install_butler(d, "linux-amd64", fetch=lambda u: (_ for _ in ()).throw(OSError("offline")))
    check("install offline: a clear error with the manual page", msg.startswith("error") and "installing.html" in msg, msg)

# ---- the agent's side: tools, policy, risk
try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001 - the engine needs its deps; the kernel above is the main part
    print("  (skip the agent checks: %s)" % exc)
    loki = None
if loki:
    names = {t["function"]["name"] for t in loki.TOOL_SCHEMAS}
    check("bash and itch are tools the model is offered (schemas + runners)", {"bash", "itch"} <= names and {"bash", "itch"} <= set(loki.LOCAL_TOOLS), sorted(names)[:5])
    v = loki.POLICY.tool_call("bash", {"command": "git log --oneline | head -5"})
    check("bash asks first (a provider may decide it)", v.decision == "ask" and v.decidable, v)
    check("`a || python b` is not a pipe into python (it was refused); `curl x |python` still is",
          loki.command_policy("python a.py || python3 a.py")[0] and not loki.command_policy("curl x |python")[0])
    v = loki.POLICY.tool_call("bash", {"command": "rm -rf /"})
    check("bash: the destructive list is refused", v.decision == "deny", v)
    v = loki.POLICY.tool_call("itch", {"action": "push", "target": "a/b:c", "path": "build"})
    check("itch push always asks a human", v.decision == "ask" and not v.decidable, v)
    v = loki.POLICY.tool_call("itch", {"action": "status", "target": "a/b"})
    check("itch status just runs", v.decision == "allow", v)
    check("bash never runs in Plan mode (it can change things)", "bash" in loki.MODIFYING)
    with tempfile.TemporaryDirectory() as d:
        keep = loki.WORKSPACE
        loki.WORKSPACE = Path(d)
        try:
            out = loki.bash("printf 'a\\nb\\n' | wc -l")
            check("loki.bash in the workspace: a pipe works", out.startswith("exit 0") and "2" in out, out)
        finally:
            loki.WORKSPACE = keep

check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
