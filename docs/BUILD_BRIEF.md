# LOKI — Build Brief for Claude Code

> Paste this whole file into Claude Code from inside the LOKI repo
> (`github.com/m03dev/loki`). It is the owner's direction for the next round of work.
> Read it fully, inspect the repo, then build. Do not stop at a plan.

---

## 1. What LOKI is

LOKI is a **living AI company on my own machines.** I tell it what I want, and it builds
it for me: it plans the work, assembles the right agents, gives each one the best model
for its job, runs them in parallel (in virtual machines and browsers when needed),
checks their work, and gets a little better every day.

- **It is alive.** It runs 24/7 on my PC, keeps working while I'm away, resumes after a
  reboot, and tells me what it did.
- **I never build agents by hand.** That's the whole point. LOKI decides which agents a
  job needs, creates them with the best spec (role, model, tools, limits), and retires
  them when done. I can look inside and override, but I shouldn't have to.
- **It improves itself, even little by little.** Every verified success becomes
  training data. The PC's GPU trains, tests and promotes better models and better
  routing. That's why the second machine exists, and I may add a third.
- **Everything works together.** Laya, the conductor, the agents, the browsers, the
  virtual machines, the memory, the learning loop and the machines are one pipeline,
  not a pile of separate features and tabs.

## 2. Hard rules

1. **Inspect first.** Read the repo, the docs and `git log` before changing anything. The
   current checkout and tests are the truth; docs and READMEs are not proof.
2. **Never lose work.** No destructive git (reset --hard, force-push, branch deletes) without
   a tag or backup first. Never move or delete files on my machines without checking
   them in a second way first (a past session trashed the live app folder because one
   listing tool showed it empty).
3. **Verify every claim.** Run the tests, run the app, and say exactly what was and wasn't
   verified. "It should work" is not done.
4. **Small steps.** Change one thing, test it, commit with a clear message, continue.
5. **No surprise costs.** Free and local first; paid providers stay behind the budget. Never
   buy or provision anything paid.
6. **Safety stays.** The policy engine, approvals for risky actions, the signed peer link,
   secrets out of git, and sandboxes (VMs) for anything that browses or clicks.
7. **Keep the repo clean and documented** (section 9) at the end of every session.

## 3. My machines

| Machine | Role | Where LOKI lives |
| --- | --- | --- |
| **Mac mini** (Apple Silicon) | where I work: the app window, chat, results | `~/Documents/loki` (Loki.app in `~/Applications` runs it) |
| **PC** (RTX 3070 Ti, 8 GB, on 24/7) | the worker: agents, VMs, browsers, local models, training | `C:\Users\macul\Documents\loki` |
| a third machine (later) | more workers | any |

They talk through the **peer link** (`engine/peers.py`, Settings > Machines,
`docs/operations/MACHINES.md`): signed, LAN-only, off by default.

## 4. Where the code is today (start here)

- Repo `m03dev/loki`. `master` and `macos-app` are identical as of commit `d16dda9`.
  Two parallel sessions were merged there. Work on one branch from now on (section 9).
- **App:** `app/loki_app.py` (pywebview window) + `app/ui/` (chat, settings, jobs,
  brain, setup), engine `engine/loki_bridge.py` (HTTP on 127.0.0.1:8767).
- **Agent core:** `engine/loki.py`: providers and smart routing with
  failover, tools, the DONE verification gate, paid budget, modes (Ask/Plan/Build).
