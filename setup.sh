#!/usr/bin/env bash
# Loki one-time setup (macOS / Linux). Safe to re-run. Needs python3 and git.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$REPO/engine"
DATA="$REPO/harness_data"
VENV="$DATA/.venv"

[ -f "$ENGINE/loki.py" ] || { echo "[loki] run this from the Loki repo root"; exit 1; }

# The newest Python 3.11+ on the machine. Apple's /usr/bin/python3 is 3.9, which
# cannot install the engine dependencies.
PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || { echo "[loki] needs Python 3.11+ (python.org or 'brew install python'); none found"; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  echo "[loki] creating a private Python environment with $PY (one time)"
  "$PY" -m venv "$VENV"
fi
echo "[loki] installing dependencies"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install -r "$ENGINE/requirements.txt"

if [ "$(uname -s)" = "Darwin" ]; then
  echo "[loki] installing the Loki window (pywebview)"
  "$VENV/bin/python" -m pip install -r "$REPO/app/requirements.txt" ||
    echo "[loki] pywebview did not install; Loki will open in your browser instead"
fi

echo "[loki] fetching the skill libraries (optional; needs git and internet)"
mkdir -p "$DATA/vendor"
[ -d "$DATA/vendor/ponytail" ] || git clone --depth 1 https://github.com/DietrichGebert/ponytail.git "$DATA/vendor/ponytail" || true
[ -d "$DATA/vendor/ECC" ] || git clone --depth 1 https://github.com/affaan-m/ECC.git "$DATA/vendor/ECC" || true

if [ ! -f "$DATA/.env" ]; then
  cp "$ENGINE/.env.example" "$DATA/.env"
  echo "[loki] created harness_data/.env - paste ONE key, or none at all: Loki works without any"
fi

"$VENV/bin/python" "tools/loki_doctor.py" || true

echo "[loki] setting up Laya, the offline first layer (Node.js 20+; downloads about 1.7 GB once)"
"$VENV/bin/python" "$REPO/tools/setup_laya.py" || echo "[loki] Laya is not set up yet; Loki uses its built-in rules until it is"
echo
if [ "$(uname -s)" = "Darwin" ] && [ "${LOKI_NO_APP_BUILD:-0}" != "1" ]; then
  bash "$REPO/tools/macos/make_loki_app.sh"
  echo "[loki] Done. Open Loki from ~/Applications (or: open ~/Applications/Loki.app)."
else
  echo "[loki] Done. Start Loki with: $VENV/bin/python app/loki_app.py"
fi
