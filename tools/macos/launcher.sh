# Loki.app launcher body. make_loki_app.sh prepends `#!/bin/bash` and a `REPO=` line
# naming this checkout, then installs the result as Loki.app/Contents/MacOS/Loki.
#
# It finds Godot 4.8+, runs setup.sh once, and opens the Loki project in the editor.
# It never downloads or installs Godot itself: when Godot is missing it says so.
#
# Overrides (also how the tests drive it):
#   LOKI_GODOT=/path/to/Godot   use this Godot binary
#   LOKI_GODOT_SEARCH_DIRS=a:b  look for Godot*.app only in these folders
#   LOKI_SKIP_SETUP=1           do not run setup.sh even if the venv is missing
set -u

MIN_MAJOR=4
MIN_MINOR=8

# Finder starts apps with a bare PATH. Add the usual tool locations so Godot - and the
# Loki bridge it starts - can find python3, git, node, uvx and the coding CLIs.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

LOG_DIR="$REPO/harness_data"
LOG="$LOG_DIR/loki_app.log"

say() {
  echo "[loki-app] $*" >&2
  [ -d "$LOG_DIR" ] && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null
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

# --- the checkout -----------------------------------------------------------------
if [ ! -f "$REPO/project.godot" ] || [ ! -f "$REPO/addons/loki/plugin.cfg" ]; then
  alert "The Loki folder is gone or moved: $REPO. Rebuild the app with tools/macos/make_loki_app.sh from the new location."
  exit 3
fi
mkdir -p "$LOG_DIR" 2>/dev/null || true

# --- Godot ------------------------------------------------------------------------
find_godot() {
  if [ -n "${LOKI_GODOT:-}" ]; then
    [ -f "$LOKI_GODOT" ] && [ -x "$LOKI_GODOT" ] && { echo "$LOKI_GODOT"; return 0; }
    return 1
  fi
  local app bin dir
  local dirs="${LOKI_GODOT_SEARCH_DIRS:-/Applications:$HOME/Applications}"
  # Newest-looking bundle first (Godot_v4.8 sorts after Godot_v4.3).
  while IFS= read -r app; do
    bin="$app/Contents/MacOS/Godot"
    [ -x "$bin" ] && { echo "$bin"; return 0; }
  done < <(IFS=:; for dir in $dirs; do ls -d "$dir"/Godot*.app 2>/dev/null; done | sort -r)
  # An explicit search list means "only look there" (the tests rely on this).
  [ -n "${LOKI_GODOT_SEARCH_DIRS:-}" ] && return 1
  if command -v mdfind >/dev/null 2>&1; then
    while IFS= read -r app; do
      bin="$app/Contents/MacOS/Godot"
      [ -x "$bin" ] && { echo "$bin"; return 0; }
    done < <(mdfind 'kMDItemCFBundleIdentifier == "org.godotengine.godot"' 2>/dev/null | sort -r)
  fi
  bin=$(command -v godot 2>/dev/null) && [ -n "$bin" ] && { echo "$bin"; return 0; }
  return 1
}

if ! GODOT=$(find_godot); then
  if [ -n "${LOKI_GODOT:-}" ]; then
    alert "LOKI_GODOT does not point to a runnable Godot binary: $LOKI_GODOT"
  else
    alert "Godot 4.8 or newer was not found. Install it from godotengine.org into Applications, then open Loki again."
  fi
  exit 4
fi

VERSION=$("$GODOT" --version 2>/dev/null | head -n 1)
MAJOR=$(printf '%s' "$VERSION" | cut -d. -f1)
MINOR=$(printf '%s' "$VERSION" | cut -d. -f2)
case "$MAJOR$MINOR" in
  ''|*[!0-9]*)
    alert "Could not read the Godot version from $GODOT (got: '$VERSION')."
    exit 5 ;;
esac
if [ "$MAJOR" -lt "$MIN_MAJOR" ] || { [ "$MAJOR" -eq "$MIN_MAJOR" ] && [ "$MINOR" -lt "$MIN_MINOR" ]; }; then
  alert "Loki needs Godot $MIN_MAJOR.$MIN_MINOR or newer; found $VERSION at $GODOT."
  exit 5
fi
say "using Godot $VERSION at $GODOT"

# --- one-time setup -----------------------------------------------------------------
if [ ! -x "$REPO/harness_data/.venv/bin/python" ] && [ "${LOKI_SKIP_SETUP:-0}" != "1" ]; then
  notify "First launch: setting up Loki's Python environment. This takes a few minutes."
  if ! (cd "$REPO" && bash ./setup.sh) >>"$LOG" 2>&1; then
    alert "Loki setup failed. Details are in $LOG"
    exit 6
  fi
fi

# --- open the editor ------------------------------------------------------------------
say "opening $REPO in the Godot editor"
exec "$GODOT" --path "$REPO" -e
