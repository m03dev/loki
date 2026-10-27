@AGENTS.md

Claude-specific: ship to `master` with `tools/ship.py` like every other agent - never an `agent/<topic>` branch (the
owner's machines only install master; branches left fixes stranded). A cloud session has no LOKI venv: first
`pip install --break-system-packages -r engine/requirements.txt`, then `python3 tools/ship.py -m "..."`.
