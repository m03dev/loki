# Loki — Master System Blueprint

> Canonical long-term vision and rules for the Loki project. Read this before making
> significant architectural decisions. Update implementation status in the roadmap and
> session log, never here — this document describes the enduring direction.

Repo: https://github.com/m03dev/loki
Local checkout: `C:\Users\macul\Documents\loki` (this is the confirmed, active checkout)

Loki is an AI development and creative operating environment, delivered as a
**standalone desktop app** (`app/`) over the Loki engine. The Godot 4 editor addon
remains as an optional adapter for game projects (see the 2026-10-12 scope entry). It should be able to receive a goal, understand a
project, retrieve the right context, consult its decision layer, select appropriate
tools, execute an approved workflow, verify the result, and preserve the knowledge
required to continue later.

The goal is **not** to download the largest possible collection of repositories. The
goal is a system that can discover, evaluate, integrate, manage, and safely use useful
capabilities. Every capability must be discoverable, permissioned, testable,
replaceable, and observable.

---

## 0. Scope log

Dated, permanent records of scope changes. The vision above stays; this is how the
concrete scope has grown against it.

- **2026-10-12 — Phase 1 safety.** `run_command` gained a `command_policy()` guard
(destructive shapes and remote-execution pipes are refused before the shell).
- **2026-10-12 — the decision layer is filled in.** Laya is identified as
  **github.com/receptron/laya** (the open-source, Jev-compatible System-1 decision model,
  ONNX Runtime) and integrated as the **preferred local-first decision provider**, with
  Jev as the fallback (see `harness/laya.py`, `harness/decisions.py`). This resolves the
  earlier 'Laya unavailable' blocker in section 4.
- **2026-10-12 — runtime input harness.** Loki can now drive a running scene: inject a
  timed input sequence, hold each press for at least two physics frames, and report what
  the game actually received, with a screenshot (`harness/loki_probe.gd`, `probe_scene`).
- **2026-10-12 — Loki becomes a standalone desktop app.** The owner's direction: Loki is
  no longer a Godot product. It ships as its own app (`app/loki_app.py` + `app/ui/`,
  `Loki.app` on macOS) over the same engine (`addons/loki/loki_bridge.py` +
  `harness/`), which now runs without Godot. Godot becomes one optional creative
  adapter among several (Blender, Unreal, ...), active only when the workspace is a
  Godot project. Supersedes AD-1; see AD-10.
- **Ongoing — prepared upstream contributions.** Improvements to third-party
  dependencies are prepared as patches under `contrib/<project>/` with a README. Opening
  a fork or pull request is an externally visible action and requires explicit
  authorization; the patch is the deliverable until then.

---

## 1. Principles

- **Preserve working functionality.** Build from the existing codebase; do not rewrite
  it to match a preferred architecture.
- **Least privilege.** Ordinary, reversible development work is authorized inside the
  workspace. Destructive, financial, externally visible, publishing, or irreversible
  operations require explicit authorization.
- **Evidence over claims.** Never report a tool, model, API, integration, or test as
  working unless it was actually run and passed. Source files existing is not evidence.
- **Boundaries are part of the design.** Filesystem, subprocess, network, credential,
  plugin-loading, and agent-loop boundaries are audited and enforced explicitly.
- **Local-first.** Mirrors are not needed. Keep user data (keys, memory) out of the
  shipped addon.
- **English only.** Everything Loki produces, and every artefact in the repo, is written
  in English.

---

## 2. First task: audit the existing project

Before designing changes, inspect the actual codebase: directory tree and entry points;
language/framework/dependency manifests; the request lifecycle from input to model
invocation and response; agent orchestration and tool execution; model-provider
implementations; the Jev decision integration and its real execution path; Laya's
availability; memory and persistence; MCP and plugin integrations; git/repo tooling;
Godot and other creative-tool integrations; configuration/credential/secret handling;
filesystem and subprocess access; network access; tests, docs, and known failures;
incomplete features and duplicated abstractions.

