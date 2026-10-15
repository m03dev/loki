# Systems worth importing into LOKI

A survey of open-source projects whose *systems* (not code) LOKI should adopt, mapped to the
files that would change, with a verdict and a reason. Written after reading LOKI's own
architecture (`docs/ARCHITECTURE.md`, `engine/` ~21k lines) so nothing here duplicates what
already exists.

The owner's rule: **one coherent system, not a pile of features and tabs.** Each row says what
LOKI has today, what the outside project does better, and the smallest change that closes the
gap. Each lands on its own, with tests; none needs a big-bang rewrite.

---

## 1. Evaluations - Inspect (UK AISI) - ADOPT

**Theirs.** A Task is exactly three things: a **dataset**, a **solver** (how the model is
driven) and a **scorer** (how the answer is graded). Solvers are composable functions over a
`TaskState`; scorers are separate so one task runs under many strategies (`--solver`). 200+
pre-built evals use that one shape.

**Ours.** `experience.py` logs outcomes and `tools/self_improve.py` promotes a model "only if it
beats the current one" - but there is **no evaluation harness**: no dataset, no solver
abstraction, no scorer, no baseline. "Better" is decided from loose production evidence, so
improvement is neither measurable nor reversible - which the vision explicitly asks for.

**Change.** **DONE**: `engine/evals.py` (`Task` = dataset + solver + scorer, `run`, scorers,
`REGISTRY`, `record` -> the routing scorecard) + `tests/test_evals.py`. Next: the local-model
trial that drives each installed model through `TRIAL_TASKS` and records the score.

| Task | scorer |
| --- | --- |
| `make-a-file` | the file exists and holds the expected text |
| `call-the-right-tool` | right tool name + right argument (BFCL-style) |
| `answer-from-the-project` | the expected fact is in the answer |

## 2. Routing on predicted difficulty - RouteLLM - ADAPT

**Theirs.** Learn a router from preference data to send easy queries to a weak/cheap model and
hard ones to a strong/expensive one, holding quality at a target: cost >2x lower at equal
quality, and it generalises to model pairs it never trained on.

**Ours.** `SMART_ORDER` + `learned_order` (per-provider success) and `first_layer` already
computes **difficulty 0..3** - but routing ignores it. A trivial request and a hard one take the
same path.

**Change.** Feed `LAST_TRIAGE["difficulty"]` into routing: 0-1 may stay on a local or free model
even when something stronger is configured; 2-3 prefers the strongest available. The tiers
already exist (`provider_tier`), so this is one policy function.

## 3. Router mechanics - LiteLLM - ADAPT

**Theirs.** `order` = priority levels inside a model group (all order-1, then order-2); within a
group, strategies (least-busy, latency, cost); a 429 puts a deployment on **cooldown** after
`allowed_fails` in a minute; and the **budget is re-checked against every fallback target**, so a
free primary cannot silently fall back to a paid model uncapped.

**Ours.** Failover, `_SMART_FAILED`, `_RATE_LIMITED` with a wait, and a paid budget re-checked
before each attempt (keep that - it is the same guarantee).

**Change.** (a) Model the `allowed_fails`/`cooldown` pair instead of one "used-up" mark, so a
provider that hiccuped once is not exiled for the whole session. (b) Make LOKI's tiers explicit
`order` levels so "every free tier, then subscriptions, then local" is data, not list order.

## 4. Skills - Agent Skills spec (agentskills) - ADOPT (mostly already right)

**Theirs.** A skill is a folder with `SKILL.md`: YAML frontmatter `name` (<=64, lowercase and
hyphens, must match the folder), `description` (<=1024, must say what it does **and when to use
it**), optional `license`, `compatibility`, `metadata`, `allowed-tools`; then **progressive
disclosure** - metadata (~100 tokens) at startup, the body (<500 lines) on activation, and
`scripts/`, `references/`, `assets/` only when a step needs them.

**Ours.** `skill_scan.py` already parses the frontmatter and **deliberately ignores
`allowed-tools`** - correct, because `policy.py` decides what may run, not the skill. Ruflo's 47
plugins ship in the same shape.

