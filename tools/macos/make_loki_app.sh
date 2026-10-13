#!/usr/bin/env bash
# Build Loki.app: a double-clickable macOS launcher for this checkout.
#
#   tools/macos/make_loki_app.sh                # -> ~/Applications/Loki.app
#   tools/macos/make_loki_app.sh /Applications  # -> /Applications/Loki.app
#
# Loki.app runs the standalone Loki app (app/loki_app.py): the Loki window over the
# Loki engine. It is a thin bundle around tools/macos/launcher.sh and points at this
# checkout instead of copying it, so `git pull` updates what it runs. setup.sh calls
# this script at the end on macOS, so the bundle is built on the Mac with the right
# permissions.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/Loki.app"
MARKER="Contents/Resources/loki-app.marker"

[ -f "$REPO/app/loki_app.py" ] && [ -f "$HERE/launcher.sh" ] ||
  { echo "[loki-app] run this from inside the Loki checkout"; exit 1; }

# Only ever replace a bundle this script made.
if [ -e "$APP" ]; then
  if [ ! -f "$APP/$MARKER" ]; then
    echo "[loki-app] $APP exists and was not made by this script; not touching it"
    exit 1
  fi
  rm -rf "$APP"
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

{
  echo '#!/bin/bash'
  printf 'REPO=%q\n' "$REPO"
  cat "$HERE/launcher.sh"
} >"$APP/Contents/MacOS/Loki"
chmod 755 "$APP/Contents/MacOS/Loki"

VERSION="$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo dev)"
cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Loki</string>
  <key>CFBundleDisplayName</key><string>Loki</string>
  <key>CFBundleIdentifier</key><string>dev.m03.loki</string>
  <key>CFBundleExecutable</key><string>Loki</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST

printf '%s\n' "$REPO" >"$APP/$MARKER"

# An ad-hoc signature keeps macOS from treating the bundle as damaged. Built locally,
# it carries no quarantine flag, so Gatekeeper lets it open.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "[loki-app] ad-hoc signing skipped"
fi

echo "[loki-app] built $APP -> $REPO"