If `addons/loki/harness/jev.py` exists, inspect it and trace how its outputs are
consumed. If it does not, record that finding rather than assuming. Run the existing
test suite if practical and safe, and record the exact commands and results.

The audit results live in `docs/architecture/CURRENT_STATE.md`; the durable documents
this task must produce are listed in section 12.

---

## 3. Core architecture

A modular architecture with clearly defined interfaces. Keep orchestration, policy
enforcement, model providers, skills, tools, memory, APIs, and creative integrations
separate. Use the existing language and framework unless there is a demonstrated reason
to change — do **not** rewrite Loki in C++ because native code might be faster.

**3.1 Loki Core** manages application lifecycle, UI, projects/workspaces, task creation
and status, context preparation, agent orchestration, capability discovery, permission
checks, event handling, configuration, observability, and recovery. External providers
must not be embedded in the core.

**3.2 Standard capability interfaces** — where appropriate, common interfaces for model
providers, decision providers, agents, skills, tools, memory providers, knowledge
providers, API connectors, repository providers, worker computers, artifact providers,
evaluation providers, and security scanners. Use structured input/output schemas,
explicit error types, timeouts, cancellation, and validation. Adopt MCP, OpenAPI, and
established skill formats where they solve a real interoperability problem; do not
invent redundant protocols.

**3.3 Capability lifecycle.** Each capability has a unique id, name/description,
type/version, interface and I/O schema, source/provenance, license, dependency and
compatibility requirements, requested permissions, credential requirements, health,
verification status, tests, enablement state, and disable/removal procedure. Keep the
distinctions between **discovered, reviewed, installed, enabled, and verified**. A
repository being listed must not make its code executable.

---

## 4. Jev and Laya integration

Jev and Laya must participate in the real request pipeline. First determine what they
actually are, where their source lives, how they communicate, what they return, and what
is already implemented. Do not invent APIs or pretend to connect unavailable systems. If
an interface is unavailable, create a documented adapter contract and a mock provider.

**4.1 Required request flow**

User request → request normalization → project and memory context retrieval → Jev/Laya
decision preflight → planning → capability selection → independent permission
enforcement → model and tool execution → verification → memory and audit updates → user
response. Keep the flow configurable so simple tasks bypass unnecessary overhead.

**4.2 Decision responsibilities** (only what is supported and testable): intent
classification, task-complexity estimation, ambiguity detection, missing-context
identification, workflow selection, tool/capability recommendations, plan
recommendations, risk classification, loop detection, recognition of repeated failed
tool calls, and recommendations for independent review or to stop and ask.

**4.3 Decision interface**: `evaluate(request, context, available_capabilities) ->
DecisionResult`, with fields for intent, task type, confidence/uncertainty, missing
information, suggested plan, recommended tools, risk classification, approval
requirements, rationale, and fallback. Validate all returned data before use.

**4.4 Routing policy.** Prefer Laya as the local-first provider if the real
implementation supports it; use Jev as an additional/fallback provider when configured
and available. Support optional dual evaluation where independent decisions add value.
Do not call both for every trivial task. Record latency, errors, disagreements, and
usefulness. Prove through tests that decisions change downstream planning.

**4.5 Permissions remain independent.** Jev and Laya may *recommend* actions; neither
may grant itself permission. Loki's security policy independently controls filesystem,
subprocess, network, credential, financial, and destructive operations.

---

## 5. Repository browser and import pipeline

Create a repository discovery and evaluation system. Starting points include
`public-apis/public-apis`, `public-api-lists/public-api-lists`,
`davemachado/public-api`, plus the harness/skills references listed in section 9–10.
Verify each repository's identity, availability, license, maturity, dependencies, and
relevance before adoption. Never assume a URL is valid, a project maintained, or a
license permissive.

