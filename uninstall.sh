#!/usr/bin/env bash
# Loki uninstall (macOS / Linux) - the opposite of setup.sh. Removes the start-at-login entry,
# the macOS app bundle and Loki's private Python environment, and stops Loki. Your data is kept
# unless you pass --purge.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$REPO/harness_data"
VENV="$DATA/.venv"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

[ -f "$REPO/engine/loki.py" ] || { echo "[loki] run this from the Loki repo root"; exit 1; }

echo
echo "[loki] This will remove LOKI from this computer:"
echo "       - the 'start at login' entry (macOS: the Loki.app too)"
echo "       - LOKI's private Python environment ($VENV)"
if [ "$PURGE" = 1 ]; then
  echo "       - ALL of harness_data: your keys, memory, jobs and models"
else
  echo "       - your data (keys, memory, jobs) is KEPT; pass --purge to delete it too"
fi
echo
printf "Type yes to continue: "
read -r CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "[loki] nothing was changed."; exit 0; }

echo "[loki] stopping LOKI if it is running"
pkill -f "loki_app.py" 2>/dev/null || true
pkill -f "loki_bridge.py" 2>/dev/null || true
pkill -f "loki.py --job" 2>/dev/null || true

if [ "$(uname -s)" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/com.m03dev.loki.plist"
  if [ -f "$PLIST" ]; then launchctl unload "$PLIST" 2>/dev/null || true; rm -f "$PLIST"; echo "[loki] removed $PLIST"; fi
  APP="$HOME/Applications/Loki.app"
  if [ -d "$APP" ]; then rm -rf "$APP"; echo "[loki] removed $APP"; fi
fi

echo "[loki] removing LOKI's private Python environment"
rm -rf "$VENV"
if [ "$PURGE" = 1 ]; then echo "[loki] removing harness_data"; rm -rf "$DATA"; fi
echo "[loki] Done. Ollama and the folder $REPO are left alone; delete the folder if you want."
