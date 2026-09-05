param([switch]$Quiet)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Launcher = Join-Path $PSScriptRoot "launch_autostart.ps1"
$TaskName = "LaptopRemoteAgent"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Laptop Remote.lnk"

if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found. Run start.bat once before installing auto-start."
}

function Write-Status([string]$Message) {
    if (-not $Quiet) {
        Write-Host $Message
    }
}

function Install-LogonTask {
    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Launcher`"" `
        -WorkingDirectory $Root

    $LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $LogonTrigger.Delay = "PT20S"

    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -DontStopOnIdleEnd `
        -StartWhenAvailable `
        -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew
    $Settings.ExecutionTimeLimit = "PT0S"
    $Settings.Priority = 8

    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $LogonTrigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Starts Laptop Remote after you sign in to Windows." `
        -Force | Out-Null
}

function Install-StartupShortcut {
    if (-not (Test-Path $StartupDir)) {
        New-Item -ItemType Directory -Path $StartupDir -Force | Out-Null
    }
    $Wsh = New-Object -ComObject WScript.Shell
    $Shortcut = $Wsh.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Launcher`""
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.WindowStyle = 7
    $Shortcut.Description = "Starts Laptop Remote after you sign in."
    $Shortcut.Save()
}

$taskOk = $false
try {
    Install-LogonTask
    $taskOk = $true
} catch {
    Write-Status "Scheduled task could not be created ($($_.Exception.Message)). Using Startup folder instead."
}

if ($taskOk) {
    if (Test-Path $ShortcutPath) {
        Remove-Item $ShortcutPath -Force
    }
    Write-Status "Laptop Remote will start automatically after restart or when you sign in."
    exit 0
}

try {
    Install-StartupShortcut
} catch {
    Write-Error "Could not enable auto-start: $($_.Exception.Message)"
}

Write-Status "Laptop Remote will start automatically after restart or when you sign in."
