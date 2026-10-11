# Model providers

Loki talks to any **OpenAI-compatible** endpoint. Put keys in `harness/.env`
(copy from `harness/.env.example`) and choose one with `LOKI_MODEL`.

| `LOKI_MODEL` | Provider | Free tier |
|---|---|---|
| `local` / `local-reasoning` | Ollama (local) | yes, local |
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
| `deepseek` | DeepSeek | paid |
| `omniroute` | local OmniRoute gateway | routes to any of the above |
| `cloud` | Loki Cloud (after Google sign-in) | key stays server-side |
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
