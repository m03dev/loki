# Harvest - the code LOKI took from every documented repo (session 27)

The owner (2026-10-17): "go through all the connectors and add-ons we talked about, every single
repo we have documented - take the code and improve LOKI, not the ones we have." So this is not
a list of things LOKI calls out to: it is what was **copied or ported into LOKI's own code**, so
LOKI works better with nothing extra installed. Licence decision from the owner: "LOKI stays
private, copy anything" - each project's licence sits in `engine/licenses/` (or beside the
copied files) and docs/THIRD_PARTY.md has a row per port.

How the list was made: every `github.com/<owner>/<repo>` in `docs/`, `engine/`, `contrib/`,
`capabilities/`, `tools/`, `app/ui/*.js`, HANDOFF.md and ZIVA_TASKS.md (102 strings; 12 are
placeholders such as `my-org/backend`, `user/repo`, `en/actions` and are left out), plus the
documented projects whose page is not on GitHub (Hermes Agent, Headroom, OpenCode). Each
project that looked worth porting was cloned and read (`git clone --depth 1`).

Priority, from the owner's brief: what makes LOKI's agents actually **succeed** on a weak local
model (qwen3:8b on Ollama) and on free cloud models - tool calling, editing, planning, the web,
coding, research, documents, schedules.

## What was ported this session (13)

| # | From | Into LOKI | What it does for the agent |
| --- | --- | --- | --- |
| 1 | Hermes Agent `tools/fuzzy_match.py` + `escape_drift_autocorrect.py` (the opencode/cline replacer chain) | `engine/fuzzy_match.py`, `engine/escape_drift_autocorrect.py`, used by `file_editor.str_replace` (`edit_file`) | An edit whose old text is off by indentation, whitespace, escapes, smart quotes/dashes or a wrong first/last line still lands on the right block (and says which strategy matched); a miss shows the closest lines to copy. Small models fail most edits on exactly this. |
| 2 | SWE-agent `tools/windowed_edit_replace` (lint before/after, keep only new errors, undo, show applied vs original) | `engine/lint_guard.py`, used by `edit_file` and `insert_lines` | An edit that introduces a syntax error (Python, JSON, TOML, XML, or a dropped brace in JS/TS/CSS/Go/Rust/Java/C...) is NOT written; the model sees SWE-agent's report. LOKI_EDIT_LINT=0 turns it off. |
| 3 | SWE-agent `tools/filemap` (bodies elided) and `search_dir` | `engine/code_map.py`, tool `code_map` | The outline of a file or a map of a whole project (symbols + line numbers) instead of reading 6,000 lines. |
| 4 | crawl4ai `BM25ContentFilter`, `clean_tokens`, `PruningContentFilter` link density, `convert_links_to_citations` | `engine/content_filter.py`; `read_web(url, query=...)`, tool `search_docs` | Only the part of a page that answers the question; local document search (RAG with no install) over the workspace. |
| 5 | Vane (Perplexica) `searxng.ts`, focus modes, writer citation rules, researcher "mistakes to avoid" | `engine/web_search.py`, tools `web_search`, `research_web` | LOKI can **search the web natively** (SearxNG if set, else DuckDuckGo, arXiv, Wikipedia) and answer with numbered, cited sources in one call. Before this, search needed the Vane or Perplexity add-on. |
| 6 | Firecrawl `map` (`getMapResults`, cosine ranking, sitemap index + gz, path filter) | `engine/site_map.py`, tool `map_site` | Every page URL of a site, ranked for a search, without crawling. |
| 7 | browser-use `ClickableElementDetector`, `DEFAULT_INCLUDE_ATTRIBUTES`, `[i]<tag>` serializer; page-agent's attribute pruning, `*[i]` new marks, page header/footer | `engine/text_browser.py`, tool `browse_page` | A text browser with numbered links and form fields: open, click, type, select, submit (GET; POST only with LOKI_BROWSE_POST=1), scroll, back, find - no Chromium. |
| 8 | Agent Reach `utils/url.py` (public-URL rules, legacy IPv4), channel routing, Jina Reader + anti-bot detection, Reddit finding | `engine/reach_native.py`, tool `reach`; `loki._private_host` hardened | GitHub repos/issues/files via the API, RSS/Atom feeds, YouTube details, JS pages via Jina; `127.1`, `2130706433`, `metadata.google.internal` are now refused everywhere LOKI fetches. |
| 9 | Headroom SmartCrusher + LogCompressor (+ error keywords) | `engine/compress.py`, used by `loki._elide` | A 2,000-line test log or a 300-row JSON result reaches the model as its errors, traces, summary and telling rows - not as an arbitrary head and tail. |
| 10 | NVIDIA SkillSpector `yara_rules/agent_skills.yar` (4 rules) + prohibition context | `engine/skill_rules.py`, `skill_scan.NATIVE_SCANNERS` | Every skill is scanned for credential exfiltration, curl\|bash bootstrap, hidden/zero-width instructions and unconfirmed destructive commands - without the add-on. None of LOKI's 260 shipped skills trips it. |
| 11 | Hermes Agent `cron/jobs.py` (`parse_schedule`, natural "every monday 9am", once/interval/cron) | `engine/schedules.py`, tool `schedule_task`, autopilot duty `schedules` | "Every weekday at 9am summarise the news" becomes a background LOKI job at that time. Cron matching is built in (no croniter). |
| 12 | Hermes Agent `tools/arg_coercion.py` | `engine/tool_guard.py` `_coerce` / `_coerce_items` | Objects sent as JSON strings, array items as JSON strings, "null" for omitted values - repaired before the tool runs. |
| 13 | anthropics/skills (Apache-2.0 ones) | `skills/anthropic/` (frontend-design, mcp-builder, skill-creator, webapp-testing, doc-coauthoring, internal-comms), catalog source "anthropic" | Six well-written skills any LOKI agent can load. |

