#!/usr/bin/env bash
# One-time setup of Loki's GPU training environment on Linux with an NVIDIA card.
# (macOS has no CUDA: Apple-silicon training is a different path and is not set up here.)
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/harness_data/train_venv"
PY="$VENV/bin/python"

command -v nvidia-smi >/dev/null || { echo "[train-setup] nvidia-smi not found - install the NVIDIA driver"; exit 1; }
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
python3 -m pip install --user --upgrade uv
[ -x "$PY" ] || python3 -m uv venv "$VENV" --python 3.13
# Order matters: without torchao first, uv can resolve an old Unsloth.
python3 -m uv pip install --python "$PY" torchao
python3 -m uv pip install --python "$PY" unsloth --torch-backend=auto
"$PY" -c "import torch; ok=torch.cuda.is_available(); print('[train-setup] CUDA:', ok, torch.cuda.get_device_name(0) if ok else '')"
"$PY" -c "import unsloth; print('[train-setup] unsloth', unsloth.__version__)"
echo "[train-setup] Done. Next: harness_data/.venv/bin/python tools/self_improve.py status"
