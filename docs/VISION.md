# LOKI - the owner's vision (five layers)

The owner's own description of what LOKI is becoming, kept as written (diagram text
recovered as plain text). docs/BUILD_BRIEF.md is the build order; HANDOFF.md says where the
work stands. Where this document and the code disagree, the code is the truth and this is
the direction.

I'll treat the project as five connected layers:
1. LOKI Core — reasoning, routing, permissions, tools, memory, and the agent runtime.
2. LOKI Workforce — specialized agents, vertical teams, task delegation, and cross-machine collaboration.
3. LOKI Studio floor — the home screen as a preview hub: renders, models, game projects and the farm's jobs, reflecting real system activity.
4. LOKI Bridge — integrations with Godot, Unreal Engine, Blender, Maya, Substance Painter, model providers, APIs, and external services.
5. LOKI Evolution — testing, learning from failures, controlled self-improvement, and maintaining a reliable record of what changed.
The key principle is that these should work as one coherent system, not a pile of disconnected AI tools.
Expanded LOKI project review
Here is a much more complete reconstruction of the project, including the details that were missing from the previous response. This is the content I would use as the foundation for the comprehensive LOKI reference document—not just a short project summary.
1. The original vision: what LOKI is supposed to become
LOKI is not meant to be merely a chatbot, a Godot plugin, or a collection of autonomous coding agents. The vision is a local-first AI operating system for creative work, software development, education, and business automation.
The user gives LOKI a goal. LOKI works out what the user means, chooses a plan, selects suitable models and tools, delegates work, checks results, records what happened, and presents the outcome.
The guiding workflow is:
Human direction
You set goals, priorities, boundaries and approval rules.

LOKI decision layer
Interpret, consult memory, check Laya/Jev, plan and select capabilities.

Agent teams and tools
Research, coding, creative applications, APIs and local or hosted models.

Verification and memory
Test the result, record evidence, update task status and report honestly.

LOKI should become more capable over time, but not by blindly rewriting itself. Its improvement should be measurable, reversible and subject to explicit safety policies.
The long-term goal is for you to manage outcomes rather than manually coordinate every step.
2. The current LOKI project must be preserved
This is an important part of the history that should not get lost in a broad architecture proposal.
You already have a repository:
- LOKI — existing project
- Render Studio
The existing LOKI project was described as a Godot 4 editor add-on with a chat dock, viewport, Ask/Plan/Build modes, settings, approvals, a stop control, scene and script verification tools, memory, skills, a Python bridge and model/provider integrations.
Its documented architecture reportedly includes a local Python HTTP bridge on port 8766, bearer-token authentication, a loki.py harness, Godot tools, CLI adapters such as Claude Code and Codex, optional Jev typed decisions, and MCP servers. The repository documentation also describes a substantial skills collection.
Those are claims in the existing project documentation, not results of a fresh execution test. The implementation must be audited before deciding which parts are working, incomplete, duplicated or broken.
The key rule is:
Extend the existing LOKI. Do not casually replace it with a new framework.
The audit should establish:
- Which capabilities work now.
- Which capabilities exist only in documentation or partial implementations.
- Which components are duplicated.
- Which model routes and provider integrations are functional.
- How Laya and Jev are called, and why they may be skipped.
- Whether the chat interface, Python bridge, MCP tools, memory and agent runtime share the same execution path.
- Which local changes must be preserved before any edits.
- Which tests already exist and what they actually verify.
A previous project handoff referenced 173 structural offline checks and a separate live-testing mode. These must be run and interpreted rather than treated as proof that the full system works.
3. The home screen shows real work (direction changed 2026-10-21)
LOKI is a game engine, render studio and AI farm hive. The home screen is where that work is previewed: the latest render
big, then every render, model, game project, Studio session and job on this machine or the worker farm. It shows real
system state, never decorative animation: a job's card is its real status, a render's card is its real output.
Keep the AI runtime, task coordination, permissions and provider routing independent of any view; if the window closes,
LOKI's core tasks keep running.
The Nordic LOKI identity
You also wanted a creative LOKI logo built from interlocking or repeated L-shaped geometry, with a Nordic-inspired feel. Your initial acronym idea was “Local Omni Kit for Interface.”
The design direction discussed was a midnight-navy background with cyan-to-emerald accents and angular, geometric shapes.
That should be preserved as an identity constraint. Do not redesign the existing visual language simply because a new architecture is being proposed.
4. The architecture: five layers that work together

