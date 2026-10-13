# Loki the conductor

Everything starts with Loki. It plans, keeps the conversation and owns the tools. When a step
needs a specialist, it calls the `conductor` tool with a role, and `harness/conductor.py`
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
| Perplexity Sonar | `research` | `POST https://api.perplexity.ai/chat/completions`, model `sonar`; answer + numbered sources | proprietary API | `PERPLEXITY_API_KEY` in `harness_data/.env`, enable **perplexity** |
| Crawl4AI | `read_web` | `runners/web_read.py` (headless Chromium → markdown) | Apache-2.0 | `pip install crawl4ai && crawl4ai-setup` into Loki's venv, enable **crawl4ai** |
| Scrapling | `read_web` | `runners/web_read.py` (`Fetcher.get`) | BSD-3-Clause | `pip install scrapling` into Loki's venv, enable **scrapling** |
| Firecrawl (self-hosted) | `read_web` | `POST {LOKI_FIRECRAWL_URL}/v2/scrape`, formats markdown | AGPL-3.0 server (Loki only talks HTTP to it) | `docker compose up` from the Firecrawl repo (port 3002), enable **firecrawl** |
| Browser Use | `browse` | `runners/browse.py` (`Agent(task, llm=ChatOpenAI(...))`); **always asks you first** | MIT | `pip install browser-use` + `LOKI_BROWSE_MODEL` / key, enable **browser-use** |
| Hindsight | `remember`, `recall` | `runners/hindsight.py` (`retain` / `recall`, bank `loki`) against `HINDSIGHT_URL` | MIT | run the Hindsight server (docker, :8888), `pip install hindsight-client`, enable **hindsight** |
| Hermes Agent | background job | interactive `hermes` in a herdr workspace, task sent as a prompt | MIT | install Hermes, enable **herdr** and **hermes-agent**, pick it in Background |
| Headroom | in the loop | `headroom.compress(messages, model)` on a copy before each model call | Apache-2.0 | `pip install "headroom-ai[all]"`, enable **headroom** |
| SkillSpector | in the loop | `skillspector scan <skill> --format json --no-llm`; high/critical findings block a skill | reported Apache-2.0 | install from NVIDIA/SkillSpector, enable **skillspector** |
| Kiln | outside Loki | eval / fine-tune workbench for Loki's prompts; no runtime hook | MIT library, fair-code app | install the Kiln app when you start measuring Loki |

`read_web` order: `LOKI_READ_ORDER=crawl4ai,scrapling,firecrawl` (first enabled wins).

## Rules that stay true

- Every role goes through the policy engine first: capability on, permission granted,
  network host allowed. Off means the role is invisible to the model.
- Heavy libraries run in `runners/` child processes (`python -I`, no shell, a timeout) so a
  missing or broken library can never take the engine down; they report "not installed".
- The model cannot start background jobs; you do (Background panel).
- `browse` asks every time - no decision provider can skip that prompt.
- Headroom compresses a *copy*: the conversation Loki keeps is never rewritten.

## Not verified against the live services yet

Request shapes follow each project's docs; every integration is tested offline against
fakes (`tests/test_integrations.py`). The first real call per service is the acceptance
test - a mismatch is a small fix in `conductor.py` or the runner.
