@echo off
rem LOKI setup for Windows: a small Python env for the window. The launcher builds the Rust
rem driver on first start (and installs Rust into harness_data\toolchain if it is missing).
setlocal
cd /d "%~dp0"
if not exist harness_data mkdir harness_data
if not exist harness_data\.venv\Scripts\python.exe py -3 -m venv harness_data\.venv || python -m venv harness_data\.venv
harness_data\.venv\Scripts\python.exe -m pip install -q -r app\requirements.txt
if not exist harness_data\.env (echo NVIDIA_API_KEY=> harness_data\.env)
echo Done. Start LOKI with Loki.cmd
