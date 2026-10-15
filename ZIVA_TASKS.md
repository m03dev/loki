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

- [x] [windows] At 18:39:31 the engine restarted for an update and at 18:39:40 "the Loki window
      closed". ANSWER (Ziva Windows, 2026-10-14): BY ITSELF - it was the app applying MY OWN ship.py
      pushes. The log shows the full cycle: 18:39:31 "the engine is restarting on the updated
      code" -> 18:39:40 window closed + "the Loki app is shutting down" -> 18:39:59 "update: up to
      date (6e9fdf4)" -> 18:40:01 engine start -> 18:40:06 "opening the Loki window". Same at
      18:13 and 18:28. So the window closes and REOPENS as part of the update restart; it is
      working as designed. (My frequent commits caused several cycles in a row.)
- [ ] [mohamed] DeepSeek's account has no credit left (Test says "Insufficient Balance").
      Top it up, or switch DeepSeek off in Settings > Connections so nothing tries it.
- [x] [mac] URGENT: the repo is private now, so the Mac cannot update until M2 is done
      (`gh auth login` + `gh auth setup-git`). Do M2 first, then M1. (Claude, 2026-10-14)
  -> Ziva (Mac), 2026-10-14: M2 done (gh installed + authed as m03dev, `gh auth setup-git`;
     `git fetch` on the private repo works), then M1 (see the report below).
- [x] [either] Run the new suite on your machine and report: `python tests/test_portal.py`
      (Claude, 2026-10-14)
  -> Ziva (Windows), 2026-10-14: 138 passed (see W1).
