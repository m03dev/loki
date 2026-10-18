#!/usr/bin/env bash
# Build LOKI.dmg (and Loki-<v>-macos.zip) for other people: a self-contained Loki.app - no checkout,
# no git, no Python, no Homebrew, no download at first start.
#
#   python3 tools/make_release.py                      # -> dist/release/seed + manifest
#   python3 tools/bundle_runtime.py                    # -> dist/runtime (Python + LOKI's packages, this Mac's CPU)
#   cargo build --release --manifest-path packaging/launcher/Cargo.toml   # optional: the native launcher
#   bash tools/macos/make_dmg.sh                       # -> dist/Loki-<version>.dmg + dist/Loki-<version>-macos.zip
#
# Loki.app/Contents/
#   MacOS/Loki            the Rust launcher (packaging/launcher) or, without it, a small bash script
#   Resources/runtime/    python-build-standalone + packages (session 30; from dist/runtime)
#   Resources/seed/       the LOKI tree;  Resources/loki_launch.py, bootstrap.sh
# The first start makes <data>/.venv from the bundled Python (offline, under a second) and opens the
# window. Without dist/runtime (a slim build) bootstrap.sh downloads uv + Python once, as before.
# Updates come as signed release zips (engine/release_update.py), checked in the background.
# This is NOT tools/macos/make_loki_app.sh, which makes the owner's Loki.app that runs a git checkout.
#
# Signing: without a Developer ID the app is ad-hoc signed (codesign -s -), which Apple Silicon needs
# to run it at all; friends open it once with right-click > Open (docs/TESTERS.md). With:
#   LOKI_MAC_SIGN_ID="Developer ID Application: Name (TEAMID)"   codesign identity (hardened runtime)
#   LOKI_NOTARY_PROFILE=<profile>   a `xcrun notarytool store-credentials` profile -> notarized + stapled
# Env: LOKI_SEED, LOKI_DIST, LOKI_RUNTIME (default dist/runtime), LOKI_LAUNCHER_BIN, LOKI_NO_DMG=1 (app only).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SEED="${LOKI_SEED:-$REPO/dist/release/seed}"
OUT="${LOKI_DIST:-$REPO/dist}"
RUNTIME="${LOKI_RUNTIME:-$REPO/dist/runtime}"
LAUNCHER_BIN="${LOKI_LAUNCHER_BIN:-$REPO/packaging/launcher/target/release/Loki}"
[ -f "$SEED/RELEASE.json" ] || { echo "[loki-dmg] no release seed at $SEED - run: python3 tools/make_release.py"; exit 1; }
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SEED/RELEASE.json")"
STAGE="$OUT/dmg-stage"
APP="$STAGE/Loki.app"
rm -rf "$STAGE"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp -R "$SEED" "$APP/Contents/Resources/seed"
cp "$REPO/packaging/installer/loki_launch.py" "$REPO/packaging/installer/bootstrap.sh" "$APP/Contents/Resources/"
chmod 755 "$APP/Contents/Resources/bootstrap.sh"
if [ -n "$RUNTIME" ] && [ -x "$RUNTIME/python/bin/python3" ]; then
  echo "[loki-dmg] bundling the Python runtime from $RUNTIME"
  cp -R "$RUNTIME" "$APP/Contents/Resources/runtime"
else
  echo "[loki-dmg] no bundled runtime ($RUNTIME): the first start downloads Python (slim build)"
fi
if [ -f "$REPO/app/ui/icons/loki.icns" ]; then cp "$REPO/app/ui/icons/loki.icns" "$APP/Contents/Resources/loki.icns"; fi

if [ -x "$LAUNCHER_BIN" ] && file "$LAUNCHER_BIN" 2>/dev/null | grep -q "Mach-O"; then
  cp "$LAUNCHER_BIN" "$APP/Contents/MacOS/Loki"
else
  cat >"$APP/Contents/MacOS/Loki" <<'SH'
#!/bin/bash
# Loki.app (installed edition): the bundled Python opens LOKI through its launcher; a slim build
# sets Python up once first (bootstrap.sh).
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
export LOKI_INSTALL_DIR="$RES" LOKI_LAUNCH_T0="$(( $(date +%s) * 1000 ))"   # never `python3` here: on a clean Mac it asks to install Xcode tools
if [ -x "$RES/runtime/python/bin/python3" ]; then
  exec "$RES/runtime/python/bin/python3" "$RES/loki_launch.py" --seed "$RES/seed" "$@"
fi
exec /bin/bash "$RES/bootstrap.sh" "$@"
SH
fi
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
  <key>CFBundleIconFile</key><string>loki</string>
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
  # ad-hoc: no identity, but every binary gets a valid signature (Apple Silicon refuses unsigned code)
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 && echo "[loki-dmg] ad-hoc signed" || echo "[loki-dmg] ad-hoc signing failed"
fi

if [ -n "${LOKI_NO_DMG:-}" ]; then
  echo "[loki-dmg] app staged in $APP"
  exit 0
fi
if command -v ditto >/dev/null 2>&1; then   # the zip keeps the signature, links and permissions
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$OUT/Loki-$VERSION-macos.zip"
  echo "[loki-dmg] built $OUT/Loki-$VERSION-macos.zip"
fi
ln -s /Applications "$STAGE/Applications"
DMG="$OUT/Loki-$VERSION.dmg"
rm -f "$DMG"
if command -v hdiutil >/dev/null 2>&1; then
  hdiutil create -volname "LOKI" -srcfolder "$STAGE" -ov -format ULFO "$DMG" >/dev/null 2>&1 \
    || hdiutil create -volname "LOKI" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
  if [ -n "${LOKI_MAC_SIGN_ID:-}" ]; then codesign --force --sign "$LOKI_MAC_SIGN_ID" "$DMG"; fi
  if [ -n "${LOKI_NOTARY_PROFILE:-}" ]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$LOKI_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  fi
  echo "[loki-dmg] built $DMG"
else
  echo "[loki-dmg] hdiutil is macOS-only: the app is staged in $STAGE (no .dmg made here)"
fi
