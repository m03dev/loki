"""Manga Studio walks every model before a placeholder, and says so when it falls back (2026-10-28: the main
driver timed out on an outline and the step 'succeeded' with the premise pasted onto every page)."""
import asyncio
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import manga  # noqa: E402
import manga_api  # noqa: E402

PASSED = FAILED = 0


def check(name, ok):
    global PASSED, FAILED
    print(("  PASS " if ok else "  FAIL ") + name)
    PASSED, FAILED = PASSED + bool(ok), FAILED + (not ok)


GOOD = '{"logline": "A fox meets a machine.", "pages": [{"beat": "setup", "summary": "The fox sees it."}, ' \
       '{"beat": "turn", "summary": "Tofu falls out."}]}'


def fake_agent(answers):
    calls = []

    async def _port_ask(prompt, max_tokens=0, provider=""):
        calls.append(provider)
        a = answers.get(provider)
        if isinstance(a, Exception):
            raise a
        return a

    return types.SimpleNamespace(_port_ask=_port_ask, port_ladder=lambda: list(answers), calls=calls)


def run(agent):
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    state = types.SimpleNamespace(agent=agent, loop=loop)
    ws = Path(tempfile.mkdtemp())
    pid = manga.tool({"action": "project", "premise": "A fox spirit fears a vending machine.", "pages": 2}, ws)["project"]
    out = manga.tool({"action": "outline", "project": pid}, ws, ask=manga_api._ask(state, timeout_s=2))
    loop.call_soon_threadsafe(loop.stop)
    return out, manga.review(ws, pid)


t0 = time.time()
a = fake_agent({"nvidia": RuntimeError("timed out"), "nvidia-nemotron": "no json here", "local": GOOD})
out, rv = run(a)
check("each model is tried in turn until one writes usable JSON", a.calls == ["nvidia", "nvidia-nemotron", "local"])
check("the outline is the model's, not the placeholder", out["outline"]["pages"][1]["summary"] == "Tofu falls out.")
check("a good write leaves no warning", not out["warnings"])

b = fake_agent({"nvidia": RuntimeError("down"), "local": "nope"})
out, rv = run(b)
check("when every model fails the step says so", "outline" in out["warnings"] and "every model failed" in out["warnings"]["outline"])
check("and the review lists it as an open issue", any(i.startswith("outline:") for i in rv["issues"]))

# A model that timed out is tried last on the next step, and first again once it answers.
manga_api.SLOW.clear()
c = fake_agent({"nvidia": TimeoutError(), "local": GOOD})
run(c)
c.calls.clear()
run(c)
check("a model that just timed out is tried last next time", c.calls == ["local"])
manga_api.SLOW.clear()

# A retired NVIDIA model: a real call's 404 sticks even though /models still lists it (it used to flip back to ready).
import provider_health  # noqa: E402
reg = provider_health.Registry(Path(tempfile.mkdtemp()) / "h.json")
reg.record_failure("nvidia-pro", "[model error] moonshotai/kimi-k2.6 answered HTTP 404: {'status': 404, "
                   "'title': 'Not Found', 'detail': \"Function '23d4' not found for account\"}")
reg.record_probe("nvidia-pro", {"state": "ok", "models": ["moonshotai/kimi-k2.6"]})
check("a model a real call said is gone stays benched after a /models probe", not reg.usable("nvidia-pro")[0])
reg.record_success("nvidia-pro")
check("and comes back the moment a real call works", reg.usable("nvidia-pro")[0])
reg.record_failure("other", "HTTP 404 model not found")
check("a plain missing model is benched", not reg.usable("other")[0])
print("\n%d passed, %d failed (%.1f s)" % (PASSED, FAILED, time.time() - t0))
sys.exit(1 if FAILED else 0)
