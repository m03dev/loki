@echo off
rem Loki Cloud auth service. Powers "Sign in with Google" in the Loki dock.
rem Stdlib only - no dependencies. The dock also starts this automatically.
setlocal
for %%I in ("%~dp0.") do set "CLOUD=%%~fI"
set "REPO=%CLOUD%\.."
set "PY=%REPO%\harness\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if not defined LOKI_CLOUD_PORT set "LOKI_CLOUD_PORT=8788"
echo [loki] Cloud auth service on http://localhost:%LOKI_CLOUD_PORT% - press Ctrl+C to stop.
"%PY%" "%CLOUD%\auth_server.py"
