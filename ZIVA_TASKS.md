# ZIVA_TASKS.md - work for Ziva (Mac) and Ziva (Windows)

Ziva: read this file at the start of every session, after AGENTS.md, ZIVA.md and HANDOFF.md. It is how Claude,
LOKI's own agents and the owner (Mohamed) ask you for things that need a real machine: a GPU, a signed-in
browser, a phone on the Wi-Fi, a Godot editor, a Mac. Everything up to 2026-10-19 (every W/M task with its full
steps, every answer and report) is kept verbatim in **docs/operations/archive/ZIVA_TASKS_until_2026-10-19.md** -
the W/M numbers below refer to it when a request says "steps: W35".

## How this file works

- **Requests** is the inbox for all of us. Add a line:
  `- [ ] [mac|windows|either|claude|loki] what is needed - why - who asked (date)`.
  `[mac]`/`[windows]`/`[either]` = Ziva on that machine. `[claude]` = Claude in the cloud (a scheduled Claude
  session reads this file every few hours, does the code/research items that need no machine, ships them and
  answers here). `[loki]` = a job for LOKI's own agents (on the PC, paste it into LOKI; the idle autopilot also
  picks these up).
- Answer on the line under the request (`  -> who, date: answer`), so the thread stays in one place.
- Take the oldest open request for your machine first (the "Do first" block overrides that).
- When you finish one: tick it (`- [x]`), add a short entry at the TOP of **Reports** (date, machine, task,
  what you did, what you saw, what failed - paste exact errors), and ship.
- **Publish only with tools/ship.py**, never anything else, never `push --force`:
  Windows `harness_data\.venv\Scripts\python.exe tools\ship.py -m "ziva(windows): <task> <result>"`,
  Mac `harness_data/.venv/bin/python tools/ship.py -m "ziva(mac): <task> <result>"`.
- **Never commit anything from `harness_data/`** (keys, tokens, memory, logs, models). Never paste a key here.
- If a task needs Mohamed (an account, a password, a phone, a purchase, a decision, anything irreversible), do not
  guess: put the exact question under **Needs Mohamed** and go on with the next task.
- **Tests: at most 1 minute per run** (the owner's rule; ship.py's default budget is 60 s, `--full` only overnight).
  If tests fail after your change, fix it or revert it before shipping.
- **No visible terminal windows on the owner's screen.** Run commands in your own tool or hidden (Windows
  `Start-Process -WindowStyle Hidden ...`, never `start "TITLE" cmd`; Mac never `open -a Terminal`); close any you opened.
- Never open game/loki-world in Godot_v4.8-beta1_mono / Godot_mono 4.8 (it rewrites project.godot); LOKI's Godot
  tab opens it in LOKI's own 4.7.2.

## Requests

### Do first (Claude, 2026-10-19 04:10)
Seen on the PC at 04:04 (screenshot through computer use, nothing changed): the LOKI window says "LOKI's engine is
not answering" (attempt 6), it runs v0.16 patch 324 with "update waiting", and the Godot tab says "No Godot editor
is linked".
- [ ] [windows] 1. Restart LOKI on the PC so it takes the waiting update (Spaces is now a full-window tab: 6 tabs in
      the title bar). If the engine still does not answer, paste the last 40 lines of harness_data/app/loki_bridge.log here.
- [ ] [windows] 2. Godot tab > Open LOKI World in Godot, so you and the other agents are linked again (docs/LIVE_GODOT.md).
- [ ] [windows] 3. Only then: the Spaces campfires in LOKI World (Spaces below). Keep Forge Maya work in its own commits.

### Spaces (Claude, 2026-10-19)
- [ ] [either] game/loki-world: poll `GET /spaces/world` (bearer, like /world/presence) and draw each lobby / voice
      room as a place on the island (a campfire + name plate + the people in it, colour = space_color). Walking into
      it: JavaScriptBridge -> `window.parent.postMessage({lokiSpaces: "join", space, room}, location.origin)` - the
      window (app/ui/spaces.js) joins its voice. docs/SPACES.md "LOKI World".
- [ ] [mac] [windows] Spaces tab (Ctrl/Cmd+6) > + > Make it; copy the invite to the other machine > Join; chat; open a
      lobby; join voice from both and talk. Report whether the mic works inside the LOKI window (WKWebView /
      WebView2), whether Windows / macOS asked to allow incoming connections, and (Mac) whether Loki.app was rebuilt
      with tools/macos/make_loki_app.sh (its Info.plist carries NSMicrophoneUsageDescription). (Claude, 2026-10-19)

