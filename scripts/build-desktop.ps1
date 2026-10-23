param([switch]$SkipUIBuild, [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskProject '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    $taskPython = [System.IO.Path]::GetFullPath((Join-Path $taskProject '../solidworks-automation-skill/.venv/Scripts/python.exe'))
}
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Run scripts/setup.ps1 to create the project Python environment first.' }
& $taskPython (Join-Path $PSScriptRoot 'verify-vendor.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned resource verification failed.' }
if (-not $SkipUIBuild) {
    Push-Location (Join-Path $taskProject 'ui')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'UI build failed.' }
    } finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath (Join-Path $taskProject 'ui/dist/index.html'))) { throw 'Build the UI before packaging.' }
& $taskPython -m PyInstaller --noconfirm --distpath (Join-Path $taskProject 'dist') --workpath (Join-Path $taskProject '.local/desktop-build') (Join-Path $PSScriptRoot 'CodexGouwu.spec')
if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed.' }
if (-not $NoShortcut) { & (Join-Path $PSScriptRoot 'install-desktop-shortcut.ps1') }
