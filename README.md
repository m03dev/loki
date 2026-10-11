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
- **Any model, zero setup** — it runs with **no key at all** (the built-in
  `vireonix` route needs no account and no card), or point it at any free tier
  (Gemini, Groq, OpenRouter, SambaNova, Cloudflare Workers AI, UnoRouter, Nous) or a
  local Ollama model. `LOKI_MODEL=smart` picks the best one you have and falls over
  automatically when a quota runs out. Your Claude Code / Codex subscription also
  works as a provider.
- **Skills built in** — ships with the [Ponytail](https://github.com/DietrichGebert/ponytail)
  "least-code-that-works" standard and can load any of the 70+ specialised
  agents from [ECC](https://github.com/affaan-m/ECC).
- **Memory + autonomy** — persistent conversation and a task loop that keeps
  going until the job is done.

## Tests

```bash
harness_data/.venv/Scripts/python.exe tests/test_loki.py          # structural, offline
harness_data/.venv/Scripts/python.exe tests/test_loki.py --live   # + MCP and a real turn
```

See `HANDOFF.md` for the layout, modes, provider notes and the traps worth knowing.

## Requirements

| Piece | Needed for | Notes |
|---|---|---|
| **Godot 4.3+** | the editor plugin | set `GODOT_EXE` if it is not in the default path |
| **Python 3.11+** | the agent bridge | a private venv is made in `harness_data/.venv` |
| **Ollama** (optional) | local models | `ollama pull qwen3.5:9b` |
| **Node 22 + npm** (optional) | the OmniRoute gateway | see `docs/providers.md` |

See `docs/dependencies.md` for the full picture and packaging notes.

## Install

```bat
git clone https://github.com/m03dev/loki
cd loki
setup.bat
```
On macOS or Linux use `./setup.sh` instead.

Then open the folder as a Godot project and enable **Loki** in
*Project -> Project Settings -> Plugins*. The dock appears beside Scene.

Setup creates the Python environment, installs the dependencies, fetches the skill
libraries and runs the doctor. It is safe to re-run.

## Choosing a model — you do not have to

Loki starts on `LOKI_MODEL=smart`, which uses the best provider you have, falls over
automatically when one runs out of quota, and works with **no keys at all**. To add a
key, copy `addons/loki/harness/.env.example` to `harness_data/.env` and fill in any
provider you have — or run:

```bash
harness_data/.venv/Scripts/python.exe tools/loki_doctor.py
```

which lists every provider, whether it is ready, and the link to get a key for it.
Details in `docs/providers.md`.

## Layout

```
addons/loki/          the Godot editor plugin (dock, bridge, bundled agent)
  harness/            the Python agent (loki.py), tools, mcp_servers.json
  godot_mcp/          the vendored Godot editor MCP bridge
harness_data/         YOUR data - keys, memory, chats, downloaded skills, .venv
docs/                 dependencies, providers, sign-in
tools/                loki_doctor.py and headless checks
```

## Signing in with Google

Optional hosted mode — run the agent on Loki Cloud with the model key kept
server-side, so users need no keys of their own. Implemented in `cloud/`;
see `docs/google-signin.md`. It is entirely optional: Loki works fully
offline with a local model or your own key.

## License

MIT — see [LICENSE](LICENSE).
