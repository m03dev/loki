# Build the packaged Windows app: dist\Loki\Loki.exe, then zip it.
#   powershell -ExecutionPolicy Bypass -File tools\windows\build_exe.ps1
# Needs Python 3.11+ on PATH (py launcher is fine). Uses a throwaway build venv.
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Repo
$venv = Join-Path $Repo "build\venv"
if (-not (Test-Path "$venv\Scripts\python.exe")) { py -3 -m venv $venv }
$py = "$venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install pyinstaller -r engine\requirements.txt -r app\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
& $py -m PyInstaller packaging\loki.spec --noconfirm --distpath dist --workpath build\pyi
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
# Loki.exe is a windowed app, so its exit code is the reliable signal here.
$proc = Start-Process "dist\Loki\Loki.exe" -ArgumentList "--self-test" -Wait -PassThru -NoNewWindow
if ($proc.ExitCode -ne 0) { throw "Loki.exe --self-test failed" }
Compress-Archive -Path "dist\Loki" -DestinationPath "dist\Loki-windows.zip" -Force
Write-Host "[loki] built dist\Loki\Loki.exe and dist\Loki-windows.zip"
