#!/usr/bin/env bash
# Build LOKI.dmg for other people: a self-contained Loki.app (no checkout, no git, no Python needed).
#
#   python3 tools/make_release.py --feed <feed url>    # -> dist/release/seed + manifest
#   bash tools/macos/make_dmg.sh                       # -> dist/Loki-<version>.dmg
#
# The app carries the release seed and the launcher in Contents/Resources. Its first start runs
# packaging/installer/bootstrap.sh: uv + a standalone Python 3.12 + LOKI's packages go into
# ~/Library/Application Support/Loki (a few minutes, once), then loki_launch.py opens the window.
# Updates come as signed release zips (engine/release_update.py). This is NOT tools/macos/
# make_loki_app.sh, which makes the owner's Loki.app that runs a git checkout.
#
# Signing + notarization (optional; without them macOS asks the user to right-click > Open once):
#   LOKI_MAC_SIGN_ID="Developer ID Application: Name (TEAMID)"   codesign identity
#   LOKI_NOTARY_PROFILE=<profile>   a `xcrun notarytool store-credentials` profile
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SEED="${LOKI_SEED:-$REPO/dist/release/seed}"
OUT="${LOKI_DIST:-$REPO/dist}"
[ -f "$SEED/RELEASE.json" ] || { echo "[loki-dmg] no release seed at $SEED - run: python3 tools/make_release.py"; exit 1; }
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SEED/RELEASE.json")"
STAGE="$OUT/dmg-stage"
APP="$STAGE/Loki.app"
rm -rf "$STAGE"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp -R "$SEED" "$APP/Contents/Resources/seed"
cp "$REPO/packaging/installer/loki_launch.py" "$REPO/packaging/installer/bootstrap.sh" "$APP/Contents/Resources/"
chmod 755 "$APP/Contents/Resources/bootstrap.sh"

cat >"$APP/Contents/MacOS/Loki" <<'SH'
#!/bin/bash
# Loki.app (installed edition): set up once, then open LOKI through its launcher.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
exec /bin/bash "$RES/bootstrap.sh" "$@"
SH
chmod 755 "$APP/Contents/MacOS/Loki"

cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>LOKI</string>
  <key>CFBundleDisplayName</key><string>LOKI</string>
  <key>CFBundleIdentifier</key><string>dev.m03.loki.app</string>
  <key>CFBundleExecutable</key><string>Loki</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleLocalizations</key><array><string>en</string><string>es</string><string>fr</string><string>de</string><string>ar</string><string>hi</string><string>zh-Hans</string><string>ja</string></array>
  <key>NSMicrophoneUsageDescription</key><string>LOKI listens while you hold the mic button, to turn your speech into a message.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>LOKI turns your speech into a message when local Whisper is not installed.</string>
</dict>
</plist>
PLIST

if [ -n "${LOKI_MAC_SIGN_ID:-}" ]; then
  echo "[loki-dmg] signing with $LOKI_MAC_SIGN_ID"
  codesign --force --deep --options runtime --timestamp --sign "$LOKI_MAC_SIGN_ID" "$APP"
elif command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "[loki-dmg] ad-hoc signing skipped"
fi

ln -s /Applications "$STAGE/Applications"
DMG="$OUT/Loki-$VERSION.dmg"
rm -f "$DMG"
if command -v hdiutil >/dev/null 2>&1; then
  hdiutil create -volname "LOKI" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
  if [ -n "${LOKI_MAC_SIGN_ID:-}" ]; then codesign --force --sign "$LOKI_MAC_SIGN_ID" "$DMG"; fi
  if [ -n "${LOKI_NOTARY_PROFILE:-}" ]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$LOKI_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  fi
  echo "[loki-dmg] built $DMG"
else
  echo "[loki-dmg] hdiutil is macOS-only: the app is staged in $STAGE (no .dmg made here)"
fi
