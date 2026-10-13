# Capabilities, policy and the backbone

How Loki decides what it may do, and how new abilities plug in. Code lives in
`addons/loki/harness/`; tests in `tests/test_hardening.py`.

```
 model asks for a tool
        |
        v
 policy.py  PolicyEngine.tool_call()  ---- DENY ---> refused, the user never sees a prompt
        |  (fixed rules: no shell, workspace paths, capability on + granted, network)
        | ASK
        v
 approve()  -- decisions.risk_gate() (Laya / Jev) may skip the prompt ONLY via
        |      policy.final(): decidable ASK + "allow" -> ALLOW. Nothing else upgrades.
        v
 the human: Allow / Deny
        |
        v
 tool runs (run_command -> safe_exec: argv, no shell, timeout)
```

## Pieces

| Module | Role |
|---|---|
| `interfaces.py` | Protocols: `ModelProvider`, `MemoryProvider`, `DecisionProvider`, `Tool`, `Skill`; adapters over what exists (Jev/Laya via their real `enabled`, `risk_gate`, `noul`; OpenAI-compatible models; SKILL.md files). |
| `manifests.py` | `capabilities/<name>/manifest.json` discovery and enablement. JSON only, never imports. |
| `policy.py` | Hardcoded allow / ask / deny. The decision layer recommends; this decides. |
| `safe_exec.py` | Command execution without a shell. |
| `skill_scan.py` | Untrusted-skill scan before text reaches the model. |
| `knowledge.py` | `viking://memory`, `viking://state` (writable), `viking://skills`, `viking://project` over local folders. |
| `federation.py` | Health-checks Ollama on other machines (`LOKI_WORKERS`) and routes local models to one that is up and has the model. |
| `workers.py` | Background jobs (local / herdr / cua); herdr and cua jobs need their capability on. |
| `tools/export_obsidian.py` | Writes a human-readable vault (`~/Loki-Knowledge/Loki/`). Loki never reads it back. |

## Manifest

```json
{
  "name": "herdr", "version": "0.1.0", "kind": "adapter",
  "description": "...", "license": "...", "homepage": "https://herdr.dev",
  "permissions": ["process:agent"],
  "requires_cmd": ["herdr"], "requires_env": [],
  "health_endpoint": "", "entrypoint": "workers.HerdrBackend"
}
```

Kinds: tool, skill, adapter, api, memory, model, decision, worker. Permissions:
`network`, `network:loopback`, `network:<host>`, `fs:workspace`, `fs:read`, `process:agent`,
`process:spawn`, `computer:virtual`, `computer:host`, `secret:<ENV>`. High risk (never on by
default): `network`, `process:spawn`, `computer:host`.

Statuses: `disabled` (default) · `enabled` · `missing` (on, but a command/env is absent) ·
`changed` (manifest edited since approval; grants nothing) · `invalid`.

Built-ins shipped: herdr, cua, jev, laya, ollama (on by default, loopback only),
ollama-fleet. Jev and Laya keep their own switch (an API key / installed package), so their
manifests describe them rather than gate them.

## Adding a capability

1. Write `harness_data/capabilities/<name>/manifest.json` (or `capabilities/` for a built-in).
2. Implement it against the protocol in `interfaces.py`.
3. If it acts, add a rule in `policy.py` (`CAPABILITY_TOOLS` or `BACKEND_CAPABILITY`) so the
   policy engine refuses it while it is off.
4. Add checks to `tests/test_hardening.py`.

## Deliberately not done yet

- **OpenViking server.** Loki uses its `viking://` addressing over local folders today; an
  OpenViking-backed `MemoryProvider` can replace `knowledge.LocalViking` behind the same
  protocol once it is installed and evaluated.
- **Graphiti.** Add only when Loki needs temporal questions ("what was true before X").
- **Model provider endpoints through the network policy.** They are user-configured and
  still go direct.