Tests: `tests/test_harvest.py` (offline, fake openers, in `tools/ship.py` SUITES).

## Every documented repo

Decision: **ported** (this session), **already ported** (an earlier session), **in use** (LOKI
already uses its code or data as-is), **skip** (with why).

| Repo | What it is | Licence | Already in LOKI | Worth taking now | Decision |
| --- | --- | --- | --- | --- | --- |
| github.com/NousResearch/hermes-agent | Nous Research's general agent (add-on `hermes-agent`) | MIT | add-on card + herdr job runner | fuzzy edit chain, escape-drift fixer, arg coercion, cron schedule parser | **ported** (#1, #11, #12) |
| github.com/SWE-agent/SWE-agent (named in SYSTEMS_TO_IMPORT.md) | coding agent, ACI design | MIT | `_elide` bounded output, `_check_written` (session 17) | lint-on-edit revert, filemap, search_dir | **ported** (#2, #3) |
| github.com/anomalyco/opencode | coding agent CLI (add-on `opencode`) | MIT | CLI runner | its edit matching (now: exact, unicode, trailing-whitespace tiers; the older 9-replacer chain lives on in Hermes' port) | **ported** via #1 (same chain); rest is TypeScript/Effect plumbing |
| github.com/unclecode/crawl4ai | headless-Chromium page reader (add-on `crawl4ai`) | Apache-2.0 | add-on runner | BM25 filter, stop words, link density, citations | **ported** (#4); the browser engine itself stays the add-on |
| github.com/ItzCrazyKns/Vane | self-hosted answering engine (add-on `vane`) | MIT | `research` specialist via its API | SearxNG client, focus modes, citation writer rules | **ported** (#5) |
| github.com/firecrawl/firecrawl | page-to-markdown server (add-on `firecrawl`) | AGPL-3.0 (server) | `read_web` specialist over HTTP | `map` | **ported** (#6); scraping engine needs its browser fleet - skip |
| github.com/browser-use/browser-use | AI drives a real browser (add-on `browse`) | MIT | add-on runner (asks first) | clickable-element rules, attribute list, serializer format | **ported** (#7); CDP/Chromium control stays the add-on |
| github.com/alibaba/page-agent | in-page GUI agent (JS) | MIT | - (mentioned by ruflo-browser) | DOM-to-text pruning, new-element marks, page header/footer | **ported** (#7) |
| github.com/Panniantong/Agent-Reach | internet reach CLI (add-on `agent-reach`) | MIT | `reach` specialist runner | URL safety, routing, Jina fallback, anti-bot check | **ported** (#8); logged-in channels (X, XHS, Bilibili) need their CLIs - skip |
| github.com/Panniantong/agent-reach | same project, lower-case link | MIT | - | - | same as above |
| github.com/chopratejas/headroom (pypi headroom-ai) | context compression proxy (add-on `headroom`) | Apache-2.0 | add-on hook in the loop | SmartCrusher, LogCompressor | **ported** (#9); Rust core, CCR store, proxy - skip |
| github.com/NVIDIA/SkillSpector | skill security scanner (add-on `skillspector`) | Apache-2.0 | EXTERNAL_SCANNERS hook when installed | the agent-skill YARA rules | **ported** (#10); LLM analyzers need a model per skill - skip |
| github.com/anthropics/skills | agent skills | Apache-2.0 (docx/pdf/pptx/xlsx: proprietary) | listed as Planned | 6 open-source skills | **ported** (#13); proprietary document skills NOT copied |
| github.com/tinyhumansai/openhuman | Rust desktop agent | GPL-3.0 | session 26: memory core, sub-agents | channels (Telegram) = roadmap E10 | **already ported** |
| github.com/OpenHands/OpenHands | coding agent platform | MIT | session 26 (via the SDK) + CLI runner | - | **already ported** |
| github.com/OpenHands/software-agent-sdk | OpenHands SDK | MIT | session 26: condenser, stuck detector, file editor, task tracker, command risk | - | **already ported** |
| github.com/D4Vinci/Scrapling | adaptive scraper | BSD-3-Clause | session 26: `web_reader.py` | - | **already ported** |
| github.com/xiamuceer-j/MuMuAINovel | long-novel pipeline | GPL-3.0 | session 26: novel-writer skills | - | **already ported** |
| github.com/penecho/penecho | shared drawing canvas | AGPL-3.0 | session 26: sketch_reply idea | - | **already ported** (idea) |
| github.com/BabylonJS/Babylon.js | 3D engine | Apache-2.0 | LOKI World renderer (vendored build) | - | **in use** (UI is another agent's area) |
| github.com/mrdoob/three.js | 3D engine | MIT | vendored, optional world look | - | **in use** |
| github.com/stegu/webgl-noise | GLSL noise | MIT | `world_noise.js` | - | **in use** |
| github.com/ashima/webgl-noise | original of the above | MIT | same code | - | **in use** |
| github.com/paddy-exe/Godot-3D-Stylized-Water | water shader | MIT | world.js water | - | **in use** |
| github.com/coreyhaines31/marketingskills | 50 marketing skills | MIT | `skills/marketing/` | - | **in use** |
| github.com/ruvnet/ruflo | agent meta-harness | MIT | `contrib/ruflo/` agents, skills, playbooks | - | **in use** |
| github.com/ruvnet/claude-flow | ruflo's former name | MIT | inside contrib/ruflo | - | **in use** (same code) |
| github.com/ruvnet/claude-code-flow | older name of the same | MIT | - | - | skip: superseded by ruflo |
| github.com/ruvnet/agentic-flow | ruvnet agent runtime (npm) | MIT | referenced by ruflo skills | its ReasoningBank idea is already `reasoning_bank.py` | skip: Node runtime; idea already in LOKI |
| github.com/ruvnet/ruv-swarm | swarm runtime (npm, WASM) | MIT | referenced by ruflo skills | - | skip: Node/WASM swarm; LOKI has team.py + subagent.py |
| github.com/ruvnet/flow-nexus | hosted swarm platform | proprietary service | ruflo skills mention it | - | skip: cloud service, not code |
| github.com/ruvnet/ruvector | Rust vector DB | MIT | ruflo-ruvector plugin text | - | skip: needs a vector server; BM25 (#4) covers local search |
| github.com/ruvnet/neural-trader | trading agents | MIT | ruflo plugin text | - | skip: finance trading, owner said read-only finance first |
| github.com/ruvnet/metaharness | harness generator | MIT | ruflo plugin text | - | skip: generates Claude Code harnesses; LOKI is its own harness |
| github.com/ruvnet/agent-harness-generator | same family | MIT | ruflo plugin text | - | skip: as above |
| github.com/ruvnet/19d166ff9acf368c9da4172d91ac9113 (gist) | ruvnet gist | - | ruflo text | - | skip: a gist reference, no code to port |
| github.com/ruvnet/a1aca90a5c299d89fa92e905dab11041 (gist) | ruvnet gist | - | ruflo text | - | skip: as above |
| github.com/ruvnet/a708fafb1375ed69bc48377df47fa2ac (gist) | ruvnet gist | - | ruflo text | - | skip: as above |
| github.com/stuinfla/ruvnet-brain | ruvnet knowledge base | check | ruflo-mods plugin text | - | skip: a document collection, not agent code |
| github.com/cognitum-one/minimax-music | MiniMax music generation wrapper | check | ruflo-music plugin text | - | skip: thin client for a paid MiniMax API key |
| github.com/agntcy/dir | AGNTCY agent directory | Apache-2.0 | ruflo-agntcy plugin text | - | skip: multi-org agent protocol, LOKI is one owner's agent |
| github.com/agntcy/identity | AGNTCY identity | Apache-2.0 | ruflo-agntcy text | - | skip: as above (LOKI's peers already sign with their own key) |
| github.com/agntcy/observe | AGNTCY observability | Apache-2.0 | ruflo-agntcy text | - | skip: OpenTelemetry stack; LOKI has events.py |
| github.com/agntcy/slim | AGNTCY messaging | Apache-2.0 | ruflo-agntcy text | - | skip: gRPC messaging layer, not needed for two machines |
| github.com/outshift-open/ioc-protocols-models | protocol models | Apache-2.0 | ruflo-agntcy text | - | skip: as above |
| github.com/vectorize-io/hindsight | agent memory server (add-on `hindsight`) | MIT | remember/recall specialist | retain/recall/reflect - LOKI's memory_core (OpenHuman) already does learn/recall/forget with relevance + recency | skip: memory already ported in session 26 |
| github.com/volcengine/OpenViking | tiered context DB | AGPL-3.0 | pattern: `knowledge.py` viking:// URIs | L0/L1/L2 abstracts need an embedding + VLM server | skip: pattern already taken |
| github.com/getzep/graphiti | temporal knowledge graph | Apache-2.0 | - | - | skip: needs Neo4j/FalkorDB and LLM calls per episode |
| github.com/paperclipai/paperclip | agent org charts, budgets | MIT | pattern (budgets, approvals) | - | skip: pattern already in workers/team; Node+Postgres runtime |
| github.com/trycua/cua | computer-use VMs (add-on `cua`) | MIT core, FSL parts | `workers.py` cua backend | - | skip: needs a VM; the agent loop is model-specific |
| github.com/ogulcancelik/herdr | agent terminals | Apache-2.0 | state model in sessions.py/workers.py | - | skip: Rust TUI; pattern already in |
| github.com/Kiln-AI/Kiln | evals / fine-tuning workbench | MIT lib, fair-code app | add-on card | G-Eval judge could extend evals.py | skip for now: evals.py already has Task/solver/scorer; a judge needs a strong model per run |
| github.com/Yamz-Labs/kyojin | ExLlamaV3 server for 128 GB AMD | MIT | provider entry | - | skip: hardware LOKI's machines do not have |
| github.com/GVCLab/PersonaLive | portrait animation | academic only | link card | - | skip: licence (research only) and a GPU model |
| github.com/deepseek-ai/deepseek-harness | DeepSeek's agent harness (TS, Cordis plugins) | MIT | listed as Planned | - | skip: developer preview, TypeScript plugin framework; nothing small and portable beyond what Hermes/SWE-agent gave |
| github.com/milind-soni/OpenMausBot | agents as chat contacts | Apache-2.0 | idea noted | sidebar contacts is UI work | skip: UI idea (app/ui is being rebuilt by another agent) |
| github.com/nesdeq/artemis | parallel context enrichers | MIT | idea noted | - | skip: repository no longer public (clone asks for login, 2026-10-17); the idea maps onto first_layer |
| github.com/cactus-compute/cactus | on-device phone inference | Apache-2.0/check | phone app plan (mobile/) | - | skip: phone runtime, not engine code |
| github.com/mybigday/llama.rn | React Native llama.cpp | MIT | phone plan | - | skip: phone app |
| github.com/ggml-org/llama.cpp | local inference | MIT | provider entry (llama-server) | GBNF grammars - LOKI already constrains output with JSON schema (tool_guard) | skip: C++; already used as a server |
| github.com/ml-explore/mlx-lm | MLX models on the Mac | MIT | `mlx` add-on | - | **in use** (as a server) |
| github.com/unslothai/unsloth | LoRA fine-tuning | Apache-2.0 | `tools/train_lora.py` | - | **in use** |
| github.com/google-research/timesfm | forecasting model | Apache-2.0 | `forecast.py` optional | - | **in use** |
| github.com/roboflow/trackers | object tracking | Apache-2.0 | vision-track add-on | - | **in use** (needs torch) |
| github.com/remotion-dev/remotion | video from React | Remotion licence | `runners/video.py` via npx | - | skip: licence is not open source; LOKI never vendors it |
| github.com/yt-dlp/yt-dlp | video/audio downloader | Unlicense | `media` add-on (pip) | - | **in use** (pip package; 100k+ lines of extractors are not worth copying) |
| github.com/pollinations/pollinations | free image API | MIT | image specialist backend | - | **in use** |
| github.com/higgsfield-ai/higgsfield-client | Higgsfield SDK | Apache-2.0 | `higgsfield.py` protocol | - | **already ported** |
| github.com/receptron/laya | local decision model | MIT | `laya.py` | - | **in use** |
| github.com/mnfst/awesome-free-llm-apis | free LLM API list | check | 11 providers registered | - | **in use** |
| github.com/public-apis/public-apis | API list | MIT | superseded by apis.guru in api_vault | - | skip: superseded |
| github.com/public-api-lists/public-api-lists | API list | check | superseded | - | skip: superseded |
| github.com/davemachado/public-api | API list | check | superseded | - | skip: superseded |
| github.com/ekzhang/bore | TCP tunnel | MIT | relay via bore.pub | - | **in use** (as a program) |
| github.com/DietrichGebert/ponytail | coding standard | check | prompt block in loki.py | - | **in use** |
| github.com/m03dev/loki | this project | private | - | - | - |
| github.com/mermade/aws2openapi | AWS API specs (api_vault entry) | check | api_vault data | - | skip: a catalog entry, not agent code |
| github.com/mermade/mashery2openapi | API spec converter (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/mermade/swagger2openapi | spec converter (vault entry) | BSD-3 | api_vault data | - | skip: catalog entry |
| github.com/sigpwned/pinecone-openapi-spec | Pinecone spec (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/sonallux/spotify-web-api | Spotify spec (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/soundcloud/api | SoundCloud API (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/tcgdex/cards-database | card data (vault entry) | MIT | api_vault data | - | skip: catalog entry |
| github.com/up-banking/api | Up Bank API (vault entry) | check | api_vault data | - | skip: catalog entry; banking stays read-only/blocked |
| github.com/papinet/papiNet-API | paper industry API (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/HackEAC/mtaaAPI | Tanzania locations API (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/Bungie-net/api | Destiny API (vault entry) | check | api_vault data | - | skip: catalog entry |
| github.com/mastodon/mastodon | social server (vault entry) | AGPL-3.0 | api_vault data | - | skip: catalog entry |
| github.com/apicurio/apicurio-registry | schema registry (vault entry) | Apache-2.0 | api_vault data | - | skip: catalog entry |
| github.com/SeldonIO/seldon-core | model serving (vault entry) | BSL/Apache | api_vault data | - | skip: catalog entry |
| github.com/open-policy-agent/opa | policy engine (vault entry) | Apache-2.0 | api_vault data | - | skip: LOKI's policy.py is in-process and simpler; Rego would be a second language |

Placeholders found by the scan and ignored: `my-org/backend`, `my-org/frontend`, `my-org/shared`,
`org/repo-a|b|c`, `user/repo`, `username/repo`, `example/repo`, `en/actions`, `en/issues`,
`settings/billing`, `walkinglabs/` and `yenanjing/` (no repository given - "verify existence"
in INTEGRATION_REGISTRY.md).

## Not done here, and why

- **aider** (repo map, edit formats) is not documented anywhere in the project, so it was left
  to the agent researching new repos. SWE-agent's filemap (#3) covers the outline part.
- **Live checks**: every port is tested offline with fakes. Web search, research, site maps,
  the text browser, GitHub/feeds/Jina and scheduled jobs have not run against the real internet
  or a real model yet - ZIVA_TASKS.md W22 (PC) and M14 (Mac) ask for that.