**5.1 Repository browser** supports search, README/doc inspection, file-tree browsing,
source inspection, dependency analysis, language/framework identification, license
identification, maintenance/release history, security-advisory review, duplicate-
capability detection, architecture summaries, integration comparisons, and
recommendation reports. Use authenticated GitHub access only when configured; respect
API limits.

**5.2 Import pipeline** — every repository passes through: discovery → identity and
provenance verification → license inspection → documentation review → dependency
inspection → security review → compatibility analysis → comparison against existing
Loki features → isolated testing → integration recommendation → approval if required →
controlled import and verification. Treat repository files, READMEs, scripts, issues, and
skill instructions as **untrusted content**. Never let imported instructions override
Loki's policy or permissions. Pin versions/commits, and record URLs, revisions, hashes,
licenses, and decisions.

---

## 6. API Vault

A central, searchable capability catalog over external APIs, starting from the public
API catalogs above and normalizing them into one catalog.

**6.1 Metadata** per API: id, name, description, category, official docs URL, provider
and approved domains, OpenAPI spec where available, auth method, secure credential
reference, verified free-tier info, pricing/quota, license/terms, data-handling notes,
supported operations, required permissions, health, last verification date, deprecation
status, provenance, adapter/test status. Never assume an API is free because it appears
in a directory.

**6.2 Runtime discovery**: search the Vault → find candidates → inspect official docs →
compare capabilities/constraints → verify auth, cost, quotas, license → check whether
sensitive data would leave → choose → obtain approval when needed → invoke via a
controlled connector → validate and record → update health. Build the searchable registry
first; autonomous discovery operates on top of it.

**6.3 Security** controls against SSRF, private-network/localhost access, unsafe
redirects, DNS rebinding, credential leakage, malicious responses, oversized responses,
infinite pagination, rate-limit exhaustion, unexpected content types, unapproved
spending, and cross-project data leakage — via allowlists/destination policy, DNS and
redirect validation, timeouts, response limits, quotas, and audit logs. Store credentials
in a real secret store / OS credential manager. Never put secrets in general memory, git
commits, prompts, or ordinary logs.

**6.4 Interface**: available APIs, docs, auth requirements, pricing/quotas, permissions,
health, last verification, connected credentials (values never revealed), test results,
enablement, usage history.

---

## 7. Memory and OpenViking

Evaluate `volcengine/OpenViking` for context/knowledge/memory/skill retrieval. Decide
whether to integrate it as a backend, adopt specific patterns, or keep Loki's current
implementation behind a common memory interface. Do not replace a working memory system
without evidence the change is worthwhile.

**7.1 Categories**: user-approved preferences; project requirements; architecture
decisions; current implementation state; task history; verified lessons; research and
knowledge documents; skills and versions; capability metadata; temporary context;
operational audit records.

**7.2 Functionality**: search/retrieval, provenance, project isolation, deduplication,
contradiction detection, staleness tracking, confidence/verification status,
summarization, explicit updates, user inspection and correction, deletion/retention
policy, backup and restoration. Never confuse an inference with a verified fact; never
store secrets in general memory; retrieve context progressively rather than dumping whole
projects into every call.

**7.3 Resumable project state** records objective, current phase, completed work, files
changed, tests and results, known failures, open issues, decisions, blockers, and next
actions — updated after meaningful milestones.

---

## 8. Agent skills

Evaluate `anthropics/skills` and the harness-engineering catalogs; discover other
reputable skills. Cover software engineering, repository research, code review, testing,
scientific research, statistics, data visualization, cybersecurity defense, diagramming,
UI/visual design, technical documentation, game development, Blender/3D, automation, API
integration, and deployment/operations. Do not assume a skill is present — inspect it.

**8.1 Skill architecture**: unique id, version/source, purpose, applicable task types,
I/O expectations, dependencies, required tools, permissions, trust status, tests,
compatibility. Load skills only when relevant; keep instructions separate from executable
tools. Skills cannot override policy, grant permissions, access unapproved secrets, or
bypass tool restrictions.

