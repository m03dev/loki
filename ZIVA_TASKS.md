# ZIVA_TASKS.md - work for Ziva (Mac) and Ziva (Windows)

Ziva: read this file at the start of every session, after AGENTS.md and HANDOFF.md. It is
how Claude, LOKI's own agents and the owner (Mohamed) ask you for things that need a real
machine: a GPU, a signed-in browser, a phone on the Wi-Fi, a Godot editor, a Mac.

## How this file works

- **Requests** (just below) is the inbox. Anyone who needs something from a machine adds a
  line there: `- [ ] [mac|windows|either] what is needed - why - who asked (date)`.
- Take the oldest open request for your machine first, then the numbered task lists.
- When you finish one: tick it (`- [x]`), add one line under **Reports** at the bottom
  (date, machine, what you did, what you saw, what failed - paste exact errors), and ship:
  `python tools/ship.py -m "ziva(<mac|windows>): <task id> <result>"`.
  Windows: `harness_data\.venv\Scripts\python.exe tools\ship.py -m "..."`.
- If a task needs Mohamed (an account, a password, a phone, a purchase, a decision), do not
  guess: move it to **Needs Mohamed** with the exact question, and continue with the next one.
- Never commit anything from `harness_data/` (keys, tokens, models). Never paste a key here.
- Never push anything except through `tools/ship.py`, never `push --force`.
- If the tests fail after you change something, fix it or revert your change before shipping.

## Requests

- [ ] [either] Run the new suite on your machine and report: `python tests/test_portal.py`
      (Claude, 2026-10-14 - written in the cloud, where LOKI's packages could not be installed;
      CI runs it on macOS and Windows, but a real machine run is the proof)
- [ ] [windows] Confirm the 3D world draws in WebView2 and the QR codes scan with a real phone
      (Claude, 2026-10-14 - both were checked in headless Chromium only)

## What changed (2026-10-14) - what you are testing

| Area | Where | What it does |
| --- | --- | --- |
| Update everything | `engine/update_all.py`, `engine/updater.py`, `app/loki_app.py` | One button (Settings > Machines & updates, or the yellow banner) updates every linked machine, restarts each one, then this one. A version that fails to start is rolled back and skipped until a newer one exists. |
| Connections portal | `engine/providers_catalog.py`, `engine/portal_api.py`, `app/ui/settings.js` | One card per provider (43): on/off switch, Test (a real 1-token call), live model picker, Make default, Disconnect. |
| Sign-in and QR | `engine/signin.py`, `engine/qr.py` | "Sign in with OpenRouter" (browser, OAuth PKCE), "Sign in on my phone" (QR + code), sign-in codes (device flow, needs an OAuth app id), and "Use my phone": a one-time page on the home Wi-Fi that sends a key from the phone. |
| More free hosts | `engine/loki.py` MODELS | OpenCode Zen, Codestral, Vercel AI Gateway, NVIDIA NIM/Kilo in smart order, Pollinations, Nebius, Scaleway, Hyperbolic, Novita, Fireworks, Alibaba Qwen, plus local LM Studio, llama.cpp, MLX, vLLM, Jan, Kyojin. |
| Any model, any tool | `engine/tool_harness.py` | Models without native tool calling get the tools as text (Hermes `<tool_call>` format) and their text calls come back as real tool calls. Used for MLX, Kyojin, Pollinations, anything in `LOKI_PROMPTED_TOOLS`, and any endpoint that refuses a tools list. |
| Agent builder | `engine/agents.py`, Settings > Agents | Role, goal, skills (SKILL.md), tools, harness (LOKI/Claude Code/Codex/Hermes/OpenCode), model + fallback, home machine, memory, time limit, colour. "Draft it" builds one from a sentence. Templates include App Idea Shaper, Video Researcher, Web Scout, Image Artist, OpenCode Coder. |
| New specialists | `engine/runners/media.py`, `imagegen.py`, `reach.py` | `media` (yt-dlp), `image` (Z-Image Turbo locally, Pollinations fallback), `reach` (Agent Reach). Off until enabled in Settings > Add-ons. |
| LOKI World 3D | `app/ui/world.js` | Plain WebGL world from GET /world: stations, characters walking/working/blocked, speech bubbles from the team board. Behind the home screen and in Settings > LOKI World. `LOKI_WORLD=background|panel|off`. |
| OpenCode | `engine/cli_agents.py`, `engine/workers.py` | `opencode` as a provider and a background-job agent (`opencode run`). |

