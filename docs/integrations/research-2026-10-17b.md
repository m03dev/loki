# Research round 3, 2026-10-17: what the best personal-AI apps have that LOKI lacked

The owner: "keep researching, downloading and installing new features ... i want a useful app that can help
people and can turn into anything". Round 1 (`research-2026-10-17.md`) and the harvest (`HARVEST.md`) took
agent internals - tool calling, editing, research, memory. This round looks at the **apps people actually use
every day** (Open WebUI, LibreChat, AnythingLLM, Jan, LM Studio, Msty, Khoj, Leon, OpenClaw, Lobe Chat, Cherry
Studio ...) and asks: what do ordinary people get there that they did not get in LOKI?

Left out on purpose (other agents are building them right now): mini-apps / modes / extensions, documents &
data (PDF, Office, analysis, a Files view), automations / triggers, onboarding / i18n / accessibility /
installers. Also left out: everything LOKI already had (web search with citations, deep research, memory,
voice in/out, Telegram, computer use, connectors, image/video/music making, schedules, teams).

Licence decision (owner): LOKI stays private, copy anything; keep LICENSE files and a THIRD_PARTY row.

Stars and dates come from the pages cited (read 2026-10-17); where a page gave none, none is shown. The
session could not reach GitHub, npm or PyPI directly (proxy policy), so nothing was cloned this round: every
port below is LOKI's own code following the cited project's documented behaviour and formats, plus Mermaid
copied from a local install.

## What was built (8 features, all native, all offline-tested)

