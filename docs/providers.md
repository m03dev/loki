# Model providers

Loki talks to any **OpenAI-compatible** endpoint. Put keys in `harness/.env`
(copy from `harness/.env.example`) and choose one with `LOKI_MODEL`.

| `LOKI_MODEL` | Provider | Free tier |
|---|---|---|
| `local` / `local-reasoning` | Ollama (local) | yes, local |
| `gemini` | Google AI Studio | yes |
| `groq` | Groq | yes |
| `openrouter` | OpenRouter | yes (`:free` models) |
| `cerebras` | Cerebras | yes |
| `mistral` | Mistral | yes |
| `together` | Together AI | yes |
| `deepseek` | DeepSeek | paid |
| `omniroute` | local OmniRoute gateway | routes to any of the above |
| `cloud` | Loki Cloud (after Google sign-in) | key stays server-side |
| `gpt` / `claude` | OpenAI / Anthropic | paid |

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
