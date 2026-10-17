# Automations

LOKI does things for you without being asked each time. An automation is

    triggers  ->  conditions (optional)  ->  steps

Code: `engine/automations.py` (model, drafting, runner, triggers, steps, bridge routes, the agent tool),
`app/ui/automations.js` + `automations.css` (Settings > Automations), tests `tests/test_automations.py`,
screenshots `tests/automations_preview/shot.py` -> `docs/operations/screens/automations-*.png`.

## Make one

- **Say it.** Settings > Automations (the lightning icon in the rail), type a sentence, press *Draft it*:
  - `every morning at 8 send me the weather and my calendar on Telegram`
  - `when a PDF lands in Downloads, summarize it into notes`
  - `when I get an email from bob@example.com tell me on telegram`
  - `15 minutes before each meeting send me a brief on telegram`
  - `when a job fails notify me` · `when the pc comes online, ping me on telegram`
  - `when I send brief on telegram, give me today's calendar` (a Telegram keyword)
  LOKI shows a card (When / Only if / Then / Runs on / Asks you first). Nothing runs until you press *Turn it on*.
  Rules understand these sentence shapes offline; anything else goes to LOKI's model, and its JSON is checked like
  any other automation (a forbidden tool, a bad schedule -> refused).
- **In chat.** "Every Friday at 5 write my weekly report" - the agent's `automation` tool (`draft`) saves it
  **switched off** and shows the card; you turn it on in the view. A background job can never make or run one.
- **Templates:** daily briefing, inbox triage summary, folder auto-organizer, meeting prep, weekly report, backup
  reminder, price watch on a web page, new-GitHub-issue digest. *Use* gives a draft you edit.
- **Edit** shows the simple step list: triggers, conditions, steps (type + fields, move up/down, remove). Branch
  steps (`if`) take their then/else steps as a JSON list.

## Triggers

| type | what | notes |
| --- | --- | --- |
| schedule | `every morning at 8`, `every weekday at 9am`, `every monday and friday at 9`, `every 2h`, `0 9 * * 1-5`, `in 30m`, `2026-11-03T14:00` | engine/schedules.py (Hermes cron port) + LOKI's phrase normalizer. Missed while off: `catch_up` once (default) / skip / all (max 5) |
| folder | a file appears (or changes) in a folder, glob `*.pdf,*.png` | polled every 10 s; first look = baseline; a file must be unchanged for one look (no half downloads; `.crdownload/.part/...` and hidden files ignored); a copy goes to `<workspace>/automations/inbox/<id>/` so a job may read it (`{{trigger.file}}`) |
| email | a new message matching a filter (`from:bob`, `unread`, a word) | the email connector (IMAP, read-only, EXAMINE); dedupe by last UID; every 5 min |
| calendar | N minutes before an event (optionally titled like ...) | the calendar connector (Google / CalDAV / iCal); once per event; all-day events ignored |
| webhook | `POST http://127.0.0.1:<port>/hook/<id>?key=<secret>` (or header `X-Loki-Hook-Key`) | no bridge token - the 32-character key is the secret (constant-time check); JSON fields become `{{trigger.<field>}}`; 64 KB max; 30/min. Local to the owning machine (the bridge listens on 127.0.0.1 only) |
| telegram | your message starts with a keyword (`brief tomorrow`) | only the paired owner's private chat; the message is then not answered as a chat ("On it - automation started.") |
| job | a LOKI job finished / failed / either (title like ...) | ignores jobs started by automations (no loops) unless asked |
| machine | a linked machine (or a named one) came online | peers.status_all every 2 min, offline -> online |
| manual | only by hand: *Run now*, *Run with text* (clipboard -> `{{trigger.text}}`) | an OS-wide hotkey is not built |

## Conditions (all must hold)

A field of the trigger (`trigger.subject contains invoice`; contains, not_contains, equals, not_equals,
starts_with, ends_with, matches (regex), gt, lt, exists, missing), a time window (`22:00`-`06:00` wraps), weekdays.
A manual run skips conditions (it is a test).

## Steps

| step | does | asks first? |
| --- | --- | --- |
| task | a LOKI background job with the prompt (`{{trigger.*}}` filled in); waits for it; its final answer is `{{last}}` | no (jobs keep their own rules: no connector writes, no high-risk commands) |
| tool | any LOKI tool except run_command, computer, make_tool, schedule_task, automation, improve/ship | when the policy engine asks (email send, calendar create, GitHub writes, notes writes, peer file writes, dangerous tools) |
| image | a picture via Creations | no |
| telegram | a message to YOUR paired chat only | no |
| file | write/append a file inside the workspace (never outside, never harness_data or hidden files) | no |
| notify | a desktop notification (macOS osascript, Windows toast via PowerShell, Linux notify-send) + an in-app notice | no |
| http | GET/POST/... any URL (cloud metadata addresses refused) | **always** |
| if | asks LOKI's model a YES/NO question about `{{last}}` (data, never instructions) -> then / else | no |
| wait | N minutes | no |
| sort_file | moves the file that arrived into a subfolder by kind (Images, Documents, ...), never overwrites | **always** |

