"""Why background tasks failed, fixed (2026-10-25, from the Mac's 45 job records: 12 BLOCKED, most "the model stopped
calling tools" on the 9B local model, one 29-step loop re-appending a file at 300k tokens, four-agent teams for
one-line checks, Ruflo playbooks naming tools nobody has). Offline, seconds.

    python tests/test_job_reliability.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-jobrel-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import local_agent as la  # noqa: E402
import team  # noqa: E402

# ------------------------------------------------------------------ the context stays inside the model's window
msgs = [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "THE TASK"}]
for i in range(40):
    msgs.append({"role": "assistant", "content": "THOUGHT %d\n```bash\ncat big.txt\n```" % i})
    msgs.append({"role": "user", "content": "exit 0: " + ("line of the file\n" * 400)})
view = la.compact(msgs, budget=20000)
check("a long run is compacted under the budget", sum(len(m["content"]) for m in view) <= 20000,
      sum(len(m["content"]) for m in view))
check("the system prompt and THE TASK are always kept", view[0]["content"] == "SYSTEM" and view[1]["content"] == "THE TASK")
check("the last steps are kept in full", view[-1]["content"] == msgs[-1]["content"])
check("a short run is left as it is", la.compact(msgs[:6], budget=10**6) == msgs[:6])

# ------------------------------------------------------------------ going round in circles stops
script = []
for i in range(12):
    script.append("THOUGHT: the file looks cut off, let me look again\n```bash\ncat TEAM_PLAN.md\n```")
    script.append("THOUGHT: append the rest\n```bash\necho more >> TEAM_PLAN.md\n```")
replies = iter(script)
seen = []
res = la.run("write TEAM_PLAN.md", TMP / "ws", "http://127.0.0.1:1", "m", ask=lambda m: (seen.append(m[-1]["content"]), next(replies))[1],
             execute=lambda cmd: (0, "x"), max_steps=30)
check("cat / append / cat ... is caught: told once, then stopped", res["exit"] == "stuck" and res["steps"] < 15
      and "round in circles" in res["reply"], (res["exit"], res["steps"], res["reply"][:200]))
check("the nudge tells the model the file on disk is complete",
      any("files on disk are complete" in c for c in seen), "")
out = la.observation(0, "y" * 20000)
check("a shortened output says only the VIEW is shortened, the file is complete", "only this view is shortened" in out)

# ------------------------------------------------------------------ the right team size
check("a small concrete job gets one agent", team.choose_roles(
    "Pixel art check: pixelize three pictures from images/ with `loki-make pixel <file> --size 64` and write qa/pixel.md") == ["builder"])
check("a real build gets the ONE core agent (owner 2026-10-28: 'no more 5')", team.choose_roles(
    "Build a small platformer game in Godot with a menu and three levels") == ["builder"])
for _g in ("Make now: one picture of a red baby dragon, game concept art, 16:9 (make_image) into images/",
           "Turn the newest picture in images/ into a 64-pixel game sprite in sprites/",
           "make one new piece of promo art for the owner's game into images/"):
    check("one picture 'for the game' is one agent's job: %s" % _g[:40], len(team.choose_roles(_g)) == 1, team.choose_roles(_g))
check("making a game is the core agent's too (LOKI checks the outcome itself)", team.choose_roles("make a game where you jump on clouds") == ["builder"])
import workers  # noqa: E402
_env = {"LOKI_MODEL": "local-reasoning", "LOKI_PREFER": "local"}
check("a team job with no model of its own does not wait for the one local-model slot (it runs on Smart)",
      not workers.uses_local_model({"agent": "loki", "backend": "local", "model": ""}, _env))
check("... unless LOKI_JOB_MODEL=same or local-only keeps it local",
      workers.uses_local_model({"agent": "loki", "backend": "local", "model": ""}, dict(_env, LOKI_JOB_MODEL="same"))
      and workers.uses_local_model({"agent": "loki", "backend": "local", "model": ""}, dict(_env, LOKI_LOCAL_ONLY="1")))
_solo = team.agent_prompt({"id": "ab12cd34", "goal": "read this line aloud", "roles": ["builder"]}, "builder")
check("a one-agent team does the goal itself - not 'Implement TEAM_PLAN.md' (an older team's plan)",
      "Implement" not in _solo and "Do the team goal yourself" in _solo and "ignore them" in _solo, _solo[:400])
_t2 = {"id": "ff00ee11", "goal": "make a game", "roles": ["architect", "builder", "tester", "reviewer"]}
check("each team plans in its own file (team_plans/<id>.md), never the shared TEAM_PLAN.md",
      "team_plans/ff00ee11.md" in team.agent_prompt(_t2, "architect") and "TEAM_PLAN.md in the project"
      not in team.agent_prompt(_t2, "builder"))
import provider_speed  # noqa: E402
_d = TMP / "speed"
check("a provider out of credit (402) is benched for hours, a daily cap for 12 h, a passing 429 for minutes",
      provider_speed.mark_out(_d, "openrouter", '{"message":"would exceed your available credits","code":402}') == 21600
      and provider_speed.mark_out(_d, "nemo", '{"message":"Rate limit exceeded: free-models-per-day","code":429}') == 43200
      and provider_speed.mark_out(_d, "groq", "HTTP 429 rate limit") == 600
      and provider_speed.mark_out(_d, "x", "connection reset") == 0)
check("... and the next jobs start on the others", provider_speed.order(_d, ["openrouter", "nvidia", "nemo"])[0] == "nvidia")
_d2 = TMP / "speed2"
provider_speed.mark_out(_d2, "groq", "Request too large for model on input tokens per minute (ITPM): Limit 7000")
provider_speed.mark_out(_d2, "gemini", "Too Many Requests: RESOURCE_EXHAUSTED")
provider_speed.record(_d2, "nvidia", 300)
_o = provider_speed.order(_d2, ["groq", "nvidia", "gemini", "local"], keep=("local",))
check("Groq's per-minute size cap is dead for now and left off; Gemini's short quota bench is tried LAST, not never "
      "(owner 2026-10-28: 'go through models that are available ... before giving up'); the local model stays",
      _o == ["local", "nvidia", "gemini"], _o)
_d4 = TMP / "speed4"
provider_speed.mark_out(_d4, "groq", "Request too large for model on input tokens per minute (ITPM): Limit 7000")
provider_speed.mark_out(_d4, "deepseek", "Insufficient Balance")
check("... but if every one is dead, they are all still tried", provider_speed.order(_d4, ["groq", "deepseek"]) == ["groq", "deepseek"])
provider_speed.record(_d2, "gemini", 5)
check("... and one that answers again is back", "gemini" in provider_speed.order(_d2, ["groq", "gemini"]) and
      not provider_speed.is_out(_d2, "gemini"))
pb = team.clean_playbook("# Planner\nPlan well.\n## MCP Tool Integration\n```javascript\nmcp__claude-flow__task_orchestrate {}\n```\n"
                         "Use mcp__claude-flow__memory_usage.\n## Best Practices\nKeep it short.\n" + "x\n" * 2000)
check("playbooks lose the tools nobody has and stay short", "mcp__" not in pb and "claude-flow" not in pb
      and "Plan well." in pb and "Keep it short." in pb and len(pb) <= 1500, pb[:300])

# ------------------------------------------------------------------ which model a background job runs on
shim = REPO.parent / "_shim_unused"
try:
    import loki  # noqa: E402
except ModuleNotFoundError:
    loki = None
if loki is not None:
    local = "local"
    loki.online = lambda: True
    loki._free_capable_online = lambda needs: "nvidia-nemotron"  # pylint: disable=protected-access
    os.environ.pop("LOKI_JOB_MODEL", None)
    check("a chat pinned to a local model hands background jobs to Smart",
          loki.job_model_choice({}, local) == "smart" and "LOKI_JOB_MODEL=same" in loki.JOB_MODEL_NOTE.get("why", ""), local)
    check("a job's own model always wins", loki.job_model_choice({"model": local}, "smart") == local)
    os.environ["LOKI_JOB_MODEL"] = "same"
    check("LOKI_JOB_MODEL=same keeps the chat's model", loki.job_model_choice({}, local) == local)
    os.environ.pop("LOKI_JOB_MODEL")
    loki._free_capable_online = lambda needs: ""  # pylint: disable=protected-access
    loki.main_driver_ready = lambda needs=None: (False, "")
    check("nothing online ready: the job stays on the local model", loki.job_model_choice({}, local) == local)
    loki._free_capable_online = lambda needs: "nvidia-nemotron"  # pylint: disable=protected-access
    loki.experience.best_for_role = lambda role, cands, tier, min_samples=0: local
    loki.provider_configured = lambda name: True
    check("a team role whose best record is the local model is handed back to Smart", loki.model_for_role("builder") == "")
    os.environ["LOKI_JOB_MODEL"] = "same"
    check("... unless LOKI_JOB_MODEL=same", loki.model_for_role("builder") == local)
    os.environ.pop("LOKI_JOB_MODEL")
    online_pick = next(n for n in loki.MODELS if not loki._cfg_is_local(loki.MODELS[n]))  # pylint: disable=protected-access
    loki.experience.best_for_role = lambda role, cands, tier, min_samples=0: online_pick
    check("an online best pick stays", loki.model_for_role("builder") == online_pick)
    seen = {}

    class _Teams:
        def start(self, goal, ws, triage=None, model=""):
            seen["triage"] = triage
            return {"id": "t1", "roles": ["builder"]}
    loki.TEAMS, loki.LAST_TRIAGE = _Teams(), {"difficulty": 4}
    loki.start_team_background("Pixel art check")
    check("the autopilot's team start ignores the last chat's triage", seen["triage"] == {}, seen)
    import autopilot  # noqa: E402
    ap = autopilot.Autopilot(data_dir=TMP / "ap", repo=TMP, agent=loki)
    check("the autopilot uses that start", getattr(ap.start_team, "__name__", "") == "start_team_background")
else:
    print("  (the engine's openai dependency is missing here: the job-model checks are skipped)")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
