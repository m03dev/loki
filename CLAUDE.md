@AGENTS.md

Claude-specific: a cloud session usually has no LOKI venv, so `tools/ship.py` can't run its suites there.
Verify what you can (`node tests/js/...`, the suites that do run), then push an `agent/<topic>` branch whose
last commit message is the hand-over - see AGENTS.md > Git and shipping.
