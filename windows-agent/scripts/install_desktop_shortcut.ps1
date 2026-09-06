$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StartBat = Join-Path $Root "start.bat"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Start PC Control.lnk"

if (-not (Test-Path $StartBat)) {
    Write-Error "Could not find start.bat at $StartBat"
}

$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $StartBat
$Shortcut.WorkingDirectory = $Root
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Starts the PC Control (Laptop Remote) server."
$Shortcut.Save()

Write-Host "Desktop shortcut created:"
Write-Host $ShortcutPath
