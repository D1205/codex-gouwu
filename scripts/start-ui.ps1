param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskProject '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    $taskPython = [System.IO.Path]::GetFullPath((Join-Path $taskProject '../solidworks-automation-skill/.venv/Scripts/python.exe'))
}
$taskUrl = 'http://127.0.0.1:8777'
$taskLocal = Join-Path $taskProject '.local'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Run scripts/setup.ps1 to create the project Python environment first.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskProject 'ui/dist/index.html'))) { throw 'Build the UI first: cd ui; npm.cmd install; npm.cmd run build' }
New-Item -ItemType Directory -Path $taskLocal -Force | Out-Null
$taskReady = $false
try {
    $taskHealth = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 2
    if ($taskHealth.app -ne 'mechanical-design-app') { throw 'Port 8777 belongs to another application.' }
    $taskReady = $true
} catch {
    if ($_.Exception.Message -like '*belongs to another*') { throw }
}
if (-not $taskReady) {
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-m','mechanical_app.server','--port','8777') -WorkingDirectory $taskProject -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLocal 'server.stdout.log') -RedirectStandardError (Join-Path $taskLocal 'server.stderr.log') -PassThru
    @{pid=$taskProcess.Id; start_time=$taskProcess.StartTime.ToUniversalTime().ToString('o'); python=$taskPython} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskLocal 'server.json') -Encoding UTF8
    for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
        Start-Sleep -Milliseconds 300
        try {
            $taskHealth = Invoke-RestMethod -Uri "$taskUrl/api/health" -TimeoutSec 1
            if ($taskHealth.app -eq 'mechanical-design-app') { $taskReady=$true; break }
        } catch {}
        if ($taskProcess.HasExited) { break }
    }
}
if (-not $taskReady) { throw "Could not start the local design workbench. Inspect $taskLocal/server.stderr.log" }
Write-Output $taskUrl
if (-not $NoBrowser) { Start-Process $taskUrl }
