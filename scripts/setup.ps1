param([string]$Python, [switch]$SkipUI)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskProject '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    $taskBootstrapArguments = @()
    if ($Python) {
        $taskBootstrap = $Python
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $taskBootstrap = 'py.exe'
        $taskBootstrapArguments = @('-3.12')
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        $taskBootstrap = 'python.exe'
    } else { throw 'Install 64-bit Python 3.12, or pass -Python with a Python 3.11+ executable path.' }
    & $taskBootstrap @taskBootstrapArguments -c "import struct, sys; assert sys.version_info >= (3, 11) and struct.calcsize('P') == 8, '64-bit Python 3.11+ is required'"
    if ($LASTEXITCODE -ne 0) { throw 'A compatible Python interpreter is required.' }
    & $taskBootstrap @taskBootstrapArguments -m venv (Join-Path $taskProject '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project .venv.' }
}
& $taskPython (Join-Path $PSScriptRoot 'verify-vendor.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned resource verification failed.' }
# Install only into this project environment; do not upgrade a shared Python.
$taskInstallTarget = $taskProject + '[cad,desktop]'
& $taskPython -m pip install --editable $taskInstallTarget
if ($LASTEXITCODE -ne 0) { throw 'Project dependency installation failed.' }
if (-not $SkipUI) {
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22.12+ with npm, then run setup again.' }
    Push-Location (Join-Path $taskProject 'ui')
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'UI dependency installation failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'UI build failed.' }
    } finally { Pop-Location }
}
Write-Output 'Setup complete. Run scripts/start-ui.ps1, or scripts/build-desktop.ps1 to package the desktop app.'
