# Loki — Integration Registry

Status of every repository, provider, API, service, and skill the blueprint asks about.
Legend — **Verified**: identity confirmed and integrated/working; **Partial**: present but
incomplete; **Planned**: intended, no code yet; **Blocked**: cannot proceed without
something; **Rejected**: deliberately not adopted.

| Integration | Canonical URL | Capability | Identity / availability | License | Loki overlap | Approach | Status | User action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Loki** | github.com/m03dev/loki | the project itself | confirmed checkout | MIT | — | — | Verified | none |
| **Jev** (TypeSafe System One) | thejevai.com/docs | typed decisions | API; key-gated | hosted API | `engine/jev.py` risk gate + loop detection | direct client + optional MCP | Verified (optional) | set `TYPESAFE_API_KEY` to enable |
| **Laya** | github.com/receptron/laya | local-first decision provider | public repo | MIT (weights Apache-2.0) | `engine/laya.py` + `engine/decisions.py` | Jev-compatible client: HTTP `system_one` endpoint or a local Node driver delegating to `@receptron/laya`; Laya-first routing with Jev fallback | Verified (the forward pass itself needs the 1.7 GB weights, so it is not run offline) | none |
| **Laya (upstream patch)** | github.com/receptron/laya | offline testability for `systemOne` | prepared in `contrib/laya/` | MIT | improves the dependency | `Laya.fromParts()` seam + offline tests; verified with `yarn test`/`typecheck`/`lint` | Prepared (not submitted) | approve a fork + PR |
| **Herdr** | github.com/ogulcancelik/herdr (herdr.dev) | persistent agent terminals, working/blocked/idle states, socket API | v0.9.4 (2026-10-13); macOS/Linux, Windows beta | Apache-2.0 | `sessions.py` + `workers.py` adopt the state model | pattern adopted; optional dev host for Loki workers, never a dependency | Verified (pattern) | none |
| **OpenViking** | github.com/volcengine/OpenViking | tiered (L0/L1/L2) context/memory/skill retrieval | active (HEAD 2026-10-13) | **AGPL-3.0** | current markdown memory | pattern-only: copy the L0/L1/L2 tiering into Loki's own memory; do not embed (copyleft, needs an embedding + VLM server) | Evaluated: pattern-only | none |
| **apis.guru** | api.apis.guru/v2/list.json | API catalog (the vault's seed) | public, fetched + cached | free | `engine/api_vault.py` seeds 2,059 entries | normalized into the vault: title, x-origin url, provider, categories, security hint | Verified | none |
| **public-apis** | github.com/public-apis/public-apis | API catalog | public repo | check | the vault already carries apis.guru's 2,059 entries | not separately imported - apis.guru is the larger, machine-readable superset | Superseded | none |
| **public-api-lists** | github.com/public-api-lists/public-api-lists | API catalog | public repo | check | as above | as above | Superseded | none |
| **davemachado/public-api** | github.com/davemachado/public-api | API catalog | public repo (may be archived) | check | as above | as above | Superseded | none |
| **anthropics/skills** | github.com/anthropics/skills | agent skills | public repo | Apache-2.0 (docx/pdf/pptx/xlsx proprietary) | 519 vendored skills already | six open-source skills vendored in skills/anthropic (session 27, docs/integrations/HARVEST.md) | Partial | none |
| **deepseek-harness** | github.com/deepseek-ai/deepseek-harness | harness patterns | verify existence | check | Loki has its own loop | extract patterns; write a comparison first | Planned | none |
| **awesome-harness-engineering** (walkinglabs / yenanjing) | github.com/walkinglabs/... , github.com/yenanjing/... | harness references | verify existence | check | — | reference only | Planned | none |
| **Godot MCP** | "Godot Editor MCP" addon by hybridindie (was vendored; see git history) | live editor bridge for a game project | MIT | MIT (c) 2026 Johnny D | optional game capability | no longer vendored in Loki (2026-10-13); a game project adds it itself if it wants it | Removed from Loki | none |
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

| **Convai Innovations / laya-onnx** | huggingface.co/receptron/laya-onnx | the ONNX bundle Laya runs | public | weights Apache-2.0 | `laya.py` local backend | resolved by the `@receptron/laya` package | Verified (downloads on first use) | none |
| **Opus model reference** | (provider to confirm) | a requested Claude model reference | **identifier unverified** | commercial | none | verify the real model id, access and pricing before any adapter; never invent one | Blocked (no verified id) | confirm which model/plan is meant |
| **Agent substrate** | (reference ambiguous) | a common agent runtime | **identity unconfirmed** | unknown | Loki already has an agent loop | do not invent a repository from an ambiguous name; Loki's own runtime is the substrate today | Blocked (ambiguous reference) | clarify the intended project |
| **Git repository browser** | (a capability, not a repo) | repo discovery and inspection | not built | - | none | Phase 3: capability registry + provenance and license checks | Planned | none |
| **Diagramming / design skills** | (e.g. anthropics/skills) | architecture, sequence, flow, ER diagrams | not yet sourced | check | none | Mermaid/SVG-preferred skill; verify the diagram renders | Planned | none |
| **Cybersecurity skills** | (defensive, to source) | code review, threat modeling, secret detection | not yet sourced | check | none | defensive only; explicit scope for any active testing | Planned | none |
| **Scientific skills** | (to source) | evidence synthesis, citations, statistics | not yet sourced | check | none | distinguish evidence from hypothesis; never fabricate sources | Planned | none |

| **awesome-free-llm-apis** | github.com/mnfst/awesome-free-llm-apis | catalogue of LLM APIs with permanent free tiers (`data.json`) | public repo | check before reuse | extended Loki's provider list | imported 11 providers as OpenAI-compatible endpoints: aion, cohere, zai, huggingface, kilocode, llm7, modelscope, nvidia, ollama-cloud, ovh, siliconflow | Verified (registered; keys not set) | none |

## Notes
- **License verification is required before adoption** for every catalog/repo above; the
  table records "check" rather than assuming.
- **Nothing discovered is executed automatically.** A repository being listed does not
  make its code runnable — see the import pipeline in the blueprint (section 5).
- Financial integrations start read-only/sandbox and require explicit, per-action
  authorization.
| **Graphiti** | github.com/getzep/graphiti | temporal knowledge graph | v0.32.0, active | Apache-2.0 (telemetry on by default) | replaces Loki's memory model | needs Neo4j/FalkorDB/Neptune and structured-output LLM calls per episode | Rejected for now (cost + install weight on Windows/macOS) | none |
| **Paperclip** | github.com/paperclipai/paperclip | agent org charts, budgets, approvals, heartbeat wakeups | very active | MIT (telemetry on by default) | overlaps the new worker system | pattern-only: budgets before each run, approval gates, coalesced wakeups; a second runtime (Node + Postgres) is not worth it | Evaluated: pattern-only | none |
| **CUA (Cua Driver)** | github.com/trycua/cua | desktop/browser control over MCP (`cua-driver mcp`) | very active; Driver on macOS/Windows/Linux | MIT core; Spaces/Keyvault/Teleport are FSL-1.1 | none (Loki has no desktop control) | opt-in local MCP server, Driver only, behind approvals; avoid FSL parts | Planned (next experiment #2) | install Cua Driver |
| **Unsloth** | github.com/unslothai/unsloth | QLoRA fine-tuning + GGUF/Ollama export | very active; native Windows | Apache-2.0 core (Studio/UI is AGPL - not used) | none | `tools/train_lora.py` in a separate training venv; Qwen3-4B-Instruct-2507, 4-bit, r=16, 2048 tok for 8 GB | Integrated (not yet run on a GPU) | run `tools/setup_training.bat` on the GPU PC |
