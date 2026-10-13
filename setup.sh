#!/usr/bin/env bash
# Loki one-time setup (macOS / Linux). Safe to re-run. Needs python3 and git.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="$REPO/addons/loki/harness"
DATA="$REPO/harness_data"
VENV="$DATA/.venv"

[ -f "$HARNESS/loki.py" ] || { echo "[loki] run this from the Loki repo root"; exit 1; }

# The newest Python 3.11+ on the machine. Apple's /usr/bin/python3 is 3.9, which
# cannot install the harness dependencies.
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
"$VENV/bin/python" -m pip install -r "$HARNESS/requirements.txt"

echo "[loki] fetching the skill libraries (optional; needs git and internet)"
mkdir -p "$DATA/vendor"
[ -d "$DATA/vendor/ponytail" ] || git clone --depth 1 https://github.com/DietrichGebert/ponytail.git "$DATA/vendor/ponytail" || true
[ -d "$DATA/vendor/ECC" ] || git clone --depth 1 https://github.com/affaan-m/ECC.git "$DATA/vendor/ECC" || true

if [ ! -f "$DATA/.env" ]; then
  cp "$HARNESS/.env.example" "$DATA/.env"
  echo "[loki] created harness_data/.env - paste ONE key, or none at all: Loki works without any"
fi

"$VENV/bin/python" "tools/loki_doctor.py" || true
echo
echo "[loki] Done. Open this folder as a Godot project and enable Loki in"
echo "       Project > Project Settings > Plugins. The chat dock appears beside Scene."