LOKI Core
Intent interpretation, planning, decision routing, provider selection, permissions, memory, skills, tool calls, execution tracking and verification.

LOKI Workforce
Local agent teams, task queues, capability discovery, delegation, leases, handoffs, communication, worker health and cross-machine collaboration.

LOKI Studio floor
The home screen: render and project previews, status of the agents and the worker farm, activity history and visual controls.

LOKI Bridge
MCP, application adapters, APIs, provider connectors, creative software, repository inspection, file access and external services.

LOKI Evolution
Evaluations, controlled self-improvement, skill refinement, regression detection, version tracking, rollback and learning from failed tasks.

These layers need clear interfaces. Otherwise, adding another agent framework, model provider or creative application risks creating another disconnected subsystem.
5. Laya and Jev: the decision-making problem to solve first
This is your most important immediate engineering priority.
You want Laya and Jev to process prompts before the main model or a tool executes, and to be integrated into LOKI's actual chat logic rather than operating as separate, optional assistants.
The intended request pipeline is:
```
User request -> normalize and classify -> retrieve relevant memory -> Laya / Jev preflight
-> structured decision -> capability and permission checks -> plan and route
-> execute with selected models and tools -> verify result -> record events and memory
-> respond to user   (uncertain or unavailable -> defined fallback policy)
```

