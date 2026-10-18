#!/bin/bash
# LOKI's first-run setup on macOS (the .dmg's Loki.app runs this; Linux works the same way).
#
# Makes LOKI's private Python in the data folder, once, without needing Python, Homebrew or
# Xcode on the computer: it downloads uv (a small, signed-by-HTTPS tool from Astral) into
# <data>/runtime, lets uv fetch a standalone Python 3.12, and makes <data>/.venv. Then it starts
# the launcher (loki_launch.py), which installs LOKI's packages and opens the window.
#
#   bootstrap.sh            set up if needed, then open LOKI
#   bootstrap.sh --setup    only set up (the installer / CI)
# Overrides: LOKI_DATA, LOKI_UV_VERSION, LOKI_NO_DIALOGS=1 (no pop-ups, for CI).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(uname -s)" = "Darwin" ]; then
  DATA="${LOKI_DATA:-$HOME/Library/Application Support/Loki}"
else
  DATA="${LOKI_DATA:-$HOME/.local/share/loki}"
fi
UV_VERSION="${LOKI_UV_VERSION:-0.8.0}"
RUNTIME="$DATA/runtime"
VENV="$DATA/.venv"
LOG="$DATA/app/bootstrap.log"
mkdir -p "$DATA/app" "$RUNTIME"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

say() { echo "[loki-setup] $*" >&2; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"; }
quiet() { [ -n "${LOKI_NO_DIALOGS:-}${CI:-}" ]; }
notify() { quiet || osascript -e "display notification \"$1\" with title \"LOKI\"" >/dev/null 2>&1 || true; }
fail() {
  say "FAILED: $1"
  if ! quiet && command -v osascript >/dev/null 2>&1; then
    osascript -e "display alert \"LOKI could not finish setting up\" message \"$1

What to do: check the internet connection and open LOKI again. The details are in $LOG\"" >/dev/null 2>&1 || true
  fi
  exit 1
}

python_ok() { [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }

# Session 30: an installer that carries its own Python (runtime/, tools/bundle_runtime.py) needs no
# download at all - the launcher makes the environment from it, offline.
BUNDLED="$HERE/runtime/python/bin/python3"
if [ -x "$BUNDLED" ]; then
  export LOKI_INSTALL_DIR="$HERE"
  LAUNCHER="$DATA/launcher/loki_launch.py"
  [ -f "$LAUNCHER" ] || LAUNCHER="$HERE/loki_launch.py"
  if [ "${1:-}" = "--setup" ]; then
    exec "$BUNDLED" "$LAUNCHER" --seed "$HERE/seed" --check
  fi
  exec "$BUNDLED" "$LAUNCHER" --seed "$HERE/seed" "$@"
fi

if ! python_ok; then
  notify "Setting up LOKI for the first time - this takes a few minutes and needs the internet once."
  UV="$RUNTIME/uv"
  if [ ! -x "$UV" ]; then
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64) TARGET=aarch64-apple-darwin ;;
      Darwin-x86_64) TARGET=x86_64-apple-darwin ;;
      Linux-x86_64) TARGET=x86_64-unknown-linux-gnu ;;
      Linux-aarch64) TARGET=aarch64-unknown-linux-gnu ;;
      *) fail "this computer ($(uname -s) $(uname -m)) is not supported yet" ;;
    esac
    BASE="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$TARGET.tar.gz"
    TMP="$(mktemp -d)"
    say "downloading uv $UV_VERSION ($TARGET)"
    curl -fsSL --retry 3 -o "$TMP/uv.tar.gz" "$BASE" || fail "could not download uv from GitHub"
    curl -fsSL --retry 3 -o "$TMP/uv.sha256" "$BASE.sha256" || fail "could not download uv's checksum"
    WANT="$(awk '{print $1}' "$TMP/uv.sha256")"
    GOT="$(shasum -a 256 "$TMP/uv.tar.gz" | awk '{print $1}')"
    [ -n "$WANT" ] && [ "$WANT" = "$GOT" ] || fail "the uv download did not match its checksum"
    tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
    cp "$TMP/uv-$TARGET/uv" "$UV"
    chmod 755 "$UV"
    rm -rf "$TMP"
  fi
  export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
  say "getting Python 3.12 (standalone, only for LOKI)"
  "$UV" python install 3.12 >>"$LOG" 2>&1 || fail "could not download Python 3.12"
  rm -rf "$VENV"
  "$UV" venv --python 3.12 --seed "$VENV" >>"$LOG" 2>&1 || fail "could not make LOKI's Python environment"
  python_ok || fail "LOKI's Python environment does not work"
  say "Python ready: $("$VENV/bin/python" --version 2>&1)"
fi

LAUNCHER="$DATA/launcher/loki_launch.py"   # a newer one a release brought (loki_launch.py self_update)
[ -f "$LAUNCHER" ] || LAUNCHER="$HERE/loki_launch.py"
if [ "${1:-}" = "--setup" ]; then
  exec "$VENV/bin/python" "$LAUNCHER" --seed "$HERE/seed" --check
fi
exec "$VENV/bin/python" "$LAUNCHER" --seed "$HERE/seed"
