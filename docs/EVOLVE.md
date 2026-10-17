# EVOLVE - LOKI grows its own personal-agent core

LOKI builds its own "OpenHuman" inside itself, one step at a time, by itself (engine/evolve.py).
When LOKI is idle, the autopilot takes the first open line below (after the owner's own ideas
from Settings > Lab) and hands it to `improve_loki`: a background LOKI agent changes LOKI's code
in its own git worktree, runs every test suite, and ships only when all of them pass. That
agent ticks the line (`- [ ]` -> `- [x]`) in the same commit, so a finished step is finished on
every machine. A step that did not ship is tried again after 3 days, with what went wrong in
its prompt. Settings > Lab shows all of it; LOKI_EVOLVE (Settings > General) turns it on or off
(auto = only on the Windows PC, which is on 24/7).

Rules for every step: never remove a feature to make room; keep the window fast (no heavy
dependency without need); macOS and Windows; a test for what is built; the world keeps its
pixel cel-shaded look.

Reference, not code: OpenHuman (tinyhumansai/openhuman, GPL-3.0) shows what a personal agent
core has. LOKI writes its own versions; nothing is copied from it.

## Roadmap

- [ ] E1 Memory you can see and edit - Settings > Memory lists what LOKI remembers (facts, past work, skills) with search, edit and forget; at the start of a request LOKI recalls the few memories that matter and the reply says which it used.
- [ ] E11 LOKI's own game engine, step 2 - the engine (app/ui/engine/pixel_engine.js), the Play panel and the first game (Fox & Berries) exist. Next: LOKI World itself drawn by the same engine (one renderer, not two), plus sprites/particles and a simple tilemap/terrain in the engine, and two more games LOKI makes on its own (games/<name>/game.js, via game_engine_guide).
- [ ] E2 Learn skills from its own work - after a request that was verified done and took more than 5 tool calls, write a SKILL.md of the procedure to harness_data/skills/learned/ and use it the next time a similar request comes (the reply says "used learned skill ...").
- [ ] E3 Subagents - a run_subagent tool: a short-lived helper with a narrow tool set and its own small context that returns one result, so research and file searches run side by side.
- [ ] E4 More island life - animals in LOKI World in the pixel cel-shaded style with ink lines, like the fox: ducks in the pond, a cat that naps by the library, a deer at the island edge; each with a few believable behaviours.
- [ ] E5 Creations hall - a small gallery building on the island that shows what LOKI made (images/, videos/, sketches/, games) as framed pictures on its walls; clicking one opens it.
- [ ] E6 Speed watch - time startup, first paint and each request phase; Settings > Lab shows the numbers; once a week find the slowest step and make it faster.
- [ ] E7 Voice - push-to-talk in the message box (local whisper when installed, else the window's own speech recognition) and an optional spoken reply.
- [ ] E8 Self-review - once a week read the "what LOKI learned" report and add up to 3 proposals to Settings > Lab marked "LOKI's idea"; they wait for the owner's OK before they are built.
- [ ] E9 Tools LOKI writes for itself - a folder format (tool.json + one Python file) in harness_data/tools that LOKI can write and load without a restart, run like run_command (approval first).
- [ ] E10 Phone channel - talk to LOKI from Telegram: the owner pastes a bot token in Settings > General (a secret setting); messages become chats, replies go back; nothing else is exposed.
