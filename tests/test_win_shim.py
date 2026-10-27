"""Windows npm shims (owner 2026-10-27: "why hasnt windows been working?"). On the PC every OpenCode job over ~8 KB died
in 0.1 s on every provider with "The command line is too long." - cmd.exe's 8,191-char limit, because LOKI started npm's
opencode.cmd wrapper. Checked here, no Windows needed (the shim is the PC's real file, byte for byte):
  - real_exe() follows npm's opencode.cmd to node_modules/opencode-ai/bin/opencode.exe; non-shims are left alone
  - a shim that runs a .js (no .exe) keeps the .cmd; a missing target keeps the .cmd
  - find_opencode() / cli_agents.find_cli() return the .exe, not the .cmd
  - run_turn: a long message on the real .exe stays on the line (up to ARGV_MAX); if only a .cmd exists, a
    multi-line or >7000-char message goes as an attached file

    python tests/test_win_shim.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
import win_shim  # noqa: E402
import opencode_engine  # noqa: E402
try:
    import openai  # noqa: F401,E402 - cli_agents imports it; the cloud has no LOKI venv
except ImportError:
    import types
    _o = types.ModuleType("openai")
    _o.OpenAI = _o.AsyncOpenAI = object
    _o.OpenAIError = type("OpenAIError", (Exception,), {})
    sys.modules["openai"] = _o
import cli_agents  # noqa: E402

FAILED = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


PC_SHIM = ('@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n'
           '"%dp0%\\node_modules\\opencode-ai\\bin\\opencode.exe"   %*\r\n')
JS_SHIM = ('@ECHO off\r\nSETLOCAL\r\nCALL :find_dp0\r\nIF EXIST "%dp0%\\node.exe" (SET "_prog=%dp0%\\node.exe")\r\n'
           '"%_prog%"  "%dp0%\\node_modules\\x\\bin\\x.js" %*\r\n')

root = Path(tempfile.mkdtemp(prefix="loki-shim-"))
try:
    npm = root / "npm"
    exe = npm / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    shim = npm / "opencode.cmd"
    shim.write_text(PC_SHIM, encoding="utf-8", newline="")
    (npm / "x.cmd").write_text(JS_SHIM, encoding="utf-8", newline="")
    (npm / "gone.cmd").write_text(PC_SHIM.replace("opencode-ai", "missing-pkg"), encoding="utf-8", newline="")

    check("the PC's opencode.cmd resolves to the real opencode.exe", Path(win_shim.real_exe(str(shim))) == exe)
    check("a .js shim keeps the .cmd", win_shim.real_exe(str(npm / "x.cmd")) == str(npm / "x.cmd"))
    check("a shim whose target is missing keeps the .cmd", win_shim.real_exe(str(npm / "gone.cmd")) == str(npm / "gone.cmd"))
    check("a normal program is untouched", win_shim.real_exe("/usr/bin/opencode") == "/usr/bin/opencode")
    check("an unreadable shim is untouched", win_shim.real_exe(str(npm / "nope.cmd")) == str(npm / "nope.cmd"))
    check("cmd.exe limit for a .cmd", win_shim.argv_limit("a.cmd", 24000) == win_shim.CMD_LINE_MAX < 8191)
    check("no cmd limit for an .exe", win_shim.argv_limit("a.exe", 24000) == 24000)

    # find_opencode / find_cli go through the shim
    real_which = shutil.which
    shutil.which = lambda n, *a, **k: str(shim) if n in ("opencode", "opencode.cmd") else None
    os.environ.pop("LOKI_OPENCODE_EXE", None)
    os.environ.pop("LOKI_OPENCODE_EXE".replace("OPENCODE", "OPENCODE"), None)
    try:
        check("find_opencode returns the .exe, not opencode.cmd", Path(opencode_engine.find_opencode()) == exe)
        check("cli_agents.find_cli('opencode') returns the .exe", Path(cli_agents.find_cli("opencode")) == exe)
    finally:
        shutil.which = real_which

    # run_turn: what goes on the command line
    class FakeProc:
        def __init__(self, argv, **kw):
            FakeProc.argv = argv
            self.stdout = iter(())
            self.stdout = type("S", (), {"readline": lambda s: ""})()
            self.stderr = None

        def wait(self, timeout=None):
            return 0

    ws = root / "ws"
    ws.mkdir()
    big = "line one\n" + "x" * 12000          # the PC's failing jobs were 10-15 KB with newlines
    opencode_engine.run_turn(big, str(ws), exe=str(exe), config_path="c.json", env={}, popen=FakeProc)
    check("on the real .exe a 12 KB message stays on the line", FakeProc.argv[-1] == big and "--file" not in FakeProc.argv)
    opencode_engine.run_turn(big, str(ws), exe=str(shim), config_path="c.json", env={}, popen=FakeProc)
    check("on a .cmd a 12 KB message goes as a file", "--file" in FakeProc.argv and "\n" not in FakeProc.argv[-1])
    opencode_engine.run_turn("two\nlines", str(ws), exe=str(shim), config_path="c.json", env={}, popen=FakeProc)
    check("on a .cmd even a short multi-line message goes as a file (cmd.exe cuts at newlines)",
          "--file" in FakeProc.argv)
    opencode_engine.run_turn("hello", str(ws), exe=str(shim), config_path="c.json", env={}, popen=FakeProc)
    check("on a .cmd a short one-line message stays on the line", FakeProc.argv[-1] == "hello")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("%d failed" % len(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
