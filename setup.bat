@echo off
rem Loki one-time setup for Windows: private Python env, dependencies, the Loki window,
rem optional skill libraries, and Start menu + Desktop shortcuts.
rem Safe to re-run. Needs Python 3.11+ (python.org; 3.13 recommended) and git on PATH.
setlocal
for %%I in ("%~dp0.") do set "REPO=%%~fI"
set "HARNESS=%REPO%\addons\loki\harness"
set "DATA=%REPO%\harness_data"
set "VENV=%DATA%\.venv"

if not exist "%HARNESS%\loki.py" goto :noharness
echo [loki] repo %REPO%

rem Pick a Python 3.11+: the py launcher's 3.13/3.12/3.11 first, then python on PATH.
set "PY="
for %%V in (3.13 3.12 3.11 3.14) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY goto :nopython

if not exist "%VENV%\Scripts\python.exe" (
  echo [loki] creating a private Python environment with %PY% ^(one time^)
  %PY% -m venv "%VENV%" || goto :err
)
echo [loki] installing dependencies
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
"%VENV%\Scripts\python.exe" -m pip install -r "%HARNESS%\requirements.txt" || goto :err

echo [loki] installing the Loki window (pywebview)
"%VENV%\Scripts\python.exe" -m pip install -r "%REPO%\app\requirements.txt" || echo [loki] pywebview did not install; Loki will open in your browser instead

echo [loki] fetching the skill libraries (optional; needs git and internet)
if not exist "%DATA%\vendor" mkdir "%DATA%\vendor"
if not exist "%DATA%\vendor\ponytail" git clone --depth 1 https://github.com/DietrichGebert/ponytail.git "%DATA%\vendor\ponytail"
if not exist "%DATA%\vendor\ECC" git clone --depth 1 https://github.com/affaan-m/ECC.git "%DATA%\vendor\ECC"

if not exist "%DATA%\.env" (
  copy /y "%HARNESS%\.env.example" "%DATA%\.env" >nul
  echo [loki] created harness_data\.env - paste ONE key, or none at all: Loki works without any
)

"%VENV%\Scripts\python.exe" "%REPO%\tools\loki_doctor.py"

echo [loki] creating the Loki shortcuts
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\tools\windows\make_shortcuts.ps1" -Repo "%REPO%" || echo [loki] could not create shortcuts; start Loki with Loki.cmd

echo.
echo [loki] Done. Open Loki from the Start menu or the Desktop shortcut (or run Loki.cmd).
echo        Game work: the Godot dock still works - open this folder in Godot 4.8.
exit /b 0

:noharness
echo [loki] Could not find addons\loki\harness\loki.py - run this from the Loki repo root.
exit /b 1
:nopython
echo [loki] Loki needs Python 3.11 or newer. Install Python 3.13 from python.org
echo        (tick "Add python.exe to PATH"), then run setup.bat again.
exit /b 1
:err
echo [loki] Setup failed - see the messages above.
exit /b 1
