@echo off
rem Loki uninstall for Windows - the opposite of setup.bat.
rem Removes the start-at-login entry, the shortcuts and Loki's private Python environment,
rem and stops Loki if it is running. Your data is kept unless you pass --purge.
rem   uninstall.bat            keep harness_data (keys, memory, jobs, models)
rem   uninstall.bat --purge    also delete harness_data (your keys and memory - cannot be undone)
setlocal
for %%I in ("%~dp0.") do set "REPO=%%~fI"
set "DATA=%REPO%\harness_data"
set "VENV=%DATA%\.venv"
set "PURGE=0"
if /i "%~1"=="--purge" set "PURGE=1"

if not exist "%REPO%\engine\loki.py" (
  echo [loki] run this from the Loki repo root.
  exit /b 1
)

echo.
echo [loki] This will remove LOKI from this computer:
echo        - the "start at login" entry and the Desktop / Start menu shortcuts
echo        - LOKI's private Python environment (%VENV%)
if "%PURGE%"=="1" (
  echo        - ALL of harness_data: your keys, memory, jobs and models
) else (
  echo        - your data ^(keys, memory, jobs^) is KEPT; use --purge to delete it too
)
echo.
set /p "CONFIRM=Type yes to continue: "
if /i not "%CONFIRM%"=="yes" (
  echo [loki] nothing was changed.
  exit /b 0
)

echo [loki] stopping LOKI and removing the login entry + shortcuts
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\tools\windows\remove_loki_items.ps1" -Repo "%REPO%" || echo [loki] could not remove every item

echo [loki] removing LOKI's private Python environment
if exist "%VENV%" rmdir /s /q "%VENV%"

if "%PURGE%"=="1" (
  echo [loki] removing harness_data
  if exist "%DATA%" rmdir /s /q "%DATA%"
)

echo.
echo [loki] Done. LOKI is uninstalled. Ollama and this folder are left alone; delete the folder if you want.
exit /b 0
