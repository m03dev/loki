# Remove the items setup.bat created for LOKI: stop LOKI's own processes, then remove the
# start-at-login entry and the Desktop / Start menu shortcuts. Ollama and any other program
# (or another program's Startup entry) is never touched.
param(
  [Parameter(Mandatory = $true)][string]$Repo
)
$ErrorActionPreference = "Continue"

# 1. stop LOKI (only its own python processes: the app, the engine, a background job)
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'loki_app\.py|loki_bridge\.py|loki\.py --job' } |
  ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Write-Host "[loki] stopped pid $($_.ProcessId)" }
    catch { Write-Host "[loki] could not stop pid $($_.ProcessId)" }
  }

# 2. the start-at-login entry
$startup = [Environment]::GetFolderPath("Startup")
$vbs = Join-Path $startup "LOKI.vbs"
if (Test-Path $vbs) { Remove-Item -Force $vbs; Write-Host "[loki] removed $vbs" }

# 3. a legacy console launcher setup may have left in Startup (never another program's entry)
Get-ChildItem $startup -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -ne "LOKI.vbs" -and $_.Name -match 'loki' -and $_.Extension -match '^\.(lnk|cmd|bat)$' } |
  ForEach-Object { Remove-Item -Force $_.FullName; Write-Host "[loki] removed $($_.FullName)" }

# 4. the shortcuts setup made
foreach ($dir in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
  $lnk = Join-Path $dir "Loki.lnk"
  if (Test-Path $lnk) { Remove-Item -Force $lnk; Write-Host "[loki] removed $lnk" }
}
