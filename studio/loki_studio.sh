#!/usr/bin/env bash
# Start LOKI Studio on macOS or Linux: the app you build LOKI with (docs/STUDIO.md).
# It runs on its own - LOKI does not have to be running, or working.
#
#   bash studio/loki_studio.sh              the Studio window
#   bash studio/loki_studio.sh --print-url  no window; print the URL
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${LOKI_STUDIO_REPO:-$(cd "$HERE/.." && pwd)}"
DATA="${LOKI_DATA:-$REPO/harness_data}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
PY=""
for candidate in "$DATA/.venv/bin/python3" "$DATA/.venv/bin/python"; do
  if [ -x "$candidate" ]; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "[loki-studio] LOKI is not set up yet. Run: cd $REPO && bash setup.sh" >&2
  exit 4
fi
export LOKI_STUDIO_REPO="$REPO" LOKI_DATA="$DATA"
exec "$PY" "$REPO/studio/studio_app.py" "$@"