### Forge (Claude, 2026-10-19; Ziva Mac owns the Maya roadmap, docs/FORGE_MAYA.md)
- [ ] [either] With a real GPU on the Mac AND the PC: Forge > Model, cube, 1/2/3 select, drag a box, G/R/S, W handle,
      Alt+click loop; Forge > Creature: every starter builds, Walk plays.
- [ ] [either] Poly: loop cut (Ctrl+R) and bevel (Ctrl+B) using P.topology / P.edgeRing in app/ui/forge_poly.js (the
      old bevel port left holes where 3 selected edges meet).
- [ ] [either] Poly: extrude loose vertices / edges (Blender E in vert/edge mode), merge (M), knife.
- [ ] [either] Poly: speed up commit after a move on 50k+ face meshes (view.showPoly rebuild in forge.js; ~0.7 s now).
- [ ] [either] Creature: a tail-curl / stance slider, and bipeds (a second skeleton base) - add to SHAPE/PRESETS in
      engine/anycreature.py, probe extremes so they stand.
- [ ] [mac] FORGE_MAYA.md T6c: a sculpt stroke in the construction history (recorded vertex deltas, or the sculpt
      engine callable on a snapshot) - the design is in the doc.
- [ ] [windows] Forge with TripoSR on the RTX 3070 Ti: `harness_data\.venv\Scripts\python.exe tools\setup_forge3d.py`,
      then in Forge add a picture and make 3D; report the backend used, the time, and any error (the setup swaps
      torchmcubes for PyMCubes, untested). (claude, 2026-10-17)

### LOKI World and the live Godot link
- [ ] [mac] **LOKI World on the Mac (Claude, 2026-10-18; 6469d85, 4c951ac, 0c9965a, 9b160a0).** The PC verified all
      of this in W50/W51; the Mac has not. (1) `git status`: if game/loki-world/project.godot or icon.svg.import show
      as changed, `git checkout` them; delete the `app/ui/world_godot/*.before-update` leftovers. (2) Godot tab > Open
      in Godot: LOKI downloads its own macOS Godot 4.7.2 once (harness_data/addons/godot-export) and opens LOKI World
      with the island in the 3D view and the LOKI Studio dock - paste the "LOKI Studio plugin 1.2 ready" Output line
      and any error; the tab's Live link must show "Godot 4.7.2 - LOKI World". (3) In LOKI's chat: "use godot_editor: in
      LOKI World add a OmniLight3D named AgentLamp above the fountain and save" - is AgentLamp in the scene dock (Ctrl+Z
      removes it) and did the Godot tab list the agent? (4) Press Play (F5) in Godot, ask for another change while it
      runs - does it appear live (Debug > Synchronize Scene Changes)? (5) World tab (Cmd+4): the Godot game, "Connected
      to LOKI", still running after 12 s; report fps. (6) Rebuild the World tab: time + status line. (7) Forge: save a
      model, walk to the three pink pedestals in front of the creations hall - is it there, turning? (8) Godot tab >
      Add plugin by Asset Library number (e.g. Phantom Camera): status line + game/loki-world/plugins.json.
- [ ] [windows] Godot tab > Add plugin by Asset Library number (a 4.x plugin, e.g. Phantom Camera) over the real
      network: report the status line and game/loki-world/plugins.json (never tried anywhere). (Claude, 2026-10-18)

### The window (webviews)
- [ ] [windows] **Cross-origin isolation (ecf9b40): run `tools/ship.py --check`, then look in the window.** 04def98
      made the window COEP require-corp; Claude made every bridge answer send COEP require-corp + CORP cross-origin and
      Studio's server send both. In WebView2: a mermaid diagram in chat, Preview on an HTML answer, an App, the Studio
      tab (Ctrl+2) - all must show. Paste any "blocked by Cross-Origin-Embedder-Policy" line from the window's console /
      harness_data/app/loki_bridge.log. (Claude, 2026-10-18)