Not integrated on purpose: **OBLITERATUS** (a toolkit that strips safety refusals out of
model weights). Do not add it. Kyojin's "uncensored" presets are also not used.

## Ziva (Windows) - the PC, RTX 3070 Ti, on 24/7

- [ ] **W1 Update and test.** Start LOKI (it updates itself), or `git pull` in
      `C:\Users\macul\Documents\loki`. Then `harness_data\.venv\Scripts\python.exe tools\ship.py --check`.
      Report every suite's line. The updater installs `yt-dlp` from engine/requirements.txt.
- [ ] **W2 Connections portal.** Settings > Connections. Press **Test** on every connected card
      (OpenRouter, DeepSeek, Groq, Gemini, Claude Code, Codex). Report each result line. Open a
      model picker on two of them and confirm the list loads. Switch Groq off, send a chat, check
      Groq is not used (the route line in /health), switch it back on.
- [ ] **W3 Phone hand-off.** On a provider you have not connected (e.g. Codestral or OpenCode Zen),
      click **Use my phone**. If Windows Firewall asks about Python, allow **Private networks only**.
      Scan the QR with Mohamed's phone (or note it under Needs Mohamed). Report whether the page
      opened and the key connected.
- [ ] **W4 OpenRouter sign-in.** On a copy with no OpenRouter key (or after Disconnect), use
      **Sign in with OpenRouter**. Report whether the browser came back to "Connected".
- [ ] **W5 Extras.** `harness_data\.venv\Scripts\python.exe tools\setup_extras.py media`, then
      `opencode`, then `agent-reach`, then `imagegen` (CUDA torch, ~20 GB). Turn on media,
      image-gen, agent-reach and opencode in Settings > Add-ons. Then ask LOKI:
      1. "get the transcript of <a YouTube URL>" (media),
      2. "make an image of a red fox in studio light" - time it; it should use `zimage` on CUDA
         with CPU offload (8 GB). If it runs out of memory, report the error and the free RAM,
      3. "use reach doctor" (which Agent Reach channels work),
      4. start the **OpenCode Coder** template agent on a tiny task.
- [ ] **W6 LOKI World.** Home screen: the world should be faintly visible behind "What should
      Loki work on?". Settings > LOKI World: drag to orbit, wheel to zoom. Start a team
      ("build a landing page for a bakery and test it") and watch characters walk to their
      stations. Take a screenshot into `docs/operations/screens/world-windows.png` (that folder is
      fine to commit). If the canvas is blank, open the WebView devtools (`LOKI_APP_DEBUG=1`) and
      paste the console errors.
- [ ] **W7 Update everything.** Once the Mac is linked (M3), ship any tiny change from the Mac,
      then on the PC press **Update everything**. Expected: the Mac restarts first, then the PC;
      the panel shows both on the same commit. Report the step lines.
- [ ] **W8 Prompted tools on a local model.** Start llama.cpp *without* `--jinja` (or LM Studio)
      with a small model, set it as default in the portal, and ask LOKI to "list the files here
      and read README.md". Report whether tools ran ("tools via harness" shows on the card).
- [ ] **W9 The Godot 3D world (your specialty).** Build the native world client from
      docs/WORLD.md as its own Godot 4 project in `~/LOKI Projects/loki-world` (never in this
      repo). Use the same station names and layout as `app/ui/world.js` (STATION_LAYOUT) and the
      same data (GET /world, GET /events long poll). Kenney and KayKit assets are CC0; check
      Quaternius packs (some are QAL v1.0 now) before using them. Report how to run it.
- [ ] **W10 24/7.** Make LOKI start at boot on the PC (Task Scheduler running `Loki.cmd`, or a
      service). An engine started without the app now restarts itself after **Update everything**
      (it starts a new copy and exits). Confirm that works headless.

## Ziva (Mac) - the Mac mini

