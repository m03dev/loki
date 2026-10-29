@echo off
rem Start the Loki desktop app on Windows (the shortcuts setup.bat makes do the same).
setlocal
set "PYW=%~dp0harness_data\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Loki is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0app\loki_app.py" %*
