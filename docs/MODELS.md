# MODELS - which model LOKI uses for what (researched 2026-10-26)

Owner 2026-10-26: "whats our strongest model and fastest. we need a mode for that to get hard tasks done ... do
research on best models". The model picker now has four automatic modes; the order each one tries is in
`engine/loki.py` (SMART_ORDER, ONLINE_ORDER, MAX_ORDER, FAST_ORDER) and can be replaced with
`LOKI_MAX_ORDER=a,b,c` / `LOKI_FAST_ORDER=a,b,c` in harness_data/.env.

| Mode | For | First pick (when ready) | Then |
| --- | --- | --- | --- |
| **Smart** | everyday chat and jobs | the main driver: DeepSeek V4.1 Flash on NVIDIA (free) | learned order, local model |
| **Online only** | Smart without this computer's models | same | free cloud only |
| **Max (hard tasks)** | hard builds, debugging, planning, anything Smart got wrong | Claude Code (your plan: Claude Opus / Sonnet 5.5), Codex (your plan: GPT-6.x) | `nvidia-pro` = the strongest open model the free NVIDIA key serves (GLM-5.3), thinking on; paid APIs only if paid use is allowed; then Smart's order |
| **Fast** | quick questions, many small steps | `nvidia-nemotron` = Nemotron on the free NVIDIA key | the main driver, a small local model, then Smart's order |

2026-10-27: Cerebras, Groq, SambaNova and OpenRouter's free models were removed - they run out daily (see
docs/providers.md "The lean set"); the research below is kept as the record of why they were picked then.

Max never switches to a pay-per-use API by itself (same rule as Smart). The `nvidia-pro` route shares NVIDIA's
per-minute window with the main driver (`engine/ratelimit.py` buckets every `nvidia-*` route) - it is one key.

## What the research said (October 2026)

**Strongest overall (closed).** BenchLM's agentic leaderboard (updated 2026-10-26) has Claude Opus 5.5 first by a wide
margin, then Claude Fable 5.1, Claude Opus 5, Gemini 4 Argon and GPT-6.1 Sol. On Terminal-Bench 4.0 (Morph, mostly
vendor-reported) Claude Sonnet 5.5 leads, then Opus 5.5 and GPT-6 Astra. LOKI reaches these without per-token cost
through the owner's subscriptions (`claude-code`, `codex` - `engine/harness/cli_agents.py`), which is why Max tries
them first.

**Strongest free / open.** DeepSeek V4 Pro (0813) is listed at ~96% SWE-bench Verified (second on Vals) and is on
NVIDIA's free preview API (`deepseek-ai/deepseek-v4-pro`, 1M context). GLM-5.3 and Kimi K3 are the other top open
models, but NVIDIA lists only older Kimi/GLM ids (`moonshotai/kimi-k2.6`, `z-ai/glm5`), so they are not wired in.
DeepSeek V4.1 Flash (the main driver) is cheap and fast but far weaker on hard agentic work (Terminal-Bench 4.0
~31% vs ~66-70% for the Claude 5.5 models) - right for Smart, wrong for Max.

**Fastest.** gpt-oss-120B on Cerebras ran at ~1,750 output tokens/s in June 2026 (Artificial Analysis via
TokenDyno), several times anything else; Groq ~480 t/s on the same model. Free and fast: Nemotron 3.5 Lightning
(OpenRouter `:free`, ~300 t/s, 1M context, tools). Cerebras' default model in LOKI moved from llama-3.3-70b to
`gpt-oss-120b` (`CEREBRAS_MODEL` still overrides it). Note: Cerebras needs a verified payment method to activate.

**Best free OpenRouter model for agents.** `poolside/laguna-s-2.1:free` (262K, tool calling, high uptime) - already
LOKI's OpenRouter default. Free OpenRouter models: 20 requests/min, 50/day (1,000/day after a one-time $10 credit).

**Local.** Nothing local is in the same league as the cloud models above. On the PC's 8 GB RTX 3070 Ti the 7-8B
tool-callers stay (qwen3:8b and the abliterated qwen3 the owner asked for); on the 16 GB Mac keep local models small
and never beside Blender (the 2026-10-26 crash). Hard work goes to Max, not to a bigger local model.

## Sources

- [BenchLM agentic leaderboard](https://benchlm.ai/agentic) (2026-10-26)
- [Morph: best AI model for coding, October 2026](https://www.morphllm.com/best-ai-model-for-coding)
- [NVIDIA NIM model list (pi-nvidia-nim)](https://pi.dev/packages/pi-nvidia-nim) and [DeepSeek V4 Pro 0813 on build.nvidia.com](https://build.nvidia.com/deepseek-ai/deepseek-v4-pro-0813/modelcard)
- [OpenRouter free models, checked live (Oct 2026)](https://www.aieatingtheworld.com/articles/openrouter-free-models)
- [Free NVIDIA models on OpenRouter, speeds](https://modelgrep.com/best/free/nvidia)
- [TokenDyno: fastest LLM inference](https://tokendyno.com/blog/fastest-llm-inference/)
- [Morph: best Ollama models by VRAM](https://www.morphllm.com/best-ollama-models)
