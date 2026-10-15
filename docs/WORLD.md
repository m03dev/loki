# LOKI World - agents as characters, in the app

The LOKI World shows LOKI's real agents as characters in a small **3D scene inside the LOKI
app** (plain WebGL, `app/ui/world.js`): faintly behind the home screen, and full size in
Settings > LOKI World (`LOKI_WORLD=background|panel|off`). It is a **viewer, not the brain**:
LOKI's engine runs the agents, decisions, permissions and routing; the world draws what the
engine reports. There is no Godot project; the world lives in the app.
(docs/VISION.md section 3.)

## Connecting

- Engine: `http://127.0.0.1:8767` (the app's engine on the same machine).
- Token: read the file `harness_data/app/engine.token` in the LOKI checkout (it changes each
  time LOKI starts; re-read it on a 401). Send `Authorization: Bearer <token>`.
- Only the same machine can connect (loopback). To show the other machine's agents, run the
  world on that machine too, or a later version will relay them over the peer link.

## Endpoints

| Call | Returns | Use |
| --- | --- | --- |
| `GET /world` | `{"agents": [...], "teams": [...], "stats", "machine", "cursor"}` | draw the scene on start and every few seconds (cheap: it reads only what was appended to the event log since the last poll) |
| `GET /events?after=<cursor>&wait=20` | `{"events": [...], "cursor"}` - waits up to 20 s for new events | animate what happens, in order; pass the returned cursor back |
| `GET /teams` | teams with members, stage and board | team panels |
| `POST /chat` `{"message": "..."}` | LOKI's answer | a chat box inside the world |
| `POST /teams` `{"goal": "..."}` | the new team | "start a team" from the world |
| `POST /teams/cancel` `{"id": "..."}` | | stop a team |
| `POST /approval` `{"id": ..., "approved": true}` and `GET /approval` | the pending approval | approve risky actions from the world |

An **agent** in `/world`:

```json
{"id": "job-1a2b3c4d", "name": "Builder", "role": "builder", "state": "working",
 "station": "workshop", "task": "Team 9f8e · Builder: build a landing page",
 "team": "9f8e7d6c", "machine": "pc", "last_message": "built the order page",
 "since": 1760421600.0, "finished": 0, "stage": "build"}
```

`last_message` is that agent's newest board line **in its own team** (two Builders in two
teams never swap lines). `since` is when the job started (or was created), `finished` when it
ended (0 while live), `stage` its team's current stage. A **team** carries `stages`, the stages
it really has in order (`["plan", "build", "check"]`, plus `fix`/`fix-check` in a fix round).
`stats` counts real work: `working`, `waiting`, `blocked`, `done_today`, `failed_today`.

`state` is one of `idle`, `waiting`, `working`, `blocked`, `done`, `failed`; `station` is
one of `hall` (LOKI), `library` (Researcher), `drafting table` (Architect), `workshop`
(Builder), `test bench` (Tester), `review desk` (Reviewer), `terminal` (Browser tester).

An **event** (types: `agent.status`, `agent.message`, `task.created`, `task.assigned`,
`task.started`, `task.blocked`, `task.completed`, `task.failed`, `approval.required`,
`artifact.created`, `verification.completed`, `decision.made`):

```json
{"seq": 1760421600123456789, "t": 1760421600.12, "type": "agent.message",
 "sender": "Tester", "recipient": "Builder", "task": "", "team": "9f8e7d6c",
 "machine": "pc", "payload": {"text": "FAIL: the order button does nothing"}}
```

## What the world shows (and never fakes)

| Event | In the world |
| --- | --- |
| `task.assigned` / `task.created` | a character appears or walks to its station |
| `task.started` | working animation at the station |
| `agent.message` | the sender walks to (or faces) the recipient; speech bubble with `payload.text` |
| `task.blocked` | blocked pose / icon; `approval.required` shows an approval prompt |
| `task.completed` / `task.failed` | done / failed animation; result in a tooltip |
| `verification.completed` | team celebrates (`verified: true`) or flags for the owner |
| `decision.made` | LOKI (in the hall) shows how it read the request: `payload.kind`, `payload.route` |
| `artifact.created` | an item appears at the workshop (`payload.path`) |

A character never talks, works or celebrates unless an event says so.

## The life-sim layer (app/ui/world.js)

On top of the real state the app adds **ambience only** - it never adds words, work or results:

- Agents walk round the plaza ring and out along the paths (not through the pool) and stand
  at their station's desk while their job is `working`, `waiting` or `blocked`. At the desk they
  act out the station: reading a book (library), hammering with sparks (workshop), typing at
  the lit screen (terminal), bubbling beakers (test bench), stamping papers (review desk),
  drawing on the blueprint (drafting table). Each role wears its own hat; LOKI wears horns.
- Above the head, the state: a spinning cube (working), an hourglass (waiting), a red "!"
  with a hand up and a red ring (blocked), a green orb plus a cheer and confetti (done), a
  grey cloud (failed).
- A `done`/`failed`/`idle` agent leaves the desk after a moment and sits on a plaza bench or
  wanders; two free agents near each other turn to face and show a wordless "···" bubble.
- Each live team has a banner in the plaza: the flag in the team's colour and one pip per
  real stage (lit = done, pulsing = now), with its goal as a label in Settings.
- Settings > LOKI World: click an agent (or its legend row) to inspect it - state, task,
  station, machine, time on task, team and stage, last board line, all from `/world`;
  double-click or "Follow" to follow it with the camera; Esc to let go; pinch or wheel to zoom;
  arrow keys to turn. A HUD shows the local time and the real counts from `stats`.
- Scenery: a reflecting pool, a pond and waterfall off the island's edge, flowers, grass,
  benches, teal crystals under the island, floating islets, birds by day, fireflies and
  twinkling stars at night. `prefers-reduced-motion` stops the ambient motion.

**Smooth on every machine.** The static scene is baked once into one buffer (one draw for its
solids, one for their outlines, one for all static shadows; the clouds and islets are one more,
turned by one matrix), so a frame is ~200 small draws regardless of scenery. The frame-time
watcher makes world pixels one size coarser when frames keep running late and keeps that only
if it really helped (`World.adaptive = false` pins it). A lost WebGL context (sleep, GPU
switch) is rebuilt. Lights are ranked so a blocked agent's red light is never the one dropped.

## Godot brief - cancelled

An earlier brief asked Ziva to build this world as a **Godot** client in its own Godot
project. That is cancelled: the world lives **in the app** (plain WebGL, `app/ui/world.js`),
never Godot. The current checks are in ZIVA_TASKS.md (W6 on Windows, M6 on the Mac).
