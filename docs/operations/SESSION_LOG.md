# Loki — Session Log

Concise dated records of meaningful work. Newest at the top.

---

## 2026-10-12 (session 8) - The API Vault (the real catalog)

**Work completed** (`87a4770`)
- `harness/api_vault.py`: a searchable index of APIs (id, name, url, provider,
  categories, auth, docs, source) with `import_apis_guru()`, which normalizes the
  apis.guru catalog - the preferred version's title, `x-origin` url, `x-providerName`,
  `x-apisguru-categories` and its security scheme into a key/oauth hint.
- `tools/build_api_vault.py`: fetches the catalog and folds in Loki's 38 model providers
  (name + base_url only - never a key). Seed committed: **2,097 entries, 363 KiB**,
  searchable offline.
- `api_vault_lookup` tool + `GET /vault` / `POST /vault`. The shipped seed is read-only;
  'add' writes to harness_data/api_vault_extra.json, which search merges over the seed.
- Traps hit and fixed: apis.guru answers **403 to urllib's default User-Agent** (set one),
  and embedded `
` escapes get mangled when a patch is written through a heredoc - use
  `chr(10)` in generated code.
- public-apis / public-api-lists / davemachado are now marked **Superseded**: apis.guru is
  the larger, machine-readable superset and is already in the vault.

**Tests:** 331 passed, 0 failed.

---

## 2026-10-12 (session 7) - Vercel design, and the Herdr session registry

**Work completed**
- **Vercel design** in the dock (`ab3fc7e`): a pure-black canvas, #EDEDED text at full
  contrast, hairline #333 borders, small radii and one #0070F3 focus accent, applied as a
  Theme so every child and dialog inherits it. Verified headlessly (composer #0a0a0a r8,
  hover #1a1a1a, focus border #0070f3, menu #0a0a0a).
- **Agent-session registry** (`67a1b30`): `harness/sessions.py` + the `agent_sessions` tool
  + `/sessions` on the bridge. Adopts Herdr's (herdr.dev) core idea - a shared list of
  agent sessions each working / blocked / idle / done, with a summary that names who is
  stuck - as the blueprint's multi-agent runtime (9) and worker registry (7.1).

**Tests:** 313 passed, 0 failed.

---

## 2026-10-12 (session 6) - The document's systems: providers, project state, repo browser

**Work completed**
- Imported **awesome-free-llm-apis** (github.com/mnfst/awesome-free-llm-apis): 11 new
  OpenAI-compatible providers (aion, cohere, zai, huggingface, kilocode, llm7, modelscope,
  nvidia, ollama-cloud, ovh, siliconflow), documented and tested. Kept out of SMART_ORDER.
- **Resumable project state** (blueprint 7.3): `harness/project_state.py` + the
  `project_state` tool + `/state` on the bridge, over harness_data/project_state.json.
- **Capability registry** (blueprint 3.3, the API Vault seed): `harness/capabilities.py`
  with one shape for every provider/tool/MCP server/skill library, `list_capabilities` and
  `/capabilities`. (Added by a second agent committing to this repo - see below.)
- **Repository browser** (blueprint 5.1): `harness/repo_review.py` + the `review_repository`
  tool - read-only, never executes or installs anything.

**CONCURRENCY NOTE (important)**
- A SECOND writer is committing and pushing to this same repo: commit `8808db7`
  ('Add the capability registry') was made at 18:43 by m03dev and was not made by this
  session. It briefly clobbered a duplicate `capability_registry` this session had added;
  that duplicate was reverted and the other writer's implementation kept. Both landed
  coherently. If two agents are meant to be working this repo, they must pull --rebase
  before every commit and keep to separate files.

**Tests:** 301 passed, 0 failed.

---

## 2026-10-12 (session 5) - Rounded controls and a bubble for the typing box

**Feedback.** "where is the chat bubble when you're typing - everything is beveled and nice
and rounded ... do that". Session 4 only rounded the SENT message; the composer was still a
plain box and nothing else was rounded.

**Work completed**
- `_rounded_copy` / `_round` / `_apply_rounding`: each control's CURRENT stylebox is
  duplicated and only its corners and padding change, so the editor's own colours are kept.
  Deliberately NOT a replacement theme - that is what read as "just darker".
- The typing box (`_input_edit`) is now the bubble: StyleBoxFlat corner radius 12, padding
  12x9, across normal/focus/read_only.
- Every composer and header button, the chat tabs and the three dropdown panels are rounded.
- The overflow menu was reordered chat-first (New chat, Rename, Copy, Memory | Settings,
  ECC, Sync | Inspect, Validate, Run task, Clear attachments); ids are unchanged.

**Tests:** 248 passed, 0 failed. Rounding confirmed headlessly: composer box is StyleBoxFlat
corner=12 pad=12; button hover corner=6; tab corner=6.
**Not visually confirmed** (`view_image` only reads the `ai` project).

---

## 2026-10-12 (session 4) - Keep Ziva's look: bubble + Enter to send (theme reverted)

**Feedback.** The session-3 dark theme read as "just darker" and looked LESS like Ziva; the
dock before it was better. Reverted.

**Work completed**
- Reverted the Ziva-style Theme and the `_draw` canvas from `loki_dock.gd`.
- Your messages now render as a right-aligned BUBBLE (a `[bgcolor]` block with padding);
  Loki's replies stay plain text. A truly rounded bubble needs a message-list container,
  which conflicts with the deliberate single self-scrolling RichTextLabel transcript, so this
  is the closest the transcript can do.
- The composer sends on ENTER and inserts a line on Shift+Enter (was Ctrl+Enter only), the
  way Ziva's composer works. Enter is ignored while the box is empty.
- Placeholder updated to say so.

**Tests:** 248 passed, 0 failed; dock compiles; headless probe builds.
**Not visually confirmed** (`view_image` reads only the `ai` project, which must not be written to).

---

## 2026-10-12 (session 3) - Ziva-style dock theme

**Work completed**
- Restyled the Loki dock toward Ziva's visual language: a near-black canvas drawn in
  `_draw()`, quietly rounded fields, one muted secondary colour and one accent, applied
  through a single `Theme` on the dock root so the tabs, transcript, composer, icon row
  and every dialog inherit it. Palette: bg #0d0d0f, surface #17171a, field #1c1c20,
  hover #26262b, border #2e2e34, text #ececed, muted #8b8b92, accent #6ba1ff.

**Finding (important)**
- Ziva's own GUI is a **compiled CEF web app** (`addons/ziva_agent/bin/*/chrome_*.pak`,
  a 7.8 MB GDExtension DLL, a 122 MB `zivacode.exe`). There is **no readable HTML/CSS/JS**
  - the only loose UI file is `icon.svg`. Loki's dock therefore matches Ziva's LOOK, not
  its markup; a pixel-exact copy is not possible from a compiled application.

