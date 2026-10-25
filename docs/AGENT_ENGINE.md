# The agent: OpenCode + CodeGraph

On 2026-10-25 the owner said: "it says but it doesn't actually do ... get rid of it, replace it ... just make my agent
actually work". They picked "a proven agent + CodeGraph".

| Part | What it is | Where |
|---|---|---|
| OpenCode | An open-source coding agent ([anomalyco/opencode](https://github.com/anomalyco/opencode), MIT): read, write, edit, bash, git, MCP | `engine/opencode_engine.py`, `loki.run_opencode` |
| CodeGraph | A pre-indexed graph of the code ([colbymchenry/codegraph](https://github.com/colbymchenry/codegraph), MIT), served to OpenCode as an MCP server (`codegraph serve --mcp`, tool `codegraph_explore`) | `opencode_engine.build_config`, `ensure_index` |

## One turn

1. The window's Send (`/chat`) and Build tasks (`/task`) call `run_opencode`. They do not call LOKI's old loop.
2. LOKI writes `<data>/opencode/opencode.json`:
   - **Providers:** every connected provider, as an OpenAI-compatible provider `loki-<name>`. The key goes in an
     environment variable (`LOKI_OC_KEY_<NAME>`) and is never written to the file.
   - **CodeGraph:** added as an MCP server.
   - **Permissions:** everything inside the workspace is allowed, LOKI's destructive command list is denied, and
     paths outside the workspace are denied. `opencode run` cannot ask a human.
   - **Plan / Ask mode:** read-only, using OpenCode's `plan` agent.
3. LOKI runs `opencode run --format json --dir <workspace> --session <id> --model loki-<provider>/<model> <message>`.
4. Every tool call OpenCode makes is shown in the window as it runs and is counted.
5. If a provider fails before doing anything, the next connected provider is tried, up to 3 in total.
6. A reply that claims the work is done when no tool ran gets one push back. If still nothing runs, the reply says
   **NOT DONE**.
7. Each LOKI conversation keeps one OpenCode session (`<data>/opencode/sessions.json`).

## Install

Settings > Agents > Install, or the "Install it" notice over the chat. Both run `npm i -g opencode-ai@latest` and
`npm i -g @colbymchenry/codegraph`. CodeGraph indexes the workspace on first use (`codegraph init --yes`) and then
keeps the index in sync itself.

`LOKI_OPENCODE_MODEL=provider/model` pins one of OpenCode's own models, for example a free OpenCode Zen model.
`LOKI_AGENT_ENGINE=loki` switches back to the old loop; Settings > Agents has the same switch.

## Still on the old loop (next stage)

Background jobs (`workers.py` / `run_job`), teams, and LOKI's own self-improvement jobs still use the old loop. They
move next: a job becomes `opencode run` in the job's workspace.

Tests: `tests/test_opencode_engine.py` (a fake `opencode` binary that really runs git) and `tests/test_honest_chat.py`.