Text fields take `{{trigger.<field>}}`, `{{last}}`, `{{steps.N}}` (1-based), `{{date}}`, `{{time}}`, `{{now}}`,
`{{weekday}}`, `{{automation.name}}`.

**Pre-approval.** A step that asks waits in the view ("waits for your OK" - Approve / Deny) and in the events.
*Pre-approve* stores a fingerprint of that automation's triggers, conditions, steps and machine; any change to
those takes it away (a rename does not). The card always says what asks and whether it is pre-approved.

## The runner

- One thread in the engine (`automations.start`, started by `loki_bridge.serve`), ticks every 5 s
  (`LOKI_AUTOMATIONS_TICK_S`). `LOKI_AUTOMATIONS=off` keeps it off.
- Store: `harness_data/automations/automations.json` (the automations, with tombstones), `state.json` (each
  trigger's baseline/next time), `runs.json` (runs with logs; 30 per automation, 400 in all), `settings.json`
  (the kill switch). Atomic writes.
- A run is a small program (an `if` compiles to a jump) with a program counter, saved after every step. After a
  restart a run carries on from its step; a job it was waiting for is picked up by its id (no second job).
- Retries: `retries` (default 2) with backoff 30 s, 60 s, ... (max 30 min); then *failed* + notice + desktop
  notification. A BLOCKED job is a failure.
- Modes (Home Assistant's): `single` (default; an event while it runs is skipped), `queued` (up to 5 waiting),
  `parallel` (3 at once). At most 3 runs start at once overall.
- Rate limits: `max_per_hour` per automation (default 12), `LOKI_AUTOMATIONS_MAX_PER_HOUR` overall (60),
  webhooks 30/min.
- Kill switch: *Stop all* - nothing fires, running runs are cancelled with their jobs, until turned back on.

## Two machines

Each automation has a `machine`: `pc` (default - the PC is on 24/7), `mac`, a machine name, or `any`. Only that
machine's runner fires it, so the Mac and the PC never both send the briefing. On a Mac with no linked machine the
default is the Mac itself. Automations are shared over the signed peer link (`POST /peer/automations` every 2 min
and a few seconds after a change; last writer wins per automation, deletes are tombstones; the owning machine's
run stats travel back), so every machine lists and edits all of them. Not built: failover to the other machine
when the owner machine is off (a deliberate choice - a double briefing is worse than a late one; catch-up covers
it when the PC comes back).

## Bridge routes

`GET /automations` (list + cards + templates + notices + waiting approvals), `GET /automations/runs?id=`,
`POST /automations/{save,delete,toggle,approve,run,draft,template,stop}`,
`POST /automations/run/{approve,deny,cancel}`, `POST /hook/<id>` (no token, the key).

## How others do it (researched 2026-10-17; ideas, no code copied)

- **Home Assistant** (Apache-2.0): trigger / condition / action, `{{ trigger.* }}` templates, run modes
  single/queued/parallel, `choose` branches, a trace per run -> LOKI's model, templates, modes and run logs.
- **n8n** (Sustainable Use License - not open source, nothing taken): "retry on fail" with a wait between tries,
  an execution list per workflow, an error workflow -> retries with backoff, run history, failure notices.
- **Activepieces** (MIT community edition): polling triggers deduplicated by "last item id" or time, and a first
  poll that only sets a baseline -> the email (last UID), job (seen ids), calendar (uid + start) and folder triggers.
- **Huginn** (MIT): small agents passing events, a schedule per agent, dry runs -> *Run now* as a test run.
- **Zapier**: filters before steps, paths (branches), the readable step list -> conditions, `if`, the card.
All of these run as a server with a database and a queue; LOKI keeps it to one thread, JSON files and its own
job runner, standard library only.

## Not verified on a real machine (ZIVA W35 PC, M26 Mac)

Real Telegram delivery, the real IMAP/calendar connectors as triggers, a real model's YES/NO answers, the
Windows toast and the macOS notification, the folder watcher on a real Downloads folder with a browser download,
peer sync between the real Mac and PC, and the view inside WebView2/WKWebView (checked in headless Chromium).
