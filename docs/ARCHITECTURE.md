# LOKI architecture

How the pieces fit, as built. The direction for the next rounds of work is in
[BUILD_BRIEF.md](BUILD_BRIEF.md); why things are the way they are is in
[decisions/ARCHITECTURE_DECISIONS.md](decisions/ARCHITECTURE_DECISIONS.md).

```
 you ── app/ (window: pywebview + app/ui) ──HTTP 127.0.0.1:8767 + token──┐
                                                                          v
                                       engine/loki_bridge.py  (loopback API, jobs, peers)
                                                                          |
   every request ─> first_layer.py (Laya, else rules) ─> loki.py (agent loop, tools)
                                                              |
        routing + failover (smart) ── providers: local Ollama, free tiers, subscriptions
        policy.py ── approvals ── safe_exec.py (no shell)
        conductor.py ── specialists via capabilities/ manifests (browser, web, memory...)
        workers.py ── background agents (local / herdr / cua VMs), isolated git worktrees
        experience.py ── outcome log ─> learned routing, training data ─> tools/train_lora.py
        peers.py + peer_link.py ── signed LAN link to your other machines (port 8768)
```

## Request path

1. **App.** `app/loki_app.py` starts the engine (`engine/loki_bridge.py`) with a per-run
   token and opens the window on it. The UI is plain HTML/JS in `app/ui/`, served by the
   engine with a strict CSP.
2. **First layer.** `first_layer.triage` asks Laya (`laya.py` + `laya_server.mjs`, a warm
   local model) what kind of request this is, how to handle it, how hard and how risky it
   is. Built-in rules answer when Laya is not available. The verdict steers the start of
   the run and is logged with the outcome.
3. **Agent loop.** `loki.py` runs the model with tools. Modes: Ask (read only), Plan (read,
   then a plan), Build (edit, run, verify). A Build answer that changed files must pass the
   verification gate before it may say DONE.
4. **Models.** `smart` picks the best available provider in `SMART_ORDER` (free hosted tiers,
   then Claude Code / Codex subscriptions, then local Ollama), reordered by measured
   success when learned routing is on, and fails over when one runs out. Paid providers stay
   behind a budget. `usage.py` meters every call.
5. **Safety.** `policy.py` decides allow / ask / deny for every tool call; risky ones wait
   for you. Laya and Jev (`decisions.py`) can only skip a prompt for a confidently safe
   action, never grant a permission. Commands run without a shell (`safe_exec.py`).
6. **Background work.** `workers.py` runs agents (the built-in Loki agent, Claude Code,
   Codex, Hermes) as jobs: detached on this computer, in herdr, or inside a cua virtual
   computer. Host jobs work in their own git worktree. The chat shows them live above the
   message box.
7. **Learning.** `experience.py` logs every request (provider, route, triage, outcome) and
   keeps verified successes as training examples. Routing learns from measured success.
   `tools/self_improve.py` + `tools/train_lora.py` fine-tune a small model on the PC's GPU
   and promote it only if it beats the current one.
8. **Machines.** `peers.py` / `peer_link.py` link LOKI on the Mac and the PC: signed
   requests, private network only, off by default. The Mac sends jobs and verified work to
   the PC and can use its GPU and its trained model. See
   [operations/MACHINES.md](operations/MACHINES.md).

## Engine modules (`engine/`)

| Module | Role |
| --- | --- |
| `loki.py` | agent loop, tools, providers, routing, verification gate, modes |
| `loki_bridge.py` | loopback HTTP API for the app; starts jobs, peer link, Laya |
| `first_layer.py`, `laya.py`, `laya_server.mjs`, `jev.py`, `decisions.py` | first-layer triage and typed decisions |
| `policy.py`, `safe_exec.py`, `skill_scan.py` | what may run, how it runs, untrusted skills |
| `conductor.py`, `capabilities.py`, `manifests.py`, `interfaces.py`, `runners/` | specialists and optional add-ons (capabilities/*/manifest.json) |
| `workers.py`, `agents.py`, `cli_agents.py`, `sessions.py` | background agents and coding-agent subscriptions |
| `experience.py`, `usage.py`, `model_setup.py`, `federation.py` | learning, cost, local models, other machines' Ollama |
| `peers.py`, `peer_link.py` | the Mac <-> PC link |
| `knowledge.py`, `brain.py`, `project_state.py`, `repo_review.py`, `api_vault.py`, `ecc_sync.py` | context, memory, project state, skill libraries |
| `godot_tools.py`, `godot_assets.py` | the optional Godot capability for game projects |

## Data

Everything LOKI writes lives in `harness_data/` (or `LOKI_DATA`; the packaged app uses a
per-user folder): `.env` keys, `.venv`, memory, `experience/`, `workers/`, `usage.jsonl`,
`laya/` (package + weights), `app/` (engine log and token). Chats live in
`<workspace>/.loki/`. None of it is committed.
