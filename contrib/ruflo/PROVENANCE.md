# Ruflo in LOKI

- Source: https://github.com/ruvnet/ruflo (formerly claude-flow), MIT License (LICENSE here).
- Copied verbatim from commit `1882006a02487590c8c66a7eec8d7504f6af33c3`:
  - `plugin/agents/` -> `agents/` (95 agent definitions), `plugin/skills/` -> `skills/` (38 skills),
    `.claude/commands/` (= `plugin/commands`) -> `commands/` (168 commands: sparc, swarm,
    hive-mind, github, memory, hooks, training, workflows, ...);
  - every plugin in `plugins/` (47 of them, e.g. ruflo-swarm, ruflo-sparc, ruflo-goals,
    ruflo-agentdb, ruflo-cost-tracker) -> `plugins/<name>/`: its README.md, plugin.json, and the
    .md files of its agents/, skills/ and commands/ (69 agents, 159 skills, 63 commands; the six
    duplicate skills under ruflo-ai-team/directory/ are left out).
- Only text is copied: Ruflo's TypeScript/Rust code, hook scripts and npm packages are not.
  LOKI reads these files; nothing here is executed. Ruflo's own runtime (swarm and memory MCP
  tools) is the opt-in MCP server in `engine/mcp_servers.json` (`LOKI_MCP_ENABLE=ruflo`).
- How LOKI uses them (`engine/ruflo_library.py`):
  - agents -> templates in Settings > Agents ("Ruflo library");
  - skills -> the skill catalog (source "ruflo"), core and plugin;
  - commands -> runnable workflows: `/ruflo <command> <task>` in chat, "Ruflo workflows" in
    Settings > Agents; `/ruflo list <word>` lists them;
  - team roles get the matching Ruflo playbook; `sparc: <goal>` runs a team with Ruflo's SPARC
    method (engine/team.py);
  - Ruflo's ReasoningBank idea is rebuilt natively in `engine/reasoning_bank.py` (lessons from
    past tasks in the next prompt, from what actually happened).
- Every text passes LOKI's skill scan (`engine/skill_scan.py`); anything that tries to
  override LOKI's rules is never loaded.
- Updating: copy the same folders from a newer Ruflo commit, update the commit above, run
  `python tests/test_portal.py`.
