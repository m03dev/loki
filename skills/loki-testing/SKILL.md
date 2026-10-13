---
name: loki-testing
description: How to run and extend Loki's own test suites. Use before and after changing anything in addons/loki, app/, tools/ or capabilities/.
---

# Testing Loki

Loki has four offline suites. They need no network, no model and no Godot.

| Suite | What it covers | Command (from the repo root) |
|---|---|---|
| `tests/test_loki.py` | the agent, tools, providers, bridge, app launcher | `harness_data/.venv/bin/python tests/test_loki.py` |
| `tests/test_workers.py` | background jobs: local, herdr, cua | `harness_data/.venv/bin/python tests/test_workers.py` |
| `tests/test_hardening.py` | no-shell execution, policy engine, manifests, skills, federation, knowledge | `harness_data/.venv/bin/python tests/test_hardening.py` |
| `tests/test_integrations.py` | the conductor and its specialists, Hermes jobs, the brain map | `harness_data/.venv/bin/python tests/test_integrations.py` |

On Windows use `harness_data\.venv\Scripts\python.exe` instead of `harness_data/.venv/bin/python`.

## Steps

1. Run all four suites **before** changing code and note the counts. A suite prints
   `N passed, M failed` and exits non-zero on any failure.
2. Make the change.
3. Run the suites again. Every check that passed before must still pass.
4. Add a `check("what it proves", condition)` for the behaviour you added or fixed, in the
   suite that owns that area. Name checks as plain sentences.
5. `tests/test_loki.py --live` also talks to MCP and a real model. Run it only when asked;
   it needs a model to be reachable.

## Known environment failures

On a fresh clone, three checks in `tests/test_loki.py` about vendored skill libraries
(GodotPrompter) fail until setup has downloaded them (`sync_ecc`). They are not caused by
your change.

## Rules

- Do not delete or weaken an existing check to make a suite pass. Fix the code, or explain
  why the check is wrong and ask.
- Tests must stay offline: fake herdr, cua, models and the network at their boundary, as
  `tests/test_workers.py` does.
