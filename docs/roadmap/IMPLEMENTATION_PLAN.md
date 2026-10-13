# Loki — Implementation Plan

Status is honest: **Done** = implemented and verified by a test or a real run;
**Partial** = implemented but not fully verified; **Planned**/**Blocked** as labelled.
Acceptance criteria are stated per phase.

Baseline at the start of this plan: `tests/test_loki.py` -> **200 offline checks green**.

---

## Phase 0 — Locate and audit — Done
Found and confirmed `C:\Users\macul\Documents\loki` (`master`, remote
`github.com/m03dev/loki`), clean tree. Mapped the architecture and the request lifecycle,
ran the baseline suite (200 green), and created the durable documentation in `docs/`
(blueprint, current state, target architecture, decisions, security, recovery, roadmap,
integrations, session log).
**Acceptance met:** checkout confirmed; baseline recorded; docs created.

## Phase 1 — Safety and reliability — Partial
- Done: workspace path sandbox (`resolve_in_workspace`, traversal tested).
- Done: dangerous tools behind `approve()`; auto-approve only via explicit env.
- Done (this session): `command_policy()` guard in front of `run_command`; refuses
  destructive shapes and pipe-to-interpreter; pure function; 18 new tests; suite 218 green.
- Done: structured `friendly_error`/`short_error`, retry/backoff, per-provider failover,
  cancellation.
- Planned: hinting side-effect tools (delete/move/overwrite) through the same approval
  path for non-model callers, and Phases below.
- Planned: structured argument execution to replace the shell string (supersedes the
  guard when it lands; the guard stays as defence in depth).
**Acceptance:** destructive command strings cannot execute; file tools cannot escape the
workspace; suite stays green.

## Phase 2 — Jev / Laya — Done (partial verification)
- Jev: Done (risk gate + loop detection, optional, non-fatal).
- Laya: Done — `laya.py` + `decisions.py` integrate github.com/receptron/laya as the
  local-first provider (HTTP or a local Node driver that delegates to the real package),
  Laya-first routing with Jev fallback, recorded disagreements, tests with a mock.
- Open: the model's own forward pass is not run offline (needs the 1.7 GB ONNX weights).
**Acceptance met:** routing, fallback and disagreement handling are tested; a decision can
skip a prompt (never force one).

## Phase 3 — Capability registry and repository browser — Partial
- Done: the **capability registry** (`harness/capabilities.py`) with one shape for every
  provider/tool/MCP server/skill library and an honest status, exposed as `list_capabilities`
  and over `/capabilities`. This is the seed of the API Vault.
- Done: the **repository browser** (`harness/repo_review.py`) - read-only review of a local
  folder (size, licence, languages, entry points, manifests), exposed as `review_repository`.
  Nothing is executed or installed, per the blueprint's import rule.
- Planned: isolated staging and an integration-report workflow.
**Acceptance (met for the read-only path):** a repo can be reviewed and its code is never run.

## Phase 4 — API Vault — Planned
Import public API catalogs; normalize metadata; connector interface; secure credentials;
outbound destination policy; search/health. **Acceptance:** an API entry is searchable,
shows auth/cost/health, and has a tested connector or an explicit "needs credentials" state.

## Phase 5 — Memory — Partial
- Done: conversation store, memory + profile composed into the prompt, immediate refresh.
- Planned: project index / retrieval with provenance; a resumable `PROJECT_STATE` file.
**Acceptance:** context retrieval returns evidence paths; state survives restart.

## Phase 6 — Skills and multi-agent runtime — Partial
- Done: 519 vendored skills, browsable and loadable; agent/skill listing.
- Planned: specialist roles behind one runtime; bounded task graphs; isolated work areas;
  independent verification. **Acceptance:** a task graph runs with a checkpoint and an
  independent verifier pass.

## Phase 6b — Background jobs (herdr, virtual computers) — Partial
- Done: `harness/workers.py` - a job store and supervisor with three backends: `local`
  (detached Claude Code / Codex), `herdr` (one herdr workspace per job, working / blocked /
  idle tracked) and `cua` (commands or a computer-use agent inside a Docker Linux or Lume
  macOS VM). Host jobs run only known agents, in an isolated git worktree, with timeouts
  and cancel. Engine endpoints `/jobs*` and the app's Background panel. 68 offline checks
  in `tests/test_workers.py`.
- Open: first real run against herdr and cua on the Mac mini; merge/review flow for job
  branches in the app.
**Acceptance:** a herdr job and a VM command job each run to `done` on real hardware.

## Phase 7 — Distributed local models — Planned
Worker registration/heartbeat/capacity; capability-aware routing; authenticated transport.
**Acceptance:** a task runs on a remote worker and survives its disconnect.

## Phase 8 — Creative and external integrations — Partial
- Done: Godot editor workflow (build/validate/compile/run/screenshot) and the vendored
  Godot MCP bridge with on-demand capability domains.
- Done: an injected-input runtime probe (`probe_scene`) drives the running game and reports
  what it received (ported from a proven external harness).
- Planned: route scene edits through Godot's undo manager; assert game state after input
  (a value probe / servo); evaluate Unreal/Blender;
  investigate Higgsfield, Supabase, Cloudflare, Whop and the intended neobanking provider
  with the provider-pattern stubs. **Acceptance:** each provider is verified or has a
  documented stub + manual workflow.

## Phase 9 — User experience and operations — Partial
- Done: dock (tabs/history/modes/attachments/approvals), tabbed settings, Connections
  view, memory editor.
- Planned: task execution traces, cost/resource reporting, CI, backup/restore verification.
**Acceptance:** a run shows a trace and its cost; backup restores cleanly.

---

## Next concrete actions
1. Introduce a `PROJECT_STATE` (resumable) file and load it at session start.
2. Define the DecisionProvider contract + Laya mock (unblocks Phase 2).
3. Prototype the capability registry over the existing tool/MCP schemas.
