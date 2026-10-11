@echo off
rem Loki bridge launcher for MANUAL use only.
rem The dock normally starts the bridge itself via addons/loki/bootstrap.py
rem (which also creates the venv and installs dependencies), so you do not
rem need this file. It exists so the bridge can be started by hand.
rem
rem Set GODOT_EXE to your Godot 4 executable first if the agent should be able
rem to launch/run Godot - the dock passes it automatically, this script cannot
rem guess it portably.
setlocal
for %%I in ("%~dp0..\..") do set "REPO=%%~fI"
set "HARNESS=%REPO%\harness"

set "PY=%HARNESS%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "EXTRA="
if defined GODOT_EXE set "EXTRA=--godot-exe "%GODOT_EXE%""

"%PY%" "%~dp0bootstrap.py" --loki-root "%HARNESS%" --project-dir "%REPO%" %EXTRA% --secret-file "%REPO%\.godot\loki_bridge.token"
