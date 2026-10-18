# LOKI's first-run setup on Windows (the installer's Start-menu shortcut runs this).
#
# Makes LOKI's private Python in %LOCALAPPDATA%\Loki once, without needing Python on the computer:
# downloads uv (Astral) into <data>\runtime, lets uv fetch a standalone Python 3.12 and makes
# <data>\.venv. Then it starts the launcher (loki_launch.py), which installs LOKI's packages and
# opens the window.
#
#   bootstrap.ps1          set up if needed, then open LOKI
#   bootstrap.ps1 -Setup   only set up (the installer runs this; also CI)
# Overrides: $env:LOKI_DATA, $env:LOKI_UV_VERSION, $env:LOKI_NO_DIALOGS=1.
param([switch]$Setup)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = if ($env:LOKI_DATA) { $env:LOKI_DATA } else { Join-Path $env:LOCALAPPDATA "Loki" }
$UvVersion = if ($env:LOKI_UV_VERSION) { $env:LOKI_UV_VERSION } else { "0.8.0" }
$Runtime = Join-Path $Data "runtime"
$Venv = Join-Path $Data ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$PyW = Join-Path $Venv "Scripts\pythonw.exe"
$Log = Join-Path $Data "app\bootstrap.log"
New-Item -ItemType Directory -Force -Path (Join-Path $Data "app"), $Runtime | Out-Null

function Say($msg) {
  Write-Host "[loki-setup] $msg"
  Add-Content -Path $Log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg)
}
function Fail($msg) {
  Say "FAILED: $msg"
  if (-not ($env:LOKI_NO_DIALOGS -or $env:CI)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("LOKI could not finish setting up: $msg`n`nWhat to do: check the internet connection and open LOKI again. The details are in $Log", "LOKI") | Out-Null
  }
  exit 1
}
function PythonOk {
  if (-not (Test-Path $Py)) { return $false }
  & $Py -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
  return ($LASTEXITCODE -eq 0)
}

# Session 30: an installer that carries its own Python (runtime\, tools/bundle_runtime.py) needs no
# download at all - the launcher makes the environment from it, offline, with no console window.
$Bundled = Join-Path $Here "runtime\python\python.exe"
$BundledW = Join-Path $Here "runtime\python\pythonw.exe"
if (Test-Path $Bundled) {
  $env:LOKI_INSTALL_DIR = $Here
  $Launcher = Join-Path $Data "launcher\loki_launch.py"
  if (-not (Test-Path $Launcher)) { $Launcher = Join-Path $Here "loki_launch.py" }
  $Seed = Join-Path $Here "seed"
  if ($Setup) {
    & $Bundled $Launcher --seed $Seed --check *>> $Log
    if ($LASTEXITCODE -ne 0) { Fail "LOKI's bundled Python did not set up (see $Log)" }
    Say "set up (bundled Python)"
    exit 0
  }
  $runner = if (Test-Path $BundledW) { $BundledW } else { $Bundled }
  Start-Process -FilePath $runner -ArgumentList @("`"$Launcher`"", "--seed", "`"$Seed`"") -WindowStyle Hidden
  exit 0
}

if (-not (PythonOk)) {
  $Uv = Join-Path $Runtime "uv.exe"
  if (-not (Test-Path $Uv)) {
    $arch = if ([Environment]::Is64BitOperatingSystem) { if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" } } else { Fail "32-bit Windows is not supported" }
    $target = "uv-$arch-pc-windows-msvc"
    $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$target.zip"
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("loki-uv-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    Say "downloading uv $UvVersion ($arch)"
    try {
      Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile "$tmp\uv.zip"
      Invoke-WebRequest -UseBasicParsing -Uri "$url.sha256" -OutFile "$tmp\uv.sha256"
    } catch { Fail "could not download uv from GitHub ($($_.Exception.Message))" }
    $want = ((Get-Content "$tmp\uv.sha256" -Raw).Trim() -split "\s+")[0].ToLower()
    $got = (Get-FileHash -Algorithm SHA256 "$tmp\uv.zip").Hash.ToLower()
    if (-not $want -or $want -ne $got) { Fail "the uv download did not match its checksum" }
    Expand-Archive -Path "$tmp\uv.zip" -DestinationPath $tmp -Force
    $found = Get-ChildItem -Path $tmp -Recurse -Filter uv.exe | Select-Object -First 1
    if (-not $found) { Fail "uv.exe was not in the download" }
    Copy-Item $found.FullName $Uv -Force
    Remove-Item -Recurse -Force $tmp
  }
  $env:UV_PYTHON_INSTALL_DIR = Join-Path $Runtime "python"
  Say "getting Python 3.12 (standalone, only for LOKI)"
  & $Uv python install 3.12 *>> $Log
  if ($LASTEXITCODE -ne 0) { Fail "could not download Python 3.12" }
  if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
  & $Uv venv --python 3.12 --seed $Venv *>> $Log
  if ($LASTEXITCODE -ne 0) { Fail "could not make LOKI's Python environment" }
  if (-not (PythonOk)) { Fail "LOKI's Python environment does not work" }
  Say ("Python ready: " + (& $Py --version 2>&1))
}

$Launcher = Join-Path $Data "launcher\loki_launch.py"   # a newer one a release brought
if (-not (Test-Path $Launcher)) { $Launcher = Join-Path $Here "loki_launch.py" }
$Seed = Join-Path $Here "seed"
if ($Setup) {
  & $Py $Launcher --seed $Seed --check *>> $Log
  if ($LASTEXITCODE -ne 0) { Fail "LOKI's packages did not install (see $Log)" }
  Say "set up"
  exit 0
}
$runner = if (Test-Path $PyW) { $PyW } else { $Py }
Start-Process -FilePath $runner -ArgumentList @("`"$Launcher`"", "--seed", "`"$Seed`"") -WindowStyle Hidden
