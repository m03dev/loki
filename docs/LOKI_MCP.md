# The LOKI MCP API

`engine/loki_mcp.py` is a real MCP server (the `mcp` package, already a LOKI dependency) that
exposes LOKI's engine and LOKI's own code to an agent. LOKI Studio's development agent drives LOKI
through it (docs/STUDIO.md); Claude Code, Codex and Ziva can connect to it the same way.

## Drive LOKI from Claude (2026-10-25)

On 2026-10-25 the owner said: "you build loki, how can you not control it - mcp, api, sdk". These tools let Claude
(or any MCP client) use the running LOKI the way the owner does in its window, then check what really happened on
disk.

| Tool | What it does |
|---|---|
| `chat` | Sends a message to LOKI's chat, as the window does, and waits for the answer. The reply includes LOKI's response (OpenCode does the work) and the files that changed. |
| `task` | Starts a Build task and waits until it is done or LOKI says NOT DONE. |
| `agent_status` / `agent_install` | Shows LOKI's agent (OpenCode + CodeGraph) and the workspace; installs whatever is missing. |
| `workspace_files` / `workspace_read` | Lists or reads what is really in LOKI's workspace. Secrets are refused. |

**Setup on the Mac (once):**
1. Open Claude desktop > Settings > Developer > Edit Config.
2. Add this, then restart Claude desktop:
   ```json
   {"mcpServers": {"loki": {"command": "/bin/bash", "args": ["/Users/mohamed/Documents/loki/tools/loki_mcp_launch.sh"]}}}
   ```
   Use your checkout's real path.
3. Claude sessions linked to that Mac then see the `loki` tools.

The launcher finds the checkout's Python, which needs the `mcp` package from `engine/requirements.txt`. It also finds
the running LOKI's data folder and engine token, either in `~/Library/Application Support/Loki` or in the checkout's
`harness_data`. On Windows, use `tools\loki_mcp_launch.cmd` as the command.

## Two halves

**The running LOKI** - through the engine's loopback API with its bridge token
(`harness_data/app/engine.token`, port 8767 = `LOKI_APP_PORT`; override with `LOKI_BRIDGE_URL` /
`LOKI_BRIDGE_TOKEN_FILE`). When LOKI is not running these tools say so plainly; the log tools still
work because they read from disk.

| Tool | What |
| --- | --- |
| `loki_status` | running or not, mode/provider/model, version, update record (last good, on trial, skipped, history) - works when down |
| `models_doctor` | the routing in plain words (`GET /models/doctor`), incl. the main-driver line |
| `settings_get` | Settings > General values; secrets are never sent (only whether one is saved) |
| `settings_set` | change one General setting - **asks** - never a secret or a key |
| `jobs_list` / `job_start` / `job_stop` | background jobs; start and stop **ask** (the engine's own policy still decides) |
| `job_logs` / `engine_logs` | a job's log, or LOKI's engine/app/bridge/studio log, from disk (keys redacted) |
| `world_summary` | the live view: agents at work, jobs, teams, linked machines (GET /world) |
| `memory_search` | what LOKI would recall for a query |
| `tools_health` | every tool's health and one-click fixes |
| `creations_list` | the newest things LOKI made |
| `restart_engine` | restart the engine (`POST /engine/restart`) - **asks** |

**LOKI's code** - only inside the **dev worktree** (`--worktree`; default
`harness_data/studio/worktrees/dev` on branch `studio/dev`, made from the checkout's HEAD). Never the
owner's checkout, never `harness_data/`, `.env` files, `*.token`, keys or `.git`.

| Tool | What |
| --- | --- |
| `read_file` (start_line/end_line), `list_files`, `search_files` (regex, glob) | read |
| `edit_file` (old_text must appear exactly once), `write_file` | change |
| `git_status`, `git_diff` (new files included), `git_log` | git of the dev worktree |
| `read_doc` | HANDOFF.md / ZIVA_TASKS.md / AGENTS.md / docs/BUILD_BRIEF.md, optionally from a heading |
| `run_tests` | `tools/ship.py --check [--only suite]` in the worktree, hermetic like CI and `check_loki` (no LOKI_* settings, no keys) |
| `ship` | `tools/ship.py -m ...` from the worktree - every suite must pass; each machine takes it only through the health-gated updater - **always asks** |

## Approvals

The risky tools (`settings_set`, `job_start`, `job_stop`, `restart_engine`, `ship`) go through
`engine/policy.py` and come back "needs the owner's approval ... Nothing was done" unless:

- the call carries the **approval code** of the program that asked the owner. LOKI Studio starts the
  server with `LOKI_MCP_APPROVAL_SECRET` and computes the code (an HMAC of exactly that tool + those
  arguments) only after the owner clicks Approve. The code is never shown to the model; and
- or the server was started with `--allow-risky`: then the client's OWN permission prompt is the
  gate (Claude Code asks before every MCP tool call unless you allowed it). Use it only with a
  client that asks you.

## Connect a client

stdio (recommended; the client starts the server). Paths are the LOKI checkout on that machine;
on Windows use `harness_data\.venv\Scripts\python.exe` and backslashes.

Claude Code (`.mcp.json` in the project, or `claude mcp add`):

```json
{
  "mcpServers": {
    "loki": {
      "command": "/Users/you/Documents/loki/harness_data/.venv/bin/python",
      "args": ["/Users/you/Documents/loki/engine/loki_mcp.py",
               "--worktree", "/Users/you/Documents/loki/harness_data/studio/worktrees/dev",
               "--allow-risky"]
    }
  }
}
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.loki]
command = "/Users/you/Documents/loki/harness_data/.venv/bin/python"
args = ["/Users/you/Documents/loki/engine/loki_mcp.py", "--worktree", "/Users/you/Documents/loki/harness_data/studio/worktrees/dev"]
```

Ziva / any client that takes the generic `mcp_servers` shape (the same shape as LOKI's own
`engine/mcp_servers.json`):

```json
{
  "mcp_servers": {
    "loki": {
      "command": "C:\\Users\\macul\\Documents\\loki\\harness_data\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\macul\\Documents\\loki\\engine\\loki_mcp.py",
               "--worktree", "C:\\Users\\macul\\Documents\\loki\\harness_data\\studio\\worktrees\\dev"]
    }
  }
}
```

Streamable HTTP on loopback (a client that cannot start processes):

    python engine/loki_mcp.py --http --port 8770 --worktree <dev worktree>

URL `http://127.0.0.1:8770/mcp`, header `Authorization: Bearer <the bridge token>` (the contents of
`harness_data/app/engine.token`; it changes when the engine restarts). Anything else gets 401; only
`127.0.0.1` / `localhost` Host headers are accepted.

`python engine/loki_mcp.py --list` prints the tools.

LOKI Studio is an MCP server too: `studio/studio_mcp.py` gives a client Studio's hands in the live Godot editor
(through the LOKI Studio plugin), the offline Godot docs, the project index and Studio's sessions - see
docs/STUDIO.md "Studio as an MCP server".

## Tests

`tests/test_studio.py` section 4: every tool through the mcp client in-process, the jail, approvals
(refused without a code, a code is valid for one exact call), a fake running engine (status,
doctor, settings without secrets, jobs, restart), the stdio server process and the HTTP token check.
