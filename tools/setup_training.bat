@echo off
rem One-time setup of Loki's GPU training environment (for an NVIDIA card, e.g. RTX 3070 Ti).
rem Separate from Loki's own venv: it is large (PyTorch + CUDA) and only training needs it.
rem Safe to re-run. Needs Python on PATH and an NVIDIA driver; downloads several GB.
setlocal
for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "VENV=%REPO%\harness_data\train_venv"
set "PY=%VENV%\Scripts\python.exe"

where nvidia-smi >nul 2>nul || (
  echo [train-setup] nvidia-smi was not found. Install the NVIDIA driver first.
  exit /b 1
)
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo [train-setup] installing uv (the installer Unsloth documents for Windows)
python -m pip install --user --upgrade uv || goto :err

if not exist "%PY%" (
  echo [train-setup] creating %VENV%
  python -m uv venv "%VENV%" --python 3.13 || goto :err
)
rem Order matters: without torchao first, uv silently resolves an OLD Unsloth.
python -m uv pip install --python "%PY%" torchao || goto :err
python -m uv pip install --python "%PY%" unsloth --torch-backend=auto || goto :err

"%PY%" -c "import torch; ok=torch.cuda.is_available(); print('[train-setup] CUDA:', ok, torch.cuda.get_device_name(0) if ok else '')"
"%PY%" -c "import unsloth; print('[train-setup] unsloth', unsloth.__version__)" || goto :err
echo.
echo [train-setup] Done. Next:
echo   harness_data\.venv\Scripts\python.exe tools\self_improve.py status
echo   harness_data\.venv\Scripts\python.exe tools\self_improve.py schedule
exit /b 0

:err
echo [train-setup] FAILED - see the messages above.
exit /b 1