The decision layer should produce a structured result containing:
- Intent and task type.
- Relevant context and uncertainty.
- Missing information, if any.
- Proposed steps and dependencies.
- Required capabilities and tools.
- Candidate model or provider requirements.
- Privacy and risk classification.
- Approval requirements.
- Rationale and fallback behavior.
What needs investigating in the actual code
Do not immediately rewrite the whole chat system. First trace one real message from the UI to its final response.
Find out:
1. Where the chat request enters the runtime.
2. Where the primary model is called.
3. Where Laya is defined and invoked.
4. Where Jev is defined and invoked.
5. Whether either can be bypassed by a shortcut, alternate route or fallback.
6. Whether decisions are structured data or merely text responses.
7. Whether the tool executor actually consumes the decision.
8. What happens when Laya or Jev times out, returns invalid data or is unavailable.
9. Whether tests prove the decision layer ran before execution.
10. Whether the UI displays the same plan and execution state that the runtime actually used.
The key test is not whether Laya or Jev can answer a question. It is whether every applicable request follows the required decision path before model and tool execution.
Laya can be the local-first decision component where the actual implementation supports it. Jev can provide the intended second check or optional fallback. Their precise roles must be confirmed against the code rather than assumed.
Neither one should be able to grant itself permissions, bypass spending limits or override the security policy.
6. Model routing, local inference and free-credit management
You want LOKI to use the best available model for each job without wasting money or overwhelming the hardware.
The system needs to distinguish four different things:
- Local inference: a model runs on your own machine.
- Hosted inference: a provider runs the model and exposes an API.
- Free-tier inference: hosted use subject to quotas, rate limits, account conditions or changing availability.
- Paid inference: usage that may incur a charge and therefore requires explicit budget controls.
Hardware-aware routing
Your known environment includes a Mac mini M4 with 16 GB of memory, a Windows PC with an RTX 3070 Ti and 8 GB VRAM with 16 GB system RAM, an RTX 3070 laptop with unknown VRAM, and a school PC with an RTX 3070 Ti and 8 GB VRAM that should only be used when authorized and available.
LOKI must inspect actual hardware and current availability before deciding what can run where.
A hardware profile should record CPU, RAM, GPU, VRAM, operating system, available disk space, installed inference engines, model files, current load and worker availability. It should not assume that every machine is always connected or available.
The user has also been running smaller local Qwen models and reported that Opus 5.5 at a medium setting is smart. The provider/model inventory should preserve those observations as user feedback, while recording actual model identifiers and configurations before treating them as reproducible benchmarks.
Model selection policy
Task	Preferred routing approach
Simple classification	Cheapest suitable local or free model
Prompt normalization	Small, fast model or deterministic logic
Laya/Jev preflight	Required decision components and validated fallback
Repository research	Capable model with search and source tools
Complex coding	Strong coding model, local if sufficient or hosted within budget
Security review	Independent review and deterministic checks where possible
Creative brainstorming	Suitable creative model based on quality and cost
Verification	Tests, logs, builds and independent checks—not just another confident answer
The router should compare capability, latency, context size, privacy, reliability, quotas and cost. It should be able to reject a model that cannot meet the task's requirements.
The API Vault
This should be a real provider registry, not just a settings page full of API keys.
For every provider, track:
- Provider and endpoint.
- Supported models and capabilities.
- Authentication method and secret reference.
- Current availability and health.
- Published prices, where applicable.
- Free-tier quotas and rate limits.
- Actual usage and known credits.
- Last usage refresh and source of the data.
- Privacy and retention conditions.
- Per-task and global spending limits.
- Whether paid fallback is permitted.
Crucially, free quota, remaining prepaid credits, account balance, rate limit and actual spend are different measurements. A provider may not expose a live account balance through its API. In that case, LOKI must show the value as unknown or estimate usage from its own records rather than inventing a balance.
Your policy should include:
- No paid fallback unless explicitly authorized.
- Hard per-task and daily spending limits.
- A global stop condition when the budget is exhausted.
- No API keys in prompts, logs, repository files or screenshots.
- Provider-specific rate-limit handling.
- Clear reporting when a free service is unavailable.
7. Free inference and remote GPU/VRAM
Your question was whether agents could use remote VRAM online for free.
The answer requires an important distinction: free hosted inference is not the same as having permanent free access to a remote GPU.
Hosted APIs may offer limited free requests. Notebook services may provide temporary GPU sessions. Community infrastructure may have variable availability. These are not necessarily stable, always-on workers that LOKI can depend on.
The research section should compare:
- Free hosted model APIs.
- Free model tiers through aggregators.
- Temporary GPU notebooks.
- Open-source distributed inference.
- Self-hosted inference on your own machines.
- Optional paid GPU services, clearly separated from the free options.
Each entry should state the official URL, license or terms where relevant, platform support, eligibility, quota limitations, persistence, privacy implications and integration effort.
The sensible baseline is local-first inference with optional hosted providers behind the same interface. Free hosted services should be treated as opportunistic capacity, not guaranteed infrastructure. LOKI should never silently switch to a paid provider when a free route fails.
8. Mac and Windows working together
You want the Mac mini to help coordinate LOKI while Windows performs development and testing work. You also want each machine to be capable of running its own vertical team of agents.
That is feasible as an architecture, provided the machines communicate through a defined protocol instead of sharing ad hoc instructions.
Mac mini — coordination and local work
Task coordination, local models where appropriate, memory access, status aggregation and its own worker team.

Shared coordination protocol
Authenticated messages, task IDs, leases, artifacts, heartbeats, approvals and result verification.

Windows PC — build and test workers
Repository work, coding agents, engine builds, tests, GPU-capable inference and creative application tasks.