**Change.** Validate against the real field limits, require the description to state *when* to
use the skill, and load bodies only for the skills triage selected instead of listing them all.
Keep ignoring `allowed-tools`, and document why.

## 5. Memory - Letta/MemGPT, Mem0, GraphRAG - ADAPT (consolidate, do not add)

**Theirs.** Letta: an agent owns **memory blocks** it edits, with a paged working context. Mem0:
extract durable facts and consolidate them. GraphRAG: an entity graph, answered from communities.

**Ours.** Five peer modules hold memory-ish state: `knowledge.py`, `brain.py`,
`project_state.py`, `reasoning_bank.py` (lessons - that is ExpeL, already), `experience.py`, plus
the `save_memory`/`recall` tools. That is the "pile of tabs" the owner objects to.

**Change.** Define **one** memory interface with named tiers - working (this request), episodic
(reasoning_bank), semantic (knowledge/brain), procedural (skills) - and make each module an
implementation of a tier instead of a peer. No new storage engine; the win is one interface and
one consolidation path.

## 6. Orchestration - MetaGPT / AutoGen / CrewAI - ADAPT

**Theirs.** MetaGPT runs a **SOP** where roles produce typed artifacts (requirements -> design ->
code) and each consumes the previous one's. AutoGen has an explicit speaker-selection policy.

**Ours.** `team.py`: roles per goal, stages, a shared board, one fix round, SPARC support.

**Change.** Make the **artifact** the unit that moves between stages (a named, typed dict), so a
stage consumes a specific artifact instead of reading the whole board, and "the Researcher wrote
a specification" becomes checkable rather than inferred from prose.

## 7. Agent-computer interface - SWE-agent / OpenHands - ADAPT

**Theirs.** SWE-agent calls the agent/computer boundary the ACI and optimises it: terse,
well-bounded outputs, and a linter on every edit so the agent sees its own error immediately.

**Ours.** `safe_exec.py` (no shell - keep), and `verify_files` only after DONE.

**Change.** Return tool output **compactly** (head/tail with an explicit elision marker) and run
the syntax check at edit time, not only at the end. This is the biggest single lever on small
and local models: shorter, cleaner observations.

## 8. Observability - OpenTelemetry GenAI semconv, Langfuse/Phoenix - ADAPT

**Theirs.** One trace per run, spans for model and tool calls, standard attribute names
(`gen_ai.system`, `gen_ai.usage.input_tokens`), so any viewer can read it.

**Ours.** `events.py` and `experience.py` - good content, LOKI-specific shape.

**Change.** Emit the same data under the standard names too, so a run opens in a generic viewer
with no custom exporter.

## 9. Durable execution - Temporal / Inngest - ADAPT (a slice)

**Theirs.** Work survives a restart: each step is journalled, so a crashed workflow resumes.

**Ours.** `workers.py` jobs with a 24/7 requirement, but a job in flight at reboot is lost.

**Change.** Persist a step journal per job and resume on start. LOKI already writes job state;
the change is to make that state a resume point rather than a status.

---

## Deliberately NOT taken

| Project | Why not |
| --- | --- |
| OBLITERATUS (abliteration) | Removes a model's refusal behaviour. Reliability comes from native tool calls, the tool guard and a tool-tuned model, not from uncensoring. |
| Grammar/constrained decoding *replacing* the tool guard | Already added (constrained JSON in `tool_guard.py`); the guard repairs what a grammar cannot (wrong names, missing required values). |
| Auto-approving policy engines | Owner's hard rule: risky actions wait for a human. Laya/Jev may skip a *safe* prompt, never grant a permission. |
| Shell-based tool execution | `safe_exec.py` runs commands without a shell on purpose. |

## Priority

1. **`engine/evals.py` + the local-model trial** - the missing backbone of Evolution, and it
   feeds routing with real numbers. *(harness shipped)*
2. **Difficulty-aware routing** - small, and it is what "smart" should have meant.
3. **Compact tool output + check-on-edit** - the biggest lever on local model quality.
4. **Memory tiers behind one interface** - the "make it one system" rework.
5. Skills spec validation, artifact-typed teams, event semconv, durable jobs.