| # | Feature | Learned from | LOKI files | What an ordinary person gets |
| --- | --- | --- | --- | --- |
| 1 | **Message actions**: Copy, Edit & send again, Regenerate, Branch from here | Open WebUI, LibreChat (fork), Lobe Chat, Msty | `engine/chat_plus.py`, `app/ui/chat_plus.js` | Fix a typo in a question without starting over; ask again for a better answer; try a different direction in a new chat while keeping the old one |
| 2 | **Rich replies + artifacts canvas**: tables, links that open in the browser, [n] citations that jump to their source, code blocks with Copy, live **Preview** of HTML/SVG in a sandboxed canvas (Save keeps versions), **Mermaid diagrams** drawn in place, ```chart blocks drawn as bar/line/pie charts | Claude artifacts, Open WebUI artifacts (versions), LibreChat/Lobe Chat previews, Cherry Studio Mermaid | `engine/artifacts.py`, `app/ui/artifacts.js`, `app/ui/vendor/mermaid/` | "Make me a little web page / a flowchart / a chart of these numbers" shows the real thing, not code |
| 3 | **Export / import chats**: Markdown, a standalone web page, JSON; import from **ChatGPT**, **Claude**, **Open WebUI**, **LibreChat**, LOKI and Markdown/`User:` transcripts | LibreChat import (ChatGPT, Claude, ChatbotUI), Open WebUI import/export | `engine/chat_io.py`, `/convo/export`, `/convo/import` | Bring years of ChatGPT history into LOKI; keep or share a chat as a file |
| 4 | **Prompt library**: 12 starter prompts (reply to an email, summarise, explain simply, translate, fix grammar, meals for the week, plan a trip, cover letter, help me decide, review code, write a message, plan my day) with `{{blanks|defaults}}`, `{{date}}`/`{{weekday}}`/`{{clipboard}}`; save your own; `/p name` | Open WebUI prompts (`/` commands, variables), LibreChat presets, Lobe Chat assistant market, Cherry Studio agents | `engine/prompt_library.py`, the book button in the message box | Good prompts without knowing how to write prompts |
| 5 | **Compare models side by side** + a leaderboard from your votes (Elo) | Msty split chats, Cherry Studio multi-model answers, Open WebUI arena | `engine/compare.py`, `/compare` | See which free/local model is best for *your* questions |
| 6 | **Home Assistant** connector `home`: status, list, find, state, history; turn on/off/toggle (brightness, colour, temperature), any service, Assist - names like "living room lights" resolved; every change asks | homeassistant-mcp (tevonsb), OpenClaw smart-home control, Leon | `engine/conn_home.py` (+ policy `ACTION_ALWAYS_ASK["home"]`) | "Turn off the downstairs lights", "is the front door locked?" |
| 7 | **Everyday answers with no key**: `weather` (Open-Meteo, °F in the US), `news` (Google News search RSS / BBC World), `world_clock`, `translate` (the model, or a LibreTranslate server) - with cards in the chat; `/weather`, `/news`, `/time`, `/translate` | Lobe Chat / Cherry Studio plugin stores, OpenClaw morning briefings, Leon skills | `engine/everyday.py` | The questions people ask an assistant first, answered for free |
| 8 | **Picture edits on this computer**: resize, crop, rotate, flip, convert, compress, grayscale, thumbnail, upscale (Real-ESRGAN when installed, else Lanczos), **remove background** (rembg add-on) | rembg (MIT), Real-ESRGAN ncnn (MIT), Cherry Studio image tools | `engine/image_tools.py`, add-on `capabilities/rembg` | "Make this photo smaller for email", "cut me out of this picture" - nothing uploaded |
| 9 | **Your data** (Settings): what LOKI keeps and where, which providers got your messages in 30 days, **backup** (one zip, no keys unless asked) and **restore** (checked, safety backup first), clear logs/previews/usage/chats | Open WebUI export-all + backups, Cherry Studio backup/restore, Jan/Msty/AnythingLLM privacy pages | `engine/your_data.py`, `app/ui/data_panel.js` | Trust ("what left my computer?") and never losing your chats |

Routes: `engine/assist_api.py` (the bridge only routes). Tests: `tests/test_research3.py` (154 checks, in
SUITES): fakes for every network service, real Pillow, the real bridge server, and the real window in headless
Chromium (Mermaid really draws, the preview's script really runs, the frames cannot read LOKI's token).

## Ranked table (35)

Score = how much it helps an ordinary person using LOKI x how cheaply LOKI can have it. "Built" = in LOKI now.

| # | Project / feature | Licence | Stars / activity | What to take | Decision |
| --- | --- | --- | --- | --- | --- |
| 1 | [Open WebUI](https://github.com/open-webui/open-webui) - artifacts, prompts with variables, chat import/export, arena | BSD-3 + branding clause (check repo) | 147K-154K | Artifact window with versions; prompt library; ChatGPT import; arena voting -> leaderboard | **Built** (#1-#5, #9) |
| 2 | [LibreChat](https://github.com/danny-avila/LibreChat) - fork/branch, import ChatGPT/Claude/ChatbotUI, presets | MIT | (large) | Conversation forking; the importers' formats | **Built** (#1, #3) |
| 3 | [Msty](https://msty.ai) split chats | proprietary app (free) | - | Same prompt to several models, side by side | **Built** (#5) as a native idea; no code |
| 4 | [Cherry Studio](https://github.com/CherryHQ/cherry-studio) - multi-model answers, assistants, backup/restore, Mermaid | AGPL-3.0 (check) | (large) | Multi-model compare, assistants library, backup | **Built** as ideas (#4, #5, #9); no code copied |
| 5 | [Lobe Chat / LobeHub](https://github.com/lobehub/lobe-chat) - assistant market, artifacts, plugin cards | Apache-2.0-based LobeHub licence (check) | (large) | Card-style plugin answers (weather, news) | **Built** as idea (#7 cards) |
| 6 | [Mermaid](https://github.com/mermaid-js/mermaid) | MIT | (very large) | Diagrams from text, drawn in a sandboxed frame | **Built** (#2; vendored 11.16.1) |
| 7 | [rembg](https://github.com/danielgatis/rembg) | MIT (models: own licences; bria-rmbg non-commercial) | 2.0.85, 2026-09-20 | `remove()` / `new_session()` with u2net/isnet/birefnet ONNX | **Built** (#8, add-on `rembg`, pip `rembg[cpu]`) |
| 8 | [Real-ESRGAN ncnn Vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) | MIT | stable | One binary 2-4x upscaler on any GPU via Vulkan | **Built** (#8: used when on PATH / LOKI_REALESRGAN); install = ZIVA |
| 9 | [Open-Meteo](https://open-meteo.com) | API free, data CC BY 4.0 | - | Geocoding + forecast with no key | **Built** (#7) |
| 10 | [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest) / [homeassistant-mcp](https://glama.ai/mcp/servers/tevonsb/homeassistant-mcp) | Apache-2.0 / MIT | MCP server inactive per Glama | states, services, history, conversation/process; control by friendly name | **Built** (#6) natively (stdlib) |
| 11 | [OpenClaw (Clawdbot)](https://github.com/openclaw/openclaw) | open source (licence not stated in sources) | 385K (Jul 2026) | Channels everywhere, proactive briefings, Live Canvas, voice wake, skills hub | Canvas idea **built** (#2); briefings = automations agent; voice wake = next |
| 12 | [Khoj](https://github.com/khoj-ai/khoj) | AGPL-3.0 | - | **Desktop quick chat (Khoj Mini)**, shareable chat links, automations by email | Quick-launch hotkey: **next** (needs a native global hotkey on both OSes); share = export page (#3) |
| 13 | [Jan](https://github.com/janhq/jan) | Apache-2.0 variant | ~44.3K (Sep 2026) | Assistants (personas), projects, local API server | Personas ~ prompt library (#4); projects = other agent's area |
| 14 | [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | MIT | 64K | Workspaces with RAG, no-code agent builder | Skip: documents & data is another agent's area; LOKI has agents |
| 15 | [LM Studio](https://lmstudio.ai) | proprietary app | - | Model discovery UI, MLX on Mac | Skip: LOKI's Local models tab + MLX add-on cover it |
| 16 | [Leon](https://github.com/leon-ai/leon) | MIT | since 2017; 2.0 preview | Layered memory, SKILL.md workflows, offline voice | Skip: LOKI has memory_core + skills |
| 17 | [Hermes Agent](https://github.com/NousResearch/hermes-agent) | MIT | 223K | Skills learned from experience | Already ported (HARVEST #1, #11, #12; make_tool) |
| 18 | [Goose](https://github.com/block/goose) | Apache-2.0 | "tens of thousands" | YAML **recipes** (prompt + extensions + params), subagents | Recipes ~ prompt library with blanks (#4); MCP extensions already in LOKI |
| 19 | [Cline](https://github.com/cline/cline) | Apache-2.0 | 65K | Plan/Act, checkpoints in VS Code | Already in LOKI (modes + workbench checkpoints) |
| 20 | [Continue](https://github.com/continuedev/continue) | Apache-2.0 | (large) | IDE assistant, rules | Skip: IDE plug-in; LOKI is its own app |
| 21 | [OpenHands](https://github.com/OpenHands/OpenHands) | MIT | 83K | coding platform | Already ported (session 26) |
| 22 | [Perplexica / Vane](https://github.com/ItzCrazyKns/Vane) | MIT | - | Answer engine with citations | Already ported (HARVEST #5); citations now clickable in the chat (#2) |
| 23 | [Morphic](https://github.com/miurla/morphic) | Apache-2.0 | ~9K | Generative UI: answers streamed as UI components | Idea **built** (```loki-card / ```chart blocks rendered as components, #2/#7) |
| 24 | [Letta](https://github.com/letta-ai/letta) | Apache-2.0 | 24K | Self-editing memory blocks | Skip: LOKI's memory core (session 28) covers it |
| 25 | [Mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | 62K | Universal memory layer | Skip: as above |
| 26 | [Cognee](https://github.com/topoteretes/cognee) | Apache-2.0 | 30K | Knowledge-graph memory | Skip: needs a graph store |
| 27 | [Pipecat](https://github.com/pipecat-ai/pipecat) | BSD-2 | 1.0 in Apr 2026 | Frame pipeline, Silero VAD + **Smart Turn v3.2** (8 MB CPU) for barge-in | Next: hands-free voice mode (Smart Turn for end-of-turn) on top of voice.js |
| 28 | [LiveKit Agents](https://github.com/livekit/agents) | Apache-2.0 | - | Semantic turn detector, WebRTC rooms | Skip: a room server is overkill for one person |
| 29 | [OpenVoice](https://github.com/myshell-ai/OpenVoice) / [F5-TTS](https://github.com/SWivid/F5-TTS) | MIT / MIT code | 37K / 15K | Voice cloning | Later (Kokoro first; owner decision) |
| 30 | [browser-use](https://github.com/browser-use/browser-use) / [Stagehand](https://github.com/browserbase/stagehand) | MIT | - | Browser agents | Already ported (HARVEST #7, session 28 Chromium) |
| 31 | Clipboard history (Raycast / Maccy pattern) | - | - | Recent copies searchable by LOKI | Next: needs a background watcher per OS (pyperclip poll) - privacy opt-in |
| 32 | Desktop notifications when a job ends (Khoj, Goose) | - | - | osascript / Windows toast | Next: small, but touches workers/autopilot (other agents' areas) |
| 33 | Screenshot + "what's on my screen" (Cherry Studio, OpenClaw) | - | - | One-shot screen capture to the vision model | Mostly there: `computer` tool `look`/`screenshot` (session 28); a toolbar button is next |
| 34 | Code interpreter in chat (Open WebUI, Khoj) | - | - | Run Python blocks in a sandbox and show output/plots | Skip now: documents & data agent; LOKI's run_command + user_tools sandbox exist |
| 35 | [OmniRoute](https://github.com/diegosouzapw/OmniRoute) | MIT | 35K | One endpoint for many providers | Already a provider entry |

## How it fits together

- **Chat actions** never rewrite history in place behind the model's back: edit/regenerate cut the stored chat
  just before that message and send through the normal `/chat` path (modes, approvals and tools as usual);
  branch makes a new chat. Messages are found by text + occurrence because LOKI stores fewer turns than the
  window shows (it drops its own steering turns and DONE lines). Both wait (409) while LOKI is answering.
- **Previews are sandboxed twice**: the frame has `sandbox="allow-scripts"` (opaque origin - no token, no
  engine calls, no window access; the test proves `window.parent.state` is unreachable) and the page has its
  own CSP (`sandbox allow-scripts`, `connect-src 'none'`, images only data:/blob:, scripts inline or from three
  CDNs, Mermaid only from LOKI's own `/ui/vendor/`). The window's own CSP is unchanged.
- **Home Assistant** writes go through `policy.ACTION_ALWAYS_ASK` (never decidable, refused in background jobs,
  like email send); the tool is hidden from the model until the address and token are saved (Settings > Tools >
  Home). The token is a SECRET setting and is redacted from every error.
- **Backups** never include `.env` unless the owner ticks "include my keys"; restore refuses zips with escaping
  paths or links and makes a safety backup first. Default folder `~/LOKI Backups` (LOKI_BACKUP_DIR).
- **New settings**: `LOKI_HOME_CITY` (weather default), `LOKI_NEWS_FEED`, `LOKI_LIBRETRANSLATE_URL`,
  `LOKI_REALESRGAN`, `LOKI_BACKUP_DIR`, `LOKI_COMPARE_TIMEOUT`, `LOKI_COMPARE_TOKENS`, `HA_URL`, `HA_TOKEN`.

## Not verified here (needs the real machines - ZIVA W35 PC, M26 Mac)

No real Home Assistant, Open-Meteo, Google News, LibreTranslate, rembg model, Real-ESRGAN binary or model
provider was reached (all faked; this sandbox cannot reach them). The window was tested in headless Chromium,
not in WebView2 / WKWebView: the file picker for Import, `confirm()`/`prompt()` dialogs, clipboard access and
the sandboxed frames inside pywebview must be checked on each machine.

## Sources

- Open WebUI artifacts: https://docs.openwebui.com/features/code-execution/artifacts
- Open WebUI import/export: https://docs.openwebui.com/features/chat-conversations/data-controls/import-export
- Open WebUI arena / evaluation: https://www.simplified.guide/open-webui/model-arena-run , https://docs.openwebui.com/features/administration/evaluation/
- Open WebUI 2026 review (stars, features): https://aiindigo.com/blog/open-webui-the-definitive-2026-review
- LibreChat import: https://www.librechat.ai/nl/docs/features/import_convos
- ChatGPT export format: https://ai-chat-importer.com/guides/chatgpt-export-format-explained
- Msty split chats: https://msty.ai/blog/split-chats , https://docs.msty.studio/conversations/split-chat
- Cherry Studio review: https://aiindigo.com/blog/cherry-studio-review-the-unified-hub-for-the-fragmented-ai-era
- LobeHub docs: https://lobehub.com/docs
- Personal assistants overview (Jan, AnythingLLM, Leon, QwenPaw, PyGPT): https://www.vellum.ai/md/blog/best-open-source-personal-ai-assistants
- Top AI GitHub repos 2026 (stars: OpenClaw, Hermes, Mem0, Letta, Cline ...): https://www.bitdoze.com/md/top-ai-github-repos.md
- Clawdbot / OpenClaw guide: https://www.contextstudios.ai/blog/clawdbot-the-complete-guide-to-the-viral-open-source-ai-assistant-2026.md
- Khoj features: https://docs.khoj.dev/category/features/
- Jan review: https://www.promptquorum.com/power-local-llm/jan-review
- Goose review: https://dev.to/jangwook_kim_e31e7291ad98/goose-by-block-a-free-open-source-ai-agent-review-2026-fno
- Morphic: https://dev.co/ai/frameworks/morphic
- Home Assistant MCP server: https://glama.ai/mcp/servers/tevonsb/homeassistant-mcp
- rembg (licence, models, API): https://libraries.io/pypi/rembg
- Pipecat vs LiveKit Agents: https://www.forasoft.com/blog/article/pipecat-vs-livekit-agents
- Open-Meteo: https://open-meteo.com/
