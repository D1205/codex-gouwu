param([string]$Executable, [string]$Store)
$ErrorActionPreference = 'Stop'
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskAppName = 'codex' + [char]0x7684 + [char]0x6784 + [char]0x7269
if (-not $Executable) { $Executable = Join-Path $taskProject ('dist/' + $taskAppName + '/' + $taskAppName + '.exe') }
$taskExecutable = (Resolve-Path -LiteralPath $Executable).Path
if (-not $Store -and (Test-Path -LiteralPath (Join-Path $taskProject 'results/integration') -PathType Container)) {
    # Preserve this checkout's existing records without embedding a build-machine
    # data path in the release. Only this local shortcut receives the argument.
    $Store = Join-Path $taskProject 'results/integration'
}
$taskDesktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if (-not $taskDesktop) { throw 'Windows did not provide the user Desktop directory.' }
$taskShortcutPath = Join-Path $taskDesktop ($taskAppName + '.lnk')
$taskShell = New-Object -ComObject WScript.Shell
try {
    $taskShortcut = $taskShell.CreateShortcut($taskShortcutPath)
    $taskShortcut.TargetPath = $taskExecutable
    $taskShortcut.Arguments = ''
    if ($Store) { $taskShortcut.Arguments = '--store "' + [System.IO.Path]::GetFullPath($Store) + '"' }
    $taskShortcut.WorkingDirectory = Split-Path -Parent $taskExecutable
    $taskShortcut.Description = $taskAppName
    # Use the same embedded multi-resolution brand icon as the packaged EXE.
    $taskShortcut.IconLocation = $taskExecutable + ',0'
    $taskShortcut.WindowStyle = 7
    $taskShortcut.Save()
} finally { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskShell) }
Write-Output $taskShortcutPath
