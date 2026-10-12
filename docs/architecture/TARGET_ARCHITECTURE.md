# Loki — Target Architecture

The component model the existing code grows toward. It is deliberately close to what is
already built, so most work is additive.

```
                 ┌───────────────────────────────────────────────┐
                 │                   Loki Core                    │
                 │  lifecycle · UI · projects · tasks · context   │
                 │  orchestration · discovery · policy · events   │
                 │  configuration · observability · recovery      │
                 └───────────────┬───────────────────────────────┘
                                 │  capability interfaces
     ┌───────────────┬───────────┼───────────┬───────────────┬───────────────┐
     ▼               ▼           ▼           ▼               ▼               ▼
 Model          Decision     Agent        Skill          Memory         Capability
 providers      providers    runtime      registry       providers      registry
 (local+cloud)  (Jev/Laya)   (roles)      (SKILL.md)     (facts,state)  (tools,APIs)
     │               │           │           │               │               │
     └───────────────┴───────────┴───────────┴───────────────┴───────────────┘
                                 │
        ┌────────────┬───────────┼───────────┬────────────┬────────────┐
        ▼            ▼           ▼           ▼            ▼            ▼
      Tool         Repository  API Vault   Artifact     Worker       Security
      exec         browser     /connectors store/       coord        scanners
      policy                   (creds)     provenance   (remote)     (+ policy)
```

## Interfaces (structured, validated, bounded)

- **ModelProvider** — id, context window, tool-calling/vision flags, cost, privacy,
  invoke(messages, tools) with timeouts and cancellation. (Exists.)
- **DecisionProvider** — `evaluate(request, context, available_capabilities) -> Decision`
  with intent, task type, confidence, missing info, plan, tools, risk, approval need,
  rationale, fallback. Jev exists behind this shape today; Laya needs an adapter + mock.
- **Agent** — a role with a system policy, an allowed tool set, and a bounded loop that
  returns artifacts, never an unbounded delegation.
- **Skill** — a versioned instruction bundle (id, purpose, inputs/outputs, deps, required
  tools, permissions, trust). Instructions only; executable tools stay separate.
- **Tool / Capability** — a schema'd call with explicit permissions and an error
  taxonomy. Mirrors MCP's tool model; capabilities are discoverable and enable-able.
- **MemoryProvider** — search/get/set with provenance, project isolation, and a
  verified-vs-inferred distinction.
- **RepositoryProvider / APIConnector** — discovery, provenance, license, and a
  controlled outbound call with destination policy and response limits.
- **Worker** — registration, heartbeat, capacity, task queue, authenticated transport.

## Boundaries (enforced, independent of the model and of Jev)

Policy is enforced at the tool boundary, not inside a decision provider:

- **Filesystem** — workspace-scoped, traversal- and symlink-safe.
- **Subprocess** — a command policy in front of the shell now; structured argument
  execution is the target.
- **Network** — destination policy, timeouts, response-size limits, audit log.
- **Secrets** — OS/secret-store only; never in memory, prompts, logs, or git.

## Non-goals

- No rewrite in a faster language; the existing Python + GDScript split stays.
- No second plugin: a consuming project needs only `addons/loki`.
- No framework pile-up: adopt a component only with a measured reason.