The Mac should not have to run every task itself, and Windows should not have to wait for the Mac to perform all its reasoning. Each host can run its own team, while shared tasks can be delegated between hosts.
Each worker should advertise capabilities such as repository.read, code.edit, godot.test, unreal.build, blender.inspect or model.local-inference. Those capabilities must be backed by actual installed tools and permissions.
The school PC is a conditional worker, not a permanent dependency. The laptop's GPU capacity should be measured rather than guessed.
Steam P2P
You specifically asked whether the machines could use Steam P2P.
The research should evaluate Steam networking and GodotSteam as a possible transport, but not assume that Steam P2P is a complete orchestration system.
A robust design would make transport replaceable, allowing Steam networking to be evaluated alongside a secured LAN connection or a private network solution. The coordination layer still needs durable task records, authentication, leases, retries, artifact tracking and recovery if a peer disappears.
Steam P2P should not be the sole source of truth for tasks or approvals. It may also impose Steamworks, application identity, account and deployment constraints that need verification.
9. Vertical agent teams and agent communication
Each machine should be able to host a team with distinct responsibilities.
A possible team structure is:
- Planner: breaks goals into bounded tasks.
- Researcher: searches repositories, documentation and references.
- Architect: proposes interfaces and integration designs.
- Coder: makes scoped code changes.
- Tester: runs tests, builds and regression checks.
- Security reviewer: examines permissions, dependencies and unsafe behavior.
- Creative specialist: operates supported game and content tools.
- Verifier: checks that the deliverable meets acceptance criteria.
- Coordinator: tracks assignments, dependencies, status and handoffs.
These are logical roles, not necessarily nine permanently running models. LOKI should create workers as needed and fit the workload to available hardware and budgets.
Common message format
All machines and agents need shared message semantics. At minimum, events should support:
- agent.status
- agent.message
- task.created
- task.assigned
- task.started
- task.blocked
- task.completed
- task.failed
- approval.required
- artifact.created
- verification.completed
Each message should include a task or correlation ID, sender, recipient, timestamp, payload type and relevant authorization context.
The Godot characters can then visualize these events. A character should not pretend to be talking to another agent unless the runtime has recorded the corresponding communication event.
10. Repository research: what to investigate and why
You asked for lots of repositories and useful resources, but the result should be a curated research catalog—not a list of projects to install indiscriminately.
The following are the strongest candidates from the research already discussed.

DeepSeek Harness
A plugin-oriented agent harness worth inspecting for architecture and extensibility. It was described as a developer preview, so compatibility and maturity need testing before adoption.

OpenViking
A context and memory system for agents, including knowledge, retrieval and skills. Its main project is AGPL-3.0 according to the research notes, so license obligations must be evaluated before incorporating it into a distributed product.

Graphiti
A candidate for temporal knowledge-graph memory. Compare it against OpenViking and LOKI's existing memory rather than adding multiple memory systems without a defined reason.

OpenHub
A candidate for multi-agent coordination, task queues, leases, verification gates, shared artifacts and approvals. Test whether it solves a real gap in LOKI before integrating it.

October Bus
An alternative for durable agent communication, task ownership, handoffs and shared context. Evaluate it against OpenHub; do not adopt both by default.

AutoHelix
A candidate for controlled code improvement using isolated worktrees, tests, constraints and bounded iterations. It is especially relevant after LOKI's decision routing and evaluation infrastructure are reliable.

EvoSkill
Relevant to learning reusable skills or refining prompts from failures and benchmarks. It complements, rather than replaces, the agent scheduler.

AgentArena
A Godot-oriented agent framework worth examining for event-driven execution, navigation, memory, tools and replayable behavior. Its compatibility and maintenance state should be verified.

OpenScreen
A screen-capture candidate for documenting development, capturing gameplay and producing progress footage. It is separate from the orchestration core.

