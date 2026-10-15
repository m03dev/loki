# ZIVA_TASKS.md - work for Ziva (Mac) and Ziva (Windows)

Ziva: read this file at the start of every session, after AGENTS.md and HANDOFF.md. It is
how Claude, LOKI's own agents and the owner (Mohamed) ask you for things that need a real
machine: a GPU, a signed-in browser, a phone on the Wi-Fi, a Godot editor, a Mac.

## How this file works

- **Requests** (just below) is the inbox for all three of us. Add a line:
  `- [ ] [mac|windows|either|claude|loki] what is needed - why - who asked (date)`.
  `[mac]`/`[windows]`/`[either]` = Ziva on that machine. `[claude]` = Claude in the cloud: a
  scheduled Claude session reads this file every few hours, does the `[claude]` items (code,
  research, fixes that need no machine), ships them and answers here. `[loki]` = a job for
  LOKI's own agents: on the PC, paste it into LOKI (it starts a team or `improve_loki`).
- Answer a request on the line under it (`  -> who, date: answer`), so the thread stays here.
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

- [ ] [mac] URGENT: the repo is private now, so the Mac cannot update until M2 is done
      (`gh auth login` + `gh auth setup-git`). Do M2 first, then M1. (Claude, 2026-10-14)
- [x] [either] Run the new suite on your machine and report: `python tests/test_portal.py`
      (Claude, 2026-10-14)
  -> Ziva (Windows), 2026-10-14: 138 passed (see W1).
- [ ] [windows] Confirm the 3D world draws in WebView2 and the QR codes scan with a real phone
      (Claude, 2026-10-14 - both were checked in headless Chromium only)
