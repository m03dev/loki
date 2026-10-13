# Offline-first: models, agents and the credits meter

Loki works with no internet and no account. On first launch it checks this computer and
offers to set it up (Settings > Models shows the same screen any time).

## Models

- **Finds what you have.** Loki asks Ollama which installed models can call tools
  (`/api/show` capabilities) and uses the best one that fits your memory. LM Studio
  (port 1234), a llama.cpp server (8080) and Jan (1337) are picked up automatically too.
- **Downloads what fits.** No model yet? Setup recommends one for your memory (e.g.
  `qwen3:30b` with 32 GB+, `gpt-oss:20b` with 16 GB+, `qwen3:8b` with 8 GB) and downloads it
  through Ollama with a progress bar. A tag that no longer exists falls through to the next.
- **Installs Ollama for you** (macOS: the official DMG into Applications; Windows: the
  official installer). On Linux it shows the official command instead.
- **Makes local models smarter.** Ollama's default context window is too small for an agent
  prompt with tools, which is why local models used to look confused. Loki creates a
  `loki-<model>` copy with a bigger window (`/api/create`, no download, same weights).
- **Makes them faster.** The model is kept loaded (`keep_alive`), local models get a short
  list of core tools instead of every tool, and MCP servers start in the background so the
  window is ready at once.
- **Local first.** `smart` uses the local model when there is one (`LOKI_PREFER=local`, the
  default; untick "Prefer this local model" to prefer cloud). With no internet it only uses
  local models. Pin one with `LOKI_LOCAL_MODEL=<tag>`.

## Agents and background work

Background jobs no longer need Claude Code, Codex or herdr: the built-in **Loki** agent runs
Loki's own loop headless (`loki.py --job`) on Loki's model. Open **Background**:

- **Your agents** - Researcher, Builder, Reviewer and Tester to start; **New agent** makes
  your own (name, instructions, engine, whether it may run commands). Type a task and Run.
- In chat, Loki can hand a task to an agent with the `delegate` tool. It always asks you first.
- A background job edits files only in its own folder (a git worktree when the project is a
  git repo). Commands, moves and deletes need "May run commands", and still pass the command
  policy and the no-shell rule.

## Credits meter

Every model call is counted in `harness_data/usage.jsonl`: tokens in/out (from the
provider, or estimated), time, tokens per second and cost. A line under each reply shows it;
the pill at the top shows today's total; **Settings > Usage** breaks it down by provider.
Local models, free tiers and subscriptions (Claude Code, Codex) cost nothing; paid providers
use list prices - override any in `harness_data/prices.json`, e.g.
`{"openrouter": [0.27, 1.10]}` (USD per million input/output tokens).

## Health snapshot

`harness_data/app/status.json` is rewritten every 30 seconds: the model in use, the local
model, online/offline, hardware, background backends, today's usage and capability states.
Key names only, never values.

## Tests

`python tests/test_offline_e2e.py` runs all of the above against a fake Ollama: model
discovery, the long-context copy, a real tool-calling chat turn, usage, downloads with
fallback, offline routing, and background jobs by the built-in agent as real child processes.
