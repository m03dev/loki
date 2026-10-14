# Loki — Architecture Decisions

Reasons behind decisions that a reader of the code cannot recover on their own. `AD-n`
ids are referenced from the roadmap and session log.

## AD-1 — Deliver as a self-contained Godot addon (superseded by AD-10)
A consuming project needs **only `addons/loki`** — no second plugin, no manual step.
**Why:** the user's hard requirement; it drives layout, the bundled MCP bridge, and the
bootstrap launcher. **Consequence:** user data (keys, memory) lives in
`<project>/harness_data/`, never in the addon, so the addon can be copied without leaking
secrets.

## AD-2 — Two independent editor plugins talking by node group
`plugin.gd` (viewport screen + MCP bridge) and `chat/plugin.gd` (dock) never hold
references to each other; the dock sets a distinct `layout_key` so Godot does not merge
the two "Loki" widgets into one tab.
**Why:** merging them produced duplicate tabs and a broken dock layout. **Consequence:**
the two can be enabled independently and one failing does not take the other down.

## AD-3 — Keep Python for the agent; do not port Core to a native language
**Why:** the blueprint forbids a rewrite for speed alone; a readable Python addon is a
feature. **Consequence:** performance work targets the hot paths, not a language change.

## AD-4 — Normal Send is one turn; the unbounded goal loop is opt-in
Normal Send → `POST /chat` (`run_agent`); only the explicit "Run task (no limit)" item →
`POST /task` (`pursue_goal`).
**Why:** routing every message through the unbounded loop made a simple question run
dozens of turns against a weak model and stall until the socket closed. **Consequence:**
conversational input is answered in one turn; autonomous multi-step work is a deliberate
choice.

## AD-5 — Dangerous tools are excluded from the offered set and gated
`run_command`, `open_godot`, `run_godot` are callable but not offered to the model by
default; dangerous tools pass through `approve()`.
**Why:** small models misuse shell tools (e.g. `ls -R` on Windows) and stall the task.
**Consequence:** the `system` category is off by default and enable-able per user.

## AD-6 — Jev decisions are advisory and non-fatal; permissions stay independent
Jev may skip a prompt (risk gate) or nudge the loop, but can never force an action, and
with no key it is inert.
**Why:** the decision layer must not be a permission authority. **Consequence:** every
Jev call is guarded; enablement is a key in `.env`.

## AD-7 — One pure function gates MCP server startup
`_server_skip_reason()` decides `enabled` / `requires_env` / `requires_cmd`.
**Why:** an earlier patch split the gating blocks and a disabled server still started,
adding ~20 schemas to every request. **Consequence:** gating is unit tested; adding a
condition means editing one function.

## AD-8 — Guard the shell with a command policy before structured execution
`command_policy()` refuses known-destructive shapes (disk/boot tampering, root deletion,
account/registry edits, pipe-to-interpreter) before `run_command` reaches the shell.
**Why:** the blueprint's Phase 1 safety work; a full structured-argument rework is larger
and must not stall the immediate risk reduction. **Consequence:** the policy is a pure,
tested, overridable guard (`LOKI_COMMAND_POLICY=0`), and `run_command` stays behind the
approval gate. Structured argument execution remains the Phase-1 target.

## AD-9 — No framework pile-up
Adopt a component only with a measured reason; do not integrate several frameworks that
solve the same problem.
**Why:** the blueprint's harness-engineering rule. **Consequence:** the repository keeps
519 vendored skills and MCP wrappers rather than embedding competing agent frameworks.

## AD-10 — Loki is a standalone desktop app; Godot is an optional adapter
`app/loki_app.py` starts the engine (`loki_bridge.py`) and opens the Loki window
(pywebview: WKWebView on macOS) on `app/ui/`, served by the engine itself. Godot,
its MCP servers and the game-dev Build prompt switch on only when the workspace holds a
`project.godot`. `Loki.app` is built on the Mac by `setup.sh`.
**Why:** the owner's direction (2026-10-12): Loki is a desktop command center, not a
Godot product. The engine already spoke a loopback HTTP API, so the change is a new
front end, not a rewrite (AD-3 stands).
**Consequences:** one engine, two front ends (app and Godot dock) behind the same
token-protected API. The UI is served with a Host check (DNS rebinding) and a strict
CSP; the token reaches the window in the URL fragment, never in a request. Quitting the
app stops the engine it started. Godot-free workspaces default to `~/Loki`.

## AD-11 — LOKI is its own application; nothing Godot in the repo (supersedes AD-1)
The engine moved from `addons/loki/harness` to `engine/`. `project.godot`, the editor dock,
its plugins, `.uid` files and the vendored Godot MCP addon were deleted. Godot remains one
optional capability that works on a game project elsewhere (`godot_tools.py`; the probe
script ships as data in `godot_assets.py`). The default workspace is
`~/LOKI Projects/Home`, never `~/Loki`, and chats live in `<workspace>/.loki/`.
**Why:** the owner's direction (2026-10-13): LOKI must never be mistaken for a Godot
project; a Godot project named Loki in `~/Loki` had already been confused with the app.
**Consequences:** one front end (the app) behind the engine's API; user data is found as
`<repo>/harness_data` directly; older chats in `.godot/` are copied over once.

## AD-12 — Laya is the first layer, kept warm
Every request is triaged by Laya before the agent starts (`first_layer.py`), with built-in
rules as the fallback. Laya runs as one warm Node process (`laya_server.mjs`) instead of
one process per decision, because the model is ~1.7 GB and loading takes seconds.
**Why:** the owner's direction: Laya fully offline, as the first layer. **Consequences:**
~2 GB of RAM while warm (unloaded after `LOKI_LAYA_IDLE`); triage is advice only and is
measured against outcomes (`experience.triage_stats`).

## AD-13 — Background work lives in the conversation
The Background and Brain tabs were removed. Running agents show above the message box;
"Run in background" hands a message to an agent. **Why:** the owner's direction: no
separate tabs for pipeline work, and no hand-built agents.