**8.2 Scientific skills**: source discovery, evidence synthesis, citation verification,
reproducible analysis, experimental planning, statistical checks, research reports.
Distinguish evidence from hypothesis; never fabricate sources or claim experiments were
run.

**8.3 Cybersecurity skills** (defensive): authorized code review, threat modeling,
dependency analysis, secret detection, secure configuration, vulnerability remediation,
isolated testing. Require explicit scope/authorization for active scanning; never give a
skill unrestricted access to attack external systems.

**8.4 Diagramming and design**: architecture/sequence/flow/data-flow/ER diagrams, state
machines, wireframes, technical visuals. Prefer editable outputs (Mermaid, SVG,
application-native). Verify diagrams render where possible.

---

## 9. Agent substrate and multi-agent execution

Investigate the exact identity of the user's "agent substrate" reference before deciding
what to integrate — do not invent a repository from an ambiguous name. Build or
strengthen a common agent runtime with roles such as planner, researcher, repository
analyst, software engineer, test engineer, security reviewer, creative director,
scientific analyst, game-dev specialist, documentation writer, and independent verifier —
using shared interfaces, not a separate application per role.

**9.1 Orchestration**: task graphs, dependencies, bounded parallelism, shared project
state, structured handoffs, separate working contexts, checkpoints, cancellation, retry
policies, timeouts, failure isolation, result aggregation, independent review. Avoid
endless delegation loops. Prevent agents overwriting each other (file ownership or
isolated branches/worktrees). Require integration tests before combining parallel
changes. Use multiple agents only when they offer a measurable advantage.

---

## 10. Local models and computer workers

Design for the real environment (e.g. an Apple-silicon Mac as coordinator, GPU machines
as inference/specialist workers). Inspect actual hardware, software, and network before
configuring workloads. Do not assume any machine is always online.

**10.1 Worker capabilities**: registration, authentication, heartbeats, health checks,
capacity reporting, model capability discovery, task queues, timeouts, cancellation,
result validation, reconnection, failure recovery. Use authenticated/encrypted
connections; never expose inference or tool-execution publicly without a reviewed design.

**10.2 Model providers and routing**: investigate local runtimes (Ollama, llama.cpp);
keep a common provider interface; track id/revision, provider, context window, hardware
requirements, quantization, tool-calling, vision/multimodal, latency, availability,
privacy, cost, evaluation results. Route by complexity, capability, hardware, privacy,
latency, and budget. Never assume models are equally capable. Support local-only
operation where practical.

**10.3 Named model references** (e.g. a requested "Opus 5.5"): verify current
availability, real identifiers, provider docs, API access, and pricing. Do not invent a
model id or claim availability. Build an adapter when supported and appropriate. Remote
use follows configured privacy rules and cost controls.

---

## 11. Harness engineering references

Evaluate the DeepSeek harness and the awesome-harness-engineering catalogs; extract
patterns for agent execution, tool management, context preparation, memory, session
state, task scheduling, evaluation, plugin architecture, error recovery, and
observability. Compare with Loki's architecture and write a brief comparison before
adopting major components. Do not integrate several frameworks that solve the same
problem without a specific, measured reason.

---

## 12. Creative and game development

Support serious software and creative workflows. Preserve useful existing Godot tools;
plan adapters for Godot, Unreal Engine 5, Blender, game-project inspection, code and
scene editing, asset management, procedural generation, import validation, build/test
automation, and creative artifact management. Keep game-specific logic out of Loki Core.

**12.1 Game-dev workflow**: inspect project and engine version → read scripts/scenes/
assets/config → understand conventions → plan the smallest useful change → edit the
correct files → run available checks → launch builds/tools when supported → capture logs
and failures → bounded repair iterations → report what changed and was verified. Do not
claim a project builds unless the build was actually run.

