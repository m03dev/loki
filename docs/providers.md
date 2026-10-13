# Model providers

Loki talks to any **OpenAI-compatible** endpoint. Put keys in `harness/.env`
(copy from `harness/.env.example`) and choose one with `LOKI_MODEL`.

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

Each provider is one entry in `MODELS` in `harness/loki.py`:

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
