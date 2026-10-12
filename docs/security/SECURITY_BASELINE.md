# Loki — Security Baseline

Controls that exist, known issues, and remediation status. Security is a core
requirement, not a later pass.

## Filesystem access — Controlled
- All file tools resolve through `resolve_in_workspace()`; any path escaping `WORKSPACE`
  raises `ValueError`. Reads, writes, edits, moves, deletes, and directory walks are all
  rooted there.
- `res://`, `./`, and quoted prefixes are normalized; `..` traversal is rejected
  (covered by the "filesystem sandbox" test section).
- **Issue:** symlink escapes are not explicitly tested. **Remediation:** resolve the real
  path and assert containment before use; add a test with a symlink out of the workspace.

## Subprocess execution — Guarded
- `run_command` executes a **shell string** via `subprocess.run(..., shell=True,
  cwd=WORKSPACE, timeout=...)`.
- New this session: `command_policy(command)` runs first and refuses, before the shell is
  reached:
  - destructive shapes: `rm -rf /`, `rm -fr /`, `rm -rf ~`, `del /f /s /q`, `rd /s /q`,
    `format `, `mkfs`, `diskpart`, `fdisk`, `wipefs`, `dd if=`, `> /dev/sda|nvme`,
    fork bombs, `shutdown`/`reboot`/`poweroff`, `cipher /w`, `vssadmin`, `bcdedit`,
    `bootrec`, `takeown`, `icacls`, `reg delete|add`, `net user|localgroup`,
    `netsh advfirewall`, `chmod/chown -R 777 /`;
  - pipe-to-interpreter: `| sh`, `| bash`, `| zsh`, `| python`, `| perl`, `| iex`,
    `invoke-expression`, `iex(`, `eval(`.
  - Whitespace-normalized, case-insensitive; empty commands refused. Pure function;
    override with `LOKI_COMMAND_POLICY=0` for a trusted unattended context.
- `run_command` / `run_godot` / `open_godot` are **not offered to the model** by default
  and are in the `system` category (off by default); when called they pass through
  `approve()`.
- **Status:** the policy is a **guard, not a sandbox**. Structured argument execution is
  the Phase-1 target (see the roadmap); the guard remains as defence in depth.

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

## Agent loops
- Exact-signature repeat detection plus an optional Jev-based "repeating without progress"
  check; the unbounded loop is opt-in only.

## Known issues (tracked)
1. Symlink-escape path is untested. (remediation above)
2. `run_command` shell string not yet replaced by structured execution. (Phase 1)
3. No outbound destination policy yet. (Phase 4)
4. `godot_omni` MCP backend must stay disabled alongside `addons/godot_ai` +
   `addons/godot_omni` (port fight terminates the editor). Keep them disabled.
