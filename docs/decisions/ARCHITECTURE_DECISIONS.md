# Loki — Architecture Decisions

Reasons behind decisions that a reader of the code cannot recover on their own. `AD-n`
ids are referenced from the roadmap and session log.

## AD-1 — Deliver as a self-contained Godot addon
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