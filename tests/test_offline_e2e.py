"""End-to-end, offline: Loki finds a local model, prepares it, chats with tools, counts
usage, and runs a background job with the built-in agent - against a fake Ollama on
127.0.0.1:11434 (no internet, no real model, no Claude Code/Codex/herdr needed).

    python tests/test_offline_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "tests"), str(REPO / "addons" / "loki" / "harness"), str(REPO / "addons" / "loki")]

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (detail,)))


def section(title: str) -> None:
    print("\n" + title)


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # TIME_WAIT from a previous run is fine
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


if not port_free(11434):
    print("port 11434 is in use (a real Ollama?) - skipping the offline end-to-end test")
    sys.exit(0)

from fake_ollama import FakeOllama  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki-e2e-"))
DATA, WORK = TMP / "data", TMP / "work"
DATA.mkdir()
WORK.mkdir()
os.environ.update(LOKI_DATA=str(DATA), LOKI_WORKSPACE=str(WORK), LOKI_PREFER="local", LOKI_MODE="build",
                  LOKI_MODEL="smart", LOKI_AUTO_APPROVE="0")
for key in [k for k in os.environ if k.endswith("_API_KEY")]:
    os.environ.pop(key)

fake = FakeOllama(models=["qwen3.5:9b-q4_K_M", "nomic-embed-text:latest"], pullable=["qwen3:4b"]).start()
try:
    import loki  # noqa: E402
    import workers  # noqa: E402
    import loki_bridge  # noqa: E402

    # ------------------------------------------------------------------ the local model
    section("finding and preparing the local model")
    state = loki.resolve_local(force=True)
    check("the installed tool-calling model is found", "qwen3.5" in state["note"], state)
    check("an agent-sized context variant is created (no download)",
          state["name"].startswith("loki-qwen3.5-9b") and fake.created, (state, list(fake.created)))
    created = next(iter(fake.created.values()), {})
    check("the variant raises num_ctx", created.get("parameters", {}).get("num_ctx", 0) >= 8192, created)
    check("the embedding model is never picked as the chat model", "embed" not in state["name"])
    check("smart mode prefers the local model", loki.active_model_name() == "local", loki.active_model_name())
    check("'local' points at the prepared model", loki.MODELS["local"].model == state["name"])
    time.sleep(0.3)
    check("the model is warmed up (keep_alive)", any(p == "POST /api/generate" for p, _ in fake.calls))
    loki.MODELS["local-reasoning"] = loki.ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama",
                                                      model="qwen3.5:9b")
    loki._match_installed_tags([n for n in fake.models])
    check("a short tag is matched to the installed long tag",
          loki.MODELS["local-reasoning"].model == "qwen3.5:9b-q4_K_M", loki.MODELS["local-reasoning"].model)

    # ------------------------------------------------------------------ a real chat turn
    section("a chat turn with tools, offline")
    events = []
    loki.loki_progress_callback = lambda event, text: events.append((event, text))
    loki.messages[:] = [{"role": "system", "content": loki.system_prompt()}]
    answer = asyncio.run(loki.run_agent("please create the file notes/hello.txt"))
    check("the model's tool call ran (file written in the workspace)", (WORK / "notes" / "hello.txt").is_file())
    check("the final answer came back", "DONE" in answer, answer)
    sent = fake.chat_requests()
    check("Loki talked to the local model", sent and sent[0]["model"] == state["name"])
    check("a local model gets a trimmed tool list",
          sent and 0 < len(sent[0].get("tools", [])) <= loki.LOCAL_MAX_TOOLS, len(sent[0].get("tools", [])))
    check("the core file tools are in that list",
          {"read_file", "write_file", "edit_file"} <= {t["function"]["name"] for t in sent[0].get("tools", [])})

    # ------------------------------------------------------------------ usage meter
    section("usage meter")
    check("every model call was counted", len(loki.LAST_USAGE) >= 2, loki.LAST_USAGE)
    first = loki.LAST_USAGE[0] if loki.LAST_USAGE else {}
    check("tokens come from the provider's usage block", first.get("in", 0) >= 1200 and not first.get("est"), first)
    check("a local model is free", first.get("free") and first.get("cost") == 0.0, first)
    check("the meter line was streamed to the UI", any(e == "usage" for e, _ in events))
    summary = loki.USAGE.summary()
    check("the ledger persists and sums", summary["today"]["calls"] >= 2 and (DATA / "usage.jsonl").is_file())
    total = loki_bridge.usage_total(loki.LAST_USAGE)
    check("the chat response carries a usage total with a meter line", total.get("line") and total["calls"] >= 2, total)

    # ------------------------------------------------------------------ setup status
    section("first-run setup status")
    bstate = types.SimpleNamespace(agent=loki, jobs=None, project=WORK)
    info = loki_bridge.setup_status(bstate)
    check("setup reports Ollama running with its models", info["ollama"]["running"] and info["ollama"]["models"])
    check("setup is not needed when a local model works", info["needs_setup"] is False, info["active"])
    check("setup recommends models that fit", isinstance(info["recommend"], list) and info["recommend"])
    code, body = loki_bridge.setup_action(bstate, "/setup/pull", {"tags": ["nope:1b", "qwen3:4b"]})
    check("a download starts in the background", code == 200, body)
    for _ in range(50):
        if loki.model_setup.PROGRESS.snapshot()["done"]:
            break
        time.sleep(0.1)
    snap = loki.model_setup.PROGRESS.snapshot()
    check("a missing tag falls through to the next candidate", snap["status"] == "success" and snap["target"] == "qwen3:4b", snap)
    check("the downloaded model is installed", "qwen3:4b" in fake.models)
    code, body = loki_bridge.setup_action(bstate, "/setup/prefer", {"prefer": "cloud"})
    check("the user can prefer cloud", body["prefer"] == "cloud")
    loki._ONLINE.update(at=time.time() + 3600, ok=False)
    check("with no internet, smart stays local even when cloud is preferred", loki.active_model_name() == "local")
    loki._ONLINE.update(at=0, ok=True)
    loki.PREFER = "local"

    # ------------------------------------------------------------------ background job, built-in agent
    section("background job with the built-in agent (real child process)")
    sup = workers.default_supervisor(DATA)
    sup.tick_s = 0.3
    check("the local backend is available with nothing installed", sup.status()["backends"]["local"]["available"])
    job = sup.create({"backend": "local", "agent": "loki", "workspace": str(WORK), "isolate": False,
                      "prompt": "write the file notes/job.txt"})
    check("a job defaults to the built-in agent", sup.create({"backend": "local", "workspace": str(WORK),
                                                             "prompt": "x"})["agent"] == "loki")
    sup.cancel(sup.store.all()[-1]["id"])
    deadline = time.time() + 90
    while time.time() < deadline:
        sup.tick()
        if sup.store.get(job["id"])["status"] in workers.FINAL:
            break
        time.sleep(0.3)
    done = sup.store.get(job["id"])
    check("the job finished", done["status"] == "done", {k: done[k] for k in ("status", "error", "exit_code")})
    check("the job's agent wrote its file", (WORK / "notes" / "job.txt").is_file(), done.get("output", "")[-800:])
    check("the job log shows the agent's DONE line", "DONE" in done.get("output", ""), done.get("output", "")[-400:])

    # ------------------------------------------------------------------ agents
    section("your agents")
    bstate.jobs = sup
    loki.JOBS = sup
    code, body = loki_bridge.agents_action(bstate, "/agents", {"name": "Docs writer", "instructions": "Write docs.",
                                                               "engine": "loki"})
    check("an agent can be created", code == 200 and body["agent"]["id"] == "docs-writer", body)
    check("starter agents stay alongside it", {"researcher", "builder", "docs-writer"} <= {a["id"] for a in body["agents"]})
    code, body = loki_bridge.agents_action(bstate, "/agents/run", {"id": "docs-writer",
                                                                   "task": "write the file notes/docs.txt"})
    check("running an agent starts a background job", code == 200 and body.get("id"), body)
    jid = body.get("id", "")
    deadline = time.time() + 90
    while jid and time.time() < deadline:
        sup.tick()
        if sup.store.get(jid)["status"] in workers.FINAL:
            break
        time.sleep(0.3)
    check("the agent's job did its work", (WORK / "notes" / "docs.txt").is_file(),
          (sup.store.get(jid) or {}).get("output", "")[-600:])
    out = loki.delegate("Reviewer", "review the notes")
    check("the conductor can delegate to an agent", out.startswith("started background job"), out)
    check("delegate always asks the user first", "delegate" in loki.policy.ALWAYS_ASK)
    check("an unknown agent is reported with the list", "Researcher" in loki.delegate("nobody", "x"))
    for j in sup.store.all():
        sup.cancel(j["id"])
finally:
    fake.stop()

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
