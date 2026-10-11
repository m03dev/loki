# Loki — Local Omni Kit Interface

An AI game-dev agent that lives inside the **Godot 4** editor. You describe a
change in the dock; Loki plans, edits your scenes and scripts, runs Godot to
check its work, and iterates until it is done — locally or on any LLM you have
a key for.

## Features

- **Godot-native dock** — a chat beside the Scene dock with **conversation
  tabs and saved history**, live progress, tool approvals and a Stop button.
- **Memory + saved chats** — every chat is kept on disk and reopens in a tab;
  lasting facts live in an editable Memory (Settings → Memory).
- **ECC agent library** — 71 specialist agents and 311 skills from
  [affaan-m/ECC](https://github.com/affaan-m/ECC), fetched from GitHub on first
  run and browsable from the dock ("Agents and skills"); Loki adopts whichever
  one suits the task.
- **Real verification** — Loki validates scenes (`validate_scene`), compiles
  scripts (`check_script`) and actually runs scenes (`play_scene`) before it
  claims success.
- **Any model** — local Ollama out of the box; optional free cloud providers
  (Gemini, Groq, OpenRouter, Cerebras, Mistral, Together, …) and the OmniRoute
  gateway.
- **Skills built in** — ships with the [Ponytail](https://github.com/DietrichGebert/ponytail)
  "least-code-that-works" standard and can load any of the 70+ specialised
  agents from [ECC](https://github.com/affaan-m/ECC).
- **Memory + autonomy** — persistent conversation and a task loop that keeps
  going until the job is done.

## Requirements

| Piece | Needed for | Notes |
|---|---|---|
| **Godot 4.3+** | the editor plugin | set `GODOT_EXE` if it is not in the default path |
| **Python 3.11+** | the agent bridge | a venv is created by `setup.bat` |
| **Ollama** (optional) | local models | `ollama pull qwen3.5:9b` |
| **Node 22 + npm** (optional) | the OmniRoute gateway | see `docs/providers.md` |

See `docs/dependencies.md` for the full picture and packaging notes.

## Install

```bat
git clone https://github.com/m03dev/loki
cd loki
setup.bat
```

Then open the folder as a Godot project and enable **Loki** in
*Project -> Project Settings -> Plugins*. The dock appears beside the Scene dock.

## Choosing a model

Copy `harness/.env.example` to `harness/.env` and add any key you have — every
listed provider has a free tier. Then set `LOKI_MODEL` (e.g. `gemini`, `groq`,
`local-reasoning`, `omniroute`). Details in `docs/providers.md`.

## Layout

```
addons/loki/     the Godot editor plugin (dock + bridge launcher)
harness/         the Python agent (loki.py), tools and memory
docs/            dependencies, providers, sign-in
tools/           headless checks
```

## Signing in with Google

Optional hosted mode — run the agent on Loki Cloud with the model key kept
server-side, so users need no keys of their own. Implemented in `cloud/`;
see `docs/google-signin.md`. It is entirely optional: Loki works fully
offline with a local model or your own key.

## License

MIT — see [LICENSE](LICENSE).
