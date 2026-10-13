# Loki.app launcher body. make_loki_app.sh prepends `#!/bin/bash` and a `REPO=` line
# naming this checkout, then installs the result as Loki.app/Contents/MacOS/Loki.
#
# It runs the standalone Loki app (app/loki_app.py) with Loki's private Python. On the
# very first launch, when that Python does not exist yet, it runs setup.sh once.
# It never installs anything else on its own.
#
# Overrides (also how the tests drive it):
#   LOKI_PYTHON=/path/to/python  use this interpreter
#   LOKI_DATA=/path              Loki's data folder (default: <checkout>/harness_data)
#   LOKI_SKIP_SETUP=1            never run setup.sh from here
set -u

# Finder starts apps with a bare PATH. Add the usual tool locations so the engine can
# find git, node, uvx, ollama and the coding CLIs.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

DATA="${LOKI_DATA:-$REPO/harness_data}"
LOG_DIR="$DATA/app"
LOG="$LOG_DIR/loki_app.log"

say() {
  echo "[loki-app] $*" >&2
  mkdir -p "$LOG_DIR" 2>/dev/null && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null
  return 0
}

alert() {
  say "$1"
  if command -v osascript >/dev/null 2>&1; then
    local text=${1//\"/\'}
    osascript -e "display alert \"Loki\" message \"$text\"" >/dev/null 2>&1 || true
  fi
}

notify() {
  say "$1"
  if command -v osascript >/dev/null 2>&1; then
    local text=${1//\"/\'}
    osascript -e "display notification \"$text\" with title \"Loki\"" >/dev/null 2>&1 || true
  fi
}

if [ ! -f "$REPO/app/loki_app.py" ]; then
  alert "The Loki folder is gone or moved: $REPO. Run setup.sh in the new location to rebuild the app."
  exit 3
fi

find_python() {
  if [ -n "${LOKI_PYTHON:-}" ]; then
    [ -x "$LOKI_PYTHON" ] && { echo "$LOKI_PYTHON"; return 0; }
    return 1
  fi
  local candidate
  for candidate in "$DATA/.venv/bin/python3" "$DATA/.venv/bin/python"; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  return 1
}

if ! PY=$(find_python); then
  if [ -n "${LOKI_PYTHON:-}" ]; then
    alert "LOKI_PYTHON does not point to a runnable Python: $LOKI_PYTHON"
    exit 4
  fi
  if [ "${LOKI_SKIP_SETUP:-0}" = "1" ]; then
    alert "Loki is not set up yet. In Terminal run: cd $REPO && bash setup.sh"
    exit 4
  fi
  notify "First launch: setting up Loki. This takes a few minutes."
  if ! (cd "$REPO" && LOKI_NO_APP_BUILD=1 bash ./setup.sh) >>"$LOG" 2>&1; then
    alert "Loki setup failed. Details are in $LOG"
    exit 6
  fi
  PY=$(find_python) || { alert "Setup finished but Loki's Python is missing. See $LOG"; exit 6; }
fi

say "starting Loki with $PY"
exec "$PY" "$REPO/app/loki_app.py"