**12.2 Asset provenance**: track source, licensing, dependencies, import settings, and
project use. Do not silently include assets with unclear redistribution rights. Preserve
editable source files where practical.

---

## 13. External providers (optional)

Apply one provider pattern to image/video/audio/3D-generation services and hosted
platforms: authentication, capability discovery, job submission, job status, result
retrieval, error handling, quotas/cost, artifact storage, provenance, and permission
controls. If no appropriate public interface exists, document the limitation and provide
a supported manual workflow — **never invent endpoints or automate private interfaces
without authorization**. Candidate services to evaluate: Higgsfield, Supabase (Postgres
persistence, auth, sync, object metadata, realtime), Cloudflare (Workers, R2, Access,
Tunnels, DNS, Queues), and commerce/neobanking platforms (Whop and the intended
neobanking provider). Keep core functionality local-only; use scoped credentials, RLS,
and migrations; never commit secrets; start financial integrations read-only/sandbox;
never move money without explicit authorization and confirmation; never claim regulatory
compliance; build a documented stub when credentials are missing.

---

## 14. Additional system capabilities

Project-aware context (retrieve relevant files/config/tests/docs/decisions automatically;
never load whole repos); search (full-text, source, symbol-aware, optional semantic —
always return paths and evidence); reusable workflows (research a repo, evaluate a
dependency, integrate an API, implement a feature, fix a bug, review security, produce
diagrams, scientific research, build a game feature, resume a project, prepare a
release); a capability marketplace view (local/remote/not-installed/needs-credentials/
needs-approval/experimental/disabled/unavailable/rejected); artifact management with
provenance; cost and resource management with configurable limits; offline operation with
graceful degradation; and backup/migration with documented recovery.

---

## 15. Security and execution policy

Security is a core architectural requirement. Audit filesystem access, subprocesses,
network access, plugin loading, dependency installation, secrets, and agent loops. If
existing tools use unrestricted shell execution, replace or constrain it with structured
argument execution and explicit command policies. Inspect path handling for traversal,
arbitrary absolute paths, symlink escapes, and workspace violations. Use least privilege.

**15.1 Permission classes**: reading project files, writing project files, running tests,
executing approved commands, network access, using specific credentials, invoking paid
services, publishing/deploying, modifying infrastructure, deleting/overwriting data.
Authorization covers ordinary reversible development work inside the confirmed
workspace; it does not cover deleting unrelated files, destructive disk operations,
exfiltrating secrets, publishing private code, deploying publicly, spending money,
financial transactions, modifying unrelated repositories, changing OS security settings,
accessing another person's machine, or bypassing access controls.

**15.2 Supply-chain protection**: before executing external code, inspect its source and
license, inspect install scripts and dependencies, use isolated environments, apply
static checks, restrict filesystem/network access, record revision/provenance, and test
before enabling it in the main workflow. Imported skills and repositories are untrusted
until reviewed.

---

## 16. Testing and verification

Establish a repeatable quality framework. Track task completion, test pass rate, correct
tool selection, decision-provider usefulness, memory retrieval quality, citation
accuracy, recovery behavior, loop prevention, latency, cost, worker utilization,
permission enforcement, and regression frequency. Test ordinary questions, code
modifications, repository inspection, API discovery, decision-provider failures, missing
models, worker disconnections, malicious skill instructions, unsafe paths, secret-leak
attempts, invalid tool responses, conflicting agent edits, cancellation, and recovery.
Use mocks for deterministic local testing; keep external-service integration tests
separate from unit tests. Never report a feature as verified merely because its source
files exist.

---

## 17. Implementation roadmap

Execute in stages; reorder only when the repository provides a clear reason. Each phase
has explicit acceptance criteria. Do not attempt one enormous patch.

