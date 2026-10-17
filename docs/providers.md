# Model providers

Loki talks to any **OpenAI-compatible** endpoint. Put keys in `harness_data/.env`
(copy from `engine/.env.example`) and choose one with `LOKI_MODEL`.

| `LOKI_MODEL` | Provider | Free tier |
|---|---|---|
| `local` / `local-reasoning` | Ollama (local) | yes, local |
| `local-tools` | Ollama `llama3-groq-tool-use:8b` | yes - best tool-caller for an 8 GB card |
| `local-fast` | Ollama `qwen3:4b` | yes - ~2.8 GB, ~80 tok/s |
| `online` | **online mode** - see below | resolves to the best online provider |
| `gemini` | Google AI Studio | yes |
| `groq` | Groq | yes |
| `openrouter` | OpenRouter | yes (`:free` models) |
| `cerebras` | Cerebras | no - needs a verified payment method |
| `sambanova` | SambaNova Cloud | yes (20 req/min, 20/day, 200k tok/day) |
| `cloudflare` | Cloudflare Workers AI | yes (10,000 Neurons/day) |
| `unorouter` | UnoRouter | yes (many `:free` routes, no card) |
| `nous` | Nous Portal | yes ($0 plan `:free` models) |
| `mistral` | Mistral | yes |
| `together` | Together AI | yes |
| `deepseek` | DeepSeek V4.1-Flash (`deepseek-flash`) | no - $0.15/M in, $0.60/M out off-peak |
| `omniroute` | local OmniRoute gateway | routes to any of the above |

| `gpt` / `claude` | OpenAI / Anthropic | paid |
| `claude-code` | Claude Code CLI (your subscription) | no key - flat rate you already pay |
| `codex` | Codex CLI (your subscription) | no key - flat rate you already pay |

## More providers (2026-10)

Settings > Connections shows every provider below as a card (engine/providers_catalog.py
has the facts and links). New ids: `codestral`, `opencode-zen`, `vercel`, `pollinations`
(keyless), `nebius`, `scaleway`, `hyperbolic`, `novita`, `fireworks`, `dashscope`
(free credits; counted as paid), local servers `lmstudio`, `llamacpp`, `mlx` (port 8082),
`vllm`, `jan`, `kyojin` (`KYOJIN_BASE_URL`), and the `opencode` CLI agent. GitHub Models
was retired on 2026-07-30. Switch any provider off with its card (`LOKI_DISABLED_PROVIDERS`).

Models with no native tool calling get tools as text (engine/tool_harness.py). List more
providers for that with `LOKI_PROMPTED_TOOLS=name,name`; an endpoint that refuses a tools
list is switched to it automatically.

## How LOKI picks a model (session 28: models & routing)

Smart mode (and online mode) choose per TASK, not once. Ask LOKI to explain it any time:
type `/models doctor` (or Settings > Connections > **Explain routing**). It answers in plain
words, e.g. "Pictures -> gemini, because free, sees pictures; Background jobs -> openrouter,
because background jobs get the best free model that calls tools reliably", lists what is
skipped right now with a one-line fix, and the local side (Ollama version, Bonsai, context).

