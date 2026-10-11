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

## Adding your own provider

Each provider is one entry in `MODELS` in `harness/loki.py`:

```python
"myprovider": ModelConfig(base_url="https://.../v1", api_key=os.getenv("MYPROVIDER_API_KEY",""), model="...")
```
