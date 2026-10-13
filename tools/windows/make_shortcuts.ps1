# Create the Loki shortcuts on Windows: Start menu and Desktop.
# setup.bat runs this at the end. The shortcuts start the standalone Loki app with
# Loki's private Python (pythonw.exe, so no console window appears).
param(
  [Parameter(Mandatory = $true)][string]$Repo
)
$ErrorActionPreference = "Stop"

$pythonw = Join-Path $Repo "harness_data\.venv\Scripts\pythonw.exe"
$app = Join-Path $Repo "app\loki_app.py"
if (-not (Test-Path $pythonw)) { throw "Loki's Python is missing: $pythonw (run setup.bat)" }
if (-not (Test-Path $app)) { throw "Loki app not found: $app" }

$shell = New-Object -ComObject WScript.Shell
$targets = @(
  (Join-Path ([Environment]::GetFolderPath("Programs")) "Loki.lnk"),
  (Join-Path ([Environment]::GetFolderPath("Desktop")) "Loki.lnk")
)
foreach ($path in $targets) {
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = $pythonw
  $link.Arguments = '"' + $app + '"'
  $link.WorkingDirectory = $Repo
  $link.Description = "Loki - desktop command center"
  $link.Save()
  Write-Host "[loki] shortcut: $path"
}
