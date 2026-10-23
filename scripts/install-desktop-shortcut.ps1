param([string]$Executable, [string]$Store)
$ErrorActionPreference = 'Stop'
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskAppName = 'codex' + [char]0x7684 + [char]0x6784 + [char]0x7269
if (-not $Executable) { $Executable = Join-Path $taskProject ('dist/' + $taskAppName + '/' + $taskAppName + '.exe') }
$taskExecutable = (Resolve-Path -LiteralPath $Executable).Path
$taskIconSource = Join-Path (Split-Path -Parent $taskExecutable) '_internal/resources/mechanical-design-app/ui/dist/brand/app.ico'
if (-not (Test-Path -LiteralPath $taskIconSource -PathType Leaf)) {
    $taskIconSource = Join-Path $taskProject 'ui/public/brand/app.ico'
}
if (-not (Test-Path -LiteralPath $taskIconSource -PathType Leaf)) { throw 'The application brand icon was not found.' }
# A content-specific .ico path avoids reusing the shell's cached icon for an
# executable rebuilt at the same location. Keep this file outside build output.
$taskIconHash = (Get-FileHash -LiteralPath $taskIconSource -Algorithm SHA256).Hash.ToLowerInvariant()
$taskIconDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CodexGouwu/icons'
New-Item -ItemType Directory -Path $taskIconDirectory -Force | Out-Null
$taskIconPath = Join-Path $taskIconDirectory ('app-' + $taskIconHash + '.ico')
if (-not (Test-Path -LiteralPath $taskIconPath -PathType Leaf) -or (Get-FileHash -LiteralPath $taskIconPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskIconHash) {
    Copy-Item -LiteralPath $taskIconSource -Destination $taskIconPath -Force
}
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
    $taskShortcut.IconLocation = $taskIconPath + ',0'
    $taskShortcut.WindowStyle = 7
    $taskShortcut.Save()
} finally { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskShell) }
# Notify Explorer without restarting it or removing other applications' caches.
if (-not ('CodexGouwu.ShortcutShell' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace CodexGouwu {
    public static class ShortcutShell {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        public static extern void SHChangeNotify(uint eventId, uint flags, string item, IntPtr other);
    }
}
'@
}
[CodexGouwu.ShortcutShell]::SHChangeNotify(0x00002000, 0x00001005, $taskShortcutPath, [IntPtr]::Zero)
[CodexGouwu.ShortcutShell]::SHChangeNotify(0x08000000, 0, $null, [IntPtr]::Zero)
Write-Output $taskShortcutPath
