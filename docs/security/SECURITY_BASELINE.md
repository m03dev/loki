# Loki — Security Baseline

Controls that exist, known issues, and remediation status. Security is a core
requirement, not a later pass.

## Filesystem access — Controlled
- All file tools resolve through `resolve_in_workspace()`; any path escaping `WORKSPACE`
  raises `ValueError`. Reads, writes, edits, moves, deletes, and directory walks are all
  rooted there.
- `res://`, `./`, and quoted prefixes are normalized; `..` traversal is rejected
  (covered by the "filesystem sandbox" test section).
- Symlinks are resolved before the containment check, so a link out of the workspace is
  denied (tested in tests/test_hardening.py).

## Subprocess execution — Structured (no shell)
- `run_command` no longer uses a shell. `harness/safe_exec.py` splits the command into an
  argv with `shlex` and runs it with `shell=False`, a timeout and stdin closed.
- `a && b` chains run as separate steps that stop at the first failure. Every other shell
  feature is refused with a reason before anything runs: `|`, `||`, `;`, `&`, `>`, `>>`,
  `<`, `$(...)`, `${...}`, backticks and multi-line input. Quoted text is data, so
  `git commit -m "a; b"` works.
- The executable must resolve on PATH (or to a file in the workspace); cmd.exe built-ins
  (`dir`, `type`, ...) are refused with a pointer to the file tools.
- `command_policy(command)` still runs first as defence in depth (destructive shapes,
  pipe-to-interpreter). `LOKI_COMMAND_POLICY=0` disables only that guard, never the no-shell
  rule.
- There is no `shell=True`, `os.system` or `os.popen` left in the code (a test pins it).
- `run_command` / `run_godot` / `open_godot` are **not offered to the model** by default and
  sit in the `system` category (off by default).

## Policy engine — Hardcoded
`harness/policy.py` decides **allow / ask / deny** from fixed rules, before any approval
prompt. No model is consulted.
- DENY: command policy or no-shell parser rejects the command; any path argument escapes
  the workspace (symlinks are resolved first); a capability is off, changed since approval,
  missing requirements or not granted the permission; a network host is not loopback, not
  in `LOKI_NET_ALLOW` and not granted to the capability.
- ASK: dangerous tools. `run_command`, `move_file`, `open_godot` are *decidable*;
  `delete_file` always asks.
- `policy.final()` is the only place a decision provider's "allow" counts: it can turn a
  decidable ASK into ALLOW and nothing else. A DENY is never shown to the user as a prompt.

## Capabilities — Discovered, never executed
`capabilities/<name>/manifest.json` (built-in, trusted) and
`harness_data/capabilities/<name>/manifest.json` (user, untrusted) are parsed as JSON only.
Nothing is imported because a manifest exists. A capability stays off until the user turns
it on in Settings > Capabilities; that records the manifest fingerprint and the granted
permissions. A changed manifest drops to "changed" and grants nothing until re-approved.
User manifests can never be on by default nor shadow a built-in. Built-ins may be on by
default only without high-risk permissions (`network`, `process:spawn`, `computer:host`).

## Skills — Untrusted text
`harness/skill_scan.py` runs before a skill or agent file reaches the model. Text that tries
to override Loki's rules (ignore previous instructions, `LOKI_AUTO_APPROVE=1`,
`bypassPermissions`, `--dangerously-skip-permissions`, disabling the policy/sandbox) or
frontmatter that grants permissions is **refused**. Skills that ship executables are loaded
with a note that Loki never runs them. `allowed-tools` frontmatter is ignored.

## Permission model
- Dangerous tools (`run_command`, `open_godot`, `move_file`, `delete_file`) route through
  `approve()`. In the editor the bridge overrides `approve()` with the dock's UI; headless
  it prompts on stdin. `LOKI_AUTO_APPROVE=1` bypasses prompts for unattended runs — do not
  enable it where destructive operations are possible.
- Jev may skip a prompt for a confident-safe call; it can never force an action. The human
  path stays authoritative.
- Modes constrain capability: Plan cannot write/run/delete; Ask changes nothing.

## Network access
- Model calls go only to the configured provider endpoints. MCP servers are external
  processes (`uvx`) launched per `mcp_servers.json`, gated by `_server_skip_reason`
  (`enabled` / `requires_env` / `requires_cmd`).
- **Issue:** no general outbound destination allowlist for future API-vault connectors.
  **Remediation:** add a destination policy with SSRF/private-range/redirect checks when
  the API Vault lands (Phase 4).

## Credentials and secrets
- Keys live in `harness_data/.env` (git-ignored); the addon ships `.env.example` only.
- The Connections view deliberately never includes credential values.
- `keys/loki_public.pem` is a public verification key; the private signing key is never in
  the repo.
- **Rule:** secrets never go into memory, prompts, logs, or git.

## Supply chain
- Vendored libraries are fetched into `harness_data/vendor/` by `ecc_sync.py` and treated
  as untrusted instruction content; skills cannot grant permissions or override policy.
- **Planned:** pin revisions/hashes and record provenance in the integration registry.

## Agent loops and timeouts
- Exact-signature repeat detection plus an optional Laya/Jev "repeating without progress"
  check.
- Safety ceilings hold even when the per-request budgets are unlimited:
  `LOKI_HARD_MAX_TURNS` (default 400 model/tool cycles) and `LOKI_HARD_DEADLINE`
  (default 6 hours).
- Every model HTTP call has a timeout (`LOKI_MODEL_TIMEOUT`, default 180 s); background
  jobs have their own time limit; health and federation probes use 2-3 s timeouts.

## Known issues (tracked)
1. ~~Symlink-escape path is untested.~~ Tested (tests/test_hardening.py).
2. ~~`run_command` shell string.~~ Replaced by structured execution (safe_exec.py).
3. Outbound destination policy exists for capability health checks and federation; model
   provider endpoints are configured by the user and not yet routed through it.
4. `godot_omni` MCP backend must stay disabled alongside `addons/godot_ai` +
   `addons/godot_omni` (port fight terminates the editor). Keep them disabled.
