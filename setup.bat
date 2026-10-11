@echo off
rem One-time setup: create the Python env, install deps, fetch agent skills.
setlocal
for %%I in ("%~dp0") do set "REPO=%%~fI"
set "HARNESS=%REPO%\harness"

echo [loki] Creating Python virtual environment...
python -m venv "%HARNESS%\.venv" || goto :err
call "%HARNESS%\.venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
python -m pip install -r "%HARNESS%\requirements.txt" || goto :err

echo [loki] Fetching agent skills (ponytail, ECC)...
if not exist "%HARNESS%\vendor" mkdir "%HARNESS%\vendor"
if not exist "%HARNESS%\vendor\ponytail" git clone --depth 1 https://github.com/DietrichGebert/ponytail.git "%HARNESS%\vendor\ponytail"
if not exist "%HARNESS%\vendor\ECC" git clone --depth 1 https://github.com/affaan-m/ECC.git "%HARNESS%\vendor\ECC"

echo.
echo [loki] Done. Set GODOT_EXE if your Godot is not in the default location, then open the project.
exit /b 0
:err
echo [loki] Setup failed.
exit /b 1
