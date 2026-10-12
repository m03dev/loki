# Loki — Session Log

Concise dated records of meaningful work. Newest at the top.

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
