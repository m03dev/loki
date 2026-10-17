# LOKI World MMO - the API a client implements

LOKI World is an MMO made of LOKI's real work. The **engine** (this repo) owns the game state;
a **client** draws it and plays it. Clients:

- the in-app fallback (`app/ui/mmo/`, Babylon/classic renderer): walk your character today;
- the **Godot 4 client** (`game/loki-world/`, the one Godot project in this repo - AGENTS.md): exported as a desktop app
  (Steam) and as a web build shown inside LOKI's window.

Everything below is plain HTTP + JSON on the LOKI bridge. Engine code: `engine/mmo_state.py`
(game state), `engine/presence.py` (other machines' avatars and chat), routes in
`engine/loki_bridge.py`. Tests: `tests/test_mmo.py`.

The rule that never bends: **nothing is invented.** Quests are jobs, monsters are failed jobs,
loot is what LOKI made, NPC levels come from finished jobs, chat lines are real messages. A
client may animate, but every number and word it shows comes from these endpoints.

## 1. Connecting

| | |
| --- | --- |
| Base URL | `http://127.0.0.1:8767` (the app's engine; a command-line engine uses 8766, `LOKI_PORT`) |
| Token | read `harness_data/app/engine.token` in the LOKI checkout; it changes every time LOKI starts - on a 401, read it again |
| Header | `Authorization: Bearer <token>` on every call |
| Host | must be `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding guard) - loopback only |
| Origin | absent (desktop Godot) or one of `http://127.0.0.1[:port]`, `http://localhost[:port]`, `null`; anything else gets 403 |
| POST body | JSON object, **never empty** (send `{}`), at most the bridge's body cap; `Content-Type: application/json` |
| Errors | non-200 with `{"ok": false, "error": "<plain sentence to show the player>"}` |

The engine never accepts connections from another machine on this port. Other machines are
reached only through the engine's signed peer link (section 5); a client never talks to a peer.

**Web build inside LOKI's window** (Godot web export): it would be served by the bridge under
`/ui/...` (same origin, so the token can be handed over as in the app: in the URL fragment).
Needed in the bridge before it can load, not done yet: `.wasm` and `.pck` in `UI_TYPES`, and
`'wasm-unsafe-eval'` in the UI CSP's `script-src` for that page. Export **single-threaded**
(Godot 4.3+ "Thread Support" off) so no COOP/COEP headers or SharedArrayBuffer are needed -
WKWebView (Mac) and WebView2 (PC) both run that.

## 2. Polling rates

| Call | When | Why |
| --- | --- | --- |
| `GET /mmo/state` | on start, then every **3 s**; at once after any POST below | the whole game (cheap: reads the job list and the creations folder) |
| `POST /world/presence` | every **150 ms while you move**, every **1 s** standing still, at once when you chat or emote | your avatar out, other machines' avatars and chat back, in one call |
| `GET /world` | every **2.5 s** if you draw agents walking to stations (optional - `/mmo/state` has the NPCs) | agents, teams, machines, creations hall, model, usage |
| `GET /events?after=<cursor>&wait=20` | long-poll, optional | animate events in order (docs/WORLD.md) |

Stop polling while the client is hidden or minimised. Presence pushing between machines stops
by itself 15 s after the last `POST /world/presence`.

## 3. Coordinates and zones

Each device has its own island; **each island is a zone**, named by the machine's name
(`profile.machine` for this one, `zones.machines[].name` for the linked ones). A position is
machine-neutral: `zone` + `u`, `v` = the place on that island as a fraction of its radius
(-1..1, centre 0,0), `ry` = facing in radians (0 = +v, atan2(du, dv)), `y` = height above the
ground (a jump). Every client lays the islands out its own way; a client that does not know a
zone hides avatars there. The in-app client uses island radius 9.6 (home) / 3.4 (others) and
walks between islands over the bridges of light.

## 4. The game: `GET /mmo/state`

```json
{
  "ok": true, "version": 1, "time": 1760700000.0,
  "profile": {"name": "Mohamed", "cls": "Mage", "color": "#8b7bff", "xp": 2410, "level": 7,
              "xp_into": 130, "xp_need": 1610, "hp_max": 156, "en_max": 100, "power": 1.2,
              "stats": {"quests": 31, "kills": 4, "deaths": 1, "casts": 12, "loot": 9, "retries": 1},
              "machine": "Mac mini"},
  "classes": {"Warrior": {"color": "#d9604f", "about": "...", "hp": 1.2, "power": 1.0}, "Mage": {...}, "Archer": {...}, "Shaman": {...}},
  "skills": [{"slot": 1, "id": "strike", "name": "Strike", "kind": "combat", "cd_s": 1.1, "energy": 0, "cast_s": 0, "range": 2.2, "dmg": [10, 16]}, "..."],
  "quests": [{"id": "a1b2c3d4", "title": "Make an image of a red fox", "kind": "image", "status": "active",
              "job_status": "working", "objective": "Loki agent is on it", "role": "Loki agent", "giver": "LOKI",
              "created": 0, "started": 0, "finished": 0, "xp": 100}],
  "monsters": [{"id": "e5f6", "job_id": "e5f6", "name": "Timeout Wraith", "kind": "wraith", "level": 6, "hp_max": 148,
                "dmg": [9, 15], "attack_every_s": 2.0, "aggro_radius": 4.5, "leash": 9.0, "speed": 2.2, "xp": 100,
                "error": "timed out after 1800 s", "title": "Research ...", "finished": 0,
                "spawn": {"zone": "Mac mini", "u": 0.41, "v": -0.55}}],
  "npcs": [{"id": "loki", "name": "LOKI", "class": {"name": "Trickster", "color": "#2ee6d6"}, "level": 9, "jobs_done": 40,
            "state": "idle", "station": "hall", "task": "", "quest_giver": true, "hp": 1.0, "energy": 0.6,
            "last_message": "", "machine": "Mac mini", "role": "conductor"}],
  "loot": {"items": [{"id": "images/fox.jpg", "title": "red fox in studio light", "kind": "images", "show": "image",
                      "rarity": "rare", "url": "/creations/images/fox.jpg", "t": 0, "new": false}],
           "scrolls": [{"id": "scroll:e5f6", "title": "Lesson: ...", "rarity": "uncommon", "text": "the error", "job_id": "e5f6"}]},
  "zones": {"self": {"name": "Mac mini", "os": "Darwin"}, "machines": [{"name": "pc", "ok": true, "os": "Windows"}]},
  "presence": {"players": ["...section 5"], "chat": ["..."], "cursor": 12},
  "welcome": {"xp": 1860, "quests": 30, "creations": 4, "level": 7}
}
```

- **quests[].status**: `active` (queued / working / blocked - `objective` says which; blocked
  means the owner must answer in LOKI), `complete` (turn it in), `turned_in`, `failed` (a
  monster is out there), `beaten`, `cancelled`. Newest 60. `kind`: image, video, game, research,
  retry, team, task. LOKI (`npcs[].quest_giver`) gives and takes quests.
- **monsters**: failed jobs of the last 7 days not yet beaten, newest 6. Name from the error
  (Timeout Wraith, Rate-Limit Slime, Syntax Golem, Gatekeeper Goblin, Netwisp, Model Mimic, Bug
  Beetle, Error Gremlin). The spawn is stable per job. Behaviour the client plays out: wander
  near the spawn, chase you inside `aggro_radius` at `speed`, hit for `dmg` every
  `attack_every_s`, go home and heal beyond `leash`.
- **npcs**: the agents of `/world` with a class from their role (Trickster, Sage, Arcanist,
  Smith, Alchemist, Paladin, Scout, Adventurer) and a level from the jobs that role finished.
  `hp` 0.15 = failed; `energy` = how busy (working 1, waiting 0.4, blocked 0.15).
- **loot.items** = everything LOKI made; `new` = not seen yet. Fetch the file at `url` with the
  same bearer token (images, videos, sounds). Rarity: sketch common, sound uncommon, picture
  rare, video epic, game legendary.
- **welcome** appears once, the first time: past work became XP (done jobs turned in, older
  failures beaten, existing creations already in the bags).
- Levels: XP to go from level L to L+1 is `round(80 * L^1.55)`; max 99. `hp_max` =
  `(90 + 12 * level) * classes[cls].hp`.

### Combat (played out by the client)

Combat is the client's: target a monster, use `combat`/`self` skills within `range`, respect
`cd_s`, `energy` and `cast_s` (moving cancels a cast). Suggested numbers (what the in-app
client uses): damage `rand(dmg) + 2 * level`, times `profile.power`, 15 % crits x1.75; energy
regenerates 6/s in combat, 14/s out of it; health regenerates 6 %/s after 5 s out of combat.
Death: respawn at LOKI's hall after 4 s and report it (`/mmo/note {"death": true}`). The
engine only records the outcome: `POST /mmo/monster/defeat`.

## 5. Actions (POST)

| Endpoint | Body | Answer | Does |
| --- | --- | --- | --- |
| `/mmo/profile` | `{"name"?: str<=24, "cls"?: "Warrior"/"Mage"/"Archer"/"Shaman"}` | `{name, cls}` | rename / change class |
| `/mmo/skill` | `{"skill": "image"/"research"/"build"/"video"/"game", "text": "what"}` | `{quest: {id, kind, status}}` | a hotbar LOKI action: starts a **real background job** (built-in agent, isolated worktree, 30 min) - the same prompt words as Settings > Creations. Combat skill ids get 400 |
| `/mmo/quest/accept` | `{"kind": <as skill>, "text": "what"}` | same | accepting a quest LOKI offers (same as the skill) |
| `/mmo/quest/turnin` | `{"id": "<job id>"}` or `{"all": true}` | `{turned_in: [ids], loot: [items made while it ran], xp, total_xp, level, xp_into, xp_need, level_up}` | XP = 100 + 20 per minute the job took (max +200) |
| `/mmo/monster/defeat` | `{"id": "<job id>"}` | `{monster, loot: [scroll], retry: {id, path}, xp, ..., level_up}` | once per monster; the scroll holds the real error |
| `/mmo/monster/retry` | `{"id": "<job id>", "model"?: "<a name from GET /models>"}` | `{job: {id}, ...defeat reward}` | starts the failed job again (same prompt, never more permissions) on that model, and the monster is beaten |
| `/mmo/note` | `{"death"?: true, "seen"?: ["<loot id>", ...]}` | `{stats}` | small facts: a death, loot looked at |
| `/world/retry` | `{"id", "model"?}` | the new job | the same retry without the game reward |

Jobs go through the bridge's own `POST /jobs`, so LOKI's policy decides as for any job (403 with
the reason when it refuses). Turn-in, defeat and profile are idempotent where it matters
(a second turn-in or defeat of the same id is a 400).

## 6. Presence: the owner on the Mac sees himself on the PC

`POST /world/presence`

```json
{"player": {"name": "Mohamed", "cls": "Mage", "lvl": 7, "zone": "Mac mini", "u": 0.12, "v": -0.3, "y": 0,
            "ry": 1.57, "hp": 0.9, "en": 1, "moving": true, "emote": "", "emote_at": 0,
            "ts": 1760700000123, "color": "#8b7bff", "target": ""},
 "chat": "optional line you just typed (<=200 chars)",
 "after": 12}
```
answers
```json
{"ok": true, "self": "Mac mini", "cursor": 14, "pushing": true,
 "players": [{"machine": "pc", "age": 0.4, "name": "Mohamed", "cls": "Warrior", "lvl": 5, "zone": "pc",
              "u": 0.5, "v": 0.2, "y": 0, "ry": 0, "hp": 1, "en": 1, "moving": false, "emote": "wave",
              "emote_at": 1760700000000, "ts": 1760699999950, "color": "", "target": ""}],
 "chat": [{"id": "pc:3", "oseq": 3, "seq": 13, "machine": "pc", "from": "Mohamed", "text": "hi from the PC", "t": 0}]}
```
`GET /world/presence?after=<cursor>` answers the same without posting (a spectator).
`GET /world` carries `presence` too (players + the last 20 lines).

- `after`: the `cursor` of your last answer; you get only newer lines. Lines you posted come
  back too (render from the answer, not optimistically, and you never show one twice).
- `players`: the **other** machines' avatars heard from in the last 12 s; `age` = seconds since.
- **Interpolate**: buffer each player's samples by its own `ts` (the sender's clock in ms),
  estimate the clock offset as min(local receive time - ts), and draw at about 350-700 ms in
  the past between the two samples around that time (cap extrapolation at 250 ms). Machine to
  machine the engines exchange every ~350 ms while someone moves (2 s otherwise), over the LAN
  or the relay.
- Emotes: `wave`, `dance`, `sit`, `cheer`, `bow` (+ `emote_at` in ms); chat commands like
  `/wave` are the client's.
- Everything from another machine is display-only and sanitised by the engine (lengths capped,
  control and bidi characters removed, numbers clamped); show it as plain text, never markup.

Between engines (not for clients): signed `POST /peer/presence {machine, player, chat:[{oseq, from, text}], since}`
answered by `{ok, machine, player, chat}` - one call carries both directions, so a link that
can only be dialled one way (the relay) still shows both owners. A peer on an older LOKI answers
404 and is simply retried later.

## 7. What a client should feel like (the owner's list)

WASD + mouse camera (Q/E turn, Space jump), nameplates with level and health/energy bars, a
minimap, the chat box, a 9-slot hotbar (1 Strike, 2 Bolt, 3 Mend, 4 Picture, 5 Research,
6 Build, 7 Video, 8 Game, 9 Hearth - `skills[]`), party frames (the busy agents), a target
frame, cast bars, cooldowns, damage numbers, a quest log + tracker, bags (loot), a character
sheet, a loot window, level-up effects, zones (islands) with a banner, day/night, emotes, sound
- in LOKI World's look: pixel cel shading, black ink outlines, the fox and the rabbits.
