# LOKI's agent system

Owner, 2026-10-28: "agent system design needs to be the main focus here. orchestration context memory tools guardrails
instruments power chassis ... interview like always asks me if this is what i want with options ... playbook and
toolbox do deep dive ... a schedule task for loki to always check where he got what hes using ... a way for me to not
want something made right now, i just send it back with a prompt."

Code: `engine/agentsys/` (one module per layer). Window: `app/ui/agentsys.js`, For you (`app/ui/home_review.js`),
Lab > System. API: `/agentsys/*` (`engine/agentsys/api.py`). Tests: `tests/test_agentsys.py`,
`tests/test_agentsys_ui.py`.

## Why (the root cause)

LOKI runs a request on one of several harnesses: OpenCode (the default), DeepSeek Harness, the Codex / Claude Code
CLIs, the local shell agent, or LOKI's own loop. Memory, lessons, triage, the tool guard, the stuck detector and the
experience log were all built inside LOKI's own loop - so on the default path **none of them ran**: no memory in the
prompt, nothing learned after a request, no trace of what happened. Every new layer was bolted onto one harness.

The fix is a chassis around every harness: `engine/agentsys/runtime.py install()` wraps `run_opencode` (chat, Build
tasks, background jobs - every harness goes through it), LOKI's own loop, its tool calls and its model calls. It runs
in the engine and in every job process (installed at the end of `engine/loki.py`).

## The layers

| Layer | Module | What it does | Copied from |
| --- | --- | --- | --- |
| Chassis | `runtime.py`, `hooks.py` | Wraps every harness: context in, trace around, guardrails out, learning after. Hook points `before_request`, `after_request`, `before_tool`, `after_tool`; strictest decision wins; a crashed tool check fails closed | Claude Agent SDK hooks, Google ADK callbacks/plugins |
| Interview | `interview.py` | 1-4 questions with 2-4 options each before work starts; drops what the request already says; big work asks "Specialist team or one agent"; unwatched work waits in For you as a question card | Claude AskUserQuestion, ChatGPT deep research's clarify step, A2A `input-required` |
| Orchestration | `orchestrator.py` | The delegation loop: task ledger (facts given / to look up / to derive / guesses, acceptance, plan) -> each step to a specialist with objective, output, tools, boundaries -> evaluator checks it, sends it back with fixes -> progress ledger; stall counter re-plans; a step waiting for the owner parks the run, resume carries on | Magentic-One ledgers + stall counter, Anthropic orchestrator-workers + effort scaling, evaluator-optimizer, Cognition single-threaded writes |
| Playbooks + toolboxes | `playbooks.py`, `playbook_interview.py` | The owner's workflow per job (goal, done means, steps, rules, examples) and its toolbox (tools, his files and templates, scripts, apps), one file per job in `<Home>/playbooks/`, written by LOKI interviewing him and used only once he approves it. Every preamble gets the index (names + one line) and the matching playbook in full; the `playbook` tool reads any | Anthropic Agent Skills (progressive disclosure), the owner's screenshot (2026-10-28) |
| Context | `context.py` | One preamble for every harness: the owner's rules -> extra -> the matching playbook + toolbox -> the playbook index -> memory pack -> learned bullets -> tools -> the ledger last; budget 10000 chars (4000 for a model on this computer); cut from the tools end, the owner's rules never | Manus (stable prefix, recitation), Anthropic context engineering |
| Memory | `memory.py` (existing) | Now on every harness: `memory.pack` goes into the preamble, `memory.after_request` learns after it | Mem0 / Letta (bounded pack) |
| Playbooks | `playbook.py` | Learned strategies per kind of work as counted bullets `[img-00042] owner helpful=3 harmful=0 :: ...`; a model only proposes ops (ADD / UPDATE / RETIRE), code applies them; hurting bullets retire; only the top few go into a prompt; the owner's notes are owner bullets a model can never rewrite | ACE (generator / reflector / curator), Dynamic Cheatsheet, ReasoningBank, Voyager |
| Toolbox | `toolbox.py` | Every tool's facts (read-only, destructive, asks the owner, GPU, online), MCP annotations on loki-make, `for_task` = core set + BM25 matches | MCP tool annotations, Anthropic tool search, langgraph-bigtool |
| Guardrails | `guardrails.py` | Budget (steps, re-plans, stalls, revisions, time, tokens), stall watch (same result again, A/B loops), spotlighting outside text that gives orders, destructive tools ask, a reply naming files that are not there is not shown as done | OpenAI tripwires, OpenHands stuck detector, Microsoft spotlighting |
| Instruments | `trace.py` | A trace per run: spans for the request, each model call (tokens), tool, guardrail, hand-off, interview and feedback; OpenTelemetry GenAI names; keys masked; 14 days kept; `runs()` / `summary()` for Lab > System | OpenAI Agents SDK tracing, OTel GenAI semantic conventions, Langfuse / Phoenix |
| Send back / park | `sendback.py` | Any result back with a note -> a revision request (note, original request, files, previous answer) + an owner bullet in the playbook; "Not now" parks the request (a running job is cancelled), resume with an optional note | Evaluator-optimizer with the owner as evaluator, Claude Code's denial message |
| Upstream | `upstream.py` | Registry of every open-source source LOKI uses (THIRD_PARTY.md, ecc_sync, PROVENANCE, docstrings, toolshelf) with its pin; a daily check (autopilot duty `upstream`) asks GitHub what changed; each new change is a For you card: Adopt (an agent ports what matters, moves the pin, tests, ships), Skip, Not now | - |

