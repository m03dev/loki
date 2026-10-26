# LOKI_TASKS.md - work for LOKI's own agents

LOKI's autopilot takes the oldest open `[loki]` request under "Requests" (engine/autopilot.py), does it, and ticks it.
`[windows]` / `[mac]` = it needs that machine (the other machine's LOKI gets it through run_on_machine). Write results
into the workspace's qa/ folder. The owner and Claude add requests here; nobody else.

## Requests

- [ ] [loki] [windows] DO FIRST - area edit proof on this PC: make a picture of "a knight with a sword and shield, full body" (make_image), then edit ONLY the helmet area with region_edit (POST /image/edit-area {path, box, prompt: "a golden helmet with a red plume", strength 0.75} or `python -c "import sys; sys.path.insert(0,'engine'); import region_edit; print(region_edit.edit_area(...))"`). Check the original file is unchanged and that every pixel outside the box matches it (PIL ImageChops.difference); write qa/area-edit.md with both file paths, the box, the seconds it took, the backend and any error text, and show both pictures. If sd.cpp rejects -i/--mask with this model, say so and try without --mask. (owner via Claude, 2026-10-26)
- [ ] [loki] [mac] DO FIRST - the same area edit proof on the Mac with mflux (--image-path / --image-strength); everything big on /Volumes/Xero (LokiSSD while Xero is away). qa/area-edit-mac.md. (owner via Claude, 2026-10-26)
- [ ] [loki] [windows] Turnaround v2 on this PC's ComfyUI (docs/PIPELINE_RESEARCH_2026-10-26.md section 2): install Qwen-Image-Edit-2511 as a GGUF Q4 (or Nunchaku) build that fits the 8 GB card with offload, the DWPose preprocessor and the Apache LoRA fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA - big files under D:\ (never C:). Check each licence on its Hugging Face card first and write it into docs/THIRD_PARTY.md; stop if one is not Apache/MIT. Then take the newest concept in images/ and make front, side, back and top views of it in a T-pose; save them like make_turnaround does (turnarounds/<name>/) and write qa/turnaround-v2.md: time per view, VRAM peak, how well each view matches the concept next to make_turnaround's v1 sheet for the same concept. (owner via Claude, 2026-10-26)
- [ ] [loki] [windows] 3D from the turnaround: TRELLIS.2 in ComfyUI (native nodes) in low-VRAM mode with BiRefNet for the cut-out (never RMBG-2.0), MESH ONLY first, from the front view of the newest turnaround; then check whether textured GLB export needs nvdiffrast (non-commercial - do not use it) and write the answer and the model's triangle count, time and VRAM into qa/trellis2.md. (owner via Claude, 2026-10-26)
- [x] [loki] [windows] Blender MCP on this PC - DONE 2026-10-26 by Claude through the file inbox: Blender 5.2.3 LTS, LOKI's loader + core in the Script Directory ~/LOKI Projects/Home/blender/scripts (set by the owner), MCP socket 9876 up, campfire built/rendered/exported (renders/campfire-blender_20261026-1338.png, models/campfire-blender_20261026-1338.glb + .blend). Use the `blender` tool now (engine/blender_link.py); fixes to the core are a file write (hot reload).
- [ ] [loki] [windows] Make with Blender: through the `blender` tool (action=make), build from scratch and render 3 game props for the concept-art pipeline - a treasure chest, a wooden signpost, a lantern - low-poly, own scene each, named after the prop; show the renders in the chat and list the .glb/.blend files. Write qa/blender-props.md with what worked and any error text. (owner via Claude, 2026-10-26)
- [ ] [loki] [mac] DO FIRST - Blender on the Mac: `harness_data/.venv/bin/python engine/blender_link.py setup --install` (brew onto /Volumes/Xero, LokiSSD while Xero is away - never the internal drive; it copies the add-on, LOKI's loader and core into Blender's own scripts folder and enables the add-on), then `... blender_link.py proof` (works with no Blender window: a background Blender), show the render in the chat, qa/blender-mac.md with the JSON. (owner via Claude, 2026-10-26)
- [ ] [loki] [mac] DO FIRST - find the owner's Maya MCP ("i have it, it should work"). It is not on the PC (checked 2026-10-26: nothing in Documents\maya, Maya's plug-ins, npm or uv tools). Look on the Mac: ~/Library/Application Support/Claude/claude_desktop_config.json, ~/.cursor/mcp.json, ~/.codex/config.toml, ~/Library/Preferences/Autodesk/maya/2027/ (scripts, plug-ins, userSetup.py, commandPort), ~/Documents, ~/Downloads, /Volumes/Xero and /Volumes/LokiSSD for folders or files named *maya*mcp* / *mcp*maya*. Report where it is, its repo/licence and how it starts in qa/maya-mcp.md. If it is MIT/BSD/Apache/GPL: add it to engine/mcp_servers.json as "maya" (with a requires_check like blender's so it only starts where Maya is installed), make Maya open the port it needs at startup on both machines, and prove it: through its tools make a polyCube, bevel it and save scenes/maya-mcp-test.ma. Ask the owner first if its licence is anything else. (owner via Claude, 2026-10-26)
- [ ] [loki] [mac] 3D scene, first try: MCP for Blender is now built in (engine/blender_link.py, request above); then lay out one small game scene (a forest clearing) from 3+ models in models/ plus Poly Haven CC0 ground and trees, export it as glTF into scenes/ and render one still with render_scene. Write qa/scene.md with the steps that worked. (owner via Claude, 2026-10-26)
- [ ] [loki] [windows] DO FIRST - local model test, on THIS PC's local model (loki-huihui_ai-qwen3-abliterated-8b, no cloud): draw "a knight with a sword and shield" with make_sprite (size 64) into sprites/, then list sprites/ and reply with the exact file path, its size in pixels and the model that made it. Write the same into qa/local-abliterated.md. (owner via Claude, 2026-10-26 10:40)
- [ ] [loki] [windows] Forge 3D on this PC: update ComfyUI (git pull in its folder, restart it), then run `python tools/setup_trellis.py` and `python tools/setup_trellis.py install` from LOKI's folder; restart ComfyUI; run setup_trellis.py again until pixal3d, trellis2 and pixal3d-views all say ready. Then make one model in Forge (Image, a picture of one object, backend Pixal3D) and write qa/trellis.md: time taken, triangles, any error text; if it ran out of GPU memory, retry with ComfyUI started with --lowvram and Output > Detail 512, Texture 2048, and write which settings worked. (2026-10-25)
- [ ] [loki] [windows] Startup time: start LOKI once after updating and copy harness_data/app/startup.json into qa/startup.md with the slowest step named. (2026-10-25)
- [ ] [loki] [windows] Local model check: in a new chat on the local model, "make a git repo called win-test with a README, commit it and show git log"; paste the reply's git log into qa/local-model.md. (2026-10-25)
- [ ] [loki] Pixel art check (again - the first run looped on the local model): pixelize three pictures from images/ with `loki-make pixel <file> --size 64` (plain, --palette pico-8, --palette endesga-32 --dither bayer) and write qa/pixel.md with the files made and how they look. (2026-10-25)
- [ ] [loki] Build the next "not yet" rows of docs/FORGE_MAYA_PARITY.md, Edit Mesh and Mesh Tools first (Add Divisions,
      Smart Bevel, Smart Extrude, Transform, Flip, Symmetrize, Edit Edge Flow, Flip Triangle Edge, Make Hole, Crease Tool):
      one command at a time, each with a test, its id added to MAP in tools/forge_maya/gen_layout.py, then gen_layout.py
      and tests/test_forge_maya_layout.py. Real commands only - never a row that does nothing. (owner via Claude, 2026-10-22)
- [ ] [loki] Brand name: research 20 candidate names for this app (a desktop 3D studio: Maya-style modelling + sculpting, a render studio with an AI renderer, a Mac+PC worker farm and AI agents), check each with web search for existing apps, trademarks, a free .com / .app and free @handles on X, Instagram and TikTok, then pick the best 3 with the reasons and the checks. Write brand/name.md (a table of all 20, the top 3 first). Do not rename anything in the code: the owner picks. (owner via Claude, 2026-10-22)
- [ ] [loki] Logo: for each of the top 3 names in brand/name.md, 3 logo directions (a mark + a wordmark) as clean SVG files - one-colour and full-colour, readable at 16 px, on dark and on light - plus a picture of each as an app icon and on a social banner made with the image generator on the PC's GPU. Save to brand/logo/<name>/ and compare them in brand/logo/index.md with your favourite and why. (owner via Claude, 2026-10-22)
- [ ] [loki] Social content kit: a positioning line, 3 audience personas (3D artists, indie game devs, AI-curious creators), a 2-week posting calendar for X, Instagram, TikTok/Shorts, LinkedIn and Reddit (r/3Dmodeling, r/blender, r/IndieDev - follow each subreddit's self-promotion rules), 14 ready captions with hashtags, 5 short-video scripts (15-45 s: Forge sculpting, Multi-Cut, the AI renderer, the agent farm) and 6 post images made from real Forge renders and screenshots. Save to brand/content/ with brand/content/calendar.md. Draft only: post nothing. (owner via Claude, 2026-10-22)
- [ ] [loki] Ad drafts: 3 ad concepts, one per persona in brand/content/, each with a headline, body, call to action and visual, made for 1080x1920 (Instagram / TikTok), 1200x675 (X / LinkedIn) and a 15 s YouTube pre-roll script; make the visuals with the image generator and Forge renders. Save to brand/ads/ with brand/ads/index.md. No ad accounts, no spend: drafts for the owner. (owner via Claude, 2026-10-22)
- [ ] [loki] Render check: `loki-make render models/<any>.glb` (passes only), then with --prompt (a still) and with --prompt --frames 33 (a turntable; collect it with action=status). Write what came out and how long each took into qa/render.md.
- [ ] [loki] Make now (retry, fixed tool calls): one picture of a red baby dragon guarding a pile of gold coins, game concept art, 16:9 (make_image) into images/, then a 64-pixel sprite of it (loki-make pixel --size 64 --palette endesga-32) into sprites/. Reply with both file paths. (owner via Claude, 2026-10-25 19:50)
- [ ] [loki] Make now (retry, fixed tool calls): render models/creature.glb with render_scene - passes and contact sheet (no prompt), then a 9-frame turntable of passes - into renders/. Reply with the folder. (owner via Claude, 2026-10-25 19:50)
- [ ] [loki] Make now (third try, own plan per team): read this line aloud with the voice tool and save it in voice/: "LOKI is online. Your agents are building while you sleep." Reply with the file path. (owner via Claude, 2026-10-25 19:50)
- [ ] [loki] Make now (retry, fixed tool calls): a 3D model from images/20261017-115147-a-red-fox-sitting-in-green-grass-soft-morning-li.jpg (make_3d, best backend this computer has) into models/, then render_scene it into renders/. Reply with the paths. (owner via Claude, 2026-10-25 19:50)
- [ ] [loki] [windows] Make now, from scratch on this PC: a new picture of a stone golem guardian in a mossy forest, game concept art, 16:9 (make_image) into images/, then a textured 3D model of it (make_3d, backend pixal3d or trellis2 on ComfyUI) into models/, then render_scene it with frames 48 into renders/. Reply with every file path. (owner via Claude, 2026-10-25 19:57)
- [ ] [loki] [windows] Make now, from scratch on this PC: a 30-second instrumental music loop, mysterious forest temple, soft drums and flute (make_music) into music/. Reply with the file path. (owner via Claude, 2026-10-25 19:57)
- [ ] [loki] [mac] Hand one job to the PC with run_on_machine (machine pc): "make a new picture of a glowing crystal sword on a stone altar, game concept art (make_image), save it in images/ and reply with the path" - then check it with machine_job until it is done and write the result into qa/pc-handoff.md. (owner via Claude, 2026-10-25 19:57)
- [ ] [loki] [mac] Make now: three new pieces of game concept art like the red baby dragon the owner loved (make_image with style game-concept, 16:9): a moss golem waking in a ruined forest temple, a fox spirit with blue flame tails on a cliff at dusk, an ice wyvern over a frozen lake - into images/. Reply with the paths. (owner via Claude, 2026-10-25 21:10)
- [ ] [loki] [mac] Make now: game sprites with make_sprite (loki-make sprite): one from images/20261025-205231-concept-art-of-a-red-baby-dragon-guarding-a-pile.png (size 64), and two drawn from scratch - "a fox spirit with blue flame tails" and "a small moss golem" (size 64) - into sprites/. Reply with the paths. (owner via Claude, 2026-10-25 21:10)
- [ ] [loki] [mac] Hand one job to the PC with run_on_machine (machine pc): "make_3d from a new picture: draw 'a red baby dragon, full body, game asset' (make_image style sprite-source), then make_3d it with the best 3D backend this PC has (pixal3d or trellis2 on ComfyUI, else online), then render_scene it with frames 48; reply with every file path" - follow it with machine_job until it is done and write the result into qa/pc-3d.md. (owner via Claude, 2026-10-25 21:10)
- [ ] [loki] [mac] Make now (retry 4 - pass image="images/<the picture you drew>" to make_3d), real 3D on this Mac: draw "a small moss golem, full body, game asset" with make_image style sprite-source into images/, then make_3d it with backend online (TRELLIS on Hugging Face, now installed) into models/, then render_scene it with frames 48 into renders/. If online fails, write the exact error into qa/mac-3d.md. Reply with every file path. (owner via Claude, 2026-10-25 21:55)

## Always

Standing goals: LOKI's agents keep working through these, in turn, whenever a slot is free and no request is
waiting - up to 3 at once (LOKI_AUTOPILOT_SLOTS), anything that needs the GPU one at a time. Drafts and assets only:
nothing is published or posted without the owner. Edit freely.

- [loki] Look in the library first, then make one new piece of game concept art for the owner's game (make_image style game-concept - the owner's favourite, 16:9) into images/, with a two-line caption draft in brand/drafts/.
- [loki] Make a 64-pixel game sprite of the main subject of the newest concept picture in images/ that has no sprite yet: describe that subject in a few words and draw it fresh with make_sprite prompt=... (not cut from the scene - a sprite from a busy scene loses parts), into sprites/, and note it in brand/drafts/assets.md.
- [loki] Write one short devlog / social post draft about what changed in LOKI since yesterday (git log in the LOKI folder) into brand/drafts/, with a suggested picture from the library.
- [loki] Make one 30-60 second instrumental music loop for the game (make_music; a mood not made before - check the library) into music/.
- [loki] TECHNICAL ARTIST: take the newest concept picture in images/ that has no turnaround yet (check turnarounds/*/turnaround.json "concept") and make its turnaround with make_turnaround concept=<that picture> kind=<character | creature | prop | vehicle> - flat orthographic front, side, back and top views, T-pose for characters - into turnarounds/. Open the sheet and check the views match each other and the concept (same colours, shapes, parts); if one view is off, make it again with the same seed. Note it in brand/drafts/assets.md (concept -> sheet).
- [loki] [windows] 3D ARTIST: take the newest turnaround in turnarounds/ that has no model yet and make the model from its FRONT view (make_3d image=turnarounds/<name>/front.png, backend pixal3d, else trellis2) into models/, named after the turnaround; check it against the side and back views and say what differs. Write concept -> sheet -> model into brand/drafts/assets.md so every asset's path is known.
- [loki] Render the newest model in models/ that has no render yet (render_scene; a finished still with a prompt in the game's style, and a 33-frame turntable when ComfyUI is free) into renders/.
- [loki] Test one of LOKI's makers on a real file, in turn (loki-make pixel, render, image, voice, music, library - the next one after the last in qa/makers.md): run it, open what it made, and add a row to qa/makers.md (date, maker, input, output file, worked / broke and the error).

## Needs Mohamed

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


## 2026-10-26 - check the storage fix on the Mac
- After this update, open the Local models tab on the Mac: the Hugging Face models (harness_data/big/huggingface, ~18 GB) and Ollama models must be listed again. Report the count in the task log.
- Never write into /Volumes/Xero/loki - it is an old copy of the repo, not a cache folder. Big things go to harness_data/big (LokiSSD, which lives on Xero).

## 2026-10-26 - PC: jobs stopped on a non-answer (merge origin/agent/pc-non-answer first)
- Seen on the PC today: 6 of the last 9 team jobs ended "BLOCKED: no tool ran". Chain each time: NVIDIA DeepSeek timed out
  after 1200 s, OpenCode Zen "Model is unavailable", DeepSeek "Insufficient Balance", then Vireonix 'auto' answered
  "Unable to answer question due to internal guardrails" or "I don't see a specific team goal" - and the job stopped there.
- The branch makes such a reply move on to the next provider (this PC's local model included) and benches the route for
  an hour; empty-balance DeepSeek is benched 12 h, a 1200 s timeout 1 h.
- Check on the PC: run one Builder job ("make a 64-pixel sprite of a knight") with the local abliterated model
  (huihui_ai/qwen3-abliterated:8b, installed) and report the file it made, the model that made it and how long it took.