- **Systems already there:** `conductor.py` (specialists by role), `workers.py` (background
  jobs: built-in Loki agent, Claude Code, Codex, herdr, cua), `agents.py`, `policy.py`,
  `manifests.py` + `capabilities/*` (Browser Use, cua, Crawl4AI, Firecrawl, Scrapling,
  Perplexity, Vane, Hermes, Hindsight, Headroom, SkillSpector, Kiln, Laya, Jev, Ollama
  fleet), `laya.py` + `decisions.py`, `model_setup.py` (offline-first model picking),
  `usage.py` (credits meter), `experience.py` + `tools/self_improve.py` +
  `tools/train_lora.py` (learning loop), `federation.py` (use another machine's Ollama),
  `peers.py` + `peer_link.py` (Mac ↔ PC), `knowledge.py`, `brain.py`.
- **Tests:** `tests/test_loki.py`, `test_hardening.py`, `test_integrations.py`,
  `test_workers.py`, `test_offline_e2e.py`, `test_peers.py`. All green at `d16dda9`
  (849 checks).
- **Never verified for real:** GPU training on the PC, the Mac↔PC link between the real
  machines, herdr/cua/Browser Use running real jobs, Laya with its real weights.

## 5. The work

Do these in order. Each item ends with **Done when**: build it until that is true and
shown.

### 5.1 Make LOKI its own app: nothing Godot about it

LOKI started as a Godot editor addon, and it still looks like one: `project.godot` at the
repo root, `addons/loki/...`, `.gd`/`.uid` files, a Godot dock, a vendored Godot MCP addon.
It must not be, or resemble, a Godot project anywhere.

- Restructure the repo as a normal application, for example `engine/` (the Python core,
  formerly `engine` + `loki_bridge.py`), `app/` (window + UI), `capabilities/`,
  `skills/`, `tools/`, `tests/`, `docs/`. Fix every import, path, the PyInstaller spec, the
  Mac launcher, setup scripts and tests.
- Delete `project.godot`, the Godot dock and plugins (`plugin.cfg`, `loki_dock.gd`,
  `loki_settings.gd`, `chat/`), `.uid` files, and anything only the Godot editor used.
- Godot becomes **one optional capability** for when I ask LOKI to make a game: an adapter
  that works on a game project somewhere else (installing its MCP addon into *that*
  project only when needed). It is not LOKI's own identity.
- The default workspace must not be `~/Loki` (that's how a game ended up in a folder
  named Loki). Use a projects folder, e.g. `~/LOKI Projects/<project>`, chosen per
  project.
- Remove leftover Godot projects named Loki on my machines (old `~/Loki` copies, the
  "missing project" entries in Godot's project list) **only after listing them and asking
  me.** Keep only the current app checkout and what's on GitHub.

**Done when:** a fresh clone contains no Godot files, the app and all tests run from the
new layout on Mac and Windows, and the Windows build still builds.

### 5.2 Laya as the first layer, fully offline

Laya (`github.com/receptron/laya`, the `@receptron/laya` package, ONNX weights) is the
fast local "System 1" that every request passes through first.

- Make it work with no internet: install the package and download the weights during
  setup (with progress), check Node is present, cache everything locally, and pass a
  self-test.
- Every request goes through Laya first for the cheap, fast decisions: what kind of
  task, how hard, which route (answer directly / one tool / plan / delegate to agents),
  risk level, "is the agent looping?", "does this look done?".
- Typed outputs, logged with the experience log, measured against outcomes. Laya's
  advice can't override the policy engine.
- If Laya is unavailable, fall back to the current heuristics and say so in the UI.

**Done when:** on a machine with the network cut off, a request is classified and routed
by Laya (visible in the trace) and its decisions are being logged and measured.

### 5.3 An agent company that builds itself

I describe the goal; LOKI builds the team.

- **Agent factory:** for each task, the conductor (with Laya's classification) decides
  which roles are needed (researcher, architect, coder, tester, reviewer, browser
  operator, designer...), creates each agent with the **best spec**: model chosen by
  measured success for that role (`experience.provider_stats`), hardware and cost; tools
  limited to the role; time and budget limits. Then it runs them.
- **Subagents that really work:** parallel where possible, a shared task board
  (who's doing what, blocked, done), messages between agents, hand-offs with results,
  and the parent verifies children's work before saying DONE.
- **Company structure:** standing teams can persist (e.g. a "web team" or a "game team")
  with their own memory and skills, and grow from what worked. I can view, rename,
  pause or fire agents, but never *have* to create them.
- Jobs run on the best machine automatically (PC for heavy/GPU/VM work, Mac for light
  work), using the peer link.

**Done when:** one sentence from me ("build a landing page for X and test it in a
browser") produces a visible team, runs it (partly on the PC), verifies the result,
and reports, with no agent set up by hand.

### 5.4 Alive 24/7 on the PC

- The PC runs LOKI as a **background service** (starts at boot, no window needed): the
  engine, the job queue, the peer server, the learning loop. A watchdog restarts it if it
  dies; jobs resume after a reboot.
- A heartbeat and status the Mac can see; notifications when something finishes, fails
  or needs me.
- Idle time is used well: training, evaluations and maintenance run when the GPU is
  free, and stop instantly when I game or render.

**Done when:** I reboot the PC, don't log in to anything, and the Mac shows the PC
online with its queue and the job that was running finishes.

### 5.5 Virtual machines and Browser Use: the workforce

- **cua** virtual computers on the PC (Docker Linux desktops; Lume VMs on the Mac): a
  pool with limits, snapshots, clean reset per job, and screenshots the app can show.
- **Browser Use** runs *inside* those VMs, never in my own browser: research, sign-ups
  I approve, testing websites LOKI built, data gathering.
- Approvals: logins, purchases, posting or sending anything always ask me first.

**Done when:** an agent opens a browser in a VM on the PC, completes a real multi-step
web task, and I can watch it from the Mac.

### 5.6 Self-improvement as the core loop

- Keep the existing loop (verified work → dataset → QLoRA on the 3070 Ti → eval →
  promote only if better) and make it **run on its own** on the PC, using work from all
  machines (the Mac already sends its verified work to the PC).
- Improve more than weights: routing by measured success, prompts and agent specs that
  win, reusable **skills** agents write from successful work (reviewed by the
  skill scanner before use), and a growing evaluation set.
- A plain "what LOKI learned this week" report.

**Done when:** after a week of normal use there is a recorded training run, an
evaluation, a promote/keep decision, and a visible routing change that came from
measured results.

### 5.7 Make the app feel like one thing (modular underneath)

- **Remove the Brain tab** unless it becomes genuinely useful (e.g. browsing and
  correcting what LOKI knows). Pictures alone aren't worth a tab.
- **Remove the Background tab.** Background work belongs *in the pipeline*: when I ask
  for something, the chat shows the team, its progress, the machine and the result,
  right there.
- Fewer small features, each one useful. Every system is a module with a clear interface
  (the capability manifests and `interfaces.py` are the start), so parts can be swapped or
  switched off without breaking the rest.

**Done when:** a new user can install, chat, see a team work and get a verified result
without visiting any extra tab.

### 5.8 More model sources

Keep OpenRouter and the current providers. Then **evaluate and add** more sources (verify
each one's current terms, free tier, OpenAI compatibility and limits before adding; note
what you found):

- Gateways and routers: Cloudflare AI Gateway, Vercel AI Gateway, Portkey, Requesty,
  LiteLLM (self-hosted on the PC as one gateway for everything).
- Hosted models: Hugging Face Inference Providers, GitHub Models, NVIDIA NIM, Together,
  Fireworks, DeepInfra, Novita, Hyperbolic, Nebius AI Studio, Chutes, Groq, Cerebras,
  SambaNova, Mistral, Google AI Studio.
- Local on the PC: Ollama, LM Studio, llama.cpp server, vLLM. The PC serves models to the
  Mac over the LAN (`LOKI_WORKERS`).

Route by measured quality, speed, cost and availability per role, free and local first.

### 5.9 Ziva

I'd like to use Ziva (ziva.sh) if possible. As of October 2026 I couldn't find a public
API: its site describes a Godot editor agent that uses your own Claude Code / Codex
subscription or local models, and lets you add MCP servers to it. Check the official
docs and pricing. Integrate only through an **official** API or MCP endpoint whose
terms allow it. If there isn't one, write down what you found and move on. LOKI already
uses Claude Code and Codex subscriptions the same way.

### 5.10 Home and the modes (owner, 2026-10-21)

- Home is calm: one header row, the big preview, ONE row of recent things (All for the rest); running jobs are a
  "working" chip that shows the job in the preview. Keep it that way - nothing new crowds Home without a reason.
- **Later (keep it in mind, not built yet): a live view on Home** - the preview spot showing live work as it happens
  (a render filling in, a farm job, Forge or Godot), built into the existing preview, not a new panel.
- The modes in the message box are for the digital industry: Content creator, Social media, Outreach (cold emails,
  follow-ups, sponsor / collab pitches), Writer, Growth & SEO, Researcher, Developer, 3D & games. "General" keeps its
  name with a plain icon. No Small business / Tutor / Student / Life admin.

### 5.11 LOKI markets what it makes (owner, 2026-10-22)

- "Start doing ads and making social media content for the app - that's what the app has to do, gear it towards that."
  LOKI's agents make the brand and the marketing: names, logos, posting calendars, captions, short-video scripts, post
  images and ad drafts - for LOKI itself first (it is being renamed), then for whatever the owner makes with it (a
  model, a render, a game). Work lands in the workspace's `brand/` and shows on Home as **Content**.
- Drafts only until the owner approves: nothing is posted, published, bought or renamed by an agent on its own
  (section 7 still holds). Connecting real accounts (X, Instagram, TikTok, YouTube) is a later, owner-approved step.
- The modes in the message box already lean this way (Content creator, Social media, Outreach, Growth & SEO).

## 6. Add anything else that serves this

You may add features I haven't named if they make LOKI more alive, more capable, cheaper or
better at improving itself. For example: a nightly "what got done" summary, phone
notifications, a project memory per company/team, automatic test generation, cost
reports per project, a skills marketplace from my own successful work. Explain each
addition in the report.

## 7. Cost and safety guardrails (keep these)

- Free/local first; paid providers capped per request and per day; a cost line on every
  answer.
- Risky actions (delete, money, logins, posting, sending) always ask me.
- Browsers and computer-use only inside VMs.
- The peer link stays signed, LAN-only and off until I turn it on.
- Secrets never in git, logs or training data.

## 8. Definition of done for each session

- Tests run and pass (and new tests for what you built).
- The app was actually started and the feature was used, and you say how.
- What was **not** verified is listed plainly.
- The repo is cleaned and the docs updated (section 9).

## 9. Repo hygiene, every session

- **One main branch.** Merge finished work; tag before anything risky; delete merged
  feature branches (tag `safety/pre-hardening` first so it's kept).
- **README = how to build and run LOKI** on Mac and Windows, kept current: requirements,
  setup, run, test, build the Windows app, link the machines, start training. No history
  in it.
- **Remove what's obsolete.** The project has changed a lot: delete superseded docs,
  dead code and old experiments (Godot addon pieces, replaced catalogs, unused
  prototypes). Keep `docs/` small and true: architecture, operations (Mac, Windows,
  machines, training), decisions, security, and a short session log.
- `.gitignore` covers all runtime data (`harness_data/` or its replacement, logs,
  venvs, models, VM images).
- Clear commit messages that say what changed and how it was verified.

## 10. Report at the end

1. What you built, in plain words.
2. What you verified, and how (commands, runs, screenshots).
3. What doesn't work yet, and why.
4. What you removed from the repo.
5. What I need to do on each machine (exact commands), if anything.
6. The next most valuable step.