## One core agent

Owner 2026-10-28: "i want the one with the best results that doesnt break and is superior in all contexts do research".

| Source | Finding |
| --- | --- |
| Google Research, "Towards a science of scaling agent systems" (2025, 180 configurations) | Parallel, decomposable work: a centralized multi-agent set-up +81%. Sequential work: every multi-agent variant 39-70% WORSE. Independent agents amplify errors 17.2x, an orchestrator 4.4x; coordination costs grow with the number of tools |
| Anthropic, multi-agent research system | +90% on broad research (many independent directions) at ~15x the tokens of chat; poor fit for shared-context work, many dependencies, most coding |
| Cognition, "Don't build multi-agents" / "Multi-agents: what's actually working" | Parallel writers make conflicting choices; what works is ONE writer, read-only helpers (search), a reviewer with a clean context, map-reduce for research |
| Anthropic, Agent Skills | One general agent + skills (name/description always loaded, the full skill when it fits, bundled files/scripts on demand) instead of a separate agent per use case |

So: ONE core agent does the job, with the owner's playbook + toolbox for it (owner 2026-10-28: "change the style ...
no more 5"). No reviewer, tester, researcher or browser agent: the core agent has those tools, and the check is LOKI's
own from the outside - engine/proof.py (the files are real) and engine/receipts.py (every pasted output was really
printed by a tool), with engine/proof_runner.py running a request's own checks first. A "team" (engine/team.py) is
that one agent; the orchestrator's worker is the core agent. Models: every route is tried before giving up (only dead
ones - no credit, a model the key cannot run - are skipped), then LOKI's own agent on another route.
The art pipeline's gated stages (engine/asset_pipeline.py) stay: each stage is the same core flow with the owner's
check-off between stages.

## How a request flows now

1. The owner types. His message shows at once; the interview card follows (templates in milliseconds, a model may
   sharpen them inside 4 s). Go / As written / Not now. LOKI_INTERVIEW = always (default) | big | off.
2. The brief (his request + his choices) goes to the harness - or, for "Specialist team", to the orchestrator.
3. The chassis builds the preamble (memory, playbook bullets with ids), opens a trace, runs the harness.
4. The reply is checked (missing files are named, not shown as done), the run is remembered for a send-back, the
   bullets used are counted, memory learns in the background.
5. On LOKI's newest answer: Send back (a note) or Not now. A send-back is a revision request in the same chat and an
   owner bullet for that kind of work - the next similar task starts from his words.
6. Pictures keep the For you gate (prompt cards, result cards); the Prompt Expert now writes with the image
   playbook, and the owner's approve / retake counts for the bullets it used.

## The delegation loop in detail

- Specialists: the art pipeline (Concept Artist, Technical Artist, 3D Artist, 3D Finisher, Lighting/Render, Video
  Director - with their skills), the team roles (Researcher, Architect, Builder, Tester, Reviewer) and a general
  worker. A made-up name is mapped to the closest real one.
- Read-only steps run as sub-agents side by side (at most 3); writing steps run one at a time as background jobs.
- Each step's result is checked: files must exist, then a reviewer holds it against the step's own check. A failed
  check goes back to the same specialist with the fixes (LOKI_ORCH_MAX_REVISIONS, 2).
- After a failed step the progress ledger decides; past LOKI_ORCH_STALL_LIMIT (2) stalls, or when a failed step is
  out of tries, it re-plans what is left (LOKI_ORCH_MAX_REPLANS, 3). LOKI_ORCH_MAX_STEPS (24) caps a run.
- A step that waits for the owner (a picture prompt) parks the run; the autopilot resumes it once his cards are
  decided. Every run is saved in `<data>/orchestrations/<id>.json`; the report lands in the chat.

## Settings

| Variable | Default | |
| --- | --- | --- |
| LOKI_INTERVIEW | always | always / big / off |
| LOKI_INTERVIEW_MODEL_S | 4 | how long a model may sharpen the questions |
| LOKI_PREAMBLE_CHARS / _LOCAL_CHARS | 6000 / 2500 | the context budget |
| LOKI_PLAYBOOK_TOP_K / _MAX | 8 / 150 | bullets per prompt / per playbook |
| LOKI_ORCH_* | see above | the delegation loop's budgets |
| LOKI_TRACE / LOKI_TRACE_DAYS | on / 14 | traces |
| LOKI_UPSTREAM / LOKI_UPSTREAM_S / LOKI_UPSTREAM_BATCH | on / 86400 / 12 (80 with a token) | the upstream check; GITHUB_TOKEN or `gh auth` lifts GitHub's 60 calls an hour |

## What was not changed

LOKI's own loop keeps its memory triage, tool guard and stuck detector (they work there). The harness choice
(Settings > Agent) is untouched. `options.py` (readings of an open request) stays behind `/options`; the interview
replaced its automatic offer. Teams (`engine/team.py`) still run; the orchestrator uses their roles as specialists.

Research notes with sources: `docs/research/AGENT_SYSTEMS_2026-10-28.md`.