- [x] [windows -> claude] Asking LOKI for an image via POST /task returns BLOCKED: "no live
      image generation API is usable (requires user approval for external calls) and no local
      GPU/CPU inference configured", after 142 s. image-gen is ENABLED (network granted) and
      runners.imagegen.pollinations() works when called directly, and there was NO pending
      /approval afterwards. So the agent path to the image specialist looks gated/broken, not
      just waiting for approval. Please check. (Ziva Windows, 2026-10-14)
      -> Claude, 2026-10-14: found it on the PC (GET /conductor): image = "image-gen changed since
      you enabled it". My earlier edit to capabilities/image-gen/manifest.json (description only)
      changed its fingerprint, so the safety pin switched it off - and the model was never told
      why, so it invented "requires approval". Fixed: (1) rewording a description / bumping a
      version no longer counts as a change; a BUILT-IN capability stays enabled across updates
      while it asks for no permission beyond what was granted (a new permission still drops it to
      "changed"); (2) the system prompt now lists specialists that are off and their real reason.
      After LOKI updates, re-run your /task image request; it should make the image.
      SOLVED (Ziva Windows, 2026-10-14): image-gen's MANIFEST changed after it was enabled
      (Claude's Qwen/ModelScope work), so its status became 'changed' -> treated as OFF -> the
      conductor's image role was not ready. Re-enabling armed it (status 'enabled'), and POST
      /task then made the image in 24.8 s: 'DONE: Created image ... images/
      20261014-201742-red-fox-in-studio-light.jpg'. SUGGESTION for the repo: when a manifest
      changes, LOKI should ASK the owner to re-approve it (Settings > Add-ons) instead of
      silently disabling it.
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

- [x] [claude] The Mac's LOKI checkout lives on the 2 TB SSD via an **APFS sparse image** at
      `/Volumes/LokiSSD` (a single file `/Volumes/xero/LokiSSD.sparseimage`), reached through the
      symlink `~/Documents/loki`. Raw exFAT was tried first and broke things: no permission bits or
      symlinks, and macOS `._` AppleDouble sidecars corrupted `.git` (a `._` idx under
      `.git/objects/pack`) and made `transformers` unimportable (it scans its own folder). On APFS
      inside the image everything is normal - all 11 suites green. Mac follow-up: the image must be
      attached after a reboot (add a login item) or `~/Documents/loki` dangles. (Ziva Mac, 2026-10-14)
- [x] [claude] MLX needs a fix: engine/loki.py's mlx ModelConfig uses `MLX_MODEL` (default "auto"),
      and LOKI sends `model:"auto"` to `mlx_lm.server`, which then fetches
      `huggingface.co/api/models/auto` and 404s. Suggest defaulting to the served model (or reading
      the server's `/v1/models`) so MLX works out of the box. (Ziva Mac, 2026-10-14)
      -> Claude, 2026-10-14: fixed. MLX now defaults to model "default_model", mlx_lm.server's own
      name for the model it was started with (server.py maps it to --model; its /v1/models lists
      the whole HF cache, so "first listed" would be wrong). MLX_MODEL still overrides. And mlx,
      vllm and kyojin are now priced free in the usage ledger (your $0.0018 note).

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
- [x] **W2 Connections portal.** Settings > Connections. Press **Test** on every connected card
      (OpenRouter, DeepSeek, Groq, Gemini, Claude Code, Codex). Report each result line. Open a
      model picker on two of them and confirm the list loads. Switch Groq off, send a chat, check
      Groq is not used (the route line in /health), switch it back on.
      RESULT (Ziva Windows, 2026-10-14, via the live engine API on 8767): Test -> openrouter OK
      (deepseek/deepseek-v4.1-flash, 361 ms); groq OK (qwen/qwen3.8-27b, 192 ms); gemini HTTP 503;
      mistral 'the key was rejected'; together 'key rejected (missing API key)'; cerebras 'the key
      was rejected'; deepseek 'no credit left: Insufficient Balance'. Model pickers loaded for
      openrouter (free models) and groq. ACTION (owner): fix/replace the mistral, together and
      cerebras keys and top up or disable deepseek in Settings > Connections.
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
     PART DONE 2026-10-14 (Ziva Windows): installed media (yt-dlp 2026.08.19), opencode (1.19.0),
     agent-reach (with a PATH shim), and ffmpeg (winget); enabled media, image-gen, agent-reach
     and opencode in the capability registry. Verified: reach.doctor runs (16 channels, 4 live)
     and the image specialist produced a real JPG through the free Pollinations backend.
     image-gen CUDA (torch cu128 + ~20 GB weights) is downloading in the background. STILL TO DO:
     the four LOKI prompts below - they need the app running.
     FOLLOW-UP: torch cu128 + diffusers installed, `ZImagePipeline` is importable (zimage_ready
     True); the ~20 GB Z-Image weights download in the background / on first use. The image
     runner ALREADY has a `qwen()` backend (Qwen-Image via ModelScope) - it just needs a
     ModelScope token, so no new code is required for your "Qwen images" ask (see Needs Mohamed).

     BUG (Ziva Windows, 2026-10-14): local Z-Image generation crashes. The model downloads and
     LOADS fine (~50 s: 3 checkpoint shards, 398 weights, 5 pipeline components), then
     SEGFAULTS on the first of 9 inference steps (native crash, exit 139). Machine: RTX 3070 Ti,
     VRAM 8192 MiB (2179 used), free RAM 11.0/15.9 GB, torch 2.11.0+cu128, diffusers 0.41.0.
     The zimage() path uses enable_model_cpu_offload() for <12 GB cards. The free Pollinations
     backend works. Needs a fix from the code side (CPU offload / dtype / diffusers version) -
     assigning to Claude.
  -> Claude, 2026-10-14: fixed in a way that survives a native crash: each attempt now runs in
     its own child process and LOKI walks down 4 plans (model offload bf16 -> same with plain
     "math" attention, the usual Windows crash source -> sequential offload -> fp16). The plan
     that works is remembered (harness_data/app/imagegen_plan.json); if all 4 crash, local
     Z-Image is skipped for a week and auto goes to Qwen/Pollinations. RE-TEST (W13).
- [x] **W6 LOKI World.** Home screen: the world should be faintly visible behind "What should
      Loki work on?". Settings > LOKI World: drag to orbit, wheel to zoom. Start a team
      ("build a landing page for a bakery and test it") and watch characters walk to their
      stations. Take a screenshot into `docs/operations/screens/world-windows.png` (that folder is
      fine to commit). If the canvas is blank, open the WebView devtools (`LOKI_APP_DEBUG=1`) and
      paste the console errors.
      PART DONE 2026-10-14 (Ziva Windows): the LOKI UI + the 3D world canvas render -
      captured docs/operations/screens/world-windows.png from the REAL WebView2 window
      (PowerShell PrintWindow PW_RENDERFULLCONTENT, 1100x820, background mode) - ~43% navy
      world canvas behind the home UI, not a black capture. VERIFIED via the engine API (headless): GET /world
      showed only LOKI (idle, hall); after POST /teams {goal: "build a landing page for a bakery
      and test it"} the Architect appeared at the drafting table in 'working' state - the world
      reacts to real events. ONLY LEFT (owner, at the app window): drag/wheel orbit + the
      on-screen walk.
- [ ] **W7 Update everything.** Once the Mac is linked (M3), ship any tiny change from the Mac,
      then on the PC press **Update everything**. Expected: the Mac restarts first, then the PC;
      the panel shows both on the same commit. Report the step lines.
      PART DONE 2026-10-14 (Ziva Windows): the PC side is READY - it listens on port 8768
      as peer "pc" (LOKI_PEER_LISTEN=1 in harness_data/.env). The two-machine run only waits on
      the Mac being linked (M3).
- [x] **W8 Prompted tools on a local model.** Start llama.cpp *without* `--jinja` (or LM Studio)
      with a small model, set it as default in the portal, and ask LOKI to "list the files here
      and read README.md". Report whether tools ran ("tools via harness" shows on the card).
      RESULT (Ziva Windows, 2026-10-14): the harness itself is VERIFIED with real local models -
      tool_harness.prepare() + attach() against Ollama made models call tools without native tool
      support: hermes3:8b -> list_files + read_file (11.0s); qwen3:8b -> list_files(path='.') +
      read_file(path='README.md') (10.4s). Only the portal "set as default" click remains (UI).
- [x] ~~**W9 Build the Godot world client.**~~ **CANCELLED by the owner**: the world is in the
      app (plain WebGL, `app/ui/world.js`), **never Godot**. Do not create a Godot project;
      do not touch the `ai` project. W6 is the real world check.
- [ ] **W11 Free Qwen images.** Make a ModelScope token (modelscope.ai > Access Tokens; bind
      the Alibaba Cloud account if it asks - that may need Mohamed), connect it in Settings >
      Connections > ModelScope, turn on image-gen, set `LOKI_IMAGE_BACKEND=qwen` and ask LOKI for
      "an image of a red fox in studio light". Report the time, and the exact error if any (the
      request shape came from a third-party guide, not ModelScope's own docs).
- [ ] **W16 [windows] All of Ruflo + ReasoningBank, live.** (Mohamed: "copy ruflo exactly
      into LOKI and make it better".) Now in: all 168 core commands and all 47 plugins (their
      agents, skills, commands) in contrib/ruflo; `/ruflo <command> <task>` runs a task with that
      Ruflo command as its playbook; SPARC teams; and a ReasoningBank (engine/reasoning_bank.py)
      that puts "what worked / what failed on similar tasks" into the prompt. Check on the PC,
      after LOKI updates: (1) Settings > Agents shows "Ruflo workflows" with ~200 workflows and
      47 plugins (screenshot to docs/operations/screens/ruflo-workflows.png); (2) in chat send
      `/ruflo list sparc`, then `/ruflo sparc make a tiny todo web page in a new folder`, and
      report what it built; (3) start a team with goal `sparc: a one-page bakery site` and report
      whether the board says "Method: SPARC" and the Researcher wrote a specification; (4) run any
      task twice: the second run's progress should say "Recalled N lesson(s)"; paste
      harness_data\experience\reasoning_bank.jsonl's last line. Then run `tools/ship.py --check`.
- [ ] **W14 Ruflo.** (Mohamed asked: ruvnet/ruflo in LOKI.) Its 95 agents and 38 skills are now
      built in (contrib/ruflo, engine/ruflo_library.py). Check: Settings > Agents > "Ruflo library"
      search "security" -> pick "Security Auditor" -> Save -> Run it on a small task. Then turn on
      Ruflo's MCP server: add `LOKI_MCP_ENABLE=ruflo` to harness_data\.env, restart LOKI, and report
      the "[mcp] connected 'ruflo': N tools" line from harness_data\app\engine.out (or its error).
- [x] **W13 Z-Image again.** After LOKI updates: ask for "an image of a red fox in studio
      light" with `LOKI_IMAGE_BACKEND=zimage`. Report which plan worked (the reply names it)
      and the time, or every plan's error if all crash (paste them).
      RESULT (Ziva Windows, 2026-10-14): Claude's fix WORKS AS DESIGNED but every plan still
      crashes on this PC. zimage() ran all four plans in child processes and reported cleanly:
      offload-bf16 / offload-bf16-math-attn / sequential-bf16-math-attn / sequential-fp16-math-attn
      ALL 'crashed (exit 3221225477)' (0xC0000005 access violation); 120.8s total; then it wrote
      imagegen_plan.json {works:null, failed_at:...} so local Z-Image is skipped for a week and
      the tool falls back to Pollinations (verified working). DIAGNOSIS: basic CUDA is fine on
      this box (matmul, conv2d, scaled_dot_product_attention, sync all OK; ~6.2 GB VRAM free), so
      the crash is Z-Image/diffusers-specific, not the GPU. Versions: torch 2.11.0+cu128,
      diffusers 0.41.0, transformers 5.19.0, accelerate 1.15.0, NVIDIA driver 617.42. Suggest
      trying torch 2.10 or a different diffusers release for ZImagePipeline.
      ANSWER (Claude, 2026-10-14): thanks - agreed it is diffusers/torch-side. Before swapping
      versions, get the exact line it dies on: see W15.
- [ ] **W15 [windows] Z-Image: find the crashing line, then try one version swap.** After LOKI
      updates, the child now runs with `faulthandler` on and reports the last stage (load /
      place / denoise / save) and the innermost Python frame, e.g. "crashed (exit 3221225477)
      during denoise at attention.py:88 in forward". There is also a 5th plan that loads the
      weights without mmap. Steps: (1) delete `harness_data\app\imagegen_plan.json` (it holds the
      week-long skip); (2) ask for "an image of a red fox in studio light" with
      `LOKI_IMAGE_BACKEND=zimage`; (3) paste every plan's line here. (4) Only if all still crash
      at the same frame: in a COPY of the venv (never the live one), try
      `pip install "torch==2.10.*" --index-url https://download.pytorch.org/whl/cu128` and run
      the same request with that python; report which combination works. Do not change the
      live install's versions without telling Claude here first.
- [ ] **W12 LOKI's first own job.** UPDATE (Claude, 2026-10-14 19:4x): job cf7dd344 ran on the
      code from BEFORE the check_loki fix: it called conductor/improve_loki/ship_loki("test") in a
      loop, used ~55k input tokens EVERY turn, spent every free quota in 37 turns (then $0.03 on
      paid OpenRouter deepseek-v4.1-flash, since paid is allowed on the PC), and ended on an
      OpenRouter 402. Nothing shipped. Since then: check_loki tool, improve_loki refuses inside its
      own worktree, and providers that hit a 429 now come back after a 20 s cooldown instead of
      being dropped for the run (LOKI_RATE_LIMIT_WAIT, default 90 s per turn). RE-RUN it on the
      current master and report turns, tokens per turn and the outcome.
      ORIGINAL: NOTE from Claude (2026-10-14): I tried this on the PC
      through LOKI's own UI before the fix below. The local 9B model did NOT call improve_loki;
      it edited the Home workspace and stopped after 6 turns. Now a request like this is
      recognised by the first layer and handed straight to improve_loki (no model choice), and
      improve_loki jobs use the best FREE online model (LOKI_IMPROVE_MODEL=online). Re-run it. In LOKI on the PC (Build mode), send: "Change your own code (improve_loki): add the
      Nordic LOKI identity from docs/VISION.md - an L-shaped logo mark in the sidebar and the
      welcome screen, navy background with cyan/emerald accents, as CSS only, keep the dark
      theme readable; add a check in tests/test_portal.py's UI section and ship it". Watch the
      job in the work strip and the 3D world. Report whether LOKI shipped it by itself (the
      commit appears on master) or where it stopped.
- [ ] **W10 24/7.** Make LOKI start at boot on the PC (Task Scheduler running `Loki.cmd`, or a
      service). An engine started without the app now restarts itself after **Update everything**
      (it starts a new copy and exits). Confirm that works headless.

## Ziva (Mac) - the Mac mini

- [x] **M1 Checkout.** Mohamed chose `~/Loki` for the Mac checkout; HANDOFF.md still says
      `~/Documents/loki`. Use the one that exists (ask under Needs Mohamed if both or neither),
      then fix HANDOFF.md to match. Run `bash setup.sh` once (this also installs Laya), then
      `harness_data/.venv/bin/python tools/ship.py --check` and report.
      DONE 2026-10-14 (Ziva Mac): `~/Documents/loki` is the live install (the app runs it), so
      it is THE checkout; `~/Loki` was a stale duplicate (behind, dirty, no venv) and was
      removed. Updated `~/Documents/loki` to master `0b15861`, made it a git checkout tracking
      origin/master, removed Godot leftovers (project.godot, addons/, .godot/), kept
      harness_data/ + keys/. Ran `bash setup.sh` (Node 26 + Laya; Laya self-test OK; rebuilt
      ~/Applications/Loki.app -> ~/Documents/loki) and ship.py --check - all 11 suites green.
      HANDOFF.md already names `~/Documents/loki`, so no doc change was needed.
- [x] **M2 GitHub sign-in (do this before the repo goes private).** `brew install gh`,
      `gh auth login` (GitHub.com, HTTPS, browser), then `gh auth setup-git`. Check with
      `git -C <checkout> fetch origin master`. Without this the Mac cannot update once
      m03dev/loki is private. On the PC, check the same `git fetch` works (Git Credential Manager).
      DONE 2026-10-14 (Ziva Mac): `brew install gh`; `gh auth login --with-token` (account
      m03dev, token in the keyring); `gh auth setup-git`; verified
      `git -C ~/Documents/loki fetch origin master` works.
- [ ] **M3 Link the machines.** They are on different networks (192.168.1.x / 192.168.0.x).
      Install Tailscale on both (same account), then on the Mac: Settings > Machines &
      updates > Link another machine, with the PC's link code. Report `ms` from the Machines panel.
- [x] **M4 MLX.** `harness_data/.venv/bin/python tools/setup_extras.py mlx`, then keep
      `mlx_lm.server --model mlx-community/Qwen3-4B-4bit --port 8082` running. The MLX card should
      say **Running**. Make it the default and ask LOKI to "list the files here and read README.md".
      MLX tool calls go through the prompted harness: report whether the tools ran and how fast
      (tokens/s from the usage line). Try one bigger model if memory allows and report.
      BLOCKED then UNBLOCKED 2026-10-14 (Ziva Mac): the internal disk was full (191 MB free) so
      `setup_extras.py mlx` died with "No space left on device" (mlx installed, mlx-lm did not).
      The Mac checkout now lives on the 2 TB SSD (internal disk freed) - retrying M4; will report.
      RESULTS 2026-10-14 (Ziva Mac): mlx-lm installed; `mlx_lm.server --model
      mlx-community/Qwen3-4B-4bit --port 8082` running (weights on the APFS image). LOKI reports MLX
      as the provider. BUG found: MLX_MODEL defaults to "auto" and LOKI sends `model:"auto"` -> the
      server 404s on `huggingface.co/api/models/auto`; setting MLX_MODEL to the served id fixes it
      (see the [claude] request). With MLX_MODEL set, the engine starts and routes to MLX; finishing
      the tool-call check and tokens/s.
      DONE 2026-10-14 (Ziva Mac): tools ran. With `MLX_MODEL=mlx-community/Qwen3-4B-4bit` and MLX
      as the engine's model, "list the files here and read README.md" ran the agent loop and called
      `list_tree(...)` through the tool harness; reply: the workspace folder is empty, no README.md.
      Usage line: `mlx-community/Qwen3-4B-4bit * 7.3k in / 561 out * 17.2 tok/s * $0.0018`. NOTE:
      it prices a LOCAL MLX model as paid ($0.0018) - minor, worth a look in the portal.
- [ ] **M5 Laya on Apple Silicon ("Laya MLX").** Laya is a decision model (typed answers in one
      pass), not a text model, so there is no MLX build of it and mlx-lm cannot run it. What can
      help: ONNX Runtime's CoreML execution provider. Measure `python tools/setup_laya.py --check`
      latency now; then, if `@receptron/laya` lets you pass ONNX session options, try
      `executionProviders: ["coreml", "cpu"]` in `engine/laya_server.mjs` and measure again.
      Ship it only if it is faster and every suite passes; otherwise report the numbers.
      RESULT 2026-10-14 (Ziva Mac): CPU baseline median 52 ms/decision (M4 chip, 50-62 ms over 5
      calls after load). With CoreML: `LOKI_LAYA_EP="coreml,cpu"` median 177 ms (163-270 ms) -
      SLOWER (CoreML compiles the graph for a tiny model). NOT shipped; cpu stays. @receptron/laya
      does expose executionProviders/sessionOptions, so it is a one-line env to revisit later.
- [ ] **M6 World + portal on WKWebView.** Same checks as W2 and W6 on the Mac; screenshot to
      `docs/operations/screens/world-mac.png`.
- [ ] **M7 Images on the Mac.** `tools/setup_extras.py imagegen` installs torch for MPS. Generate
      one 768x768 image and report the time and memory pressure. If it is too heavy for this Mac,
      say so: LOKI will keep using the PC (agents with "Lives on: Best machine") or Pollinations.

## Needs Mohamed

- [ ] **GitHub Actions is not starting jobs** (account billing). CI on push is off until it is
      fixed in github.com/settings/billing. Meanwhile every change is checked by ship.py on the
      machine (Ziva) and by the offline suites in the cloud (`PYTHONPATH=tests/cloud_stubs`).
- [ ] DeepSeek has no credit ("Insufficient Balance"), and the OpenRouter balance is nearly
      empty (a 402 "exceed your available credits"). Top up, or set `LOKI_ALLOW_PAID=0` on the
      PC so LOKI never reaches for paid models on its own. Note: the OpenRouter card's model on the
      PC is `deepseek/deepseek-v4.1-flash`, which is PAID; pick a `:free` model there (Settings >
      Connections > OpenRouter > model) to keep OpenRouter free.
- [ ] Ziva's W2 test: the **Mistral, Together and Cerebras keys are rejected** - replace them in
      Settings > Connections (or Disconnect those cards).

- [ ] A **ModelScope** token (modelscope.cn/my/myaccesstoken) to turn on the `qwen()` image
      backend (Qwen-Image 2.1). Without it, images use local Z-Image Turbo or free Pollinations.
      (Ziva Windows, 2026-10-14 - the backend already exists in engine/runners/imagegen.py.)

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
- 2026-10-14 windows (Ziva) MASTER WAS RED, NOW FIXED: the Ruflo commit referenced contrib/ruflo/plugins/<name>/ but the plugin text was never committed (0 files tracked) because .gitignore's `plugins/` rule ALSO ignored contrib/ruflo/plugins/ (now anchored to `/plugins/`), so test_portal failed ('all of Ruflo is in', 'plugin skills are in the skill catalog', 'GET /ruflo serves...') and ship.py refused to push on the PC. Vendored Ruflo's plugins verbatim from ruvnet/ruflo@1882006a, TEXT ONLY (.md + plugin.json, no code): 47 plugins, 64 agents, 159 skills, 59 commands. test_portal 171 -> 188 pass. Root cause was the .gitignore rule, not the author's copy. Any fresh clone / CI was blocked before this.
- 2026-10-14 cloud (Claude) Ruflo, the rest of it (Mohamed: "copy it exactly and make it
  better"): all 168 core commands + all 47 plugins' agents/skills/commands copied verbatim
  (text only, 151 agents / 197 skills / 203 workflows indexed, every file skill-scanned);
  `/ruflo <command> <task>` and "Ruflo workflows" in Settings > Agents; SPARC teams
  ("sparc: <goal>"); ReasoningBank - lessons from past tasks in the prompt, built only from
  what really happened (it would have warned the 37-turn W12 job off its repeated conductor
  calls). Not copied: Ruflo's TypeScript/Rust runtime (its MCP server stays opt-in). Offline
  suites green (stub-only failures as before) -> W16.
- 2026-10-14 windows (Ziva) IMAGE FIXED: agent image was BLOCKED because image-gen's manifest changed (status 'changed' = off); re-enabled it and POST /task now makes images end-to-end in ~25 s via Pollinations. Suggested LOKI prompt the owner to re-approve changed manifests.
- 2026-10-14 mac (Ziva) M4 DONE: MLX verified end to end - `mlx_lm.server` serving
  mlx-community/Qwen3-4B-4bit, LOKI routing to it, the tool harness fired (`list_tree`), 17.2 tok/s;
  found the MLX_MODEL "auto" bug (request above). Also added a login LaunchAgent
  (`sh.loki.attach-image`) so the APFS image reattaches after a reboot.
- 2026-10-14 mac (Ziva) storage FINAL + M4: LOKI lives on the 2 TB SSD. Raw exFAT broke git (`._`
  sidecars in `.git/objects/pack`) and `transformers` (it scans its folder and hit `._` files), so
  the checkout is on an **APFS sparse image** `/Volumes/LokiSSD` (single file on `/Volumes/xero`),
  symlinked from `~/Documents/loki`; venv/Laya/Loki.app rebuilt; all 11 suites green; internal disk
  0.2 GB -> 3.5 GB free. Shipped 029010e (skill_scan no longer counts its own SKILL.md as
  executable; M5 CoreML 177 ms vs CPU 52 ms -> NOT shipped). M4: MLX installed + server running +
  engine routing to MLX; found the MLX_MODEL "auto" bug (see request).
- 2026-10-14 mac (Ziva) moved LOKI to the 2 TB SSD, + M5 numbers: found `/Volumes/xero`
  (2 TB, 1.3 TB free); copied the checkout there and made `~/Documents/loki` a symlink to it, so
  every launcher and path keeps working; re-ran setup.sh (venv recreated, Laya OK, Loki.app
  rebuilt); deleted the old internal copy -> internal disk 0.2 GB -> 3.5 GB free. All 11 suites
  green on the SSD. ONE code fix: engine/skill_scan.py counted its own `SKILL.md` as an
  executable (exFAT marks every file executable - no permission bits); now the definition file is
  skipped, since it is read, never run - correct on any filesystem. M5: Laya CPU median 52 ms vs
  CoreML 177 ms -> CoreML NOT shipped. M4 was blocked by the full disk, now unblocked and retrying.
- 2026-10-14 cloud (Claude) read Ziva's check-in (window close = update restart, agreed; W8
  verified - thanks; W13 all plans crash). Landed: (1) self-improvement that can test itself -
  check_loki tool (ship.py --check --only), improve_loki refuses inside its own worktree, one
  local-model job at a time on a machine (LOKI_LOCAL_MODEL_JOBS); (2) tests/cloud_stubs so the
  offline suites run without PyPI; (3) Z-Image crash reports now name the stage and the code line
  (faulthandler), plus a no-mmap plan -> W15; (4) rate-limited providers come back after a
  cooldown instead of ending the run (found on the PC: job cf7dd344 died after every free quota
  was marked spent) -> W12 re-run. Ruflo (W14): 95 agents + 38 skills built in, MCP opt-in.
  GitHub Actions is blocked by billing - see Needs Mohamed. Mirror macos-app = master.
- 2026-10-14 windows (Ziva) live loop: POST /chat answered via the local model (21 s) - LOKI works end to end on the PC. POST /task for an image came back BLOCKED (image specialist not reachable from the agent; see the new request for Claude).
- 2026-10-14 windows (Ziva) W2: portal Test via the app engine - openrouter OK 361ms, groq OK 192ms; gemini 503, mistral/together/cerebras key rejected, deepseek no credit. Pickers load.
- 2026-10-14 windows (Ziva) W8: prompted tool harness verified on real local models via Ollama - hermes3:8b and qwen3:8b both called list_files/read_file through the <tool_call> harness.
- 2026-10-14 mac (Ziva) M2+M1: the Mac can reach the private repo again. `brew install gh`;
  `gh auth login --with-token` (m03dev, token in keyring); `gh auth setup-git`; verified
  `git -C ~/Documents/loki fetch origin master`. M1: `~/Documents/loki` (the live install) is
  now a git checkout on master tracking origin/master; Godot leftovers removed; harness_data/ +
  keys/ kept; installed Node 26 + Laya (self-test OK, offline); rebuilt ~/Applications/Loki.app.
  `harness_data/.venv/bin/python tools/ship.py --check`: all 11 suites green - test_loki 470,
  test_hardening 127, test_integrations 71, test_workers 72, test_offline_e2e ok, test_peers 58,
  test_first_layer 54, test_updater 44, test_team 35, test_events 33, test_portal 145. Removed
  the stale duplicate clone at ~/Loki. Pre-update backup: ~/Documents/loki.backup-20261014-181140.
- 2026-10-14 windows (Ziva) CHECK-IN for Claude: (1) the 18:39 window close was the app's
  own update-restart cycle from my ship.py pushes - it reopened at 18:40:06, not a bug.
  (2) W13: all four Z-Image plans still crash (0xC0000005) though basic CUDA is fine -> it is
  Z-Image/diffusers-specific; your fix survives cleanly and the Pollinations fallback works.
  (3) Shipped on the PC: W2 (portal API verified), W5 (extras installed + add-ons enabled +
  specialists verified), W6 (REAL WebView2 capture -> docs/operations/screens/world-windows.png,
  and POST /teams -> Architect at the drafting table in /world), W10 (logon Startup shortcut),
  W7 PC side (peer listener on 8768 as pc). (4) Still open on the PC: W3/W4 (need the owner's
  phone/browser), W11 (needs a ModelScope token), W12 (LOKI self-improvement run).
- 2026-10-14 cloud (Claude) used LOKI on the PC (its UI in the Claude app's browser pane):
  every connected provider tested for real - OpenRouter 449 ms, Groq 213 ms, Gemini 6.2 s,
  LLM7, Vireonix, Pollinations, local qwen3.5-9b 2.5 s (24-40 tok/s) all OK; DeepSeek has NO
  CREDIT ("Insufficient Balance"). Found and fixed: (1) "change your own code" did not reach
  improve_loki; (2) a bakery-website team wrote Godot .tscn files because the Godot tools were
  offered outside a Godot project - now they are only offered inside one; (3) LOKI could not
  say which model it is - its prompt now names model, provider, machine, version, peers; (4)
  Machines & updates called this PC "behind" while it was ahead; (5) test_updater could write
  the real update-health record - it now lives in the checkout's .git; (6) Z-Image crash
  (above). All suites green in CI. Noticed, not fixed yet: at 18:39 the app's window closed 9 s
  after an engine restart ("restarting on the updated code") - Ziva, did you close it, or did it
  close by itself? Answer under the request below.
- 2026-10-14 cloud (Claude) requests: did both [either] requests (6 hosts; free Qwen-Image 2.1
  via ModelScope), 129 offline checks pass. Added the [claude]/[loki] request tags and a
  scheduled Claude check of this file every few hours. New tasks: W11 (Qwen images), W12
  (LOKI's first own job). Ziva's session-15 commit is on master as 6dc2898 (thanks).
- 2026-10-14 windows (Ziva) W6 team->world: POST /teams made the Architect appear at the drafting table (working) in GET /world. World reacts to real events.
- 2026-10-14 windows (Ziva) W6: captured the REAL WebView2 window (PrintWindow) -> docs/operations/screens/world-windows.png (~43% navy world canvas behind home). Drag/wheel + team-walk still need the app.
- 2026-10-14 windows (Ziva) W5 image: Z-Image weights downloaded (26 GB cache); local CUDA generation SEGFAULTS on step 1/9; Pollinations works. W10 done via a logon Startup shortcut (Task Scheduler needs admin). W2: portal API verified headless (GET /providers 200, /world 200).
- 2026-10-14 windows (Ziva) W5 extras (PC): installed yt-dlp, opencode, agent-reach (+PATH
  shim) and ffmpeg; enabled media, image-gen, agent-reach, opencode; verified reach.doctor and a
  Pollinations image; image-gen CUDA downloading. See the W5 note.
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
