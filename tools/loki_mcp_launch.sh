#!/bin/bash
# Start LOKI's MCP server (engine/loki_mcp.py) for an MCP client - the Claude desktop app, Claude Code, Codex.
# It finds this checkout's Python and the running LOKI's data folder (where its engine token is) by itself.
#   Claude desktop app > Settings > Developer > Edit Config:
#     {"mcpServers": {"loki": {"command": "/bin/bash", "args": ["<this checkout>/tools/loki_mcp_launch.sh"]}}}
cd "$(dirname "$0")/.." || exit 1
PY=""
for p in harness_data/.venv/bin/python harness_data/runtime/bin/python3 "$(command -v python3)"; do
  if [ -n "$p" ] && [ -x "$p" ] && "$p" -c "import mcp" 2>/dev/null; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then echo "loki_mcp: no Python with the mcp package here (pip install -r engine/requirements.txt)" >&2; exit 1; fi
if [ -z "$LOKI_DATA" ]; then
  for d in "$HOME/Library/Application Support/Loki" "$PWD/harness_data"; do
    if [ -f "$d/app/engine.token" ]; then export LOKI_DATA="$d"; break; fi
  done
fi
exec "$PY" engine/loki_mcp.py "$@"
