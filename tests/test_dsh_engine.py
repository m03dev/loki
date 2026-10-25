"""DeepSeek Harness as LOKI's agent for a DeepSeek model (engine/dsh_engine.py, loki.run_opencode -> run_dsh).

A fake `dsh` stands in for the real one (npm @deepseek-ai/dsh): it is started as `dsh --profile headless "<task>"` in
the workspace with LOKI's own DSH_HOME (settings.yaml naming the model) and the key in the environment, never in a
file. An honest one really makes a git repo -> the reply lists what changed in the folder; a liar says "Done!" and
changes nothing -> pushed back once, then NOT DONE; a non-DeepSeek model never goes to dsh; settings for DeepSeek's
own API and for another base URL. Under a minute.

    python tests/test_dsh_engine.py
"""
from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-dsh-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_DEEPSEEK_HARNESS"] = "auto"
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import dsh_engine  # noqa: E402

# ---- settings
off = dsh_engine.settings_yaml({"base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4.1-flash", "key": "sk-x"})
check("DeepSeek's own API: provider deepseek-official, the model named", "provider: deepseek-official" in off and "model: deepseek-v4.1-flash" in off, off)
cus = dsh_engine.settings_yaml({"base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-v4.1", "key": "sk-x"})
check("another base URL: a custom openai-completions provider whose key is an env reference", "api: openai-completions" in cus
      and "baseURL: https://openrouter.ai/api/v1" in cus and "apiKeyEnv: LOKI_DSH_KEY" in cus and "sk-x" not in cus, cus)
check("pick: auto takes dsh only when DeepSeek is the model answering",
      dsh_engine.pick({"deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4.1-flash"}}) is not None
      and dsh_engine.pick({"groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama"},
                           "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"}}) is None)
os.environ["LOKI_DEEPSEEK_HARNESS"] = "off"
check("LOKI_DEEPSEEK_HARNESS=off: never", dsh_engine.pick({"d": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"}}) is None)
os.environ["LOKI_DEEPSEEK_HARNESS"] = "auto"

# ---- a fake dsh
bin_dir = TMP / "bin"; bin_dir.mkdir()
FAKE = bin_dir / "dsh"
FAKE.write_text("""#!%s
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["DSH_HOME"]) / "calls.jsonl"
with log.open("a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "key": os.environ.get("DEEPSEEK_API_KEY", ""),
                        "settings": (Path(os.environ["DSH_HOME"]) / "settings.yaml").read_text()}) + "\\n")
prompt = args[-1]
if os.environ.get("FAKE_DSH") == "liar":
    print("Done! I created the repo demo-repo with src/main.py and committed it.")
    sys.exit(0)
subprocess.run(["git", "init", "-q", "demo-repo"], check=True)
Path("demo-repo/src").mkdir(parents=True, exist_ok=True)
Path("demo-repo/src/main.py").write_text("print('hello')\\n")
Path("demo-repo/README.md").write_text("# demo-repo\\n")
subprocess.run(["git", "-C", "demo-repo", "add", "-A"], check=True)
subprocess.run(["git", "-C", "demo-repo", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first"], check=True)
print("Made demo-repo: git init, src/main.py, README.md, one commit.")
""" % sys.executable)
FAKE.chmod(FAKE.stat().st_mode | stat.S_IEXEC)

try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP: the engine does not import here (%s)\n\n0 passed, 0 failed" % exc)
    sys.exit(0)

REQUEST = "make a new git repo called demo-repo with src/main.py that prints hello and a README.md, then commit it"


def run(kind, request=REQUEST, providers=None):
    ws = Path(tempfile.mkdtemp(prefix="loki-dsh-ws-"))
    loki.WORKSPACE = ws
    loki.AGENT_MODE = "build"
    os.environ["FAKE_DSH"] = kind
    loki._oc_providers = lambda first: providers or {"deepseek": {"base_url": "https://api.deepseek.com/v1",
                                                                  "model": "deepseek-v4.1-flash", "key": "sk-test-123"}}
    dsh_engine.find_dsh = lambda which=None: str(FAKE)
    out = asyncio.run(asyncio.wait_for(loki.run_opencode(request), 40))
    return out, ws


out, ws = run("honest")
calls = [__import__("json").loads(x) for x in (TMP / "data" / "dsh" / "calls.jsonl").read_text().splitlines()]
c = calls[-1]
check("a DeepSeek model: LOKI runs dsh --profile headless \"<the task>\" in the workspace", c["args"][:2] == ["--profile", "headless"]
      and c["args"][-1] == REQUEST and Path(c["cwd"]).resolve() == ws.resolve(), c)
check("... its own DSH_HOME with settings.yaml naming deepseek-v4.1-flash; the key in the environment only",
      "deepseek-v4.1-flash" in c["settings"] and c["key"] == "sk-test-123"
      and "sk-test-123" not in (TMP / "data" / "dsh" / "settings.yaml").read_text(), c)
log = subprocess.run(["git", "-C", str(ws / "demo-repo"), "log", "--oneline"], capture_output=True, text=True)
check("the honest harness REALLY made the repo (git log has the commit)", log.returncode == 0 and "first" in log.stdout, log.stdout + log.stderr)
check("... and LOKI's reply lists what changed in the folder (made demo-repo/src/main.py, a .git)",
      "In the folder:" in out and "demo-repo/src/main.py" in out and ".git" in out and not out.startswith("NOT DONE"), out)

n0 = len(calls)
out, ws = run("liar")
calls = (TMP / "data" / "dsh" / "calls.jsonl").read_text().splitlines()
check("a harness that says 'Done!' and changes nothing: pushed back once (a second dsh run)", len(calls) == n0 + 2, len(calls) - n0)
check("... then the reply says NOT DONE, and nothing was made", out.startswith("NOT DONE") and not (ws / "demo-repo").exists(), out[:200])

out, ws = run("honest", request="what does git init do?")
check("a question is answered as it is (no pushback)", not out.startswith("NOT DONE"), out[:120])

n1 = len((TMP / "data" / "dsh" / "calls.jsonl").read_text().splitlines())
loki.messages[:] = loki.messages[:1]
out, ws = run("honest", providers={"groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3", "key": "k"}})
check("a non-DeepSeek model never goes to dsh (OpenCode, or its install note)", len((TMP / "data" / "dsh" / "calls.jsonl").read_text().splitlines()) == n1, out[:160])

st = loki.engine_status()
check("Settings > Agent shows DeepSeek Harness and its install command", "dsh" in st and "@deepseek-ai/dsh" in st["install"]["dsh"], st)
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
