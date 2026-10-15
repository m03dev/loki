# Ruflo library in LOKI

- Source: https://github.com/ruvnet/ruflo (formerly claude-flow), MIT License (LICENSE here).
- Copied verbatim on 2026-10-14 from commit `1882006a02487590c8c66a7eec8d7504f6af33c3`:
  `plugin/agents/` -> `agents/` (95 unique agent definitions) and `plugin/skills/` -> `skills/`
  (38 skills). Nothing here is executed: LOKI reads these as text.
- How LOKI uses them: `engine/ruflo_library.py` (agent templates in Settings > Agents, skills
  in the skill catalog, playbooks for team roles). Ruflo's own MCP server is opt-in in
  `engine/mcp_servers.json` (`LOKI_MCP_ENABLE=ruflo`).
- Every text passes LOKI's skill scan (`engine/skill_scan.py`); anything that tries to
  override LOKI's rules is never loaded (today: the `github-project-management` skill).
- Updating: copy the two folders from a newer Ruflo commit, update the commit above, run
  `python tests/test_portal.py`.
