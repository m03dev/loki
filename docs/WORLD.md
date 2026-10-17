# LOKI World - agents as characters, in the app

The LOKI World shows LOKI's real agents as characters in a small **3D scene inside the LOKI
app** (plain WebGL, `app/ui/world.js`): faintly behind the home screen, and full size in
Settings > LOKI World (`LOKI_WORLD=background|panel|off`). It is a **viewer, not the brain**:
LOKI's engine runs the agents, decisions, permissions and routing; the world draws what the
engine reports. The in-app world lives in the app; the MMO is a Godot 4 project in `game/loki-world/` (below).
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

## LOKI World as an MMO (session 27)

The owner wants LOKI World to play like hordes.io. The **game state lives in the engine** and any
client uses it - the contract is **docs/MMO_API.md**:

- `GET /mmo/state`: your profile (name, class, level, XP, stats), quests = jobs, monsters =
  failed jobs, loot = creations, NPCs = agents with classes and levels, the 9-slot hotbar.
- `POST /mmo/skill` (a LOKI action from the hotbar starts a real job), `/mmo/quest/turnin`,
  `/mmo/monster/defeat`, `/mmo/monster/retry` (the failed job again on a stronger model),
  `/mmo/profile`, `/mmo/note` - engine/mmo_state.py, progress in `harness_data/.../mmo/profile.json`.
- `POST /world/presence`: your avatar out, the **other machines' avatars and chat** back. The
  engines exchange them over the signed peer link (`/peer/presence`, engine/presence.py), so the
  owner on the Mac and on the PC see each other.

**Clients.** The owner chose a **Godot 4 client**: `game/loki-world/` in this repo (AGENTS.md - the
only place for Godot files), a desktop app for Steam and a web build inside LOKI's window; see
"LOKI World in Godot 4" below. Until its web build is exported, the in-app world has the
first stage as a fallback (`app/ui/mmo/mmo_core.js`): in Settings > LOKI World press **Play**:

| Key | Does |
| --- | --- |
| W A S D / arrow up, down | walk (relative to the camera) |
| drag the mouse, Q / E, arrow left / right | turn the camera |
| wheel / pinch | zoom (down to 3 in Play) |
| Space | jump |
| walk onto a bridge of light at the island's edge | travel to that machine's island (its zone); S turns back |
| click a machine's name | travel there |
| Spectate | the old orbiting view, everything as before |

Your character is drawn in the island's style (the agents' body and visor) with a class hat,
cape and weapon (Warrior helm and sword, Mage hat and staff, Archer hood and bow, Shaman feathers
and totem); the Mac starts as a Mage, the PC as a Warrior. It walks round the pool, buildings,
desks, trees, benches and the gallery, never off the island. What it draws comes from pools made
once (no allocation per frame); `tests/test_mmo.py` guards that. Screenshots:
`python tests/mmo_preview/shot.py <dir>` (headless Chromium, fake /world data).

## LOKI World in Godot 4 - the MMO (`game/loki-world/`)

One Godot 4 project (GL Compatibility renderer everywhere), exported **(a)** as its own desktop app
(Windows / macOS / Linux; Steam later) and **(b)** as a single-threaded web build into
`app/ui/world_godot/` that LOKI's window shows instead of the Babylon world
(Settings > General > LOKI World look = **godot**; until the export is there, or if the window
cannot run it, LOKI falls back to Babylon by itself). It plays the engine's game (docs/MMO_API.md).

**What it is.** You walk as yourself on the island of the machine you are on; every other machine
running LOKI is its own island out in the shared sky, joined by walkable bridges of light (or open
the map with M and click an island to fly there). LOKI's agents are NPCs at their stations with a
class from their role and a level from finished jobs; LOKI (horns, in the hall) gives and takes
quests. Your quests are LOKI's jobs - the hotbar's LOKI actions (4-8) start real jobs; finished
ones are turned in at LOKI for XP. A failed job is a monster out on the island (Timeout Wraith,
Syntax Golem...): beat it for XP and a lesson scroll (the real error), then **retry it on a
stronger model** from the loot window. Loot is what LOKI made: pictures hang in the creations hall
(pink roof) and fill your bags. The owner on his other machine walks around live (presence), and
the chat reaches him (Say) or LOKI (`/l ...`). Day and night follow the local clock. The fox and the
rabbits live on the home island (the fox sleeps at night).