1. **Provider health** (`engine/provider_health.py`). Every failure is classified and
   remembered in `harness_data/provider_health.json` (no keys - a short hash only), so the
   engine, every background job (its own process) and the next start all know:
   `key_rejected` (401/403; until you paste a NEW key), `no_credit` (402, "insufficient
   balance"; 12 h), `quota` (a spent free quota: until the provider's `retryDelay`, the next
   day for per-day quotas, else 1 h), `rate_limited` (429: as long as it said, min 30 s),
   `size_limited` (Groq's 413 "Limit 6000, Requested 9133": only bigger requests skip it),
   a context-too-long error (its window is remembered), `unreachable` (timeouts),
   `model_missing`, empty replies. A background refresher re-checks connected providers every
   30 min with **free** calls only (`GET /models`, OpenRouter `/key` for a negative balance,
   DeepSeek `/user/balance`) - never a completion. It also reads each model's context window,
   tool calling and vision from the provider's own model list. `LOKI_HEALTH_PROBES=0` turns the
   probes off; `LOKI_HEALTH_EVERY_S` sets the period. Settings > Connections shows the state
   and the fix on each card; **Re-check** probes now.
2. **Task-aware order** (`engine/routing.py`). Needs: kind + difficulty (the first layer),
   background job, tool-heavy (code/build/ops/browse/research, every background job), pictures in
   the message, size in tokens, local only. Abilities: tools native / prompted / measured
   (`experience.tool_score`), vision, context window, code. A provider that cannot do the task
   (cannot call tools reliably for tool-heavy work, cannot see a picture, too small a window)
   goes to the END of the order - never removed, so there is no dead end. Within one cost tier
   the provider with the best record for THIS kind of task goes first (a success table per
   provider/model x task kind from the experience log: verified/done = good; a provider switched
   away from mid-request = bad; 5 samples before it moves anything). Free never loses its place
   to paid; paid is only automatic with `LOKI_ALLOW_PAID=1`.
3. **Background jobs** get the best FREE capable online model, not the local 8B just because the
   triage said "easy" (subscription agents are not used up by unattended jobs; they stay in the
   smart order after the free tiers). Anonymous keyless routes (vireonix, llm7, pollinations) must earn it first
   (a measured tool score). `LOKI_LOCAL_ONLY=1` (Settings > General > "Private") keeps everything,
   jobs included, on this computer.
4. **Failover mid-task keeps the conversation**: 429 / 402 / 401 / context too long / timeout /
   empty choices / 413 all move the SAME turn to the next provider. With another provider ready a
   429 gets one quick retry (not four, and never a long Retry-After wait), a timeout one retry;
   the OpenAI SDK's own hidden retries are off (`max_retries=0`). When everything is spent, the
   provider whose limit ends soonest is tried rather than a local model that is not there.
5. **Local models**: Ollama's OpenAI endpoint ignores `num_ctx`, so LOKI makes a `loki-<model>`
   variant (`/api/create` with `num_ctx`, metadata only) big enough for its prompt + tools
   + room (`model_setup.required_context`: >= 8k, 16k on 10 GB+, 32k on 24 GB+), re-makes an
   older smaller one, reads the real window back (`/api/show` num_ctx, `/api/ps`), and sizes the
   local condenser to it - past the window Ollama silently drops the START of the prompt (the
   system prompt and tools), a main cause of small-model failures. The same applies to
   `local-hermes`/`loki-tuned` and to a pinned `LOKI_LOCAL_MODEL`. Bonsai 2 (Q2_0) needs Ollama
   0.40.6+: on an older one it is never picked or downloaded, and the doctor gives the one update
   command (Windows `winget upgrade --id Ollama.Ollama -e`, Mac `brew upgrade ollama` or the app's
   own "Restart to update"). On a Mac with no Ollama tool model an MLX server on 8082
   (`python -m mlx_vlm.server --model prism-ml/Ternary-Bonsai-2-9B-mlx-2bit --port 8082`) is the
   local fallback.

Routes: `GET /models/doctor`, `GET /providers/health`, `POST /providers/probe {id?}`.

## Subscription coding agents

`claude-code` and `codex` are not API clients. Once installed and signed in they run on
the subscription allowance you already pay, so an extra request costs nothing more - and
they are real coding agents with their own file/edit/shell tools, which they use on the
project folder directly. Loki hands Claude Code its own MCP servers too, so it also gets
the Godot editor tools.

```
npm install -g @anthropic-ai/claude-code   # then: claude   -> /login
npm install -g @openai/codex               # then: codex login
```

Then `LOKI_MODEL=claude-code` (or `codex`). They also sit in Smart order after the free
cloud tiers and before the local models, so when every free quota is spent the job goes
to a real agent rather than a weak local model. Point Loki at a different binary with
`LOKI_CLAUDE_CODE_EXE` / `LOKI_CODEX_EXE`.

## Online mode

`LOKI_MODEL=online` runs Loki with **no Ollama and no GPU**. It picks the best provider
you can reach over the network: the free tiers first, then the subscription agents
(Claude Code / Codex, which need no key and no GPU), and it **never** falls back to a local
model. If nothing is configured it names the provider to set up rather than silently
reaching for a local model you may not have.

```bash
LOKI_MODEL=online
```

This is the mode to use on a machine with no GPU, or when you would rather not install
Ollama at all. `smart` is different: it prefers the same free tiers but falls back to a
local model as a last resort.

## Environment variables

- `<PROVIDER>_API_KEY` — the key (for example `GEMINI_API_KEY`).
- `<PROVIDER>_MODEL` — override the model name.
- `LOKI_MODEL` — which provider to use by default.
- `GODOT_EXE` — path to your Godot 4 executable.

## OmniRoute (optional)

A single local gateway that fronts many providers with automatic fallback.

```
npm install -g omniroute      # needs Node 22
omniroute --no-open           # serves http://localhost:20128/v1
```

Create an API key in the dashboard, put it in `OMNIROUTE_API_KEY`, and set
`LOKI_MODEL=omniroute`.

## Jev (optional typed decisions)

Jev is **not a chat model** — it is a decision model: send one `state` and typed
questions (`choice` / `score` / `noul`) and get probability-backed answers your code
branches on in a few hundred ms. Loki uses it for two loop decisions: the **risk gate**
before a dangerous tool call and **loop detection** when the agent repeats itself.
It is optional and never fatal — no key means Loki behaves exactly as before.

- Key: `TYPESAFE_API_KEY` (aliases `JEV_API_KEY`, `JEV_KEY`) in `harness_data/.env`.
  A hosted `jv_live_` key talks to `https://thejevai.com/v1/systemone`; an official
  `console.typesafe.ai` key to `https://api.typesafe.ai/v1/systemone`. The endpoint
  follows the key; `JEV_BASE_URL` overrides it.
- Model: `JEV_MODEL` (default `typesafe/jev-1.13`); pin a version in production.
- Knobs: `LOKI_JEV=0` disables it; `LOKI_JEV_RISK` (0.15) is the risk threshold;
  `LOKI_JEV_CACHE` caches identical decisions; `GET /jev` on the bridge shows status.
- The MCP route (`mcp_servers.json` -> `"jev"` -> `uvx jev-mcp-server`) is registered
  but **gated by `requires_env: TYPESAFE_API_KEY`**, so it starts (and costs tool
  schemas) only once a key is set.

## Adding your own provider

Each provider is one entry in `MODELS` in `engine/loki.py`:

```python
"myprovider": ModelConfig(base_url="https://.../v1", api_key=os.getenv("MYPROVIDER_API_KEY",""), model="...")
```

## Go-to model: DeepSeek V4.1 via OpenRouter

The default go-to is **`deepseek/deepseek-v4.1-flash`** on OpenRouter: one account, 1M
context, very cheap, and it tolerates a **200-tool** request where Gemini and Groq refuse
one well below that. It leads `SMART_ORDER`, so smart mode picks it whenever
`OPENROUTER_API_KEY` is set. Name it directly with `LOKI_MODEL=deepseek-4.1`, or use
`deepseek-4.1`'s override `DEEPSEEK_41_MODEL`.

## More free tiers (awesome-free-llm-apis)

These providers come from [github.com/mnfst/awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis),
a catalogue of LLM APIs with **permanent** free tiers (it ships a machine-readable `data.json`).
Each is an OpenAI-compatible endpoint, and each is overridable with `<PROVIDER>_MODEL` and
`<PROVIDER>_BASE_URL`. Run `tools/loki_doctor.py` for the signup link of each.

| Loki name | Endpoint | Where to get the key |
| --- | --- | --- |
| `aion` | `https://api.aionlabs.ai/v1` | https://www.aionlabs.ai/app/api-keys/ |
| `cohere` | `https://api.cohere.com/compatibility/v1` | https://dashboard.cohere.com/api-keys |
| `zai` | `https://open.bigmodel.cn/api/paas/v4` | https://open.bigmodel.cn/usercenter/apikeys |
| `huggingface` | `https://router.huggingface.co/v1` | https://huggingface.co/settings/tokens |
| `kilocode` | `https://api.kilo.ai/api/gateway` | https://app.kilo.ai/profile |
| `llm7` | `https://api.llm7.io/v1` | https://token.llm7.io (optional - anonymous use works) |
| `modelscope` | `https://api-inference.modelscope.cn/v1` | https://modelscope.cn/my/myaccesstoken |
| `nvidia` | `https://integrate.api.nvidia.com/v1` | https://build.nvidia.com/explore/discover |
| `ollama-cloud` | `https://ollama.com/api` | https://ollama.com/settings/keys |
| `ovh` | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` | https://www.ovhcloud.com/en/public-cloud/ai-endpoints/ |
| `siliconflow` | `https://api.siliconflow.cn/v1` | https://cloud.siliconflow.cn/account/ak |

Notes:
- These are **selectable by name** (`LOKI_MODEL=zai`). They are deliberately **not** added to
  `SMART_ORDER`, so smart mode keeps its verified failover chain; name one to use it directly.
- Cohere's own v2 API is not OpenAI-shaped, so `cohere` points at Cohere's OpenAI compatibility
  endpoint.
- `llm7` answers anonymously, so it works with no key (like `vireonix`).
- Free-tier terms change and model names move; every value here is an override-able default.
