@echo off
rem Start LOKI Studio on Windows: the app you build LOKI with (docs\STUDIO.md).
rem It runs on its own - LOKI does not have to be running, or working.
setlocal
set "PYW=%~dp0harness_data\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo LOKI is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0studio\studio_app.py" %*