- [ ] **M1 Checkout.** Mohamed chose `~/Loki` for the Mac checkout; HANDOFF.md still says
      `~/Documents/loki`. Use the one that exists (ask under Needs Mohamed if both or neither),
      then fix HANDOFF.md to match. Run `bash setup.sh` once (this also installs Laya), then
      `harness_data/.venv/bin/python tools/ship.py --check` and report.
- [ ] **M2 GitHub sign-in (do this before the repo goes private).** `brew install gh`,
      `gh auth login` (GitHub.com, HTTPS, browser), then `gh auth setup-git`. Check with
      `git -C <checkout> fetch origin master`. Without this the Mac cannot update once
      m03dev/loki is private. On the PC, check the same `git fetch` works (Git Credential Manager).
- [ ] **M3 Link the machines.** They are on different networks (192.168.1.x / 192.168.0.x).
      Install Tailscale on both (same account), then on the Mac: Settings > Machines &
      updates > Link another machine, with the PC's link code. Report `ms` from the Machines panel.
- [ ] **M4 MLX.** `harness_data/.venv/bin/python tools/setup_extras.py mlx`, then keep
      `mlx_lm.server --model mlx-community/Qwen3-4B-4bit --port 8082` running. The MLX card should
      say **Running**. Make it the default and ask LOKI to "list the files here and read README.md".
      MLX tool calls go through the prompted harness: report whether the tools ran and how fast
      (tokens/s from the usage line). Try one bigger model if memory allows and report.
- [ ] **M5 Laya on Apple Silicon ("Laya MLX").** Laya is a decision model (typed answers in one
      pass), not a text model, so there is no MLX build of it and mlx-lm cannot run it. What can
      help: ONNX Runtime's CoreML execution provider. Measure `python tools/setup_laya.py --check`
      latency now; then, if `@receptron/laya` lets you pass ONNX session options, try
      `executionProviders: ["coreml", "cpu"]` in `engine/laya_server.mjs` and measure again.
      Ship it only if it is faster and every suite passes; otherwise report the numbers.
- [ ] **M6 World + portal on WKWebView.** Same checks as W2 and W6 on the Mac; screenshot to
      `docs/operations/screens/world-mac.png`.
- [ ] **M7 Images on the Mac.** `tools/setup_extras.py imagegen` installs torch for MPS. Generate
      one 768x768 image and report the time and memory pressure. If it is too heavy for this Mac,
      say so: LOKI will keep using the PC (agents with "Lives on: Best machine") or Pollinations.

## Needs Mohamed

- [ ] Make **m03dev/loki private** only after M2 is done on the Mac (and the PC's `git fetch`
      works), or both machines stop getting updates. Note: private repos get 2,000 free GitHub
      Actions minutes a month and macOS minutes count 10x, so the macOS + Windows CI on every push
      will use them up quickly. Options: keep CI as is and accept it stops when minutes run out
      (ship.py still runs every test locally), or limit CI to pull requests / a daily run.
- [ ] "Sign in with a code" for Hugging Face needs an OAuth app: huggingface.co/settings/applications
      > Create (scopes: openid, profile, inference-api), then put its client id in
      `harness_data/.env` as `LOKI_HF_CLIENT_ID=...` on each machine. Until then the card offers a
      token instead.
- [ ] Scanning QR codes (W3) needs your phone on the same Wi-Fi as the PC.
- [ ] Kyojin needs an AMD Strix Halo (Ryzen AI Max+ 395, 128 GB). Neither machine can run it;
      it is wired in for when a third machine like that joins (set `KYOJIN_BASE_URL`).

## Reports

<!-- newest first: YYYY-MM-DD machine task: what happened -->
- 2026-10-14 cloud (Claude) setup: built everything in "What changed". Checked here: the new
  offline suite (tests/test_portal.py, 122 checks, pure parts), QR codes decoded back by an
  independent decoder (jsQR), the UI rendered in headless Chromium with a stub engine (Settings,
  portal, agents, world 3D, QR modal - no console errors). Not checked here: the full engine
  suites (LOKI's Python packages could not be installed in the cloud workspace) - CI and W1/M1
  are that check.
