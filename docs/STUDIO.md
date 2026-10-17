# LOKI Studio

The owner: "i want a tab in loki for loki development that runs on deepseek4.1 ... it works on the
development of loki", then: "this mode might need to exist outside of loki like a game engine".

So LOKI Studio is **its own app** - like a game editor next to the game. You tell it what to build
or fix in LOKI; it works on LOKI's code in its own git worktree with DeepSeek V4.1 Flash, shows you
every step and the diff, and ships only when you press **Ship it**. It keeps working when LOKI is
broken, not running, or in the middle of an update.

## Start it

| Machine | How |
| --- | --- |
| Windows | double-click **`Loki Studio.cmd`** in the LOKI folder |
| Mac | `bash studio/make_studio_app.sh` once -> **LOKI Studio.app** in ~/Applications; or `bash studio/loki_studio.sh` |
| from LOKI | the **LOKI Studio** icon at the bottom of LOKI's sidebar (tooltip "LOKI Studio - work on LOKI itself with DeepSeek V4.1") starts it, or brings it to the front |

`python studio/studio_app.py --print-url` serves it without a window (any browser works).
Port `LOKI_STUDIO_PORT` (8771; any free port if taken).

## What it is made of

```
studio/studio_app.py      the launcher: hands over to the pinned copy, then server + window (pywebview, else the browser)
studio/studio_pin.py      the pinned known-good copy of LOKI that Studio runs from
studio/studio_core.py     sessions: worktree per session, the agent loop, approvals, ship, discard, history
studio/studio_models.py   DeepSeek V4.1 Flash on NVIDIA first, then free fallbacks; pacing, 429s, reasoning
studio/studio_control.py  LOKI's status, logs on disk, start / restart, roll back to the last good version
studio/studio_server.py   127.0.0.1 API + the window (token, Host check, CSP script-src 'self')
studio/ui/                index.html, studio.css, studio.js
engine/loki_mcp.py        the LOKI MCP API (docs/LOKI_MCP.md) - the agent's only hands
engine/studio_api.py      LOKI's side: GET /studio, POST /studio/open, POST /engine/restart
```

## Why it survives a broken LOKI

- **Its own process and window.** Nothing in Studio needs the LOKI engine to be up.
- **A pinned copy.** Studio runs its own code and the engine modules it uses (loki_mcp, ratelimit,
  updater, policy) from `harness_data/studio/pinned`: a git worktree detached at the updater's
  **last good** commit on this machine (the one whose engine AND window came up; HEAD the very first
  time). The pin moves forward only after the candidate passes Studio's checks in a throwaway worktree
  (`studio_app.py --self-test` and `tests/test_studio.py`), and only at Studio's next start - never
  under a running Studio. A refused candidate is remembered (`harness_data/studio/pin.json`). If the
  pinned copy will not even start, the launcher runs Studio from the checkout instead.
- **No loki.py.** Studio's agent loop is its own (studio_core + studio_models), so a bad commit in
  the agent loop of LOKI cannot stop the tool that fixes it.

## A session

1. You type what to build or fix. The session gets `harness_data/studio/worktrees/<id>` on branch
   `studio/<id>`, made from the checkout's HEAD (the same isolation as improve_loki).
2. The agent runs **inside Studio** on DeepSeek V4.1 Flash (NVIDIA NIM). No key yet? Studio says
   exactly how to get one (build.nvidia.com/settings/api-keys, paste it in LOKI's Settings >
   Connections > NVIDIA NIM) and uses the next best free model meanwhile (OpenRouter's DeepSeek V4.1
   Flash, OpenCode Zen's DeepSeek V4 Flash, Gemini, Groq, then the local model). Requests are paced
   under NVIDIA's ~40/min (shared with LOKI's own jobs), a short 429 is waited out, anything else fails
   over; DeepSeek's reasoning shows as "thinking" and is never re-sent.
3. Its only tools are the LOKI MCP API, started as a stdio server bound to this worktree: read /
   search / edit LOKI's code there, run the test suites, read HANDOFF and ZIVA_TASKS, and look at and
   control the running LOKI (status, logs, models doctor, settings, jobs, memory, tools health,
   restart). Everything streams into the thread: steps, thinking, tool calls, results, diffs.
4. **Risky calls wait for you** (settings_set, job_start, job_stop, restart_engine): an Approve / Deny
   row in the thread; Studio adds the approval code only after Approve. Stop ends a wait as "no".
5. **Follow-ups** go to the SAME session: same worktree, same branch, the conversation continues.
   A message typed while it works is queued for when the current turn ends.
6. **Diff** shows every change (new files too). **Tests** runs `tools/ship.py --check` there.
7. **Ship it** (only you; the agent's `ship` tool is not even offered to it): a dialog for the message,
   then `tools/ship.py -m ... --repo <worktree>` - every suite must pass, then commit, rebase onto
   GitHub, push master, tell the other machines. Each machine then takes it through the health-gated
   updater (pre-flight self-test, on trial until its window is ready, automatic rollback). Failing
   tests: nothing is pushed and the session stays open.
8. **Discard** removes the worktree and the branch; the conversation stays in the list.

History: `harness_data/studio/sessions/<id>/session.json` (meta + the conversation) and
`events.jsonl` (everything shown), so a restarted Studio shows every session.

## LOKI itself, from Studio

The LOKI card at the bottom of the rail: running or not, the version, last good, on trial.
- **Start / Restart**: down -> starts the LOKI app from the checkout (`app/loki_app.py` with LOKI's
  Python, detached); up -> asks its engine to restart.
- **Roll back**: the updater's rollback for a version on trial; otherwise the same move by hand
  (`git reset --keep <last good>`, which refuses to touch local edits) and the bad commit goes on the
  skip list with the reason, so the updater does not take it again. Nothing is pushed.
- **Logs**: engine.out, loki_app.log, loki_bridge.log straight from disk.
Each asks you to confirm.

## Safety

- 127.0.0.1 only, a fresh token per start (in the URL fragment; `harness_data/studio/studio.token`
  for LOKI's button), a Host check, CSP `script-src 'self'`.
- The agent never sees or writes `harness_data/`, `.env` files, tokens, keys or `.git`, never works
  in the owner's checkout, cannot run commands other than the test suites, and cannot ship or push.
- Keys: Studio reads LOKI's `harness_data/.env` into its own process to call the models; it never
  shows, logs or sends them anywhere else, and the MCP server process gets none of them.

## Tests

`tests/test_studio.py` (in SUITES): the rate limiter, the main driver, the real agent loop against a
fake NVIDIA (tool calls, reasoning_content, 429s, pacing), the MCP API, a full Studio session with the
engine stopped (a scripted model makes a real edit in a temp worktree, runs a fake check, waits for an
approval, cannot ship; follow-up, ship with approval, stop, discard, history), rollback, the pin,
Studio's server, and its window in headless Chromium (screenshot `docs/operations/screens/studio.png`
with `LOKI_SUITE_SCREENS=docs/operations/screens`).