Other candidates previously identified:
- Self-Improving Coding Agent — self-evaluation and improvement experiments; its shell-execution risks make isolation essential.
- Open Multi-Agent — self-hosted multi-agent runtime.
- Cotal — agent coordination concepts and shared work queues.
- GodotWebSocketMultiplayer — Godot networking, not a complete agent runtime.
- GDLlama — a local llama.cpp bridge for Godot; assess engine compatibility and whether model inference belongs outside the UI process.
- Synapse Messenger — local-first agent messaging and coordination.
- Paperclip — agent organization and task orchestration.
- Anthropic Skills — a source of skill design patterns.
- Awesome Harness Engineering and another harness catalog — discovery sources, not proof that every listed project is safe or maintained.
- Public APIs, Public API Lists and davemachado/public-api — API discovery resources.
For every repository, the final reference should record the exact repository URL, license, last meaningful activity, platform compatibility, prerequisites, maintenance status, security concerns, integration effort, what to reuse, and whether to adopt, adapt, defer or reject it.
A repository appearing in this list is a research candidate, not a recommendation to install it automatically.
11. Creative application bridges and MCP
You want LOKI to operate across creative software rather than being trapped in a single engine.
The integration inventory should cover:
Application	What LOKI should eventually be able to do
Godot	Inspect scenes, edit scripts, run projects, collect errors and test gameplay in the owner's projects.
Unreal Engine 5	Inspect projects, edit supported assets and code, trigger builds and tests, inspect logs and verify results.
Blender	Inspect and manipulate scenes, create or edit models, use scripts, render and verify output.
Maya	Inspect and operate supported scenes, use licensed software and its available scripting or integration interfaces.
Substance 3D Painter	Work with supported project and asset workflows, materials, textures and exports.
Unity	Explore the official AI/MCP integration path and compatible editor packages.
Image and video tools	Generate or edit assets, capture outputs and maintain provenance.
Git and code-hosting services	Inspect changes, create branches, run checks, prepare commits and require approval for sensitive publishing actions.
Relevant starting points include the official Unity AI/MCP getting-started article, Unity AI, and GDLlama.
The final document should research the current official or maintained community integrations for each application. It must distinguish official integrations, third-party MCP servers, ordinary scripting interfaces and experimental adapters. They are not interchangeable.
Maya and Substance Painter should not be represented as free software. The integration can use an existing licensed installation where available.
One common creative-tool interface
LOKI should define common operations such as:
- Inspect project or scene.
- List objects and resources.
- Read relevant source or properties.
- Propose a change.
- Apply a scoped edit.
- Execute or render.
- Run tests or validate the output.
- Capture logs and artifacts.
- Revert the change where possible.
Each application adapter translates those operations into its own tools. That lets LOKI reuse its decision, approval and verification logic instead of building a separate AI brain for every program.
12. Memory, Obsidian and the knowledge graph
You want persistent memory that makes the system more coherent over time and can be explored visually.
The existing project memory should be audited first. Then LOKI can establish a consistent memory interface so that the storage backend can change without rewriting every agent.
Potential memory categories:
- User preferences and project constraints.
- Project architecture and decisions.
- Repository and dependency inventory.
- Skills and capabilities.
- Task history and artifacts.
- Provider performance and actual usage.
- Failures, fixes and regression cases.
- Research sources and provenance.
- Agent relationships and handoffs.
- Pending questions and blocked tasks.
Obsidian should provide a human-readable Markdown knowledge vault with YAML metadata and linked notes. The runtime must continue functioning if Obsidian is closed; Obsidian is a viewer and editor, not a mandatory database server.
OpenViking and Graphiti should be compared with the current memory implementation using the same representative tasks. The evaluation should consider retrieval accuracy, persistence, ease of backup, complexity, license and whether the extra infrastructure solves a demonstrated problem.
13. Skills and repository intake
LOKI needs a system for discovering and using external skills, APIs, MCP servers and repositories without blindly trusting them.
Each skill should carry metadata for:
- Source and version.
- Purpose and capabilities.
- Dependencies.
- Required tools and permissions.
- Trust classification.
- Supported platforms.
- Installation and update procedure.
- Tests and verification evidence.
A skill must not be allowed to override LOKI's security policy just because it claims to be an agent instruction or system prompt.
The repository intake workflow should be:
1. Record the canonical URL and revision.
2. Check license, provenance and dependency requirements.
3. Inspect install scripts, build scripts, permissions and network access.
4. Compare existing capabilities before adding another implementation.
5. Run static checks and isolated tests where appropriate.
6. Document the components worth reusing.
7. Decide to adopt, adapt, defer or reject.
8. Pin the chosen revision and record attribution.
9. Add regression tests for the integrated behavior.
Repository content, readmes, issues, agent instructions and downloaded skills must be treated as untrusted input. They cannot silently grant themselves authority to access secrets or execute privileged actions.
14. Security and the API Vault
Security should be a foundational subsystem, not a later polish task.
The implementation needs explicit controls for:
- Secret storage and redaction.
- File access boundaries and path traversal.
- Symbolic links and absolute paths.
- Shell command execution.
- Network destinations and private-network access.
- Server-side request forgery and DNS rebinding.
- Untrusted dependencies and install scripts.
- Prompt injection from repositories, websites and tool output.
- Resource exhaustion, retries and rate limits.
- Large payloads, timeouts and runaway workers.
- Audit logs and approval history.
- Local bridge authentication and network exposure.
Paid actions, destructive edits, publishing, deployment, credential access and sensitive external actions should require the appropriate approval.
The existing bridge on port 8766 must not be exposed publicly without strong authentication, narrow permissions and a reviewed deployment design.
LOKI should separate the model's proposed action from the policy engine's authorization. A model can recommend an action, but only the runtime's permission system can authorize it.
15. Hosting, APIs, publishing and the business side
You also wanted the research to cover free or low-cost hosting, public APIs, GitHub, itch.io, Gumroad, Supabase and Cloudflare.
These belong in the same research catalog but serve different purposes.
Service or category	Potential purpose	What needs checking
GitHub	Source control, releases, issues and project documentation	Repository visibility, actions limits, permissions and secret handling
GitHub Pages	Static documentation or a public project website	Static-site limits; it does not run a persistent LOKI backend
Vercel / Netlify	Website hosting and supported serverless functionality	Current free-plan limits, usage rules and function restrictions
Cloudflare	DNS, static hosting, selected serverless services and secure connectivity options	Current free limits, service-specific terms and network exposure
Supabase	Potential hosted database, authentication or synchronization	Free-plan limits, data access controls and whether cloud storage is necessary
Render	Hosting supported web services	Free-instance availability, sleep behavior and resource limits
itch.io	Publishing game builds and creative projects	Distribution terms, payment settings and project configuration
Gumroad	Selling digital products and assets	Current fees, payment terms and product requirements
Public API directories	Discovering external capabilities	Licensing, authentication, quotas, data quality and service reliability
Official starting points already identified include Vercel's limits documentation, Unity AI, and the OpenRouter pricing page.
Current terms and prices must be rechecked before the final document presents them as facts. Free hosting is not the same as a free, always-on machine capable of running LOKI's full agent runtime.
The local-first default should be that sensitive inference, files and tool execution remain on your own machines unless you explicitly enable an external service. Public websites should not directly expose the local LOKI bridge.
16. Business and education capabilities
Your vision extends beyond using LOKI to write code. The business side includes a workforce that can help operate services and develop new creative products.
The service ideas recorded in the master prompt were:
- AI Agent Factory — build agents and automation workflows.
- AI Agent Audit — assess existing agents, integrations and workflows.
- Creative Backend — help manage production workflows and creative software.
- Short-Form Drama Engine — support a pipeline for producing short dramatic content.
- Local AI Setup — help users install and configure local-first AI systems.
The educational side includes game development using Godot, Unity, Unreal Engine and Blender. LOKI should eventually be able to support learning, guide a student through a project, capture milestones, help maintain a portfolio and prepare social progress posts for review.
The business system should remain modular. These service lines should not distract from fixing the core decision pipeline first.
17. Capturing work and proving results
LOKI needs to know not only that a tool returned a response, but whether the intended work actually happened.
The capture layer should support:
- Screenshots and screen recordings.
- Application and console logs.
- Gameplay and build captures.
- Before-and-after comparisons.
- Test results.
- Generated assets and artifacts.
- Portfolio-ready progress evidence.
- Draft social posts and progress summaries.
OpenScreen was identified as a potential capture tool. It should be evaluated for the desired workflow and platform rather than installed without testing.
The system should distinguish between a model claims it succeeded and a verifiable artifact proves it succeeded. For example, a coding agent should not report that a Godot project builds until the appropriate build or test was actually run and the result recorded.
18. Controlled autonomous improvement
You want LOKI to improve itself, learn from failures, improve its harness and work autonomously over time.
That is a central feature, but it needs a bounded process:
```
observe failure or weakness -> measurable hypothesis -> isolated worktree or branch
-> one scoped change -> baseline and regression tests -> compare results and resource use
-> passes acceptance criteria? yes: record evidence, propose integration, approval where
   required, merge and record version; no: reject or revise within budget, store the lesson
```

