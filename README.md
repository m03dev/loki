# Loki - Local Omni Kit Interface

An AI game-dev agent that lives inside the **Godot 4** editor. You describe a change
and Loki investigates, plans, edits your scenes and scripts, runs Godot to check its
own work, and iterates until the job is done - locally, or on any model you have access
to. Repo: https://github.com/m03dev/loki

## The interface

- **Chat dock** - a clean panel in the left dock column, beside Scene. Each
  conversation gets its own tab; the transcript scrolls, the composer sits under it,
  and the toolbar holds the model picker, the mode picker and Stop.
- **Loki screen** - the **Loki** tab in the viewport. A small welcome with *Open chat*
  and *Settings*, so the tab is a useful place and not a dead end.
- **Ask, Plan, Build** - three ways to work, chosen from the mode picker:
  - **Ask** answers your question and calls no tools at all.
  - **Plan** reads your project, asks up to three clarifying questions, then writes a
    numbered plan. It cannot write, run or delete anything.
  - **Build** is the full autonomous agent: it edits, runs and verifies.
- **Settings** - a tabbed dialog: **Agent** (turn tool categories on and off),
  **Account**, **Memory** (facts Loki keeps), **Profile** and **Connections** (what it
  can reach right now - secrets are never shown).
- **Approvals and Stop** - dangerous tools ask first, and a running task can be stopped
  mid-turn.

## What it can do

- **Real verification** - validates scenes (`validate_scene`), compiles scripts
  (`check_script`) and actually runs scenes (`play_scene`) before claiming success.
- **519 skills across six libraries** - ECC, GodotPrompter, Superpowers,
  awesome-gamedev, gamedev-plugin and agentic-gamedev are vendored in
  `harness_data/vendor/` and browsable from the dock ("Agents and skills"). Loki adopts
  whichever suits the task, and ships with the
  [Ponytail](https://github.com/DietrichGebert/ponytail) "least code that works"
  standard.
- **Memory** - lasting facts about you and the project, editable in Settings, plus
  saved conversations that reopen in their own tab.
- **Live editor tools** - a bundled Godot MCP bridge (MIT) gives Loki hands inside the
  running editor; extra MCP servers can be opted into without any of them being
  required.

## Models - no single provider

Loki runs with **no key at all**: the built-in `vireonix` route needs no account and
no card, and a local Ollama model always works. Point it at a free tier (Gemini, Groq,
OpenRouter, SambaNova, Cloudflare Workers AI, Nous) or use your Claude Code / Codex
subscription as a provider.

`smart` prefers the best provider you have (OpenRouter leading with DeepSeek) and fails
over automatically when a quota runs out or a request is rejected - a provider going
dark degrades the run, it does not end it.

## Install

```bash
setup.bat      # Windows
./setup.sh     # Linux / macOS
```

Then enable **Loki** and **Loki Chat** in Project Settings -> Plugins.

## Tests

```bash
harness_data/.venv/Scripts/python.exe tests/test_loki.py          # 173 structural checks, offline
harness_data/.venv/Scripts/python.exe tests/test_loki.py --live   # + MCP and a real model turn
```

`HANDOFF.md` has the layout, the mode internals, provider notes and the traps worth
knowing before changing anything.