**The look.** Cel-shaded toon light (4 hard bands, faceted low-poly faces), black ink outlines
(inverted hull; each island bakes its own hull so a whole island is 2 draw calls), the 3D view
rendered small and shown with nearest filtering (pixels; `--pixel=N`, default 3), posterize with a
4x4 Bayer dither, a banded sky with a pixel sun and stars, floating islands with teal crystals
under them, a waterfall off the home island. Everything is built from Godot primitives at run
time - no assets (game/loki-world/LICENSES.md).

| Key | Does |
| --- | --- |
| W A S D | walk (relative to the camera); R autorun |
| mouse drag / right drag | orbit the camera / orbit and turn you; wheel zoom; Q / E turn |
| Space | jump |
| click / Tab | target / nearest enemy; double or right click or F: talk / attack (auto attack) |
| 1-9 | Strike, Bolt, Mend, Make a picture, Research, Build, Make a video, Make a game, Hearth |
| Enter | chat (Say); `/l text` talks to LOKI; `/wave /dance /sit /cheer /bow` |
| L B C M H Esc | quest log, bags, character (name + class), map, help, close / clear target |

HUD: nameplates with level and health/energy bars, your frame and the target frame, party frames
(the agents working right now), minimap (turns with the camera) with zone and clock, quest
tracker, hotbar with cooldown sweeps and tooltips, cast bar, XP bar, floating damage numbers,
zone and level-up banners.

**Talking to LOKI** (`autoload/loki_api.gd`, the only net code): the web build is same-origin and
takes the token from the page fragment (`#token=`, as app/ui does); the desktop build tries
`http://127.0.0.1:8767` then `:8766` and reads the token from LOKI's state folder
(`<LOKI_DATA or checkout>/harness_data/app/engine.token`, the per-user folder of a packaged LOKI,
`~/Documents/loki/...`), or `--token=` / `--token-file=` / `LOKI_TOKEN`, or the Pair window. It
uses `GET /mmo/state` every 3 s and the `/mmo/*` actions; `POST /world/presence` every 150 ms while
you move (1 s standing). An engine without the MMO API: the same game is derived from `/world`,
`/jobs` and `/creations` (`scripts/net/derive.gd`). No LOKI at all: an **offline demo world**
(clearly marked) so the game always runs, and it keeps looking for LOKI every 10 s.

**Open, run, export.** Open `game/loki-world/project.godot` in Godot 4.4+ (the PC has 4.8) and
press Play (F5); with LOKI running on the same machine it joins by itself. Command-line options
after `--`: `--mode=background`, `--pixel=3`, `--hour=21`, `--screenshot=shot.png --frames=150`,
`--cam=yaw,pitch,dist`, `--at=x,z`, `--open=bags|quests|character|help|map`, `--fight=1`,
`--loki-url=`, `--token=`, `--no-save`. Export (Project > Export, presets in
`export_presets.cfg`; install the export templates of your Godot version first):
- **Web** -> `app/ui/world_godot/index.html` (+ index.js, .wasm, .pck): single-threaded (no
  COOP/COEP needed, runs in WKWebView and WebView2), shell `web/shell.html` has no inline script
  (LOKI's CSP); the bridge serves `.wasm`/`.pck` and gives `'wasm-unsafe-eval'` to that page only.
- **Windows Desktop** / **macOS** / **Linux** -> `game/loki-world/build/` (not committed).
- **Steam (later):** a Steamworks app id, the GodotSteam GDExtension (MIT) for the overlay /
  achievements / friends, Steam builds via SteamPipe from the desktop exports; nothing in the game
  needs Steam to run. Ship Godot's licence notices with any build.

**Tests.** `godot --headless --path game/loki-world res://tests/run_tests.tscn -- --no-save`
(107: scripts compile, levels/classes/monsters like the engine, derive, offline world, net layer,
the world builds, combat to a kill with XP and loot, Mend and cooldowns). `tests/test_godot_world.py`
(in ship.py) checks the files, the systems, that the net layer only uses real bridge routes and
the engine's words and tables, no CDN, licence notes, the export presets and the hooks; when a
Godot 4 binary is on PATH (or `LOKI_SUITE_GODOT`) it also imports the project, runs those tests
and plays the game headless against the real bridge (source=engine, presence and chat both ways).

## Godot brief (2026-10-14) - superseded

The first Godot brief (a separate Godot client) was cancelled on 2026-10-14; on 2026-10-17 the owner
chose Godot for the MMO after all, inside this repo in `game/loki-world/` (above).
