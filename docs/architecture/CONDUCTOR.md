# Loki the conductor

Everything starts with Loki. It plans, keeps the conversation and owns the tools. When a step
needs a specialist, it calls the `conductor` tool with a role, and `engine/conductor.py`
sends the step to whichever enabled capability can do it. A role only appears in Loki's
instructions once something behind it is switched on (Settings > Capabilities).

```
                              Loki (conductor)
       ┌──────────┬───────────┬───────┴────┬──────────────┬───────────────┐
   research    read_web     browse     remember/recall   background jobs   in the loop
  Perplexity  crawl4ai    Browser Use    Hindsight      Claude Code, Codex  Headroom
              Scrapling   (asks you)                    Hermes (herdr)      SkillSpector
              Firecrawl                                 cua VMs
```

| Project | Role | How Loki uses it | Licence | Turn it on |
|---|---|---|---|---|
| Vane | `research` (first choice) | `GET /api/providers` then `POST /api/search` (sources web, speed mode) on `VANE_URL` (default http://127.0.0.1:3000); answer + numbered sources. Private: your SearxNG and your local models | MIT | `docker run -d -p 3000:3000 -v vane-data:/home/vane/data --name vane itzcrazykns1337/vane:latest`, set a model in its setup screen, enable **vane** |
| Perplexity Sonar | `research` | `POST https://api.perplexity.ai/chat/completions`, model `sonar`; answer + numbered sources | proprietary API | `PERPLEXITY_API_KEY` in `harness_data/.env`, enable **perplexity** |
| Crawl4AI | `read_web` | `runners/web_read.py` (headless Chromium → markdown) | Apache-2.0 | `pip install crawl4ai && crawl4ai-setup` into Loki's venv, enable **crawl4ai** |
| Scrapling | `read_web` | `runners/web_read.py` (`Fetcher.get`) | BSD-3-Clause | `pip install scrapling` into Loki's venv, enable **scrapling** |
| Firecrawl (self-hosted) | `read_web` | `POST {LOKI_FIRECRAWL_URL}/v2/scrape`, formats markdown | AGPL-3.0 server (Loki only talks HTTP to it) | `docker compose up` from the Firecrawl repo (port 3002), enable **firecrawl** |
| Browser Use | `browse` | `runners/browse.py` (`Agent(task, llm=ChatOpenAI(...))`); **always asks you first** | MIT | `pip install browser-use` + `LOKI_BROWSE_MODEL` / key, enable **browser-use** |
| Hindsight | `remember`, `recall` | `runners/hindsight.py` (`retain` / `recall`, bank `loki`) against `HINDSIGHT_URL` | MIT | run the Hindsight server (docker, :8888), `pip install hindsight-client`, enable **hindsight** |
| Hermes Agent | background job | `hermes -z <task>` (one-shot, final answer only) on This computer, or interactive `hermes` in a herdr workspace; never `--yolo` | MIT | install Hermes, enable **hermes-agent** (and **herdr** for herdr jobs), pick it in Background. `LOKI_HERMES_MODEL` / `LOKI_HERMES_PROVIDER` pick its model |
| Headroom | in the loop | `headroom.compress(messages, model)` on a copy before each model call | Apache-2.0 | `pip install "headroom-ai[all]"`, enable **headroom** |
| SkillSpector | in the loop | `skillspector scan <skill> --format json --no-llm`; high/critical findings block a skill | reported Apache-2.0 | install from NVIDIA/SkillSpector, enable **skillspector** |
| Kiln | outside Loki | eval / fine-tune workbench for Loki's prompts; no runtime hook | MIT library, fair-code app | install the Kiln app when you start measuring Loki |

`read_web` order: `LOKI_READ_ORDER=crawl4ai,scrapling,firecrawl`; `research` order: `LOKI_RESEARCH_ORDER=vane,perplexity` (first enabled wins).

Agents: the conductor can hand a longer task to one of your agents with `delegate` (always asks you); see docs/operations/OFFLINE_FIRST.md.

## Rules that stay true

- Every role goes through the policy engine first: capability on, permission granted,
  network host allowed. Off means the role is invisible to the model.
- Heavy libraries run in `runners/` child processes (`python -I`, no shell, a timeout) so a
  missing or broken library can never take the engine down; they report "not installed".
- Background jobs start only with your OK: you start them in Background, or approve Loki's `delegate` request.
- `browse` asks every time - no decision provider can skip that prompt.
- Headroom compresses a *copy*: the conversation Loki keeps is never rewritten.

## Not verified against the live services yet

Request shapes follow each project's docs; every integration is tested offline against
fakes (`tests/test_integrations.py`). The first real call per service is the acceptance
test - a mismatch is a small fix in `conductor.py` or the runner.

### Hermes with Perplexity

Hermes has no Perplexity provider of its own, but it is an MCP client. To let a Hermes job
search the live web with Perplexity, add the official server to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  perplexity:
    command: npx
    args: ["-y", "@perplexity-ai/mcp-server"]
    env:
      PERPLEXITY_API_KEY: "pplx-..."
```

It gives Hermes `perplexity_search`, `perplexity_ask`, `perplexity_research` and
`perplexity_reason`. Loki itself uses Perplexity directly as its `research` specialist.
