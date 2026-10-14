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
| `GET /world` | `{"agents": [...], "teams": [...], "machine", "cursor"}` | draw the scene on start and every few seconds |
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
 "team": "9f8e7d6c", "machine": "pc", "last_message": "built the order page"}
```

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

## Godot brief - cancelled

An earlier brief asked Ziva to build this world as a **Godot** client in its own Godot
project. That is cancelled: the world lives **in the app** (plain WebGL, `app/ui/world.js`),
never Godot. The current checks are in ZIVA_TASKS.md (W6 on Windows, M6 on the Mac).
