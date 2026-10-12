# Loki — Integration Registry

Status of every repository, provider, API, service, and skill the blueprint asks about.
Legend — **Verified**: identity confirmed and integrated/working; **Partial**: present but
incomplete; **Planned**: intended, no code yet; **Blocked**: cannot proceed without
something; **Rejected**: deliberately not adopted.

| Integration | Canonical URL | Capability | Identity / availability | License | Loki overlap | Approach | Status | User action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Loki** | github.com/m03dev/loki | the project itself | confirmed checkout | MIT | — | — | Verified | none |
| **Jev** (TypeSafe System One) | thejevai.com/docs | typed decisions | API; key-gated | hosted API | `harness/jev.py` risk gate + loop detection | direct client + optional MCP | Verified (optional) | set `TYPESAFE_API_KEY` to enable |
| **Laya** | github.com/receptron/laya | local-first decision provider | public repo | MIT (weights Apache-2.0) | `harness/laya.py` + `harness/decisions.py` | Jev-compatible client: HTTP `system_one` endpoint or a local Node driver delegating to `@receptron/laya`; Laya-first routing with Jev fallback | Verified (the forward pass itself needs the 1.7 GB weights, so it is not run offline) | none |
| **Laya (upstream patch)** | github.com/receptron/laya | offline testability for `systemOne` | prepared in `contrib/laya/` | MIT | improves the dependency | `Laya.fromParts()` seam + offline tests; verified with `yarn test`/`typecheck`/`lint` | Prepared (not submitted) | approve a fork + PR |
| **OpenViking** | github.com/volcengine/OpenViking | context/knowledge/memory/skill retrieval | public repo | check before use | current memory system works | evaluate as backend behind a memory interface; adopt patterns only | Planned | none |
| **public-apis** | github.com/public-apis/public-apis | API catalog | public repo | check | none | import/normalize into the API Vault | Planned | none |
| **public-api-lists** | github.com/public-api-lists/public-api-lists | API catalog | public repo | check | none | as above | Planned | none |
| **davemachado/public-api** | github.com/davemachado/public-api | API catalog | public repo (may be archived) | check | none | as above | Planned | none |
| **anthropics/skills** | github.com/anthropics/skills | agent skills | public repo | check | 519 vendored skills already | review and import relevant skills | Planned | none |
| **deepseek-harness** | github.com/deepseek-ai/deepseek-harness | harness patterns | verify existence | check | Loki has its own loop | extract patterns; write a comparison first | Planned | none |
| **awesome-harness-engineering** (walkinglabs / yenanjing) | github.com/walkinglabs/... , github.com/yenanjing/... | harness references | verify existence | check | — | reference only | Planned | none |
| **Godot MCP (vendored)** | addons/loki/godot_mcp | live editor bridge | vendored, MIT | MIT (c) 2026 Johnny D | core capability surface | bundled in the addon | Verified | none |
| **godot-editor-mcp server** | uvx package | MCP server | external, `uvx` on PATH | per package | 26 domains, on-demand unlock | MCP via `mcp_servers.json` | Verified | install `uvx` |
| **godot_run** | Coding-Solo/@coding-solo/godot-mcp | run/stop/debug game | `npx`-gated | per package | overlaps `play_scene` | opt-in MCP server | Verified | `npx` on PATH |
| **godot_omni** | bebabinlarsson gateway | 1,820 ops | needs its own addons; port conflict | per package | overlaps godot MCP | registered but OFF | Rejected (for now) | do not enable alongside godot_ai/godot_omni addons |
| **git MCP** | uvx mcp-server-git | repo ops | `uvx`-gated | per package | file tools | opt-in MCP server | Verified | `uvx` on PATH |
| **sequential-thinking MCP** | uvx mcp-sequential-thinking | reasoning aid | `uvx`-gated | per package | — | opt-in MCP server | Verified | `uvx` on PATH |
| **Claude Code** | CLI subscription | provider | installed CLI, needs sign-in | subscription | `cli_agents.py` | `cli-agent://claude-code` provider | Partial (needs sign-in) | `claude` then `/login` |
| **Codex** | CLI subscription | provider | installed CLI, needs sign-in | subscription | `cli_agents.py` | `cli-agent://codex` provider | Partial (needs sign-in) | `codex login` |
| **OpenRouter / DeepSeek** | openrouter.ai | model provider | key set | provider terms | default go-to model | OpenAI-compatible provider | Verified | key in `.env` |
| **Ollama** | ollama.com | local models | local | MIT | local-first fallback | provider | Verified | install Ollama + a model |
| **Higgsfield** | higgsfield.ai | image/video generation | API availability unverified | commercial | none | provider-pattern adapter if a public API exists; else documented manual workflow | Planned | confirm intended use + API access |
| **Supabase** | supabase.com/docs | Postgres/auth/sync/realtime | optional | commercial | local JSON persistence works | optional provider; keep core local | Planned | none |
| **Cloudflare** | developers.cloudflare.com | Workers/R2/Access/Tunnels/DNS/Queues | optional | commercial | none | optional provider | Planned | none |
| **Whop** | whop.com | commerce/platform | API availability unverified | commercial | none | investigate official docs; stub if unavailable | Planned | confirm intended use |
| **Neobanking** | provider TBD | financial | **provider not chosen** | — | none | generic adapter, read-only/sandbox first; never move money without authorization | Blocked | identify the intended provider |
| **Ponytail standard** | — | coding standard | embedded prompt block | — | part of the prompt | prompt block | Verified | none |
| **ECC + skill libraries** | mixed | 519 skills / 88 agents | vendored into `harness_data/vendor/` | per library | skills browser | `ecc_sync.py` | Verified | none |

## Notes
- **License verification is required before adoption** for every catalog/repo above; the
  table records "check" rather than assuming.
- **Nothing discovered is executed automatically.** A repository being listed does not
  make its code runnable — see the import pipeline in the blueprint (section 5).
- Financial integrations start read-only/sandbox and require explicit, per-action
  authorization.
