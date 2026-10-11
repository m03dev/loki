@echo off
rem Loki bridge launcher. Starts the local agent server the dock talks to.
setlocal
for %%I in ("%~dp0..\..") do set "REPO=%%~fI"
set "HARNESS=%REPO%\harness"
set "PY=%HARNESS%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not defined GODOT_EXE (
  if exist "D:\Godot_v4.8-dev7_mono_win64\Godot_v4.8-dev7_mono_win64\Godot_v4.8-dev7_mono_win64.exe" (
    set "GODOT_EXE=D:\Godot_v4.8-dev7_mono_win64\Godot_v4.8-dev7_mono_win64\Godot_v4.8-dev7_mono_win64.exe"
  ) else (
    echo [loki] Set GODOT_EXE to your Godot 4 executable and retry.
    exit /b 1
  )
)
if defined LOKI_MCP_DIR set "PATH=%LOKI_MCP_DIR%;%PATH%"

rem free the port if a previous bridge is still listening
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8766" ^| findstr LISTENING') do (
  taskkill /f /pid %%p >nul 2>&1
)
"%PY%" "%~dp0loki_bridge.py" --loki-root "%HARNESS%" --project-dir "%REPO%" --godot-exe "%GODOT_EXE%" --secret-file "%REPO%\.godot\loki_bridge.token"
