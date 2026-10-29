#!/usr/bin/env bash
# LOKI setup for macOS / Linux: a small Python env for the window, then start LOKI.
# The driver (Rust) is built by the launcher on first start; Rust is installed into
# harness_data/toolchain if this machine has none (keep the checkout on the external drive).
set -euo pipefail
cd "$(dirname "$0")"
VENV=harness_data/.venv
mkdir -p harness_data
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q -r app/requirements.txt || echo "[loki] pywebview missing: LOKI will open in the browser"
[ -f harness_data/.env ] || printf '# Free model keys\nNVIDIA_API_KEY=\n# GROQ_API_KEY=\n# OPENROUTER_API_KEY=\n# MISTRAL_API_KEY=\n' > harness_data/.env
if [ "$(uname)" = "Darwin" ]; then
  BUNDLE="$HOME/Applications/Loki.app/Contents"; mkdir -p "$BUNDLE/MacOS"
  printf '#!/bin/sh\nexec "%s/%s/bin/python" "%s/app/loki_app.py" "$@"\n' "$PWD" "$VENV" "$PWD" > "$BUNDLE/MacOS/Loki"; chmod +x "$BUNDLE/MacOS/Loki"
  [ -f "$BUNDLE/Info.plist" ] || printf '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>CFBundleName</key><string>Loki</string><key>CFBundleExecutable</key><string>Loki</string><key>CFBundleIdentifier</key><string>dev.m03.loki</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>\n' > "$BUNDLE/Info.plist"
  echo "[loki] Done. Open Loki from ~/Applications."
else
  echo "[loki] Done. Start: $VENV/bin/python app/loki_app.py"
fi
