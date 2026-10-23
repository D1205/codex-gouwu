$ErrorActionPreference = 'Stop'
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskMarker = Join-Path $taskProject '.local/server.json'
if (-not (Test-Path -LiteralPath $taskMarker)) { Write-Output 'No server owned by this launcher.'; exit }
$taskRecord = Get-Content -LiteralPath $taskMarker -Raw -Encoding UTF8 | ConvertFrom-Json
$taskProcess = Get-Process -Id $taskRecord.pid -ErrorAction SilentlyContinue
if ($null -eq $taskProcess) { Write-Output 'Server already stopped.'; exit }
if ($taskProcess.Path -ne $taskRecord.python -or $taskProcess.StartTime.ToUniversalTime().ToString('o') -ne $taskRecord.start_time) { throw 'Process identity changed; refusing to stop an unrelated process.' }
Stop-Process -Id $taskProcess.Id
Write-Output 'Local design workbench stopped. SolidWorks was left untouched.'
