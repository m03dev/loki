# Anthropic skills (vendored, session 27 harvest)

Six open-source skills from [anthropics/skills](https://github.com/anthropics/skills), copied
unchanged: `frontend-design`, `mcp-builder`, `skill-creator`, `webapp-testing`,
`doc-coauthoring`, `internal-comms`. Apache-2.0 (each folder's `LICENSE.txt`;
`doc-coauthoring` ships without one upstream and falls under the repository's statement that
its open-source skills are Apache 2.0, so the same licence text is placed beside it).

Not copied: `docx`, `pdf`, `pptx`, `xlsx` (source-available, "all rights reserved" - not open
source), the Anthropic-specific ones (`brand-guidelines`, `claude-api`, `academy-guide`,
`discernment-nudge`) and the large asset-heavy ones (`canvas-design`, `theme-factory`,
`algorithmic-art`, `slack-gif-creator`, `web-artifacts-builder`).

LOKI reads skills as text and never runs the scripts that come with them (engine/skill_scan.py);
the catalog lists these under the source "anthropic".