- **Phase 0 — Locate and audit.** Find Loki; confirm the active checkout; inspect the
  working tree; map the architecture; run baseline tests; identify security issues;
  verify the Jev/Laya implementations; create durable documentation.
- **Phase 1 — Safety and reliability.** Harden filesystem boundaries; review shell and
  subprocess execution; add explicit permissions; improve timeouts and structured errors;
  add checkpoints and recovery; test security boundaries.
- **Phase 2 — Jev/Laya.** Implement the decision interface; connect available providers;
  integrate outputs into the real request path; add fallback and disagreement handling;
  add tests and traces.
- **Phase 3 — Capability registry and repository browser.** Capability manifests;
  repository discovery and inspection; provenance and license checks; isolated staging;
  integration evaluation reports.
- **Phase 4 — API Vault.** Import selected catalogs; normalize metadata; connector
  interfaces; secure credentials and outbound policy; search, testing, health monitoring.
- **Phase 5 — Memory.** Evaluate OpenViking; strengthen project-scoped memory; add
  provenance and retrieval; resumable project state; test recovery.
- **Phase 6 — Skills and multi-agent runtime.** Review and import useful skills;
  specialist agents; bounded task graphs; isolated work areas; independent verification.
- **Phase 7 — Distributed local models.** Worker registration and health checks;
  capability-aware routing; authenticated communication; failure/reconnection tests.
- **Phase 8 — Creative and external integrations.** Improve Godot support; evaluate
  Unreal/Blender; investigate Higgsfield; evaluate Supabase/Cloudflare; investigate Whop
  and the intended financial provider; add other justified providers.
- **Phase 9 — User experience and operations.** Capability management; execution traces;
  better configuration; cost/resource reporting; finish documentation; regression and
  security suites; verify backup and restore.

---

## 18. Autonomous working rules

Ordinary, reversible engineering decisions inside the confirmed workspace are authorized
— do not ask approval for every file edit or routine test. Before risky changes, create a
checkpoint or branch. Do not overwrite existing user modifications. Do not delete
unfamiliar code. Do not install every repository in an index. Do not expose credentials.
Do not execute unreviewed code with unrestricted privileges. Do not claim a
model/API/integration works without evidence. Do not report tests as passing unless they
were run. Do not bypass OS or application permissions. Do not perform destructive,
financial, externally visible, or irreversible operations without authorization. When
one integration is blocked, continue independent tasks. Prefer small changes, useful
tests, clear documentation, and repeatable workflows. If an implementation fails, inspect
the failure, update the plan, and recover without concealing the problem.

---

## 19. Permanent project continuity

Maintain these files inside the repository. Keep the blueprint as the permanent reference
and update the others as work progresses.

| Document | Purpose |
| --- | --- |
| `docs/LOKI_MASTER_BLUEPRINT.md` | The permanent architectural vision and rules (this file). |
| `docs/architecture/CURRENT_STATE.md` | What the codebase actually is today (the audit). |
| `docs/architecture/TARGET_ARCHITECTURE.md` | The target component model and interfaces. |
| `docs/roadmap/IMPLEMENTATION_PLAN.md` | Milestones, status, acceptance criteria, next actions. |
| `docs/integrations/INTEGRATION_REGISTRY.md` | Repositories, providers, APIs, skills, licenses, status. |
| `docs/decisions/ARCHITECTURE_DECISIONS.md` | Important design decisions and reasons. |
| `docs/operations/RECOVERY_AND_RESUME.md` | How to recover work and resume after interruption. |
| `docs/operations/SESSION_LOG.md` | Concise dated records of meaningful work. |
| `docs/security/SECURITY_BASELINE.md` | Security controls, known issues, remediation status. |

**At the start of each session**: read the blueprint, the roadmap, the recovery state,
and recent session notes; check git and the current implementation state.

**At the end of each meaningful session**, record work completed, files changed, tests
executed with exact results, known issues, remaining tasks, blockers, and next concrete
actions.