- [ ] [mac] The same check in WKWebView (Safari's COEP rules are stricter): Mermaid diagram, Preview, an App, the Studio
      tab (Cmd+2), and is `crossOriginIsolated` still true in the Godot tab? Also report whether the frameless title
      bar (traffic lights, centred tabs, double-click zooms) looks right - not seen on the real Mac since 68b9469. (Claude, 2026-10-18)
- [ ] [either] **Chat quality of life in the real window** (docs/integrations/ZIVA_QOL.md; steps W44 PC / M33 Mac):
      disconnect banner + reconnect, queue + steer, error cards, "Allow for this session", which Ctrl/Cmd shortcuts
      reach LOKI, the "LOKI finished" toast/notification, a 20,000-character paste. (Claude, 2026-10-17)

### Computer use
- [ ] [either] **Computer use: never into LOKI itself + open_app brings the app forward (0d544bf).** Claude changed
      engine/computer_use.py, engine/computer_backends.py (frontmost() returns the pid; new activate() per OS) and
      app/loki_app.py (LOKI_APP_PID). (1) The --check line for test_tools_core; (2) with LOKI's window in front,
      `computer(action=type, text=hi)` answers "DENIED: LOKI's own window is in front" and asks nothing; (3) "open
      TextEdit and type hello" (Mac, after the Accessibility + Screen Recording grants - Needs Mohamed) / "open Notepad
      and type hello" (PC): open_app says "(it is in front)" and hello lands in the app. Paste the exact open_app answer
      if it says "NOT in front". (Claude, 2026-10-18)
- [ ] [windows] Tools, connectors, computer use on the PC (steps: W34): health map rows that say Broken or Failing,
      GitHub connector (issues list + the create-issue approval, say No), computer use with Notepad, the kill switch.
      The Mac did all of this on 2026-10-18 (Reports). (Claude, 2026-10-17)

### Installers and packaging
- [ ] [either] **One-click installers from GitHub Actions on a clean account** (merges the session 29 and 30 asks;
      steps: W45 PC, M34 Mac; older manual build steps W38 / M29). Actions > Installers > Run workflow (no tag); install
      the Windows setup / the macOS .dmg on a NEW standard user with Wi-Fi off. Report: each job's result (first error
      of a failed step), SmartScreen / Gatekeeper dialogs, any console window or Xcode prompt (a bug), seconds to the
      window and the `window shown after` / `engine ready after ... since the double-click` lines from loki_app.log,
      the tour's local model download (did Ollama install with no window?), Send feedback zip contents, uninstall
      keeps the data folder. Delete the test user afterwards. (Claude, 2026-10-17)
- [ ] [windows] New add-ons godogen / wechaty / nanocoder (not run on a real machine yet): (1)
      `harness_data\.venv\Scripts\python.exe tools\setup_extras.py nanocoder`, turn on nanocoder + godogen in Settings >
      Add-ons, ask LOKI "make a godot game: a fox collects berries" - report the folder in ~/LOKI Projects, the agent
      picked and whether the job ran; (2) `tools\setup_extras.py wechaty`, turn on wechaty, check Settings > General
      shows a WeChat QR link (do NOT log in a personal account; report only whether the sidecar starts and any error). (claude, 2026-10-17)

### Models, agents, self-improvement
- [ ] [windows] **Run the task bench with real models (steps: W31)** - the owner's #1 core system; only scripted fakes
      have run it (31/31). `tools\task_bench.py --model local`, then `--model bonsai`, then `--model smart` (hours; leave
      the PC alone). Report the summary table from `harness_data\bench\<date>.md` and, per FAILED task, its "why it
      failed" cell + the last 30 lines of its log; say which look like a loop bug and which like the model; do not fix
      them in the same session. Then: did the nightly `task_bench` duty run (harness_data\autopilot.json)? (Claude, 2026-10-17)
- [ ] [either] **DeepSeek V4.1 Flash as the main driver + Studio (steps: W36 PC / M27 Mac).** The key is in the Mac's
      `~/.loki/keys.env`. `/models doctor` must show "Main driver: deepseek-ai/deepseek-v4.1-flash on nvidia"; one chat
      and one background job (the `[loki-job] ... | model ...` line, time; no <think> text in the reply); three jobs at
      once - any 429 (`findstr /c:"429" harness_data\jobs\*.log` / `grep -l 429 harness_data/jobs/*.log`)?; a small real
      Studio task (diff, tests) - Discard unless Mohamed agreed to ship. This is also the first real check of the
      streamed replies (4c34824). (Claude, 2026-10-17/18)
- [ ] [either] **Models & routing doctor (steps: W32 PC / M23 Mac):** paste `/models doctor` under Reports, Re-check
      vs the Test buttons, `ollama show <loki-* model>` num_ctx >= 8192, one background job's model line; Mac: MLX
      Bonsai 2 (`python -m mlx_vlm.server --model prism-ml/Ternary-Bonsai-2-9B-mlx-2bit --port 8082`). (Claude, 2026-10-17)
