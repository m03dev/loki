#!/usr/bin/env bash
# Build "LOKI Studio.app": a double-clickable macOS launcher for LOKI Studio in this checkout.
#
#   bash studio/make_studio_app.sh                # -> ~/Applications/LOKI Studio.app
#   bash studio/make_studio_app.sh /Applications
#
# A thin bundle around studio/loki_studio.sh that points at this checkout (nothing is copied).
# Studio itself runs from its pinned known-good copy (studio/studio_pin.py), so a bad LOKI commit
# cannot break it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/LOKI Studio.app"
MARKER="Contents/Resources/loki-studio.marker"

[ -f "$REPO/studio/studio_app.py" ] || { echo "[loki-studio] run this from inside the LOKI checkout"; exit 1; }
if [ -e "$APP" ]; then
  if [ ! -f "$APP/$MARKER" ]; then
    echo "[loki-studio] $APP exists and was not made by this script; not touching it"
    exit 1
  fi
  rm -rf "$APP"
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
{
  echo '#!/bin/bash'
  printf 'export LOKI_STUDIO_REPO=%q\n' "$REPO"
  printf 'exec /bin/bash %q "$@"\n' "$REPO/studio/loki_studio.sh"
} >"$APP/Contents/MacOS/LOKI Studio"
chmod 755 "$APP/Contents/MacOS/LOKI Studio"
SHORT_VERSION="$(tr -d '[:space:]' <"$REPO/VERSION" 2>/dev/null || true)"
cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>LOKI Studio</string>
  <key>CFBundleDisplayName</key><string>LOKI Studio</string>
  <key>CFBundleIdentifier</key><string>dev.m03.loki.studio</string>
  <key>CFBundleExecutable</key><string>LOKI Studio</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${SHORT_VERSION:-0.1}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST
printf '%s\n' "$REPO" >"$APP/$MARKER"
if command -v codesign >/dev/null 2>&1; then
  codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "[loki-studio] ad-hoc signing skipped"
fi
echo "[loki-studio] built $APP -> $REPO"