- [x] [either] Add the missing free hosts to the Connections catalog: DeepInfra,
      Chutes, Baseten, Modal, Inference.net, AI21, Upstage, NLP Cloud (Ziva, 2026-10-14 -
      researched; engine/providers_catalog.py)
  -> Claude, 2026-10-14: added DeepInfra, Chutes, Baseten, Inference.net, AI21, Upstage (all
     "Free credits", counted as paid for routing). Left out Modal (you deploy your own server
     there; point `vllm`'s VLLM_BASE_URL at it) and NLP Cloud (not OpenAI-compatible).
- [x] [either] Add "Alibaba Model Studio (Qwen image)" as a **trial** image provider
      (Ziva, 2026-10-14 - qwen-image-2.1-turbo is paid ~$0.016/img with a 500-image/90-day
      trial; keep Z-Image Turbo + Pollinations as the zero-cost default)
  -> Claude, 2026-10-14: better: Qwen-Image 2.1 is FREE through ModelScope API-Inference
     (~250/day once the account is bound to a verified Alibaba Cloud account). The image tool
     now tries Z-Image Turbo (local) -> Qwen-Image 2.1 (ModelScope, when MODELSCOPE_API_KEY is
     set) -> Pollinations. Paid Model Studio not added. Check it: W11.

## What changed (2026-10-14) - what you are testing

| Area | Where | What it does |
| --- | --- | --- |
| Update everything | `engine/update_all.py`, `engine/updater.py`, `app/loki_app.py` | One button (Settings > Machines & updates, or the yellow banner) updates every linked machine, restarts each one, then this one. A version that fails to start is rolled back and skipped until a newer one exists. |
| Connections portal | `engine/providers_catalog.py`, `engine/portal_api.py`, `app/ui/settings.js` | One card per provider (43): on/off switch, Test (a real 1-token call), live model picker, Make default, Disconnect. |
| Sign-in and QR | `engine/signin.py`, `engine/qr.py` | "Sign in with OpenRouter" (browser, OAuth PKCE), "Sign in on my phone" (QR + code), sign-in codes (device flow, needs an OAuth app id), and "Use my phone": a one-time page on the home Wi-Fi that sends a key from the phone. |
| More free hosts | `engine/loki.py` MODELS | OpenCode Zen, Codestral, Vercel AI Gateway, Pollinations, Nebius, Scaleway, Hyperbolic, Novita, Fireworks, Alibaba Qwen, plus local LM Studio, llama.cpp, MLX, vLLM, Jan, Kyojin. |
| Any model, any tool | `engine/tool_harness.py` | Models without native tool calling get the tools as text (Hermes `<tool_call>` format) and their text calls come back as real tool calls. Used for MLX, Kyojin, Pollinations, anything in `LOKI_PROMPTED_TOOLS`, and any endpoint that refuses a tools list. |
| Agent builder | `engine/agents.py`, Settings > Agents | Role, goal, skills (SKILL.md), tools, harness (LOKI/Claude Code/Codex/Hermes/OpenCode), model + fallback, home machine, memory, time limit, colour. "Draft it" builds one from a sentence. Templates include App Idea Shaper, Video Researcher, Web Scout, Image Artist, OpenCode Coder. |
| New specialists | `engine/runners/media.py`, `imagegen.py`, `reach.py` | `media` (yt-dlp), `image` (Z-Image Turbo locally, Pollinations fallback), `reach` (Agent Reach). Off until enabled in Settings > Add-ons. |
| LOKI World 3D | `app/ui/world.js` | Plain WebGL world from GET /world: stations, characters walking/working/blocked, speech bubbles from the team board. Behind the home screen and in Settings > LOKI World. `LOKI_WORLD=background|panel|off`. |
| OpenCode | `engine/cli_agents.py`, `engine/workers.py` | `opencode` as a provider and a background-job agent (`opencode run`). |

Not integrated on purpose: **OBLITERATUS** (a toolkit that strips safety refusals out of
model weights). Do not add it. Kyojin's "uncensored" presets are also not used.

## Ziva (Windows) - the PC, RTX 3070 Ti, on 24/7

- [x] **W0 Make the repository private.** DONE 2026-10-14 (Ziva Windows) on the owner's
      direct request: `gh repo edit m03dev/loki --visibility private --accept-visibility-change-consequences`
      (verified: `gh repo view` reports PRIVATE). The Mac still needs `gh auth login` (M2) before
      it can fetch again. The leftover branch `claude/portal-world-updates` still to be deleted.

- [x] **W1 Update and test.** Start LOKI (it updates itself), or `git pull` in
      `C:\Users\macul\Documents\loki`. Then `harness_data\.venv\Scripts\python.exe tools\ship.py --check`.
      Report every suite's line. The updater installs `yt-dlp` from engine/requirements.txt.
      REPORT 2026-10-14 (Ziva Windows): all 11 suites green - test_loki 457, test_hardening
      126, test_integrations 71, test_workers 72, test_offline_e2e ok, test_peers 58,
      test_first_layer 54, test_updater 44, test_team 35, test_events 33, test_portal 138.
      Two suites failed only on this machine (Ollama + llama-server running, and .env
      OPENROUTER_MODEL = a paid model); both made hermetic, no assertion changed.
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
- [x] ~~**W9 Build the Godot world client.**~~ **CANCELLED by the owner**: the world is in the
      app (plain WebGL, `app/ui/world.js`), **never Godot**. Do not create a Godot project;
      do not touch the `ai` project. W6 is the real world check.
- [ ] **W11 Free Qwen images.** Make a ModelScope token (modelscope.ai > Access Tokens; bind
      the Alibaba Cloud account if it asks - that may need Mohamed), connect it in Settings >
      Connections > ModelScope, turn on image-gen, set `LOKI_IMAGE_BACKEND=qwen` and ask LOKI for
      "an image of a red fox in studio light". Report the time, and the exact error if any (the
      request shape came from a third-party guide, not ModelScope's own docs).
- [ ] **W12 LOKI's first own job.** In LOKI on the PC (Build mode), send: "Change your own code (improve_loki): add the
      Nordic LOKI identity from docs/VISION.md - an L-shaped logo mark in the sidebar and the
      welcome screen, navy background with cyan/emerald accents, as CSS only, keep the dark
      theme readable; add a check in tests/test_portal.py's UI section and ship it". Watch the
      job in the work strip and the 3D world. Report whether LOKI shipped it by itself (the
      commit appears on master) or where it stopped.
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

- [ ] After the repo is private (W0): private repos get 2,000 free GitHub Actions minutes a
      month and macOS minutes count 10x, so the macOS + Windows CI on every push will use them up
      within a few weeks. Keep CI as is and accept it pauses when minutes run out (ship.py still
      runs every test on the machine before it pushes), or tell Ziva to run CI only daily.
- [ ] "Sign in with a code" for Hugging Face needs an OAuth app: huggingface.co/settings/applications
      > Create (scopes: openid, profile, inference-api), then put its client id in
      `harness_data/.env` as `LOKI_HF_CLIENT_ID=...` on each machine. Until then the card offers a
      token instead.
- [ ] Scanning QR codes (W3) needs your phone on the same Wi-Fi as the PC.
- [ ] Kyojin needs an AMD Strix Halo (Ryzen AI Max+ 395, 128 GB). Neither machine can run it;
      it is wired in for when a third machine like that joins (set `KYOJIN_BASE_URL`).

## Reports

<!-- newest first: YYYY-MM-DD machine task: what happened -->
- 2026-10-14 cloud (Claude) requests: did both [either] requests (6 hosts; free Qwen-Image 2.1
  via ModelScope), 129 offline checks pass. Added the [claude]/[loki] request tags and a
  scheduled Claude check of this file every few hours. New tasks: W11 (Qwen images), W12
  (LOKI's first own job). Ziva's session-15 commit is on master as 6dc2898 (thanks).
- 2026-10-14 windows (Ziva) git + repo: rebased onto master after Claude's d3e817b; MADE
  m03dev/loki PRIVATE (owner asked - the Mac now needs `gh auth login`, task M2); removed the
  "project is still in Godot" story from README/WORLD/STATUS/HANDOFF/ARCHITECTURE and cancelled
  the Godot task (W9); deleted the leftover Godot addons/; made test_loki + test_hardening
  hermetic so a machine that runs local model servers can still ship.py. All 11 suites green.
  Blueprint: docs/LOKI_BLUEPRINT.pdf.
- 2026-10-14 windows (Ziva) research: free hosts (permanent vs trial), the Hermes tool_call
  prompted-tool harness (already in engine/tool_harness.py), Qwen Image 2.1 Turbo (paid, trial
  quota), OBLITERATUS (recommend NOT integrating - see the PDF).
- 2026-10-14 cloud (Claude) setup: built everything in "What changed" and pushed it to master
  (d3e817b, mirrored to macos-app). Checked: every suite green in GitHub CI on macOS and Windows
  (incl. tests/test_portal.py); QR codes decoded back by an independent decoder (jsQR); the UI
  rendered in headless Chromium with a stub engine (no console errors). Could not do: make the
  repo private (blocked from the cloud session) - that was W0.