- [ ] [windows] **LOKI fixes its own issues - watch, do NOT fix them yourself (W41).** E13 is done (2ddc73d); next are
      E15 ground texture, E14 unique island per machine, E12 loading screen (docs/EVOLVE.md). Settings > Lab: evolve On,
      "Start the next step now" once; after each attempt report the step, shipped or not, the job's last 30 log lines
      and the time; start the next only after the previous ended. Only unblock it (a missing package, a stuck job).
- [ ] [windows] Lab on the PC (steps: W28): Jobs + Speed watch cards, "Run the self-test now" (3 jobs - report the %
      and failed logs), "Retry on a stronger model", "make yourself a tool that counts the words in a text, with a test"
      (make_tool asks first), "Review now". [mac] the Lab cards in WKWebView with "Window first paint" / "Window ready"
      numbers (M20). (Claude, 2026-10-17)

### Memory, documents, apps, automations, research tools (real-window and two-machine checks)
- [ ] [either] **One memory on both machines (steps: W33 PC + M24 Mac, at the same time).** test_memory_core2's two
      eval lines; teach "Remember that the PC's backup drive is called ORCA-7." on the PC, ask on the Mac; "Remember
      that the Mac's favourite test project is Pebble." the other way; Undo on one -> gone on both and
      `findstr ORCA-7 harness_data\memory_log.jsonl` finds nothing. (Claude, 2026-10-17)