**Tests / verification**
- `loki_dock.gd` compiles; `tests/test_loki.py` -> 248 passed, 0 failed; the headless dock
  probe builds (`ready=true tabs=1`); the theme values are read back and confirmed
  (label #ececed, field #1c1c20, accent focus border, hover #26262b, tab #17171a).
- **Not visually confirmed**: `view_image` reads only the `ai` project, which must not be
  written to, so the PrintWindow screenshot could not be inspected. The Loki editor is
  open for a human look.

**Residual gap vs Ziva**
- Ziva's right-aligned rounded user BUBBLES need a message-list container; Loki's
  transcript is one self-scrolling RichTextLabel (a deliberate anti-min-size-blowup
  choice) that cannot render a true padded bubble. Staged, not done.

---

## 2026-10-12 (session 2) - Laya, an upstream contribution, and the input probe

**Work completed**
- Integrated **Laya** (github.com/receptron/laya) as Loki's local-first decision provider:
  `laya.py` (HTTP + a local Node backend via `laya_driver.mjs`, delegating to the real
  `@receptron/laya` package), `decisions.py` (Laya-first routing with Jev fallback and
  recorded disagreements), wired into `approve()` and loop detection; the bridge `/jev`
  and the doctor report it. Installed `@receptron/laya` into `harness_data/laya` (gitignored).
- Prepared an upstream contribution to `receptron/laya` in `contrib/laya/`
  (`0001-systemone-offline-tests.patch` + README): a `Laya.fromParts()` test seam and
  offline tests for `systemOne`'s answer shaping. Verified in the clone: `yarn test`
  13 pass / 1 skip, `yarn typecheck` clean, `yarn lint` no errors.
- Ported the injected-input discipline into Loki: `addons/loki/harness/loki_probe.gd` +
  the `probe_scene` tool run a scene in a real window, feed it timed inputs (action/key/
  mouse/motion), hold each press for at least two PHYSICS frames, and report what the game
  actually received, plus a screenshot.

**Files changed**
- `addons/loki/harness/`: `laya.py`, `laya_driver.mjs`, `decisions.py`, `loki_probe.gd`,
  `loki.py`, `.env.example`; plus `loki_bridge.py`, `tools/loki_doctor.py`,
  `tests/test_loki.py`, `.gitignore`.
- `contrib/laya/0001-systemone-offline-tests.patch`, `contrib/laya/README.md` (new).
- docs: this log, CURRENT_STATE, IMPLEMENTATION_PLAN, INTEGRATION_REGISTRY.

**Tests executed and results**
- `tests/test_loki.py` -> **248 passed, 0 failed** (was 200 at session start).
- Laya driver error paths exercised through Node (missing package, empty stdin).
- `probe_scene` run end-to-end against a throwaway Godot project: 2/2 inputs delivered,
  the game printed `INPUT_SEEN: ui_right`, and the 0 ms key was clamped to 2 physics frames.

**Known issues**
- Laya's model forward pass is not exercised (needs the 1.7 GB ONNX weights on first use).
- The input probe reports delivery and a screenshot; it does not yet assert game-state
  changes (a value probe / servo is the next step).

**Next concrete actions**
1. Assert game state after input (a value probe / servo), not only delivery.
2. Fork and open a PR for the Laya patch if it should be submitted.
3. Resumable `PROJECT_STATE` file.

---

## 2026-10-12 — Audit, command policy, and the durable documentation

**Work completed**
- Located and confirmed the checkout (`C:\Users\macul\Documents\loki`, `master`,
  `github.com/m03dev/loki`), clean tree.
- Audited the request lifecycle, providers, Jev (present), Laya (absent), memory, tools
  and MCP gating, security posture, tests, and docs.
- Ran the baseline suite: **200 offline checks green**.
- **Phase 1 implementation:** added `command_policy()` to `addons/loki/harness/loki.py`
  and wired it into `run_command` so destructive/remote-exec command strings are refused
  before the shell is reached. Pure, testable, overridable via `LOKI_COMMAND_POLICY=0`.
- Added 18 tests (section "command policy (the run_command guard)"). Suite now
  **218 passed, 0 failed**.
- Created the permanent documentation tree under `docs/`: master blueprint, current
  state, target architecture, implementation plan, architecture decisions, security
  baseline, recovery and resume, session log, integration registry.

**Files changed**
- `addons/loki/harness/loki.py` (+ `command_policy`, `_DESTRUCTIVE_SNIPPETS`,
  `_REMOTE_EXEC_TOKENS`; `run_command` guarded).
- `tests/test_loki.py` (+18 checks).
- `docs/LOKI_MASTER_BLUEPRINT.md`, `docs/architecture/CURRENT_STATE.md`,
  `docs/architecture/TARGET_ARCHITECTURE.md`, `docs/roadmap/IMPLEMENTATION_PLAN.md`,
  `docs/integrations/INTEGRATION_REGISTRY.md`,
  `docs/decisions/ARCHITECTURE_DECISIONS.md`, `docs/operations/RECOVERY_AND_RESUME.md`,
  `docs/operations/SESSION_LOG.md`, `docs/security/SECURITY_BASELINE.md`.

**Tests executed and results**
- `harness_data/.venv/Scripts/python.exe tests/test_loki.py` -> 218 passed, 0 failed.
- (Not run this session) `--live` (needs a model + MCP servers).

**Known issues**
- Laya not implemented; symlink-escape path untested; no outbound destination policy;
  `run_command` still a shell string (guard only).

**Blockers**
- None for the work above.

**Next concrete actions**
1. Resumable `PROJECT_STATE` file loaded at session start.
2. DecisionProvider contract + Laya mock.
3. Capability registry prototype over existing tool/MCP schemas.
