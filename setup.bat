@echo off
rem Loki one-time setup: private Python env, dependencies, optional skill libraries.
rem Safe to re-run. Needs Python 3.11+ and git on PATH (Ollama is optional).
setlocal
for %%I in ("%~dp0") do set "REPO=%%~fI"
set "HARNESS=%REPO%\addons\loki\harness"
set "DATA=%REPO%\harness_data"
set "VENV=%DATA%\.venv"

if not exist "%HARNESS%\loki.py" goto :noharness
echo [loki] repo %REPO%

if not exist "%VENV%\Scripts\python.exe" (
  echo [loki] creating a private Python environment (one time)
  python -m venv "%VENV%" || goto :err
)
echo [loki] installing dependencies
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
"%VENV%\Scripts\python.exe" -m pip install -r "%HARNESS%\requirements.txt" || goto :err

echo [loki] fetching the skill libraries (optional; needs git and internet)
if not exist "%DATA%\vendor" mkdir "%DATA%\vendor"
if not exist "%DATA%\vendor\ponytail" git clone --depth 1 https://github.com/DietrichGebert/ponytail.git "%DATA%\vendor\ponytail"
if not exist "%DATA%\vendor\ECC" git clone --depth 1 https://github.com/affaan-m/ECC.git "%DATA%\vendor\ECC"

if not exist "%DATA%\.env" (
  copy /y "%HARNESS%\.env.example" "%DATA%\.env" >nul
  echo [loki] created harness_data\.env - paste ONE key, or none at all: Loki works without any
)

"%VENV%\Scripts\python.exe" "tools\loki_doctor.py"

echo.
echo [loki] Done. Open this folder as a Godot project and enable Loki in
echo        Project ^> Project Settings ^> Plugins. The chat dock appears beside Scene.
exit /b 0

:noharness
echo [loki] Could not find addons\loki\harness\loki.py - run this from the Loki repo root.
exit /b 1
:err
echo [loki] Setup failed - see the messages above.
exit /b 1