- [ ] [either] **Documents & data (steps: W39 PC / M30 Mac):** install documents / ocr / data-analysis add-ons, a REAL
      PDF (cites name.pdf#pN), a scanned PDF ("+ocr:rapidocr"), a REAL spreadsheet + data_sql, Word/PowerPoint/
      sign_ready PDF; Mac: does a Finder drag-drop reach the page in WKWebView? (Claude, 2026-10-17)
- [ ] [either] **LOKI Apps (steps: W40 PC / M31 Mac):** apps in the real windows (file dialogs, the sandboxed frame,
      color-mix on macOS) and app sync between the machines (install on one, appears on the other in ~5 min). (Claude, 2026-10-17)
- [ ] [either] **Automations (steps: W35 PC / M26 Mac):** folder watcher (no run on a `.crdownload`), job-failed
      Windows toast / macOS `display notification`, webhook (wrong key -> 404), kill switch, restart mid-run; the
      Telegram morning briefing once the bot is paired (Needs Mohamed); the PC's automation listed on the Mac and never
      fired there. (Claude, 2026-10-17)
- [ ] [either] **Research round 3 in the real window (steps: W37 PC / M28 Mac):** sandboxed iframes (diagram +
      preview), Import file picker, confirm()/prompt() dialogs, clipboard, links open in the browser, rembg timing. (Claude, 2026-10-17)
- [ ] [either] **Creative pipelines (steps: W30 PC / M22 Mac):** PC stable-diffusion.cpp local pictures + a 3 s video;
      Mac `local-image` (mflux, filipstrand/Z-Image-Turbo-mflux-4bit) - memory pressure and swap must stay sane on the
      16 GB M4. (Claude, 2026-10-17)
- [ ] [windows] Ruflo's MCP server (W14): `LOKI_MCP_ENABLE=ruflo` in harness_data\.env, restart, report the
      "[mcp] connected 'ruflo': N tools" line from harness_data\app\engine.out (or its error).
- [ ] [windows] Object tracking (V1): `tools\setup_extras.py vision`, enable vision-track, "track the cars in
      <a short clip>.mp4 max_frames=150"; does tracks\<clip>-tracked.mp4 play and the CSV have rows? (Claude, 2026-10-15)
- [ ] [windows] Extras prompts left from W5 (2026-10-14): "get the transcript of <a YouTube URL>" (media), "use reach
      doctor", the OpenCode Coder template agent on a tiny task.

### Two machines, phone, sign-in
- [ ] [windows] Update everything (W7): ship a tiny change from the Mac, then on the PC press Update everything - the
      Mac restarts first, then the PC; both on the same commit. Report the step lines. (The machines are linked now.)
- [ ] [either] Phone (needs Mohamed's phone on the Wi-Fi): Settings > Machines > Pair a phone - the QR opens LOKI's
      chat page on the phone (home link, then the relay link from mobile data); a paired phone still shows in Settings >
      Machines; "Use my phone" key hand-off (W3) on an unconnected provider; on Windows "Let phones in" asks once
      (UAC) for TCP 8770. (Claude, 2026-10-17/18)
- [ ] [windows] OpenRouter sign-in (W4): with no OpenRouter key, Sign in with OpenRouter - does the browser come back
      to "Connected"?

## Ziva's long run (from Claude, 2026-10-19)

The owner wants you running for hours, linked live, cleaning up and building - not one task and stop. This is the
loop. Both machines run it; each takes its own list below. **Owner's standing rule (2026-10-19): don't remove
anything, only improve.** Never delete a feature, a menu entry, a test check, a file or a doc to make something
pass; move it, keep it behind a setting, or archive it (docs/operations/archive/).

**The loop (repeat until the list is empty, then start again at step 1):**
1. `git pull` (or let LOKI's updater take it), read the newest 3 entries in **Reports** - the other machine's
   Ziva and Claude write there too. Keep your Godot editor's LOKI Studio dock linked (docs/LIVE_GODOT.md) so
   LOKI and its agents see what you change, live.
2. Take the next unticked item for your machine below (or a newer `[mac]`/`[windows]` request above it).
3. Small step, a test for it, `git status` - **ship only the files your task touched** (ship.py does `git add -A`:
   if Godot rewrote project.godot or you have game files lying around, restore or stash them first), then ship.
4. A one-line entry at the top of Reports: time, machine, item, result, numbers, exact errors.
5. About once an hour: run LOKI like a new user for 5 minutes (chat, a background job, Forge, Spaces); anything
   broken becomes a new request line for your machine and goes to the top of your list.

**Ziva (Mac) - Forge, the Maya way.** Maya 2027 is installed on this Mac: open it next to Forge and copy how it
*feels*. Spec: docs/FORGE_MAYA_SPEC.md (read off Maya's own scripts). Roadmap: docs/FORGE_MAYA.md. Suite:
tests/test_forge_maya_ui.py (keep it under a minute, add to it, never take checks out).
- [ ] M-F1 (T7) Twenty minutes in Forge with Maya open beside it, WKWebView, mouse AND trackpad: every hotkey in
      the spec table, Option + the three buttons, the hotbox zones, Space tap over each pane, marking menus flicked
      fast (direction only), Outliner drag / Shift-range / right-click, d pivot edit, Shift+drag duplicate. Report
      every place Forge does something different from Maya, then fix the top 5.
- [ ] M-F2 (T8) Bevel (Ctrl+B) on edges and faces in app/ui/forge_poly.js (GoBuild, GPL-3.0, vendored) as a history
      op, a forge_poly test, then turn on the greyed "Bevel" wedges in forge_maya.js (FORGE_MAYA_CMDS.bevel).
- [ ] M-F3 (T8) Insert Edge Loop and Multi-Cut, same way (P.edgeRing exists).
- [ ] M-F4 (T8) Merge / Merge to Center, Fill Hole, Chamfer Vertex, Poke Face - one ship each.
- [ ] M-F5 (T10) Save .glb writes the whole scene (every visible node, hierarchy, transforms, not the selection
      boxes); a test reads it back with GLTFLoader and counts the nodes.
- [ ] M-F6 (T9) Smooth preview on 1 / 3 (display-only Catmull-Clark of the working mesh).
- [x] M-F7 (T11) Sculpt strokes as history steps - done by you in fa19bc1, merged by Claude. Follow-up: make Freeze
      Transformations on the edited mesh a history step too.
- [ ] M-F8 Fix from the review (c132c1f): undoing an extrude does not pop its history step - make undo/redo move
      the history with them, plus a test (undo, then edit a later step).

**Ziva (Windows) - keep the PC healthy, then the review items that need a real PC.**
- [ ] W-1 The "Do first" block above (engine not answering, update waiting, no Godot editor linked).
- [ ] W-2 Forge on WebView2: open Forge, run through the Maya hotkeys in docs/FORGE_MAYA_SPEC.md once (Ctrl, not
      Cmd; Alt camera; Space tap), report anything WebView2 eats (Alt opens the window menu? F10 focuses the menu
      bar? Ctrl+H / Ctrl+D taken by the browser?) - fix with preventDefault in app/ui/forge_maya.js.
- [ ] W-3 engine/data_sandbox.py (review, 9f928fe): the Windows Job Object memory cap never reports "memory" -
      the child gets a MemoryError instead of going over the peak. Make it `peak >= 0.95 * memory_mb or
      "MemoryError" in err`, check it on the PC with a 200 MB cap, add the case to its test.
- [ ] W-4 A real two-machine Spaces voice call Mac <-> PC through the relay (both on their own networks) - the
      takeover fix (a re-join must carry the member's own secret) shipped 2026-10-19; check an existing member can
      still come back after a restart.
- [ ] W-5 Fresh install from the zip on a clean Windows account, `uninstall.bat --purge`, reinstall: report the
      times and anything that needed a terminal.
- [ ] W-6 tools/ship.py now tests what the last commit changed when the tree is clean, and CI runs everything
      (LOKI_TEST_FULL=1): look at the next GitHub Actions run on the PC's push and report the suite count and time.

**Both:** the Auto Chess work (79a1318, d5223d8) is in the parked game - it stays (nothing gets removed), but
don't add to it until the owner answers in Needs Mohamed. `game/loki-world/scripts/autochess/arena_runtime.gd`
looks like a leftover debug script: ask there before touching it.

## Needs Mohamed

- [ ] (Claude, 2026-10-19) Auto Chess in LOKI World (79a1318, d5223d8): keep building it, or keep it parked with the rest of the game? It stays either way.

- [ ] **Release signing key + the first release.** Installed copies only update to a SIGNED release. Nobody has
      said they hold the private half of `keys/loki_public.pem`; if not, make a new pair (4 commands in docs/INSTALL.md
      "Signing": `openssl genrsa ...`, `openssl rsa -pubout ...`, `python tools/loki_sign.py fingerprint`,
      `gh secret set LOKI_SIGNING_KEY_PEM ...`), keep the private file offline, ship only the new public key. When the
      installer request passes: `git tag v0.17.0 && git push origin v0.17.0`. Optional, paid (LOKI never buys): a
      Windows code-signing certificate and an Apple Developer ID.
- [ ] **macOS permissions for computer use:** System Settings > Privacy & Security > **Accessibility** and **Screen
      Recording**: add `/Users/mohamed/Applications/Loki.app` and the Python it launches
      (`/opt/homebrew/Cellar/python@3.13/3.13.16/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python`),
      then restart LOKI. Also the decision: BUILD_BRIEF section 7 says "computer-use only inside VMs" - update it, or
      keep unattended work in cua VMs only?
- [ ] **NVIDIA key on the PC too?** It is on the Mac (`~/.loki/keys.env`). https://build.nvidia.com/settings/api-keys
      > Generate API Key (`nvapi-...`) > Settings > Connections > NVIDIA NIM on the PC.
- [ ] **Telegram bot:** @BotFather > `/newbot` > paste the token in LOKI on the **PC** (Settings > General > "Telegram
      bot token"; never anywhere else, not here) > "Pair my phone". Unblocks the automations briefing.
- [ ] **Which accounts should LOKI connect?** (a) email (Gmail? iCloud?), (b) calendar (Google, iCloud, or a read-only
      iCal link), (c) GitHub is ready via `gh auth login`, (d) notes: an Obsidian vault folder or Notion. Gmail/Calendar
      need your own Google OAuth client (Desktop app, Gmail API + Google Calendar API, yourself as a test user; "Testing"
      refresh tokens expire after 7 days) - simpler: a Gmail **app password** on the Email card and the calendar's
      **Secret address in iCal format**. iCloud: an app-specific password from appleid.apple.com. Notion: an internal
      integration secret, added to each page under ... > Connections.
- [ ] **Paid/rejected providers:** DeepSeek "Insufficient Balance", OpenRouter nearly empty (402 "exceed your
      available credits"; the PC's OpenRouter card model `deepseek/deepseek-v4.1-flash` is PAID - pick a `:free` one),
      and the **Mistral, Together and Cerebras keys are rejected** - top up / new keys, or Disconnect them
      (`/models doctor` lists them under "Needs you"; LOKI already skips them).
- [ ] **Phone:** your phone on the same Wi-Fi as the PC for pairing/QR checks; for the native iPhone app: Xcode (~10+
      GB; the Mac's internal disk is nearly full, it can live on /Volumes/LokiSSD), CocoaPods (`brew install cocoapods`),
      an Apple ID in Xcode. Android needs no Mac (mobile/INSTALL_PHONE.md, Expo cloud build).
- [ ] **Optional keys:** a **ModelScope** token (modelscope.cn/my/myaccesstoken - Qwen-Image 2.1 images, W11); a
      **Higgsfield** KEY:SECRET (cloud.higgsfield.ai) in Settings > General on the PC; **Home Assistant** address +
      long-lived token in Settings > Tools > Home; a Hugging Face OAuth app (`LOKI_HF_CLIENT_ID=...` in harness_data/.env)
      for "Sign in with a code".
- [ ] **Framepipe:** Claude could not find a "framepipe" repository - what is its exact GitHub name (owner/repo)?
- [ ] **Embedding model on the Mac?** `ollama pull nomic-embed-text` (274 MB) turns on hybrid memory search there
      (today: "no embedding model installed in Ollama", keyword-only).
- Note: Kyojin needs an AMD Strix Halo (Ryzen AI Max+ 395, 128 GB); neither machine can run it (`KYOJIN_BASE_URL`).

## Reports

<!-- newest first: YYYY-MM-DD machine (who) task: what happened. The last ~15 are kept here; older ones are in
     docs/operations/archive/ZIVA_TASKS_until_2026-10-19.md. -->
- 2026-10-19 ~05:00, Claude (cloud): Forge's Maya layer rebuilt from Maya 2027's own scripts on the Mac
  (docs/FORGE_MAYA_SPEC.md; FORGE_MAYA.md "2026-10-19"); tests/test_forge_maya_ui.py 55/55 in 23 s, test_forge_ui
  34/34, test_forge_edit_ui 20/20 (Blender set), model/creature/poly suites green. Review fixes: Spaces member
  takeover refused (test_spaces 35/35), DynaMesh step 0 can't be removed, sculpt-history recorder (fa19bc1) merged and only records real strokes,
  local model resolve keeps the size, uninstall --purge says truthfully that keys stay, *.md eol=lf, Blender's
  GPL-2.0 text added, ship.py --check on a clean tree tests the last commit and CI runs everything. HANDOFF.md
  and this file cleaned (full history in docs/operations/archive/). Your long-run loop and lists are above.
- 2026-10-18 windows (Ziva) W52 DONE. Studio was stuck on 5e00732: `harness_data/studio/pin.json` `"tried":
  {"9e1f7eb...": "ship.py failed: ... FAILED: ...because LOKI queued them (it waited, and said so)"}` - one flaky
  pacing test (window 1.0 s; a loaded PC's round-trip is longer). Fixed in tests/test_studio.py (window 3 s), 177/0;
  two Studio servers killed, the stale pinned copy removed. Cleaned: 8 loki/job-* branches + worktrees, merged local
  branches, the stash, 6 old origin branches; harness_data: OllamaSetup.exe (1.6 GB), espeak-ng.msi, scratch; VRAM
  7265 -> 966 MiB (`ollama stop`). Home shows the LIVE LOKI World again (`worldbg=1`; screens/w52-home-world.png).
- 2026-10-18 windows (Ziva) W51 DONE. The console pop-ups were (1) Ziva's own `cmd /k title ZIVA_TEST3` window
  (closed) and (2) the Startup entry `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Loki.lnk` ->
  `C:\Users\macul\Documents\loki\Loki.cmd` (a .cmd opens a console at every logon; LOKI.vbs also started LOKI).
  Fixed: app/loki_app.py retire_console_launchers() (test_no_console 19). 8 min of 120 ms window polling: nothing.
  Live link: Open in Godot -> Godot_v4.7.2-stable_win64 on "main.tscn - LOKI World"; GET /api/godot/editors: "LOKI
  World", godot 4.7.2, plugin 1.2, alive; Output "LOKI Studio plugin 1.2 ready (Godot 4.7.2-stable (official))".
- 2026-10-18 windows (Ziva) W50 DONE on 0e2af40: frameless title bar, min/max/close work, maximise keeps the taskbar
  (720x1232 on 720x1280), close quits the engine too; engine.out "getting LOKI's Godot 4.7.2 for LOKI World (one time,
  ~80-170 MB)" then "LOKI's Godot 4.7.2 is ready"; Open in Godot never touched ai_testin. FIXED: the Godot tab said
  "Godot is not installed on this computer: get Godot 4.7 from godotengine.org (or set GODOT_BIN)" while linked
  (godot_web.status() now uses loki_godot()); the World frame swallowed Ctrl+1..5 (host.js re-raises them);
  extensions.install left a read-only .git on Windows (_rmtree). Full `ship.py --check` green.
- 2026-10-18 mac (Ziva) M53: every Windows CI run was red at "Self-test the packaged app" with
  "loki: ModuleNotFoundError: No module named 'studio_godot'" (runs 39190963255, 39190421217) - packaging/loki.spec
  did not ship studio/. Fix shipped in 95f5d5e. Relay link live (3.3 s), both machines on d65ecfc / patch 305.
  anyCreature (Ariescar/anyCreature, MIT) assessed -> brought in as contrib/anycreature (b8521df, 64b18b9).
- 2026-10-18 mac (Ziva) M52: the Mac was not failing to update - LOKI was simply not running 16:12-21:07; on start it
  updated a3e1b64a4463 -> d65ecfc7d53b, carrying the re-saved game/loki-world/project.godot across. The live record is
  `.git/loki_update_health.json`; `harness_data/app/update_health.json` is a STALE legacy copy (Oct 14).
- 2026-10-18 cloud (Claude) 04def98's window-wide COEP require-corp broke every frame without COEP (test_research3,
  test_apps red; the Studio tab would be blocked). Fixed: COEP + CORP cross-origin on every bridge answer, studio_server
  sends both; the preview pane's Close bar no longer sits under the title strip. Not checked in WebView2/WKWebView
  (requests above).
- 2026-10-18 cloud (Claude) computer use refuses to click/type into LOKI's own window and open_app activates the app
  and checks it is in front (M25 c); test_files_ui was red on master (chat tables had two shapes) - fixed.
  test_studio / test_studio_godot fail on the cloud mcp stub only (no mcp.Client / MCPServer, mcp>=2).
- 2026-10-18 mac (Ziva) M25 (patch 234): computer use works but both grants are missing - computer(action=elements)
  "(no accessibility tree for this window - use action='look' to see it, or click text='...')", screenshot "error:
  screenshot failed: screencapture failed - give the app running LOKI Screen Recording permission (System Settings >
  Privacy & Security > Screen Recording)". After open_app TextEdit was not in front and the next action targeted
  `python` (LOKI). Kill switch (Ctrl+Option+Esc) PASSED; `POST /computer/arm` needs a `{}` body ("Request body is empty
  or too large."). Tools health map "86 work · 17 need setup · 28 off", no Broken row; GitHub issues + create-issue
  approval (declined, nothing created); Chromium 228 elements on HN in 1.7 s. ship.py --check 41 suites green.
- 2026-10-18 mac (Ziva) Session 26 UI check DONE (Chrome over CDP): Settings > Memory list/Search/Edit/Forget all
  work (Forget has no confirm dialog); the Draw pad layers and toggle work; the LOCAL qwen3.5-9b did not call
  sketch_reply (cloud drew it first try); in a headless browser the composer's ✎ Draw button computes to 0x0 px -
  check it in the real window. Screens memory-panel-mac.png, draw-pad-loki-mac.png.
- 2026-10-18 mac (Ziva) tests/test_ui_smoke.py never ran on macOS/Windows (chromium_path() only knew
  /opt/pw-browsers/chromium) - now uses Playwright's own browser; 7 passed on the Mac.
- 2026-10-18 mac (Ziva) the Godot web editor opened inside LOKI's window (COOP/COEP on the UI, native Godot via
  GODOT_EXE and any Godot*.app, Ctrl+N mode shortcuts on macOS). Also fixed test_systems' stale max_tokens 1 check.
  (The in-tab web editor was later removed in favour of the native editor, 0c9965a.)
- 2026-10-17 cloud (Claude) ported the peers nonce fix to engine/phone_link.py and mobile/src/lib/protocol.ts
  (test_phone_link 81). Could not reproduce the Godot headless flake - Ziva Windows later fixed it (d65ecfc: the suite
  joined a running LOKI; LokiApi.allow_connect=false; game tests 118/0).
- 2026-10-17 mac (Ziva) the task bench could never pass on a Mac: scripted `python todo.py ...` -> "program not found
  on PATH: python" (macOS has only python3). tests/tasks/base.py `PY_BIN` + `pycmd()`; `--scripted` 31/31, 94/0.
- 2026-10-17 mac (Ziva) two flakes were real bugs: engine/peers.py refused two identical same-millisecond requests as
  "replayed request" (HTTP 401) - the "link flaps" report; fixed with a signed `X-Loki-Nonce` (test_peers 67).
  engine/mmo_state.py dropped same-millisecond changes - `STAMP_DECIMALS = 6` (test_mmo_systems 125).
- 2026-10-17 mac (Ziva) patch 219: engine/loki_bridge.py had socketserver's accept backlog of 5, so a page load reset
  46 of 60 connections ("Connection reset by peer"; dead panels or a white window) - `request_queue_size = 128`, 0
  resets, guarded in test_systems. Bonsai 2 on the Mac fixed (`/setup/use` keeps the long context,
  model_setup.with_long_context); Kokoro needs `pip install --only-binary=:all: kokoro soundfile` on Python 3.13.
