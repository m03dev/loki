# How the big agent systems are built (research, 2026-10-28)

What LOKI's agent system (docs/AGENT_SYSTEM.md) copies, and where it comes from. Paraphrased notes; read the sources
for the details.

## Orchestration and delegation

- **Anthropic, multi-agent research system.** A lead agent plans, saves the plan outside its context, starts 3-5
  workers in parallel and combines what they return. Every delegated task needs an objective, an output format, the
  tools to use and its boundaries - vague tasks made workers duplicate each other. Effort is written into the prompt
  (1 worker for a fact, 2-4 for a comparison, more only for big work); early versions started 50 workers for simple
  questions. Multi-agent runs use about 15x the tokens of a chat. Workers return summaries or file references, not
  transcripts. https://www.anthropic.com/engineering/multi-agent-research-system
- **Anthropic, building effective agents / long-running harnesses.** Orchestrator-workers (subtasks decided at run
  time) and evaluator-optimizer (a critic loop, only where criteria are clear). Long runs keep a progress log and a
  feature list where a feature only passes after an end-to-end check.
  https://www.anthropic.com/engineering/building-effective-agents,
  https://anthropic.com/engineering/effective-harnesses-for-long-running-agents
- **Magentic-One (Microsoft).** Outer loop: a task ledger (given facts, facts to look up, to derive, guesses) and a
  plan. Inner loop: a progress ledger every turn (satisfied? looping? progressing? who next? what instruction?). A
  stall counter; past 2 it reflects, rewrites the facts and re-plans. Most common failure: repeating the same
  inefficient action. https://arxiv.org/abs/2411.04468
- **OpenAI Agents SDK.** Handoffs (the specialist takes over) vs agents-as-tools (the manager stays in charge); input /
  output / tool guardrails with tripwires; max_turns. https://openai.github.io/openai-agents-python/running_agents
- **Google ADK / A2A.** Sequential / Parallel / Loop agents; a loop never stops by itself - a max or an exit tool.
  A2A's task states include `input-required` (a clarifying question parks the task). https://adk.dev/agents/workflow-agents/loop-agents/
- **LangGraph.** Plan-and-execute with a re-planner that only plans the remaining steps; interrupts need a checkpointer
  and re-run the interrupted node on resume. https://docs.langchain.com/oss/python/langgraph/interrupts
- **OpenHands.** Stuck detection without a model (same action + observation 4x, same error 3x, monologue, A/B loops);
  condensers summarise old events. https://docs.openhands.dev/sdk/guides/agent-stuck-detector
- **Cognition (2026).** A reviewer with clean context finds real bugs; review notes must be held against the user's
  instructions; parallel writers make conflicting choices - keep writes single-threaded.
  https://cognition.com/blog/multi-agents-working

## Interviews and send-backs

- **Claude AskUserQuestion:** 1-4 questions, a header of 12 characters, 2-4 options with descriptions, multi-select,
  "Other" as free text; only the top-level agent asks. https://code.claude.com/docs/en/agent-sdk/user-input
- **ChatGPT deep research:** clarify -> rewrite the request -> research. https://cobusgreyling.substack.com/p/openai-api-deep-research
- **Cursor plan mode:** research, ask, then an editable plan. https://cursor.com/blog/plan-mode

## Context, memory, tools, playbooks

- **Manus:** keep the prompt prefix stable (KV cache), append only, fixed key order; hide tools instead of removing
  them; the file system as memory; recite the plan (todo.md) at the end; keep errors in context.
  https://manus.im/en/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- **Anthropic context editing / memory tool / tool search:** clear old tool results past a trigger, keep the last few;
  a file-based memory; deferred tools found by BM25 or regex (accuracy up, tokens down a lot).
  https://anthropic.com/engineering/advanced-tool-use, https://www.anthropic.com/engineering/writing-tools-for-agents
- **Letta / Mem0 / Zep:** bounded core memory; ADD / UPDATE / DELETE / NOOP extraction; facts with validity times.
  https://www.arxiv.org/pdf/2504.19413, https://arxiv.org/html/2501.13956
- **ACE (Agentic Context Engineering):** playbooks as bullets with helpful / harmful counters, a reflector and a curator
  that applies small deltas in code - whole rewrites collapse the context. An independent review found the public
  code never used the counters to rank or prune and injected the whole playbook; LOKI does both.
  https://github.com/ace-agent/ace, https://zby.github.io/commonplace/agent-memory-systems/reviews/ace/
- **Dynamic Cheatsheet, ReasoningBank, Voyager:** learn from both success and failure; promote a skill only after a
  verified success. https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/
- **MCP tool annotations:** readOnlyHint, destructiveHint, idempotentHint, openWorldHint - hints for confirmation and
  retry decisions. https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/

## Guardrails, instruments, the chassis

- **Hooks:** Claude Code (PreToolUse / PostToolUse / Stop, deny > ask > allow, a timed-out pre-tool hook blocks),
  ADK callbacks and plugins. https://code.claude.com/docs/en/agent-sdk/hooks
- **Tracing:** OpenTelemetry GenAI semantic conventions (invoke_agent / chat / execute_tool spans, gen_ai.* attributes,
  message content opt-in only). https://opentelemetry.io/blog/2026/genai-observability/
- **Prompt injection:** spotlighting (mark outside text as data) cut attack success from about half to a few percent;
  CaMeL and LlamaFirewall go further. https://arxiv.org/html/2403.14720v1
- **Durable execution:** checkpoint per step, idempotent side effects, resume re-runs the interrupted step (LangGraph,
  Temporal). https://docs.langchain.com/oss/python/langgraph/persistence