Every improvement experiment should have a maximum iteration count, time budget, token or financial budget, defined tests and a rollback path.
The system should protect its policy engine, evaluator, permission checks, secrets handling and merge logic from uncontrolled self-modification. Changes to those areas require stricter review.
AutoHelix and EvoSkill are relevant candidates for parts of this process, but they should not be wired into LOKI until the current codebase has reliable tests and a clear definition of what constitutes improvement.
19. Evaluations and the project dashboard
LOKI needs a consistent evaluation suite, not a collection of ad hoc demonstrations.
The suite should test at least:
- Basic question and answer routing.
- Laya/Jev preflight on every applicable request.
- Missing-context handling.
- Provider failure and fallback behavior.
- Free-quota exhaustion and spending limits.
- Repository analysis and feature implementation.
- Bug fixing and regression prevention.
- Malicious skill and prompt-injection handling.
- Unsafe file paths and commands.
- Approval enforcement.
- Multi-machine disconnection and task recovery.
- Build and test verification.
- Memory retrieval and task resumption.
- Creative-tool integration where available.
Record success rate, latency, cost, model used, errors, retries, test results and relevant resource usage.
The dashboard should display task status, workers, models, integrations, API Vault health, pending approvals, security events, recent evaluations, milestones and the next actionable tasks.
The status vocabulary in the master prompt is useful and should be preserved:
Proposed → Investigating → Blocked / Implementing → Implemented → Tested → Verified
Deprecated should be available for retired capabilities.
20. The implementation order
The full vision is large. The project needs a deliberate sequence so that each stage improves the next instead of creating more disconnected parts.
1. Locate and audit the real checkout. Identify the active branch, local changes, working integrations and test coverage. Preserve work on both machines.
2. Stabilize the existing LOKI core. Establish a known-good baseline and recovery procedure.
3. Fix Laya/Jev orchestration. Trace and test the complete request path before adding more features.
4. Fix model routing and usage accounting. Centralize model selection, provider health, quotas, credits and hard spending controls.
5. Standardize capabilities and tool calls. Make every integration expose explicit capabilities, permissions and verification results.
6. Build the provider and API Vault. Add clear health, usage and policy reporting.
7. Unify memory and skills. Integrate the existing system first, then compare external candidates.
8. Establish task coordination. Add worker registration, task ownership, leases, handoffs, checkpoints and recovery.
9. Connect Mac and Windows. Start with one real task dispatched to the other machine and verified end-to-end.
10. Show real work on the home screen: renders, projects and the farm's jobs from genuine runtime state.
11. Expand creative adapters. Prioritize the tools that work reliably and are most useful to the project.
12. Add controlled improvement. Use isolated experiments and evaluation results to accept or reject changes.
13. Expand the research, dashboard and business layers. Add more capabilities once the core path is dependable.
21. What the final comprehensive document still needs
This is the fuller project reconstruction. It is still not the finished research deliverable you originally requested.
The complete document should also include:
- The exact text of LOKI — MASTER BUILD PROMPT v2, preserved verbatim rather than paraphrased.
- A full repository catalog with precise links, licenses, activity and adoption recommendations.
- A current comparison of free inference options and actual provider quota visibility.
- Current hosting and publishing terms.
- Current Godot, Unreal, Blender, Maya and Substance Painter bridge options.
- A proper Steam P2P versus private-network versus LAN comparison.
- A complete API and capability inventory.
- A list of confirmed facts versus unverified repository claims.
- Acceptance criteria and tests for each implementation phase.
- A recovery and rollback procedure.
- A clear list of immediate next actions for Claude Code or another coding agent working in the actual checkout.
